"""محرك الربط الاختياري للـ ERP (Zero-Overhead Hook Architecture) + محرك التكلفة المرجحة (WAC) والقيود المحاسبية الآلية."""
import datetime
from decimal import Decimal, ROUND_HALF_UP

import db
from api_common import ApiError, _format_doc_seq, _int


def compute_wac(old_qty: int, old_cost: int, added_qty: int, landed_unit_cost: int) -> int:
    """حساب المتوسط المرجح المتحرك للتكلفة (WAC) بالقرش مع الحماية من الكميات السالبة أو الصفرية."""
    q_old = max(0, int(old_qty or 0))
    c_old = max(0, int(old_cost or 0))
    q_new = max(0, int(added_qty or 0))
    c_new = max(0, int(landed_unit_cost or 0))
    if q_new <= 0:
        return c_old
    if q_old <= 0 or c_old <= 0:
        return c_new
    total_val = Decimal(q_old) * Decimal(c_old) + Decimal(q_new) * Decimal(c_new)
    total_qty = Decimal(q_old + q_new)
    return int((total_val / total_qty).to_integral_value(rounding=ROUND_HALF_UP))


def allocate_landed_costs(items: list[dict], invoice_discount: int = 0, shipping_cost: int = 0) -> list[dict]:
    """توزيع الخصم المكتسب ومصاريف الشحن/النقل بالتناسب على تكلفة الوحدة لكل بند (Landed Cost Allocation)."""
    subtotal = sum(max(0, int(it["qty"])) * max(0, int(it["unit_cost"])) for it in items)
    net_adj = int(shipping_cost or 0) - int(invoice_discount or 0)
    out = []
    for it in items:
        q = max(1, int(it["qty"]))
        uc = max(0, int(it["unit_cost"]))
        line_sub = q * uc
        if subtotal > 0 and net_adj != 0:
            share = (Decimal(line_sub) / Decimal(subtotal)) * Decimal(net_adj)
            unit_adj = (share / Decimal(q)).to_integral_value(rounding=ROUND_HALF_UP)
            landed = max(0, uc + int(unit_adj))
        else:
            landed = uc
        d = dict(it)
        d["landed_unit_cost"] = landed
        out.append(d)
    return out


