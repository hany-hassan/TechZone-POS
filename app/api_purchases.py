"""وحدة المشتريات والموردين وأوامر الشراء والمرتجعات وسندات الصرف وتقارير التوريد."""
import datetime
import json
import sqlite3
from decimal import Decimal, ROUND_HALF_UP

import db
import erp_hooks
from api_common import ApiError, _fmt_money, _format_doc_seq, _int, _money


def _refresh_supplier_cache(conn, supplier_id: int) -> dict | None:
    """تحديث أرصدة المورد المجمّعة (إجمالي المشتريات، المسدد، الرصيد الدائن المستحق) ذرياً."""
    sup = conn.execute("SELECT * FROM suppliers WHERE id=?", (supplier_id,)).fetchone()
    if not sup:
        return None
    pur_row = conn.execute(
        """SELECT COALESCE(SUM(total), 0) AS tot_pur,
                  COALESCE(SUM(paid_amount), 0) AS direct_paid
           FROM purchases
           WHERE supplier_id=? AND status IN ('posted','partial_return','returned')""",
        (supplier_id,),
    ).fetchone()
    ret_row = conn.execute(
        """SELECT COALESCE(SUM(total), 0) AS tot_ret,
                  COALESCE(SUM(CASE WHEN refund_method='credit' THEN total ELSE 0 END), 0) AS credit_ret
           FROM purchase_returns
           WHERE supplier_id=?""",
        (supplier_id,),
    ).fetchone()
    pay_row = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS v_paid FROM supplier_payments WHERE supplier_id=?",
        (supplier_id,),
    ).fetchone()

    opening = int(sup["opening_balance"] or 0)
    tot_pur = max(0, int(pur_row["tot_pur"] or 0) - int(ret_row["tot_ret"] or 0))
    direct_paid = int(pur_row["direct_paid"] or 0)
    v_paid = int(pay_row["v_paid"] or 0)
    credit_ret = int(ret_row["credit_ret"] or 0)
    paid_total = direct_paid + v_paid
    balance = max(0, opening + int(pur_row["tot_pur"] or 0) - credit_ret - paid_total)

    conn.execute(
        "UPDATE suppliers SET total_purchases=?, paid_total=?, balance=? WHERE id=?",
        (tot_pur, paid_total, balance, supplier_id),
    )
    return {
        "opening_balance": opening,
        "total_purchases": tot_pur,
        "paid_total": paid_total,
        "balance": balance,
    }


