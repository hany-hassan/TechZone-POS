"""وحدة المحاسبة العامة والمالية (القيد المزدوج)، شجرة الحسابات، الخزائن، المصروفات، الفترات المالية، والقوائم المالية."""
import datetime
import sqlite3

import db
import erp_hooks
from api_common import ApiError, _fmt_money, _format_doc_seq, _int, _money


def _update_subtree_levels_and_type(conn, parent_id: int, parent_level: int, parent_type: str, parent_norm: str) -> None:
    """تحديث المستوى والنوع والطبيعة لجميع الحسابات الفرعية عند نقل حساب رئيسي."""
    children = conn.execute("SELECT id FROM accounts WHERE parent_id=?", (parent_id,)).fetchall()
    next_lvl = parent_level + 1
    for ch in children:
        cid = int(ch["id"])
        conn.execute(
            "UPDATE accounts SET level=?, type=?, normal_balance=? WHERE id=?",
            (next_lvl, parent_type, parent_norm, cid),
        )
        _update_subtree_levels_and_type(conn, cid, next_lvl, parent_type, parent_norm)


class AccountingMixin:
    """إدارة شجرة الحسابات، القيود اليومية، الخزائن والتحويلات، المصروفات التشغيلية، والتقارير المالية."""

    # ---------------------------------------------------------- لوحة المحاسبة السريعة
    def accounting_dashboard(self):
        self._perm_any("accounting_coa_view", "accounting_statements_view", "treasury_view", "expenses_view")
        today = datetime.date.today().isoformat()
        month_prefix = today[:7]
        with db.connect() as conn:
            treasuries = [
                dict(r)
                for r in conn.execute(
                    """SELECT t.*, a.code AS account_code, a.name AS account_name, a.balance
                       FROM treasury_accounts t
                       JOIN accounts a ON a.id = t.account_id
                       WHERE t.active=1 ORDER BY t.is_default DESC, t.id ASC"""
                ).fetchall()
            ]
            total_liquidity = sum(int(t["balance"] or 0) for t in treasuries)

            exp_month = conn.execute(
                "SELECT COUNT(*) AS cnt, COALESCE(SUM(amount), 0) AS tot FROM expenses WHERE expense_date LIKE ?",
                (f"{month_prefix}%",),
            ).fetchone()

            tb_chk = conn.execute(
                """SELECT COALESCE(SUM(jl.debit), 0) AS dr, COALESCE(SUM(jl.credit), 0) AS cr
                   FROM journal_lines jl
                   JOIN journal_entries je ON je.id = jl.entry_id
                   WHERE je.status = 'posted'"""
            ).fetchone()
            total_dr = int(tb_chk["dr"] or 0)
            total_cr = int(tb_chk["cr"] or 0)

            je_cnt = conn.execute("SELECT COUNT(*) FROM journal_entries WHERE status='posted'").fetchone()[0]
            op_row = conn.execute(
                "SELECT id, entry_no, entry_date, total_debit, created_at FROM journal_entries WHERE kind='opening' AND status='posted' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            pnl = self.accounting_income_statement(date_from=f"{month_prefix}-01", date_to=today)
            return {
                "treasuries": treasuries,
                "total_liquidity": total_liquidity,
                "month_expenses_count": exp_month["cnt"],
                "month_expenses_total": exp_month["tot"],
                "month_net_profit": pnl["net_profit"],
                "month_gross_profit": pnl["gross_profit"],
                "month_net_sales": pnl["net_sales"],
                "posted_entries_count": je_cnt,
                "trial_debit": total_dr,
                "trial_credit": total_cr,
                "is_balanced": total_dr == total_cr,
                "has_opening_entry": bool(op_row),
                "opening_entry": dict(op_row) if op_row else None,
            }

    # ---------------------------------------------------------- شجرة الحسابات (Chart of Accounts)
    def accounts_tree(self, include_inactive=False):
        self._perm_any("accounting_coa_view", "accounting_statements_view", "treasury_view", "expenses_view")
        w_sql = "" if include_inactive else "WHERE a.active=1"
        with db.connect() as conn:
            rows = conn.execute(
                f"""SELECT a.*, p.code AS parent_code, p.name AS parent_name,
                           (SELECT COUNT(*) FROM journal_lines jl WHERE jl.account_id=a.id) AS lines_count,
                           (SELECT COUNT(*) FROM accounts ch WHERE ch.parent_id=a.id) AS children_count
                    FROM accounts a
                    LEFT JOIN accounts p ON p.id = a.parent_id
                    {w_sql}
                    ORDER BY a.code ASC"""
            ).fetchall()
            out = []
            for r in rows:
                d = dict(r)
                d["can_delete"] = (
                    not bool(d["is_system"])
                    and int(d["lines_count"] or 0) == 0
                    and int(d["children_count"] or 0) == 0
                    and int(d["debit_total"] or 0) == 0
                    and int(d["credit_total"] or 0) == 0
                )
                out.append(d)
            return out

    def account_save(self, code, name, parent_id=None, type="asset", normal_balance=None, is_group=0, id=None):
        self._perm("accounting_journal_manual")
        code = (code or "").strip()
        name = (name or "").strip()
        if not code or not name:
            raise ApiError("كود الحساب واسم الحساب مطلوبان")
        acc_type = (type or "asset").strip().lower()
        if acc_type not in ("asset", "liability", "equity", "revenue", "expense"):
            raise ApiError("نوع الحساب غير صالح")
        if normal_balance in ("debit", "credit"):
            norm = normal_balance
        else:
            norm = "debit" if acc_type in ("asset", "expense") else "credit"
        grp = 1 if is_group else 0
        pid = _int(parent_id) if parent_id not in (None, "", 0, "0") else None

        with db.connect() as conn:
            level = 1
            if pid:
                p_row = conn.execute("SELECT id, level, is_group, type, normal_balance FROM accounts WHERE id=?", (pid,)).fetchone()
                if not p_row:
                    raise ApiError("الحساب الأب غير موجود")
                if not p_row["is_group"]:
                    raise ApiError("الحساب الأب يجب أن يكون حساباً رئيسياً/تجميعياً (Group)")
                level = int(p_row["level"] or 1) + 1
                acc_type = p_row["type"]
                if normal_balance not in ("debit", "credit"):
                    norm = p_row["normal_balance"]
            try:
                if id:
                    aid = _int(id)
                    ex = conn.execute("SELECT * FROM accounts WHERE id=?", (aid,)).fetchone()
                    if not ex:
                        raise ApiError("الحساب غير موجود")
                    if pid == aid:
                        raise ApiError("لا يمكن ربط الحساب بنفسه كحساب أب")
                    # منع الحلقة الدائرية عند نقل الحساب الأب
                    curr_p = pid
                    while curr_p:
                        if curr_p == aid:
                            raise ApiError("لا يمكن نقل الحساب داخل أحد حساباته الفرعية")
                        pr = conn.execute("SELECT parent_id FROM accounts WHERE id=?", (curr_p,)).fetchone()
                        curr_p = int(pr["parent_id"]) if (pr and pr["parent_id"]) else None
                    if grp == 1 and not ex["is_group"]:
                        has_jl = conn.execute("SELECT 1 FROM journal_lines WHERE account_id=? LIMIT 1", (aid,)).fetchone()
                        if has_jl:
                            raise ApiError("لا يمكن تحويل حساب فرعي عليه قيود محاسبية إلى حساب رئيسي")
                    if grp == 0 and ex["is_group"]:
                        has_ch = conn.execute("SELECT 1 FROM accounts WHERE parent_id=? LIMIT 1", (aid,)).fetchone()
                        if has_ch:
                            raise ApiError("لا يمكن تحويل حساب رئيسي تحته حسابات فرعية إلى حساب فرعي")
                    conn.execute(
                        "UPDATE accounts SET code=?, name=?, parent_id=?, level=?, type=?, normal_balance=?, is_group=? WHERE id=?",
                        (code, name, pid, level, acc_type, norm, grp, aid),
                    )
                    if grp:
                        _update_subtree_levels_and_type(conn, aid, level, acc_type, norm)
                    erp_hooks.rebuild_all_account_balances(conn)
                else:
                    cur = conn.execute(
                        """INSERT INTO accounts
                           (code, name, parent_id, level, type, normal_balance, is_group, is_system, system_role, debit_total, credit_total, balance, active, created_at)
                           VALUES(?,?,?,?,?,?,?,0,NULL,0,0,0,1,?)""",
                        (code, name, pid, level, acc_type, norm, grp, db.now()),
                    )
                    aid = cur.lastrowid
            except sqlite3.IntegrityError:
                raise ApiError("كود الحساب مستخدم بالفعل لحساب آخر")
            return dict(conn.execute("SELECT * FROM accounts WHERE id=?", (aid,)).fetchone())

    def account_delete(self, id):
        """حذف حساب من شجرة الحسابات بشرط عدم كونه نظامياً وعدم وجود أي حركات أو حسابات فرعية عليه."""
        self._perm("accounting_journal_manual")
        aid = _int(id)
        with db.connect() as conn:
            ex = conn.execute("SELECT * FROM accounts WHERE id=?", (aid,)).fetchone()
            if not ex:
                raise ApiError("الحساب غير موجود")
            if ex["is_system"]:
                raise ApiError("لا يمكن حذف حساب نظامي أساسي مرتبط بالقيود الآلية")
            if conn.execute("SELECT 1 FROM accounts WHERE parent_id=? LIMIT 1", (aid,)).fetchone():
                raise ApiError("لا يمكن حذف حساب رئيسي تحته حسابات فرعية — انقل أو احذف الحسابات الفرعية أولاً")
            if (
                conn.execute("SELECT 1 FROM journal_lines WHERE account_id=? LIMIT 1", (aid,)).fetchone()
                or int(ex["debit_total"] or 0) != 0
                or int(ex["credit_total"] or 0) != 0
            ):
                raise ApiError("لا يمكن حذف هذا الحساب لوجود حركات وقيود محاسبية مسجلة عليه")
            if (
                conn.execute("SELECT 1 FROM treasury_accounts WHERE account_id=? LIMIT 1", (aid,)).fetchone()
                or conn.execute("SELECT 1 FROM expense_categories WHERE account_id=? LIMIT 1", (aid,)).fetchone()
                or conn.execute("SELECT 1 FROM accounting_posting_rules WHERE account_id=? LIMIT 1", (aid,)).fetchone()
            ):
                raise ApiError("لا يمكن حذف حساب مرتبط بخزنة أو تصنيف مصروفات أو قاعدة ترحيل نشطة")
            conn.execute("DELETE FROM accounts WHERE id=?", (aid,))
            return {"id": aid, "deleted": True}

    def account_move(self, account_id, new_parent_id=None):
        """تحريك حساب (Drag & Drop) إلى حساب رئيسي (مجموعة) آخر مع تحديث المستويات وإعادة تجميع الأرصدة."""
        self._perm("accounting_journal_manual")
        aid = _int(account_id)
        pid = _int(new_parent_id) if new_parent_id not in (None, "", 0, "0") else None
        if pid == aid:
            raise ApiError("لا يمكن نقل الحساب إلى نفسه")
        with db.connect() as conn:
            acc = conn.execute("SELECT * FROM accounts WHERE id=?", (aid,)).fetchone()
            if not acc:
                raise ApiError("الحساب المراد نقله غير موجود")
            if pid is not None:
                parent = conn.execute("SELECT * FROM accounts WHERE id=?", (pid,)).fetchone()
                if not parent:
                    raise ApiError("الحساب الأب الهدف غير موجود")
                if not parent["is_group"]:
                    raise ApiError("يمكن إفلات ونقل الحساب داخل حساب رئيسي/تجميعي (مجموعة) فقط")
                # فحص عدم النقل إلى أحد الأبناء
                curr = pid
                while curr:
                    if curr == aid:
                        raise ApiError("لا يمكن نقل حساب رئيسي إلى داخل أحد حساباته الفرعية")
                    pr = conn.execute("SELECT parent_id FROM accounts WHERE id=?", (curr,)).fetchone()
                    curr = int(pr["parent_id"]) if (pr and pr["parent_id"]) else None
                new_level = int(parent["level"] or 1) + 1
                new_type = parent["type"]
                new_norm = parent["normal_balance"] if acc["type"] != new_type else acc["normal_balance"]
            else:
                if not acc["is_group"]:
                    raise ApiError("الحسابات في المستوى الجذري الأول يجب أن تكون حسابات رئيسية (مجموعات)")
                new_level = 1
                new_type = acc["type"]
                new_norm = acc["normal_balance"]

            conn.execute(
                "UPDATE accounts SET parent_id=?, level=?, type=?, normal_balance=? WHERE id=?",
                (pid, new_level, new_type, new_norm, aid),
            )
            if acc["is_group"]:
                _update_subtree_levels_and_type(conn, aid, new_level, new_type, new_norm)
            erp_hooks.rebuild_all_account_balances(conn)
            return dict(conn.execute("SELECT * FROM accounts WHERE id=?", (aid,)).fetchone())

    def account_toggle(self, id, active=True):
        self._perm("accounting_journal_manual")
        aid = _int(id)
        act = 1 if active else 0
        with db.connect() as conn:
            ex = conn.execute("SELECT * FROM accounts WHERE id=?", (aid,)).fetchone()
            if not ex:
                raise ApiError("الحساب غير موجود")
            if ex["is_system"] and not act:
                raise ApiError("لا يمكن تعطيل حساب نظامي أساسي مرتبط بالقيود الآلية")
            conn.execute("UPDATE accounts SET active=? WHERE id=?", (act, aid))
            return {"id": aid, "active": bool(act)}

    # ---------------------------------------------------------- الخزائن والبنوك والتحويلات
    def treasury_list(self):
        self._perm_any("treasury_view", "treasury_transfer", "accounting_coa_view", "purchases_payment", "expenses_manage")
        with db.connect() as conn:
            rows = conn.execute(
                """SELECT t.*, a.code AS account_code, a.name AS account_name, a.balance
                   FROM treasury_accounts t
                   JOIN accounts a ON a.id = t.account_id
                   WHERE t.active=1
                   ORDER BY t.is_default DESC, t.id ASC"""
            ).fetchall()
            return [dict(r) for r in rows]

    def treasury_save(self, name, kind="cash", account_id=None, code=None, is_default=0, notes=None, id=None):
        self._perm("treasury_transfer")
        name = (name or "").strip()
        if not name:
            raise ApiError("اسم الخزنة / الحساب البنكي مطلوب")
        kind = (kind or "cash").strip()
        if kind not in ("cash", "pos_drawer", "wallet", "bank"):
            raise ApiError("نوع الخزنة غير صالح")

        with db.connect() as conn:
            acc_id = _int(account_id) if account_id else None
            if not acc_id:
                parent_code = "1101" if kind in ("cash", "pos_drawer") else "1102"
                parent = conn.execute("SELECT id, level FROM accounts WHERE code=?", (parent_code,)).fetchone()
                cnt = conn.execute("SELECT COUNT(*) FROM accounts WHERE parent_id=?", (parent["id"] if parent else 0,)).fetchone()[0] + 10
                new_acc_code = f"{parent_code}{cnt:02d}"
                while conn.execute("SELECT 1 FROM accounts WHERE code=?", (new_acc_code,)).fetchone():
                    cnt += 1
                    new_acc_code = f"{parent_code}{cnt:02d}"
                cur_a = conn.execute(
                    """INSERT INTO accounts(code, name, parent_id, level, type, normal_balance, is_group, is_system, debit_total, credit_total, balance, active, created_at)
                       VALUES(?,?,?,?, 'asset','debit',0,0,0,0,0,1,?)""",
                    (new_acc_code, name, parent["id"] if parent else None, 4, db.now()),
                )
                acc_id = cur_a.lastrowid

            if is_default:
                conn.execute("UPDATE treasury_accounts SET is_default=0")

            if id:
                tid = _int(id)
                conn.execute(
                    "UPDATE treasury_accounts SET name=?, kind=?, account_id=?, is_default=?, notes=? WHERE id=?",
                    (name, kind, acc_id, 1 if is_default else 0, (notes or "").strip() or None, tid),
                )
            else:
                cnt_t = conn.execute("SELECT COUNT(*) FROM treasury_accounts").fetchone()[0] + 1
                t_code = (code or "").strip() or f"TR-{cnt_t:02d}"
                cur_t = conn.execute(
                    """INSERT INTO treasury_accounts(code, name, kind, account_id, is_default, active, notes, created_at)
                       VALUES(?,?,?,?,?,1,?,?)""",
                    (t_code, name, kind, acc_id, 1 if is_default else 0, (notes or "").strip() or None, db.now()),
                )
                tid = cur_t.lastrowid
            return dict(conn.execute("SELECT * FROM treasury_accounts WHERE id=?", (tid,)).fetchone())

    def treasury_transfer_create(self, from_treasury_id, to_treasury_id, amount, transfer_date=None, ref_no=None, notes=None):
        """تحويل مالي بين خزنتين/بنكين (مثل توريد نقدية درج الكاشير إلى الخزنة الرئيسية أو البنك) مع قيد آلي."""
        u = self._perm("treasury_transfer")
        f_id = _int(from_treasury_id)
        t_id = _int(to_treasury_id)
        if f_id == t_id:
            raise ApiError("لا يمكن التحويل من وإلى نفس الخزنة")
        amt = _money(amount)
        if amt <= 0:
            raise ApiError("مبلغ التحويل يجب أن يكون أكبر من صفر")
        dt_str = (transfer_date or db.now()[:10]).strip()[:10]
        clean_notes = (notes or "").strip() or None
        clean_ref = (ref_no or "").strip() or None

        with db.connect() as conn:
            f_tr = conn.execute("SELECT * FROM treasury_accounts WHERE id=? AND active=1", (f_id,)).fetchone()
            t_tr = conn.execute("SELECT * FROM treasury_accounts WHERE id=? AND active=1", (t_id,)).fetchone()
            if not f_tr or not t_tr:
                raise ApiError("إحدى الخزائن المحددة غير موجودة")

            now_ts = db.now()
            cur = conn.execute(
                """INSERT INTO treasury_transfers
                   (transfer_no, from_treasury_id, to_treasury_id, amount, transfer_date, ref_no, notes, user_id, created_at)
                   VALUES('TRF-TMP',?,?,?,?,?,?,?,?)""",
                (f_id, t_id, amt, dt_str, clean_ref, clean_notes, u["id"], now_ts),
            )
            trf_id = cur.lastrowid
            trf_no = _format_doc_seq(f"TRF-{dt_str[:4]}-", trf_id)
            conn.execute("UPDATE treasury_transfers SET transfer_no=? WHERE id=?", (trf_no, trf_id))

            memo = clean_notes or f"تحويل من «{f_tr['name']}» إلى «{t_tr['name']}» ({trf_no})"
            je = erp_hooks.post_journal_entry(
                conn,
                memo=memo,
                lines=[
                    {"account_id": t_tr["account_id"], "debit": amt, "credit": 0, "memo": memo},
                    {"account_id": f_tr["account_id"], "debit": 0, "credit": amt, "memo": memo},
                ],
                entry_date=dt_str,
                kind="auto",
                source_module="accounting",
                source_table="treasury_transfers",
                source_id=trf_id,
                ref=trf_no,
                user_id=u["id"],
            )
            conn.execute("UPDATE treasury_transfers SET journal_entry_id=? WHERE id=?", (je["entry_id"], trf_id))
            return {
                "id": trf_id,
                "transfer_no": trf_no,
                "amount": amt,
                "journal_entry_id": je["entry_id"],
                "entry_no": je["entry_no"],
            }

    def treasury_transfers_list(self, limit=100):
        self._perm_any("treasury_view", "treasury_transfer")
        lim = max(1, min(200, _int(limit, 100)))
        with db.connect() as conn:
            rows = conn.execute(
                """SELECT tr.*, f.name AS from_name, t.name AS to_name, u.name AS user_name, je.entry_no
                   FROM treasury_transfers tr
                   JOIN treasury_accounts f ON f.id = tr.from_treasury_id
                   JOIN treasury_accounts t ON t.id = tr.to_treasury_id
                   LEFT JOIN users u ON u.id = tr.user_id
                   LEFT JOIN journal_entries je ON je.id = tr.journal_entry_id
                   ORDER BY tr.id DESC LIMIT ?""",
                (lim,),
            ).fetchall()
            return [dict(r) for r in rows]

    # ---------------------------------------------------------- المصروفات التشغيلية ومراكز التكلفة
    def expense_categories_list(self):
        self._perm_any("expenses_view", "expenses_manage", "accounting_coa_view")
        with db.connect() as conn:
            rows = conn.execute(
                """SELECT ec.*, a.code AS account_code, a.name AS account_name
                   FROM expense_categories ec
                   JOIN accounts a ON a.id = ec.account_id
                   WHERE ec.active=1 ORDER BY ec.id ASC"""
            ).fetchall()
            return [dict(r) for r in rows]

    def expense_category_save(self, name, account_id=None, id=None):
        self._perm("expenses_manage")
        name = (name or "").strip()
        if not name:
            raise ApiError("اسم بند المصروف مطلوب")
        with db.connect() as conn:
            acc_id = _int(account_id) if account_id else None
            if not acc_id:
                acc = erp_hooks.get_account_by_role(conn, "exp_general", "5205")
                acc_id = acc["id"] if acc else None
            if not acc_id:
                raise ApiError("حساب المصروف غير محدد")
            try:
                if id:
                    cid = _int(id)
                    conn.execute("UPDATE expense_categories SET name=?, account_id=? WHERE id=?", (name, acc_id, cid))
                else:
                    cur = conn.execute("INSERT INTO expense_categories(name, account_id, active) VALUES(?,?,1)", (name, acc_id))
                    cid = cur.lastrowid
            except sqlite3.IntegrityError:
                raise ApiError("يوجد تصنيف مصروف بهذا الاسم مسبقاً")
            return dict(conn.execute("SELECT * FROM expense_categories WHERE id=?", (cid,)).fetchone())

    def cost_centers_list(self):
        self._perm_any("accounting_coa_view", "expenses_view", "accounting_statements_view")
        with db.connect() as conn:
            rows = conn.execute("SELECT * FROM cost_centers WHERE active=1 ORDER BY id ASC").fetchall()
            return [dict(r) for r in rows]

    def cost_center_save(self, code, name, id=None):
        self._perm("accounting_journal_manual")
        code = (code or "").strip()
        name = (name or "").strip()
        if not code or not name:
            raise ApiError("كود واسم مركز التكلفة مطلوبان")
        with db.connect() as conn:
            try:
                if id:
                    ccid = _int(id)
                    conn.execute("UPDATE cost_centers SET code=?, name=? WHERE id=?", (code, name, ccid))
                else:
                    cur = conn.execute("INSERT INTO cost_centers(code, name, active, created_at) VALUES(?,?,1,?)", (code, name, db.now()))
                    ccid = cur.lastrowid
            except sqlite3.IntegrityError:
                raise ApiError("كود مركز التكلفة مستخدم بالفعل")
            return dict(conn.execute("SELECT * FROM cost_centers WHERE id=?", (ccid,)).fetchone())

    def expense_create(
        self,
        category_id,
        amount,
        treasury_id=None,
        method="cash",
        from_drawer=False,
        cost_center_id=None,
        expense_date=None,
        payee=None,
        ref_no=None,
        notes=None,
    ):
        """تسجيل مصروف تشغيلي (إيجار/رواتب/كهرباء/نقل...) وتوليد قيد يومية آلي."""
        u = self._perm("expenses_manage")
        cat_id = _int(category_id)
        amt = _money(amount)
        if amt <= 0:
            raise ApiError("مبلغ المصروف يجب أن يكون أكبر من صفر")
        dt_str = (expense_date or db.now()[:10]).strip()[:10]
        method = (method or "cash").strip().lower()
        use_drawer = bool(from_drawer)

        with db.connect() as conn:
            cat = conn.execute("SELECT * FROM expense_categories WHERE id=?", (cat_id,)).fetchone()
            if not cat:
                raise ApiError("تصنيف المصروف غير موجود")

            shift_id = None
            if use_drawer:
                s_open = self._open_shift(conn, u["id"])
                if not s_open:
                    raise ApiError("صرف المصروف من درج الكاشير يتطلب وردية مفتوحة")
                shift_id = s_open["id"]

            if treasury_id:
                tr = conn.execute("SELECT * FROM treasury_accounts WHERE id=? AND active=1", (_int(treasury_id),)).fetchone()
            else:
                kind_target = "pos_drawer" if use_drawer else ("wallet" if method == "wallet" else ("bank" if method in ("bank", "instapay") else "cash"))
                tr = conn.execute(
                    "SELECT * FROM treasury_accounts WHERE kind=? AND active=1 ORDER BY is_default DESC, id ASC LIMIT 1",
                    (kind_target,),
                ).fetchone()
                if not tr:
                    tr = conn.execute("SELECT * FROM treasury_accounts WHERE active=1 ORDER BY is_default DESC, id ASC LIMIT 1").fetchone()
            if not tr:
                raise ApiError("لا توجد خزنة مفعلة لصرف المصروف")

            now_ts = db.now()
            cc_id = _int(cost_center_id) if cost_center_id else None
            clean_payee = (payee or "").strip() or None
            clean_ref = (ref_no or "").strip() or None
            clean_notes = (notes or "").strip() or None

            cur = conn.execute(
                """INSERT INTO expenses
                   (expense_no, category_id, account_id, treasury_id, cost_center_id, shift_id, from_drawer,
                    amount, expense_date, method, ref_no, payee, notes, user_id, created_at)
                   VALUES('EXP-TMP',?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    cat_id, cat["account_id"], tr["id"], cc_id, shift_id, 1 if use_drawer else 0,
                    amt, dt_str, method, clean_ref, clean_payee, clean_notes, u["id"], now_ts,
                ),
            )
            exp_id = cur.lastrowid
            exp_no = _format_doc_seq(f"EXP-{dt_str[:4]}-", exp_id)
            conn.execute("UPDATE expenses SET expense_no=? WHERE id=?", (exp_no, exp_id))

            memo = f"مصروف ({cat['name']})" + (f" — {clean_notes}" if clean_notes else "")
            je = erp_hooks.post_journal_entry(
                conn,
                memo=memo,
                lines=[
                    {"account_id": cat["account_id"], "debit": amt, "credit": 0, "cost_center_id": cc_id, "memo": memo},
                    {"account_id": tr["account_id"], "debit": 0, "credit": amt, "memo": f"صرف {exp_no} من {tr['name']}"},
                ],
                entry_date=dt_str,
                kind="auto",
                source_module="accounting",
                source_table="expenses",
                source_id=exp_id,
                ref=exp_no,
                user_id=u["id"],
            )
            conn.execute("UPDATE expenses SET journal_entry_id=? WHERE id=?", (je["entry_id"], exp_id))
            return {
                "id": exp_id,
                "expense_no": exp_no,
                "amount": amt,
                "journal_entry_id": je["entry_id"],
                "entry_no": je["entry_no"],
            }

    def expense_delete(self, id):
        u = self._perm("accounting_journal_manual")
        exp_id = _int(id)
        with db.connect() as conn:
            ex = conn.execute("SELECT * FROM expenses WHERE id=?", (exp_id,)).fetchone()
            if not ex:
                raise ApiError("سجل المصروف غير موجود")
            if ex["journal_entry_id"]:
                erp_hooks.reverse_journal_entry(
                    conn,
                    ex["journal_entry_id"],
                    reason=f"إلغاء مصروف {ex['expense_no']}",
                    user_id=u["id"],
                )
            conn.execute("DELETE FROM expenses WHERE id=?", (exp_id,))
            return True

    def expenses_list(self, category_id=None, date_from=None, date_to=None, limit=100, offset=0):
        self._perm_any("expenses_view", "expenses_manage", "accounting_coa_view")
        limit = max(1, min(200, _int(limit, 100)))
        offset = max(0, _int(offset, 0))
        where = ["1=1"]
        args = []
        if category_id:
            where.append("e.category_id=?")
            args.append(_int(category_id))
        if date_from:
            where.append("e.expense_date >= ?")
            args.append(date_from.strip()[:10])
        if date_to:
            where.append("e.expense_date <= ?")
            args.append(date_to.strip()[:10])
        w_sql = " AND ".join(where)
        with db.connect() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM expenses e WHERE {w_sql}", args).fetchone()[0]
            sum_amt = conn.execute(f"SELECT COALESCE(SUM(e.amount), 0) FROM expenses e WHERE {w_sql}", args).fetchone()[0]
            rows = conn.execute(
                f"""SELECT e.*, c.name AS category_name, t.name AS treasury_name,
                           cc.name AS cost_center_name, u.name AS user_name, je.entry_no
                    FROM expenses e
                    JOIN expense_categories c ON c.id = e.category_id
                    JOIN treasury_accounts t ON t.id = e.treasury_id
                    LEFT JOIN cost_centers cc ON cc.id = e.cost_center_id
                    LEFT JOIN users u ON u.id = e.user_id
                    LEFT JOIN journal_entries je ON je.id = e.journal_entry_id
                    WHERE {w_sql}
                    ORDER BY e.id DESC LIMIT ? OFFSET ?""",
                [*args, limit, offset],
            ).fetchall()
            return {"rows": [dict(r) for r in rows], "total": total, "total_amount": sum_amt}

    # ---------------------------------------------------------- دفتر اليومية والقيود اليدوية والعكسية
    def journal_entries_list(self, q="", kind=None, status=None, source_module=None, date_from=None, date_to=None, limit=100, offset=0):
        self._perm_any("accounting_coa_view", "accounting_journal_manual", "accounting_statements_view")
        limit = max(1, min(200, _int(limit, 100)))
        offset = max(0, _int(offset, 0))
        where = ["1=1"]
        args = []
        if kind:
            where.append("je.kind=?")
            args.append(kind)
        if status:
            where.append("je.status=?")
            args.append(status)
        if source_module:
            where.append("je.source_module=?")
            args.append(source_module)
        if date_from:
            where.append("je.entry_date >= ?")
            args.append(date_from.strip()[:10])
        if date_to:
            where.append("je.entry_date <= ?")
            args.append(date_to.strip()[:10])
        if q:
            like = f"%{q.strip()}%"
            where.append("(je.entry_no LIKE ? OR COALESCE(je.ref,'') LIKE ? OR je.memo LIKE ?)")
            args.extend([like, like, like])
        w_sql = " AND ".join(where)
        with db.connect() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM journal_entries je WHERE {w_sql}", args).fetchone()[0]
            rows = conn.execute(
                f"""SELECT je.*, u.name AS user_name
                    FROM journal_entries je
                    LEFT JOIN users u ON u.id = je.user_id
                    WHERE {w_sql}
                    ORDER BY je.id DESC LIMIT ? OFFSET ?""",
                [*args, limit, offset],
            ).fetchall()
            return {"rows": [dict(r) for r in rows], "total": total}

    def journal_entry_get(self, id=None, source_table=None, source_id=None):
        self._perm_any("accounting_coa_view", "accounting_journal_manual", "accounting_statements_view")
        with db.connect() as conn:
            if id:
                je = conn.execute(
                    """SELECT je.*, u.name AS user_name
                       FROM journal_entries je
                       LEFT JOIN users u ON u.id = je.user_id
                       WHERE je.id=?""",
                    (_int(id),),
                ).fetchone()
            elif source_table and source_id:
                je = conn.execute(
                    """SELECT je.*, u.name AS user_name
                       FROM journal_entries je
                       LEFT JOIN users u ON u.id = je.user_id
                       WHERE je.source_table=? AND je.source_id=?
                       ORDER BY je.id DESC LIMIT 1""",
                    (str(source_table), _int(source_id)),
                ).fetchone()
            else:
                raise ApiError("معرف القيد مطلوب")
            if not je:
                raise ApiError("القيد المحاسبي غير موجود")
            d = dict(je)
            lines = conn.execute(
                """SELECT jl.*, a.code AS account_code, a.name AS account_name, cc.name AS cost_center_name
                   FROM journal_lines jl
                   JOIN accounts a ON a.id = jl.account_id
                   LEFT JOIN cost_centers cc ON cc.id = jl.cost_center_id
                   WHERE jl.entry_id=?
                   ORDER BY jl.line_no ASC""",
                (je["id"],),
            ).fetchall()
            d["lines"] = [dict(x) for x in lines]
            return d

    def journal_entry_create(self, memo, lines, entry_date=None, ref=None, kind="manual"):
        """إنشاء قيد يومية يدوي متوازن (مع تحويل القيم من جنيه إلى قرش إن لم تكن محولة)."""
        u = self._perm("accounting_journal_manual")
        memo = (memo or "").strip()
        if not memo:
            raise ApiError("بيان القيد اليومي مطلوب")
        if kind not in ("manual", "opening", "closing"):
            kind = "manual"
        parsed_lines = []
        for raw in lines or []:
            dr_raw = raw.get("debit", 0)
            cr_raw = raw.get("credit", 0)
            is_minor = bool(raw.get("is_minor", False))
            dr = _int(dr_raw, 0) if is_minor else _money(dr_raw, 0)
            cr = _int(cr_raw, 0) if is_minor else _money(cr_raw, 0)
            parsed_lines.append({
                "account_id": _int(raw.get("account_id")),
                "debit": dr,
                "credit": cr,
                "cost_center_id": _int(raw.get("cost_center_id"), 0) or None,
                "party_type": raw.get("party_type"),
                "party_id": _int(raw.get("party_id"), 0) or None,
                "memo": raw.get("memo") or memo,
            })
        with db.connect() as conn:
            res = erp_hooks.post_journal_entry(
                conn,
                memo=memo,
                lines=parsed_lines,
                entry_date=entry_date,
                kind=kind,
                source_module="accounting",
                source_table="manual",
                ref=(ref or "").strip() or None,
                user_id=u["id"],
                strict_closed_check=True,
            )
        return self.journal_entry_get(id=res["entry_id"])

    def journal_entry_reverse(self, id, reason=None):
        """عكس قيد يومية مرحّل بإنشاء قيد عكسي متوازن."""
        u = self._perm("accounting_journal_manual")
        with db.connect() as conn:
            rev = erp_hooks.reverse_journal_entry(conn, _int(id), reason=reason or "", user_id=u["id"])
        return self.journal_entry_get(id=rev["entry_id"])

    # ---------------------------------------------------------- القوائم والتقارير المالية
    def accounting_ledger(self, account_id, date_from=None, date_to=None, party_type=None, party_id=None):
        """دفتر الأستاذ العام والمساعد لحساب محدد مع الرصيد الافتتاحي والرصيد المتحرك بعد كل قيد."""
        self._perm_any("accounting_coa_view", "accounting_statements_view")
        aid = _int(account_id)
        df = (date_from or "").strip()[:10]
        dt = (date_to or "").strip()[:10]
        with db.connect() as conn:
            acc = conn.execute("SELECT * FROM accounts WHERE id=?", (aid,)).fetchone()
            if not acc:
                raise ApiError("الحساب غير موجود")
            is_dr_norm = acc["normal_balance"] == "debit"

            p_clauses = ["jl.account_id=?", "je.status='posted'"]
            p_args = [aid]
            if party_type:
                p_clauses.append("jl.party_type=?")
                p_args.append(party_type)
            if party_id:
                p_clauses.append("jl.party_id=?")
                p_args.append(_int(party_id))

            opening_dr = 0
            opening_cr = 0
            if df:
                op_row = conn.execute(
                    f"""SELECT COALESCE(SUM(jl.debit), 0) AS dr, COALESCE(SUM(jl.credit), 0) AS cr
                        FROM journal_lines jl
                        JOIN journal_entries je ON je.id = jl.entry_id
                        WHERE {' AND '.join(p_clauses)} AND je.entry_date < ?""",
                    [*p_args, df],
                ).fetchone()
                opening_dr = int(op_row["dr"] or 0)
                opening_cr = int(op_row["cr"] or 0)

            opening_balance = (opening_dr - opening_cr) if is_dr_norm else (opening_cr - opening_dr)

            m_clauses = list(p_clauses)
            m_args = list(p_args)
            if df:
                m_clauses.append("je.entry_date >= ?")
                m_args.append(df)
            if dt:
                m_clauses.append("je.entry_date <= ?")
                m_args.append(dt)

            rows = conn.execute(
                f"""SELECT jl.*, je.entry_no, je.entry_date, je.kind, je.ref, je.source_module, je.memo AS entry_memo
                    FROM journal_lines jl
                    JOIN journal_entries je ON je.id = jl.entry_id
                    WHERE {' AND '.join(m_clauses)}
                    ORDER BY je.entry_date ASC, je.id ASC, jl.line_no ASC""",
                m_args,
            ).fetchall()

            running = opening_balance
            out_lines = []
            period_dr = 0
            period_cr = 0
            for r in rows:
                d = dict(r)
                dr = int(d["debit"] or 0)
                cr = int(d["credit"] or 0)
                period_dr += dr
                period_cr += cr
                running += (dr - cr) if is_dr_norm else (cr - dr)
                d["balance_after"] = running
                out_lines.append(d)

            return {
                "account": dict(acc),
                "opening_balance": opening_balance,
                "period_debit": period_dr,
                "period_credit": period_cr,
                "closing_balance": running,
                "rows": out_lines,
            }

    def accounting_trial_balance(self, date_from=None, date_to=None):
        """ميزان المراجعة بالأرصدة والمجاميع (أول المدة / حركات الفترة / الرصيد الختامي)."""
        self._perm("accounting_statements_view")
        df = (date_from or "").strip()[:10]
        dt = (date_to or "").strip()[:10]
        with db.connect() as conn:
            accs = conn.execute(
                "SELECT * FROM accounts WHERE is_group=0 AND active=1 ORDER BY code ASC"
            ).fetchall()

            op_map = {}
            if df:
                for r in conn.execute(
                    """SELECT jl.account_id, COALESCE(SUM(jl.debit), 0) AS dr, COALESCE(SUM(jl.credit), 0) AS cr
                       FROM journal_lines jl
                       JOIN journal_entries je ON je.id = jl.entry_id
                       WHERE je.status='posted' AND je.entry_date < ?
                       GROUP BY jl.account_id""",
                    (df,),
                ).fetchall():
                    op_map[r["account_id"]] = (int(r["dr"] or 0), int(r["cr"] or 0))

            p_where = ["je.status='posted'"]
            p_args = []
            if df:
                p_where.append("je.entry_date >= ?")
                p_args.append(df)
            if dt:
                p_where.append("je.entry_date <= ?")
                p_args.append(dt)

            per_map = {}
            for r in conn.execute(
                f"""SELECT jl.account_id, COALESCE(SUM(jl.debit), 0) AS dr, COALESCE(SUM(jl.credit), 0) AS cr
                    FROM journal_lines jl
                    JOIN journal_entries je ON je.id = jl.entry_id
                    WHERE {' AND '.join(p_where)}
                    GROUP BY jl.account_id""",
                p_args,
            ).fetchall():
                per_map[r["account_id"]] = (int(r["dr"] or 0), int(r["cr"] or 0))

            rows = []
            totals = {
                "opening_debit": 0,
                "opening_credit": 0,
                "period_debit": 0,
                "period_credit": 0,
                "closing_debit": 0,
                "closing_credit": 0,
            }
            for a in accs:
                aid = a["id"]
                op_dr, op_cr = op_map.get(aid, (0, 0))
                pr_dr, pr_cr = per_map.get(aid, (0, 0))
                if op_dr == 0 and op_cr == 0 and pr_dr == 0 and pr_cr == 0:
                    continue
                op_net = op_dr - op_cr
                op_d_bal = max(0, op_net)
                op_c_bal = max(0, -op_net)

                cl_net = (op_dr + pr_dr) - (op_cr + pr_cr)
                cl_d_bal = max(0, cl_net)
                cl_c_bal = max(0, -cl_net)

                rows.append({
                    "account_id": aid,
                    "code": a["code"],
                    "name": a["name"],
                    "type": a["type"],
                    "opening_debit": op_d_bal,
                    "opening_credit": op_c_bal,
                    "period_debit": pr_dr,
                    "period_credit": pr_cr,
                    "closing_debit": cl_d_bal,
                    "closing_credit": cl_c_bal,
                })
                totals["opening_debit"] += op_d_bal
                totals["opening_credit"] += op_c_bal
                totals["period_debit"] += pr_dr
                totals["period_credit"] += pr_cr
                totals["closing_debit"] += cl_d_bal
                totals["closing_credit"] += cl_c_bal

            is_balanced = (
                totals["opening_debit"] == totals["opening_credit"]
                and totals["period_debit"] == totals["period_credit"]
                and totals["closing_debit"] == totals["closing_credit"]
            )
            return {"rows": rows, "totals": totals, "is_balanced": is_balanced}

    def accounting_income_statement(self, date_from=None, date_to=None, cost_center_id=None):
        """قائمة الدخل (P&L): صافي المبيعات - تكلفة المبيعات = مجمل الربح + الإيرادات الأخرى - المصروفات = صافي الربح."""
        self._perm_any("accounting_statements_view", "accounting_coa_view", "reports_profit_view")
        df = (date_from or "").strip()[:10]
        dt = (date_to or "").strip()[:10]
        cc_id = _int(cost_center_id) if cost_center_id else None

        clauses = ["je.status='posted'", "je.kind != 'closing'", "a.type IN ('revenue','expense')"]
        args = []
        if df:
            clauses.append("je.entry_date >= ?")
            args.append(df)
        if dt:
            clauses.append("je.entry_date <= ?")
            args.append(dt)
        if cc_id:
            clauses.append("jl.cost_center_id = ?")
            args.append(cc_id)

        with db.connect() as conn:
            rows = conn.execute(
                f"""SELECT a.id, a.code, a.name, a.type, a.normal_balance, a.system_role,
                           COALESCE(SUM(jl.debit), 0) AS dr,
                           COALESCE(SUM(jl.credit), 0) AS cr
                    FROM accounts a
                    LEFT JOIN journal_lines jl ON jl.account_id = a.id
                    LEFT JOIN journal_entries je ON je.id = jl.entry_id
                    WHERE {' AND '.join(clauses)}
                    GROUP BY a.id
                    ORDER BY a.code ASC""",
                args,
            ).fetchall()

            gross_sales = 0
            sales_returns = 0
            discount_allowed = 0
            other_revenues = []
            cogs_items = []
            operating_expenses = []

            for r in rows:
                dr = int(r["dr"] or 0)
                cr = int(r["cr"] or 0)
                role = r["system_role"]
                code = r["code"]
                if r["type"] == "revenue":
                    if role == "sales_revenue" or code == "4101":
                        gross_sales += max(0, cr - dr)
                    elif role == "sales_returns" or code == "4102":
                        sales_returns += max(0, dr - cr)
                    elif role == "discount_allowed" or code == "4103":
                        discount_allowed += max(0, dr - cr)
                    else:
                        amt = cr - dr
                        if amt != 0:
                            other_revenues.append({"code": code, "name": r["name"], "amount": amt})
                elif r["type"] == "expense":
                    amt = dr - cr
                    if amt == 0:
                        continue
                    if code.startswith("51") or role in ("cogs", "repair_parts_cogs", "stock_adj_diff"):
                        cogs_items.append({"code": code, "name": r["name"], "amount": amt})
                    else:
                        operating_expenses.append({"code": code, "name": r["name"], "amount": amt})

            net_sales = gross_sales - sales_returns - discount_allowed
            total_cogs = sum(x["amount"] for x in cogs_items)
            gross_profit = net_sales - total_cogs
            total_other_rev = sum(x["amount"] for x in other_revenues)
            total_op_exp = sum(x["amount"] for x in operating_expenses)
            net_profit = gross_profit + total_other_rev - total_op_exp

            return {
                "gross_sales": gross_sales,
                "sales_returns": sales_returns,
                "discount_allowed": discount_allowed,
                "net_sales": net_sales,
                "cogs_items": cogs_items,
                "total_cogs": total_cogs,
                "gross_profit": gross_profit,
                "other_revenues": other_revenues,
                "total_other_revenues": total_other_rev,
                "operating_expenses": operating_expenses,
                "total_operating_expenses": total_op_exp,
                "net_profit": net_profit,
            }

    def accounting_balance_sheet(self, as_of_date=None):
        """الميزانية العمومية (المركز المالي): الأصول = الالتزامات + حقوق الملكية (شاملة صافي ربح الفترة)."""
        self._perm("accounting_statements_view")
        dt = (as_of_date or "").strip()[:10]
        where = ["je.status='posted'"]
        args = []
        if dt:
            where.append("je.entry_date <= ?")
            args.append(dt)

        with db.connect() as conn:
            rows = conn.execute(
                f"""SELECT a.id, a.code, a.name, a.type, a.normal_balance,
                           COALESCE(SUM(jl.debit), 0) AS dr,
                           COALESCE(SUM(jl.credit), 0) AS cr
                    FROM accounts a
                    JOIN journal_lines jl ON jl.account_id = a.id
                    JOIN journal_entries je ON je.id = jl.entry_id
                    WHERE a.is_group=0 AND {' AND '.join(where)}
                    GROUP BY a.id
                    ORDER BY a.code ASC""",
                args,
            ).fetchall()

            assets = []
            liabilities = []
            equity = []
            rev_net = 0
            exp_net = 0

            for r in rows:
                dr = int(r["dr"] or 0)
                cr = int(r["cr"] or 0)
                t = r["type"]
                if t == "asset":
                    bal = dr - cr
                    if bal != 0:
                        assets.append({"code": r["code"], "name": r["name"], "balance": bal})
                elif t == "liability":
                    bal = cr - dr
                    if bal != 0:
                        liabilities.append({"code": r["code"], "name": r["name"], "balance": bal})
                elif t == "equity":
                    bal = cr - dr
                    if bal != 0:
                        equity.append({"code": r["code"], "name": r["name"], "balance": bal})
                elif t == "revenue":
                    rev_net += (cr - dr)
                elif t == "expense":
                    exp_net += (dr - cr)

            period_net_profit = rev_net - exp_net
            total_assets = sum(x["balance"] for x in assets)
            total_liabilities = sum(x["balance"] for x in liabilities)
            total_equity_base = sum(x["balance"] for x in equity)
            total_equity = total_equity_base + period_net_profit
            total_liab_and_equity = total_liabilities + total_equity

            return {
                "as_of_date": dt or db.now()[:10],
                "assets": assets,
                "liabilities": liabilities,
                "equity": equity,
                "period_net_profit": period_net_profit,
                "total_assets": total_assets,
                "total_liabilities": total_liabilities,
                "total_equity": total_equity,
                "total_liabilities_and_equity": total_liab_and_equity,
                "is_balanced": total_assets == total_liab_and_equity,
            }

    def accounting_tax_report(self, date_from=None, date_to=None):
        """إقرار وملخص الضرائب: ضريبة القيمة المضافة (مخرجات - مدخلات) وضريبة الخصم والإضافة (1% / 3%)."""
        self._perm("accounting_statements_view")
        df = (date_from or "").strip()[:10]
        dt = (date_to or "").strip()[:10]
        where = ["je.status='posted'"]
        args = []
        if df:
            where.append("je.entry_date >= ?")
            args.append(df)
        if dt:
            where.append("je.entry_date <= ?")
            args.append(dt)

        with db.connect() as conn:
            def _role_movement(role_key, fallback_code):
                acc = erp_hooks.get_account_by_role(conn, role_key, fallback_code)
                if not acc:
                    return 0, 0
                r = conn.execute(
                    f"""SELECT COALESCE(SUM(jl.debit), 0) AS dr, COALESCE(SUM(jl.credit), 0) AS cr
                        FROM journal_lines jl
                        JOIN journal_entries je ON je.id = jl.entry_id
                        WHERE jl.account_id=? AND {' AND '.join(where)}""",
                    [acc["id"], *args],
                ).fetchone()
                return int(r["dr"] or 0), int(r["cr"] or 0)

            in_dr, in_cr = _role_movement("vat_input", "1107")
            out_dr, out_cr = _role_movement("vat_output", "2102")
            wht_dr, wht_cr = _role_movement("wht_payable", "2103")

            vat_input = max(0, in_dr - in_cr)
            vat_output = max(0, out_cr - out_dr)
            net_vat_payable = vat_output - vat_input
            wht_payable = max(0, wht_cr - wht_dr)

            return {
                "vat_output": vat_output,
                "vat_input": vat_input,
                "net_vat_payable": net_vat_payable,
                "wht_collected": wht_cr,
                "wht_remitted": wht_dr,
                "wht_payable": wht_payable,
            }

    # ---------------------------------------------------------- الفترات المالية وإقفال السنة
    def fiscal_periods_list(self):
        self._perm_any("accounting_statements_view", "accounting_coa_view")
        with db.connect() as conn:
            erp_hooks.ensure_open_period(conn, db.now()[:10], strict_closed_check=False)
            years = [dict(r) for r in conn.execute("SELECT * FROM fiscal_years ORDER BY name DESC").fetchall()]
            periods = [dict(r) for r in conn.execute("SELECT * FROM fiscal_periods ORDER BY period_key DESC").fetchall()]
            return {"years": years, "periods": periods}

    def fiscal_period_toggle(self, period_id, status="closed"):
        u = self._perm("accounting_statements_view")
        pid = _int(period_id)
        st = "closed" if status == "closed" else "open"
        with db.connect() as conn:
            fp = conn.execute("SELECT * FROM fiscal_periods WHERE id=?", (pid,)).fetchone()
            if not fp:
                raise ApiError("الفترة المالية غير موجودة")
            conn.execute(
                "UPDATE fiscal_periods SET status=?, closed_at=?, closed_by=? WHERE id=?",
                (st, db.now() if st == "closed" else None, u["id"] if st == "closed" else None, pid),
            )
            return dict(conn.execute("SELECT * FROM fiscal_periods WHERE id=?", (pid,)).fetchone())

    def fiscal_year_close(self, year_id=None, year_name=None):
        """إقفال السنة المالية وترحيل صافي ربح/خسارة العام إلى حساب الأرباح المحتجزة آلياً."""
        u = self._perm("accounting_statements_view")
        with db.connect() as conn:
            if year_id:
                fy = conn.execute("SELECT * FROM fiscal_years WHERE id=?", (_int(year_id),)).fetchone()
            elif year_name:
                fy = conn.execute("SELECT * FROM fiscal_years WHERE name=?", (str(year_name).strip(),)).fetchone()
            else:
                fy = conn.execute("SELECT * FROM fiscal_years WHERE status='open' ORDER BY name DESC LIMIT 1").fetchone()
            if not fy:
                raise ApiError("السنة المالية غير موجودة")
            if fy["status"] == "closed":
                raise ApiError("هذه السنة المالية مقفلة بالفعل")

            rows = conn.execute(
                """SELECT a.id, a.code, a.name, a.type,
                          COALESCE(SUM(jl.debit), 0) AS dr,
                          COALESCE(SUM(jl.credit), 0) AS cr
                   FROM accounts a
                   JOIN journal_lines jl ON jl.account_id = a.id
                   JOIN journal_entries je ON je.id = jl.entry_id
                   WHERE a.is_group=0 AND a.type IN ('revenue','expense')
                     AND je.status='posted' AND je.entry_date >= ? AND je.entry_date <= ?
                   GROUP BY a.id""",
                (fy["start_date"], fy["end_date"]),
            ).fetchall()

            acc_ret = erp_hooks.get_account_by_role(conn, "retained_earnings", "3104")
            if not acc_ret:
                raise ApiError("حساب الأرباح المحتجزة (3104) غير موجود")

            closing_lines = []
            total_dr = 0
            total_cr = 0
            for r in rows:
                dr = int(r["dr"] or 0)
                cr = int(r["cr"] or 0)
                net = dr - cr
                if net > 0:
                    closing_lines.append({"account_id": r["id"], "debit": 0, "credit": net, "memo": f"إقفال حساب {r['name']}"})
                    total_cr += net
                elif net < 0:
                    closing_lines.append({"account_id": r["id"], "debit": -net, "credit": 0, "memo": f"إقفال حساب {r['name']}"})
                    total_dr += (-net)

            closing_entry_id = None
            diff = total_dr - total_cr
            if closing_lines:
                if diff > 0:
                    closing_lines.append({"account_id": acc_ret["id"], "debit": 0, "credit": diff, "memo": f"صافي ربح العام {fy['name']} مرحل للأرباح المحتجزة"})
                elif diff < 0:
                    closing_lines.append({"account_id": acc_ret["id"], "debit": -diff, "credit": 0, "memo": f"صافي خسارة العام {fy['name']} مرحلة للأرباح المحتجزة"})
                je = erp_hooks.post_journal_entry(
                    conn,
                    memo=f"قيد إقفال السنة المالية ({fy['name']})",
                    lines=closing_lines,
                    entry_date=fy["end_date"],
                    kind="closing",
                    source_module="accounting",
                    source_table="fiscal_years",
                    source_id=fy["id"],
                    ref=f"CLS-{fy['name']}",
                    user_id=u["id"],
                    strict_closed_check=False,
                )
                closing_entry_id = je["entry_id"]

            now_ts = db.now()
            conn.execute(
                "UPDATE fiscal_periods SET status='closed', closed_at=?, closed_by=? WHERE fiscal_year_id=?",
                (now_ts, u["id"], fy["id"]),
            )
            conn.execute(
                "UPDATE fiscal_years SET status='closed', closed_at=?, closing_entry_id=? WHERE id=?",
                (now_ts, closing_entry_id, fy["id"]),
            )
            return {"year_id": fy["id"], "name": fy["name"], "status": "closed", "closing_entry_id": closing_entry_id, "net_profit_closed": diff}

    # ---------------------------------------------------------- معالج الترصيد الافتتاحي (Onboarding & Backfill Wizard)
    def accounting_opening_preview(self):
        """حساب الأرصدة التشغيلية الحالية من قاعدة البيانات لمعالج الترصيد الافتتاحي مع التحقق من وجود قيد افتتاحي سابق."""
        self._perm_any("accounting_journal_manual", "accounting_coa_view")
        with db.connect() as conn:
            inv_reg = conn.execute(
                "SELECT COALESCE(SUM(CASE WHEN qty > 0 THEN qty * cost ELSE 0 END), 0) FROM products WHERE active=1 AND sku NOT LIKE 'USED-%'"
            ).fetchone()[0]
            inv_used = conn.execute(
                "SELECT COALESCE(SUM(CASE WHEN qty > 0 THEN qty * cost ELSE 0 END), 0) FROM products WHERE active=1 AND sku LIKE 'USED-%'"
            ).fetchone()[0]
            inst_rem = conn.execute(
                "SELECT COALESCE(SUM(remaining_total), 0) FROM installment_plans WHERE status='active'"
            ).fetchone()[0]
            total_cust_debt = conn.execute(
                "SELECT COALESCE(SUM(debt), 0) FROM customers WHERE debt > 0"
            ).fetchone()[0]
            ar_customers = max(0, int(total_cust_debt) - int(inst_rem))
            ap_suppliers = conn.execute(
                "SELECT COALESCE(SUM(balance), 0) FROM suppliers WHERE active=1 AND balance > 0"
            ).fetchone()[0]
            op_row = conn.execute(
                "SELECT id, entry_no, entry_date, total_debit, created_at FROM journal_entries WHERE kind='opening' AND status='posted' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            return {
                "inventory_value": int(inv_reg or 0),
                "used_inventory_value": int(inv_used or 0),
                "ar_customers": int(ar_customers or 0),
                "ar_installments": int(inst_rem or 0),
                "ap_suppliers": int(ap_suppliers or 0),
                "has_opening_entry": bool(op_row),
                "opening_entry": dict(op_row) if op_row else None,
            }

    def accounting_opening_apply(self, cash_main=0, cash_pos=0, wallet_main=0, bank_main=0, entry_date=None, notes=None):
        """إنشاء قيد افتتاحي متوازن 100% لمرة واحدة فقط (يرفض التكرار إذا وُجد قيد افتتاحي مرحّل مسبقاً)."""
        u = self._perm("accounting_journal_manual")
        prev = self.accounting_opening_preview()
        if prev.get("has_opening_entry") and prev.get("opening_entry"):
            op_info = prev["opening_entry"]
            raise ApiError(
                f"تم تنفيذ معالج الترصيد الافتتاحي مسبقاً بموجب القيد رقم ({op_info['entry_no']}) بتاريخ ({op_info['entry_date']}) — لا يمكن تكرار العملية لمنع ازدواج الأرصدة (إذا أردت إعادة الترصيد اعكس القيد الافتتاحي السابق أولاً)"
            )

        c_main = max(0, _money(cash_main, 0))
        c_pos = max(0, _money(cash_pos, 0))
        w_main = max(0, _money(wallet_main, 0))
        b_main = max(0, _money(bank_main, 0))

        with db.connect() as conn:
            lines = []

            def _add_role(role_k, fallback_c, dr_val, cr_val, lbl):
                if dr_val <= 0 and cr_val <= 0:
                    return
                acc = erp_hooks.get_account_by_role(conn, role_k, fallback_c)
                if acc:
                    lines.append({"account_id": acc["id"], "debit": dr_val, "credit": cr_val, "memo": lbl})

            _add_role("cash_main", "110101", c_main, 0, "رصيد افتتاحي — الخزنة الرئيسية")
            _add_role("cash_pos", "110102", c_pos, 0, "رصيد افتتاحي — درج الكاشير")
            _add_role("wallet_main", "110201", w_main, 0, "رصيد افتتاحي — المحفظة الإلكترونية")
            _add_role("bank_main", "110202", b_main, 0, "رصيد افتتاحي — البنك / إنستا باي")
            _add_role("ar_customers", "1103", prev["ar_customers"], 0, "رصيد افتتاحي — ذمم العملاء")
            _add_role("ar_installments", "1104", prev["ar_installments"], 0, "رصيد افتتاحي — ذمم الأقساط")
            _add_role("inventory", "1105", prev["inventory_value"], 0, "رصيد افتتاحي — المخزون السلعي")
            _add_role("used_inventory", "1106", prev["used_inventory_value"], 0, "رصيد افتتاحي — مخزون المستعمل")
            _add_role("ap_suppliers", "2101", 0, prev["ap_suppliers"], "رصيد افتتاحي — ذمم الموردين")

            tot_dr = sum(x["debit"] for x in lines)
            tot_cr = sum(x["credit"] for x in lines)
            if tot_dr == 0 and tot_cr == 0:
                raise ApiError("لا توجد أرصدة موجبة لإنشاء القيد الافتتاحي")

            diff = tot_dr - tot_cr
            acc_cap = erp_hooks.get_account_by_role(conn, "capital", "3101")
            if not acc_cap:
                raise ApiError("حساب رأس المال (3101) غير موجود")
            if diff > 0:
                lines.append({"account_id": acc_cap["id"], "debit": 0, "credit": diff, "memo": "صافي رأس المال الافتتاحي"})
            elif diff < 0:
                lines.append({"account_id": acc_cap["id"], "debit": -diff, "credit": 0, "memo": "تسوية رأس المال الافتتاحي"})

            je = erp_hooks.post_journal_entry(
                conn,
                memo=(notes or "").strip() or "القيد الافتتاحي للأرصدة التشغيلية والمالية",
                lines=lines,
                entry_date=(entry_date or db.now()[:10]).strip()[:10],
                kind="opening",
                source_module="accounting",
                source_table="opening_wizard",
                ref="OPEN-ERP",
                user_id=u["id"],
                strict_closed_check=False,
            )
        return self.journal_entry_get(id=je["entry_id"])

    # ---------------------------------------------------------- قواعد الترحيل المحاسبي
    def accounting_posting_rules_get(self):
        self._perm_any("accounting_coa_view", "accounting_journal_manual")
        with db.connect() as conn:
            rows = conn.execute(
                """SELECT r.*, a.code AS account_code, a.name AS account_name
                   FROM accounting_posting_rules r
                   JOIN accounts a ON a.id = r.account_id
                   ORDER BY r.rule_key ASC"""
            ).fetchall()
            return [dict(r) for r in rows]

    def accounting_posting_rules_save(self, rules):
        self._perm("accounting_journal_manual")
        if not isinstance(rules, dict):
            raise ApiError("صيغة قواعد الترحيل غير صالحة")
        with db.connect() as conn:
            now_ts = db.now()
            for r_key, acc_id in rules.items():
                aid = _int(acc_id)
                acc = conn.execute("SELECT id, is_group FROM accounts WHERE id=?", (aid,)).fetchone()
                if not acc or acc["is_group"]:
                    raise ApiError("يجب ربط القاعدة بحساب فرعي صالح")
                conn.execute(
                    "UPDATE accounting_posting_rules SET account_id=?, updated_at=? WHERE rule_key=?",
                    (aid, now_ts, str(r_key)),
                )
        return self.accounting_posting_rules_get()