def apply_product_wac_update(
    conn,
    product_id: int,
    added_qty: int,
    unit_cost: int,
    landed_unit_cost: int,
    source_type: str = "purchase",
    source_id: int | None = None,
    ref: str | None = None,
    user_id: int | None = None,
    new_sell_price: int | None = None,
) -> dict:
    """تحديث كمية وتكلفة الصنف (WAC) وتسجيل سجل تاريخ التكلفة داخل نفس المعاملة."""
    p = conn.execute("SELECT id, qty, cost, price FROM products WHERE id=?", (product_id,)).fetchone()
    if not p:
        raise ApiError("الصنف غير موجود لتحديث التكلفة")
    old_qty = int(p["qty"] or 0)
    old_cost = int(p["cost"] or 0)
    q_add = int(added_qty or 0)
    c_landed = int(landed_unit_cost if landed_unit_cost is not None else unit_cost)
    new_wac = compute_wac(old_qty, old_cost, q_add, c_landed)
    new_qty = old_qty + q_add
    final_price = int(new_sell_price) if (new_sell_price is not None and int(new_sell_price) > 0) else int(p["price"] or 0)
    conn.execute(
        "UPDATE products SET qty=?, cost=?, price=? WHERE id=?",
        (new_qty, new_wac, final_price, product_id),
    )
    conn.execute(
        """INSERT INTO product_cost_history
           (product_id, created_at, source_type, source_id, ref, old_qty, old_cost, added_qty, unit_cost, landed_unit_cost, new_qty, new_wac, user_id)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            product_id,
            db.now(),
            source_type,
            source_id,
            ref,
            old_qty,
            old_cost,
            q_add,
            int(unit_cost or 0),
            c_landed,
            new_qty,
            new_wac,
            user_id,
        ),
    )
    return {
        "product_id": product_id,
        "old_qty": old_qty,
        "old_cost": old_cost,
        "new_qty": new_qty,
        "new_wac": new_wac,
        "price": final_price,
        "margin_warning": new_wac >= final_price and final_price > 0,
    }


def is_module_active(api, conn, module_key: str) -> bool:
    """فحص سريع O(1) من الذاكرة المخبأة لمعرفة ما إذا كان القسم مفعلاً (صفر حمل عند التعطيل)."""
    if api is not None and hasattr(api, "_module_enabled"):
        try:
            return bool(api._module_enabled(module_key))
        except Exception:
            pass
    row = conn.execute("SELECT enabled FROM modules WHERE key=?", (module_key,)).fetchone()
    return bool(row and row["enabled"])


def get_account_by_role(conn, system_role: str, fallback_code: str | None = None):
    """جلب حساب الأستاذ المرتبط بدور نظامي أو من قواعد الترحيل المخصصة."""
    rule = conn.execute(
        """SELECT a.* FROM accounting_posting_rules r
           JOIN accounts a ON a.id = r.account_id
           WHERE r.rule_key=? AND a.active=1 AND a.is_group=0""",
        (system_role,),
    ).fetchone()
    if rule:
        return rule
    acc = conn.execute(
        "SELECT * FROM accounts WHERE system_role=? AND active=1 AND is_group=0 LIMIT 1",
        (system_role,),
    ).fetchone()
    if acc:
        return acc
    if fallback_code:
        return conn.execute(
            "SELECT * FROM accounts WHERE code=? AND active=1 AND is_group=0 LIMIT 1",
            (fallback_code,),
        ).fetchone()
    return None


def resolve_treasury_account_id(conn, method: str = "cash", treasury_id: int | None = None, from_drawer: bool = False) -> int | None:
    """تحديد حساب الأستاذ للخزينة أو البنك أو المحفظة أو درج الكاشير."""
    if treasury_id:
        tr = conn.execute(
            "SELECT account_id FROM treasury_accounts WHERE id=? AND active=1",
            (_int(treasury_id),),
        ).fetchone()
        if tr and tr["account_id"]:
            return int(tr["account_id"])
    m = (method or "cash").strip().lower()
    if m == "cash":
        role = "cash_pos" if from_drawer else "cash_main"
        acc = get_account_by_role(conn, role)
        if not acc:
            acc = get_account_by_role(conn, "cash_main", "110101")
        return int(acc["id"]) if acc else None
    if m in ("wallet",):
        acc = get_account_by_role(conn, "wallet_main", "110201")
        return int(acc["id"]) if acc else None
    if m in ("instapay", "bank", "bank_transfer"):
        acc = get_account_by_role(conn, "bank_main", "110202")
        return int(acc["id"]) if acc else None
    acc = get_account_by_role(conn, "cash_main", "110101")
    return int(acc["id"]) if acc else None


def ensure_open_period(conn, entry_date: str, strict_closed_check: bool = True) -> int:
    """التحقق من الفترة المالية للتاريخ المحدد وإنشاؤها تلقائياً إن لم تكن موجودة، ورفض الترحيل في فترة مغلقة."""
    dt_str = (entry_date or db.now()[:10]).strip()[:10]
    try:
        dt = datetime.date.fromisoformat(dt_str)
    except ValueError:
        dt = datetime.date.today()
        dt_str = dt.isoformat()

    year_str = f"{dt.year:04d}"
    period_key = f"{dt.year:04d}-{dt.month:02d}"

    fy = conn.execute("SELECT * FROM fiscal_years WHERE name=?", (year_str,)).fetchone()
    if not fy:
        cur_fy = conn.execute(
            """INSERT INTO fiscal_years(name, start_date, end_date, status, created_at)
               VALUES(?,?,?,?,?)""",
            (year_str, f"{year_str}-01-01", f"{year_str}-12-31", "open", db.now()),
        )
        fy_id = cur_fy.lastrowid
    else:
        if strict_closed_check and fy["status"] == "closed":
            raise ApiError(f"السنة المالية ({year_str}) مغلقة — لا يمكن ترحيل قيود محاسبية فيها")
        fy_id = fy["id"]

    fp = conn.execute("SELECT * FROM fiscal_periods WHERE period_key=?", (period_key,)).fetchone()
    if not fp:
        import calendar
        last_day = calendar.monthrange(dt.year, dt.month)[1]
        cur_fp = conn.execute(
            """INSERT INTO fiscal_periods(fiscal_year_id, period_key, name, start_date, end_date, status)
               VALUES(?,?,?,?,?,'open')""",
            (fy_id, period_key, f"شهر {dt.month:02d}/{dt.year}", f"{period_key}-01", f"{period_key}-{last_day:02d}"),
        )
        return cur_fp.lastrowid

    if strict_closed_check and fp["status"] == "closed":
        raise ApiError(f"الفترة المالية ({period_key}) مغلقة — لا يمكن ترحيل قيود محاسبية فيها")
    return fp["id"]


def _update_account_running_balance(conn, account_id: int, debit_delta: int, credit_delta: int) -> None:
    """تحديث الرصيد المجمّع (Materialized Balance) لحساب الأستاذ والحسابات الأب هرمياً."""
    acc = conn.execute(
        "SELECT id, parent_id, normal_balance, debit_total, credit_total FROM accounts WHERE id=?",
        (account_id,),
    ).fetchone()
    if not acc:
        return
    new_dr = int(acc["debit_total"] or 0) + int(debit_delta or 0)
    new_cr = int(acc["credit_total"] or 0) + int(credit_delta or 0)
    if acc["normal_balance"] == "debit":
        new_bal = new_dr - new_cr
    else:
        new_bal = new_cr - new_dr
    conn.execute(
        "UPDATE accounts SET debit_total=?, credit_total=?, balance=? WHERE id=?",
        (new_dr, new_cr, new_bal, account_id),
    )
    if acc["parent_id"]:
        _update_account_running_balance(conn, int(acc["parent_id"]), debit_delta, credit_delta)


def rebuild_all_account_balances(conn) -> None:
    """إعادة بناء الأرصدة المجمّعة لشجرة الحسابات بالكامل من القيود المرحّلة (مفيد بعد نقل حسابات بين المجموعات)."""
    conn.execute("UPDATE accounts SET debit_total=0, credit_total=0, balance=0")
    leaf_sums = conn.execute(
        """SELECT jl.account_id, COALESCE(SUM(jl.debit), 0) AS dr, COALESCE(SUM(jl.credit), 0) AS cr
           FROM journal_lines jl
           JOIN journal_entries je ON je.id = jl.entry_id
           WHERE je.status='posted'
           GROUP BY jl.account_id"""
    ).fetchall()
    for r in leaf_sums:
        _update_account_running_balance(conn, int(r["account_id"]), int(r["dr"] or 0), int(r["cr"] or 0))


def post_journal_entry(
    conn,
    memo: str,
    lines: list[dict],
    entry_date: str | None = None,
    kind: str = "auto",
    source_module: str | None = None,
    source_table: str | None = None,
    source_id: int | None = None,
    ref: str | None = None,
    user_id: int | None = None,
    reversal_of_entry_id: int | None = None,
    strict_closed_check: bool = True,
) -> dict:
    """إنشاء وترحيل قيد يومية مزدوج متوازن وتحديث أرصدة الحسابات ذرياً داخل نفس المعاملة."""
    clean_lines = []
    total_debit = 0
    total_credit = 0

    for raw in lines or []:
        acc_id = _int(raw.get("account_id"), 0)
        dr = max(0, int(raw.get("debit") or 0))
        cr = max(0, int(raw.get("credit") or 0))
        if dr == 0 and cr == 0:
            continue
        if dr > 0 and cr > 0:
            raise ApiError("لا يمكن أن يحتوي سطر القيد الواحد على مدين ودائن معاً")
        if not acc_id:
            raise ApiError("حساب الأستاذ مطلوب لكل سطر في القيد")
        acc = conn.execute("SELECT id, name, is_group, active FROM accounts WHERE id=?", (acc_id,)).fetchone()
        if not acc:
            raise ApiError(f"حساب الأستاذ رقم ({acc_id}) غير موجود")
        if acc["is_group"]:
            raise ApiError(f"لا يمكن الترحيل على حساب رئيسي/تجميعي («{acc['name']}») — اختر حساباً فرعياً")
        total_debit += dr
        total_credit += cr
        clean_lines.append({
            "account_id": acc_id,
            "debit": dr,
            "credit": cr,
            "cost_center_id": _int(raw.get("cost_center_id"), 0) or None,
            "party_type": raw.get("party_type") if raw.get("party_type") in ("customer", "supplier", "user") else None,
            "party_id": _int(raw.get("party_id"), 0) or None,
            "memo": (raw.get("memo") or memo or "").strip()[:240],
        })

    if len(clean_lines) < 2:
        raise ApiError("القيد المحاسبي يجب أن يتكون من طرفين على الأقل (مدين ودائن)")
    if total_debit <= 0 or total_Debit_mismatch(total_debit, total_credit):
        raise ApiError(
            f"القيد غير متوازن: إجمالي المدين ({total_debit / 100:,.2f}) لا يساوي إجمالي الدائن ({total_credit / 100:,.2f})"
        )

    dt_str = (entry_date or db.now()[:10]).strip()[:10]
    period_id = ensure_open_period(conn, dt_str, strict_closed_check=strict_closed_check)
    now_ts = db.now()

    cur = conn.execute(
        """INSERT INTO journal_entries
           (entry_no, entry_date, period_id, kind, source_module, source_table, source_id, ref, memo,
            total_debit, total_credit, status, reversal_of_entry_id, user_id, created_at, posted_at)
           VALUES('JE-TMP',?,?,?,?,?,?,?,?,?,?,'posted',?,?,?,?)""",
        (
            dt_str,
            period_id,
            kind,
            source_module,
            source_table,
            source_id,
            ref,
            (memo or "قيد يومية").strip(),
            total_debit,
            total_credit,
            reversal_of_entry_id,
            user_id,
            now_ts,
            now_ts,
        ),
    )
    entry_id = cur.lastrowid
    year_s = dt_str[:4] if len(dt_str) >= 4 else datetime.datetime.now().strftime("%Y")
    entry_no = _format_doc_seq(f"JE-{year_s}-", entry_id)
    if conn.execute("SELECT 1 FROM journal_entries WHERE entry_no=? AND id!=?", (entry_no, entry_id)).fetchone():
        entry_no = f"JE-{year_s}-{entry_id:05d}"
    conn.execute("UPDATE journal_entries SET entry_no=? WHERE id=?", (entry_no, entry_id))

    for idx, ln in enumerate(clean_lines, start=1):
        conn.execute(
            """INSERT INTO journal_lines
               (entry_id, line_no, account_id, debit, credit, cost_center_id, party_type, party_id, memo)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                entry_id,
                idx,
                ln["account_id"],
                ln["debit"],
                ln["credit"],
                ln["cost_center_id"],
                ln["party_type"],
                ln["party_id"],
                ln["memo"],
            ),
        )
        _update_account_running_balance(conn, ln["account_id"], ln["debit"], ln["credit"])

    return {
        "entry_id": entry_id,
        "entry_no": entry_no,
        "total_debit": total_debit,
        "total_credit": total_credit,
    }


