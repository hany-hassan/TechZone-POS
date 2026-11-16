"""وضع المالك الرئيسي (Owner Mode): المصادقة، مفتاح الاسترداد، تصفير رمز المدير، وسجل التدقيق."""
import hmac
import json
import os
import re
import secrets
import time

import db
from api_common import ApiError, OWNER_SESSION_TTL, _STATE, _int
from modules_map import MODULE_REQUIRES
from profiles import BUSINESS_PROFILES, DEFAULT_LABELS, LABEL_KEYS

OWNER_LOCK_MAX_ATTEMPTS = 5
OWNER_LOCK_SECONDS = 15 * 60
_RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_WEAK_PINS = {"1234", "0000", "1111"}
_ICON_RE = re.compile(r"^[a-z0-9_]{1,40}$")
_COLOR_RE = re.compile(r"^(#[0-9a-fA-F]{3,8}|linear-gradient\([#0-9a-zA-Z,.%() -]{1,120}\))$")
_PARAMS_RE = re.compile(r"^[A-Za-z0-9_=&.-]{0,120}$")


def _validate_module_fields(title, icon, color, params="", perm_keys=None):
    t = str(title or "").strip()
    if not t or len(t) > 60:
        raise ApiError("اسم القسم مطلوب (بحد أقصى 60 حرفاً)")
    ic = str(icon or "").strip()
    if not _ICON_RE.match(ic):
        raise ApiError("اسم الأيقونة غير صالح (أحرف إنجليزية صغيرة وأرقام و _ فقط)")
    col = str(color or "").strip()
    if not _COLOR_RE.match(col):
        raise ApiError("صيغة اللون أو التدرج غير صالحة")
    par = str(params or "").strip().lstrip("?")
    if not _PARAMS_RE.match(par):
        raise ApiError("معاملات الرابط غير صالحة (أحرف وأرقام و = & _ - . فقط)")
    if perm_keys is None:
        perms = None
    else:
        if not isinstance(perm_keys, list):
            raise ApiError("صيغة الصلاحيات غير صالحة")
        valid_perms = set(db.DEFAULT_CASHIER_PERMS.keys())
        perms = [str(k) for k in perm_keys if str(k) in valid_perms]
    return t, ic, col, par, perms


def _generate_recovery_key() -> str:
    """توليد مفتاح استرداد عشوائي بطول 20 محرفاً مقسماً إلى 4 مجموعات."""
    chars = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(20))
    return "-".join(chars[i : i + 5] for i in range(0, 20, 5))


def _normalize_recovery_key(raw: str) -> str:
    return "".join(ch for ch in str(raw or "").upper() if ch.isalnum())


def _validate_passphrase(raw: str) -> str:
    p = str(raw or "").strip()
    if len(p) < 8:
        raise ApiError("عبارة مرور المالك يجب أن تتكون من 8 أحرف على الأقل")
    if len(p) > 128:
        raise ApiError("عبارة مرور المالك طويلة جداً (الحد الأقصى 128 حرفاً)")
    return p