def _append_supplier_ledger(
    conn,
    supplier_id: int,
    kind: str,
    ref: str,
    debit: int = 0,
    credit: int = 0,
    purchase_id: int | None = None,
    payment_id: int | None = None,
    method: str | None = None,
    ref_no: str | None = None,
    notes: str | None = None,
    user_id: int | None = None,
    user_name: str | None = None,
    created_at: str | None = None,
) -> int:
    """إضافة حركة في دفتر أستاذ المورد (supplier_ledger) وتحديث رصيده الدائن."""
    last = conn.execute(
        "SELECT balance_after FROM supplier_ledger WHERE supplier_id=? ORDER BY id DESC LIMIT 1",
        (supplier_id,),
    ).fetchone()
    if last is not None:
        prev_bal = int(last["balance_after"] or 0)
    else:
        srow = conn.execute("SELECT balance FROM suppliers WHERE id=?", (supplier_id,)).fetchone()
        prev_bal = int(srow["balance"] or 0) if srow else 0
    # للمورد (حساب دائن): credit يزيد المستحق للمورد، debit ينقص المستحق للمورد
    bal_after = max(0, prev_bal + int(credit or 0) - int(debit or 0))
    conn.execute(
        """INSERT INTO supplier_ledger
           (supplier_id, created_at, kind, ref, purchase_id, payment_id, debit, credit, balance_after, method, ref_no, notes, user_id, user_name)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            supplier_id,
            created_at or db.now(),
            kind,
            ref,
            purchase_id,
            payment_id,
            int(debit or 0),
            int(credit or 0),
            bal_after,
            method,
            ref_no,
            notes,
            user_id,
            user_name,
        ),
    )
    _refresh_supplier_cache(conn, supplier_id)
    return bal_after


class PurchasesMixin:
    """إدارة الموردين، أوامر الشراء، فواتير المشتريات، المرتجعات، وسندات الصرف."""

    # ---------------------------------------------------------- الموردون
    def suppliers_search(self, q="", limit=20):
        self._perm_any("suppliers_view", "suppliers_manage", "purchases_view", "purchases_create_post")
        q = (q or "").strip()
        lim = max(1, min(100, _int(limit, 20)))
        with db.connect() as conn:
            rows = conn.execute(
                """SELECT id, code, name, company_name, phone, tax_reg_no, payment_terms_days, credit_limit, balance
                   FROM suppliers
                   WHERE active=1 AND (name LIKE ? OR COALESCE(company_name,'') LIKE ? OR COALESCE(phone,'') LIKE ? OR code LIKE ?)
                   ORDER BY name LIMIT ?""",
                (f"%{q}%", f"%{q}%", f"%{q}%", f"%{q}%", lim),
            ).fetchall()
            return [dict(r) for r in rows]

    def suppliers_list(self, q="", debt_only=False, limit=100, offset=0):
        self._perm_any("suppliers_view", "suppliers_manage", "purchases_view", "purchases_create_post")
        q = (q or "").strip()
        limit = max(1, min(200, _int(limit, 100)))
        offset = max(0, _int(offset, 0))
        where = ["active=1"]
        args = []
        if debt_only:
            where.append("balance > 0")
        if q:
            like = f"%{q}%"
            where.append("(name LIKE ? OR COALESCE(company_name,'') LIKE ? OR COALESCE(phone,'') LIKE ? OR code LIKE ?)")
            args.extend([like, like, like, like])
        w_sql = " AND ".join(where)
        with db.connect() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM suppliers WHERE {w_sql}", args).fetchone()[0]
            rows = conn.execute(
                f"SELECT * FROM suppliers WHERE {w_sql} ORDER BY balance DESC, name ASC LIMIT ? OFFSET ?",
                [*args, limit, offset],
            ).fetchall()
            sum_row = conn.execute(
                """SELECT COUNT(*) AS total_suppliers,
                          COALESCE(SUM(CASE WHEN balance > 0 THEN 1 ELSE 0 END), 0) AS owed_suppliers_count,
                          COALESCE(SUM(total_purchases), 0) AS total_purchases,
                          COALESCE(SUM(paid_total), 0) AS total_paid,
                          COALESCE(SUM(balance), 0) AS total_balance
                   FROM suppliers WHERE active=1"""
            ).fetchone()
            return {
                "rows": [dict(r) for r in rows],
                "total": total,
                "summary": dict(sum_row) if sum_row else {
                    "total_suppliers": 0,
                    "owed_suppliers_count": 0,
                    "total_purchases": 0,
                    "total_paid": 0,
                    "total_balance": 0,
                },
            }

    def supplier_get(self, id):
        self._perm_any("suppliers_view", "suppliers_manage", "purchases_view")
        sid = _int(id)
        with db.connect() as conn:
            r = conn.execute("SELECT * FROM suppliers WHERE id=?", (sid,)).fetchone()
            if not r:
                raise ApiError("المورد غير موجود")
            return dict(r)

    def supplier_save(
        self,
        name,
        id=None,
        code=None,
        company_name=None,
        phone=None,
        email=None,
        address=None,
        tax_reg_no=None,
        tax_card_no=None,
        payment_terms_days=0,
        credit_limit=0,
        opening_balance=0,
        notes=None,
        active=1,
    ):
        u = self._perm("suppliers_manage")
        name = (name or "").strip()
        if not name:
            raise ApiError("اسم المورد مطلوب")
        comp = (company_name or "").strip() or None
        phone = (phone or "").strip() or None
        email = (email or "").strip() or None
        address = (address or "").strip() or None
        tax_reg = (tax_reg_no or "").strip() or None
        tax_card = (tax_card_no or "").strip() or None
        terms = max(0, _int(payment_terms_days, 0))
        cr_lim = max(0, _money(credit_limit, 0))
        open_bal = max(0, _money(opening_balance, 0))
        notes = (notes or "").strip() or None
        act = 1 if active else 0

        with db.connect() as conn:
            if id:
                sid = _int(id)
                cur_s = conn.execute("SELECT * FROM suppliers WHERE id=?", (sid,)).fetchone()
                if not cur_s:
                    raise ApiError("المورد غير موجود")
                final_code = (code or cur_s["code"] or f"SUP-{sid:03d}").strip()
                conn.execute(
                    """UPDATE suppliers
                       SET code=?, name=?, company_name=?, phone=?, email=?, address=?,
                           tax_reg_no=?, tax_card_no=?, payment_terms_days=?, credit_limit=?,
                           opening_balance=?, notes=?, active=?
                       WHERE id=?""",
                    (final_code, name, comp, phone, email, address, tax_reg, tax_card, terms, cr_lim, open_bal, notes, act, sid),
                )
                _refresh_supplier_cache(conn, sid)
                return dict(conn.execute("SELECT * FROM suppliers WHERE id=?", (sid,)).fetchone())
            else:
                now_ts = db.now()
                cur = conn.execute(
                    """INSERT INTO suppliers
                       (code, name, company_name, phone, email, address, tax_reg_no, tax_card_no,
                        payment_terms_days, credit_limit, opening_balance, total_purchases, paid_total, balance, notes, active, created_at)
                       VALUES('SUP-TMP',?,?,?,?,?,?,?,?,?,?,0,0,?,?,1,?)""",
                    (name, comp, phone, email, address, tax_reg, tax_card, terms, cr_lim, open_bal, open_bal, notes, now_ts),
                )
                sid = cur.lastrowid
                final_code = (code or "").strip() or f"SUP-{sid:03d}"
                if conn.execute("SELECT 1 FROM suppliers WHERE code=? AND id!=?", (final_code, sid)).fetchone():
                    final_code = f"SUP-{sid:04d}"
                conn.execute("UPDATE suppliers SET code=? WHERE id=?", (final_code, sid))
                if open_bal > 0:
                    _append_supplier_ledger(
                        conn,
                        sid,
                        "opening",
                        "OPEN-SUP",
                        credit=open_bal,
                        notes="رصيد أول المدة للمورد",
                        user_id=u["id"],
                        user_name=u["name"],
                        created_at=now_ts,
                    )
                return dict(conn.execute("SELECT * FROM suppliers WHERE id=?", (sid,)).fetchone())

    def supplier_delete(self, id):
        self._perm("suppliers_manage")
        sid = _int(id)
        with db.connect() as conn:
            sup = conn.execute("SELECT * FROM suppliers WHERE id=?", (sid,)).fetchone()
            if not sup:
                raise ApiError("المورد غير موجود")
            if int(sup["balance"] or 0) > 0:
                raise ApiError("لا يمكن حذف مورد له رصيد مستحق — يجب سداد الرصيد أولاً")
            has_docs = conn.execute(
                "SELECT 1 FROM purchases WHERE supplier_id=? UNION SELECT 1 FROM supplier_payments WHERE supplier_id=? LIMIT 1",
                (sid, sid),
            ).fetchone()
            if has_docs:
                conn.execute("UPDATE suppliers SET active=0 WHERE id=?", (sid,))
                return {"id": sid, "deactivated": True}
            conn.execute("DELETE FROM suppliers WHERE id=?", (sid,))
            return {"id": sid, "deleted": True}

    def supplier_statement(self, id, date_from=None, date_to=None):
        """كشف حساب المورد التفصيلي مع فواتير الشراء وسندات الصرف والمرتجعات."""
        self._perm_any("suppliers_view", "purchases_payment")
        sid = _int(id)
        with db.connect() as conn:
            sup = conn.execute("SELECT * FROM suppliers WHERE id=?", (sid,)).fetchone()
            if not sup:
                raise ApiError("المورد غير موجود")
            _refresh_supplier_cache(conn, sid)
            sup = dict(conn.execute("SELECT * FROM suppliers WHERE id=?", (sid,)).fetchone())

            l_where = ["supplier_id=?"]
            l_args = [sid]
            if date_from:
                l_where.append("created_at >= ?")
                l_args.append(f"{date_from.strip()} 00:00:00")
            if date_to:
                l_where.append("created_at <= ?")
                l_args.append(f"{date_to.strip()} 23:59:59")

            ledger = [
                dict(r)
                for r in conn.execute(
                    f"SELECT * FROM supplier_ledger WHERE {' AND '.join(l_where)} ORDER BY id DESC",
                    l_args,
                ).fetchall()
            ]
            bills = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM purchases WHERE supplier_id=? ORDER BY id DESC LIMIT 100",
                    (sid,),
                ).fetchall()
            ]
            payments = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM supplier_payments WHERE supplier_id=? ORDER BY id DESC LIMIT 100",
                    (sid,),
                ).fetchall()
            ]
            returns = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM purchase_returns WHERE supplier_id=? ORDER BY id DESC LIMIT 100",
                    (sid,),
                ).fetchall()
            ]
            return {
                "supplier": sup,
                "ledger": ledger,
                "purchases": bills,
                "payments": payments,
                "returns": returns,
            }

    # ---------------------------------------------------------- سندات الصرف للموردين
    def supplier_payment_create(
        self,
        supplier_id,
        amount,
        method="cash",
        purchase_id=None,
        treasury_id=None,
        from_drawer=False,
        ref_no=None,
        notes=None,
    ):
        """إصدار سند صرف لمورد من الخزنة الرئيسية/البنك/المحفظة أو من درج الكاشير."""
        u = self._perm("purchases_payment")
        sid = _int(supplier_id)
        amt = _money(amount)
        if amt <= 0:
            raise ApiError("مبلغ الصرف يجب أن يكون أكبر من صفر")
        method = (method or "cash").strip().lower()
        if method not in ("cash", "wallet", "instapay", "bank"):
            raise ApiError("طريقة الدفع غير صالحة (cash/wallet/instapay/bank)")
        ref_no = (ref_no or "").strip() or None
        if method in ("wallet", "instapay", "bank") and not ref_no:
            raise ApiError("يرجى إدخال رقم العملية المرجعية للتحويل")
        use_drawer = bool(from_drawer)

        with db.connect() as conn:
            sup = conn.execute("SELECT * FROM suppliers WHERE id=?", (sid,)).fetchone()
            if not sup:
                raise ApiError("المورد غير موجود")
            summary = _refresh_supplier_cache(conn, sid)
            cur_bal = int(summary["balance"] or 0)
            if cur_bal <= 0:
                raise ApiError("لا توجد مديونية مستحقة لهذا المورد")
            if amt > cur_bal:
                raise ApiError(f"مبلغ الصرف ({_fmt_money(amt)}) يتجاوز الرصيد المستحق للمورد ({_fmt_money(cur_bal)})")

            shift_id = None
            if use_drawer:
                s = self._open_shift(conn, u["id"])
                if not s:
                    raise ApiError("الدفع من درج الكاشير يتطلب وجود وردية مفتوحة — افتح وردية أو اختر الصرف من الخزنة الرئيسية")
                shift_id = s["id"]

            pos_tpl = self._load_templates(conn)["pos"]
            sp_prefix = (pos_tpl.get("supplier_voucher_prefix") or "SPV-").strip() or "SPV-"
            cnt = conn.execute("SELECT COUNT(*) FROM supplier_payments").fetchone()[0] + 1
            ref = _format_doc_seq(sp_prefix, cnt)
            if conn.execute("SELECT 1 FROM supplier_payments WHERE ref=?", (ref,)).fetchone():
                ref = f"{sp_prefix}{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}-{cnt}"

            now_ts = db.now()
            pur_id_val = _int(purchase_id) if purchase_id else None
            tr_id_val = _int(treasury_id) if treasury_id else None
            clean_notes = (notes or "").strip() or None

            cur = conn.execute(
                """INSERT INTO supplier_payments
                   (ref, supplier_id, purchase_id, user_id, shift_id, treasury_id, created_at, amount, method, from_drawer, ref_no, notes)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (ref, sid, pur_id_val, u["id"], shift_id, tr_id_val, now_ts, amt, method, 1 if use_drawer else 0, ref_no, clean_notes),
            )
            pay_id = cur.lastrowid

            _append_supplier_ledger(
                conn,
                sid,
                "payment",
                ref,
                debit=amt,
                purchase_id=pur_id_val,
                payment_id=pay_id,
                method=method,
                ref_no=ref_no,
                notes=clean_notes or f"سند صرف للمورد ({ref})",
                user_id=u["id"],
                user_name=u["name"],
                created_at=now_ts,
            )

            erp_hooks.on_supplier_payment(
                self,
                conn,
                payment_id=pay_id,
                supplier_id=sid,
                amount=amt,
                method=method,
                ref=ref,
                treasury_id=tr_id_val,
                from_drawer=use_drawer,
                user=u,
            )
            new_bal = conn.execute("SELECT balance FROM suppliers WHERE id=?", (sid,)).fetchone()["balance"]
            return {"id": pay_id, "ref": ref, "remaining_balance": new_bal}

    def supplier_payment_delete(self, id):
        u = self._perm("purchases_cancel_delete")
        pid = _int(id)
        with db.connect() as conn:
            sp = conn.execute("SELECT * FROM supplier_payments WHERE id=?", (pid,)).fetchone()
            if not sp:
                raise ApiError("سند الصرف غير موجود")
            conn.execute("DELETE FROM supplier_payments WHERE id=?", (pid,))
            _append_supplier_ledger(
                conn,
                sp["supplier_id"],
                "adjustment",
                sp["ref"],
                credit=sp["amount"],
                purchase_id=sp["purchase_id"],
                method=sp["method"],
                ref_no=sp["ref_no"],
                notes=f"إلغاء سند صرف ({sp['ref']})",
                user_id=u["id"],
                user_name=u["name"],
            )
            if erp_hooks.is_module_active(self, conn, "accounting"):
                je = conn.execute(
                    "SELECT id FROM journal_entries WHERE source_table='supplier_payments' AND source_id=? AND status='posted' ORDER BY id DESC LIMIT 1",
                    (pid,),
                ).fetchone()
                if je:
                    erp_hooks.reverse_journal_entry(conn, je["id"], reason=f"إلغاء سند صرف {sp['ref']}", user_id=u["id"])
            return True

    # ---------------------------------------------------------- أوامر الشراء (Purchase Orders)
    def purchase_orders_list(self, q="", status=None, supplier_id=None, limit=100, offset=0):
        self._perm_any("purchases_view", "purchases_create_post")
        limit = max(1, min(200, _int(limit, 100)))
        offset = max(0, _int(offset, 0))
        where = ["1=1"]
        args = []
        if status:
            where.append("po.status=?")
            args.append(status)
        if supplier_id:
            where.append("po.supplier_id=?")
            args.append(_int(supplier_id))
        if q:
            like = f"%{q}%"
            where.append("(po.po_no LIKE ? OR s.name LIKE ?)")
            args.extend([like, like])
        w_sql = " AND ".join(where)
        with db.connect() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM purchase_orders po JOIN suppliers s ON s.id=po.supplier_id WHERE {w_sql}",
                args,
            ).fetchone()[0]
            rows = conn.execute(
                f"""SELECT po.*, s.name AS supplier_name, u.name AS user_name
                    FROM purchase_orders po
                    JOIN suppliers s ON s.id = po.supplier_id
                    LEFT JOIN users u ON u.id = po.user_id
                    WHERE {w_sql}
                    ORDER BY po.id DESC LIMIT ? OFFSET ?""",
                [*args, limit, offset],
            ).fetchall()
            return {"rows": [dict(r) for r in rows], "total": total}

    def purchase_order_get(self, id):
        self._perm_any("purchases_view", "purchases_create_post")
        poid = _int(id)
        with db.connect() as conn:
            po = conn.execute(
                """SELECT po.*, s.name AS supplier_name, s.phone AS supplier_phone, u.name AS user_name
                   FROM purchase_orders po
                   JOIN suppliers s ON s.id = po.supplier_id
                   LEFT JOIN users u ON u.id = po.user_id
                   WHERE po.id=?""",
                (poid,),
            ).fetchone()
            if not po:
                raise ApiError("أمر الشراء غير موجود")
            d = dict(po)
            d["items"] = [
                dict(x)
                for x in conn.execute("SELECT * FROM purchase_order_items WHERE po_id=? ORDER BY id", (poid,)).fetchall()
            ]
            return d

    def purchase_order_save(
        self,
        supplier_id,
        items,
        id=None,
        order_date=None,
        expected_date=None,
        discount=0,
        shipping_cost=0,
        tax_rate=0,
        status="ordered",
        notes=None,
    ):
        u = self._perm("purchases_create_post")
        sid = _int(supplier_id)
        items = items or []
        if not items:
            raise ApiError("يرجى إضافة صنف واحد على الأقل في أمر الشراء")
        if status not in ("draft", "ordered"):
            status = "ordered"
        dt_order = (order_date or db.now()[:10]).strip()[:10]
        dt_exp = (expected_date or dt_order).strip()[:10]
        disc = max(0, _money(discount, 0))
        ship = max(0, _money(shipping_cost, 0))
        t_rate = max(0, min(100, _int(tax_rate, 0)))

        with db.connect() as conn:
            sup = conn.execute("SELECT id FROM suppliers WHERE id=?", (sid,)).fetchone()
            if not sup:
                raise ApiError("المورد غير موجود")
            parsed = []
            subtotal = 0
            for raw in items:
                pid = _int(raw.get("product_id"))
                p = conn.execute("SELECT id, sku, name, cost FROM products WHERE id=?", (pid,)).fetchone()
                if not p:
                    raise ApiError("أحد الأصناف غير موجود في المخزون")
                q = max(1, _int(raw.get("qty_ordered") or raw.get("qty"), 1))
                uc = _money(raw.get("unit_cost"), 0) if raw.get("unit_cost") is not None else int(p["cost"] or 0)
                line_tot = q * uc
                subtotal += line_tot
                parsed.append({
                    "product_id": pid,
                    "sku": p["sku"],
                    "name": p["name"],
                    "qty_ordered": q,
                    "unit_cost": uc,
                    "tax_rate": t_rate,
                    "line_total": line_tot,
                })
            taxable = max(0, subtotal - disc)
            tax_amt = int((Decimal(taxable) * Decimal(t_rate) / Decimal(100)).to_integral_value(rounding=ROUND_HALF_UP))
            total = taxable + ship + tax_amt
            now_ts = db.now()

            if id:
                poid = _int(id)
                ex = conn.execute("SELECT * FROM purchase_orders WHERE id=?", (poid,)).fetchone()
                if not ex:
                    raise ApiError("أمر الشراء غير موجود")
                if ex["status"] == "received":
                    raise ApiError("لا يمكن تعديل أمر شراء تم استلامه وتحويله لفاتورة")
                conn.execute(
                    """UPDATE purchase_orders
                       SET supplier_id=?, order_date=?, expected_date=?, subtotal=?, discount=?, tax=?,
                           shipping_cost=?, total=?, status=?, notes=?, updated_at=?
                       WHERE id=?""",
                    (sid, dt_order, dt_exp, subtotal, disc, tax_amt, ship, total, status, (notes or "").strip() or None, now_ts, poid),
                )
                conn.execute("DELETE FROM purchase_order_items WHERE po_id=?", (poid,))
            else:
                cur = conn.execute(
                    """INSERT INTO purchase_orders
                       (po_no, supplier_id, order_date, expected_date, subtotal, discount, tax, shipping_cost, total, status, notes, user_id, created_at, updated_at)
                       VALUES('PO-TMP',?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (sid, dt_order, dt_exp, subtotal, disc, tax_amt, ship, total, status, (notes or "").strip() or None, u["id"], now_ts, now_ts),
                )
                poid = cur.lastrowid
                year_s = dt_order[:4]
                po_no = _format_doc_seq(f"PO-{year_s}-", poid)
                conn.execute("UPDATE purchase_orders SET po_no=? WHERE id=?", (po_no, poid))

            for it in parsed:
                conn.execute(
                    """INSERT INTO purchase_order_items(po_id, product_id, sku, name, qty_ordered, qty_received, unit_cost, tax_rate, line_total)
                       VALUES(?,?,?,?,?,0,?,?,?)""",
                    (poid, it["product_id"], it["sku"], it["name"], it["qty_ordered"], it["unit_cost"], it["tax_rate"], it["line_total"]),
                )
        return self.purchase_order_get(poid)

    def purchase_order_status(self, id, status):
        self._perm_any("purchases_create_post", "purchases_cancel_delete")
        poid = _int(id)
        if status not in ("draft", "ordered", "cancelled"):
            raise ApiError("حالة أمر الشراء غير صالحة")
        with db.connect() as conn:
            po = conn.execute("SELECT * FROM purchase_orders WHERE id=?", (poid,)).fetchone()
            if not po:
                raise ApiError("أمر الشراء غير موجود")
            if po["status"] == "received":
                raise ApiError("لا يمكن تغيير حالة أمر شراء مستلم بالكامل")
            conn.execute("UPDATE purchase_orders SET status=?, updated_at=? WHERE id=?", (status, db.now(), poid))
        return self.purchase_order_get(poid)

    def purchase_order_convert(
        self,
        id,
        paid_amount=0,
        payment_method="cash",
        treasury_id=None,
        from_drawer=False,
        supplier_invoice_no=None,
        wht_rate=0,
        ref_no=None,
    ):
        """تحويل أمر الشراء مباشرة إلى فاتورة مشتريات معتمدة وإدخال البضاعة للمخزون."""
        self._perm("purchases_create_post")
        po = self.purchase_order_get(id)
        if po["status"] in ("received", "cancelled"):
            raise ApiError("أمر الشراء مستلم مسبقاً أو ملغى")
        items_payload = [
            {
                "product_id": it["product_id"],
                "qty": it["qty_ordered"],
                "unit_cost": it["unit_cost"] / 100.0,
                "tax_rate": it["tax_rate"],
            }
            for it in po["items"]
        ]
        res = self.purchase_save(
            supplier_id=po["supplier_id"],
            items=items_payload,
            supplier_invoice_no=supplier_invoice_no,
            po_id=po["id"],
            invoice_date=db.now()[:10],
            discount=po["discount"] / 100.0,
            shipping_cost=po["shipping_cost"] / 100.0,
            tax_rate=po["items"][0]["tax_rate"] if po["items"] else 0,
            wht_rate=wht_rate,
            paid_amount=paid_amount,
            payment_method=payment_method,
            treasury_id=treasury_id,
            from_drawer=from_drawer,
            ref_no=ref_no,
            status="posted",
            notes=f"محولة من أمر شراء ({po['po_no']})",
        )
        with db.connect() as conn:
            conn.execute(
                "UPDATE purchase_orders SET status='received', converted_purchase_id=?, updated_at=? WHERE id=?",
                (res["id"], db.now(), po["id"]),
            )
            conn.execute("UPDATE purchase_order_items SET qty_received=qty_ordered WHERE po_id=?", (po["id"],))
        return res

    # ---------------------------------------------------------- فواتير المشتريات (Purchases)
    def _post_purchase_in_tx(self, conn, pur_row, items_rows, u):
        """اعتماد وترحيل فاتورة مشتريات: تحديث WAC والمخزون والسيريالات ودفتر المورد وقيد المحاسبة."""
        pur_id = pur_row["id"]
        pur_no = pur_row["purchase_no"]
        sup_id = pur_row["supplier_id"]
        now_ts = db.now()

        margin_warnings = []
        for it in items_rows:
            pid = it["product_id"]
            qty = int(it["qty"] or 0)
            uc = int(it["unit_cost"] or 0)
            landed = int(it["landed_unit_cost"] or uc)
            new_sp = it["new_sell_price"] if "new_sell_price" in it.keys() else None

            p = conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
            if not p:
                raise ApiError(f"الصنف «{it['name']}» غير موجود")

            serials_list = []
            if it["serials_json"]:
                try:
                    serials_list = [str(s).strip() for s in json.loads(it["serials_json"]) if str(s).strip()]
                except Exception:
                    serials_list = []
            if p["tracked"] and serials_list and len(serials_list) != qty:
                raise ApiError(f"الصنف المتتبّع «{p['name']}» يتطلب إدخال {qty} سيريال مطابق للكمية")
            for sn in serials_list:
                dup = conn.execute("SELECT 1 FROM serials WHERE serial=?", (sn,)).fetchone()
                if dup:
                    raise ApiError(f"الرقم التسلسلي «{sn}» مسجل مسبقاً في المخزون")
                conn.execute(
                    "INSERT INTO serials(product_id, serial, status, purchase_item_id, created_at) VALUES(?,?,'in_stock',?,?)",
                    (pid, sn, it["id"], now_ts),
                )

            wac_res = erp_hooks.apply_product_wac_update(
                conn,
                product_id=pid,
                added_qty=qty,
                unit_cost=uc,
                landed_unit_cost=landed,
                source_type="purchase",
                source_id=pur_id,
                ref=pur_no,
                user_id=u["id"],
                new_sell_price=new_sp,
            )
            if it["expiry_date"]:
                conn.execute("UPDATE products SET expiry_date=? WHERE id=?", (it["expiry_date"], pid))
            if wac_res.get("margin_warning"):
                margin_warnings.append({
                    "product_id": pid,
                    "name": p["name"],
                    "new_wac": wac_res["new_wac"],
                    "sell_price": wac_res["price"],
                })

            conn.execute(
                """INSERT INTO stock_movements(created_at, user_id, product_id, qty_change, qty_after, reason, ref)
                   VALUES(?,?,?,?,?,?,?)""",
                (now_ts, u["id"], pid, qty, wac_res["new_qty"], "purchase", pur_no),
            )

        total = int(pur_row["total"] or 0)
        paid = int(pur_row["paid_amount"] or 0)

        # تسجيل الفاتورة والمدفوع الفوري في دفتر المورد
        _append_supplier_ledger(
            conn,
            sup_id,
            "purchase_bill",
            pur_no,
            credit=total,
            purchase_id=pur_id,
            method="credit" if paid < total else pur_row["payment_method"],
            ref_no=pur_row["supplier_invoice_no"] or pur_row["ref_no"],
            notes=f"فاتورة مشتريات ({pur_no})",
            user_id=u["id"],
            user_name=u["name"],
            created_at=now_ts,
        )
        if paid > 0:
            _append_supplier_ledger(
                conn,
                sup_id,
                "payment",
                pur_no,
                debit=paid,
                purchase_id=pur_id,
                method=pur_row["payment_method"],
                ref_no=pur_row["ref_no"],
                notes=f"دفعة مسددة مع فاتورة المشتريات ({pur_no})",
                user_id=u["id"],
                user_name=u["name"],
                created_at=now_ts,
            )

        erp_hooks.on_purchase_posted(self, conn, purchase_id=pur_id, user=u)
        return margin_warnings

    def purchase_save(
        self,
        supplier_id,
        items,
        id=None,
        supplier_invoice_no=None,
        po_id=None,
        invoice_date=None,
        due_date=None,
        discount=0,
        shipping_cost=0,
        tax_rate=0,
        wht_rate=0,
        paid_amount=0,
        payment_method="cash",
        treasury_id=None,
        from_drawer=False,
        ref_no=None,
        status="posted",
        notes=None,
    ):
        """إنشاء أو حفظ فاتورة مشتريات (مسودة أو مرحلة مباشرة مع تحديث WAC والمخزون والقيد المحاسبي)."""
        u = self._perm("purchases_create_post")
        sid = _int(supplier_id)
        items = items or []
        if not items:
            raise ApiError("يرجى إضافة صنف واحد على الأقل في فاتورة المشتريات")
        status = (status or "posted").strip()
        if status not in ("draft", "posted"):
            status = "posted"

        inv_dt = (invoice_date or db.now()[:10]).strip()[:10]
        disc = max(0, _money(discount, 0))
        ship = max(0, _money(shipping_cost, 0))
        t_rate = max(0, min(100, _int(tax_rate, 0)))
        w_rate = max(0, min(20, _int(wht_rate, 0)))
        paid = max(0, _money(paid_amount, 0))
        method = (payment_method or "cash").strip().lower()
        if method not in ("cash", "wallet", "instapay", "bank"):
            method = "cash"
        use_drawer = bool(from_drawer)
        ref_no_clean = (ref_no or "").strip() or None
        sup_inv_no = (supplier_invoice_no or "").strip() or None

        with db.connect() as conn:
            sup = conn.execute("SELECT * FROM suppliers WHERE id=?", (sid,)).fetchone()
            if not sup:
                raise ApiError("المورد المحدد غير موجود")

            if not due_date:
                terms = int(sup["payment_terms_days"] or 0)
                try:
                    dt_obj = datetime.date.fromisoformat(inv_dt) + datetime.timedelta(days=terms)
                    due_dt = dt_obj.isoformat()
                except ValueError:
                    due_dt = inv_dt
            else:
                due_dt = str(due_date).strip()[:10]

            raw_lines = []
            subtotal = 0
            for raw in items:
                pid = _int(raw.get("product_id"))
                p = conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
                if not p:
                    raise ApiError("أحد الأصناف غير موجود في الكتالوج")
                qty = max(1, _int(raw.get("qty"), 1))
                uc = _money(raw.get("unit_cost"), 0)
                if uc < 0:
                    raise ApiError("سعر التكلفة لا يمكن أن يكون سالباً")
                new_sp = _money(raw.get("new_sell_price"), 0) if raw.get("new_sell_price") not in (None, "", 0, "0") else None
                exp_dt = (raw.get("expiry_date") or "").strip()[:10] or None
                serials = raw.get("serials") or []
                if isinstance(serials, str):
                    serials = [x.strip() for x in serials.replace(",", "\n").splitlines() if x.strip()]
                line_total = qty * uc
                subtotal += line_total
                raw_lines.append({
                    "product_id": pid,
                    "sku": p["sku"],
                    "name": p["name"],
                    "qty": qty,
                    "unit_cost": uc,
                    "new_sell_price": new_sp,
                    "tax_rate": t_rate,
                    "line_total": line_total,
                    "expiry_date": exp_dt,
                    "serials": serials,
                })

            if disc > subtotal:
                raise ApiError("قيمة الخصم المكتسب لا يمكن أن تتجاوز إجمالي الأصناف")

            allocated_lines = erp_hooks.allocate_landed_costs(raw_lines, invoice_discount=disc, shipping_cost=ship)
            taxable_base = max(0, subtotal - disc)
            tax_amt = int((Decimal(taxable_base) * Decimal(t_rate) / Decimal(100)).to_integral_value(rounding=ROUND_HALF_UP))
            wht_amt = int((Decimal(taxable_base) * Decimal(w_rate) / Decimal(100)).to_integral_value(rounding=ROUND_HALF_UP))
            total = max(0, taxable_base + ship + tax_amt - wht_amt)

            if paid > total:
                paid = total

            shift_id = None
            if paid > 0 and use_drawer:
                s_open = self._open_shift(conn, u["id"])
                if not s_open:
                    raise ApiError("الدفع من درج الكاشير يتطلب وجود وردية مفتوحة — افتح وردية أولاً أو ادفع من الخزنة الرئيسية")
                shift_id = s_open["id"]

            now_ts = db.now()
            po_id_val = _int(po_id) if po_id else None
            tr_id_val = _int(treasury_id) if treasury_id else None

            if id:
                pur_id = _int(id)
                ex = conn.execute("SELECT * FROM purchases WHERE id=?", (pur_id,)).fetchone()
                if not ex:
                    raise ApiError("فاتورة المشتريات غير موجودة")
                if ex["status"] != "draft":
                    raise ApiError("لا يمكن تعديل فاتورة مشتريات مرحلة — استخدم مرتجع المشتريات أو عكس الفاتورة")
                conn.execute(
                    """UPDATE purchases
                       SET supplier_id=?, supplier_invoice_no=?, po_id=?, invoice_date=?, due_date=?,
                           subtotal=?, discount=?, shipping_cost=?, tax_rate=?, tax=?, wht_rate=?, wht_amount=?,
                           total=?, paid_amount=?, payment_method=?, treasury_id=?, shift_id=?, ref_no=?,
                           status=?, notes=?, posted_at=?
                       WHERE id=?""",
                    (
                        sid, sup_inv_no, po_id_val, inv_dt, due_dt,
                        subtotal, disc, ship, t_rate, tax_amt, w_rate, wht_amt,
                        total, paid, method, tr_id_val, shift_id, ref_no_clean,
                        status, (notes or "").strip() or None,
                        now_ts if status == "posted" else None,
                        pur_id,
                    ),
                )
                conn.execute("DELETE FROM purchase_items WHERE purchase_id=?", (pur_id,))
            else:
                cur = conn.execute(
                    """INSERT INTO purchases
                       (purchase_no, supplier_id, supplier_invoice_no, po_id, invoice_date, due_date,
                        subtotal, discount, shipping_cost, tax_rate, tax, wht_rate, wht_amount,
                        total, paid_amount, payment_method, treasury_id, shift_id, ref_no,
                        status, notes, user_id, created_at, posted_at)
                       VALUES('PUR-TMP',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        sid, sup_inv_no, po_id_val, inv_dt, due_dt,
                        subtotal, disc, ship, t_rate, tax_amt, w_rate, wht_amt,
                        total, paid, method, tr_id_val, shift_id, ref_no_clean,
                        status, (notes or "").strip() or None, u["id"], now_ts,
                        now_ts if status == "posted" else None,
                    ),
                )
                pur_id = cur.lastrowid
                year_s = inv_dt[:4]
                pur_no = _format_doc_seq(f"PUR-{year_s}-", pur_id)
                conn.execute("UPDATE purchases SET purchase_no=? WHERE id=?", (pur_no, pur_id))

            for ln in allocated_lines:
                conn.execute(
                    """INSERT INTO purchase_items
                       (purchase_id, product_id, sku, name, qty, returned_qty, unit_cost, landed_unit_cost,
                        new_sell_price, tax_rate, line_total, expiry_date, serials_json)
                       VALUES(?,?,?,?,?,0,?,?,?,?,?,?,?)""",
                    (
                        pur_id, ln["product_id"], ln["sku"], ln["name"], ln["qty"],
                        ln["unit_cost"], ln["landed_unit_cost"], ln["new_sell_price"],
                        ln["tax_rate"], ln["line_total"], ln["expiry_date"],
                        json.dumps(ln["serials"], ensure_ascii=False) if ln["serials"] else None,
                    ),
                )

            warnings = []
            if status == "posted":
                pur_row = conn.execute("SELECT * FROM purchases WHERE id=?", (pur_id,)).fetchone()
                items_rows = conn.execute("SELECT * FROM purchase_items WHERE purchase_id=? ORDER BY id", (pur_id,)).fetchall()
                warnings = self._post_purchase_in_tx(conn, pur_row, items_rows, u)

        out = self.purchase_get(pur_id)
        out["margin_warnings"] = warnings
        return out

    def purchase_post(self, id, paid_amount=None, payment_method=None, treasury_id=None, from_drawer=False, ref_no=None):
        """ترحيل مسودة فاتورة مشتريات إلى معتمدة."""
        u = self._perm("purchases_create_post")
        pur_id = _int(id)
        with db.connect() as conn:
            pur = conn.execute("SELECT * FROM purchases WHERE id=?", (pur_id,)).fetchone()
            if not pur:
                raise ApiError("فاتورة المشتريات غير موجودة")
            if pur["status"] != "draft":
                raise ApiError("هذه الفاتورة مرحلة بالفعل أو ملغاة")
            paid = _money(paid_amount) if paid_amount is not None else int(pur["paid_amount"] or 0)
            paid = max(0, min(int(pur["total"] or 0), paid))
            method = (payment_method or pur["payment_method"] or "cash").strip()
            tr_id = _int(treasury_id) if treasury_id else pur["treasury_id"]
            shift_id = pur["shift_id"]
            if paid > 0 and from_drawer:
                s_open = self._open_shift(conn, u["id"])
                if not s_open:
                    raise ApiError("الدفع من درج الكاشير يتطلب فتح وردية أولاً")
                shift_id = s_open["id"]
            conn.execute(
                "UPDATE purchases SET status='posted', paid_amount=?, payment_method=?, treasury_id=?, shift_id=?, ref_no=COALESCE(?, ref_no), posted_at=? WHERE id=?",
                (paid, method, tr_id, shift_id, (ref_no or "").strip() or None, db.now(), pur_id),
            )
            pur_row = conn.execute("SELECT * FROM purchases WHERE id=?", (pur_id,)).fetchone()
            items_rows = conn.execute("SELECT * FROM purchase_items WHERE purchase_id=? ORDER BY id", (pur_id,)).fetchall()
            warnings = self._post_purchase_in_tx(conn, pur_row, items_rows, u)
        out = self.purchase_get(pur_id)
        out["margin_warnings"] = warnings
        return out

    def purchase_cancel(self, id, reason=None):
        """إلغاء مسودة فاتورة مشتريات أو عكس فاتورة مشتريات لم يتم إرجاع بنود منها."""
        u = self._perm("purchases_cancel_delete")
        pur_id = _int(id)
        with db.connect() as conn:
            pur = conn.execute("SELECT * FROM purchases WHERE id=?", (pur_id,)).fetchone()
            if not pur:
                raise ApiError("فاتورة المشتريات غير موجودة")
            if pur["status"] == "cancelled":
                raise ApiError("الفاتورة ملغاة مسبقاً")
            if pur["status"] == "draft":
                conn.execute("UPDATE purchases SET status='cancelled' WHERE id=?", (pur_id,))
                return {"id": pur_id, "status": "cancelled"}

            has_ret = conn.execute("SELECT 1 FROM purchase_returns WHERE purchase_id=?", (pur_id,)).fetchone()
            if has_ret:
                raise ApiError("لا يمكن إلغاء فاتورة تم عمل مرتجع جزئي عليها")

            items = conn.execute("SELECT * FROM purchase_items WHERE purchase_id=?", (pur_id,)).fetchall()
            now_ts = db.now()
            for it in items:
                p = conn.execute("SELECT qty FROM products WHERE id=?", (it["product_id"],)).fetchone()
                if p and int(p["qty"] or 0) < int(it["qty"] or 0):
                    raise ApiError(f"لا يمكن إلغاء الفاتورة لأن جزءاً من الصنف «{it['name']}» تم بيعه بالفعل")
            for it in items:
                conn.execute("UPDATE products SET qty=qty-? WHERE id=?", (it["qty"], it["product_id"]))
                conn.execute("DELETE FROM serials WHERE purchase_item_id=? AND status='in_stock'", (it["id"],))
                after = conn.execute("SELECT qty FROM products WHERE id=?", (it["product_id"],)).fetchone()[0]
                conn.execute(
                    """INSERT INTO stock_movements(created_at, user_id, product_id, qty_change, qty_after, reason, ref)
                       VALUES(?,?,?,?,?,?,?)""",
                    (now_ts, u["id"], it["product_id"], -it["qty"], after, "purchase_cancel", pur["purchase_no"]),
                )

            conn.execute("UPDATE purchases SET status='cancelled' WHERE id=?", (pur_id,))
            net_unpaid = max(0, int(pur["total"] or 0) - int(pur["paid_amount"] or 0))
            if net_unpaid > 0:
                _append_supplier_ledger(
                    conn,
                    pur["supplier_id"],
                    "adjustment",
                    pur["purchase_no"],
                    debit=net_unpaid,
                    purchase_id=pur_id,
                    notes=f"إلغاء فاتورة مشتريات ({pur['purchase_no']}) — {reason or ''}".strip(" —"),
                    user_id=u["id"],
                    user_name=u["name"],
                )
            else:
                _refresh_supplier_cache(conn, pur["supplier_id"])

            if erp_hooks.is_module_active(self, conn, "accounting"):
                je = conn.execute(
                    "SELECT id FROM journal_entries WHERE source_table='purchases' AND source_id=? AND status='posted' ORDER BY id DESC LIMIT 1",
                    (pur_id,),
                ).fetchone()
                if je:
                    erp_hooks.reverse_journal_entry(conn, je["id"], reason=reason or f"إلغاء فاتورة مشتريات {pur['purchase_no']}", user_id=u["id"])
            return {"id": pur_id, "status": "cancelled"}

    def purchase_get(self, id):
        self._perm_any("purchases_view", "purchases_create_post", "purchases_return")
        can_cost = self._has_perm("cost_view") or self._has_perm("purchases_create_post")
        pur_id = _int(id)
        with db.connect() as conn:
            r = conn.execute(
                """SELECT p.*, s.name AS supplier_name, s.code AS supplier_code, s.phone AS supplier_phone,
                          s.tax_reg_no AS supplier_tax_reg, u.name AS user_name
                   FROM purchases p
                   JOIN suppliers s ON s.id = p.supplier_id
                   LEFT JOIN users u ON u.id = p.user_id
                   WHERE p.id=?""",
                (pur_id,),
            ).fetchone()
            if not r:
                raise ApiError("فاتورة المشتريات غير موجودة")
            d = dict(r)
            items = [dict(x) for x in conn.execute("SELECT * FROM purchase_items WHERE purchase_id=? ORDER BY id", (pur_id,)).fetchall()]
            for it in items:
                it["remaining_qty"] = max(0, int(it["qty"] or 0) - int(it["returned_qty"] or 0))
                if not can_cost:
                    it["unit_cost"] = None
                    it["landed_unit_cost"] = None
                    it["line_total"] = None
            d["items"] = items
            d["due_amount"] = max(0, int(d["total"] or 0) - int(d["paid_amount"] or 0))
            if erp_hooks.is_module_active(self, conn, "accounting"):
                je = conn.execute(
                    "SELECT id, entry_no, status FROM journal_entries WHERE source_table='purchases' AND source_id=? ORDER BY id DESC LIMIT 1",
                    (pur_id,),
                ).fetchone()
                d["journal_entry"] = dict(je) if je else None
            return d

    def purchases_list(self, q="", status=None, supplier_id=None, date_from=None, date_to=None, limit=100, offset=0):
        self._perm_any("purchases_view", "purchases_create_post")
        limit = max(1, min(200, _int(limit, 100)))
        offset = max(0, _int(offset, 0))
        where = ["1=1"]
        args = []
        if status:
            where.append("p.status=?")
            args.append(status)
        if supplier_id:
            where.append("p.supplier_id=?")
            args.append(_int(supplier_id))
        if date_from:
            where.append("p.invoice_date >= ?")
            args.append(date_from.strip()[:10])
        if date_to:
            where.append("p.invoice_date <= ?")
            args.append(date_to.strip()[:10])
        if q:
            like = f"%{q}%"
            where.append("(p.purchase_no LIKE ? OR COALESCE(p.supplier_invoice_no,'') LIKE ? OR s.name LIKE ?)")
            args.extend([like, like, like])
        w_sql = " AND ".join(where)
        with db.connect() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM purchases p JOIN suppliers s ON s.id=p.supplier_id WHERE {w_sql}",
                args,
            ).fetchone()[0]
            rows = conn.execute(
                f"""SELECT p.*, s.name AS supplier_name, u.name AS user_name
                    FROM purchases p
                    JOIN suppliers s ON s.id = p.supplier_id
                    LEFT JOIN users u ON u.id = p.user_id
                    WHERE {w_sql}
                    ORDER BY p.id DESC LIMIT ? OFFSET ?""",
                [*args, limit, offset],
            ).fetchall()
            out = []
            for r in rows:
                d = dict(r)
                d["due_amount"] = max(0, int(d["total"] or 0) - int(d["paid_amount"] or 0))
                out.append(d)
            return {"rows": out, "total": total}

    # ---------------------------------------------------------- مرتجعات المشتريات
    def purchase_return_create(self, purchase_id, items, refund_method="credit", treasury_id=None, from_drawer=False, reason=None):
        """إرجاع بضاعة لمورد وخصمها من المخزون وحساب المورد (أو استردادها نقداً للخزنة)."""
        u = self._perm("purchases_return")
        pur_id = _int(purchase_id)
        items = items or []
        if not items:
            raise ApiError("اختر الأصناف والكميات المراد إرجاعها للمورد")
        refund_method = (refund_method or "credit").strip().lower()
        if refund_method not in ("credit", "cash", "wallet", "bank"):
            refund_method = "credit"

        with db.connect() as conn:
            pur = conn.execute("SELECT * FROM purchases WHERE id=?", (pur_id,)).fetchone()
            if not pur:
                raise ApiError("فاتورة المشتريات غير موجودة")
            if pur["status"] not in ("posted", "partial_return"):
                raise ApiError("لا يمكن عمل مرتجع إلا لفاتورة مشتريات معتمدة")

            shift_id = None
            if refund_method == "cash" and from_drawer:
                s_open = self._open_shift(conn, u["id"])
                if not s_open:
                    raise ApiError("استرداد النقدية في درج الكاشير يتطلب وردية مفتوحة")
                shift_id = s_open["id"]

            now_ts = db.now()
            ret_lines = []
            sub_ret = 0

            for req in items:
                p_item_id = _int(req.get("purchase_item_id"))
                qty = _int(req.get("qty"), 0)
                if qty <= 0:
                    continue
                pi = conn.execute(
                    "SELECT * FROM purchase_items WHERE id=? AND purchase_id=?",
                    (p_item_id, pur_id),
                ).fetchone()
                if not pi:
                    raise ApiError("أحد بنود المرتجع لا ينتمي لهذه الفاتورة")
                rem = int(pi["qty"] or 0) - int(pi["returned_qty"] or 0)
                if qty > rem:
                    raise ApiError(f"كمية المرتجع للصنف «{pi['name']}» أكبر من المتاح في الفاتورة ({rem})")
                p = conn.execute("SELECT qty, name FROM products WHERE id=?", (pi["product_id"],)).fetchone()
                if not p or int(p["qty"] or 0) < qty:
                    raise ApiError(f"رصيد المخزون الحالي للصنف «{pi['name']}» لا يكفي لإتمام المرتجع للمورد")

                uc = int(pi["landed_unit_cost"] or pi["unit_cost"] or 0)
                amt = qty * uc
                sub_ret += amt
                ret_lines.append((pi, qty, uc, amt, req.get("serials") or []))

            if not ret_lines:
                raise ApiError("يرجى تحديد كمية أكبر من صفر للإرجاع")

            t_rate = int(pur["tax_rate"] or 0)
            w_rate = int(pur["wht_rate"] or 0)
            tax_ret = int((Decimal(sub_ret) * Decimal(t_rate) / Decimal(100)).to_integral_value(rounding=ROUND_HALF_UP))
            wht_ret = int((Decimal(sub_ret) * Decimal(w_rate) / Decimal(100)).to_integral_value(rounding=ROUND_HALF_UP))
            tot_ret = max(0, sub_ret + tax_ret - wht_ret)

            cur = conn.execute(
                """INSERT INTO purchase_returns
                   (return_no, purchase_id, supplier_id, created_at, subtotal, tax_amount, wht_amount, total,
                    refund_method, treasury_id, shift_id, reason, user_id)
                   VALUES('PRN-TMP',?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    pur_id, pur["supplier_id"], now_ts, sub_ret, tax_ret, wht_ret, tot_ret,
                    refund_method, _int(treasury_id) if treasury_id else None, shift_id,
                    (reason or "").strip() or "مرتجع مشتريات للمورد", u["id"],
                ),
            )
            ret_id = cur.lastrowid
            ret_no = _format_doc_seq(f"PRN-{now_ts[:4]}-", ret_id)
            conn.execute("UPDATE purchase_returns SET return_no=? WHERE id=?", (ret_no, ret_id))

            for pi, qty, uc, amt, serials_ret in ret_lines:
                conn.execute(
                    """INSERT INTO purchase_return_items
                       (return_id, purchase_item_id, product_id, qty, unit_cost, amount, serials_json)
                       VALUES(?,?,?,?,?,?,?)""",
                    (ret_id, pi["id"], pi["product_id"], qty, uc, amt, json.dumps(serials_ret, ensure_ascii=False) if serials_ret else None),
                )
                conn.execute("UPDATE purchase_items SET returned_qty=returned_qty+? WHERE id=?", (qty, pi["id"]))
                conn.execute("UPDATE products SET qty=qty-? WHERE id=?", (qty, pi["product_id"]))
                if serials_ret:
                    ph = ",".join("?" for _ in serials_ret)
                    conn.execute(f"DELETE FROM serials WHERE product_id=? AND serial IN ({ph}) AND status='in_stock'", [pi["product_id"], *serials_ret])
                after = conn.execute("SELECT qty FROM products WHERE id=?", (pi["product_id"],)).fetchone()[0]
                conn.execute(
                    """INSERT INTO stock_movements(created_at, user_id, product_id, qty_change, qty_after, reason, ref)
                       VALUES(?,?,?,?,?,?,?)""",
                    (now_ts, u["id"], pi["product_id"], -qty, after, "purchase_return", ret_no),
                )

            rem_all = conn.execute(
                "SELECT COALESCE(SUM(qty - returned_qty), 0) FROM purchase_items WHERE purchase_id=?",
                (pur_id,),
            ).fetchone()[0]
            new_status = "returned" if rem_all <= 0 else "partial_return"
            conn.execute("UPDATE purchases SET status=? WHERE id=?", (new_status, pur_id))

            if refund_method == "credit":
                _append_supplier_ledger(
                    conn,
                    pur["supplier_id"],
                    "purchase_return",
                    ret_no,
                    debit=tot_ret,
                    purchase_id=pur_id,
                    method="credit",
                    notes=f"مرتجع مشتريات ({ret_no}) من فاتورة ({pur['purchase_no']})",
                    user_id=u["id"],
                    user_name=u["name"],
                    created_at=now_ts,
                )
            else:
                _refresh_supplier_cache(conn, pur["supplier_id"])

            erp_hooks.on_purchase_returned(self, conn, return_id=ret_id, purchase_id=pur_id, user=u)
            return {"return_id": ret_id, "return_no": ret_no, "total": tot_ret, "purchase_status": new_status}

    def purchase_returns_list(self, purchase_id=None, supplier_id=None, limit=100, offset=0):
        self._perm_any("purchases_view", "purchases_return")
        limit = max(1, min(200, _int(limit, 100)))
        offset = max(0, _int(offset, 0))
        where = ["1=1"]
        args = []
        if purchase_id:
            where.append("pr.purchase_id=?")
            args.append(_int(purchase_id))
        if supplier_id:
            where.append("pr.supplier_id=?")
            args.append(_int(supplier_id))
        w_sql = " AND ".join(where)
        with db.connect() as conn:
            rows = conn.execute(
                f"""SELECT pr.*, p.purchase_no, s.name AS supplier_name, u.name AS user_name
                    FROM purchase_returns pr
                    JOIN purchases p ON p.id = pr.purchase_id
                    JOIN suppliers s ON s.id = pr.supplier_id
                    LEFT JOIN users u ON u.id = pr.user_id
                    WHERE {w_sql}
                    ORDER BY pr.id DESC LIMIT ? OFFSET ?""",
                [*args, limit, offset],
            ).fetchall()
            return [dict(r) for r in rows]

    # ---------------------------------------------------------- تقارير ولوحة المشتريات
    def purchases_dashboard(self):
        self._perm_any("purchases_view", "suppliers_view")
        today = datetime.date.today().isoformat()
        month_prefix = today[:7]
        with db.connect() as conn:
            m_pur = conn.execute(
                """SELECT COUNT(*) AS cnt, COALESCE(SUM(total), 0) AS tot
                   FROM purchases
                   WHERE status IN ('posted','partial_return') AND invoice_date LIKE ?""",
                (f"{month_prefix}%",),
            ).fetchone()
            sup_sum = conn.execute(
                """SELECT COUNT(*) AS cnt, COALESCE(SUM(balance), 0) AS total_ap
                   FROM suppliers WHERE active=1"""
            ).fetchone()
            po_open = conn.execute(
                "SELECT COUNT(*) AS cnt FROM purchase_orders WHERE status IN ('draft','ordered','partial_received')"
            ).fetchone()
            ret_month = conn.execute(
                "SELECT COUNT(*) AS cnt, COALESCE(SUM(total), 0) AS tot FROM purchase_returns WHERE created_at LIKE ?",
                (f"{month_prefix}%",),
            ).fetchone()
            return {
                "month_purchases_count": m_pur["cnt"],
                "month_purchases_total": m_pur["tot"],
                "suppliers_count": sup_sum["cnt"],
                "total_ap_balance": sup_sum["total_ap"],
                "open_po_count": po_open["cnt"],
                "month_returns_count": ret_month["cnt"],
                "month_returns_total": ret_month["tot"],
            }

    def report_ap_aging(self):
        """تقرير أعمار الديون الدائنة للموردين (AP Aging: 0-30 / 31-60 / 61-90 / +90 يوماً)."""
        self._perm_any("suppliers_view", "purchases_view")
        today_dt = datetime.date.today()
        with db.connect() as conn:
            sups = conn.execute(
                "SELECT id, code, name, company_name, phone, balance FROM suppliers WHERE active=1 AND balance > 0 ORDER BY balance DESC"
            ).fetchall()
            rows = []
            totals = {"b_0_30": 0, "b_31_60": 0, "b_61_90": 0, "b_90_plus": 0, "total": 0}
            for s in sups:
                rem = int(s["balance"] or 0)
                bills = conn.execute(
                    """SELECT invoice_date, due_date, total, paid_amount
                       FROM purchases
                       WHERE supplier_id=? AND status IN ('posted','partial_return')
                       ORDER BY invoice_date DESC, id DESC""",
                    (s["id"],),
                ).fetchall()
                b0 = b30 = b60 = b90 = 0
                left = rem
                for b in bills:
                    if left <= 0:
                        break
                    unpaid = max(0, int(b["total"] or 0) - int(b["paid_amount"] or 0))
                    if unpaid <= 0:
                        continue
                    chunk = min(left, unpaid)
                    ref_dt_s = (b["invoice_date"] or today_dt.isoformat())[:10]
                    try:
                        days = (today_dt - datetime.date.fromisoformat(ref_dt_s)).days
                    except ValueError:
                        days = 0
                    if days <= 30:
                        b0 += chunk
                    elif days <= 60:
                        b30 += chunk
                    elif days <= 90:
                        b60 += chunk
                    else:
                        b90 += chunk
                    left -= chunk
                if left > 0:
                    b0 += left
                rows.append({
                    "supplier_id": s["id"],
                    "code": s["code"],
                    "name": s["name"],
                    "phone": s["phone"],
                    "b_0_30": b0,
                    "b_31_60": b30,
                    "b_61_90": b60,
                    "b_90_plus": b90,
                    "total": rem,
                })
                totals["b_0_30"] += b0
                totals["b_31_60"] += b30
                totals["b_61_90"] += b60
                totals["b_90_plus"] += b90
                totals["total"] += rem
            return {"rows": rows, "totals": totals}

    def report_price_variance(self, threshold_pct=5):
        """تقرير تغيرات وتنبيهات ارتفاع أسعار الشراء للأصناف (Price Variance Alert)."""
        self._perm_any("purchases_view", "cost_view")
        thr = max(0, _int(threshold_pct, 5))
        with db.connect() as conn:
            rows = conn.execute(
                """SELECT h.*, p.name AS product_name, p.sku, p.price AS current_sell_price
                   FROM product_cost_history h
                   JOIN products p ON p.id = h.product_id
                   WHERE h.old_cost > 0
                   ORDER BY h.id DESC LIMIT 100"""
            ).fetchall()
            out = []
            for r in rows:
                d = dict(r)
                old_c = int(d["old_cost"] or 0)
                new_c = int(d["landed_unit_cost"] or d["unit_cost"] or 0)
                diff = new_c - old_c
                pct = round((diff / old_c) * 100, 2) if old_c > 0 else 0.0
                d["diff"] = diff
                d["variance_pct"] = pct
                if abs(pct) >= thr:
                    out.append(d)
            return out

    def product_cost_history_list(self, product_id=None, limit=50):
        self._perm_any("purchases_view", "cost_view")
        lim = max(1, min(200, _int(limit, 50)))
        with db.connect() as conn:
            if product_id:
                rows = conn.execute(
                    """SELECT h.*, p.name AS product_name, p.sku
                       FROM product_cost_history h
                       JOIN products p ON p.id = h.product_id
                       WHERE h.product_id=?
                       ORDER BY h.id DESC LIMIT ?""",
                    (_int(product_id), lim),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT h.*, p.name AS product_name, p.sku
                       FROM product_cost_history h
                       JOIN products p ON p.id = h.product_id
                       ORDER BY h.id DESC LIMIT ?""",
                    (lim,),
                ).fetchall()
            return [dict(r) for r in rows]