def total_Debit_mismatch(dr: int, cr: int) -> bool:
    return int(dr) != int(cr)


def reverse_journal_entry(conn, entry_id: int, reason: str = "", user_id: int | None = None) -> dict:
    """عكس قيد يومية مرحّل بإنشاء قيد عكسي متوازن وتوثيق الربط دون حذف السجل التاريخي."""
    je = conn.execute("SELECT * FROM journal_entries WHERE id=?", (_int(entry_id),)).fetchone()
    if not je:
        raise ApiError("القيد المحاسبي غير موجود")
    if je["status"] == "reversed" or je["reversed_by_entry_id"]:
        raise ApiError("تم عكس هذا القيد مسبقاً")
    if je["status"] != "posted":
        raise ApiError("لا يمكن عكس قيد غير مرحّل")

    orig_lines = conn.execute(
        "SELECT * FROM journal_lines WHERE entry_id=? ORDER BY line_no ASC",
        (je["id"],),
    ).fetchall()
    rev_lines = []
    for ln in orig_lines:
        rev_lines.append({
            "account_id": ln["account_id"],
            "debit": ln["credit"],
            "credit": ln["debit"],
            "cost_center_id": ln["cost_center_id"],
            "party_type": ln["party_type"],
            "party_id": ln["party_id"],
            "memo": f"عكس قيد {je['entry_no']} — {ln['memo'] or ''}".strip(" —"),
        })

    memo_txt = f"قيد عكسي للقيد ({je['entry_no']})"
    if reason and reason.strip():
        memo_txt += f" — السبب: {reason.strip()}"

    rev_res = post_journal_entry(
        conn,
        memo=memo_txt,
        lines=rev_lines,
        entry_date=db.now()[:10],
        kind="reversal",
        source_module=je["source_module"],
        source_table=je["source_table"],
        source_id=je["source_id"],
        ref=je["entry_no"],
        user_id=user_id,
        reversal_of_entry_id=je["id"],
    )
    conn.execute(
        "UPDATE journal_entries SET status='reversed', reversed_by_entry_id=? WHERE id=?",
        (rev_res["entry_id"], je["id"]),
    )
    return rev_res


# ==============================================================================
#  نقاط الربط التلقائية للعمليات التشغيلية (Optional Event Hooks)
# ==============================================================================

def _merge_lines_by_account(lines: list[dict]) -> list[dict]:
    """تجميع السطور المتشابهة في الحساب والطرف والنوع لتفادي تكرار الحساب في نفس الطرف."""
    grouped = {}
    order = []
    for ln in lines:
        dr = max(0, int(ln.get("debit") or 0))
        cr = max(0, int(ln.get("credit") or 0))
        if dr == 0 and cr == 0:
            continue
        side = "dr" if dr > 0 else "cr"
        key = (int(ln["account_id"]), side, ln.get("party_type"), ln.get("party_id"), ln.get("cost_center_id"))
        if key not in grouped:
            grouped[key] = dict(ln)
            grouped[key]["debit"] = dr
            grouped[key]["credit"] = cr
            order.append(key)
        else:
            grouped[key]["debit"] += dr
            grouped[key]["credit"] += cr
    return [grouped[k] for k in order if grouped[k]["debit"] > 0 or grouped[k]["credit"] > 0]


