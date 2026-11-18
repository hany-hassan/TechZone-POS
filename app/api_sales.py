"""الورديات، نقاط البيع، الفواتير، المرتجعات، وإرسال واتساب."""
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
    _sale_net_credit,
    _sync_sale_ledger_delta,
    _upsert_customer,
    _validate_image_data_url,
    _win32_auto_paste_into_whatsapp,
    _win32_copy_pdf_to_clipboard,
    _find_whatsapp_hwnd,
)


class SalesMixin:
    # ---------------------------------------------------------- ورديات
    def shift(self):
        u = self._perm_any("pos_sell", "shift_manage", "shift_summary_view", "history_view_own", "history_view_all", "reports_sales_view")
        see_all = self._has_perm("history_view_all") or self._has_perm("reports_sales_view")
        see_own = see_all or self._has_perm("shift_summary_view") or self._has_perm("history_view_own")
        with db.connect() as conn:
            s = self._open_shift(conn, u["id"])
            today_data = None
            shift_sales = None
            if see_all:
                today = conn.execute(
                    """SELECT COUNT(*) n, COALESCE(SUM(total),0) t FROM sales
                       WHERE created_at >= date('now','localtime')""",
                ).fetchone()
                today_data = {"count": today["n"], "total": today["t"]}
            elif see_own:
                today = conn.execute(
                    """SELECT COUNT(*) n, COALESCE(SUM(total),0) t FROM sales
                       WHERE user_id=? AND created_at >= date('now','localtime')""",
                    (u["id"],),
                ).fetchone()
                today_data = {"count": today["n"], "total": today["t"]}
            if s and see_own:
                shift_sales = conn.execute(
                    "SELECT COUNT(*) n, COALESCE(SUM(total),0) t FROM sales WHERE shift_id=?", (s["id"],)
                ).fetchone()
            return {
                "shift": dict(s) if s else None,
                "today": today_data,
                "shift_sales": dict(shift_sales) if shift_sales else None,
            }

    def shift_summary(self):
        """تقرير تفصيلي كامل للوردية المفتوحة قبل إغلاقها (جميع العمليات وتفصيل النقدي والمحفظة والآجل)."""
        u = self._perm("shift_summary_view")
        with db.connect() as conn:
            s = self._open_shift(conn, u["id"])
            if not s:
                raise ApiError("لا توجد وردية مفتوحة حالياً")
            sid = s["id"]
            sales_rows = conn.execute(
                """SELECT s.id, s.invoice_no, s.created_at, s.customer_name, s.total, s.status
                   FROM sales s WHERE s.shift_id=? ORDER BY s.id DESC""",
                (sid,),
            ).fetchall()

            pays_by_method = {"cash": 0, "wallet": 0, "credit": 0}
            for r in conn.execute(
                """SELECT p.method, COALESCE(SUM(p.amount),0) t FROM payments p
                   JOIN sales s ON s.id=p.sale_id WHERE s.shift_id=? GROUP BY p.method""",
                (sid,),
            ).fetchall():
                pays_by_method[r["method"]] = r["t"]

            ret_row = conn.execute(
                """SELECT COUNT(*) n, COALESCE(SUM(sr.total),0) t FROM sale_returns sr
                   JOIN sales s ON s.id=sr.sale_id WHERE s.shift_id=?""",
                (sid,),
            ).fetchone()

            vouchers_rows = conn.execute(
                """SELECT cp.*, c.name AS customer_name FROM customer_payments cp
                   LEFT JOIN customers c ON c.id=cp.customer_id
                   WHERE cp.shift_id=? ORDER BY cp.id DESC""",
                (sid,),
            ).fetchall()
            cash_vouchers = sum(v["amount"] for v in vouchers_rows if v["method"] == "cash")
            wallet_vouchers = sum(v["amount"] for v in vouchers_rows if v["method"] == "wallet")

            inst_pay_rows = conn.execute(
                """SELECT ip.*, c.name AS customer_name, p.plan_no
                   FROM installment_payments ip
                   JOIN installment_plans p ON p.id=ip.plan_id
                   LEFT JOIN customers c ON c.id=ip.customer_id
                   WHERE ip.shift_id=? ORDER BY ip.id DESC""",
                (sid,),
            ).fetchall()
            cash_inst = sum(r["amount"] for r in inst_pay_rows if r["method"] == "cash")
            wallet_inst = sum(r["amount"] for r in inst_pay_rows if r["method"] == "wallet")

            inst_down_rows = conn.execute(
                """SELECT p.*, c.name AS customer_name
                   FROM installment_plans p
                   LEFT JOIN customers c ON c.id=p.customer_id
                   WHERE p.shift_id=? AND p.sale_id IS NULL AND p.status != 'cancelled' AND p.down_payment > 0
                   ORDER BY p.id DESC""",
                (sid,),
            ).fetchall()
            cash_inst += sum(r["down_payment"] for r in inst_down_rows if r["down_method"] == "cash")
            wallet_inst += sum(r["down_payment"] for r in inst_down_rows if r["down_method"] == "wallet")

            # جمع مدفوعات كل المبيعات دفعة واحدة (تجنب N+1)
            sale_ids = [sr["id"] for sr in sales_rows]
            pays_map = {}
            if sale_ids:
                placeholders = ",".join("?" for _ in sale_ids)
                for p in conn.execute(
                    f"SELECT sale_id, method, amount, ref_no FROM payments WHERE sale_id IN ({placeholders})",
                    sale_ids,
                ).fetchall():
                    pays_map.setdefault(p["sale_id"], []).append(p)

            ops = []
            for sr in sales_rows:
                spays = pays_map.get(sr["id"], [])
                m_labels = []
                for p in spays:
                    lbl = {"cash": "نقدي", "wallet": "محفظة", "credit": "آجل"}.get(p["method"], p["method"])
                    if p["ref_no"]:
                        lbl += f" ({p['ref_no']})"
                    m_labels.append(f"{lbl}: {_fmt_money(p['amount'])}")
                ops.append({
                    "kind": "sale",
                    "ref": sr["invoice_no"],
                    "created_at": sr["created_at"],
                    "party": sr["customer_name"] or "عميل نقدي",
                    "amount": sr["total"],
                    "methods_summary": " + ".join(m_labels) if m_labels else "—",
                    "status": sr["status"],
                })
            for vr in vouchers_rows:
                lbl = "سند قبض نقدي" if vr["method"] == "cash" else f"سند قبض محفظة ({vr['ref_no'] or ''})"
                ops.append({
                    "kind": "voucher",
                    "ref": vr["ref"],
                    "created_at": vr["created_at"],
                    "party": vr["customer_name"] or "عميل",
                    "amount": vr["amount"],
                    "methods_summary": lbl,
                    "status": "completed",
                })
            for ir in inst_pay_rows:
                lbl = "تحصيل قسط نقدي" if ir["method"] == "cash" else f"تحصيل قسط محفظة ({ir['ref_no'] or ''})"
                ops.append({
                    "kind": "installment_payment",
                    "ref": ir["receipt_no"],
                    "created_at": ir["created_at"],
                    "party": ir["customer_name"] or "عميل",
                    "amount": ir["amount"],
                    "methods_summary": f"{lbl} ({ir['plan_no']})",
                    "status": "completed",
                })
            for idr in inst_down_rows:
                lbl = "مقدم تقسيط نقدي" if idr["down_method"] == "cash" else f"مقدم تقسيط محفظة ({idr['down_ref_no'] or ''})"
                ops.append({
                    "kind": "installment_down",
                    "ref": idr["plan_no"],
                    "created_at": idr["created_at"],
                    "party": idr["customer_name"] or "عميل",
                    "amount": idr["down_payment"],
                    "methods_summary": lbl,
                    "status": "completed",
                })
            ops.sort(key=lambda x: x["created_at"], reverse=True)

            expected_cash = s["opening_cash"] + pays_by_method["cash"] + cash_vouchers + cash_inst
            sales_total = sum(sr["total"] for sr in sales_rows)
            return {
                "shift": dict(s),
                "opening_cash": s["opening_cash"],
                "sales_count": len(sales_rows),
                "sales_total": sales_total,
                "returns_count": ret_row["n"],
                "returns_total": ret_row["t"],
                "cash_sales": pays_by_method["cash"],
                "wallet_sales": pays_by_method["wallet"],
                "credit_sales": pays_by_method["credit"],
                "cash_vouchers": cash_vouchers,
                "wallet_vouchers": wallet_vouchers,
                "cash_installments": cash_inst,
                "wallet_installments": wallet_inst,
                "expected_cash": expected_cash,
                "operations": ops,
            }

    def shift_open(self, opening_cash=0):
        u = self._perm("shift_manage")
        with db.connect() as conn:
            if self._open_shift(conn, u["id"]):
                raise ApiError("توجد وردية مفتوحة بالفعل")
            cur = conn.execute(
                "INSERT INTO shifts(user_id, opened_at, opening_cash) VALUES(?,?,?)",
                (u["id"], db.now(), _money(opening_cash)),
            )
            return dict(conn.execute("SELECT * FROM shifts WHERE id=?", (cur.lastrowid,)).fetchone())

    def shift_close(self, counted_cash):
        u = self._perm("shift_manage")
        can_see_summary = self._has_perm("shift_summary_view")
        with db.connect() as conn:
            s = self._open_shift(conn, u["id"])
            if not s:
                raise ApiError("لا توجد وردية مفتوحة")
            cash_sales = conn.execute(
                """SELECT COALESCE(SUM(amount),0) c FROM payments
                   JOIN sales ON sales.id=payments.sale_id
                   WHERE sales.shift_id=? AND payments.method='cash'""",
                (s["id"],),
            ).fetchone()["c"]
            cash_vouchers = conn.execute(
                """SELECT COALESCE(SUM(amount),0) c FROM customer_payments
                   WHERE shift_id=? AND method='cash'""",
                (s["id"],),
            ).fetchone()["c"]
            cash_inst = conn.execute(
                """SELECT COALESCE(SUM(amount),0) c FROM installment_payments
                   WHERE shift_id=? AND method='cash'""",
                (s["id"],),
            ).fetchone()["c"]
            cash_inst += conn.execute(
                """SELECT COALESCE(SUM(down_payment),0) c FROM installment_plans
                   WHERE shift_id=? AND sale_id IS NULL AND status != 'cancelled'
                     AND down_payment > 0 AND down_method='cash'""",
                (s["id"],),
            ).fetchone()["c"]
            expected = s["opening_cash"] + cash_sales + cash_vouchers + cash_inst
            counted = _money(counted_cash)
            conn.execute(
                "UPDATE shifts SET closed_at=?, counted_cash=?, expected_cash=?, diff=? WHERE id=?",
                (db.now(), counted, expected, counted - expected, s["id"]),
            )
            erp_hooks.on_shift_closed(self, conn, s["id"], counted - expected, user=u)
            res = dict(conn.execute("SELECT * FROM shifts WHERE id=?", (s["id"],)).fetchone())
        # أخذ نسخة احتياطية تلقائية لقاعدة البيانات عند إغلاق كل وردية
        try:
            db.backup_database("shift_close")
        except Exception:
            pass
        if not can_see_summary:
            return {
                "id": res["id"],
                "opened_at": res["opened_at"],
                "closed_at": res["closed_at"],
                "counted_cash": res["counted_cash"],
                "blind": True,
            }
        return res

    def shifts(self):
        self._perm("reports_shifts_view")
        with db.connect() as conn:
            rows = conn.execute(
                """SELECT s.*, u.name user_name,
                          (SELECT COALESCE(SUM(total),0) FROM sales WHERE shift_id=s.id) sales_total
                   FROM shifts s JOIN users u ON u.id=s.user_id
                   ORDER BY s.id DESC LIMIT 50"""
            ).fetchall()
            return [dict(r) for r in rows]

    # ---------------------------------------------------------- مبيعات
    def sale_create(self, items, discount=0, payments=None, customer_name=None, customer_phone=None, notes=None):
        u = self._perm("pos_sell")
        can_edit_price = self._has_perm("pos_price")
        can_item_disc = self._has_perm("pos_item_discount")
        can_inv_disc = self._has_perm("pos_invoice_discount")
        can_credit = self._has_perm("pos_credit_sale")
        items = items or []
        if not items:
            raise ApiError("السلة فارغة")
        payments = payments or []
        customer_name = (customer_name or "").strip() or None
        customer_phone = (customer_phone or "").strip() or None
        with db.connect() as conn:
            s = self._open_shift(conn, u["id"])
            if not s:
                raise ApiError("لا يمكن البيع بدون وردية مفتوحة — افتح وردية أولاً")
            st = self._settings(conn)
            tax_enabled = st.get("tax_enabled", "1") != "0"
            rate = int(Decimal(st.get("tax_rate", "14") or 0)) if tax_enabled else 0

            has_credit = any((p.get("method") == "credit" and _money(p.get("amount"), 0) > 0) for p in payments)
            if has_credit and not can_credit:
                raise ApiError("ممنوع: ليست لديك صلاحية البيع الآجل وتسجيل مديونيات على العملاء")
            if has_credit and not customer_name:
                raise ApiError("لا يمكن البيع الآجل بدون اختيار أو إدخال اسم العميل")

            customer_id = _upsert_customer(conn, customer_name, customer_phone) if customer_name else None

            lines = []
            for it in items:
                pid = _int(it.get("product_id"))
                qty = _int(it.get("qty", 1))
                if qty <= 0:
                    raise ApiError("كمية غير صالحة")
                p = conn.execute("SELECT * FROM products WHERE id=? AND active=1", (pid,)).fetchone()
                if not p:
                    raise ApiError("منتج غير موجود في السلة")
                up = it.get("unit_price")
                unit = p["price"]
                if up is not None:
                    req_unit = _money(up)
                    if req_unit < 0:
                        raise ApiError("سعر الوحدة بعد الخصم لا يمكن أن يكون سالباً")
                    if req_unit != p["price"]:
                        if req_unit < p["price"] and (can_edit_price or can_item_disc):
                            unit = req_unit
                        elif req_unit > p["price"] and can_edit_price:
                            unit = req_unit
                        else:
                            raise ApiError("ممنوع: ليست لديك صلاحية تعديل سعر الصنف أو عمل خصم عليه")
                if p["tracked"]:
                    serial_ids = it.get("serial_ids") or []
                    if len(serial_ids) != qty:
                        raise ApiError(f"منتج متتبّع بالسيريال: يتطلب {qty} رقم تسلسلي متاح")
                    srows = conn.execute(
                        "SELECT * FROM serials WHERE product_id=? AND id IN (%s)" % ",".join("?" * qty),
                        [pid] + [_int(x) for x in serial_ids],
                    ).fetchall()
                    if len(srows) != qty or any(r["status"] != "in_stock" for r in srows):
                        raise ApiError("أحد الأرقام التسلسلية غير متاح")
                    for r in srows:
                        lines.append((p, 1, unit, [r["id"]]))
                else:
                    if p["qty"] < qty:
                        raise ApiError(f"مخزون غير كافٍ لـ {p['name']} (المتوفر {p['qty']})")
                    lines.append((p, qty, unit, []))

            discount = _money(discount)
            if discount > 0 and not can_inv_disc:
                raise ApiError("ممنوع: ليست لديك صلاحية عمل خصم على إجمالي الفاتورة")
            subtotal = sum(q * up for _, q, up, _ in lines)
            if discount < 0 or discount > subtotal:
                raise ApiError("قيمة الخصم غير صالحة")
            taxable = subtotal - discount
            tax = int((Decimal(taxable) * rate / 100).to_integral_value(rounding=ROUND_HALF_UP))
            total = taxable + tax

            got = 0
            pays = []
            for pay in payments:
                method = pay.get("method")
                if method not in ("cash", "wallet", "credit"):
                    raise ApiError("طريقة دفع غير معروفة (نقدي/محفظة/آجل)")
                amount = _money(pay.get("amount"))
                raw_rec = pay.get("received")
                received = _money(raw_rec) if raw_rec not in (None, "") else amount
                ref_no = (pay.get("ref_no") or "").strip() or None
                if amount <= 0:
                    raise ApiError("مبلغ دفع غير صالح")
                if len(payments) == 1 and method == "cash" and amount > total:
                    received = max(received, amount)
                    amount = total
                if method == "cash" and received < amount:
                    raise ApiError("المبلغ المستلم أقل من مبلغ الدفع النقدي")
                if method == "wallet" and not ref_no:
                    raise ApiError("يرجى إدخال رقم العملية المرجعية لتحويل المحفظة")
                pays.append((method, amount, received, max(0, received - amount), ref_no))
                got += amount
            if got != total:
                raise ApiError(f"مجموع الدفعات ({_fmt_money(got)}) لا يساوي الإجمالي ({_fmt_money(total)})")

            cur = conn.execute(
                """INSERT INTO sales(invoice_no, shift_id, user_id, customer_id, created_at, customer_name, customer_phone,
                                     subtotal, discount, tax, total, notes)
                    VALUES('INV-00000',?,?,?,?,?,?,?,?,?,?,?)""",
                (s["id"], u["id"], customer_id, db.now(), customer_name, customer_phone,
                 subtotal, discount, tax, total, notes),
            )
            sale_id = cur.lastrowid
            pos_tpl = self._load_templates(conn)["pos"]
            pos_prefix = (pos_tpl.get("pos_invoice_prefix") or "INV-").strip() or "INV-"
            invoice = _format_doc_seq(pos_prefix, sale_id)
            if conn.execute("SELECT 1 FROM sales WHERE invoice_no=? AND id!=?", (invoice, sale_id)).fetchone():
                invoice = f"{invoice}-{sale_id}"
            conn.execute("UPDATE sales SET invoice_no=? WHERE id=?", (invoice, sale_id))

            for p, qty, unit, serials in lines:
                sid = serials[0] if serials else None
                conn.execute(
                    """INSERT INTO sale_items(sale_id, product_id, serial_id, name, qty, unit_price, cost_unit, line_total)
                       VALUES(?,?,?,?,?,?,?,?)""",
                    (sale_id, p["id"], sid, p["name"], qty, unit, int(p["cost"] or 0), unit * qty),
                )
                if serials:
                    conn.execute(
                        "UPDATE serials SET status='sold' WHERE id IN (%s)" % ",".join("?" * len(serials)),
                        serials,
                    )
                conn.execute("UPDATE products SET qty=qty-? WHERE id=?", (qty, p["id"]))
                after = conn.execute("SELECT qty FROM products WHERE id=?", (p["id"],)).fetchone()[0]
                conn.execute(
                    """INSERT INTO stock_movements(created_at, user_id, product_id, qty_change, qty_after, reason, ref)
                       VALUES(?,?,?,?,?,?,?)""",
                    (db.now(), u["id"], p["id"], -qty, after, "sale", invoice),
                )
            for method, amount, received, change, ref_no in pays:
                conn.execute(
                    "INSERT INTO payments(sale_id, method, amount, received, change, ref_no) VALUES(?,?,?,?,?,?)",
                    (sale_id, method, amount, received, change, ref_no),
                )
            if customer_id:
                credit_amt = sum(amount for method, amount, _rec, _chg, _ref in pays if method == "credit")
                if credit_amt > 0:
                    _append_ledger_entry(
                        conn,
                        customer_id,
                        "credit_sale",
                        invoice,
                        debit=credit_amt,
                        sale_id=sale_id,
                        method="credit",
                        notes=f"فاتورة آجلة ({invoice})",
                        user_id=u["id"],
                        user_name=u["name"],
                    )
                else:
                    _refresh_customer_cache(conn, customer_id)
            erp_hooks.on_sale_created(self, conn, sale_id, user=u)
            return {"sale_id": sale_id, "invoice_no": invoice}

    def sale(self, id):
        u = self._perm_any("pos_sell", "receipt_view", "history_view_own", "history_view_all", "sales_return", "sales_return_own", "sales_post_discount")
        with db.connect() as conn:
            r = conn.execute(
                """SELECT s.*, u.name user_name FROM sales s JOIN users u ON u.id=s.user_id WHERE s.id=?""",
                (_int(id),),
            ).fetchone()
            if not r:
                raise ApiError("الفاتورة غير موجودة")
            if r["user_id"] != u["id"] and not (self._has_perm("history_view_all") or self._has_perm("sales_return")):
                raise ApiError("ممنوع: لا يمكنك عرض فواتير موظفين آخرين")
            items_raw = [dict(x) for x in conn.execute(
                """SELECT si.*, COALESCE(NULLIF(si.sku, ''), p.sku, '') AS sku, p.image, p.price AS catalog_price, p.tracked
                   FROM sale_items si LEFT JOIN products p ON p.id=si.product_id
                   WHERE si.sale_id=?""",
                (r["id"],),
            ).fetchall()]
            # جمع المرتجعات دفعة واحدة
            item_ids = [it["id"] for it in items_raw]
            returned_map = {}
            if item_ids:
                placeholders = ",".join("?" for _ in item_ids)
                for row in conn.execute(
                    f"SELECT sale_item_id, COALESCE(SUM(qty),0) q FROM sale_return_items WHERE sale_item_id IN ({placeholders}) GROUP BY sale_item_id",
                    item_ids,
                ).fetchall():
                    returned_map[row["sale_item_id"]] = row["q"]
            items = []
            for it in items_raw:
                returned_qty = returned_map.get(it["id"], 0)
                it["returned_qty"] = returned_qty
                it["remaining_qty"] = max(0, it["qty"] - returned_qty)
                items.append(it)
            pays = [dict(x) for x in conn.execute("SELECT * FROM payments WHERE sale_id=?", (r["id"],))]
            returns_log = [
                dict(x) for x in conn.execute(
                    """SELECT sr.*, u.name AS user_name
                       FROM sale_returns sr JOIN users u ON u.id=sr.user_id
                       WHERE sr.sale_id=? ORDER BY sr.id DESC""",
                    (r["id"],),
                )
            ]
            d = dict(r)
            d["items"] = items
            d["payments"] = pays
            d["returns_log"] = returns_log
            direct_paid = sum(p["amount"] for p in pays if p["method"] in ("cash", "wallet"))
            voucher_paid = conn.execute(
                "SELECT COALESCE(SUM(amount),0) v FROM customer_payments WHERE sale_id=?",
                (r["id"],),
            ).fetchone()["v"]
            d["paid_amount"] = min(d["total"], direct_paid + voucher_paid)
            d["due_amount"] = max(0, d["total"] - d["paid_amount"])
            return d

    def sale_discount(self, sale_id, discount=0):
        """تعديل أو إضافة خصم على فاتورة تم دفعها (يتطلب صلاحية الخصم بعد البيع)."""
        u = self._perm("sales_post_discount")
        sid = _int(sale_id)
        disc = _money(discount)
        with db.connect() as conn:
            s = conn.execute("SELECT * FROM sales WHERE id=?", (sid,)).fetchone()
            if not s:
                raise ApiError("الفاتورة غير موجودة")
            if s["user_id"] != u["id"] and not self._has_perm("history_view_all"):
                raise ApiError("ممنوع: لا يمكنك تعديل خصم فاتورة موظف آخر")
            if disc < 0 or disc > s["subtotal"]:
                raise ApiError("قيمة الخصم غير صالحة (يجب ألا تتجاوز المجموع الفرعي)")
            prev_net_credit = _sale_net_credit(conn, sid)
            tax_rate = Decimal(0)
            if s["tax"] > 0 and (s["subtotal"] - s["discount"]) > 0:
                st = self._settings(conn)
                tax_rate = Decimal(st.get("tax_rate", "14") or 0)
            taxable = s["subtotal"] - disc
            new_tax = int((Decimal(taxable) * tax_rate / 100).to_integral_value(rounding=ROUND_HALF_UP))
            new_total = taxable + new_tax
            diff = s["total"] - new_total
            now_ts = db.now()
            log_line = f"[{now_ts}] بواسطة {u['name']}: تعديل خصم الفاتورة إلى {_fmt_money(disc)}"
            prev_log = (s["modification_summary"] or "").strip() if "modification_summary" in s.keys() else ""
            full_log = (prev_log + " | " + log_line) if prev_log else log_line
            conn.execute(
                "UPDATE sales SET discount=?, tax=?, total=?, modified_by=?, modified_by_name=?, modified_at=?, modification_summary=? WHERE id=?",
                (disc, new_tax, new_total, u["id"], u["name"], now_ts, full_log, sid),
            )
            if diff != 0:
                first_pay = conn.execute("SELECT * FROM payments WHERE sale_id=? ORDER BY id LIMIT 1", (sid,)).fetchone()
                if first_pay:
                    new_amt = max(0, first_pay["amount"] - diff)
                    conn.execute("UPDATE payments SET amount=? WHERE id=?", (new_amt, first_pay["id"]))
            _sync_sale_ledger_delta(conn, s, prev_net_credit, user=u, reason_prefix="خصم على فاتورة آجلة")
            return {"sale_id": sid, "discount": disc, "total": new_total, "modified_by_name": u["name"], "modified_at": now_ts}

    def sale_modify_from_cart(self, sale_id, items=None, discount=0, notes=None, reason=None):
        """حفظ تعديل / مرتجع فاتورة مدفوعة من داخل سلة المشتريات مع توثيق المستخدم والوقت لمنع التلاعب."""
        u = self._perm_any("sales_return", "sales_return_own", "sales_post_discount", "pos_item_discount", "pos_price")
        sid = _int(sale_id)
        items = items or []
        sub_map = {_int(it.get("sale_item_id")): it for it in items if it.get("sale_item_id")}
        with db.connect() as conn:
            s = conn.execute("SELECT * FROM sales WHERE id=?", (sid,)).fetchone()
            if not s:
                raise ApiError("الفاتورة غير موجودة")
            if s["user_id"] != u["id"] and not (self._has_perm("sales_return") or self._has_perm("history_view_all")):
                raise ApiError("ممنوع: لا يمكنك تعديل فواتير موظفين آخرين")
            if s["status"] == "returned":
                raise ApiError("هذه الفاتورة مرتجعة بالكامل مسبقاً")
            prev_net_credit = _sale_net_credit(conn, sid)

            orig_items = conn.execute("SELECT * FROM sale_items WHERE sale_id=?", (sid,)).fetchall()
            returned_entries = []
            price_changes = []
            now_ts = db.now()

            for si in orig_items:
                item_id = si["id"]
                already_ret = conn.execute(
                    "SELECT COALESCE(SUM(qty),0) q FROM sale_return_items WHERE sale_item_id=?",
                    (item_id,),
                ).fetchone()["q"]
                orig_rem = max(0, si["qty"] - already_ret)
                if orig_rem <= 0:
                    continue

                sub_it = sub_map.get(item_id)
                new_rem = _int(sub_it.get("qty", 0)) if sub_it else 0
                if new_rem < 0 or new_rem > orig_rem:
                    raise ApiError(f"الكمية للصنف «{si['name']}» غير صالحة (المتاح في الفاتورة: {orig_rem})")

                if new_rem < orig_rem:
                    can_ret_this = self._has_perm("sales_return") or (self._has_perm("sales_return_own") and s["user_id"] == u["id"])
                    if not can_ret_this:
                        raise ApiError("ممنوع: ليست لديك صلاحية استرجاع أصناف من هذه الفاتورة")
                    ret_qty = orig_rem - new_rem
                    conn.execute("UPDATE products SET qty=qty+? WHERE id=?", (ret_qty, si["product_id"]))
                    if si["serial_id"]:
                        conn.execute("UPDATE serials SET status='in_stock' WHERE id=?", (si["serial_id"],))
                    after_qty = conn.execute("SELECT qty FROM products WHERE id=?", (si["product_id"],)).fetchone()[0]
                    conn.execute(
                        """INSERT INTO stock_movements(created_at, user_id, product_id, qty_change, qty_after, reason, ref)
                           VALUES(?,?,?,?,?,?,?)""",
                        (now_ts, u["id"], si["product_id"], ret_qty, after_qty, "return", s["invoice_no"]),
                    )
                    ret_amt = si["unit_price"] * ret_qty
                    returned_entries.append((item_id, ret_qty, ret_amt, si["name"]))

                if sub_it and sub_it.get("unit_price") is not None and new_rem > 0:
                    new_up = _money(sub_it.get("unit_price"))
                    if new_up < 0:
                        raise ApiError("سعر الصنف لا يمكن أن يكون سالباً")
                    if new_up != si["unit_price"]:
                        if not (self._has_perm("pos_item_discount") or self._has_perm("pos_price")):
                            raise ApiError("ممنوع: ليست لديك صلاحية تعديل أسعار أو خصم الأصناف")
                        conn.execute(
                            "UPDATE sale_items SET unit_price=?, line_total=qty*? WHERE id=?",
                            (new_up, new_up, item_id),
                        )
                        price_changes.append(f"خصم سعر «{si['name']}» من {_fmt_money(si['unit_price'])} إلى {_fmt_money(new_up)}")

            new_disc = _money(discount)
            if new_disc != s["discount"]:
                if not (self._has_perm("sales_post_discount") or self._has_perm("sales_return") or (self._has_perm("sales_return_own") and s["user_id"] == u["id"])):
                    raise ApiError("ممنوع: ليست لديك صلاحية تعديل خصم الفاتورة")
                price_changes.append(f"تعديل خصم الفاتورة من {_fmt_money(s['discount'])} إلى {_fmt_money(new_disc)}")

            if not returned_entries and not price_changes and (notes or None) == s["notes"]:
                raise ApiError("لم يتم إجراء أي مرتجع أو تعديل على الفاتورة")

            ret_total = 0
            if returned_entries:
                ret_total = sum(x[2] for x in returned_entries)
                cur = conn.execute(
                    "INSERT INTO sale_returns(sale_id, user_id, created_at, reason, total) VALUES(?,?,?,?,?)",
                    (sid, u["id"], now_ts, (reason or "").strip() or "مرتجع من سلة نقاط البيع", ret_total),
                )
                for item_id, r_qty, r_amt, _ in returned_entries:
                    conn.execute(
                        "INSERT INTO sale_return_items(return_id, sale_item_id, qty, amount) VALUES(?,?,?,?)",
                        (cur.lastrowid, item_id, r_qty, r_amt),
                    )

            # إعادة حساب إجمالي الفاتورة للأصناف المتبقية
            updated_items = conn.execute("SELECT * FROM sale_items WHERE sale_id=?", (sid,)).fetchall()
            new_subtotal = 0
            remaining_units = 0
            for si in updated_items:
                alr = conn.execute(
                    "SELECT COALESCE(SUM(qty),0) q FROM sale_return_items WHERE sale_item_id=?",
                    (si["id"],),
                ).fetchone()["q"]
                rem = max(0, si["qty"] - alr)
                remaining_units += rem
                new_subtotal += si["qty"] * si["unit_price"]

            if new_disc < 0 or new_disc > new_subtotal:
                new_disc = min(max(0, new_disc), new_subtotal)

            tax_rate = Decimal(0)
            if s["tax"] > 0 and (s["subtotal"] - s["discount"]) > 0:
                st = self._settings(conn)
                tax_rate = Decimal(st.get("tax_rate", "14") or 0)
            taxable = max(0, new_subtotal - new_disc)
            new_tax = int((Decimal(taxable) * tax_rate / 100).to_integral_value(rounding=ROUND_HALF_UP))
            new_total = taxable + new_tax

            total_ret_ever = conn.execute(
                "SELECT COALESCE(SUM(total),0) t FROM sale_returns WHERE sale_id=?", (sid,)
            ).fetchone()["t"]
            new_status = "returned" if remaining_units == 0 else ("partial_return" if (total_ret_ever > 0 or price_changes) else s["status"])

            log_parts = []
            if returned_entries:
                log_parts.append("مرتجع (" + "، ".join(f"{nm} ×{rq}" for _, rq, _, nm in returned_entries) + ")")
            if price_changes:
                log_parts.extend(price_changes)
            if reason and reason.strip():
                log_parts.append(f"السبب: {reason.strip()}")
            log_line = f"[{now_ts}] بواسطة {u['name']}: " + (" — ".join(log_parts) if log_parts else "تعديل فاتورة")
            prev_log = (s["modification_summary"] or "").strip() if "modification_summary" in s.keys() else ""
            full_log = (prev_log + " | " + log_line) if prev_log else log_line

            conn.execute(
                """UPDATE sales
                   SET subtotal=?, discount=?, tax=?, total=?, status=?, notes=?,
                       modified_by=?, modified_by_name=?, modified_at=?, modification_summary=?
                   WHERE id=?""",
                (new_subtotal, new_disc, new_tax, new_total, new_status,
                 (notes or "").strip() or s["notes"], u["id"], u["name"], now_ts, full_log, sid),
            )
            _sync_sale_ledger_delta(conn, s, prev_net_credit, user=u, reason_prefix="تعديل فاتورة آجلة")
            return {
                "sale_id": sid,
                "invoice_no": s["invoice_no"],
                "status": new_status,
                "total": new_total,
                "returned_total": ret_total,
                "net_after_returns": max(0, new_total - total_ret_ever),
                "modified_by_name": u["name"],
                "modified_at": now_ts,
                "modification_summary": full_log,
            }

    def receipt_text(self, id):
        """نص إيصال 80 عموداً للطابعة الحرارية."""
        d = self.sale(id)
        with db.connect() as conn:
            st = self._settings(conn)
        name, cur = st.get("store_name", "تك زون للإلكترونيات"), st.get("currency", "ج.م")
        tax_enabled = st.get("tax_enabled", "1") != "0"
        show_tax = tax_enabled and (st.get("receipt_show_tax", "1") != "0")
        show_pays = st.get("receipt_show_payments", "1") != "0"
        thanks = st.get("receipt_thanks") or "شكراً لزيارتكم"
        footer = st.get("receipt_footer") or "يرجى الاحتفاظ بالإيصال للاستبدال"
        W = 80
        L = []
        sep = lambda ch: ch * W

        def center(s):
            s = s[:W]
            return s.center(W)[:W]

        L.append(sep("="))
        L.append(center(name))
        if st.get("store_address"):
            L.append(center(st.get("store_address", "")))
        if st.get("store_phone"):
            L.append(center(f"هاتف: {st.get('store_phone', '')}"))
        if st.get("store_email"):
            L.append(center(st.get("store_email", "")))
        if st.get("store_cr"):
            L.append(center(f"سجل تجاري: {st.get('store_cr', '')}"))
        if st.get("store_vat"):
            L.append(center(f"الرقم الضريبي: {st.get('store_vat', '')}"))
        L.append(sep("="))
        dt = datetime.datetime.strptime(d["created_at"], "%Y-%m-%d %H:%M:%S")
        L.append(f"فاتورة: {d['invoice_no']}".ljust(40) + f"التاريخ: {dt:%d/%m/%Y}".rjust(40))
        L.append(f"الكاشير: {d['user_name']}".ljust(40) + f"الوقت: {dt:%H:%M}".rjust(40))
        if d["customer_name"]:
            L.append("العميل: " + str(d["customer_name"]))
        L.append(sep("-"))
        L.append(f"{'الصنف':<34}{'الكمية':>10}{'السعر':>20}")
        L.append(sep("-"))
        for it in d["items"]:
            nm = it["name"][:32]
            L.append(f"{nm:<34}{it['qty']:>10}{_fmt_money(it['line_total']):>20}")
        L.append(sep("-"))
        L.append(f"{'المجموع الفرعي':<40}{_fmt_money(d['subtotal']):>20}")
        if d["discount"]:
            L.append(f"{'الخصم':<40}{('-' + _fmt_money(d['discount'])):>20}")
        if show_tax and d["tax"]:
            L.append(f"{'ضريبة القيمة المضافة':<40}{_fmt_money(d['tax']):>20}")
        L.append(sep("="))
        L.append(f"{'الإجمالي':<40}{(_fmt_money(d['total']) + ' ' + cur):>20}")
        if show_pays:
            method_ar = {"cash": "نقدي", "wallet": "محفظة", "credit": "آجل"}
            for p in d["payments"]:
                extra = f" (المستلم: {_fmt_money(p['received'])})" if p["received"] > p["amount"] else ""
                ref_part = f" [مرجع: {p['ref_no']}]" if p.get("ref_no") else ""
                L.append(f"الدفع: {method_ar.get(p['method'], p['method'])} {_fmt_money(p['amount'])}{extra}{ref_part}")
            change = sum(p["change"] for p in d["payments"])
            if change:
                L.append(f"المتبقي (الباقي): {_fmt_money(change)}")
        L.append(sep("="))
        L.append(center(thanks))
        L.append(center(footer))
        L.append(sep("="))
        return "\n".join(line[:W] for line in L)

    def whatsapp_send_invoice(self, sale_id, phone=None, pdf_image=None, img_w=720, img_h=1050):
        """إنشاء ملف الفاتورة PDF ونسخه للحافظة وفتح واتساب مع رسالة ترحيب باسم الشركة من الإعدادات وإرفاق الملف."""
        import base64
        import subprocess
        import urllib.parse
        import webbrowser

        self._perm("pos_whatsapp")

        with db.connect() as conn:
            st = self._settings(conn)
            if str(st.get("whatsapp_send_enabled", "1")).strip() == "0":
                raise ApiError("إرسال WhatsApp معطّل من قبل المدير")

        d = self.sale(sale_id)
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

        # تجهيز رسالة الفاتورة باسم الشركة كما هو محفوظ في الإعدادات
        store_name = (st.get("store_name") or "تك زون للإلكترونيات").strip()
        cur = (st.get("currency") or "ج.م").strip()
        cust_part = f" أ/ {d['customer_name']}" if d.get("customer_name") else ""
        msg_lines = [
            f"مرحباً{cust_part}،",
            f"لديك فاتورة من *{store_name}*",
            f"رقم الفاتورة: *{d['invoice_no']}*",
            f"التاريخ: {d['created_at'][:16]}",
            f"الإجمالي: *{_fmt_money(d['total'])} {cur}*",
            "مرفق ملف الفاتورة (PDF).",
        ]
        if st.get("receipt_thanks"):
            msg_lines.append(st["receipt_thanks"])
        msg_text = "\n".join(msg_lines)
        encoded_text = urllib.parse.quote(msg_text)

        # 1) استخراج بيانات صورة الفاتورة المولدة من Canvas وتحويلها إلى ملف PDF حقيقي
        jpeg_bytes = _FALLBACK_JPEG
        if pdf_image and isinstance(pdf_image, str) and "," in pdf_image:
            try:
                b64_part = pdf_image.split(",", 1)[1]
                decoded = base64.b64decode(b64_part)
                if decoded.startswith(b"\xff\xd8"):
                    jpeg_bytes = decoded
            except Exception:
                pass

        pdf_bytes = _jpeg_to_pdf_bytes(jpeg_bytes, _int(img_w, 720), _int(img_h, 1050))
        receipts_dir = pathlib.Path(db.db_path()).resolve().parent / "receipts"
        receipts_dir.mkdir(parents=True, exist_ok=True)
        safe_invoice = "".join(c if (c.isalnum() or c in ("-", "_")) else "_" for c in str(d["invoice_no"]))
        if not safe_invoice:
            safe_invoice = f"invoice_{sale_id}"
        pdf_file = receipts_dir / f"{safe_invoice}.pdf"
        pdf_file.write_bytes(pdf_bytes)

        # حفظ نسخة نصية احتياطية أيضاً
        txt_file = receipts_dir / f"{safe_invoice}.txt"
        txt_file.write_text(self.receipt_text(sale_id), encoding="utf-8")

        pdf_abs = str(pdf_file.resolve())
        wa_proto = f"whatsapp://send?phone={digits}&text={encoded_text}"
        wa_web = f"https://web.whatsapp.com/send?phone={digits}&text={encoded_text}"
        opened = False

        # 2) على نظام ويندوز: نسخ ملف الـ PDF للحافظة مباشرة (Win32 CF_HDROP) + فتح محادثة واتساب مع نص الفاتورة + تفعيل خانة الكتابة ولصق الملف تلقائياً
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
            "pdf_dir": str(receipts_dir.resolve()),
            "receipt_file": pdf_abs,
            "opened": opened,
        }

    def _history_date_clause(self, col_prefix, date=None, date_from=None, date_to=None, all_dates=False):
        if str(all_dates).lower() in ("1", "true", "yes"):
            return [], []
        clauses, args = [], []
        df = (date_from or "").strip()
        dt = (date_to or "").strip()
        d = (date or "").strip()
        if df or dt:
            if df:
                clauses.append(f"{col_prefix}created_at >= ?")
                args.append(f"{df} 00:00:00")
            if dt:
                clauses.append(f"{col_prefix}created_at <= ?")
                args.append(f"{dt} 23:59:59")
        elif d:
            clauses.append(f"{col_prefix}created_at LIKE ?")
            args.append(f"{d}%")
        return clauses, args

    def sales(self, date=None, kind=None, q=None, limit=100, offset=0, date_from=None, date_to=None, all_dates=False):
        u = self._perm_any("history_view_own", "history_view_all", "sales_return", "sales_return_own", "sales_post_discount")
        see_all = self._has_perm("history_view_all") or self._has_perm("sales_return")
        can_quotes = self._has_perm("quotes_view")
        can_repairs = self._has_perm("repair_view")
        limit, offset = _int(limit, 100), _int(offset, 0)
        q_str = (q or "").strip()
        k_norm = (kind or "").strip().lower()
        with db.connect() as conn:
            out = []
            include_sales = k_norm in ("", "all", "sale", "pos", "b2b", "invoice", "returned")
            include_quotes = can_quotes and k_norm in ("", "all", "quote", "quotes")
            include_repairs = can_repairs and k_norm in ("", "all", "repair", "repairs")

            if include_sales:
                where, args = ["1=1"], []
                d_cl, d_ar = self._history_date_clause("s.", date=date, date_from=date_from, date_to=date_to, all_dates=all_dates)
                where += d_cl
                args += d_ar
                if k_norm == "pos":
                    where.append("COALESCE(s.doc_type, 'pos') != 'b2b'")
                elif k_norm in ("b2b", "invoice"):
                    where.append("s.doc_type = 'b2b'")
                elif k_norm == "returned":
                    where.append("s.status IN ('returned', 'partial_return')")
                if q_str:
                    where.append("(s.invoice_no LIKE ? OR s.customer_name LIKE ? OR s.customer_phone LIKE ?)")
                    args += [f"%{q_str}%", f"%{q_str}%", f"%{q_str}%"]
                if not see_all:
                    where.append("s.user_id=?")
                    args.append(u["id"])
                base = f"""SELECT s.id, s.invoice_no, s.created_at, u.name user_name,
                                  s.status, s.total, s.discount, s.customer_name, s.customer_phone,
                                  COALESCE(s.doc_type, 'pos') AS doc_type, s.quote_id,
                                  s.modified_by_name, s.modified_at, s.modification_summary
                           FROM sales s JOIN users u ON u.id=s.user_id
                           WHERE {' AND '.join(where)} ORDER BY s.id DESC"""
                for r in conn.execute(base, args).fetchall():
                    row_d = dict(r)
                    row_d["kind"] = "sale"
                    row_d["sub_kind"] = "b2b" if row_d.get("doc_type") == "b2b" else "pos"
                    out.append(row_d)

            if include_quotes:
                where, args = ["q.doc_type = 'quote'", "q.status != 'converted'"], []
                d_cl, d_ar = self._history_date_clause("q.", date=date, date_from=date_from, date_to=date_to, all_dates=all_dates)
                where += d_cl
                args += d_ar
                if q_str:
                    where.append("(q.quote_no LIKE ? OR q.customer_name LIKE ? OR q.customer_phone LIKE ?)")
                    args += [f"%{q_str}%", f"%{q_str}%", f"%{q_str}%"]
                if not see_all:
                    where.append("q.user_id=?")
                    args.append(u["id"])
                base = f"""SELECT q.id, q.quote_no, q.created_at, u.name user_name,
                                  q.status, q.total, q.discount, q.customer_name, q.customer_phone, q.doc_date
                           FROM quotations q JOIN users u ON u.id=q.user_id
                           WHERE {' AND '.join(where)} ORDER BY q.id DESC"""
                for r in conn.execute(base, args).fetchall():
                    row_d = dict(r)
                    row_d["kind"] = "quote"
                    row_d["sub_kind"] = "quote"
                    row_d["quote_id"] = row_d["id"]
                    row_d["invoice_no"] = row_d["quote_no"]
                    out.append(row_d)

            if include_repairs:
                where, args = ["1=1"], []
                d_cl, d_ar = self._history_date_clause("r.", date=date, date_from=date_from, date_to=date_to, all_dates=all_dates)
                where += d_cl
                args += d_ar
                if q_str:
                    where.append("(r.ref LIKE ? OR r.customer_name LIKE ? OR r.customer_phone LIKE ? OR r.device_type LIKE ?)")
                    args += [f"%{q_str}%", f"%{q_str}%", f"%{q_str}%", f"%{q_str}%"]
                base = f"""SELECT r.id, r.ref, r.created_at, u.name user_name,
                                  r.status, r.cost, r.customer_name, r.customer_phone, r.device_type
                           FROM repairs r JOIN users u ON u.id=r.user_id
                           WHERE {' AND '.join(where)} ORDER BY r.id DESC"""
                for r in conn.execute(base, args).fetchall():
                    row_d = dict(r)
                    row_d["kind"] = "repair"
                    row_d["sub_kind"] = "repair"
                    out.append(row_d)

            out.sort(key=lambda x: x["created_at"], reverse=True)
            tot = len(out)
            return {"rows": out[offset:offset + limit], "total": tot}

    def history_suggestions(self, q=""):
        u = self._perm_any("history_view_own", "history_view_all", "sales_return", "sales_return_own", "quotes_view", "repair_view")
        can_sales = self._has_perm("history_view_own") or self._has_perm("history_view_all") or self._has_perm("sales_return") or self._has_perm("sales_return_own")
        see_all = self._has_perm("history_view_all") or self._has_perm("sales_return")
        can_quotes = self._has_perm("quotes_view")
        can_repairs = self._has_perm("repair_view")
        q_str = (q or "").strip()
        like = f"%{q_str}%"
        with db.connect() as conn:
            items = []
            if can_sales:
                u_sql = "" if see_all else " AND user_id=?"
                u_args = (q_str, like, like, like) if see_all else (q_str, like, like, like, u["id"])
                for r in conn.execute(
                    f"""SELECT id, invoice_no AS ref, customer_name, customer_phone, total, COALESCE(doc_type, 'pos') AS doc_type, created_at
                        FROM sales
                        WHERE (? = '' OR invoice_no LIKE ? OR customer_name LIKE ? OR customer_phone LIKE ?){u_sql}
                        ORDER BY id DESC LIMIT 6""",
                    u_args,
                ).fetchall():
                    items.append({
                        "kind": "b2b" if r["doc_type"] == "b2b" else "pos",
                        "id": r["id"],
                        "ref": r["ref"],
                        "customer_name": r["customer_name"] or "",
                        "customer_phone": r["customer_phone"] or "",
                        "amount": r["total"],
                        "created_at": r["created_at"],
                    })
            if can_quotes:
                u_sql = "" if see_all else " AND user_id=?"
                u_args = (q_str, like, like, like) if see_all else (q_str, like, like, like, u["id"])
                for r in conn.execute(
                    f"""SELECT id, quote_no AS ref, customer_name, customer_phone, total, created_at
                        FROM quotations
                        WHERE doc_type='quote' AND status!='converted'
                          AND (? = '' OR quote_no LIKE ? OR customer_name LIKE ? OR customer_phone LIKE ?){u_sql}
                        ORDER BY id DESC LIMIT 5""",
                    u_args,
                ).fetchall():
                    items.append({
                        "kind": "quote",
                        "id": r["id"],
                        "ref": r["ref"],
                        "customer_name": r["customer_name"] or "",
                        "customer_phone": r["customer_phone"] or "",
                        "amount": r["total"],
                        "created_at": r["created_at"],
                    })
            if can_repairs:
                for r in conn.execute(
                    """SELECT id, ref, customer_name, customer_phone, cost, created_at
                       FROM repairs
                       WHERE (? = '' OR ref LIKE ? OR customer_name LIKE ? OR customer_phone LIKE ?)
                       ORDER BY id DESC LIMIT 5""",
                    (q_str, like, like, like),
                ).fetchall():
                    items.append({
                        "kind": "repair",
                        "id": r["id"],
                        "ref": r["ref"],
                        "customer_name": r["customer_name"] or "",
                        "customer_phone": r["customer_phone"] or "",
                        "amount": r["cost"],
                        "created_at": r["created_at"],
                    })
            items.sort(key=lambda x: x["created_at"], reverse=True)
            return items[:12]

    def sales_stats(self, date=None, date_from=None, date_to=None, all_dates=False):
        u = self._perm_any("history_view_own", "history_view_all", "sales_return", "sales_return_own", "quotes_view", "repair_view", "reports_sales_view")
        can_sales = self._has_perm("history_view_own") or self._has_perm("history_view_all") or self._has_perm("sales_return") or self._has_perm("sales_return_own") or self._has_perm("reports_sales_view")
        see_all = self._has_perm("history_view_all") or self._has_perm("reports_sales_view") or self._has_perm("sales_return")
        can_quotes = self._has_perm("quotes_view") or self._has_perm("reports_sales_view")
        can_repairs = self._has_perm("repair_view") or self._has_perm("reports_sales_view")
        if not date and not date_from and not date_to and not all_dates:
            date = datetime.datetime.now().strftime("%Y-%m-%d")
        d_cl, d_ar = self._history_date_clause("", date=date, date_from=date_from, date_to=date_to, all_dates=all_dates)
        w_sql = (" AND ".join(d_cl)) if d_cl else "1=1"
        u_filter = "" if see_all else " AND user_id=?"
        u_args = list(d_ar) + ([] if see_all else [u["id"]])
        with db.connect() as conn:
            if can_sales:
                s = conn.execute(
                    f"SELECT COUNT(*) n, COALESCE(SUM(total),0) t FROM sales WHERE {w_sql}{u_filter} AND status != 'returned'",
                    u_args,
                ).fetchone()
                pos_s = conn.execute(
                    f"SELECT COUNT(*) n, COALESCE(SUM(total),0) t FROM sales WHERE {w_sql}{u_filter} AND status != 'returned' AND COALESCE(doc_type,'pos') != 'b2b'",
                    u_args,
                ).fetchone()
                b2b_s = conn.execute(
                    f"SELECT COUNT(*) n, COALESCE(SUM(total),0) t FROM sales WHERE {w_sql}{u_filter} AND status != 'returned' AND doc_type = 'b2b'",
                    u_args,
                ).fetchone()
                ret = conn.execute(
                    f"SELECT COUNT(*) n, COALESCE(SUM(total),0) t FROM sale_returns WHERE {w_sql}{u_filter}",
                    u_args,
                ).fetchone()
            else:
                s = pos_s = b2b_s = ret = {"n": 0, "t": 0}
            if can_quotes:
                q_s = conn.execute(
                    f"SELECT COUNT(*) n, COALESCE(SUM(total),0) t FROM quotations WHERE {w_sql}{u_filter} AND doc_type = 'quote' AND status != 'converted'",
                    u_args,
                ).fetchone()
            else:
                q_s = {"n": 0, "t": 0}
            if can_repairs:
                rp = conn.execute(
                    f"""SELECT COUNT(*) n, SUM(CASE WHEN status IN ('received','in_review','pending_approval')
                       THEN 1 ELSE 0 END) active FROM repairs WHERE {w_sql}""",
                    d_ar,
                ).fetchone()
            else:
                rp = {"n": 0, "active": 0}
            return {
                "sales": {"count": s["n"], "total": s["t"]},
                "pos_sales": {"count": pos_s["n"], "total": pos_s["t"]},
                "b2b_invoices": {"count": b2b_s["n"], "total": b2b_s["t"]},
                "quotes": {"count": q_s["n"], "total": q_s["t"]},
                "returns": {"count": ret["n"], "total": ret["t"]},
                "repairs": {"count": rp["n"], "active": rp["active"] or 0},
            }

    def sale_return(self, sale_id, items, reason=None):
        u = self._perm_any("sales_return", "sales_return_own")
        items = items or []
        if not items:
            raise ApiError("اختر أصنافاً للإرجاع")
        with db.connect() as conn:
            s = conn.execute("SELECT * FROM sales WHERE id=?", (_int(sale_id),)).fetchone()
            if not s:
                raise ApiError("الفاتورة غير موجودة")
            if s["user_id"] != u["id"] and not self._has_perm("sales_return"):
                raise ApiError("ممنوع: صلاحيتك تقتصر على مرتجع فواتيرك فقط")
            if s["status"] == "returned":
                raise ApiError("الفاتورة مرتجعة بالكامل مسبقاً")
            prev_net_credit = _sale_net_credit(conn, s["id"])
            total = 0
            done = []
            for it in items:
                item_id, qty = _int(it.get("sale_item_id")), _int(it.get("qty", 1))
                si = conn.execute("SELECT * FROM sale_items WHERE id=? AND sale_id=?", (item_id, s["id"])).fetchone()
                if not si:
                    raise ApiError("الصنف غير موجود في الفاتورة")
                already = conn.execute(
                    """SELECT COALESCE(SUM(qty),0) q FROM sale_return_items
                       WHERE sale_item_id=?""", (item_id,),
                ).fetchone()["q"]
                if qty <= 0 or qty > si["qty"] - already:
                    raise ApiError(f"كمية الإرجاع غير صالحة (المتبقي {si['qty'] - already})")
                conn.execute("UPDATE products SET qty=qty+? WHERE id=?", (qty, si["product_id"]))
                if si["serial_id"]:
                    conn.execute("UPDATE serials SET status='in_stock' WHERE id=?", (si["serial_id"],))
                after = conn.execute("SELECT qty FROM products WHERE id=?", (si["product_id"],)).fetchone()[0]
                conn.execute(
                    """INSERT INTO stock_movements(created_at, user_id, product_id, qty_change, qty_after, reason, ref)
                       VALUES(?,?,?,?,?,?,?)""",
                    (db.now(), u["id"], si["product_id"], qty, after, "return", s["invoice_no"]),
                )
                amount = si["unit_price"] * qty
                total += amount
                done.append((item_id, qty, amount))
            cur = conn.execute(
                "INSERT INTO sale_returns(sale_id, user_id, created_at, reason, total) VALUES(?,?,?,?,?)",
                (s["id"], u["id"], db.now(), reason, total),
            )
            for item_id, qty, amount in done:
                conn.execute(
                    """INSERT INTO sale_return_items(return_id, sale_item_id, qty, amount)
                       VALUES(?,?,?,?)""",
                    (cur.lastrowid, item_id, qty, amount),
                )
            remaining = conn.execute(
                """SELECT (SELECT COALESCE(SUM(qty),0) FROM sale_items WHERE sale_id=?)
                         - (SELECT COALESCE(SUM(r.qty),0) FROM sale_return_items r
                            JOIN sale_returns sr ON sr.id=r.return_id WHERE sr.sale_id=?)""",
                (s["id"], s["id"]),
            ).fetchone()[0]
            now_ts = db.now()
            log_line = f"[{now_ts}] بواسطة {u['name']}: مرتجع بقيمة {_fmt_money(total)}" + (f" ({reason})" if reason else "")
            prev_log = (s["modification_summary"] or "").strip() if "modification_summary" in s.keys() else ""
            full_log = (prev_log + " | " + log_line) if prev_log else log_line
            conn.execute(
                "UPDATE sales SET status=?, modified_by=?, modified_by_name=?, modified_at=?, modification_summary=? WHERE id=?",
                ("returned" if not remaining else "partial_return", u["id"], u["name"], now_ts, full_log, s["id"]),
            )
            _sync_sale_ledger_delta(conn, s, prev_net_credit, user=u, reason_prefix="مرتجع فاتورة آجلة")
            new_net_credit = _sale_net_credit(conn, s["id"])
            ret_cost_row = conn.execute(
                """SELECT COALESCE(SUM(sri.qty * COALESCE(NULLIF(si.cost_unit, 0), p.cost, 0)), 0) AS c
                   FROM sale_return_items sri
                   JOIN sale_items si ON si.id = sri.sale_item_id
                   LEFT JOIN products p ON p.id = si.product_id
                   WHERE sri.return_id=?""",
                (cur.lastrowid,),
            ).fetchone()
            erp_hooks.on_sale_returned(
                self,
                conn,
                sale_id=s["id"],
                return_id=cur.lastrowid,
                returned_amount=total,
                returned_cost=int(ret_cost_row["c"] or 0) if ret_cost_row else 0,
                credit_delta=max(0, prev_net_credit - new_net_credit),
                user=u,
            )
            return {"return_id": cur.lastrowid, "total": total}

