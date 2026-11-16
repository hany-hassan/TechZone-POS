"""وضع المالك الرئيسي (Owner Mode): المصادقة، مفتاح الاسترداد، تصفير رمز المدير، وسجل التدقيق."""
import hmac
import json
import os
import secrets
import time

import db
from api_common import ApiError, OWNER_SESSION_TTL, _STATE, _int

OWNER_LOCK_MAX_ATTEMPTS = 5
OWNER_LOCK_SECONDS = 15 * 60
_RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_WEAK_PINS = {"1234", "0000", "1111"}


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