def on_sale_created(api, conn, sale_id: int, user: dict | None = None) -> dict | None:
    """توليد قيد فاتورة المبيعات بالمبلغ الفعلي للفاتورة تماماً + قيد ثانٍ مستقل لتكلفة البضاعة المباعة (COGS)."""
    if not is_module_active(api, conn, "accounting"):
        return None
    s = conn.execute("SELECT * FROM sales WHERE id=?", (sale_id,)).fetchone()
    if not s or int(s["total"] or 0) <= 0:
        return None

    acc_rev = get_account_by_role(conn, "sales_revenue", "4101")
    acc_vat = get_account_by_role(conn, "vat_output", "2102")
    acc_ar = get_account_by_role(conn, "ar_customers", "1103")
    acc_cogs = get_account_by_role(conn, "cogs", "5101")
    acc_inv = get_account_by_role(conn, "inventory", "1105")
    if not (acc_rev and acc_ar):
        return None

    pays = conn.execute("SELECT * FROM payments WHERE sale_id=?", (sale_id,)).fetchall()
    sale_lines = []
    for p in pays:
        amt = int(p["amount"] or 0)
        if amt <= 0:
            continue
        if p["method"] == "credit":
            sale_lines.append({
                "account_id": acc_ar["id"],
                "debit": amt,
                "credit": 0,
                "party_type": "customer" if s["customer_id"] else None,
                "party_id": s["customer_id"],
                "memo": f"آجل فاتورة مبيعات {s['invoice_no']}",
            })
        else:
            from_drawer = bool(s["shift_id"]) and p["method"] == "cash"
            tr_acc_id = resolve_treasury_account_id(conn, p["method"], from_drawer=from_drawer)
            if tr_acc_id:
                sale_lines.append({
                    "account_id": tr_acc_id,
                    "debit": amt,
                    "credit": 0,
                    "memo": f"تحصيل فاتورة مبيعات {s['invoice_no']} ({p['method']})",
                })

    subtotal = int(s["subtotal"] or 0)
    disc = int(s["discount"] or 0)
    tax = int(s["tax"] or 0)
    net_rev_credit = max(0, subtotal - disc)

    if net_rev_credit > 0:
        sale_lines.append({
            "account_id": acc_rev["id"],
            "debit": 0,
            "credit": net_rev_credit,
            "memo": f"صافي إيراد مبيعات فاتورة {s['invoice_no']}" + (f" (بعد خصم {disc/100:,.2f})" if disc > 0 else ""),
        })
    if tax > 0 and acc_vat:
        sale_lines.append({
            "account_id": acc_vat["id"],
            "debit": 0,
            "credit": tax,
            "memo": f"ضريبة مخرجات فاتورة {s['invoice_no']}",
        })

    merged_sale = _merge_lines_by_account(sale_lines)
    dr_sum = sum(x["debit"] for x in merged_sale)
    cr_sum = sum(x["credit"] for x in merged_sale)
    if dr_sum != cr_sum or dr_sum <= 0:
        return None

    uid = user["id"] if user else s["user_id"]
    entry_dt = s["invoice_date"] if ("invoice_date" in s.keys() and s["invoice_date"]) else s["created_at"][:10]
    src_mod = "pos" if (s["doc_type"] if "doc_type" in s.keys() else "pos") != "b2b" else "sales_quotes"

    # 1) قيد المبيعات الأساسي (مبلغ القيد يطابق إجمالي الفاتورة الفعلي s['total'] بنسبة 100%)
    sale_je = post_journal_entry(
        conn,
        memo=f"فاتورة مبيعات ({s['invoice_no']})",
        lines=merged_sale,
        entry_date=entry_dt,
        kind="auto",
        source_module=src_mod,
        source_table="sales",
        source_id=sale_id,
        ref=s["invoice_no"],
        user_id=uid,
        strict_closed_check=False,
    )

    # 2) قيد ثانٍ مستقل للجرد المستمر وتكلفة البضاعة المباعة (COGS -> المخزون)
    cost_row = conn.execute(
        """SELECT COALESCE(SUM(si.qty * COALESCE(NULLIF(si.cost_unit, 0), p.cost, 0)), 0) AS total_cost
           FROM sale_items si
           LEFT JOIN products p ON p.id = si.product_id
           WHERE si.sale_id=?""",
        (sale_id,),
    ).fetchone()
    total_cost = int(cost_row["total_cost"] or 0) if cost_row else 0
    if total_cost > 0 and acc_cogs and acc_inv:
        post_journal_entry(
            conn,
            memo=f"تكلفة بضاعة مباعة — فاتورة ({s['invoice_no']})",
            lines=[
                {
                    "account_id": acc_cogs["id"],
                    "debit": total_cost,
                    "credit": 0,
                    "memo": f"تكلفة بضاعة مباعة للفاتورة {s['invoice_no']}",
                },
                {
                    "account_id": acc_inv["id"],
                    "debit": 0,
                    "credit": total_cost,
                    "memo": f"صرف مخزون للفاتورة {s['invoice_no']}",
                },
            ],
            entry_date=entry_dt,
            kind="auto",
            source_module=src_mod,
            source_table="sales_cogs",
            source_id=sale_id,
            ref=s["invoice_no"],
            user_id=uid,
            strict_closed_check=False,
        )

    return sale_je


def on_sale_returned(
    api,
    conn,
    sale_id: int,
    return_id: int,
    returned_amount: int,
    returned_cost: int,
    credit_delta: int,
    user: dict | None = None,
) -> dict | None:
    """توليد قيد مرتجع المبيعات بقيمة المرتجع الفعلية + قيد مستقل لإعادة تكلفة البضاعة للمخزون."""
    if not is_module_active(api, conn, "accounting"):
        return None
    ret_amt = int(returned_amount or 0)
    if ret_amt <= 0:
        return None
    s = conn.execute("SELECT * FROM sales WHERE id=?", (sale_id,)).fetchone()
    if not s:
        return None

    acc_sret = get_account_by_role(conn, "sales_returns", "4102")
    acc_ar = get_account_by_role(conn, "ar_customers", "1103")
    acc_cogs = get_account_by_role(conn, "cogs", "5101")
    acc_inv = get_account_by_role(conn, "inventory", "1105")
    if not (acc_sret and acc_ar):
        return None

    cr_part = max(0, min(ret_amt, int(credit_delta or 0)))
    cash_part = max(0, ret_amt - cr_part)

    lines = [
        {
            "account_id": acc_sret["id"],
            "debit": ret_amt,
            "credit": 0,
            "memo": f"مردودات مبيعات فاتورة {s['invoice_no']}",
        }
    ]
    if cr_part > 0:
        lines.append({
            "account_id": acc_ar["id"],
            "debit": 0,
            "credit": cr_part,
            "party_type": "customer" if s["customer_id"] else None,
            "party_id": s["customer_id"],
            "memo": f"تخفيض مديونية العميل بمرتجع {s['invoice_no']}",
        })
    if cash_part > 0:
        tr_acc_id = resolve_treasury_account_id(conn, "cash", from_drawer=bool(s["shift_id"]))
        if tr_acc_id:
            lines.append({
                "account_id": tr_acc_id,
                "debit": 0,
                "credit": cash_part,
                "memo": f"رد نقدية مرتجع مبيعات {s['invoice_no']}",
            })

    merged = _merge_lines_by_account(lines)
    if sum(x["debit"] for x in merged) != sum(x["credit"] for x in merged):
        return None

    uid = user["id"] if user else s["user_id"]
    ret_je = post_journal_entry(
        conn,
        memo=f"مرتجع مبيعات ({s['invoice_no']})",
        lines=merged,
        entry_date=db.now()[:10],
        kind="auto",
        source_module="history",
        source_table="sale_returns",
        source_id=return_id,
        ref=s["invoice_no"],
        user_id=uid,
        strict_closed_check=False,
    )

    ret_cost = max(0, int(returned_cost or 0))
    if ret_cost > 0 and acc_inv and acc_cogs:
        post_journal_entry(
            conn,
            memo=f"عكس تكلفة بضاعة مرتجعة — فاتورة ({s['invoice_no']})",
            lines=[
                {
                    "account_id": acc_inv["id"],
                    "debit": ret_cost,
                    "credit": 0,
                    "memo": f"إرجاع بضاعة للمخزون من فاتورة {s['invoice_no']}",
                },
                {
                    "account_id": acc_cogs["id"],
                    "debit": 0,
                    "credit": ret_cost,
                    "memo": f"تخفيض تكلفة البضاعة المباعة بمرتجع {s['invoice_no']}",
                },
            ],
            entry_date=db.now()[:10],
            kind="auto",
            source_module="history",
            source_table="sale_returns_cogs",
            source_id=return_id,
            ref=s["invoice_no"],
            user_id=uid,
            strict_closed_check=False,
        )

    return ret_je


