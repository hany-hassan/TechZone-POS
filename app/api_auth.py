"""مصادقة المستخدمين، الجلسات، الإعدادات، القوالب، والنسخ الاحتياطي."""
import datetime
import hmac
import json
import os
import pathlib
import sqlite3
import sys
import time
from decimal import Decimal, ROUND_HALF_UP

import db
from api_common import (
    ApiError,
    _FALLBACK_JPEG,
    _LOGIN_ATTEMPTS,
    _STATE,
    _customer_debt_summary,
    _customers_enriched_cte,
    _fmt_money,
    _format_doc_seq,
    _int,
    _jpeg_to_pdf_bytes,
    _money,
    _upsert_customer,
    _validate_image_data_url,
    _win32_auto_paste_into_whatsapp,
    _win32_copy_pdf_to_clipboard,
    _find_whatsapp_hwnd,
)


class AuthSettingsMixin:
    # ---------------------------------------------------------- جلسة ومستخدمون
    def login_config(self):
        """إعدادات شاشة تسجيل الدخول العامة (اسم المحل والشعار وطريقة الدخول وقائمة أسماء الموظفين دون كشف الدور)."""
        with db.connect() as conn:
            st = self._settings(conn)
            rows = conn.execute("SELECT id, username, name, avatar FROM users ORDER BY id").fetchall()
            try:
                fail_state = json.loads(st.get("login_fail_state") or "{}")
                if not isinstance(fail_state, dict):
                    fail_state = {}
            except Exception:
                fail_state = {}
            info = fail_state.get("pin_only", {}) if isinstance(fail_state, dict) else {}
            try:
                locked_until = float(info.get("locked_until", 0.0) or 0.0)
            except Exception:
                locked_until = 0.0
            return {
                "store_name": (st.get("store_name") or "تك زون للإلكترونيات").strip() or "تك زون للإلكترونيات",
                "store_address": st.get("store_address") or "",
                "store_phone": st.get("store_phone") or "",
                "receipt_logo": st.get("receipt_logo") or "",
                "login_mode": st.get("login_mode") or "pin_only",
                "default_start_page": st.get("default_start_page") or "pos",
                "default_start_mode": st.get("default_start_mode") or "window",
                "os_default_theme": st.get("os_default_theme") or "dark",
                "login_locked_until": locked_until,
                "users": [{"id": r["id"], "username": r["username"], "name": r["name"], "avatar": r["avatar"]} for r in rows],
            }

    def users(self):
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT id, username, name, role, permissions, card_size, start_page, start_mode, theme_mode, avatar, created_at FROM users ORDER BY id"
            ).fetchall()
            out = []
            for r in rows:
                d = dict(r)
                d["permissions"] = db.parse_user_perms(d["role"], d.get("permissions"))
                out.append(d)
            return out

    def _row_to_user_dict(self, row) -> dict:
        keys = row.keys()
        return {
            "id": row["id"],
            "username": row["username"],
            "name": row["name"],
            "role": row["role"],
            "permissions": db.parse_user_perms(row["role"], row["permissions"] if "permissions" in keys else None),
            "card_size": row["card_size"] if "card_size" in keys else None,
            "wallpaper": row["wallpaper"] if "wallpaper" in keys else None,
            "custom_bg": row["custom_bg"] if "custom_bg" in keys else None,
            "accent_color": row["accent_color"] if "accent_color" in keys else None,
            "desktop_layout": row["desktop_layout"] if "desktop_layout" in keys else None,
            "start_page": row["start_page"] if "start_page" in keys else None,
            "start_mode": row["start_mode"] if "start_mode" in keys else None,
            "theme_mode": row["theme_mode"] if "theme_mode" in keys else None,
            "avatar": row["avatar"] if "avatar" in keys else None,
        }

    def user_pref_save(
        self,
        card_size=None,
        wallpaper=None,
        custom_bg=None,
        accent_color=None,
        desktop_layout=None,
        start_page=None,
        start_mode=None,
        theme_mode=None,
        reset_theme=False,
    ):
        """حفظ تفضيلات العرض والفتح الخاصة بالمستخدم الحالي في قاعدة البيانات بشكل دائم لكل مستخدم."""
        u = self._user()
        uid = u["id"]
        valid_pages = {"", "pos", "sales_quotes", "inventory", "customers", "repair", "history", "buy_used", "reports", "settings", "receipt", "desktop"}
        valid_modes = {"", "window", "maximized", "direct"}
        valid_themes = {"", "light", "dark"}
        with db.connect() as conn:
            if reset_theme:
                conn.execute(
                    "UPDATE users SET wallpaper=NULL, custom_bg=NULL, accent_color=NULL, theme_mode=NULL WHERE id=?",
                    (uid,),
                )
            if card_size not in (None, ""):
                cs = _int(card_size, 0)
                if cs < 110 or cs > 360:
                    raise ApiError("حجم البلوك يجب أن يكون بين 110 و 360")
                conn.execute("UPDATE users SET card_size=? WHERE id=?", (cs, uid))
            if wallpaper is not None:
                wp = str(wallpaper).strip()[:60] or None
                conn.execute("UPDATE users SET wallpaper=? WHERE id=?", (wp, uid))
            if custom_bg is not None:
                bg = str(custom_bg).strip()
                if bg == "":
                    conn.execute("UPDATE users SET custom_bg=NULL WHERE id=?", (uid,))
                else:
                    _validate_image_data_url(bg, 950 * 1024)
                    conn.execute("UPDATE users SET custom_bg=?, wallpaper='custom' WHERE id=?", (bg, uid))
            if accent_color is not None:
                ac = str(accent_color).strip()[:20] or None
                conn.execute("UPDATE users SET accent_color=? WHERE id=?", (ac, uid))
            if desktop_layout is not None:
                if isinstance(desktop_layout, dict):
                    dl = json.dumps(desktop_layout, ensure_ascii=False) if desktop_layout else None
                else:
                    dl = str(desktop_layout).strip() or None
                conn.execute("UPDATE users SET desktop_layout=? WHERE id=?", (dl, uid))
            if start_page is not None:
                sp = str(start_page).strip()
                if sp not in valid_pages:
                    raise ApiError("الصفحة الافتراضية المختارة غير صالحة")
                conn.execute("UPDATE users SET start_page=? WHERE id=?", (sp or None, uid))
            if start_mode is not None:
                sm = str(start_mode).strip()
                if sm not in valid_modes:
                    raise ApiError("وضع فتح الصفحة غير صالح")
                conn.execute("UPDATE users SET start_mode=? WHERE id=?", (sm or None, uid))
            if theme_mode is not None:
                tm = str(theme_mode).strip()
                if tm not in valid_themes:
                    raise ApiError("وضع المظهر غير صالح")
                conn.execute("UPDATE users SET theme_mode=? WHERE id=?", (tm or None, uid))
            conn.commit()
            row = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
            if row:
                _STATE["user"] = self._row_to_user_dict(row)
        return {
            "card_size": _STATE["user"].get("card_size"),
            "wallpaper": _STATE["user"].get("wallpaper"),
            "custom_bg": _STATE["user"].get("custom_bg"),
            "accent_color": _STATE["user"].get("accent_color"),
            "desktop_layout": _STATE["user"].get("desktop_layout"),
            "start_page": _STATE["user"].get("start_page"),
            "start_mode": _STATE["user"].get("start_mode"),
            "theme_mode": _STATE["user"].get("theme_mode"),
            "avatar": _STATE["user"].get("avatar"),
        }

    def profile_save(
        self,
        name=None,
        username=None,
        current_pin=None,
        new_pin=None,
        avatar=None,
        start_page=None,
        start_mode=None,
        theme_mode=None,
        card_size=None,
        accent_color=None,
        wallpaper=None,
        custom_bg=None,
        pin=None,
    ):
        """تحديث الملف الشخصي للموظف الحالي (الاسم، معرف الدخول، الصورة الشخصية، كلمة السر/الرمز السري، وإعدادات الفتح والمظهر)."""
        u = self._user()
        uid = u["id"]
        if new_pin is None and pin is not None:
            new_pin = pin
        with db.connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
            if not row:
                raise ApiError("المستخدم غير موجود")

            final_name = (name if name is not None else row["name"]).strip()
            final_username = (username if username is not None else row["username"]).strip()
            if not final_name or not final_username:
                raise ApiError("الاسم الكامل ومعرف الدخول مطلوبان")

            dup_u = conn.execute("SELECT id FROM users WHERE username=? AND id!=?", (final_username, uid)).fetchone()
            if dup_u:
                raise ApiError("معرف الدخول مسجل لموظف آخر مسبقاً")

            if new_pin is not None and str(new_pin).strip() != "":
                np = str(new_pin).strip()
                if len(np) < 4 or len(np) > 24:
                    raise ApiError("كلمة المرور / الرمز السري الجديد يجب أن يتكون من 4 خانات على الأقل")
                if current_pin is not None and str(current_pin).strip() != "":
                    cp = str(current_pin).strip()
                    if not hmac.compare_digest(db.hash_pin(cp, row["pin_salt"]), row["pin_hash"]):
                        raise ApiError("الرمز السري الحالي غير صحيح")
                for other in conn.execute("SELECT id, pin_salt, pin_hash FROM users WHERE id!=?", (uid,)).fetchall():
                    if hmac.compare_digest(db.hash_pin(np, other["pin_salt"]), other["pin_hash"]):
                        raise ApiError("الرمز السري الجديد مستخدم بالفعل لموظف آخر — يرجى اختيار رمز فريد")
                salt = os.urandom(16)
                conn.execute(
                    "UPDATE users SET pin_salt=?, pin_hash=? WHERE id=?",
                    (salt, db.hash_pin(np, salt), uid),
                )

            if avatar is not None:
                av = str(avatar).strip()
                if av == "":
                    conn.execute("UPDATE users SET avatar=NULL WHERE id=?", (uid,))
                else:
                    _validate_image_data_url(av, 450 * 1024)
                    conn.execute("UPDATE users SET avatar=? WHERE id=?", (av, uid))

            conn.execute(
                "UPDATE users SET name=?, username=? WHERE id=?",
                (final_name, final_username, uid),
            )
            conn.commit()

        if any(x is not None for x in (start_page, start_mode, theme_mode, card_size, accent_color, wallpaper, custom_bg)):
            self.user_pref_save(
                card_size=card_size,
                wallpaper=wallpaper,
                custom_bg=custom_bg,
                accent_color=accent_color,
                start_page=start_page,
                start_mode=start_mode,
                theme_mode=theme_mode,
            )

        with db.connect() as conn:
            st = self._settings(conn)
            updated = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
            _STATE["user"] = self._row_to_user_dict(updated)
            _STATE["user"]["effective_start_page"] = _STATE["user"].get("start_page") or st.get("default_start_page") or "pos"
            _STATE["user"]["effective_start_mode"] = _STATE["user"].get("start_mode") or st.get("default_start_mode") or "window"
            _STATE["user"]["force_change_pin"] = bool(
                updated["role"] == "admin" and hmac.compare_digest(db.hash_pin("1234", updated["pin_salt"]), updated["pin_hash"])
            )
        return dict(_STATE["user"])

    def user_save(self, username, name, role="cashier", pin=None, permissions=None, id=None, start_page=None, start_mode=None, avatar=None):
        self._perm("settings_manage")
        username = (username or "").strip()
        name = (name or "").strip()
        if not username or not name:
            raise ApiError("اسم الدخول والاسم الكامل مطلوبان")
        if role not in ("admin", "cashier"):
            raise ApiError("دور المستخدم غير صالح")
        if pin is not None and str(pin).strip() != "":
            pin = str(pin).strip()
            if len(pin) < 4 or len(pin) > 24:
                raise ApiError("الرمز السري / كلمة المرور يجب أن يتكون من 4 خانات على الأقل")
        else:
            pin = None

        valid_pages = {"", "pos", "sales_quotes", "inventory", "customers", "repair", "history", "buy_used", "reports", "settings", "receipt", "desktop"}
        valid_modes = {"", "window", "maximized", "direct"}
        sp_val = str(start_page).strip() if start_page is not None else None
        if sp_val is not None and sp_val not in valid_pages:
            sp_val = None
        sm_val = str(start_mode).strip() if start_mode is not None else None
        if sm_val is not None and sm_val not in valid_modes:
            sm_val = None

        perms_dict = dict(db.ALL_ADMIN_PERMS) if role == "admin" else dict(db.DEFAULT_CASHIER_PERMS)
        if role != "admin" and isinstance(permissions, dict):
            for k in perms_dict:
                if k in permissions:
                    perms_dict[k] = bool(permissions[k])
        perms_json = json.dumps(perms_dict, ensure_ascii=False)

        with db.connect() as conn:
            # التأكد من عدم تكرار الرمز السري بين المستخدمين لتمييز كل مستخدم تلقائياً من الرمز السري فقط
            if pin:
                target_uid = _int(id) if id else 0
                for other in conn.execute("SELECT id, name, pin_salt, pin_hash FROM users").fetchall():
                    if other["id"] == target_uid:
                        continue
                    if hmac.compare_digest(db.hash_pin(pin, other["pin_salt"]), other["pin_hash"]):
                        raise ApiError("الرمز السري مستخدم بالفعل لموظف آخر — يجب أن يكون لكل مستخدم رمز سري فريد")
            try:
                if id:
                    uid = _int(id)
                    cur_u = conn.execute("SELECT start_page, start_mode, avatar FROM users WHERE id=?", (uid,)).fetchone()
                    final_sp = (sp_val or None) if start_page is not None else (cur_u["start_page"] if cur_u else None)
                    final_sm = (sm_val or None) if start_mode is not None else (cur_u["start_mode"] if cur_u else None)
                    final_av = (str(avatar).strip() or None) if avatar is not None else (cur_u["avatar"] if cur_u else None)
                    if final_av:
                        _validate_image_data_url(final_av, 450 * 1024)
                    if pin:
                        salt = os.urandom(16)
                        conn.execute(
                            "UPDATE users SET username=?, name=?, role=?, pin_salt=?, pin_hash=?, permissions=?, start_page=?, start_mode=?, avatar=? WHERE id=?",
                            (username, name, role, salt, db.hash_pin(pin, salt), perms_json, final_sp, final_sm, final_av, uid),
                        )
                    else:
                        conn.execute(
                            "UPDATE users SET username=?, name=?, role=?, permissions=?, start_page=?, start_mode=?, avatar=? WHERE id=?",
                            (username, name, role, perms_json, final_sp, final_sm, final_av, uid),
                        )
                    if _STATE["user"] and _STATE["user"]["id"] == uid:
                        row = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
                        if row:
                            _STATE["user"] = self._row_to_user_dict(row)
                    return {"id": uid}
                else:
                    if not pin:
                        raise ApiError("الرمز السري (4 أرقام) مطلوب للمستخدم الجديد")
                    salt = os.urandom(16)
                    cur = conn.execute(
                        "INSERT INTO users(username, name, role, pin_salt, pin_hash, permissions, start_page, start_mode, avatar, created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (username, name, role, salt, db.hash_pin(pin, salt), perms_json, sp_val or None, sm_val or None, (str(avatar).strip() or None) if avatar else None, db.now()),
                    )
                    return {"id": cur.lastrowid}
            except sqlite3.IntegrityError:
                raise ApiError("اسم الدخول مسجل مسبقاً")

    def user_delete(self, id):
        u = self._perm("settings_manage")
        uid = _int(id)
        if uid == u["id"]:
            raise ApiError("لا يمكنك حذف حسابك الحالي أثناء الجلسة")
        with db.connect() as conn:
            target = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
            if not target:
                raise ApiError("المستخدم غير موجود")
            if target["role"] == "admin":
                admins = conn.execute("SELECT COUNT(*) c FROM users WHERE role='admin'").fetchone()["c"]
                if admins <= 1:
                    raise ApiError("لا يمكن حذف المدير الوحيد في النظام")
            try:
                conn.execute("UPDATE sales SET modified_by=NULL WHERE modified_by=?", (uid,))
                conn.execute("DELETE FROM users WHERE id=?", (uid,))
            except sqlite3.IntegrityError:
                raise ApiError("لا يمكن حذف مستخدم مرتبط بعمليات بيع أو صيانة سابقة")
            return True

    def login(self, username=None, pin=None):
        """تسجيل الدخول: يدعم الدخول بالرمز السري فقط (يكتشف المستخدم ودوره مدير/كاشير تلقائياً) أو باسم المستخدم والرمز السري."""
        pin = str(pin or "").strip()
        username = str(username or "").strip()
        if len(pin) < 4:
            raise ApiError("اسم المستخدم أو الرمز السري غير صحيح")
        lock_key = username.lower() if username else "pin_only"
        now_ts = time.time()

        with db.connect() as conn:
            st = self._settings(conn)
            max_attempts = max(1, _int(st.get("login_max_attempts", 5), 5))
            lock_minutes = max(1, _int(st.get("login_lockout_minutes", 10), 10))
            try:
                fail_state = json.loads(st.get("login_fail_state") or "{}")
                if not isinstance(fail_state, dict):
                    fail_state = {}
            except Exception:
                fail_state = {}
            info = fail_state.get(lock_key, {"count": 0, "locked_until": 0.0})
            try:
                info["locked_until"] = float(info.get("locked_until", 0.0) or 0.0)
            except Exception:
                info["locked_until"] = 0.0
            info["count"] = int(info.get("count", 0) or 0)

            if info["locked_until"] > now_ts:
                remain = int(info["locked_until"] - now_ts)
                mins = max(1, (remain + 59) // 60)
                raise ApiError(f"تم تجاوز عدد المحاولات المسموح. حاول بعد {mins} دقيقة [LOCKED:{remain}]")

            if info["locked_until"] and info["locked_until"] <= now_ts:
                info = {"count": 0, "locked_until": 0.0}
                fail_state[lock_key] = info

            try:
                if username:
                    row = conn.execute("SELECT * FROM users WHERE username=? OR name=?", (username, username)).fetchone()
                    if not row:
                        raise ApiError("اسم المستخدم أو الرمز السري غير صحيح")
                    expect = db.hash_pin(pin, row["pin_salt"])
                    if not hmac.compare_digest(expect, row["pin_hash"]):
                        raise ApiError("اسم المستخدم أو الرمز السري غير صحيح")
                else:
                    rows = conn.execute("SELECT * FROM users ORDER BY id").fetchall()
                    matched = None
                    for r in rows:
                        expect = db.hash_pin(pin, r["pin_salt"])
                        if hmac.compare_digest(expect, r["pin_hash"]):
                            matched = r
                            break
                    if not matched:
                        raise ApiError("الرمز السري غير صحيح")
                    row = matched
            except ApiError:
                info["count"] = info.get("count", 0) + 1
                if info["count"] >= max_attempts:
                    info["locked_until"] = now_ts + (lock_minutes * 60)
                    info["count"] = 0
                fail_state[lock_key] = info
                conn.execute(
                    "INSERT INTO settings(key, value) VALUES(?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    ("login_fail_state", json.dumps(fail_state)),
                )
                self._settings_cache = None
                conn.commit()
                if info.get("locked_until", 0) > now_ts:
                    mins = max(1, (int(info["locked_until"] - now_ts) + 59) // 60)
                    raise ApiError(f"تم تجاوز عدد المحاولات المسموح. حاول بعد {mins} دقيقة [LOCKED:{int(info['locked_until'] - now_ts)}]")
                raise

            # نجاح: إعادة تعيين
            fail_state[lock_key] = {"count": 0, "locked_until": 0.0}
            conn.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                ("login_fail_state", json.dumps(fail_state)),
            )
            # إلغاء أي إقفال سابق
            conn.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                ("login_locked_until", "0"),
            )
            self._settings_cache = None
            _STATE["user"] = self._row_to_user_dict(row)
            out = dict(_STATE["user"])
            out["effective_start_page"] = out.get("start_page") or st.get("default_start_page") or "pos"
            out["effective_start_mode"] = out.get("start_mode") or st.get("default_start_mode") or "window"
            # فحص أمني: هل الحساب الإداري ما زال يستخدم الرمز السري الافتراضي 1234؟
            if row["role"] == "admin" and hmac.compare_digest(db.hash_pin("1234", row["pin_salt"]), row["pin_hash"]):
                out["force_change_pin"] = True
                out["default_pin_warning"] = "تنبيه أمني: الحساب الإداري يستخدم الرمز الافتراضي (1234). يرجى تعيين رمز جديد لحماية متجرك."
            else:
                out["force_change_pin"] = False
            return out

    def session(self):
        if _STATE["user"]:
            with db.connect() as conn:
                st = self._settings(conn)
                row = conn.execute("SELECT * FROM users WHERE id=?", (_STATE["user"]["id"],)).fetchone()
                if row:
                    _STATE["user"] = self._row_to_user_dict(row)
                    _STATE["user"]["effective_start_page"] = _STATE["user"].get("start_page") or st.get("default_start_page") or "pos"
                    _STATE["user"]["effective_start_mode"] = _STATE["user"].get("start_mode") or st.get("default_start_mode") or "window"
                    _STATE["user"]["force_change_pin"] = bool(row["role"] == "admin" and hmac.compare_digest(db.hash_pin("1234", row["pin_salt"]), row["pin_hash"]))
        return {"user": _STATE["user"]}

    def logout(self):
        _STATE["user"] = None
        return True

    # ---------------------------------------------------------- إعدادات
    def settings(self):
        self._perm("settings_manage")
        with db.connect() as conn:
            return self._settings(conn)

    def settings_save(self, **kv):
        self._perm("settings_manage")
        allowed = {"store_name", "store_address", "store_phone", "currency", "tax_enabled", "tax_rate",
                   "pos_card_size", "os_default_wallpaper", "os_default_custom_bg", "os_default_accent", "os_default_layout",
                   "os_default_theme", "login_mode", "default_start_page", "default_start_mode",
                    "store_email", "store_cr", "store_vat", "receipt_thanks", "receipt_footer",
                    "receipt_logo", "receipt_show_logo", "receipt_show_barcode",
                    "receipt_show_tax", "receipt_show_payments", "whatsapp_send_enabled",
                    "login_max_attempts", "login_lockout_minutes",
                    "template_a4_config", "template_pos_config", "pos_categories_config"}
        show = {"tax_enabled", "receipt_show_logo", "receipt_show_barcode", "receipt_show_tax", "receipt_show_payments", "whatsapp_send_enabled"}
        valid_login_modes = {"pin_only", "select_user_pin", "username_password"}
        valid_start_pages = {"pos", "sales_quotes", "inventory", "customers", "repair", "history", "buy_used", "reports", "settings", "receipt", "desktop"}
        valid_start_modes = {"window", "maximized", "direct"}
        with db.connect() as conn:
            for k, v in kv.items():
                if k not in allowed or v is None:
                    continue
                s = str(v)
                if s == "" and k not in show and k not in ("os_default_custom_bg", "os_default_layout", "receipt_logo", "pos_categories_config"):
                    continue
                if k in show:
                    if s not in ("0", "1"):
                        raise ApiError("قيمة عرض غير صالحة (استخدم 0 أو 1)")
                elif k == "login_mode":
                    if s not in valid_login_modes:
                        raise ApiError("طريقة تسجيل الدخول غير صالحة")
                elif k == "default_start_page":
                    if s not in valid_start_pages:
                        raise ApiError("الصفحة الافتراضية غير صالحة")
                elif k == "default_start_mode":
                    if s not in valid_start_modes:
                        raise ApiError("وضع فتح الصفحة الافتراضية غير صالح")
                elif k == "os_default_theme":
                    if s not in ("light", "dark"):
                        raise ApiError("وضع المظهر الافتراضي غير صالح")
                elif k == "login_max_attempts":
                    n = _int(s, 5)
                    if n < 1 or n > 20:
                        raise ApiError("عدد المحاولات يجب أن يكون بين 1 و 20")
                    s = str(n)
                elif k == "login_lockout_minutes":
                    n = _int(s, 10)
                    if n < 1 or n > 1440:
                        raise ApiError("مدة الإقفال يجب أن تكون بين 1 و 1440 دقيقة")
                    s = str(n)
                elif k == "pos_card_size":
                    cs = _int(s, 200)
                    if cs < 110 or cs > 360:
                        raise ApiError("حجم البلوك الافتراضي يجب أن يكون بين 110 و 360")
                    s = str(cs)
                elif k == "receipt_logo" and s != "":
                    _validate_image_data_url(s, 200 * 1024)
                conn.execute(
                    "INSERT INTO settings(key, value) VALUES(?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (k, s),
                )
            self._settings_cache = None
            return self._settings(conn)

    def db_backup(self, reason="manual"):
        """إنشاء نسخة احتياطية فورية لقاعدة البيانات (للمدير)."""
        self._perm("settings_manage")
        path = db.backup_database(str(reason or "manual"))
        if not path:
            raise ApiError("فشل إنشاء النسخة الاحتياطية لقاعدة البيانات")
        stat = path.stat()
        return {
            "name": path.name,
            "path": str(path),
            "size_bytes": stat.st_size,
            "size_kb": round(stat.st_size / 1024, 1),
            "created_at": datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        }

    def backups_list(self):
        """استعراض النسخ الاحتياطية المتوفرة (للمدير)."""
        self._perm("settings_manage")
        return db.list_backups()

    def db_restore(self, backup_name):
        """استرجاع قاعدة البيانات من نسخة احتياطية محددة مع أخذ نسخة أمان مسبقة (للمدير)."""
        self._perm("settings_manage")
        if not backup_name:
            raise ApiError("اسم ملف النسخة الاحتياطية مطلوب")
        try:
            res = db.restore_database(str(backup_name))
            self._settings_cache = None
            return res
        except ValueError as ve:
            raise ApiError(str(ve))
        except Exception as e:
            raise ApiError(f"تعذر استرجاع النسخة الاحتياطية: {e}")

    def _load_payment_methods(self, conn):
        cache = getattr(self, "_pm_cache", None)
        if cache is not None:
            return cache
        st = self._settings(conn)
        result = list(db.DEFAULT_PAYMENT_METHODS)
        if st.get("custom_payment_methods"):
            try:
                loaded = json.loads(st["custom_payment_methods"])
                if isinstance(loaded, list) and loaded:
                    result = loaded
            except Exception:
                pass
        self._pm_cache = result
        return result

    def payment_methods_get(self):
        """جلب قائمة طرق وأنظمة الدفع المخصصة."""
        self._user()
        with db.connect() as conn:
            return self._load_payment_methods(conn)

    def payment_methods_save(self, methods=None):
        """حفظ قائمة طرق وأنظمة الدفع المخصصة (نقدي، محافظ، خطط دفعات مقدمة وأقساط)."""
        self._user()
        if not (self._has_perm("pos_sell") or self._has_perm("settings_manage")):
            raise ApiError("ليست لديك صلاحية لتعديل طرق الدفع")
        cleaned = []
        for idx, m in enumerate(methods or []):
            if isinstance(m, str):
                nm = m.strip()
                if nm:
                    cleaned.append({"id": f"pm_{idx+1}", "name": nm, "base_type": "cash"})
            elif isinstance(m, dict):
                nm = str(m.get("name") or "").strip()
                if nm:
                    bt = "wallet" if m.get("base_type") == "wallet" else "cash"
                    mid = str(m.get("id") or f"pm_{idx+1}").strip()
                    cleaned.append({"id": mid, "name": nm, "base_type": bt})
        if not cleaned:
            cleaned = list(db.DEFAULT_PAYMENT_METHODS)
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO settings(key, value) VALUES('custom_payment_methods', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (json.dumps(cleaned, ensure_ascii=False),),
            )
            self._settings_cache = None
            self._pm_cache = None
            return cleaned

    def _load_templates(self, conn):
        cache = getattr(self, "_tpl_cache", None)
        st = self._settings(conn)
        if cache is None:
            a4 = dict(db.DEFAULT_A4_TEMPLATE)
            pos = dict(db.DEFAULT_POS_TEMPLATE)
            if st.get("template_a4_config"):
                try:
                    loaded_a4 = json.loads(st["template_a4_config"])
                    if isinstance(loaded_a4, dict):
                        a4.update(loaded_a4)
                except Exception:
                    pass
            if st.get("template_pos_config"):
                try:
                    loaded_pos = json.loads(st["template_pos_config"])
                    if isinstance(loaded_pos, dict):
                        pos.update(loaded_pos)
                except Exception:
                    pass
            cache = {"a4": a4, "pos": pos}
            self._tpl_cache = cache
        else:
            a4 = dict(cache["a4"])
            pos = dict(cache["pos"])
        next_sale_seq = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM sales").fetchone()[0]
        next_quote_seq = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM quotations").fetchone()[0]
        inv_pref = a4.get("invoice_prefix") or "الفات/2026/"
        q_pref = a4.get("quote_prefix") or "ع.س/2026/"
        return {
            "a4": a4,
            "pos": pos,
            "payment_methods": self._load_payment_methods(conn),
            "next_invoice_no": _format_doc_seq(inv_pref, next_sale_seq),
            "next_quote_no": _format_doc_seq(q_pref, next_quote_seq),
            "next_sale_seq": next_sale_seq,
            "next_quote_seq": next_quote_seq,
        }

    def templates_get(self):
        """جلب إعدادات قوالب الفواتير (قالب A4 للمبيعات وعروض الأسعار + قالب إيصال الكاشير الحراري 80mm/58mm)."""
        self._user()
        with db.connect() as conn:
            return self._load_templates(conn)

    def templates_save(self, a4=None, pos=None, reset_a4=False, reset_pos=False, sync_receipt_settings=True):
        """حفظ تخصيص قوالب الفواتير (شكل الفاتورة A4، الألوان، الشعار، البيانات، وقالب الكاشير الحراري وجميع إيصالات البرنامج)."""
        self._perm("settings_manage")
        with db.connect() as conn:
            cur = self._load_templates(conn)
            new_a4 = dict(db.DEFAULT_A4_TEMPLATE) if reset_a4 else cur["a4"]
            new_pos = dict(db.DEFAULT_POS_TEMPLATE) if reset_pos else cur["pos"]
            if isinstance(a4, dict) and not reset_a4:
                logo = a4.get("company_logo")
                if logo is not None and logo != "":
                    logo_s = str(logo).strip()
                    _validate_image_data_url(logo_s, 500 * 1024)
                for k in db.DEFAULT_A4_TEMPLATE:
                    if k in a4:
                        new_a4[k] = a4[k]
            if isinstance(pos, dict) and not reset_pos:
                for k in db.DEFAULT_POS_TEMPLATE:
                    if k in pos:
                        new_pos[k] = pos[k]
            conn.execute(
                "INSERT INTO settings(key, value) VALUES('template_a4_config', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (json.dumps(new_a4, ensure_ascii=False),),
            )
            conn.execute(
                "INSERT INTO settings(key, value) VALUES('template_pos_config', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (json.dumps(new_pos, ensure_ascii=False),),
            )
            if sync_receipt_settings and isinstance(pos, dict) and not reset_pos:
                sync_pairs = [
                    ("receipt_thanks", str(new_pos.get("thanks_text") or "شكراً لزيارتكم")),
                    ("receipt_footer", str(new_pos.get("footer_text") or "يرجى الاحتفاظ بالإيصال للاستبدال خلال 14 يوماً")),
                    ("receipt_show_logo", "1" if new_pos.get("show_logo", True) else "0"),
                    ("receipt_show_barcode", "1" if new_pos.get("show_barcode", True) else "0"),
                    ("receipt_show_tax", "1" if new_pos.get("show_tax", True) else "0"),
                    ("receipt_show_payments", "1" if new_pos.get("show_payments", True) else "0"),
                ]
                for sk, sv in sync_pairs:
                    conn.execute(
                        "INSERT INTO settings(key, value) VALUES(?, ?) "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (sk, sv),
                    )
            self._tpl_cache = None
            self._settings_cache = None
            return self._load_templates(conn)

