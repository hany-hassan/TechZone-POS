"""بناء قاعدة بيانات جديدة ونظيفة لنشاط تجاري مع إمكانية نقل بيانات مختارة بأمان."""
import json
import os
import pathlib
import sqlite3
import tempfile

import db
from api_common import ApiError, _int
from profiles import LABEL_KEYS


def _copy_table(src: sqlite3.Connection, dst: sqlite3.Connection, table: str, transform=None) -> int:
    src_cols = [r[1] for r in src.execute(f"PRAGMA table_info({table})").fetchall()]
    dst_cols = [r[1] for r in dst.execute(f"PRAGMA table_info({table})").fetchall()]
    common = [c for c in dst_cols if c in src_cols]
    if not common:
        return 0
    col_sql = ", ".join(common)
    ph_sql = ", ".join("?" for _ in common)
    rows = src.execute(f"SELECT {col_sql} FROM {table}").fetchall()
    out_rows = []
    for r in rows:
        d = {c: r[i] for i, c in enumerate(common)}
        if transform is not None:
            d = transform(d)
            if d is None:
                continue
        out_rows.append(tuple(d[c] for c in common))
    if out_rows:
        dst.executemany(f"INSERT INTO {table}({col_sql}) VALUES({ph_sql})", out_rows)
    return len(out_rows)