def on_customer_payment(api, conn, voucher_id: int, customer_id: int, amount: int, method: str, ref: str, shift_id: int | None = None, user: dict | None = None) -> dict | None:
    """توليد قيد سند قبض من عميل (من ح/ الخزنة أو المحفظة إلى ح/ ذمم العملاء)."""
    if not is_module_active(api, conn, "accounting"):
        return None
    amt = int(amount or 0)
    if amt <= 0:
        return None
    acc_ar = get_account_by_role(conn, "ar_customers", "1103")
    tr_acc_id = resolve_treasury_account_id(conn, method, from_drawer=bool(shift_id and method == "cash"))
    if not (acc_ar and tr_acc_id):
        return None
    lines = [
        {"account_id": tr_acc_id, "debit": amt, "credit": 0, "memo": f"تحصيل سند قبض {ref}"},
        {"account_id": acc_ar["id"], "debit": 0, "credit": amt, "party_type": "customer", "party_id": customer_id, "memo": f"سداد عميل بسند {ref}"},
    ]
    return post_journal_entry(
        conn,
        memo=f"سند قبض عميل ({ref})",
        lines=lines,
        entry_date=db.now()[:10],
        kind="auto",
        source_module="customers",
        source_table="customer_payments",
        source_id=voucher_id,
        ref=ref,
        user_id=user["id"] if user else None,
        strict_closed_check=False,
    )


def on_customer_payment_deleted(api, conn, voucher_row, user: dict | None = None) -> dict | None:
    """عكس القيد المحاسبي لسند قبض ملغى إن وجد."""
    if not is_module_active(api, conn, "accounting"):
        return None
    je = conn.execute(
        "SELECT id FROM journal_entries WHERE source_table='customer_payments' AND source_id=? AND status='posted' ORDER BY id DESC LIMIT 1",
        (voucher_row["id"],),
    ).fetchone()
    if je:
        return reverse_journal_entry(conn, je["id"], reason=f"إلغاء سند قبض {voucher_row['ref']}", user_id=user["id"] if user else None)
    return None


def on_installment_created(api, conn, plan_id: int, user: dict | None = None) -> dict | None:
    """توليد قيد عقد تقسيط جديد + قيد مستقل لتكلفة البضاعة المباعة إن كان عقداً مستقلاً."""
    if not is_module_active(api, conn, "accounting"):
        return None
    plan = conn.execute("SELECT * FROM installment_plans WHERE id=?", (plan_id,)).fetchone()
    if not plan:
        return None
    acc_inst_ar = get_account_by_role(conn, "ar_installments", "1104")
    acc_cust_ar = get_account_by_role(conn, "ar_customers", "1103")
    acc_rev = get_account_by_role(conn, "sales_revenue", "4101")
    acc_fee = get_account_by_role(conn, "installment_fee_rev", "4202")
    acc_cogs = get_account_by_role(conn, "cogs", "5101")
    acc_inv = get_account_by_role(conn, "inventory", "1105")
    if not (acc_inst_ar and acc_rev and acc_fee):
        return None

    lines = []
    down = int(plan["down_payment"] or 0)
    principal = int(plan["principal"] or 0)
    fee = int(plan["fee_amount"] or 0)
    financed = int(plan["financed_total"] or 0)
    cid = plan["customer_id"]
    uid = user["id"] if user else plan["user_id"]

    if plan["sale_id"]:
        base_financed = max(0, principal - down)
        lines.append({
            "account_id": acc_inst_ar["id"],
            "debit": financed,
            "credit": 0,
            "party_type": "customer",
            "party_id": cid,
            "memo": f"إثبات عقد تقسيط {plan['plan_no']}",
        })
        if base_financed > 0 and acc_cust_ar:
            lines.append({
                "account_id": acc_cust_ar["id"],
                "debit": 0,
                "credit": base_financed,
                "party_type": "customer",
                "party_id": cid,
                "memo": f"تحويل ذمة فاتورة آجلة إلى أقساط {plan['plan_no']}",
            })
        if fee > 0:
            lines.append({
                "account_id": acc_fee["id"],
                "debit": 0,
                "credit": fee,
                "memo": f"عوائد ورسوم تمويل أقساط {plan['plan_no']}",
            })
    else:
        if down > 0:
            tr_id = resolve_treasury_account_id(conn, plan["down_method"], from_drawer=bool(plan["shift_id"] and plan["down_method"] == "cash"))
            if tr_id:
                lines.append({
                    "account_id": tr_id,
                    "debit": down,
                    "credit": 0,
                    "memo": f"مقدم عقد تقسيط {plan['plan_no']}",
                })
        lines.append({
            "account_id": acc_inst_ar["id"],
            "debit": financed,
            "credit": 0,
            "party_type": "customer",
            "party_id": cid,
            "memo": f"مديونية عقد تقسيط {plan['plan_no']}",
        })
        lines.append({
            "account_id": acc_rev["id"],
            "debit": 0,
            "credit": principal,
            "memo": f"مبيعات بالتقسيط {plan['plan_no']}",
        })
        if fee > 0:
            lines.append({
                "account_id": acc_fee["id"],
                "debit": 0,
                "credit": fee,
                "memo": f"رسوم تمويل أقساط {plan['plan_no']}",
            })

    merged = _merge_lines_by_account(lines)
    if len(merged) < 2 or sum(x["debit"] for x in merged) != sum(x["credit"] for x in merged):
        return None

    plan_je = post_journal_entry(
        conn,
        memo=f"عقد تقسيط ({plan['plan_no']} — {plan['title']})",
        lines=merged,
        entry_date=plan["created_at"][:10],
        kind="auto",
        source_module="installments",
        source_table="installment_plans",
        source_id=plan_id,
        ref=plan["plan_no"],
        user_id=uid,
        strict_closed_check=False,
    )

    if not plan["sale_id"] and plan["product_id"] and acc_cogs and acc_inv:
        p = conn.execute("SELECT cost FROM products WHERE id=?", (plan["product_id"],)).fetchone()
        item_cost = (int(p["cost"] or 0) * max(1, int(plan["qty"] or 1))) if p else 0
        if item_cost > 0:
            post_journal_entry(
                conn,
                memo=f"تكلفة بضاعة مباعة بالتقسيط — عقد ({plan['plan_no']})",
                lines=[
                    {"account_id": acc_cogs["id"], "debit": item_cost, "credit": 0, "memo": f"تكلفة بضاعة تقسيط {plan['plan_no']}"},
                    {"account_id": acc_inv["id"], "debit": 0, "credit": item_cost, "memo": f"صرف مخزون تقسيط {plan['plan_no']}"},
                ],
                entry_date=plan["created_at"][:10],
                kind="auto",
                source_module="installments",
                source_table="installment_plans_cogs",
                source_id=plan_id,
                ref=plan["plan_no"],
                user_id=uid,
                strict_closed_check=False,
            )

    return plan_je


