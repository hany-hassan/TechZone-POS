"""نظام الأقساط: العقود، جدولة الأقساط، التحصيل، تنبيهات المتأخرات، والتذكير عبر واتساب."""
import calendar
import datetime
import os
import urllib.parse
import webbrowser
from decimal import Decimal, ROUND_HALF_UP

import db
from api_common import (
    ApiError,
    _append_ledger_entry,
    _fmt_money,
    _format_doc_seq,
    _int,
    _money,
    _normalize_eg_phone,
    _refresh_customer_cache,
    _resolve_sale_customer_id,
    _sale_net_credit,
    _upsert_customer,
)


def _add_months(d: datetime.date, months_offset: int) -> datetime.date:
    """إضافة أشهر بأمان مع معالجة نهاية الشهر (مثلاً 31 يناير ← 28/29 فبراير)."""
    m_idx = (d.month - 1) + months_offset
    year = d.year + m_idx // 12
    month = (m_idx % 12) + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return datetime.date(year, month, day)


def _parse_iso_date(raw: str | None, default_dt: datetime.date | None = None) -> datetime.date:
    s = (raw or "").strip()[:10]
    if not s:
        if default_dt is not None:
            return default_dt
        raise ApiError("يرجى إدخال تاريخ صحيح بصيغة YYYY-MM-DD")
    try:
        return datetime.date.fromisoformat(s)
    except ValueError:
        raise ApiError("صيغة التاريخ غير صالحة (المطلوب YYYY-MM-DD)")


def _generate_schedule(financed_total: int, count: int, frequency: str, interval_days: int, start_dt: datetime.date) -> list[tuple[int, str, int]]:
    """توليد جدول الأقساط بحيث يساوي مجموع الأقساط المبلغ الممول بالقرش دون فقد كسور."""
    base = financed_total // count
    rem = financed_total % count
    step_days = max(1, interval_days)
    out = []
    for i in range(count):
        if frequency == "monthly":
            due = _add_months(start_dt, i)
        elif frequency == "weekly":
            due = start_dt + datetime.timedelta(days=7 * i)
        else:
            due = start_dt + datetime.timedelta(days=step_days * i)
        amt = base + (rem if i == count - 1 else 0)
        out.append((i + 1, due.isoformat(), amt))
    return out