def build_fresh_profile_db(
    profile: dict,
    apply_demo_fn,
    apply_demo: bool = True,
    carry_over: dict | None = None,
    reset_store_info: bool = False,
) -> dict:
    """إنشاء قاعدة بيانات جديدة نظيفة للنشاط المختار مع حفظ نسخة احتياطية كاملة قبل الاستبدال."""
    carry = carry_over if isinstance(carry_over, dict) else {}
    carry_sales = bool(carry.get("sales", False))
    carry_products = bool(carry.get("products", False)) or carry_sales
    carry_customers = bool(carry.get("customers", False)) or carry_sales
    carry_repairs = bool(carry.get("repairs", False))

    key = profile["key"]
    target_set = set(profile.get("modules_enabled") or [])
    prof_titles = profile.get("module_titles") or {}
    default_titles = {row[0]: row[1] for row in db.DEFAULT_MODULES}
    demo_catalog = profile.get("demo_catalog") or []

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp_path = pathlib.Path(tmp.name)
    tmp.close()

    try:
        dst = sqlite3.connect(str(tmp_path), timeout=15)
        dst.row_factory = sqlite3.Row
        try:
            dst.execute("PRAGMA foreign_keys=ON")
            dst.executescript(db.SCHEMA)
            db._ensure_schema_columns(dst)
            for idx_sql in db._PERFORMANCE_INDEXES:
                dst.execute(idx_sql)
            dst.execute("DELETE FROM settings")
            dst.execute("DELETE FROM modules")
            dst.execute("DELETE FROM business_profiles")
            dst.execute("DELETE FROM user_permissions")
            dst.execute("DELETE FROM permission_roles")
            dst.execute("DELETE FROM perm_audit_log")

            ts = db.now()
            # 1) فتح اتصال القراءة من القاعدة الحالية ثم إغلاقه قبل الاستبدال لتفادي أي قفل
            with db.connect() as src_conn:
                _copy_table(src_conn, dst, "users")
                _copy_table(src_conn, dst, "user_permissions")
                _copy_table(src_conn, dst, "permission_roles")
                _copy_table(src_conn, dst, "perm_audit_log")
                _copy_table(src_conn, dst, "owner_auth")
                _copy_table(src_conn, dst, "owner_audit_log")
                _copy_table(src_conn, dst, "business_profiles")

                reset_keys = {
                    "store_name": "تك زون للإلكترونيات",
                    "store_address": "",
                    "store_phone": "",
                    "store_email": "",
                    "store_cr": "",
                    "store_vat": "",
                    "receipt_logo": "",
                }

                def _tx_setting(d):
                    k = d["key"]
                    if k == "business_profile":
                        d["value"] = key
                    elif k == "hide_empty_categories":
                        d["value"] = "0"
                    elif k == "pos_categories_config" and not carry_products:
                        d["value"] = ""
                    elif k == "structure_version":
                        d["value"] = str(_int(d.get("value"), 1) + 1)
                    elif reset_store_info and k in reset_keys:
                        d["value"] = reset_keys[k]
                    return d

                _copy_table(src_conn, dst, "settings", transform=_tx_setting)
                dst.execute(
                    "INSERT INTO settings(key, value) VALUES('business_profile', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key,),
                )
                dst.execute(
                    "INSERT INTO settings(key, value) VALUES('hide_empty_categories', '0') "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                )
                cur_sp_row = dst.execute("SELECT value FROM settings WHERE key='default_start_page'").fetchone()
                cur_sp = (cur_sp_row["value"] if cur_sp_row else None) or "pos"
                if cur_sp != "desktop" and cur_sp not in target_set:
                    dst.execute(
                        "INSERT INTO settings(key, value) VALUES('default_start_page', ?) "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (profile.get("default_start_page") or "pos",),
                    )

                def _tx_module(d):
                    if d.get("is_builtin", 1):
                        mk = d["key"]
                        d["enabled"] = 1 if ((mk in target_set) or bool(d.get("is_core", 0))) else 0
                        d["title"] = prof_titles.get(mk, default_titles.get(mk, d["title"]))
                        d["updated_at"] = ts
                    return d

                _copy_table(src_conn, dst, "modules", transform=_tx_module)
                for lk, lv in (profile.get("labels") or {}).items():
                    if lk in LABEL_KEYS and str(lv).strip():
                        dst.execute("INSERT INTO ui_labels(key, value) VALUES(?,?)", (lk, str(lv).strip()[:40]))

                # 2) البيانات التشغيلية المختارة فقط
                if carry_products:
                    _copy_table(src_conn, dst, "categories")
                    _copy_table(src_conn, dst, "products")
                    _copy_table(src_conn, dst, "serials")

                if carry_customers:
                    if carry_sales:
                        _copy_table(src_conn, dst, "customers")
                    else:
                        def _tx_cust_only(d):
                            debt = int(d.get("debt") or 0)
                            d["total_purchases"] = 0
                            d["credit_total"] = max(0, debt)
                            d["paid_total"] = 0
                            return d

                        _copy_table(src_conn, dst, "customers", transform=_tx_cust_only)
                        for cr in dst.execute("SELECT id, debt FROM customers WHERE debt != 0").fetchall():
                            debt = int(cr["debt"])
                            dst.execute(
                                """INSERT INTO customer_ledger
                                   (customer_id, created_at, kind, ref, sale_id, voucher_id, plan_id, debit, credit, balance_after, method, ref_no, notes, user_id, user_name)
                                   VALUES(?,?, 'adjustment', 'OPEN-BAL', NULL, NULL, NULL, ?, ?, ?, NULL, NULL, 'رصيد افتتاحي منقول', NULL, NULL)""",
                                (cr["id"], ts, max(0, debt), max(0, -debt), debt),
                            )

                if carry_sales:
                    _copy_table(src_conn, dst, "shifts")
                    _copy_table(src_conn, dst, "sales")
                    _copy_table(src_conn, dst, "sale_items")
                    _copy_table(src_conn, dst, "payments")
                    _copy_table(src_conn, dst, "sale_returns")
                    _copy_table(src_conn, dst, "sale_return_items")
                    _copy_table(src_conn, dst, "quotations")
                    _copy_table(src_conn, dst, "quotation_items")
                    _copy_table(src_conn, dst, "customer_payments")
                    _copy_table(src_conn, dst, "installment_plans")
                    _copy_table(src_conn, dst, "installment_items")
                    _copy_table(src_conn, dst, "installment_payments")
                    _copy_table(src_conn, dst, "customer_ledger")
                    if carry_products:
                        _copy_table(src_conn, dst, "stock_movements")

                if carry_repairs:
                    _copy_table(src_conn, dst, "repairs")
                    if carry_products:
                        _copy_table(src_conn, dst, "repair_parts")
                        _copy_table(src_conn, dst, "used_device_purchases")
                    else:
                        def _tx_used_no_prod(d):
                            d["product_id"] = None
                            return d

                        _copy_table(src_conn, dst, "used_device_purchases", transform=_tx_used_no_prod)

            # 3) البيانات التجريبية الخاصة بالنشاط المختار
            demo_seeded = 0
            if apply_demo:
                demo_seeded = apply_demo_fn(dst, key, demo_catalog, exclusive_demo=False)

            dst.execute(
                "INSERT INTO owner_audit_log(ts, action, target, details) VALUES(?,?,?,?)",
                (
                    ts,
                    "profile_fresh_db",
                    key,
                    json.dumps(
                        {
                            "carry_products": carry_products,
                            "carry_customers": carry_customers,
                            "carry_sales": carry_sales,
                            "carry_repairs": carry_repairs,
                            "demo_seeded": demo_seeded,
                        },
                        ensure_ascii=False,
                    ),
                ),
            )

            fk_bad = dst.execute("PRAGMA foreign_key_check").fetchall()
            if fk_bad:
                raise ApiError("تعذر إنشاء القاعدة الجديدة بسبب تعارض في الروابط المرجعية للبيانات المختارة")

            dst.commit()

            # 4) أخذ نسخة احتياطية كاملة قبل استبدال قاعدة البيانات الحية
            bkp_path = db.backup_database("before_fresh_profile_db")
            live_path = db.db_path()
            live_conn = sqlite3.connect(live_path, timeout=15)
            try:
                dst.backup(live_conn)
            finally:
                live_conn.close()
        finally:
            dst.close()
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    return {
        "fresh_db": True,
        "backup_file": bkp_path.name if bkp_path else None,
        "demo_seeded": demo_seeded,
        "carried": {
            "products": carry_products,
            "customers": carry_customers,
            "sales": carry_sales,
            "repairs": carry_repairs,
        },
    }