def on_installment_paid(api, conn, payment_id: int, plan_id: int, customer_id: int, amount: int, method: str, receipt_no: str, shift_id: int | None = None, user: dict | None = None) -> dict | None:
    """توليد قيد تحصيل قسط (من ح/ الخزنة أو المحفظة إلى ح/ ذمم عملاء الأقساط)."""
    if not is_module_active(api, conn, "accounting"):
        return None
    amt = int(amount or 0)
    if amt <= 0:
        return None
    acc_inst_ar = get_account_by_role(conn, "ar_installments", "1104")
    tr_id = resolve_treasury_account_id(conn, method, from_drawer=bool(shift_id and method == "cash"))
    if not (acc_inst_ar and tr_id):
        return None
    lines = [
        {"account_id": tr_id, "debit": amt, "credit": 0, "memo": f"تحصيل قسط بإيصال {receipt_no}"},
        {"account_id": acc_inst_ar["id"], "debit": 0, "credit": amt, "party_type": "customer", "party_id": customer_id, "memo": f"سداد قسط بإيصال {receipt_no}"},
    ]
    return post_journal_entry(
        conn,
        memo=f"تحصيل قسط ({receipt_no})",
        lines=lines,
        entry_date=db.now()[:10],
        kind="auto",
        source_module="installments",
        source_table="installment_payments",
        source_id=payment_id,
        ref=receipt_no,
        user_id=user["id"] if user else None,
        strict_closed_check=False,
    )


def on_installment_cancelled(api, conn, plan_row, user: dict | None = None) -> dict | None:
    """عكس قيد عقد التقسيط الملغى وقيد تكلفته إن وجد."""
    if not is_module_active(api, conn, "accounting"):
        return None
    uid = user["id"] if user else None
    out = None
    for tbl in ("installment_plans", "installment_plans_cogs"):
        je = conn.execute(
            "SELECT id FROM journal_entries WHERE source_table=? AND source_id=? AND status='posted' ORDER BY id DESC LIMIT 1",
            (tbl, plan_row["id"]),
        ).fetchone()
        if je:
            res = reverse_journal_entry(conn, je["id"], reason=f"إلغاء عقد تقسيط {plan_row['plan_no']}", user_id=uid)
            if tbl == "installment_plans":
                out = res
    return out


def on_purchase_posted(api, conn, purchase_id: int, user: dict | None = None) -> dict | None:
    """توليد قيد فاتورة المشتريات المعتمدة (المخزون + ض.ق.م مدخلات ← الموردين + الخزنة + خصم المنبع)."""
    if not is_module_active(api, conn, "accounting"):
        return None
    pur = conn.execute("SELECT * FROM purchases WHERE id=?", (purchase_id,)).fetchone()
    if not pur or pur["status"] != "posted":
        return None

    acc_inv = get_account_by_role(conn, "inventory", "1105")
    acc_vat_in = get_account_by_role(conn, "vat_input", "1107")
    acc_ap = get_account_by_role(conn, "ap_suppliers", "2101")
    acc_wht = get_account_by_role(conn, "wht_payable", "2103")
    if not (acc_inv and acc_ap):
        return None

    subtotal = int(pur["subtotal"] or 0)
    discount = int(pur["discount"] or 0)
    shipping = int(pur["shipping_cost"] or 0)
    tax = int(pur["tax"] or 0)
    wht = int(pur["wht_amount"] or 0)
    total = int(pur["total"] or 0)
    paid = int(pur["paid_amount"] or 0)
    sup_id = pur["supplier_id"]

    inv_debit = max(0, subtotal - discount + shipping)
    if inv_debit <= 0 and total <= 0:
        return None

    lines = [
        {
            "account_id": acc_inv["id"],
            "debit": inv_debit,
            "credit": 0,
            "memo": f"إدخال مخزون فاتورة مشتريات {pur['purchase_no']}",
        }
    ]
    if tax > 0 and acc_vat_in:
        lines.append({
            "account_id": acc_vat_in["id"],
            "debit": tax,
            "credit": 0,
            "memo": f"ضريبة مدخلات فاتورة مشتريات {pur['purchase_no']}",
        })
    if wht > 0 and acc_wht:
        lines.append({
            "account_id": acc_wht["id"],
            "debit": 0,
            "credit": wht,
            "memo": f"ضريبة خصم وإضافة (خصم منبع) فاتورة {pur['purchase_no']}",
        })

    rem_ap = max(0, total - paid)
    if rem_ap > 0:
        lines.append({
            "account_id": acc_ap["id"],
            "debit": 0,
            "credit": rem_ap,
            "party_type": "supplier",
            "party_id": sup_id,
            "memo": f"استحقاق مورد فاتورة مشتريات {pur['purchase_no']}",
        })
    if paid > 0:
        tr_id = resolve_treasury_account_id(
            conn,
            pur["payment_method"],
            treasury_id=pur["treasury_id"],
            from_drawer=bool(pur["shift_id"] and pur["payment_method"] == "cash" and not pur["treasury_id"]),
        )
        if tr_id:
            lines.append({
                "account_id": tr_id,
                "debit": 0,
                "credit": paid,
                "memo": f"سداد فوري لفاتورة مشتريات {pur['purchase_no']}",
            })

    merged = _merge_lines_by_account(lines)
    if sum(x["debit"] for x in merged) != sum(x["credit"] for x in merged):
        return None

    return post_journal_entry(
        conn,
        memo=f"فاتورة مشتريات ({pur['purchase_no']})",
        lines=merged,
        entry_date=pur["invoice_date"] or pur["created_at"][:10],
        kind="auto",
        source_module="purchases",
        source_table="purchases",
        source_id=purchase_id,
        ref=pur["purchase_no"],
        user_id=user["id"] if user else pur["user_id"],
        strict_closed_check=True,
    )