class InstallmentsMixin:
    # ---------------------------------------------------------- إدارة الأقساط
    def installment_alerts(self):
        """إرجاع عدادات المتأخرات والأقساط المستحقة قريباً للوحة التنبيهات السريعة."""
        u = self._user()
        if u["role"] != "admin":
            perms = u.get("permissions") or {}
            if not (perms.get("installments_view") or perms.get("installments_collect") or perms.get("installments_create")):
                return {"overdue_count": 0, "overdue_amount": 0, "due_soon_count": 0, "due_soon_amount": 0, "active_count": 0}
        today = datetime.date.today().isoformat()
        soon_end = (datetime.date.today() + datetime.timedelta(days=7)).isoformat()
        with db.connect() as conn:
            ov = conn.execute(
                """SELECT COUNT(*) AS cnt, COALESCE(SUM(ii.amount - ii.paid_amount), 0) AS amt
                   FROM installment_items ii
                   JOIN installment_plans p ON p.id = ii.plan_id
                   WHERE p.status = 'active' AND ii.status IN ('pending','partial') AND ii.due_date < ?""",
                (today,),
            ).fetchone()
            soon = conn.execute(
                """SELECT COUNT(*) AS cnt, COALESCE(SUM(ii.amount - ii.paid_amount), 0) AS amt
                   FROM installment_items ii
                   JOIN installment_plans p ON p.id = ii.plan_id
                   WHERE p.status = 'active' AND ii.status IN ('pending','partial')
                     AND ii.due_date >= ? AND ii.due_date <= ?""",
                (today, soon_end),
            ).fetchone()
            act = conn.execute("SELECT COUNT(*) AS cnt FROM installment_plans WHERE status='active'").fetchone()
            return {
                "overdue_count": ov["cnt"],
                "overdue_amount": ov["amt"],
                "due_soon_count": soon["cnt"],
                "due_soon_amount": soon["amt"],
                "active_count": act["cnt"],
            }

    def installments_list(self, q="", status="all", limit=50, offset=0):
        self._perm_any("installments_view", "installments_collect", "installments_create")
        limit = max(1, min(200, _int(limit, 50)))
        offset = max(0, _int(offset, 0))
        q = (q or "").strip()
        status = (status or "all").strip()
        today = datetime.date.today().isoformat()
        soon_end = (datetime.date.today() + datetime.timedelta(days=7)).isoformat()
        month_prefix = today[:7]

        clauses = []
        args = []
        if status == "active":
            clauses.append("p.status = 'active'")
        elif status == "completed":
            clauses.append("p.status = 'completed'")
        elif status == "cancelled":
            clauses.append("p.status = 'cancelled'")
        elif status == "overdue":
            clauses.append(
                "p.status = 'active' AND EXISTS (SELECT 1 FROM installment_items ii WHERE ii.plan_id=p.id AND ii.status IN ('pending','partial') AND ii.due_date < ?)"
            )
            args.append(today)
        elif status == "upcoming":
            clauses.append(
                "p.status = 'active' AND EXISTS (SELECT 1 FROM installment_items ii WHERE ii.plan_id=p.id AND ii.status IN ('pending','partial') AND ii.due_date >= ? AND ii.due_date <= ?)"
            )
            args.extend([today, soon_end])

        if q:
            like = f"%{q}%"
            clauses.append(
                "(p.plan_no LIKE ? OR p.title LIKE ? OR COALESCE(p.serial,'') LIKE ? "
                "OR c.name LIKE ? OR COALESCE(c.phone,'') LIKE ? OR COALESCE(p.national_id,'') LIKE ? "
                "OR COALESCE(p.guarantor_name,'') LIKE ?)"
            )
            args.extend([like, like, like, like, like, like, like])

        where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""

        with db.connect() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM installment_plans p JOIN customers c ON c.id = p.customer_id {where_sql}",
                args,
            ).fetchone()[0]

            rows = conn.execute(
                f"""SELECT p.*,
                           c.name AS customer_name,
                           c.phone AS customer_phone,
                           s.invoice_no AS sale_invoice_no,
                           u.name AS user_name,
                           (SELECT COUNT(*) FROM installment_items ii WHERE ii.plan_id=p.id AND ii.status='paid') AS paid_count,
                           (SELECT MIN(ii.due_date) FROM installment_items ii WHERE ii.plan_id=p.id AND ii.status IN ('pending','partial')) AS next_due_date,
                           (SELECT ii.amount - ii.paid_amount FROM installment_items ii WHERE ii.plan_id=p.id AND ii.status IN ('pending','partial') ORDER BY ii.seq_no LIMIT 1) AS next_due_amount,
                           (SELECT COUNT(*) FROM installment_items ii WHERE ii.plan_id=p.id AND ii.status IN ('pending','partial') AND ii.due_date < ?) AS overdue_count,
                           (SELECT COALESCE(SUM(ii.amount - ii.paid_amount), 0) FROM installment_items ii WHERE ii.plan_id=p.id AND ii.status IN ('pending','partial') AND ii.due_date < ?) AS overdue_amount
                    FROM installment_plans p
                    JOIN customers c ON c.id = p.customer_id
                    LEFT JOIN sales s ON s.id = p.sale_id
                    LEFT JOIN users u ON u.id = p.user_id
                    {where_sql}
                    ORDER BY
                      CASE WHEN p.status='active' AND overdue_count > 0 THEN 0
                           WHEN p.status='active' THEN 1
                           WHEN p.status='completed' THEN 2 ELSE 3 END,
                      COALESCE(next_due_date, '9999-12-31') ASC,
                      p.id DESC
                    LIMIT ? OFFSET ?""",
                [today, today, *args, limit, offset],
            ).fetchall()

            sum_plans = conn.execute(
                """SELECT
                      COALESCE(SUM(CASE WHEN status='active' THEN 1 ELSE 0 END), 0) AS active_count,
                      COALESCE(SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END), 0) AS completed_count,
                      COALESCE(SUM(CASE WHEN status='active' THEN remaining_total ELSE 0 END), 0) AS remaining_portfolio,
                      COALESCE(SUM(CASE WHEN status!='cancelled' THEN financed_total ELSE 0 END), 0) AS total_financed
                   FROM installment_plans"""
            ).fetchone()
            ov_sum = conn.execute(
                """SELECT COUNT(DISTINCT ii.plan_id) AS overdue_plans,
                          COUNT(*) AS overdue_items,
                          COALESCE(SUM(ii.amount - ii.paid_amount), 0) AS overdue_amount
                   FROM installment_items ii
                   JOIN installment_plans p ON p.id = ii.plan_id
                   WHERE p.status='active' AND ii.status IN ('pending','partial') AND ii.due_date < ?""",
                (today,),
            ).fetchone()
            up_sum = conn.execute(
                """SELECT COUNT(*) AS upcoming_items,
                          COALESCE(SUM(ii.amount - ii.paid_amount), 0) AS upcoming_amount
                   FROM installment_items ii
                   JOIN installment_plans p ON p.id = ii.plan_id
                   WHERE p.status='active' AND ii.status IN ('pending','partial')
                     AND ii.due_date >= ? AND ii.due_date <= ?""",
                (today, soon_end),
            ).fetchone()
            coll_month = conn.execute(
                """SELECT COALESCE(SUM(ip.amount), 0) AS amt
                   FROM installment_payments ip
                   JOIN installment_plans p ON p.id = ip.plan_id
                   WHERE p.status != 'cancelled' AND ip.created_at LIKE ?""",
                (f"{month_prefix}%",),
            ).fetchone()

            return {
                "rows": [dict(r) for r in rows],
                "total": total,
                "summary": {
                    "active_count": sum_plans["active_count"],
                    "completed_count": sum_plans["completed_count"],
                    "remaining_portfolio": sum_plans["remaining_portfolio"],
                    "total_financed": sum_plans["total_financed"],
                    "overdue_plans_count": ov_sum["overdue_plans"],
                    "overdue_items_count": ov_sum["overdue_items"],
                    "overdue_amount": ov_sum["overdue_amount"],
                    "upcoming_items_count": up_sum["upcoming_items"],
                    "upcoming_amount": up_sum["upcoming_amount"],
                    "collected_month": coll_month["amt"],
                },
            }

    def installment_eligible_sales(self, customer_id):
        """جلب الفواتير الآجلة المفتوحة للعميل الصالحة للتحويل إلى خطة أقساط."""
        self._perm_any("installments_view", "installments_collect", "installments_create")
        cid = _int(customer_id)
        with db.connect() as conn:
            cust = conn.execute("SELECT * FROM customers WHERE id=?", (cid,)).fetchone()
            if not cust:
                return []
            cname = cust["name"]
            cphone = cust["phone"]
            rows = conn.execute(
                """SELECT s.id, s.invoice_no, s.created_at, s.total,
                          COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.sale_id=s.id AND p.method='credit'), 0) AS credit_amt,
                          COALESCE((SELECT SUM(sr.total) FROM sale_returns sr WHERE sr.sale_id=s.id), 0) AS ret_amt,
                          COALESCE((SELECT SUM(cp.amount) FROM customer_payments cp WHERE cp.sale_id=s.id), 0) AS voucher_paid
                   FROM sales s
                   WHERE (s.customer_id=? OR (s.customer_id IS NULL AND s.customer_name=?) OR (? IS NOT NULL AND ? != '' AND s.customer_phone=?))
                     AND s.status != 'returned'
                     AND NOT EXISTS (SELECT 1 FROM installment_plans ip WHERE ip.sale_id=s.id AND ip.status != 'cancelled')
                   ORDER BY s.id DESC
                   LIMIT 50""",
                (cid, cname, cphone, cphone, cphone),
            ).fetchall()
            out = []
            for r in rows:
                net_cr = max(0, r["credit_amt"] - r["ret_amt"] - r["voucher_paid"])
                if net_cr > 0:
                    d = dict(r)
                    d["net_credit"] = net_cr
                    out.append(d)
            return out

    def installment_detail(self, id):
        self._perm_any("installments_view", "installments_collect", "installments_create")
        pid = _int(id)
        today_dt = datetime.date.today()
        with db.connect() as conn:
            plan = conn.execute(
                """SELECT p.*,
                          c.name AS customer_name, c.phone AS customer_phone, c.debt AS customer_debt,
                          s.invoice_no AS sale_invoice_no,
                          u.name AS user_name
                   FROM installment_plans p
                   JOIN customers c ON c.id = p.customer_id
                   LEFT JOIN sales s ON s.id = p.sale_id
                   LEFT JOIN users u ON u.id = p.user_id
                   WHERE p.id=?""",
                (pid,),
            ).fetchone()
            if not plan:
                raise ApiError("عقد التقسيط غير موجود")

            items = conn.execute(
                "SELECT * FROM installment_items WHERE plan_id=? ORDER BY seq_no ASC",
                (pid,),
            ).fetchall()
            items_out = []
            for it in items:
                d = dict(it)
                rem = max(0, d["amount"] - d["paid_amount"])
                d["remaining"] = rem
                is_ov = False
                days_ov = 0
                if plan["status"] == "active" and d["status"] in ("pending", "partial") and rem > 0:
                    try:
                        due_dt = datetime.date.fromisoformat(d["due_date"])
                        if due_dt < today_dt:
                            is_ov = True
                            days_ov = (today_dt - due_dt).days
                    except ValueError:
                        pass
                d["is_overdue"] = is_ov
                d["days_overdue"] = days_ov
                items_out.append(d)

            pays = conn.execute(
                """SELECT ip.*, u.name AS user_name
                   FROM installment_payments ip
                   LEFT JOIN users u ON u.id = ip.user_id
                   WHERE ip.plan_id=?
                   ORDER BY ip.id DESC""",
                (pid,),
            ).fetchall()

            return {
                "plan": dict(plan),
                "items": items_out,
                "payments": [dict(p) for p in pays],
            }

    def installment_create(
        self,
        customer_id=None,
        customer_name=None,
        customer_phone=None,
        sale_id=None,
        product_id=None,
        qty=1,
        title=None,
        serial=None,
        principal=0,
        down_payment=0,
        down_method="cash",
        down_ref_no=None,
        fee_type="percent",
        fee_value=0,
        months=6,
        frequency="monthly",
        interval_days=30,
        start_date=None,
        national_id=None,
        guarantor_name=None,
        guarantor_phone=None,
        guarantor_national_id=None,
        notes=None,
    ):
        """إنشاء عقد تقسيط جديد مع توليد جدول الأقساط وقيد دفتر الأستاذ وتحديث المخزون."""
        u = self._perm("installments_create")
        count = _int(months, 6)
        if count < 1 or count > 120:
            raise ApiError("عدد الأقساط يجب أن يكون بين 1 و 120 قسطاً")
        freq = (frequency or "monthly").strip()
        if freq not in ("monthly", "weekly", "custom_days"):
            raise ApiError("دورية السداد غير صالحة")
        step_days = max(1, _int(interval_days, 30))
        down_method = (down_method or "cash").strip()
        if down_method not in ("cash", "wallet"):
            down_method = "cash"
        down_ref_no = (down_ref_no or "").strip() or None
        fee_type = (fee_type or "percent").strip()
        if fee_type not in ("percent", "fixed"):
            fee_type = "percent"

        today_dt = datetime.date.today()
        default_start = _add_months(today_dt, 1) if freq == "monthly" else (
            today_dt + datetime.timedelta(days=7 if freq == "weekly" else step_days)
        )
        start_dt = _parse_iso_date(start_date, default_dt=default_start)

        qty_val = max(1, _int(qty, 1))
        down_amt = max(0, _money(down_payment))
        if down_amt > 0 and down_method == "wallet" and not down_ref_no:
            raise ApiError("يرجى إدخال رقم العملية المرجعية لدفعة المقدم بالمحفظة")

        clean_title = (title or "").strip()
        clean_serial = (serial or "").strip() or None
        nid = (national_id or "").strip() or None
        g_name = (guarantor_name or "").strip() or None
        g_phone = (guarantor_phone or "").strip() or None
        g_nid = (guarantor_national_id or "").strip() or None
        clean_notes = (notes or "").strip() or None

        with db.connect() as conn:
            sid = _int(sale_id) if sale_id else None
            pid = _int(product_id) if product_id else None
            cid = _int(customer_id) if customer_id else None
            sale_row = None

            if sid:
                sale_row = conn.execute("SELECT * FROM sales WHERE id=?", (sid,)).fetchone()
                if not sale_row:
                    raise ApiError("الفاتورة المحددة غير موجودة")
                if sale_row["status"] == "returned":
                    raise ApiError("لا يمكن تقسيط فاتورة مرتجعة بالكامل")
                dup_plan = conn.execute(
                    "SELECT id, plan_no FROM installment_plans WHERE sale_id=? AND status != 'cancelled'",
                    (sid,),
                ).fetchone()
                if dup_plan:
                    raise ApiError(f"هذه الفاتورة مرتبطة بالفعل بعقد تقسيط نشط ({dup_plan['plan_no']})")
                already_credit = _sale_net_credit(conn, sid)
                voucher_paid = conn.execute(
                    "SELECT COALESCE(SUM(amount), 0) FROM customer_payments WHERE sale_id=?",
                    (sid,),
                ).fetchone()[0]
                net_remaining = max(0, already_credit - voucher_paid)
                if net_remaining <= 0:
                    raise ApiError("لا يوجد رصيد آجل متبقٍ على هذه الفاتورة")
                principal_amt = net_remaining
                if not clean_title:
                    clean_title = f"تقسيط فاتورة ({sale_row['invoice_no']})"
                resolved_cid = _resolve_sale_customer_id(conn, sale_row)
                if resolved_cid:
                    cid = resolved_cid

            if not cid:
                cname = (customer_name or "").strip()
                cphone = (customer_phone or "").strip() or None
                if not cname:
                    raise ApiError("يرجى اختيار العميل أو إدخال اسمه لفتح عقد التقسيط")
                cid = _upsert_customer(conn, cname, cphone)
            else:
                cust = conn.execute("SELECT * FROM customers WHERE id=?", (cid,)).fetchone()
                if not cust:
                    raise ApiError("العميل غير موجود")

            if not sid:
                prod_row = None
                if pid:
                    prod_row = conn.execute("SELECT * FROM products WHERE id=? AND active=1", (pid,)).fetchone()
                    if not prod_row:
                        raise ApiError("الصنف المحدد غير موجود أو غير نشط")
                    if prod_row["qty"] < qty_val:
                        raise ApiError(f"المخزون غير كافٍ للصنف «{prod_row['name']}» (المتوفر: {prod_row['qty']})")
                    if not clean_title:
                        clean_title = prod_row["name"]
                    if _money(principal) <= 0:
                        principal_amt = prod_row["price"] * qty_val
                    else:
                        principal_amt = _money(principal)
                else:
                    principal_amt = _money(principal)
                if principal_amt <= 0:
                    raise ApiError("قيمة العقد الإجمالية يجب أن تكون أكبر من صفر")
                if not clean_title:
                    raise ApiError("يرجى إدخال وصف الجهاز أو البيان لعقد التقسيط")
            if down_amt >= principal_amt:
                raise ApiError("الدفعة المقدمة يجب أن تكون أقل من إجمالي قيمة العقد")

            base_financed = principal_amt - down_amt
            try:
                fv_dec = Decimal(str(fee_value if fee_value not in (None, "") else 0))
            except Exception:
                raise ApiError("قيمة الزيادة / الفائدة غير صالحة")
            if fv_dec < 0:
                raise ApiError("لا يمكن أن تكون الفائدة أو الرسوم قيمة سالبة")

            if fee_type == "percent":
                fee_amt = int((Decimal(base_financed) * fv_dec / Decimal(100)).to_integral_value(rounding=ROUND_HALF_UP))
                fee_rate_bp = int((fv_dec * Decimal(100)).to_integral_value(rounding=ROUND_HALF_UP))
            else:
                fee_amt = _money(fee_value)
                fee_rate_bp = int(
                    (Decimal(fee_amt) * Decimal(10000) / Decimal(base_financed)).to_integral_value(rounding=ROUND_HALF_UP)
                ) if base_financed > 0 else 0

            financed_total = base_financed + fee_amt
            if financed_total <= 0:
                raise ApiError("المبلغ المقسط يجب أن يكون أكبر من صفر")

            pos_tpl = self._load_templates(conn)["pos"]
            inst_prefix = (pos_tpl.get("installment_prefix") or "INS-").strip() or "INS-"
            s_shift = self._open_shift(conn, u["id"])
            shift_id = s_shift["id"] if s_shift else None
            now_ts = db.now()

            # في الفاتورة الآجلة المحوّلة: أصل الآجل مُسجّل مسبقاً بـ credit_sale؛ نُضيف فقط الرسوم كـ installment_charge
            # وإذا حصل مقدم الآن نُسجّله كـ voucher مقترن بالفاتورة الآجلة
            ledger_charge = fee_amt if sid else financed_total

            cur = conn.execute(
                """INSERT INTO installment_plans
                   (plan_no, customer_id, sale_id, product_id, qty, title, serial,
                    principal, down_payment, down_method, down_ref_no,
                    fee_rate, fee_amount, financed_total, ledger_charge, paid_total, remaining_total,
                    months, frequency, interval_days, start_date, status,
                    national_id, guarantor_name, guarantor_phone, guarantor_national_id,
                    notes, user_id, shift_id, created_at, updated_at)
                   VALUES('INS-TMP',?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    cid, sid, pid, qty_val, clean_title, clean_serial,
                    principal_amt, down_amt, down_method, down_ref_no,
                    fee_rate_bp, fee_amt, financed_total, ledger_charge, financed_total,
                    count, freq, step_days, start_dt.isoformat(), "active",
                    nid, g_name, g_phone, g_nid,
                    clean_notes, u["id"], shift_id, now_ts, now_ts,
                ),
            )
            plan_id = cur.lastrowid
            plan_no = _format_doc_seq(inst_prefix, plan_id)
            if conn.execute("SELECT 1 FROM installment_plans WHERE plan_no=? AND id!=?", (plan_no, plan_id)).fetchone():
                plan_no = f"{plan_no}-{plan_id}"
            conn.execute("UPDATE installment_plans SET plan_no=? WHERE id=?", (plan_no, plan_id))

            schedule = _generate_schedule(financed_total, count, freq, step_days, start_dt)
            conn.executemany(
                """INSERT INTO installment_items(plan_id, customer_id, seq_no, due_date, amount, paid_amount, status)
                   VALUES(?,?,?,?,?,0,'pending')""",
                [(plan_id, cid, seq, due_d, amt) for seq, due_d, amt in schedule],
            )

            # خصم المخزون للعقد المستقل المرتبط بصنف
            if not sid and pid:
                if clean_serial:
                    sn_row = conn.execute(
                        "SELECT id FROM serials WHERE product_id=? AND serial=? AND status='in_stock'",
                        (pid, clean_serial),
                    ).fetchone()
                    if sn_row:
                        conn.execute("UPDATE serials SET status='sold' WHERE id=?", (sn_row["id"],))
                conn.execute("UPDATE products SET qty=qty-? WHERE id=?", (qty_val, pid))
                after_qty = conn.execute("SELECT qty FROM products WHERE id=?", (pid,)).fetchone()[0]
                conn.execute(
                    """INSERT INTO stock_movements(created_at, user_id, product_id, qty_change, qty_after, reason, ref)
                       VALUES(?,?,?,?,?,?,?)""",
                    (now_ts, u["id"], pid, -qty_val, after_qty, "installment", plan_no),
                )

            if sid:
                if down_amt > 0:
                    v_prefix = (pos_tpl.get("voucher_prefix") or "RCV-").strip() or "RCV-"
                    ts_compact = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
                    vcnt = conn.execute("SELECT COUNT(*) FROM customer_payments").fetchone()[0] + 1
                    sep = "" if (v_prefix[-1].isdigit() or v_prefix.endswith(("-", "/", "_"))) else "-"
                    v_ref = f"{v_prefix}{vcnt:03d}" if v_prefix[-1].isdigit() else f"{v_prefix}{sep}{ts_compact}-{vcnt:03d}"
                    if conn.execute("SELECT 1 FROM customer_payments WHERE ref=?", (v_ref,)).fetchone():
                        v_ref = f"{v_ref}-{plan_id}"
                    v_cur = conn.execute(
                        """INSERT INTO customer_payments(ref, customer_id, sale_id, user_id, shift_id, created_at, amount, method, ref_no, notes)
                           VALUES(?,?,?,?,?,?,?,?,?,?)""",
                        (v_ref, cid, sid, u["id"], shift_id, now_ts, down_amt, down_method, down_ref_no, f"مقدم تقسيط ({plan_no})"),
                    )
                    _append_ledger_entry(
                        conn, cid, "voucher", v_ref, credit=down_amt,
                        sale_id=sid, voucher_id=v_cur.lastrowid, plan_id=plan_id,
                        method=down_method, ref_no=down_ref_no,
                        notes=f"مقدم عقد تقسيط ({plan_no})",
                        user_id=u["id"], user_name=u["name"], created_at=now_ts,
                    )
                if ledger_charge > 0:
                    _append_ledger_entry(
                        conn, cid, "installment_charge", plan_no, debit=ledger_charge,
                        sale_id=sid, plan_id=plan_id, method="credit",
                        notes=f"رسوم تقسيط فاتورة {sale_row['invoice_no']} ({plan_no})",
                        user_id=u["id"], user_name=u["name"], created_at=now_ts,
                    )
                else:
                    _refresh_customer_cache(conn, cid)
            else:
                _append_ledger_entry(
                    conn, cid, "installment_charge", plan_no, debit=ledger_charge,
                    plan_id=plan_id, method="credit",
                    notes=f"عقد تقسيط ({plan_no} - {clean_title})",
                    user_id=u["id"], user_name=u["name"], created_at=now_ts,
                )

            return {
                "id": plan_id,
                "plan_no": plan_no,
                "customer_id": cid,
                "principal": principal_amt,
                "down_payment": down_amt,
                "fee_amount": fee_amt,
                "financed_total": financed_total,
                "months": count,
            }

    def installment_pay(self, plan_id, amount, method="cash", ref_no=None, item_id=None, notes=None):
        """تحصيل دفعة أو قسط (كامل أو جزئي أو متعدد الأقساط) وتسجيل القيد والإيصال."""
        u = self._perm("installments_collect")
        pid = _int(plan_id)
        amt = _money(amount)
        if amt <= 0:
            raise ApiError("مبلغ السداد يجب أن يكون أكبر من صفر")
        method = (method or "cash").strip()
        if method not in ("cash", "wallet"):
            raise ApiError("طريقة السداد غير صالحة (نقدي أو محفظة)")
        ref_no = (ref_no or "").strip() or None
        if method == "wallet" and not ref_no:
            raise ApiError("يرجى إدخال رقم العملية المرجعية لتحويل المحفظة")
        clean_notes = (notes or "").strip() or None
        target_item_id = _int(item_id) if item_id else None

        with db.connect() as conn:
            plan = conn.execute("SELECT * FROM installment_plans WHERE id=?", (pid,)).fetchone()
            if not plan:
                raise ApiError("عقد التقسيط غير موجود")
            if plan["status"] == "cancelled":
                raise ApiError("لا يمكن التحصيل على عقد تقسيط ملغى")
            if plan["status"] == "completed" or plan["remaining_total"] <= 0:
                raise ApiError("عقد التقسيط مسدد بالكامل مسبقاً")
            if amt > plan["remaining_total"]:
                raise ApiError(
                    f"المبلغ ({_fmt_money(amt)}) أكبر من المتبقي على العقد ({_fmt_money(plan['remaining_total'])})"
                )

            open_items = conn.execute(
                """SELECT * FROM installment_items
                   WHERE plan_id=? AND status IN ('pending','partial')
                   ORDER BY CASE WHEN id=? THEN 0 ELSE 1 END, seq_no ASC""",
                (pid, target_item_id or -1),
            ).fetchall()

            left = amt
            now_ts = db.now()
            first_seq = None
            settled_seqs = []
            for it in open_items:
                if left <= 0:
                    break
                rem_item = max(0, it["amount"] - it["paid_amount"])
                if rem_item <= 0:
                    continue
                apply = min(left, rem_item)
                new_paid = it["paid_amount"] + apply
                new_item_status = "paid" if new_paid >= it["amount"] else "partial"
                paid_at_val = now_ts if new_item_status == "paid" else it["paid_at"]
                conn.execute(
                    "UPDATE installment_items SET paid_amount=?, status=?, paid_at=? WHERE id=?",
                    (new_paid, new_item_status, paid_at_val, it["id"]),
                )
                if first_seq is None:
                    first_seq = it["id"]
                settled_seqs.append(f"#{it['seq_no']}")
                left -= apply

            new_plan_paid = plan["paid_total"] + amt
            new_plan_rem = max(0, plan["financed_total"] - new_plan_paid)
            new_plan_status = "completed" if new_plan_rem == 0 else "active"
            conn.execute(
                "UPDATE installment_plans SET paid_total=?, remaining_total=?, status=?, updated_at=? WHERE id=?",
                (new_plan_paid, new_plan_rem, new_plan_status, now_ts, pid),
            )

            s_shift = self._open_shift(conn, u["id"])
            shift_id = s_shift["id"] if s_shift else None
            cnt = conn.execute("SELECT COUNT(*) FROM installment_payments").fetchone()[0] + 1
            receipt_no = f"INP-{cnt:05d}"
            if conn.execute("SELECT 1 FROM installment_payments WHERE receipt_no=?", (receipt_no,)).fetchone():
                receipt_no = f"INP-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}-{cnt}"

            cur = conn.execute(
                """INSERT INTO installment_payments
                   (receipt_no, plan_id, item_id, customer_id, user_id, shift_id, created_at, amount, method, ref_no, notes)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (receipt_no, pid, first_seq, plan["customer_id"], u["id"], shift_id, now_ts, amt, method, ref_no, clean_notes),
            )
            pay_id = cur.lastrowid

            seq_desc = "، ".join(settled_seqs[:3]) + ("..." if len(settled_seqs) > 3 else "")
            ledger_note = clean_notes or f"سداد قسط {seq_desc} — {plan['plan_no']} ({'نقدي' if method == 'cash' else 'محفظة'})"
            _append_ledger_entry(
                conn,
                plan["customer_id"],
                "installment_payment",
                receipt_no,
                credit=amt,
                sale_id=plan["sale_id"],
                plan_id=pid,
                method=method,
                ref_no=ref_no,
                notes=ledger_note,
                user_id=u["id"],
                user_name=u["name"],
                created_at=now_ts,
            )

            return {
                "payment_id": pay_id,
                "receipt_no": receipt_no,
                "plan_id": pid,
                "plan_no": plan["plan_no"],
                "paid_amount": amt,
                "remaining_total": new_plan_rem,
                "status": new_plan_status,
                "settled_items": settled_seqs,
            }

    def installment_cancel(self, plan_id, reason=None):
        """إلغاء عقد تقسيط لم تُحصّل منه أقساط، مع عكس قيد الدفتر وإعادة المخزون إن وجد."""
        u = self._perm("installments_cancel")
        pid = _int(plan_id)
        reason = (reason or "").strip() or "إلغاء عقد تقسيط"
        with db.connect() as conn:
            plan = conn.execute("SELECT * FROM installment_plans WHERE id=?", (pid,)).fetchone()
            if not plan:
                raise ApiError("عقد التقسيط غير موجود")
            if plan["status"] == "cancelled":
                raise ApiError("العقد ملغى بالفعل")
            if plan["paid_total"] > 0:
                raise ApiError("لا يمكن إلغاء عقد تم تحصيل أقساط منه حفاظاً على سجل الخزينة والدفتر")

            now_ts = db.now()
            conn.execute("UPDATE installment_plans SET status='cancelled', updated_at=?, notes=? WHERE id=?", (now_ts, reason, pid))
            conn.execute("UPDATE installment_items SET status='cancelled' WHERE plan_id=?", (pid,))

            # استرجاع المخزون إذا كان عقداً مستقلاً مرتبطاً بمنتج
            if not plan["sale_id"] and plan["product_id"]:
                prod = conn.execute("SELECT id, qty FROM products WHERE id=?", (plan["product_id"],)).fetchone()
                if prod:
                    q_ret = max(1, plan["qty"] or 1)
                    if plan["serial"]:
                        conn.execute(
                            "UPDATE serials SET status='in_stock' WHERE product_id=? AND serial=? AND status='sold'",
                            (plan["product_id"], plan["serial"]),
                        )
                    conn.execute("UPDATE products SET qty=qty+? WHERE id=?", (q_ret, plan["product_id"]))
                    after_qty = conn.execute("SELECT qty FROM products WHERE id=?", (plan["product_id"],)).fetchone()[0]
                    conn.execute(
                        """INSERT INTO stock_movements(created_at, user_id, product_id, qty_change, qty_after, reason, ref)
                           VALUES(?,?,?,?,?,?,?)""",
                        (now_ts, u["id"], plan["product_id"], q_ret, after_qty, "installment_cancel", plan["plan_no"]),
                    )

            if plan["ledger_charge"] > 0:
                _append_ledger_entry(
                    conn,
                    plan["customer_id"],
                    "adjustment",
                    plan["plan_no"],
                    credit=plan["ledger_charge"],
                    sale_id=plan["sale_id"],
                    plan_id=pid,
                    notes=f"إلغاء عقد تقسيط ({plan['plan_no']}) — {reason}",
                    user_id=u["id"],
                    user_name=u["name"],
                    created_at=now_ts,
                )
            else:
                _refresh_customer_cache(conn, plan["customer_id"])
            return True

    def installment_whatsapp_reminder(self, plan_id, item_id=None, open_app=True):
        """تجهيز وفتح رسالة تذكير بموعد القسط أو كشف العقد عبر واتساب."""
        self._perm("installments_collect")
        det = self.installment_detail(plan_id)
        plan = det["plan"]
        digits = _normalize_eg_phone(plan.get("customer_phone") or "")
        if not digits:
            raise ApiError("رقم هاتف العميل غير مسجل أو غير صالح لإرسال رسالة واتساب")

        with db.connect() as conn:
            st = self._settings(conn)
        store_name = st.get("store_name") or "المتجر"
        cur = st.get("currency") or "ج.م"

        target = None
        if item_id:
            tid = _int(item_id)
            target = next((x for x in det["items"] if x["id"] == tid), None)
        if not target:
            target = next((x for x in det["items"] if x["status"] in ("pending", "partial")), None)

        lines = [
            f"مرحباً أ/ *{plan['customer_name']}*",
            f"رسالة تذكير من *{store_name}* بخصوص عقد التقسيط رقم: `{plan['plan_no']}`",
            f"البيان: {plan['title']}",
        ]
        if target:
            rem_it = max(0, target["amount"] - target["paid_amount"])
            state_lbl = "متأخر السداد" if target.get("is_overdue") else "مستحق"
            lines.append(f"القسط رقم *#{target['seq_no']}* ({state_lbl}): *{_fmt_money(rem_it)} {cur}*")
            lines.append(f"تاريخ الاستحقاق: {target['due_date']}")
        lines.append(f"إجمالي المتبقي على العقد: *{_fmt_money(plan['remaining_total'])} {cur}*")
        lines.append("نشكركم على حسن تعاونكم.")
        msg_text = "\n".join(lines)
        encoded = urllib.parse.quote(msg_text, safe="")
        wa_proto = f"whatsapp://send?phone={digits}&text={encoded}"
        wa_web = f"https://web.whatsapp.com/send?phone={digits}&text={encoded}"

        opened = False
        if open_app:
            if os.name == "nt":
                try:
                    os.startfile(wa_proto)
                    opened = True
                except OSError:
                    pass
            if not opened:
                try:
                    webbrowser.open(wa_web)
                    opened = True
                except Exception:
                    pass

        return {
            "phone": digits,
            "message": msg_text,
            "wa_url": wa_proto,
            "wa_web_url": wa_web,
            "opened": opened,
        }
