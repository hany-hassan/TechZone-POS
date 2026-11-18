"""عروض الأسعار وفواتير المبيعات الرسمية A4."""
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
import erp_hooks
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


class QuotesMixin:
    # ---------------------------------------------------------- قسم المبيعات وعروض الأسعار والفواتير الرسمية A4
    def _ensure_custom_item_product(self, conn) -> int:
        """عنصر خدمي/مخصص غير نشط في الكتالوج لربط البنود الحرة في فواتير المبيعات دون التأثير على المخزون."""
        row = conn.execute("SELECT id FROM products WHERE sku='__CUSTOM_ITEM__'").fetchone()
        if row:
            return row["id"]
        cur = conn.execute(
            """INSERT INTO products(sku, name, price, cost, qty, min_qty, tracked, active, created_at)
               VALUES('__CUSTOM_ITEM__', 'بند مبيعات مخصص', 0, 0, 0, 0, 0, 0, ?)""",
            (db.now(),),
        )
        return cur.lastrowid

    def _convert_quote_to_sale_in_tx(self, conn, u, q_row, q_items, paid_amount=None, payment_method=None, payment_date=None, payment_method_label=None, payment_plan_note=None, payments_json=None):
        """تحويل عرض سعر أو مسودة فاتورة A4 إلى فاتورة مبيعات معتمدة في جدول sales مع خصم المخزون وتسجيل الدفعة والآجل."""
        s_shift = self._open_shift(conn, u["id"])
        shift_id = s_shift["id"] if s_shift else None

        total = q_row["total"]
        paid = _money(paid_amount) if paid_amount is not None else q_row["paid_amount"]
        paid = max(0, min(total, paid))
        due = max(0, total - paid)
        method = (payment_method or q_row["payment_method"] or "cash").strip()
        if method not in ("cash", "wallet"):
            method = "cash"
        pay_dt = (payment_date or q_row["payment_date"] or q_row["doc_date"] or db.now()[:10]).strip()

        cname = (q_row["customer_name"] or "").strip() or None
        cphone = (q_row["customer_phone"] or "").strip() or None
        if due > 0 and not cname:
            raise ApiError("يرجى إدخال اسم العميل عند وجود مبلغ متبقٍ (مستحق آجل) على الفاتورة")

        customer_id = _upsert_customer(conn, cname, cphone) if cname else None
        custom_pid = self._ensure_custom_item_product(conn)

        # التحقق من توفر المخزون للأصناف المرتبطة بالكتالوج أولاً
        for it in q_items:
            pid = it["product_id"]
            if pid and pid != custom_pid:
                p = conn.execute("SELECT * FROM products WHERE id=? AND active=1", (pid,)).fetchone()
                if p and p["qty"] < it["qty"]:
                    raise ApiError(f"المخزون غير كافٍ للصنف «{p['name']}» (المتوفر: {p['qty']}، المطلوب: {it['qty']})")

        tpl_a4 = self._load_templates(conn)["a4"]
        inv_prefix = (tpl_a4.get("invoice_prefix") or "الفات/2026/").strip()

        pm_lbl = (payment_method_label if payment_method_label is not None else (q_row["payment_method_label"] if "payment_method_label" in q_row.keys() else "")) or ("محفظة إلكترونية" if method == "wallet" else "نقدي")
        pm_note = (payment_plan_note if payment_plan_note is not None else (q_row["payment_plan_note"] if "payment_plan_note" in q_row.keys() else "")) or None
        pm_json = (payments_json if payments_json is not None else (q_row["payments_json"] if "payments_json" in q_row.keys() else None))

        cur = conn.execute(
            """INSERT INTO sales(invoice_no, shift_id, user_id, customer_id, created_at, customer_name, customer_phone,
                                 subtotal, discount, tax, total, notes, doc_type, invoice_date, due_date, source_ref, signal_ref, quote_id,
                                 payment_method_label, payment_plan_note, payments_json)
               VALUES('TMP-INV',?,?,?,?,?,?,?,?,?,?,?,'b2b',?,?,?,?,?,?,?,?)""",
            (
                shift_id,
                u["id"],
                customer_id,
                db.now(),
                cname,
                cphone,
                q_row["subtotal"],
                q_row["discount"],
                q_row["tax"],
                total,
                q_row["notes"],
                q_row["doc_date"] or db.now()[:10],
                q_row["due_date"] or q_row["doc_date"] or db.now()[:10],
                q_row["source_ref"],
                q_row["signal_ref"],
                q_row["id"],
                pm_lbl,
                pm_note,
                pm_json,
            ),
        )
        sale_id = cur.lastrowid
        invoice_no = _format_doc_seq(inv_prefix, sale_id)
        # التأكد من عدم تكرار رقم الفاتورة
        if conn.execute("SELECT 1 FROM sales WHERE invoice_no=? AND id!=?", (invoice_no, sale_id)).fetchone():
            invoice_no = f"{invoice_no}-{q_row['id']}"
        conn.execute("UPDATE sales SET invoice_no=? WHERE id=?", (invoice_no, sale_id))

        for it in q_items:
            pid = it["product_id"] if it["product_id"] else custom_pid
            p_cost_row = conn.execute("SELECT cost FROM products WHERE id=?", (pid,)).fetchone() if pid != custom_pid else None
            c_unit = int(p_cost_row["cost"] or 0) if p_cost_row else 0
            conn.execute(
                """INSERT INTO sale_items(sale_id, product_id, name, qty, unit_price, cost_unit, line_total, sku, tax_label, tax_rate)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    sale_id,
                    pid,
                    it["name"],
                    it["qty"],
                    it["unit_price"],
                    c_unit,
                    it["line_total"],
                    it["sku"] or "",
                    it["tax_label"] or "",
                    it["tax_rate"] or 0,
                ),
            )
            if pid != custom_pid:
                p = conn.execute("SELECT id, qty FROM products WHERE id=?", (pid,)).fetchone()
                if p:
                    conn.execute("UPDATE products SET qty=qty-? WHERE id=?", (it["qty"], pid))
                    after = conn.execute("SELECT qty FROM products WHERE id=?", (pid,)).fetchone()[0]
                    conn.execute(
                        """INSERT INTO stock_movements(created_at, user_id, product_id, qty_change, qty_after, reason, ref)
                           VALUES(?,?,?,?,?,?,?)""",
                        (db.now(), u["id"], pid, -it["qty"], after, "sale", invoice_no),
                    )

        # تسجيل الدفعات (المدفوع نقدي/محفظة + المتبقي آجل على حساب العميل)
        if total == 0:
            conn.execute(
                "INSERT INTO payments(sale_id, method, amount, received, change, ref_no) VALUES(?,?,0,0,0,?)",
                (sale_id, method, pay_dt),
            )
        else:
            if paid > 0:
                conn.execute(
                    "INSERT INTO payments(sale_id, method, amount, received, change, ref_no) VALUES(?,?,?,?,0,?)",
                    (sale_id, method, paid, paid, pay_dt),
                )
            if due > 0:
                conn.execute(
                    "INSERT INTO payments(sale_id, method, amount, received, change, ref_no) VALUES(?,?,?,?,0,?)",
                    (sale_id, "credit", due, 0, None),
                )
        if customer_id:
            if due > 0:
                _append_ledger_entry(
                    conn,
                    customer_id,
                    "credit_sale",
                    invoice_no,
                    debit=due,
                    sale_id=sale_id,
                    method="credit",
                    notes=f"فاتورة آجلة ({invoice_no})",
                    user_id=u["id"],
                    user_name=u["name"],
                )
            else:
                _refresh_customer_cache(conn, customer_id)

        conn.execute(
            """UPDATE quotations
               SET status='converted', doc_type='invoice', converted_sale_id=?, paid_amount=?, payment_method=?, payment_date=?, quote_no=?,
                   payment_method_label=?, payment_plan_note=?, payments_json=?
               WHERE id=?""",
            (sale_id, paid, method, pay_dt, invoice_no, pm_lbl, pm_note, pm_json, q_row["id"]),
        )
        erp_hooks.on_sale_created(self, conn, sale_id, user=u)
        return sale_id, invoice_no

    def quotation_save(
        self,
        id=None,
        doc_type="quote",
        customer_name=None,
        customer_phone=None,
        doc_date=None,
        due_date=None,
        source_ref=None,
        signal_ref=None,
        items=None,
        discount=0,
        paid_amount=0,
        payment_method="cash",
        payment_date=None,
        payment_method_label=None,
        payment_plan_note=None,
        payments_list=None,
        notes=None,
        auto_convert=False,
    ):
        """إنشاء أو تعديل عرض سعر (quote) أو إصدار فاتورة مبيعات A4 مباشرة (invoice)."""
        u = self._perm("quotes_create_edit")
        doc_type = "invoice" if doc_type == "invoice" else "quote"
        if doc_type == "invoice" or auto_convert:
            self._perm("quotes_convert")
        items = items or []
        if not items:
            raise ApiError("يرجى إضافة بند واحد على الأقل في الجدول")
        cname = (customer_name or "").strip() or None
        cphone = (customer_phone or "").strip() or None
        today_s = datetime.datetime.now().strftime("%Y-%m-%d")
        doc_date = (doc_date or "").strip() or today_s
        due_date = (due_date or "").strip() or doc_date
        payment_date = (payment_date or "").strip() or doc_date
        method = (payment_method or "cash").strip()
        if method not in ("cash", "wallet"):
            method = "cash"

        with db.connect() as conn:
            st = self._settings(conn)
            tax_enabled = st.get("tax_enabled", "1") != "0"
            tpl_a4 = self._load_templates(conn)["a4"]
            default_tax_lbl = tpl_a4.get("default_tax_label", "Zero Rated 0%")
            src_prefix = (tpl_a4.get("source_prefix") or "تقنية - Technology/").strip()
            quote_prefix = (tpl_a4.get("quote_prefix") or "ع.س/2026/").strip()
            inv_prefix = (tpl_a4.get("invoice_prefix") or "الفات/2026/").strip()

            customer_id = _upsert_customer(conn, cname, cphone) if cname else None

            parsed_items = []
            subtotal = 0
            total_tax = 0
            for raw_it in items:
                pid = _int(raw_it.get("product_id"), 0) or None
                sku = (raw_it.get("sku") or "").strip()
                name = (raw_it.get("name") or "").strip()
                if pid:
                    p = conn.execute("SELECT sku, name, price FROM products WHERE id=?", (pid,)).fetchone()
                    if p:
                        if not sku:
                            sku = p["sku"]
                        if not name:
                            name = p["name"]
                if not name:
                    raise ApiError("اسم/وصف الصنف مطلوب لكل بند في الفاتورة")
                qty = _int(raw_it.get("qty"), 1)
                if qty <= 0:
                    raise ApiError(f"الكمية للبند «{name}» يجب أن تكون 1 أو أكثر")
                unit_price = _money(raw_it.get("unit_price"), 0)
                if unit_price < 0:
                    raise ApiError("سعر الوحدة لا يمكن أن يكون سالباً")
                tax_rate = _int(raw_it.get("tax_rate"), 0) if tax_enabled else 0
                if tax_rate < 0 or tax_rate > 100:
                    tax_rate = 0
                tax_label = raw_it.get("tax_label") if tax_enabled else ""
                if not tax_enabled:
                    tax_label = ""
                elif tax_label is None:
                    tax_label = f"{tax_rate}%" if tax_rate > 0 else default_tax_lbl
                else:
                    tax_label = str(tax_label).strip()
                line_total = qty * unit_price
                line_tax = int((Decimal(line_total) * Decimal(tax_rate) / 100).to_integral_value(rounding=ROUND_HALF_UP))
                subtotal += line_total
                total_tax += line_tax
                parsed_items.append({
                    "product_id": pid,
                    "sku": sku,
                    "name": name,
                    "qty": qty,
                    "unit_price": unit_price,
                    "tax_label": tax_label,
                    "tax_rate": tax_rate,
                    "line_total": line_total,
                })

            disc = _money(discount, 0)
            if disc < 0 or disc > subtotal:
                raise ApiError("قيمة الخصم غير صالحة (يجب ألا تتجاوز المجموع الفرعي)")
            total = max(0, subtotal - disc + total_tax)
            # عرض السعر لا يحتوي على مدفوعات (المدفوعات للفواتير فقط)
            if doc_type == "quote" and not auto_convert:
                paid = 0
                pm_label = ""
                pm_note = (payment_plan_note or "").strip() or None
                pm_json = None
            else:
                cleaned_pms = []
                if isinstance(payments_list, list) and payments_list:
                    for p_it in payments_list:
                        if isinstance(p_it, dict):
                            p_amt = _money(p_it.get("amount"), 0)
                            if p_amt > 0:
                                cleaned_pms.append({
                                    "label": str(p_it.get("label") or "").strip(),
                                    "method": str(p_it.get("method") or payment_method_label or "نقدي").strip(),
                                    "date": str(p_it.get("date") or payment_date or doc_date).strip(),
                                    "amount": p_amt,
                                })
                if cleaned_pms:
                    paid = sum(x["amount"] for x in cleaned_pms)
                    pm_json = json.dumps(cleaned_pms, ensure_ascii=False)
                else:
                    paid = _money(paid_amount, 0)
                    pm_json = None
                if paid < 0:
                    paid = 0
                if paid > total:
                    paid = total
                pm_label = (payment_method_label or "").strip() or ("محفظة إلكترونية" if method == "wallet" else "نقدي")
                pm_note = (payment_plan_note or "").strip() or None

            if id:
                qid = _int(id)
                existing = conn.execute("SELECT * FROM quotations WHERE id=?", (qid,)).fetchone()
                if not existing:
                    raise ApiError("المستند غير موجود")
                self._scope_check(existing["user_id"], "history_view_all", err_msg="ممنوع: لا يمكنك تعديل مستندات موظف آخر")
                if existing["status"] == "converted":
                    raise ApiError("تم تحويل هذا المستند إلى فاتورة مبيعات معتمدة ولا يمكن تعديله كعرض سعر")
                src_val = (source_ref or "").strip() or existing["source_ref"] or f"{src_prefix}{qid:04d}"
                sig_val = (signal_ref or "").strip() or existing["signal_ref"] or src_val
                conn.execute(
                    """UPDATE quotations
                       SET doc_type=?, customer_id=?, customer_name=?, customer_phone=?,
                           doc_date=?, due_date=?, source_ref=?, signal_ref=?,
                           subtotal=?, discount=?, tax=?, total=?, paid_amount=?, payment_method=?, payment_date=?,
                           payment_method_label=?, payment_plan_note=?, payments_json=?, notes=?
                       WHERE id=?""",
                    (
                        doc_type, customer_id, cname, cphone,
                        doc_date, due_date, "", "",
                        subtotal, disc, total_tax, total, paid, method, payment_date,
                        pm_label, pm_note, pm_json,
                        (notes or "").strip() or None, qid,
                    ),
                )
                conn.execute("DELETE FROM quotation_items WHERE quote_id=?", (qid,))
            else:
                cur = conn.execute(
                    """INSERT INTO quotations(quote_no, doc_type, user_id, customer_id, customer_name, customer_phone,
                                              created_at, doc_date, due_date, source_ref, signal_ref,
                                              subtotal, discount, tax, total, paid_amount, payment_method, payment_date,
                                              payment_method_label, payment_plan_note, payments_json, status, notes)
                       VALUES('TMP-Q',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'draft',?)""",
                    (
                        doc_type, u["id"], customer_id, cname, cphone,
                        db.now(), doc_date, due_date, "", "",
                        subtotal, disc, total_tax, total, paid, method, payment_date,
                        pm_label, pm_note, pm_json,
                        (notes or "").strip() or None,
                    ),
                )
                qid = cur.lastrowid
                q_no = _format_doc_seq(inv_prefix if doc_type == 'invoice' else quote_prefix, qid)
                if conn.execute("SELECT 1 FROM quotations WHERE quote_no=? AND id!=?", (q_no, qid)).fetchone():
                    q_no = f"{q_no}-{qid}"
                conn.execute(
                    "UPDATE quotations SET quote_no=?, source_ref=?, signal_ref=? WHERE id=?",
                    (q_no, q_no, q_no, qid),
                )

            for it in parsed_items:
                conn.execute(
                    """INSERT INTO quotation_items(quote_id, product_id, sku, name, qty, unit_price, tax_label, tax_rate, line_total)
                       VALUES(?,?,?,?,?,?,?,?,?)""",
                    (
                        qid, it["product_id"], it["sku"], it["name"],
                        it["qty"], it["unit_price"], it["tax_label"], it["tax_rate"], it["line_total"],
                    ),
                )

            if doc_type == "invoice" or auto_convert:
                q_row = conn.execute("SELECT * FROM quotations WHERE id=?", (qid,)).fetchone()
                q_items = conn.execute("SELECT * FROM quotation_items WHERE quote_id=?", (qid,)).fetchall()
                self._convert_quote_to_sale_in_tx(conn, u, q_row, q_items, paid, method, payment_date, pm_label, pm_note, pm_json)

        return self.quotation(qid)

    def quotation_convert_to_sale(self, id, paid_amount=None, payment_method="cash", payment_date=None, payment_method_label=None, payment_plan_note=None):
        """تحويل عرض سعر قائم إلى فاتورة مبيعات رسمية معتمدة مع خصم المخزون وتسجيل الدفعة والمديونية."""
        u = self._perm("quotes_convert")
        qid = _int(id)
        with db.connect() as conn:
            q_row = conn.execute("SELECT * FROM quotations WHERE id=?", (qid,)).fetchone()
            if not q_row:
                raise ApiError("عرض السعر غير موجود")
            self._scope_check(q_row["user_id"], "history_view_all", err_msg="ممنوع: لا يمكنك تحويل عرض سعر لموظف آخر")
            if q_row["status"] == "converted" and q_row["converted_sale_id"]:
                raise ApiError("تم تحويل عرض السعر هذا مسبقاً إلى فاتورة مبيعات")
            q_items = conn.execute("SELECT * FROM quotation_items WHERE quote_id=?", (qid,)).fetchall()
            if not q_items:
                raise ApiError("عرض السعر لا يحتوي على أصناف")
            self._convert_quote_to_sale_in_tx(conn, u, q_row, q_items, paid_amount, payment_method, payment_date, payment_method_label, payment_plan_note)
        return self.quotation(qid)

    def quotation(self, id):
        """جلب بيانات عرض سعر أو فاتورة مبيعات A4 بالتفصيل."""
        self._perm("quotes_view")
        qid = _int(id)
        with db.connect() as conn:
            r = conn.execute(
                """SELECT q.*, u.name AS user_name
                   FROM quotations q JOIN users u ON u.id=q.user_id
                   WHERE q.id=?""",
                (qid,),
            ).fetchone()
            if not r:
                raise ApiError("المستند غير موجود")
            self._scope_check(r["user_id"], "history_view_all", err_msg="ممنوع: لا يمكنك عرض مستندات موظف آخر")
            d = dict(r)
            d["items"] = [
                dict(x) for x in conn.execute("SELECT * FROM quotation_items WHERE quote_id=? ORDER BY id", (qid,)).fetchall()
            ]
            if d.get("converted_sale_id"):
                s = conn.execute("SELECT id, invoice_no, status, total FROM sales WHERE id=?", (d["converted_sale_id"],)).fetchone()
                if s:
                    direct_paid = conn.execute(
                        "SELECT COALESCE(SUM(amount),0) p FROM payments WHERE sale_id=? AND method IN ('cash','wallet')",
                        (s["id"],),
                    ).fetchone()["p"]
                    voucher_paid = conn.execute(
                        "SELECT COALESCE(SUM(amount),0) v FROM customer_payments WHERE sale_id=?",
                        (s["id"],),
                    ).fetchone()["v"]
                    d["paid_amount"] = min(d["total"], direct_paid + voucher_paid)
                    d["sale_invoice_no"] = s["invoice_no"]
                    d["sale_status"] = s["status"]
            d["due_amount"] = max(0, d["total"] - (d.get("paid_amount") or 0))
            if d.get("payments_json"):
                try:
                    d["payments_list"] = json.loads(d["payments_json"])
                except Exception:
                    d["payments_list"] = []
            else:
                d["payments_list"] = []
            return d

    def quotations(self, doc_type=None, status=None, q=None, limit=100, offset=0):
        """قائمة عروض الأسعار وفواتير المبيعات الرسمية A4 مع إحصائيات شاملة."""
        u = self._perm("quotes_view")
        see_all = self._has_perm("history_view_all")
        limit, offset = _int(limit, 100), _int(offset, 0)
        where, args = ["1=1"], []
        if not see_all:
            where.append("q.user_id=?")
            args.append(u["id"])
        if doc_type in ("quote", "invoice"):
            where.append("q.doc_type=?")
            args.append(doc_type)
        if status:
            where.append("q.status=?")
            args.append(status)
        if q:
            where.append("(q.quote_no LIKE ? OR q.customer_name LIKE ? OR q.customer_phone LIKE ? OR q.source_ref LIKE ?)")
            args += [f"%{q}%"] * 4
        with db.connect() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM quotations q WHERE {' AND '.join(where)}", args
            ).fetchone()[0]
            rows = conn.execute(
                f"""SELECT q.*, u.name AS user_name
                    FROM quotations q JOIN users u ON u.id=q.user_id
                    WHERE {' AND '.join(where)}
                    ORDER BY q.id DESC LIMIT ? OFFSET ?""",
                args + [limit, offset],
            ).fetchall()
            out = []
            for r in rows:
                d = dict(r)
                if d.get("converted_sale_id"):
                    s_row = conn.execute("SELECT invoice_no, status FROM sales WHERE id=?", (d["converted_sale_id"],)).fetchone()
                    if s_row:
                        d["sale_invoice_no"] = s_row["invoice_no"]
                        d["sale_status"] = s_row["status"]
                    direct_paid = conn.execute(
                        "SELECT COALESCE(SUM(amount),0) p FROM payments WHERE sale_id=? AND method IN ('cash','wallet')",
                        (d["converted_sale_id"],),
                    ).fetchone()["p"]
                    voucher_paid = conn.execute(
                        "SELECT COALESCE(SUM(amount),0) v FROM customer_payments WHERE sale_id=?",
                        (d["converted_sale_id"],),
                    ).fetchone()["v"]
                    d["paid_amount"] = min(d["total"], direct_paid + voucher_paid)
                d["due_amount"] = max(0, d["total"] - (d.get("paid_amount") or 0))
                out.append(d)

            sum_user_sql = "" if see_all else " AND user_id=?"
            sum_args = [] if see_all else [u["id"]]
            stats_quotes = conn.execute(
                f"SELECT COUNT(*) n, COALESCE(SUM(total),0) t FROM quotations WHERE doc_type='quote' AND status!='converted'{sum_user_sql}",
                sum_args,
            ).fetchone()
            stats_invs = conn.execute(
                f"SELECT COUNT(*) n, COALESCE(SUM(total),0) t, COALESCE(SUM(paid_amount),0) p FROM quotations WHERE (doc_type='invoice' OR status='converted'){sum_user_sql}",
                sum_args,
            ).fetchone()
            return {
                "rows": out,
                "total": total,
                "summary": {
                    "quotes_count": stats_quotes["n"],
                    "quotes_total": stats_quotes["t"],
                    "invoices_count": stats_invs["n"],
                    "invoices_total": stats_invs["t"],
                    "invoices_paid": stats_invs["p"],
                    "invoices_due": max(0, stats_invs["t"] - stats_invs["p"]),
                },
            }

    def quotation_cancel(self, id):
        """إلغاء عرض سعر (تحويل حالته إلى cancelled) مع منع إلغاء الفواتير المعتمدة حفاظاً على الدورة المالية."""
        self._perm("quotes_cancel_delete")
        qid = _int(id)
        with db.connect() as conn:
            r = conn.execute("SELECT id, user_id, doc_type, status, converted_sale_id FROM quotations WHERE id=?", (qid,)).fetchone()
            if not r:
                raise ApiError("عرض السعر غير موجود")
            self._scope_check(r["user_id"], "history_view_all", err_msg="ممنوع: لا يمكنك إلغاء عرض سعر لموظف آخر")
            if r["doc_type"] == "invoice" or r["status"] == "converted" or r["converted_sale_id"]:
                raise ApiError("لا يمكن إلغاء فاتورة مبيعات معتمدة لأن ذلك يؤثر على الدورة المالية؛ يمكنك عمل استرجاع (مرتجع) من الفاتورة")
            conn.execute("UPDATE quotations SET status='cancelled' WHERE id=?", (qid,))
        return self.quotation(qid)

    def quotation_delete(self, id):
        """حذف عرض سعر غير محول إلى فاتورة مبيعات."""
        self._perm("quotes_cancel_delete")
        qid = _int(id)
        with db.connect() as conn:
            r = conn.execute("SELECT user_id, doc_type, status, converted_sale_id FROM quotations WHERE id=?", (qid,)).fetchone()
            if not r:
                raise ApiError("عرض السعر غير موجود")
            self._scope_check(r["user_id"], "history_view_all", err_msg="ممنوع: لا يمكنك حذف عرض سعر لموظف آخر")
            if r["doc_type"] == "invoice" or r["status"] == "converted" or r["converted_sale_id"]:
                raise ApiError("لا يمكن حذف فاتورة مبيعات معتمدة؛ استخدم شاشة المرتجعات عند الحاجة")
            conn.execute("DELETE FROM quotations WHERE id=?", (qid,))
            return True

    def whatsapp_send_quote(self, quote_id, phone=None, pdf_image=None, img_w=1240, img_h=1754):
        """إنشاء ملف PDF A4 لعرض السعر أو فاتورة المبيعات ونسخه للحافظة وفتح واتساب مع الإرفاق التلقائي السريع."""
        import base64
        import urllib.parse
        import webbrowser

        self._perm("pos_whatsapp")

        with db.connect() as conn:
            st = self._settings(conn)
            if str(st.get("whatsapp_send_enabled", "1")).strip() == "0":
                raise ApiError("إرسال WhatsApp معطّل من قبل المدير")
            tpl_a4 = self._load_templates(conn)["a4"]

        d = self.quotation(quote_id)

        raw_phone = (phone or d.get("customer_phone") or "").strip()
        digits = "".join(ch for ch in raw_phone if ch.isdigit())
        if not digits:
            raise ApiError("يرجى إدخال رقم موبايل العميل (مثال: 010xxxxxxxx) لإرسال ملف الـ PDF عبر واتساب")
        if digits.startswith("00"):
            digits = digits[2:]
        elif digits.startswith("01") and len(digits) == 11:
            digits = "2" + digits
        elif not digits.startswith("20") and len(digits) == 10:
            digits = "20" + digits

        store_name = (tpl_a4.get("company_title") or st.get("store_name") or "تك زون للإلكترونيات").strip()
        cur = (tpl_a4.get("currency_symbol") or st.get("currency") or "LE").strip()
        is_inv = d["doc_type"] == "invoice" or d["status"] == "converted"
        doc_label = "فاتورة مبيعات" if is_inv else "عرض سعر"
        cust_part = f" أ/ {d['customer_name']}" if d.get("customer_name") else ""

        msg_lines = [
            f"مرحباً{cust_part}،",
            f"لديك {doc_label} من *{store_name}*",
            f"الرقم: *{d['quote_no']}*",
            f"التاريخ: {d.get('doc_date') or d['created_at'][:10]}",
            f"الإجمالي: *{cur} {_fmt_money(d['total'])}*",
        ]
        if is_inv and d.get("due_amount", 0) > 0:
            msg_lines.append(f"المدفوع: {cur} {_fmt_money(d['paid_amount'])} | المتبقي المستحق: *{cur} {_fmt_money(d['due_amount'])}*")
        msg_lines.append(f"مرفق ملف الـ PDF ({doc_label}).")
        msg_text = "\n".join(msg_lines)
        encoded_text = urllib.parse.quote(msg_text)

        jpeg_bytes = _FALLBACK_JPEG
        if pdf_image and isinstance(pdf_image, str) and "," in pdf_image:
            try:
                b64_part = pdf_image.split(",", 1)[1]
                decoded = base64.b64decode(b64_part)
                if decoded.startswith(b"\xff\xd8"):
                    jpeg_bytes = decoded
            except Exception:
                pass

        pdf_bytes = _jpeg_to_pdf_bytes(jpeg_bytes, _int(img_w, 1240), _int(img_h, 1754))
        receipts_dir = pathlib.Path(db.db_path()).resolve().parent / "receipts"
        receipts_dir.mkdir(parents=True, exist_ok=True)
        safe_name = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in d["quote_no"])
        pdf_file = receipts_dir / f"{safe_name}.pdf"
        pdf_file.write_bytes(pdf_bytes)

        pdf_abs = str(pdf_file.resolve())
        wa_proto = f"whatsapp://send?phone={digits}&text={encoded_text}"
        wa_web = f"https://web.whatsapp.com/send?phone={digits}&text={encoded_text}"
        opened = False

        if os.name == "nt":
            import threading
            was_already_open = _find_whatsapp_hwnd() is not None
            _win32_copy_pdf_to_clipboard(pdf_abs)
            try:
                os.startfile(wa_proto)
                opened = True
            except OSError:
                try:
                    webbrowser.open(wa_web)
                    opened = True
                except Exception:
                    opened = False
            if opened:
                threading.Thread(
                    target=_win32_auto_paste_into_whatsapp,
                    args=(pdf_abs, was_already_open),
                    daemon=True,
                ).start()

        if not opened:
            try:
                webbrowser.open(wa_web)
                opened = True
            except Exception:
                pass

        return {
            "phone": digits,
            "store_name": store_name,
            "message": msg_text,
            "pdf_file": pdf_abs,
            "pdf_name": pdf_file.name,
            "pdf_dir": str(pdf_file.parent.resolve()),
            "opened": opened,
        }