def on_purchase_returned(api, conn, return_id: int, purchase_id: int, user: dict | None = None) -> dict | None:
    """توليد قيد مرتجع مشتريات لمورد."""
    if not is_module_active(api, conn, "accounting"):
        return None
    pr = conn.execute("SELECT * FROM purchase_returns WHERE id=?", (return_id,)).fetchone()
    if not pr or int(pr["total"] or 0) <= 0:
        return None

    acc_inv = get_account_by_role(conn, "inventory", "1105")
    acc_vat_in = get_account_by_role(conn, "vat_input", "1107")
    acc_ap = get_account_by_role(conn, "ap_suppliers", "2101")
    acc_wht = get_account_by_role(conn, "wht_payable", "2103")
    if not (acc_inv and acc_ap):
        return None

    sub = int(pr["subtotal"] or 0)
    tax = int(pr["tax_amount"] or 0)
    wht = int(pr["wht_amount"] or 0)
    tot = int(pr["total"] or 0)
    sup_id = pr["supplier_id"]

    lines = []
    if pr["refund_method"] == "credit":
        lines.append({
            "account_id": acc_ap["id"],
            "debit": tot,
            "credit": 0,
            "party_type": "supplier",
            "party_id": sup_id,
            "memo": f"تخفيض حساب المورد بمرتجع مشتريات {pr['return_no']}",
        })
    else:
        tr_id = resolve_treasury_account_id(
            conn,
            pr["refund_method"],
            treasury_id=pr["treasury_id"],
            from_drawer=bool(pr["shift_id"]),
        )
        if tr_id:
            lines.append({
                "account_id": tr_id,
                "debit": tot,
                "credit": 0,
                "memo": f"استرداد نقدي لمرتجع مشتريات {pr['return_no']}",
            })
    if wht > 0 and acc_wht:
        lines.append({
            "account_id": acc_wht["id"],
            "debit": wht,
            "credit": 0,
            "memo": f"عكس خصم منبع لمرتجع {pr['return_no']}",
        })
    lines.append({
        "account_id": acc_inv["id"],
        "debit": 0,
        "credit": sub,
        "memo": f"إخراج بضاعة مرتجعة للمورد {pr['return_no']}",
    })
    if tax > 0 and acc_vat_in:
        lines.append({
            "account_id": acc_vat_in["id"],
            "debit": 0,
            "credit": tax,
            "memo": f"عكس ضريبة مدخلات مرتجع {pr['return_no']}",
        })

    merged = _merge_lines_by_account(lines)
    if sum(x["debit"] for x in merged) != sum(x["credit"] for x in merged):
        return None

    return post_journal_entry(
        conn,
        memo=f"مرتجع مشتريات ({pr['return_no']})",
        lines=merged,
        entry_date=pr["created_at"][:10],
        kind="auto",
        source_module="purchases",
        source_table="purchase_returns",
        source_id=return_id,
        ref=pr["return_no"],
        user_id=user["id"] if user else pr["user_id"],
        strict_closed_check=True,
    )


def on_supplier_payment(
    api,
    conn,
    payment_id: int,
    supplier_id: int,
    amount: int,
    method: str,
    ref: str,
    treasury_id: int | None = None,
    from_drawer: bool = False,
    user: dict | None = None,
) -> dict | None:
    """توليد قيد سند صرف لمورد (من ح/ ذمم الموردين إلى ح/ الخزنة أو البنك)."""
    if not is_module_active(api, conn, "accounting"):
        return None
    amt = int(amount or 0)
    if amt <= 0:
        return None
    acc_ap = get_account_by_role(conn, "ap_suppliers", "2101")
    tr_acc_id = resolve_treasury_account_id(conn, method, treasury_id=treasury_id, from_drawer=from_drawer)
    if not (acc_ap and tr_acc_id):
        return None
    lines = [
        {"account_id": acc_ap["id"], "debit": amt, "credit": 0, "party_type": "supplier", "party_id": supplier_id, "memo": f"سداد مورد بسند صرف {ref}"},
        {"account_id": tr_acc_id, "debit": 0, "credit": amt, "memo": f"صرف دفعة لمورد بسند {ref}"},
    ]
    return post_journal_entry(
        conn,
        memo=f"سند صرف لمورد ({ref})",
        lines=lines,
        entry_date=db.now()[:10],
        kind="auto",
        source_module="purchases",
        source_table="supplier_payments",
        source_id=payment_id,
        ref=ref,
        user_id=user["id"] if user else None,
        strict_closed_check=True,
    )