class OwnerMixin:
    """دوال وضع المالك الرئيسي وإدارة أمان الهيكلة."""

    def _owner_row(self, conn):
        return conn.execute("SELECT * FROM owner_auth WHERE id=1").fetchone()

    def _parse_fail_state(self, raw: str | None) -> dict:
        try:
            st = json.loads(raw or "{}")
            if isinstance(st, dict):
                return {
                    "count": int(st.get("count", 0) or 0),
                    "locked_until": float(st.get("locked_until", 0.0) or 0.0),
                }
        except Exception:
            pass
        return {"count": 0, "locked_until": 0.0}

    def _check_owner_lock(self, conn, row, now_ts: float) -> dict:
        info = self._parse_fail_state(row["fail_state"])
        if info["locked_until"] > now_ts:
            remain = int(info["locked_until"] - now_ts)
            mins = max(1, (remain + 59) // 60)
            raise ApiError(f"تم تجاوز عدد محاولات المالك المسموحة. حاول بعد {mins} دقيقة [LOCKED:{remain}]")
        if info["locked_until"] and info["locked_until"] <= now_ts:
            info = {"count": 0, "locked_until": 0.0}
            conn.execute("UPDATE owner_auth SET fail_state=? WHERE id=1", (json.dumps(info),))
            conn.commit()
        return info

    def _record_owner_fail(self, conn, info: dict, now_ts: float) -> None:
        info["count"] = int(info.get("count", 0)) + 1
        if info["count"] >= OWNER_LOCK_MAX_ATTEMPTS:
            info["locked_until"] = now_ts + OWNER_LOCK_SECONDS
            info["count"] = 0
        conn.execute("UPDATE owner_auth SET fail_state=? WHERE id=1", (json.dumps(info),))
        conn.commit()
        if info.get("locked_until", 0.0) > now_ts:
            remain = int(info["locked_until"] - now_ts)
            mins = max(1, (remain + 59) // 60)
            raise ApiError(f"تم تجاوز عدد محاولات المالك المسموحة. حاول بعد {mins} دقيقة [LOCKED:{remain}]")

    def _clear_owner_fail(self, conn) -> None:
        conn.execute("UPDATE owner_auth SET fail_state=? WHERE id=1", ('{"count":0,"locked_until":0}',))

    def owner_status(self):
        """حالة إعداد ونشاط وضع المالك الرئيسي."""
        with db.connect() as conn:
            row = self._owner_row(conn)
            configured = bool(row)
            locked_until = 0.0
            if row:
                info = self._parse_fail_state(row["fail_state"])
                if info["locked_until"] > time.time():
                    locked_until = info["locked_until"]
        active = self._owner_is_active()
        seconds_left = 0
        if active and _STATE.get("owner"):
            seconds_left = max(0, int(_STATE["owner"]["until"] - time.time()))
        return {
            "configured": configured,
            "active": active,
            "seconds_left": seconds_left,
            "locked_until": locked_until,
        }

    def owner_setup(self, passphrase):
        """إعداد عبارة مرور المالك لأول مرة (متاح للمدير فقط قبل التكوين) ويعيد مفتاح الاسترداد لمرة واحدة."""
        self._admin()
        p = _validate_passphrase(passphrase)
        with db.connect() as conn:
            if self._owner_row(conn):
                raise ApiError("تم إعداد وضع المالك مسبقاً")
            raw_recovery = _generate_recovery_key()
            norm_recovery = _normalize_recovery_key(raw_recovery)
            pass_salt = os.urandom(16)
            rec_salt = os.urandom(16)
            ts = db.now()
            conn.execute(
                """INSERT INTO owner_auth
                   (id, pass_hash, pass_salt, recovery_hash, recovery_salt, fail_state, created_at, updated_at)
                   VALUES(1, ?, ?, ?, ?, '{"count":0,"locked_until":0}', ?, ?)""",
                (
                    db.hash_secret(p, pass_salt),
                    pass_salt,
                    db.hash_secret(norm_recovery, rec_salt),
                    rec_salt,
                    ts,
                    ts,
                ),
            )
            self._audit(conn, "owner_setup", "owner_auth")
            conn.commit()
        _STATE["owner"] = {"until": time.time() + OWNER_SESSION_TTL, "backed_up": False}
        return {
            "configured": True,
            "active": True,
            "seconds_left": OWNER_SESSION_TTL,
            "recovery_key": raw_recovery,
        }

    def owner_login(self, passphrase):
        """بدء جلسة المالك الرئيسي باستخدام عبارة المرور."""
        p = str(passphrase or "").strip()
        if not p:
            raise ApiError("يرجى إدخال عبارة مرور المالك")
        now_ts = time.time()
        with db.connect() as conn:
            row = self._owner_row(conn)
            if not row:
                raise ApiError("لم يتم إعداد وضع المالك بعد")
            info = self._check_owner_lock(conn, row, now_ts)
            if not hmac.compare_digest(db.hash_secret(p, row["pass_salt"]), row["pass_hash"]):
                self._record_owner_fail(conn, info, now_ts)
                raise ApiError("عبارة مرور المالك غير صحيحة")
            self._clear_owner_fail(conn)
            self._audit(conn, "owner_login", "owner_auth")
            conn.commit()
        _STATE["owner"] = {"until": now_ts + OWNER_SESSION_TTL, "backed_up": False}
        return self.owner_status()

    def owner_logout(self):
        """إنهاء جلسة المالك الرئيسي فوراً."""
        _STATE["owner"] = None
        return True

    def owner_change_passphrase(self, old_passphrase, new_passphrase):
        """تغيير عبارة مرور المالك بعد التحقق من العبارة الحالية."""
        self._owner()
        old_p = str(old_passphrase or "").strip()
        new_p = _validate_passphrase(new_passphrase)
        with db.connect() as conn:
            row = self._owner_row(conn)
            if not row:
                raise ApiError("لم يتم إعداد وضع المالك بعد")
            if not hmac.compare_digest(db.hash_secret(old_p, row["pass_salt"]), row["pass_hash"]):
                raise ApiError("عبارة المرور الحالية غير صحيحة")
            new_salt = os.urandom(16)
            conn.execute(
                "UPDATE owner_auth SET pass_hash=?, pass_salt=?, updated_at=? WHERE id=1",
                (db.hash_secret(new_p, new_salt), new_salt, db.now()),
            )
            self._audit(conn, "owner_change_passphrase", "owner_auth")
            conn.commit()
        return True

    def owner_recover(self, recovery_key, new_passphrase):
        """استعادة وتعيين عبارة مرور جديدة عبر مفتاح الاسترداد مع تدوير المفتاح وإصدار مفتاح جديد لمرة واحدة."""
        norm_key = _normalize_recovery_key(recovery_key)
        if not norm_key:
            raise ApiError("يرجى إدخال مفتاح الاسترداد")
        new_p = _validate_passphrase(new_passphrase)
        now_ts = time.time()
        with db.connect() as conn:
            row = self._owner_row(conn)
            if not row:
                raise ApiError("لم يتم إعداد وضع المالك بعد")
            info = self._check_owner_lock(conn, row, now_ts)
            if not hmac.compare_digest(db.hash_secret(norm_key, row["recovery_salt"]), row["recovery_hash"]):
                self._record_owner_fail(conn, info, now_ts)
                raise ApiError("مفتاح الاسترداد غير صحيح")
            new_recovery = _generate_recovery_key()
            new_norm_rec = _normalize_recovery_key(new_recovery)
            pass_salt = os.urandom(16)
            rec_salt = os.urandom(16)
            conn.execute(
                """UPDATE owner_auth
                   SET pass_hash=?, pass_salt=?, recovery_hash=?, recovery_salt=?, fail_state='{"count":0,"locked_until":0}', updated_at=?
                   WHERE id=1""",
                (
                    db.hash_secret(new_p, pass_salt),
                    pass_salt,
                    db.hash_secret(new_norm_rec, rec_salt),
                    rec_salt,
                    db.now(),
                ),
            )
            self._audit(conn, "owner_recover", "owner_auth")
            conn.commit()
        _STATE["owner"] = {"until": now_ts + OWNER_SESSION_TTL, "backed_up": False}
        return {"ok": True, "recovery_key": new_recovery}

    def owner_reset_admin_pin(self, secret, new_pin, user_id=None):
        """إعادة تعيين رمز المدير باستخدام عبارة مرور المالك أو مفتاح الاسترداد."""
        raw_secret = str(secret or "").strip()
        if not raw_secret:
            raise ApiError("يرجى إدخال عبارة مرور المالك أو مفتاح الاسترداد")
        np = str(new_pin or "").strip()
        if len(np) < 4 or len(np) > 24:
            raise ApiError("الرمز السري الجديد يجب أن يتكون من 4 خانات على الأقل (حتى 24 خانة)")
        if np in _WEAK_PINS:
            raise ApiError("يرجى اختيار رمز سري قوي غير بسيط أو افتراضي")

        now_ts = time.time()
        with db.connect() as conn:
            row = self._owner_row(conn)
            if not row:
                raise ApiError("لم يتم إعداد وضع المالك بعد")
            info = self._check_owner_lock(conn, row, now_ts)
            norm_secret = _normalize_recovery_key(raw_secret)
            match_pass = hmac.compare_digest(db.hash_secret(raw_secret, row["pass_salt"]), row["pass_hash"])
            match_rec = bool(norm_secret) and hmac.compare_digest(
                db.hash_secret(norm_secret, row["recovery_salt"]), row["recovery_hash"]
            )
            if not (match_pass or match_rec):
                self._record_owner_fail(conn, info, now_ts)
                raise ApiError("عبارة مرور المالك أو مفتاح الاسترداد غير صحيح")

            self._clear_owner_fail(conn)
            if user_id is not None:
                target = conn.execute("SELECT * FROM users WHERE id=? AND role='admin'", (_int(user_id),)).fetchone()
            else:
                target = conn.execute("SELECT * FROM users WHERE role='admin' ORDER BY id LIMIT 1").fetchone()
            if not target:
                raise ApiError("لم يتم العثور على حساب مدير النظام")

            for other in conn.execute("SELECT id, pin_salt, pin_hash FROM users WHERE id!=?", (target["id"],)).fetchall():
                if hmac.compare_digest(db.hash_pin(np, other["pin_salt"]), other["pin_hash"]):
                    raise ApiError("الرمز السري مستخدم بالفعل لموظف آخر — يرجى اختيار رمز فريد")

            salt = os.urandom(16)
            conn.execute(
                "UPDATE users SET pin_salt=?, pin_hash=? WHERE id=?",
                (salt, db.hash_pin(np, salt), target["id"]),
            )
            self._audit(
                conn,
                "owner_reset_admin_pin",
                str(target["id"]),
                {"username": target["username"], "via": "passphrase" if match_pass else "recovery_key"},
            )
            conn.commit()
            return {"id": target["id"], "username": target["username"], "name": target["name"]}

    def owner_audit_list(self, limit=100):
        """استعراض سجل تدقيق تغييرات المالك الرئيسي."""
        self._owner()
        lim = max(1, min(500, _int(limit, 100)))
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT id, ts, action, target, details FROM owner_audit_log ORDER BY id DESC LIMIT ?",
                (lim,),
            ).fetchall()
            out = []
            for r in rows:
                d = dict(r)
                try:
                    d["details"] = json.loads(d.get("details") or "{}")
                except Exception:
                    d["details"] = {}
                out.append(d)
            return out

    # ---------------------------------------------------------- سجل الأقسام (Phase 2)
    def _serialize_module(self, m: dict) -> dict:
        perms = m.get("perm_keys") or []
        perm_val = None if not perms else (perms[0] if len(perms) == 1 else list(perms))
        params = (m.get("params") or "").strip()
        url = m["url"]
        full_url = f"{url}?{params}" if params else url
        return {
            "id": m["key"],
            "key": m["key"],
            "title": m["title"],
            "icon": m["icon"],
            "color": m["color"],
            "url": url,
            "params": params,
            "full_url": full_url,
            "perm": perm_val,
            "perm_keys": list(perms),
            "sort_order": int(m.get("sort_order", 0) or 0),
            "enabled": bool(m.get("enabled", True)),
            "is_core": bool(m.get("is_core", False)),
            "is_builtin": bool(m.get("is_builtin", True)),
            "clone_of": m.get("clone_of"),
        }

    def ui_config(self):
        """إعدادات الواجهة والأقسام المفعلة والمسميات للتحميل عند التشغيل."""
        with db.connect() as conn:
            st = self._settings(conn)
            rows = self._modules_rows(conn)
            enabled = [self._serialize_module(m) for m in rows if m["enabled"]]
            lbls = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM ui_labels")}
            return {
                "modules": enabled,
                "labels": lbls,
                "default_labels": dict(DEFAULT_LABELS),
                "profile": st.get("business_profile") or "retail_electronics",
            }

    def modules_all(self):
        """عرض كافة الأقسام (المفعلة والمعطلة) في لوحة تحكم المالك."""
        self._owner()
        with db.connect() as conn:
            self._modules_cache = None
            return [self._serialize_module(m) for m in self._modules_rows(conn)]

    def module_toggle(self, key, enabled):
        """تفعيل أو تعطيل قسم مع حماية الأقسام الأساسية وفحص التبعيات."""
        self._owner()
        key = str(key or "").strip()
        en = bool(enabled)
        with db.connect() as conn:
            self._modules_cache = None
            rows = self._modules_rows(conn)
            by_key = {m["key"]: m for m in rows}
            target = by_key.get(key)
            if not target:
                raise ApiError("القسم غير موجود")
            if not en and target["is_core"]:
                raise ApiError("لا يمكن تعطيل قسم أساسي من النظام")
            if not en and target["is_builtin"]:
                dependents = [
                    m["title"]
                    for m in rows
                    if m["enabled"] and m["is_builtin"] and m["key"] != key and key in MODULE_REQUIRES.get(m["key"], [])
                ]
                if dependents:
                    raise ApiError(f"لا يمكن تعطيل «{target['title']}» لأن الأقسام التالية تعتمد عليه: {'، '.join(dependents)}")
            if en and target["is_builtin"]:
                missing_deps = [
                    by_key[d]["title"]
                    for d in MODULE_REQUIRES.get(key, [])
                    if d in by_key and not by_key[d]["enabled"]
                ]
                if missing_deps:
                    raise ApiError(f"يجب تفعيل الأقسام المطلوبة أولاً: {'، '.join(missing_deps)}")

            self._owner_backup_once()
            conn.execute(
                "UPDATE modules SET enabled=?, updated_at=? WHERE key=?",
                (1 if en else 0, db.now(), key),
            )
            self._audit(conn, "module_toggle", key, {"enabled": en})
            conn.commit()
            self._modules_cache = None
            return self._serialize_module(next(m for m in self._modules_rows(conn) if m["key"] == key))

    def module_reorder(self, keys):
        """إعادة ترتيب ظهور الأقسام حسب المصفوفة الممررة."""
        self._owner()
        if not isinstance(keys, list):
            raise ApiError("صيغة الترتيب غير صالحة")
        clean_keys = [str(k).strip() for k in keys if str(k).strip()]
        with db.connect() as conn:
            self._modules_cache = None
            existing = [m["key"] for m in self._modules_rows(conn)]
            existing_set = set(existing)
            ordered = [k for k in clean_keys if k in existing_set]
            seen = set(ordered)
            for k in existing:
                if k not in seen:
                    ordered.append(k)
            self._owner_backup_once()
            ts = db.now()
            for idx, k in enumerate(ordered, start=1):
                conn.execute("UPDATE modules SET sort_order=?, updated_at=? WHERE key=?", (idx * 10, ts, k))
            self._audit(conn, "module_reorder", None, {"order": ordered})
            conn.commit()
            self._modules_cache = None
            return [self._serialize_module(m) for m in self._modules_rows(conn)]

    def modules_reset_defaults(self, purge_custom=False):
        """استعادة الأقسام الافتراضية الـ 13 لحالتها الأصلية."""
        self._owner()
        self._owner_backup_once()
        ts = db.now()
        with db.connect() as conn:
            for key, title, icon, color, url, perms, order, is_core in db.DEFAULT_MODULES:
                conn.execute(
                    """INSERT INTO modules
                       (key, title, icon, color, url, params, perm_keys, sort_order, enabled, is_core, is_builtin, clone_of, created_at, updated_at)
                       VALUES(?,?,?,?,?,?,?,?,1,?,1,NULL,?,?)
                       ON CONFLICT(key) DO UPDATE SET
                         title=excluded.title, icon=excluded.icon, color=excluded.color,
                         url=excluded.url, params=excluded.params, perm_keys=excluded.perm_keys,
                         sort_order=excluded.sort_order, enabled=1, is_core=excluded.is_core,
                         is_builtin=1, clone_of=NULL, updated_at=excluded.updated_at""",
                    (key, title, icon, color, url, "", json.dumps(perms, ensure_ascii=False), order, is_core, ts, ts),
                )
            if purge_custom:
                conn.execute("DELETE FROM modules WHERE is_builtin=0")
            self._audit(conn, "modules_reset_defaults", None, {"purge_custom": bool(purge_custom)})
            conn.commit()
            self._modules_cache = None
            return [self._serialize_module(m) for m in self._modules_rows(conn)]

    # ---------------------------------------------------------- تعديل / نسخ / حذف الأقسام (Phase 3)
    def module_save(self, key, title, icon=None, color=None, params=None, perm_keys=None):
        """تعديل بيانات القسم (الاسم، الأيقونة، اللون، المعاملات للنسخ المخصصة، أو الصلاحيات)."""
        self._owner()
        key = str(key or "").strip()
        if not key:
            raise ApiError("مفتاح القسم مطلوب")
        with db.connect() as conn:
            self._modules_cache = None
            cur = next((m for m in self._modules_rows(conn) if m["key"] == key), None)
            if not cur:
                raise ApiError("القسم غير موجود")
            next_icon = cur["icon"] if icon is None else icon
            next_color = cur["color"] if color is None else color
            next_params = cur["params"] if (params is None or cur["is_builtin"]) else params
            next_perms = cur["perm_keys"] if perm_keys is None else perm_keys
            t, ic, col, par, perms = _validate_module_fields(title, next_icon, next_color, next_params, next_perms)
            self._owner_backup_once()
            conn.execute(
                "UPDATE modules SET title=?, icon=?, color=?, params=?, perm_keys=?, updated_at=? WHERE key=?",
                (t, ic, col, par, json.dumps(perms or [], ensure_ascii=False), db.now(), key),
            )
            self._audit(conn, "module_save", key, {"title": t, "icon": ic})
            conn.commit()
            self._modules_cache = None
            return self._serialize_module(next(m for m in self._modules_rows(conn) if m["key"] == key))

    def module_clone(self, source_key, title, icon=None, color=None, params="", perm_keys=None):
        """إنشاء قسم مخصص جديد كنسخة من قالب قسم حالي (يفتح نفس الصفحة ويشارك نفس البيانات)."""
        self._owner()
        src_key = str(source_key or "").strip()
        with db.connect() as conn:
            self._modules_cache = None
            rows = self._modules_rows(conn)
            src = next((m for m in rows if m["key"] == src_key), None)
            if not src:
                raise ApiError("القسم المصدري غير موجود")
            base_source = src.get("clone_of") or src["key"]
            next_icon = src["icon"] if not icon else icon
            next_color = src["color"] if not color else color
            next_perms = src["perm_keys"] if perm_keys is None else perm_keys
            t, ic, col, par, perms = _validate_module_fields(title, next_icon, next_color, params, next_perms)

            slug_src = re.sub(r"[^a-z0-9]+", "_", base_source.lower()).strip("_") or "mod"
            existing_keys = {m["key"] for m in rows}
            idx = 2
            new_key = f"c_{slug_src}_{idx}"
            while new_key in existing_keys:
                idx += 1
                new_key = f"c_{slug_src}_{idx}"

            max_order = max((int(m.get("sort_order", 0) or 0) for m in rows), default=0)
            ts = db.now()
            self._owner_backup_once()
            conn.execute(
                """INSERT INTO modules
                   (key, title, icon, color, url, params, perm_keys, sort_order, enabled, is_core, is_builtin, clone_of, created_at, updated_at)
                   VALUES(?,?,?,?,?,?,?,?,1,0,0,?,?,?)""",
                (new_key, t, ic, col, src["url"], par, json.dumps(perms or [], ensure_ascii=False), max_order + 10, base_source, ts, ts),
            )
            self._audit(conn, "module_clone", new_key, {"source": src_key, "title": t, "params": par})
            conn.commit()
            self._modules_cache = None
            return self._serialize_module(next(m for m in self._modules_rows(conn) if m["key"] == new_key))

    def module_delete(self, key):
        """حذف قسم مخصص فقط؛ الأقسام المبنية في النظام تُعطّل ولا تُحذف."""
        self._owner()
        key = str(key or "").strip()
        with db.connect() as conn:
            self._modules_cache = None
            cur = next((m for m in self._modules_rows(conn) if m["key"] == key), None)
            if not cur:
                raise ApiError("القسم غير موجود")
            if cur["is_builtin"] or cur["is_core"]:
                raise ApiError("لا يمكن حذف قسم أساسي أو مبني في النظام — استخدم زر التعطيل بدلاً من ذلك")
            self._owner_backup_once()
            conn.execute("DELETE FROM modules WHERE key=? AND is_builtin=0", (key,))
            self._audit(conn, "module_delete", key, {"title": cur["title"]})
            conn.commit()
            self._modules_cache = None
            return True

    # ---------------------------------------------------------- ملفات النشاط والمسميات (Phase 4)
    def profiles_list(self):
        """عرض قوالب الأنشطة التجارية المتاحة مع حالة النشاط الحالي."""
        self._owner()
        with db.connect() as conn:
            cur = self._settings(conn).get("business_profile") or "retail_electronics"
            return [
                {
                    "key": k,
                    "label": v["label"],
                    "description": v["description"],
                    "modules_enabled": list(v["modules_enabled"]),
                    "module_titles": dict(v.get("module_titles") or {}),
                    "labels": dict(v.get("labels") or {}),
                    "is_current": k == cur,
                }
                for k, v in BUSINESS_PROFILES.items()
            ]

    def profile_apply(self, key, dry_run=True):
        """معاينة أو تطبيق ملف نشاط تجاري (يحدّث الأقسام المبنية والمسميات دون مساس بالبيانات أو النسخ المخصصة)."""
        self._owner()
        key = str(key or "").strip()
        prof = BUSINESS_PROFILES.get(key)
        if not prof:
            raise ApiError("ملف النشاط التجاري غير معروف")

        target_set = set(prof["modules_enabled"])
        prof_titles = prof.get("module_titles") or {}
        default_titles = {row[0]: row[1] for row in db.DEFAULT_MODULES}

        with db.connect() as conn:
            self._modules_cache = None
            rows = self._modules_rows(conn)
            to_enable = []
            to_disable = []
            title_changes = []
            for m in rows:
                if not m["is_builtin"]:
                    continue
                next_en = (m["key"] in target_set) or bool(m["is_core"])
                next_title = prof_titles.get(m["key"], default_titles.get(m["key"], m["title"]))
                if next_en and not m["enabled"]:
                    to_enable.append({"key": m["key"], "title": next_title})
                elif not next_en and m["enabled"]:
                    to_disable.append({"key": m["key"], "title": m["title"]})
                if next_title != m["title"]:
                    title_changes.append({"key": m["key"], "from": m["title"], "to": next_title})

            if dry_run:
                return {
                    "dry_run": True,
                    "applied": False,
                    "profile": key,
                    "label": prof["label"],
                    "to_enable": to_enable,
                    "to_disable": to_disable,
                    "title_changes": title_changes,
                    "labels": dict(prof.get("labels") or {}),
                }

            self._owner_backup_once()
            ts = db.now()
            for m in rows:
                if not m["is_builtin"]:
                    continue
                next_en = 1 if ((m["key"] in target_set) or bool(m["is_core"])) else 0
                next_title = prof_titles.get(m["key"], default_titles.get(m["key"], m["title"]))
                conn.execute(
                    "UPDATE modules SET enabled=?, title=?, updated_at=? WHERE key=?",
                    (next_en, next_title, ts, m["key"]),
                )

            conn.execute("DELETE FROM ui_labels")
            for lk, lv in (prof.get("labels") or {}).items():
                if lk in LABEL_KEYS and str(lv).strip():
                    conn.execute("INSERT INTO ui_labels(key, value) VALUES(?,?)", (lk, str(lv).strip()[:40]))

            st = self._settings(conn)
            ver = _int(st.get("structure_version", "1"), 1) + 1
            conn.execute(
                "INSERT INTO settings(key, value) VALUES('business_profile', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key,),
            )
            conn.execute(
                "INSERT INTO settings(key, value) VALUES('structure_version', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(ver),),
            )
            cur_sp = st.get("default_start_page") or "pos"
            if cur_sp != "desktop" and cur_sp not in target_set:
                conn.execute(
                    "INSERT INTO settings(key, value) VALUES('default_start_page', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (prof.get("default_start_page") or "pos",),
                )

            self._audit(conn, "profile_apply", key, {"enabled": len(target_set), "disabled": len(to_disable)})
            conn.commit()
            self._modules_cache = None
            self._settings_cache = None
            return {
                "dry_run": False,
                "applied": True,
                "profile": key,
                "label": prof["label"],
                "to_enable": to_enable,
                "to_disable": to_disable,
                "title_changes": title_changes,
                "labels": dict(prof.get("labels") or {}),
            }

    def labels_save(self, labels):
        """حفظ مسميات الواجهة المخصصة مع التحقق من المفاتيح المسموحة والطول."""
        self._owner()
        if not isinstance(labels, dict):
            raise ApiError("صيغة المسميات غير صالحة")
        cleaned = {}
        for k, v in labels.items():
            sk = str(k or "").strip()
            if sk not in LABEL_KEYS:
                raise ApiError(f"مفتاح مسمى غير مسموح: {sk}")
            sv = "" if v is None else str(v).strip()
            if len(sv) > 40:
                raise ApiError("طول المسمى يجب ألا يتجاوز 40 حرفاً")
            cleaned[sk] = sv

        with db.connect() as conn:
            self._owner_backup_once()
            for sk, sv in cleaned.items():
                if sv == "":
                    conn.execute("DELETE FROM ui_labels WHERE key=?", (sk,))
                else:
                    conn.execute(
                        "INSERT INTO ui_labels(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (sk, sv),
                    )
            self._audit(conn, "labels_save", None, {"keys": sorted(cleaned.keys())})
            conn.commit()
            return {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM ui_labels")}
