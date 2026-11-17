"""إدارة العملاء، المديونيات، دفتر الأستاذ، وسندات القبض."""
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
    _append_ledger_entry,
    _customer_debt_summary,
    _customers_enriched_cte,
    _fmt_money,
    _format_doc_seq,
    _int,
    _jpeg_to_pdf_bytes,
    _money,
    _refresh_customer_cache,
    _upsert_customer,
    _validate_image_data_url,
    _win32_auto_paste_into_whatsapp,
    _win32_copy_pdf_to_clipboard,
    _find_whatsapp_hwnd,
)


class CustomersMixin:
    # ---------------------------------------------------------- عملاء ومديونيات وسندات قبض
    def customers_search(self, q="", limit=20):
        self._perm_any("customers_quick_pick", "customers_view")
        can_debt = self._has_perm("customers_debt_view")
        q = (q or "").strip()
        lim = min(100, max(1, _int(limit, 20)))
        with db.connect() as conn:
            if can_debt:
                rows = conn.execute(
                    """SELECT id, name, phone, total_purchases, credit_total, paid_total, debt, created_at
                       FROM customers
                       WHERE name LIKE ? OR phone LIKE ?
                       ORDER BY name LIMIT ?""",
                    (f"%{q}%", f"%{q}%", lim),
                ).fetchall()
                return [dict(r) for r in rows]
            rows = conn.execute(
                """SELECT id, name, phone
                   FROM customers
                   WHERE name LIKE ? OR phone LIKE ?
                   ORDER BY name LIMIT ?""",
                (f"%{q}%", f"%{q}%", lim),
            ).fetchall()
            return [dict(r) for r in rows]

    def customer(self, id):
        self._perm("customers_view")
        can_debt = self._has_perm("customers_debt_view")
        with db.connect() as conn:
            r = conn.execute("SELECT id, name, phone, created_at FROM customers WHERE id=?", (_int(id),)).fetchone()
            if not r:
                raise ApiError("العميل غير موجود")
            d = dict(r)
            if can_debt:
                full = conn.execute("SELECT * FROM customers WHERE id=?", (_int(id),)).fetchone()
                summary = _customer_debt_summary(conn, full)
                d["total_purchases"] = summary["total_purchases"]
                d["credit_total"] = summary["credit_total"]
                d["paid_total"] = summary["paid_total"]
                d["debt"] = summary["debt"]
            else:
                d["total_purchases"] = None
                d["credit_total"] = None
                d["paid_total"] = None
                d["debt"] = None
            return d

    def customers_save(self, name, phone=None, id=None):
        self._perm("customers_edit")
        name = (name or "").strip()
        phone = (phone or "").strip() or None
        if not name:
            raise ApiError("اسم العميل مطلوب")
        if len(name) > 120:
            raise ApiError("اسم العميل طويل جداً")
        if phone and len(phone) > 40:
            raise ApiError("رقم الهاتف طويل جداً")
        with db.connect() as conn:
            try:
                if id:
                    cid = _int(id)
                    cur = conn.execute("UPDATE customers SET name=?, phone=? WHERE id=?", (name, phone, cid))
                    if not cur.rowcount:
                        raise ApiError("العميل غير موجود")
                    return {"id": cid}
                else:
                    dup = conn.execute(
                        "SELECT id FROM customers WHERE name=? AND COALESCE(phone,'')=COALESCE(?, '')",
                        (name, phone),
                    ).fetchone()
                    if dup:
                        raise ApiError("العميل مسجل مسبقاً بنفس الاسم ورقم الهاتف")
                    cur = conn.execute(
                        "INSERT INTO customers(name, phone, created_at) VALUES(?,?,?)",
                        (name, phone, db.now()),
                    )
                    return {"id": cur.lastrowid}
            except sqlite3.IntegrityError:
                raise ApiError("العميل مسجل مسبقاً بنفس الاسم ورقم الهاتف")

    def customers_delete(self, id):
        self._perm("customers_delete")
        cid = _int(id)
        with db.connect() as conn:
            cust = conn.execute("SELECT * FROM customers WHERE id=?", (cid,)).fetchone()
            if not cust:
                raise ApiError("العميل غير موجود")
            summary = _customer_debt_summary(conn, cust)
            if summary["debt"] > 0:
                raise ApiError("لا يمكن حذف عميل عليه مديونية متبقية — يجب سداد المديونية أولاً")
            if summary["sales"] or summary["vouchers"] or summary.get("inst_plans_count"):
                raise ApiError("لا يمكن حذف عميل مرتبط بفواتير أو سندات قبض أو عقود أقساط للحفاظ على سلامة الحسابات وسجل الورديات")
            conn.execute("DELETE FROM customers WHERE id=?", (cid,))
            return True

    def customers_list(self, limit=100, offset=0, debt_only=False):
        self._perm("customers_view")
        can_debt = self._has_perm("customers_debt_view")
        if debt_only and not can_debt:
            raise ApiError("ممنوع: ليست لديك صلاحية عرض المديونيات")
        limit, offset = max(1, _int(limit, 100)), max(0, _int(offset, 0))
        with db.connect() as conn:
            summary_row = conn.execute(
                """SELECT COUNT(*) AS total_customers,
                          COALESCE(SUM(CASE WHEN debt > 0 THEN 1 ELSE 0 END), 0) AS debt_customers_count,
                          COALESCE(SUM(total_purchases), 0) AS total_purchases,
                          COALESCE(SUM(credit_total), 0) AS total_credit,
                          COALESCE(SUM(paid_total), 0) AS total_paid,
                          COALESCE(SUM(debt), 0) AS total_debt
                   FROM customers"""
            ).fetchone()
            if can_debt:
                global_summary = dict(summary_row) if summary_row else {
                    "total_customers": 0, "debt_customers_count": 0,
                    "total_purchases": 0, "total_credit": 0, "total_paid": 0, "total_debt": 0,
                }
                total = global_summary["debt_customers_count"] if debt_only else global_summary["total_customers"]
                where_sql = "WHERE debt > 0" if debt_only else ""
                rows = conn.execute(
                    f"""SELECT id, name, phone, total_purchases, credit_total, paid_total, debt, created_at
                        FROM customers {where_sql} ORDER BY name LIMIT ? OFFSET ?""",
                    (limit, offset),
                ).fetchall()
                return {"rows": [dict(r) for r in rows], "total": total, "summary": global_summary}
            tot_cnt = summary_row["total_customers"] if summary_row else 0
            rows = conn.execute(
                """SELECT id, name, phone, created_at
                   FROM customers ORDER BY name LIMIT ? OFFSET ?""",
                (limit, offset),
            ).fetchall()
            out_rows = [
                {**dict(r), "total_purchases": None, "credit_total": None, "paid_total": None, "debt": None}
                for r in rows
            ]
            return {
                "rows": out_rows,
                "total": tot_cnt,
                "summary": {
                    "total_customers": tot_cnt,
                    "debt_customers_count": None,
                    "total_purchases": None,
                    "total_credit": None,
                    "total_paid": None,
                    "total_debt": None,
                },
            }

    def customer_history(self, id):
        self._perm_all("customers_view", "customers_debt_view")
        cid = _int(id)
        with db.connect() as conn:
            cust = conn.execute("SELECT * FROM customers WHERE id=?", (cid,)).fetchone()
            if not cust:
                raise ApiError("العميل غير موجود")
            cname = cust["name"]
            cphone = cust["phone"]
            summary = _customer_debt_summary(conn, cust)
            cust_dict = dict(cust)
            cust_dict["total_purchases"] = summary["total_purchases"]
            cust_dict["credit_total"] = summary["credit_total"]
            cust_dict["paid_total"] = summary["paid_total"]
            cust_dict["debt"] = summary["debt"]

            ledger_rows = conn.execute(
                """SELECT id, kind, ref, sale_id, voucher_id, plan_id, created_at, debit, credit,
                          balance_after, method, ref_no, notes, user_name
                   FROM customer_ledger
                   WHERE customer_id=?
                   ORDER BY id DESC""",
                (cid,),
            ).fetchall()
            if ledger_rows:
                events = [dict(r) for r in ledger_rows]
            else:
                events = []
                for s in summary["sales"]:
                    if s["net_credit"] > 0:
                        events.append({
                            "kind": "credit_sale",
                            "ref": s["invoice_no"],
                            "sale_id": s["id"],
                            "created_at": s["created_at"],
                            "debit": s["net_credit"],
                            "credit": 0,
                            "method": "credit",
                            "ref_no": None,
                            "notes": f"فاتورة آجلة ({s['invoice_no']})",
                        })
                for v in summary["vouchers"]:
                    events.append({
                        "kind": "voucher",
                        "id": v["id"],
                        "ref": v["ref"],
                        "sale_id": v["sale_id"],
                        "created_at": v["created_at"],
                        "debit": 0,
                        "credit": v["amount"],
                        "method": v["method"],
                        "ref_no": v["ref_no"],
                        "notes": v["notes"] or ("سداد نقدي" if v["method"] == "cash" else "سداد محفظة"),
                        "user_name": v["user_name"],
                    })
                events.sort(key=lambda x: (x["created_at"], 0 if x["kind"] == "credit_sale" else 1))
                running = 0
                for ev in events:
                    running = max(0, running + ev["debit"] - ev["credit"])
                    ev["balance_after"] = running
                events.reverse()

            repairs = conn.execute(
                """SELECT r.id, r.ref, r.created_at, r.device_type, r.problem, r.status, r.cost
                   FROM repairs r
                   WHERE r.customer_name=?
                      OR (? IS NOT NULL AND ? != '' AND r.customer_phone=?)
                   ORDER BY r.id DESC""",
                (cname, cphone, cphone, cphone),
            ).fetchall()
            installments = conn.execute(
                """SELECT ip.*,
                          (SELECT COUNT(*) FROM installment_items ii WHERE ii.plan_id=ip.id AND ii.status='paid') AS paid_count,
                          (SELECT MIN(ii.due_date) FROM installment_items ii WHERE ii.plan_id=ip.id AND ii.status IN ('pending','partial')) AS next_due_date,
                          (SELECT COUNT(*) FROM installment_items ii WHERE ii.plan_id=ip.id AND ii.status IN ('pending','partial') AND ii.due_date < date('now','localtime')) AS overdue_count
                   FROM installment_plans ip
                   WHERE ip.customer_id=?
                   ORDER BY ip.id DESC""",
                (cid,),
            ).fetchall()
            return {
                "customer": cust_dict,
                "sales": summary["sales"],
                "vouchers": summary["vouchers"],
                "ledger": events,
                "repairs": [dict(r) for r in repairs],
                "installments": [dict(p) for p in installments],
            }

    def customer_payment_create(self, customer_id, amount, method="cash", ref_no=None, sale_id=None, notes=None):
        u = self._perm("customers_payment")
        cid = _int(customer_id)
        amt = _money(amount)
        if amt <= 0:
            raise ApiError("مبلغ السداد يجب أن يكون أكبر من صفر")
        if method not in ("cash", "wallet"):
            raise ApiError("طريقة السداد غير صالحة (نقدي أو محفظة)")
        ref_no = (ref_no or "").strip() or None
        if method == "wallet" and not ref_no:
            raise ApiError("يرجى إدخال رقم العملية المرجعية لتحويل المحفظة")
        with db.connect() as conn:
            cust = conn.execute("SELECT * FROM customers WHERE id=?", (cid,)).fetchone()
            if not cust:
                raise ApiError("العميل غير موجود")
            summary = _customer_debt_summary(conn, cust)
            if summary["debt"] <= 0:
                raise ApiError("لا توجد مديونية مستحقة على هذا العميل")
            if amt > summary["debt"]:
                raise ApiError(f"مبلغ السداد ({_fmt_money(amt)}) أكبر من إجمالي المديونية المتبقية ({_fmt_money(summary['debt'])})")
            s = self._open_shift(conn, u["id"])
            shift_id = s["id"] if s else None
            pos_tpl = self._load_templates(conn)["pos"]
            v_prefix = (pos_tpl.get("voucher_prefix") or "RCV-").strip() or "RCV-"
            ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            cnt = conn.execute("SELECT COUNT(*) c FROM customer_payments").fetchone()["c"] + 1
            if v_prefix[-1].isdigit():
                ref = f"{v_prefix}{cnt:03d}"
            else:
                sep = "" if v_prefix.endswith(("-", "/", "_")) else "-"
                ref = f"{v_prefix}{sep}{ts}-{cnt:03d}"
            if conn.execute("SELECT 1 FROM customer_payments WHERE ref=?", (ref,)).fetchone():
                ref = f"{ref}-{cnt}"
            now_ts = db.now()
            clean_notes = (notes or "").strip() or None
            sid_val = _int(sale_id) if sale_id else None
            cur = conn.execute(
                """INSERT INTO customer_payments(ref, customer_id, sale_id, user_id, shift_id, created_at, amount, method, ref_no, notes)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (ref, cid, sid_val, u["id"], shift_id, now_ts, amt, method, ref_no, clean_notes),
            )
            _append_ledger_entry(
                conn,
                cid,
                "voucher",
                ref,
                credit=amt,
                sale_id=sid_val,
                voucher_id=cur.lastrowid,
                method=method,
                ref_no=ref_no,
                notes=clean_notes or ("سداد نقدي" if method == "cash" else "سداد محفظة"),
                user_id=u["id"],
                user_name=u["name"],
                created_at=now_ts,
            )
            return {"id": cur.lastrowid, "ref": ref, "remaining_debt": summary["debt"] - amt}

    def customer_payment_delete(self, id):
        u = self._perm("customers_delete")
        vid = _int(id)
        with db.connect() as conn:
            v = conn.execute("SELECT * FROM customer_payments WHERE id=?", (vid,)).fetchone()
            if not v:
                raise ApiError("سند القبض غير موجود")
            conn.execute("DELETE FROM customer_payments WHERE id=?", (vid,))
            _append_ledger_entry(
                conn,
                v["customer_id"],
                "adjustment",
                v["ref"],
                debit=v["amount"],
                sale_id=v["sale_id"],
                method=v["method"],
                ref_no=v["ref_no"],
                notes=f"إلغاء سند قبض ({v['ref']})",
                user_id=u["id"],
                user_name=u["name"],
            )
            return True