def on_repair_delivered(api, conn, repair_id: int, user: dict | None = None) -> dict | None:
    """توليد قيد إيراد تسليم جهاز صيانة + قيد مستقل لتكلفة قطع الغيار المركبة."""
    if not is_module_active(api, conn, "accounting"):
        return None
    r = conn.execute("SELECT * FROM repairs WHERE id=?", (repair_id,)).fetchone()
    if not r or r["status"] != "delivered":
        return None

    rev = int(r["cost"] or 0)
    parts_cost_row = conn.execute(
        """SELECT COALESCE(SUM(rp.qty * COALESCE(NULLIF(rp.cost_unit, 0), p.cost, rp.unit_price, 0)), 0) AS c
           FROM repair_parts rp
           LEFT JOIN products p ON p.id = rp.product_id
           WHERE rp.repair_id=?""",
        (repair_id,),
    ).fetchone()
    parts_cost = int(parts_cost_row["c"] or 0) if parts_cost_row else 0
    if rev <= 0 and parts_cost <= 0:
        return None

    acc_rep_rev = get_account_by_role(conn, "repair_revenue", "4201")
    acc_rep_cogs = get_account_by_role(conn, "repair_parts_cogs", "5102")
    acc_inv = get_account_by_role(conn, "inventory", "1105")
    tr_id = resolve_treasury_account_id(conn, "cash", from_drawer=False)
    uid = user["id"] if user else r["user_id"]
    out_je = None

    if rev > 0 and tr_id and acc_rep_rev:
        out_je = post_journal_entry(
            conn,
            memo=f"تسليم جهاز صيانة ({r['ref']} — {r['device_type']})",
            lines=[
                {"account_id": tr_id, "debit": rev, "credit": 0, "memo": f"تحصيل تذكرة صيانة {r['ref']}"},
                {"account_id": acc_rep_rev["id"], "debit": 0, "credit": rev, "memo": f"إيراد صيانة تذكرة {r['ref']}"},
            ],
            entry_date=db.now()[:10],
            kind="auto",
            source_module="repair",
            source_table="repairs",
            source_id=repair_id,
            ref=r["ref"],
            user_id=uid,
            strict_closed_check=False,
        )

    if parts_cost > 0 and acc_rep_cogs and acc_inv:
        cogs_je = post_journal_entry(
            conn,
            memo=f"تكلفة قطع غيار صيانة ({r['ref']})",
            lines=[
                {"account_id": acc_rep_cogs["id"], "debit": parts_cost, "credit": 0, "memo": f"تكلفة قطع غيار صيانة {r['ref']}"},
                {"account_id": acc_inv["id"], "debit": 0, "credit": parts_cost, "memo": f"صرف قطع غيار صيانة {r['ref']}"},
            ],
            entry_date=db.now()[:10],
            kind="auto",
            source_module="repair",
            source_table="repairs_cogs" if out_je else "repairs",
            source_id=repair_id,
            ref=r["ref"],
            user_id=uid,
            strict_closed_check=False,
        )
        if not out_je:
            out_je = cogs_je

    return out_je


def on_used_purchased(api, conn, used_id: int, buy_price: int, ref: str, user: dict | None = None) -> dict | None:
    """توليد قيد شراء جهاز مستعمل (من ح/ مخزون الأجهزة المستعملة إلى ح/ الخزنة)."""
    if not is_module_active(api, conn, "accounting"):
        return None
    amt = int(buy_price or 0)
    if amt <= 0:
        return None
    acc_used = get_account_by_role(conn, "used_inventory", "1106")
    tr_id = resolve_treasury_account_id(conn, "cash", from_drawer=False)
    if not (acc_used and tr_id):
        return None
    lines = [
        {"account_id": acc_used["id"], "debit": amt, "credit": 0, "memo": f"شراء جهاز مستعمل {ref}"},
        {"account_id": tr_id, "debit": 0, "credit": amt, "memo": f"سداد ثمن جهاز مستعمل {ref}"},
    ]
    return post_journal_entry(
        conn,
        memo=f"شراء جهاز مستعمل ({ref})",
        lines=lines,
        entry_date=db.now()[:10],
        kind="auto",
        source_module="buy_used",
        source_table="used_device_purchases",
        source_id=used_id,
        ref=ref,
        user_id=user["id"] if user else None,
        strict_closed_check=False,
    )


def on_stock_adjusted(api, conn, product_id: int, qty_change: int, unit_cost: int, reason: str, user: dict | None = None) -> dict | None:
    """توليد قيد تسوية جردية للمخزون عند الزيادة أو العجز."""
    if not is_module_active(api, conn, "accounting"):
        return None
    delta = int(qty_change or 0)
    cost = max(0, int(unit_cost or 0))
    val = abs(delta) * cost
    if delta == 0 or val <= 0:
        return None
    acc_inv = get_account_by_role(conn, "inventory", "1105")
    acc_diff = get_account_by_role(conn, "stock_adj_diff", "5103")
    if not (acc_inv and acc_diff):
        return None
    if delta > 0:
        lines = [
            {"account_id": acc_inv["id"], "debit": val, "credit": 0, "memo": f"زيادة جرد مخزون ({reason})"},
            {"account_id": acc_diff["id"], "debit": 0, "credit": val, "memo": f"فروق جرد مخزون موجبة ({reason})"},
        ]
    else:
        lines = [
            {"account_id": acc_diff["id"], "debit": val, "credit": 0, "memo": f"عجز جرد مخزون ({reason})"},
            {"account_id": acc_inv["id"], "debit": 0, "credit": val, "memo": f"تخفيض مخزون بتسوية جرد ({reason})"},
        ]
    return post_journal_entry(
        conn,
        memo=f"تسوية جرد مخزون — {reason}",
        lines=lines,
        entry_date=db.now()[:10],
        kind="auto",
        source_module="inventory",
        source_table="stock_movements",
        source_id=product_id,
        ref=f"ADJ-{product_id}",
        user_id=user["id"] if user else None,
        strict_closed_check=False,
    )


def on_shift_closed(api, conn, shift_id: int, diff: int, user: dict | None = None) -> dict | None:
    """توليد قيد فروق عجز أو زيادة صندوق الكاشير عند إغلاق الوردية."""
    if not is_module_active(api, conn, "accounting"):
        return None
    d = int(diff or 0)
    if d == 0:
        return None
    acc_pos = get_account_by_role(conn, "cash_pos", "110102")
    acc_diff = get_account_by_role(conn, "cash_diff", "5204")
    if not (acc_pos and acc_diff):
        return None
    val = abs(d)
    if d < 0:
        lines = [
            {"account_id": acc_diff["id"], "debit": val, "credit": 0, "party_type": "user", "party_id": user["id"] if user else None, "memo": f"عجز صندوق وردية #{shift_id}"},
            {"account_id": acc_pos["id"], "debit": 0, "credit": val, "memo": f"تسوية عجز درج الكاشير وردية #{shift_id}"},
        ]
    else:
        lines = [
            {"account_id": acc_pos["id"], "debit": val, "credit": 0, "memo": f"زيادة درج الكاشير وردية #{shift_id}"},
            {"account_id": acc_diff["id"], "debit": 0, "credit": val, "party_type": "user", "party_id": user["id"] if user else None, "memo": f"زيادة صندوق وردية #{shift_id}"},
        ]
    return post_journal_entry(
        conn,
        memo=f"تسوية فروق وردية كاشير (#{shift_id})",
        lines=lines,
        entry_date=db.now()[:10],
        kind="auto",
        source_module="pos",
        source_table="shifts",
        source_id=shift_id,
        ref=f"SHF-{shift_id}",
        user_id=user["id"] if user else None,
        strict_closed_check=False,
    )
