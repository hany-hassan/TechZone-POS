"""التقارير المالية والإدارية التحليلية الشاملة وحركة المخزون والمديونيات والأرباح والخسائر."""
import base64
import csv
import datetime
import io
import json
import os
import pathlib
import sqlite3
import subprocess
import sys
import time
import urllib.parse
import webbrowser
import zipfile
from decimal import Decimal, ROUND_HALF_UP
from xml.sax.saxutils import escape as _xml_escape

import db
import erp_hooks
from api_common import (
    ApiError,
    _FALLBACK_JPEG,
    _LOGIN_ATTEMPTS,
    _STATE,
    _customer_debt_summary,
    _customers_enriched_cte,
    _find_whatsapp_hwnd,
    _fmt_money,
    _format_doc_seq,
    _int,
    _jpeg_to_pdf_bytes,
    _money,
    _upsert_customer,
    _validate_image_data_url,
    _win32_auto_paste_into_whatsapp,
    _win32_copy_pdf_to_clipboard,
)


def _build_native_xlsx_bytes(sheets_data: list[tuple[str, list[list]]]) -> bytes:
    """بناء ملف Excel (.xlsx) قياسي متعدد الأوراق (Multi-Sheet OpenXML) بالاكتفاء بالمكتبة القياسية بدون مكاتب خارجية."""
    buf = io.BytesIO()
    clean_sheets = []
    for idx, (raw_name, rows) in enumerate(sheets_data, start=1):
        name = "".join(ch for ch in str(raw_name or f"Sheet{idx}") if ch not in r"[]:*?/\\").strip()[:31] or f"Sheet{idx}"
        clean_sheets.append((idx, name, rows or []))

    def _col_letter(col_idx: int) -> str:
        res = ""
        n = col_idx
        while n > 0:
            n, rem = divmod(n - 1, 26)
            res = chr(65 + rem) + res
        return res or "A"

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        overrides = "".join(
            f'<Override PartName="/xl/worksheets/sheet{idx}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            for idx, _, _ in clean_sheets
        )
        zf.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            f"{overrides}</Types>",
        )
        zf.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>",
        )
        sheet_tags = "".join(
            f'<sheet name="{_xml_escape(name)}" sheetId="{idx}" r:id="rId{idx}"/>'
            for idx, name, _ in clean_sheets
        )
        zf.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f"<sheets>{sheet_tags}</sheets></workbook>",
        )
        wb_rels = "".join(
            f'<Relationship Id="rId{idx}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{idx}.xml"/>'
            for idx, _, _ in clean_sheets
        )
        styles_rid = len(clean_sheets) + 1
        zf.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'{wb_rels}<Relationship Id="rId{styles_rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            "</Relationships>",
        )
        zf.writestr(
            "xl/styles.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<fonts count="2">'
            '<font><sz val="11"/><name val="Cairo"/></font>'
            '<font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Cairo"/></font>'
            "</fonts>"
            '<fills count="3">'
            '<fill><patternFill patternType="none"/></fill>'
            '<fill><patternFill patternType="gray125"/></fill>'
            '<fill><patternFill patternType="solid"><fgColor rgb="FF0E6BA8"/><bgColor indexed="64"/></patternFill></fill>'
            "</fills>"
            '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
            '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
            '<cellXfs count="2">'
            '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
            '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>'
            "</cellXfs>"
            "</styleSheet>",
        )

        for idx, _, rows in clean_sheets:
            row_xml_parts = []
            for r_i, row in enumerate(rows, start=1):
                cells_xml = []
                style_attr = ' s="1"' if r_i == 1 else ""
                for c_i, val in enumerate(row, start=1):
                    ref = f"{_col_letter(c_i)}{r_i}"
                    if isinstance(val, (int, float, Decimal)) and not isinstance(val, bool):
                        cells_xml.append(f'<c r="{ref}"{style_attr}><v>{val}</v></c>')
                    else:
                        txt = _xml_escape(str(val if val is not None else ""))
                        cells_xml.append(f'<c r="{ref}" t="inlineStr"{style_attr}><is><t>{txt}</t></is></c>')
                row_xml_parts.append(f'<row r="{r_i}">{"".join(cells_xml)}</row>')
            sheet_xml = (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                '<sheetViews><sheetView rightToLeft="1" workbookViewId="0"/></sheetViews>'
                f'<sheetData>{"".join(row_xml_parts)}</sheetData>'
                "</worksheet>"
            )
            zf.writestr(f"xl/worksheets/sheet{idx}.xml", sheet_xml)

    return buf.getvalue()


class ReportsMixin:
    # ---------------------------------------------------------- تقارير أساسية وتقليدية
    def _range(self, conn, date=None, month=None, date_from=None, date_to=None):
        df = (date_from or "").strip()
        dt = (date_to or "").strip()
        if df or dt:
            clauses, args = [], []
            if df:
                clauses.append("created_at >= ?")
                args.append(f"{df} 00:00:00")
            if dt:
                clauses.append("created_at <= ?")
                args.append(f"{dt} 23:59:59")
            return " AND ".join(clauses), args
        if date:
            return "created_at LIKE ?", [f"{date}%"]
        if month:
            y, m = _int(month.get("year")), _int(month.get("month"))
            if not (1 <= m <= 12 and 1900 <= y <= 2999):
                raise ApiError("شهر/سنة غير صالح")
            lo = f"{y:04d}-{m:02d}-01"
            hi = (datetime.date(y, m, 1) + datetime.timedelta(days=32)).replace(day=1).strftime("%Y-%m-%d")
            return "created_at >= ? AND created_at < ?", [lo, hi]
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        return "created_at LIKE ?", [f"{today}%"]

    def _period_stats(self, conn, where, args):
        s = conn.execute(
            f"SELECT COUNT(*) n, COALESCE(SUM(subtotal),0) sub, COALESCE(SUM(discount),0) dis, COALESCE(SUM(tax),0) tax, COALESCE(SUM(total),0) tot FROM sales WHERE {where}",
            args,
        ).fetchone()
        ret = conn.execute(
            f"SELECT COUNT(*) n, COALESCE(SUM(total),0) tot FROM sale_returns WHERE {where}", args
        ).fetchone()
        s_where = where.replace("created_at", "s.created_at")
        pays = {r["method"]: r["t"] for r in conn.execute(
            f"""SELECT p.method, COALESCE(SUM(p.amount),0) t FROM payments p
                JOIN sales s ON s.id=p.sale_id WHERE {s_where} GROUP BY p.method""", args,
        ).fetchall()}
        vouchers = conn.execute(
            f"SELECT COUNT(*) n, COALESCE(SUM(amount),0) tot FROM customer_payments WHERE {where}", args
        ).fetchone()
        rp = conn.execute(
            f"""SELECT COUNT(*) n, COALESCE(SUM(CASE WHEN status='delivered' THEN 1 ELSE 0 END),0) done,
                       COALESCE(SUM(CASE WHEN status='delivered' THEN cost ELSE 0 END),0) rev
                FROM repairs WHERE {where}""",
            args,
        ).fetchone()
        return {
            "sales": {"count": s["n"], "subtotal": s["sub"], "discount": s["dis"], "tax": s["tax"], "total": s["tot"], "net": max(0, s["tot"] - ret["tot"])},
            "returns": {"count": ret["n"], "total": ret["tot"]},
            "payments": pays,
            "vouchers": {"count": vouchers["n"], "total": vouchers["tot"]},
            "repairs": {"count": rp["n"], "delivered": rp["done"], "revenue": rp["rev"]},
        }

    def report_daily(self, date=None, date_from=None, date_to=None):
        self._perm("reports_sales_view")
        with db.connect() as conn:
            if date_from or date_to:
                where, args = self._range(conn, date_from=date_from, date_to=date_to)
            else:
                d = date or datetime.datetime.now().strftime("%Y-%m-%d")
                where, args = self._range(conn, date=d)
            return self._period_stats(conn, where, args)

    def report_monthly(self, year, month):
        self._perm("reports_sales_view")
        with db.connect() as conn:
            where, args = self._range(conn, month={"year": year, "month": month})
            return self._period_stats(conn, where, args)

    def report_top(self, date_from=None, date_to=None, limit=10):
        self._perm("reports_sales_view")
        limit = _int(limit, 10)
        where, args = ["1=1"], []
        if date_from:
            where.append("s.created_at >= ?")
            args.append(f"{date_from} 00:00:00")
        if date_to:
            where.append("s.created_at <= ?")
            args.append(f"{date_to} 23:59:59")
        with db.connect() as conn:
            rows = conn.execute(
                f"""SELECT p.name, p.sku,
                           SUM(i.qty - COALESCE((SELECT SUM(ri.qty) FROM sale_return_items ri WHERE ri.sale_item_id=i.id), 0)) AS sold_qty,
                           SUM(i.line_total - COALESCE((SELECT SUM(ri.amount) FROM sale_return_items ri WHERE ri.sale_item_id=i.id), 0)) AS total
                    FROM sale_items i JOIN sales s ON s.id=i.sale_id JOIN products p ON p.id=i.product_id
                    WHERE {' AND '.join(where)} GROUP BY p.id HAVING sold_qty > 0 ORDER BY sold_qty DESC LIMIT ?""",
                args + [limit],
            ).fetchall()
            return [{"name": r["name"], "sku": r["sku"], "qty": r["sold_qty"], "total": r["total"]} for r in rows]

    def report_profit(self, date_from=None, date_to=None):
        self._perm("reports_profit_view")
        where, args = ["1=1"], []
        if date_from:
            where.append("s.created_at >= ?")
            args.append(f"{date_from} 00:00:00")
        if date_to:
            where.append("s.created_at <= ?")
            args.append(f"{date_to} 23:59:59")
        with db.connect() as conn:
            goods = conn.execute(
                f"""SELECT COALESCE(SUM(
                        (i.line_total - COALESCE((SELECT SUM(ri.amount) FROM sale_return_items ri WHERE ri.sale_item_id=i.id), 0))
                        - COALESCE(NULLIF(i.cost_unit, 0), p.cost, 0) * (i.qty - COALESCE((SELECT SUM(ri.qty) FROM sale_return_items ri WHERE ri.sale_item_id=i.id), 0))
                    ),0) profit,
                    COALESCE(SUM(
                        i.line_total - COALESCE((SELECT SUM(ri.amount) FROM sale_return_items ri WHERE ri.sale_item_id=i.id), 0)
                    ),0) revenue
                    FROM sale_items i JOIN sales s ON s.id=i.sale_id JOIN products p ON p.id=i.product_id
                    WHERE {' AND '.join(where)}""",
                args,
            ).fetchone()
            rep_where, rep_args = "1=1", []
            if date_from:
                rep_where += " AND r.created_at >= ?"
                rep_args.append(f"{date_from} 00:00:00")
            if date_to:
                rep_where += " AND r.created_at <= ?"
                rep_args.append(f"{date_to} 23:59:59")
            rep = conn.execute(
                f"""SELECT COALESCE(SUM(CASE WHEN r.status='delivered' THEN r.cost ELSE 0 END),0) rev,
                           COALESCE((SELECT SUM(lp.line_total) FROM repair_parts lp
                                     JOIN repairs r2 ON r2.id=lp.repair_id WHERE r2.status='delivered' AND {rep_where.replace('r.', 'r2.')}),0) parts
                    FROM repairs r WHERE {rep_where}""",
                rep_args * 2,
            ).fetchone()
            return {
                "goods_revenue": goods["revenue"],
                "goods_profit": goods["profit"],
                "repair_revenue": rep["rev"],
                "repair_parts_cost": rep["parts"],
                "repair_profit": rep["rev"] - rep["parts"],
            }

    def report_low(self):
        self._perm_any("inventory_view", "reports_movements_view")
        with db.connect() as conn:
            rows = conn.execute(
                """SELECT p.id, p.name, p.sku, p.qty, p.min_qty, p.cost, p.price, c.name category
                   FROM products p LEFT JOIN categories c ON c.id=p.category_id
                   WHERE p.active=1 AND p.qty<=p.min_qty ORDER BY p.qty ASC, p.name"""
            ).fetchall()
            return [dict(r) for r in rows]

    def report_movements(self, limit=100):
        self._perm("reports_movements_view")
        limit = _int(limit, 100)
        with db.connect() as conn:
            rows = conn.execute(
                """SELECT m.*, p.name product_name, u.name user_name
                   FROM stock_movements m
                   JOIN products p ON p.id=m.product_id
                   LEFT JOIN users u ON u.id=m.user_id
                   ORDER BY m.id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def stock_stats(self):
        self._perm("inventory_view")
        with db.connect() as conn:
            n = conn.execute("SELECT COUNT(*) c FROM products WHERE active=1").fetchone()["c"]
            val = conn.execute("SELECT COALESCE(SUM(CASE WHEN qty>0 THEN qty*price ELSE 0 END),0) v FROM products WHERE active=1").fetchone()["v"]
            total_qty = conn.execute("SELECT COALESCE(SUM(CASE WHEN qty>0 THEN qty ELSE 0 END),0) q FROM products WHERE active=1").fetchone()["q"]
            in_stock = conn.execute("SELECT COUNT(*) c FROM products WHERE active=1 AND qty>0").fetchone()["c"]
            low = conn.execute("SELECT COUNT(*) c FROM products WHERE active=1 AND qty>0 AND qty<=min_qty").fetchone()["c"]
            out = conn.execute("SELECT COUNT(*) c FROM products WHERE active=1 AND qty<=0").fetchone()["c"]
            return {"count": n, "value": val, "total_qty": total_qty, "in_stock": in_stock, "low": low, "out": out}

    # ---------------------------------------------------------- المركز المالي والتحليلي الشامل (ERP Comprehensive Reports)
    def report_comprehensive(self, date_from=None, date_to=None):
        """تقرير مالي وتشغيلي شامل ومفصل يغطي الأرباح والخسائر، الفواتير، الأصناف، مديونيات العملاء والأقساط، الموردين، الخزائن، والورديات، والمخزون."""
        self._perm_any("reports_sales_view", "reports_profit_view", "reports_shifts_view", "reports_movements_view")
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        df = (date_from or today).strip()[:10]
        dt = (date_to or today).strip()[:10]
        ts_from = f"{df} 00:00:00"
        ts_to = f"{dt} 23:59:59"

        with db.connect() as conn:
            has_purchases = erp_hooks.is_module_active(self, conn, "purchases")
            has_accounting = erp_hooks.is_module_active(self, conn, "accounting")
            has_installments = erp_hooks.is_module_active(self, conn, "installments")
            has_repair = erp_hooks.is_module_active(self, conn, "repair")
            has_buy_used = erp_hooks.is_module_active(self, conn, "buy_used")

            # 1) ملخص المبيعات والمرتجعات وتكلفة البضاعة المباعة (P&L)
            s_row = conn.execute(
                """SELECT COUNT(*) n, COALESCE(SUM(subtotal),0) sub, COALESCE(SUM(discount),0) dis,
                          COALESCE(SUM(tax),0) tax, COALESCE(SUM(total),0) tot
                   FROM sales WHERE created_at >= ? AND created_at <= ?""",
                (ts_from, ts_to),
            ).fetchone()
            ret_row = conn.execute(
                """SELECT COUNT(*) n, COALESCE(SUM(total),0) tot
                   FROM sale_returns WHERE created_at >= ? AND created_at <= ?""",
                (ts_from, ts_to),
            ).fetchone()

            # ربحية الفواتير التفصيلية
            inv_rows = conn.execute(
                """SELECT s.id, s.invoice_no, s.created_at, s.customer_name, s.customer_phone,
                          s.subtotal, s.discount, s.tax, s.total, s.status,
                          COALESCE((SELECT SUM(sr.total) FROM sale_returns sr WHERE sr.sale_id=s.id), 0) AS returned_total,
                          COALESCE((SELECT SUM(
                              COALESCE(NULLIF(si.cost_unit, 0), p.cost, 0) *
                              MAX(0, si.qty - COALESCE((SELECT SUM(ri.qty) FROM sale_return_items ri WHERE ri.sale_item_id=si.id), 0))
                          ) FROM sale_items si LEFT JOIN products p ON p.id=si.product_id WHERE si.sale_id=s.id), 0) AS cogs_total
                   FROM sales s
                   WHERE s.created_at >= ? AND s.created_at <= ?
                   ORDER BY s.id DESC LIMIT 300""",
                (ts_from, ts_to),
            ).fetchall()

            invoices_profit_list = []
            for r in inv_rows:
                d = dict(r)
                net_inv_rev = max(0, int(d["total"] or 0) - int(d["returned_total"] or 0) - int(d["tax"] or 0))
                cogs = int(d["cogs_total"] or 0)
                d["net_revenue_ex_tax"] = net_inv_rev
                d["profit"] = net_inv_rev - cogs
                invoices_profit_list.append(d)

            exact_cogs_row = conn.execute(
                """SELECT COALESCE(SUM(
                       COALESCE(NULLIF(si.cost_unit, 0), p.cost, 0) *
                       MAX(0, si.qty - COALESCE((SELECT SUM(ri.qty) FROM sale_return_items ri WHERE ri.sale_item_id=si.id), 0))
                   ), 0) AS cogs
                   FROM sale_items si
                   JOIN sales s ON s.id = si.sale_id
                   LEFT JOIN products p ON p.id = si.product_id
                   WHERE s.created_at >= ? AND s.created_at <= ?""",
                (ts_from, ts_to),
            ).fetchone()
            total_cogs_goods = int(exact_cogs_row["cogs"] or 0)

            # ربحية الأصناف المباعة التفصيلية
            item_rows = conn.execute(
                """SELECT p.id AS product_id, p.sku, p.name,
                          SUM(si.qty) AS gross_qty,
                          SUM(COALESCE((SELECT SUM(ri.qty) FROM sale_return_items ri WHERE ri.sale_item_id=si.id), 0)) AS returned_qty,
                          SUM(si.qty - COALESCE((SELECT SUM(ri.qty) FROM sale_return_items ri WHERE ri.sale_item_id=si.id), 0)) AS net_qty,
                          SUM(si.line_total - COALESCE((SELECT SUM(ri.amount) FROM sale_return_items ri WHERE ri.sale_item_id=si.id), 0)) AS net_revenue,
                          SUM(COALESCE(NULLIF(si.cost_unit, 0), p.cost, 0) *
                              MAX(0, si.qty - COALESCE((SELECT SUM(ri.qty) FROM sale_return_items ri WHERE ri.sale_item_id=si.id), 0))) AS cost_total
                   FROM sale_items si
                   JOIN sales s ON s.id = si.sale_id
                   JOIN products p ON p.id = si.product_id
                   WHERE s.created_at >= ? AND s.created_at <= ?
                   GROUP BY p.id
                   HAVING net_qty > 0
                   ORDER BY net_revenue DESC LIMIT 200""",
                (ts_from, ts_to),
            ).fetchall()
            items_profit_list = []
            for r in item_rows:
                d = dict(r)
                rev = int(d["net_revenue"] or 0)
                cst = int(d["cost_total"] or 0)
                prf = rev - cst
                d["profit"] = prf
                d["margin_pct"] = round((prf / rev) * 100, 1) if rev > 0 else 0.0
                items_profit_list.append(d)

            # الصيانة والأقساط والمصروفات التشغيلية
            rep_row = conn.execute(
                """SELECT COUNT(*) total_cnt,
                          COALESCE(SUM(CASE WHEN status='delivered' THEN 1 ELSE 0 END), 0) delivered_cnt,
                          COALESCE(SUM(CASE WHEN status='delivered' THEN cost ELSE 0 END), 0) rev,
                          COALESCE((SELECT SUM(COALESCE(NULLIF(lp.cost_unit,0)*lp.qty, lp.line_total, 0))
                                    FROM repair_parts lp JOIN repairs r2 ON r2.id=lp.repair_id
                                    WHERE r2.status='delivered' AND r2.created_at >= ? AND r2.created_at <= ?), 0) parts_cost
                   FROM repairs WHERE created_at >= ? AND created_at <= ?""",
                (ts_from, ts_to, ts_from, ts_to),
            ).fetchone()

            inst_fee_row = conn.execute(
                """SELECT COUNT(*) cnt, COALESCE(SUM(fee_amount), 0) fees
                   FROM installment_plans WHERE created_at >= ? AND created_at <= ?""",
                (ts_from, ts_to),
            ).fetchone()

            used_row = conn.execute(
                """SELECT COUNT(*) cnt, COALESCE(SUM(buy_price), 0) tot
                   FROM used_device_purchases WHERE created_at >= ? AND created_at <= ?""",
                (ts_from, ts_to),
            ).fetchone()

            expenses_by_category = []
            expenses_list = []
            operating_expenses_total = 0
            if has_accounting:
                exp_cat_rows = conn.execute(
                    """SELECT ec.name AS category_name, COUNT(e.id) AS count, COALESCE(SUM(e.amount), 0) AS total
                       FROM expenses e
                       LEFT JOIN expense_categories ec ON ec.id = e.category_id
                       WHERE e.expense_date >= ? AND e.expense_date <= ?
                       GROUP BY e.category_id
                       ORDER BY total DESC""",
                    (df, dt),
                ).fetchall()
                expenses_by_category = [dict(r) for r in exp_cat_rows]
                operating_expenses_total = sum(int(x["total"] or 0) for x in expenses_by_category)
                exp_rows = conn.execute(
                    """SELECT e.*, ec.name AS category_name, t.name AS treasury_name
                       FROM expenses e
                       LEFT JOIN expense_categories ec ON ec.id = e.category_id
                       LEFT JOIN treasury_accounts t ON t.id = e.treasury_id
                       WHERE e.expense_date >= ? AND e.expense_date <= ?
                       ORDER BY e.id DESC LIMIT 200""",
                    (df, dt),
                ).fetchall()
                expenses_list = [dict(r) for r in exp_rows]

            gross_sales = int(s_row["sub"] or 0)
            discounts = int(s_row["dis"] or 0)
            tax_collected = int(s_row["tax"] or 0)
            invoices_total = int(s_row["tot"] or 0)
            returns_total = int(ret_row["tot"] or 0)
            net_sales_with_tax = max(0, invoices_total - returns_total)
            net_sales_ex_tax = max(0, gross_sales - discounts - returns_total)
            gross_profit_goods = net_sales_ex_tax - total_cogs_goods
            repair_rev = int(rep_row["rev"] or 0)
            repair_parts = int(rep_row["parts_cost"] or 0)
            repair_profit = repair_rev - repair_parts
            inst_fees = int(inst_fee_row["fees"] or 0)
            total_gross_profit = gross_profit_goods + repair_profit + inst_fees
            net_profit = total_gross_profit - operating_expenses_total

            # 2) تفاصيل مديونيات العملاء والأقساط وسندات القبض
            debt_cust_rows = conn.execute(
                """SELECT c.id, c.name, c.phone, '' AS address, '' AS notes, 0 AS credit_limit,
                          (SELECT COUNT(*) FROM sales s WHERE s.customer_id=c.id) AS invoices_count,
                          c.total_purchases, c.paid_total AS total_paid, c.debt AS balance
                   FROM customers c
                   WHERE c.debt > 0
                   ORDER BY c.debt DESC, c.name ASC LIMIT 300"""
            ).fetchall()
            customers_debt_list = [dict(r) for r in debt_cust_rows]
            total_cust_debt = int(conn.execute("SELECT COALESCE(SUM(debt),0) FROM customers WHERE debt>0").fetchone()[0])
            indebted_cust_cnt = int(conn.execute("SELECT COUNT(*) FROM customers WHERE debt>0").fetchone()[0])

            today_str = datetime.datetime.now().strftime("%Y-%m-%d")
            inst_rows = conn.execute(
                """SELECT p.*,
                          p.plan_no AS contract_no,
                          p.financed_total AS total_amount,
                          p.remaining_total AS remaining_amount,
                          c.name AS customer_name,
                          c.phone AS customer_phone,
                          COALESCE((SELECT COUNT(*) FROM installment_items ii WHERE ii.plan_id=p.id AND ii.status='paid'), 0) AS paid_count,
                          COALESCE((SELECT COUNT(*) FROM installment_items ii WHERE ii.plan_id=p.id), 0) AS total_count,
                          COALESCE((SELECT COUNT(*) FROM installment_items ii WHERE ii.plan_id=p.id AND ii.status!='paid' AND ii.due_date < ?), 0) AS overdue_count,
                          COALESCE((SELECT SUM(ii.amount - ii.paid_amount) FROM installment_items ii WHERE ii.plan_id=p.id AND ii.status!='paid' AND ii.due_date < ?), 0) AS overdue_amount,
                          (SELECT MIN(ii.due_date) FROM installment_items ii WHERE ii.plan_id=p.id AND ii.status!='paid') AS next_due_date
                   FROM installment_plans p
                   LEFT JOIN customers c ON c.id = p.customer_id
                   WHERE p.status = 'active' AND p.remaining_total > 0
                   ORDER BY overdue_count DESC, p.remaining_total DESC LIMIT 300""",
                (today_str, today_str),
            ).fetchall()
            installments_list = [dict(r) for r in inst_rows]
            inst_remaining_total = sum(int(x["remaining_amount"] or 0) for x in installments_list)
            inst_overdue_total = sum(int(x["overdue_amount"] or 0) for x in installments_list)
            inst_overdue_count = sum(1 for x in installments_list if int(x["overdue_count"] or 0) > 0)

            voucher_rows = conn.execute(
                """SELECT cp.*, cp.notes AS note, c.name AS customer_name, c.phone AS customer_phone
                   FROM customer_payments cp
                   LEFT JOIN customers c ON c.id = cp.customer_id
                   WHERE cp.created_at >= ? AND cp.created_at <= ?
                   ORDER BY cp.id DESC LIMIT 250""",
                (ts_from, ts_to),
            ).fetchall()
            vouchers_list = [dict(r) for r in voucher_rows]
            vouchers_total = sum(int(x["amount"] or 0) for x in vouchers_list)

            inst_paid_period = conn.execute(
                """SELECT COALESCE(SUM(amount), 0) tot,
                          COALESCE(SUM(CASE WHEN method='wallet' THEN amount ELSE 0 END), 0) wallet_tot,
                          COALESCE(SUM(CASE WHEN method!='wallet' THEN amount ELSE 0 END), 0) cash_tot
                   FROM installment_payments
                   WHERE created_at >= ? AND created_at <= ?""",
                (ts_from, ts_to),
            ).fetchone()

            # 3) تفاصيل الموردين وفواتير المشتريات وسندات الصرف للموردين
            suppliers_debt_list = []
            purchases_list = []
            supplier_payments_list = []
            total_suppliers_debt = 0
            period_purchases_total = 0
            period_purchases_returns = 0
            period_supplier_payments_total = 0

            if has_purchases:
                sup_rows = conn.execute(
                    """SELECT s.*, s.company_name AS company,
                              (SELECT COUNT(*) FROM purchases p WHERE p.supplier_id=s.id AND p.status='posted') AS bills_count
                       FROM suppliers s
                       WHERE s.active=1 AND s.balance != 0
                       ORDER BY s.balance DESC LIMIT 300"""
                ).fetchall()
                suppliers_debt_list = [dict(r) for r in sup_rows]
                total_suppliers_debt = int(
                    conn.execute("SELECT COALESCE(SUM(balance),0) s FROM suppliers WHERE active=1 AND balance>0").fetchone()["s"]
                )
                pur_rows = conn.execute(
                    """SELECT p.*, p.purchase_no AS bill_no, p.invoice_date AS bill_date,
                              MAX(0, p.total - p.paid_amount - p.wht_amount) AS remaining_amount,
                              s.name AS supplier_name, s.phone AS supplier_phone
                       FROM purchases p
                       LEFT JOIN suppliers s ON s.id = p.supplier_id
                       WHERE p.status IN ('posted','partial_return') AND p.invoice_date >= ? AND p.invoice_date <= ?
                       ORDER BY p.id DESC LIMIT 250""",
                    (df, dt),
                ).fetchall()
                purchases_list = [dict(r) for r in pur_rows]
                period_purchases_total = sum(int(x["total"] or 0) for x in purchases_list)

                pr_row = conn.execute(
                    """SELECT COALESCE(SUM(total), 0) tot FROM purchase_returns
                       WHERE created_at >= ? AND created_at <= ?""",
                    (ts_from, ts_to),
                ).fetchone()
                period_purchases_returns = int(pr_row["tot"] or 0)

                sp_rows = conn.execute(
                    """SELECT sp.*, sp.ref AS voucher_no, substr(sp.created_at, 1, 10) AS payment_date,
                              sp.amount AS net_paid, 0 AS wht_amount, s.name AS supplier_name
                       FROM supplier_payments sp
                       LEFT JOIN suppliers s ON s.id = sp.supplier_id
                       WHERE sp.created_at >= ? AND sp.created_at <= ?
                       ORDER BY sp.id DESC LIMIT 250""",
                    (ts_from, ts_to),
                ).fetchall()
                supplier_payments_list = [dict(r) for r in sp_rows]
                period_supplier_payments_total = sum(int(x["amount"] or 0) for x in supplier_payments_list)

            # 4) حركة السيولة والخزائن والورديات
            pays_by_method = {
                r["method"]: int(r["t"] or 0)
                for r in conn.execute(
                    """SELECT p.method, COALESCE(SUM(p.amount),0) t
                       FROM payments p JOIN sales s ON s.id=p.sale_id
                       WHERE s.created_at >= ? AND s.created_at <= ?
                       GROUP BY p.method""",
                    (ts_from, ts_to),
                ).fetchall()
            }
            vouchers_by_method = {
                r["method"]: int(r["t"] or 0)
                for r in conn.execute(
                    """SELECT method, COALESCE(SUM(amount),0) t
                       FROM customer_payments
                       WHERE created_at >= ? AND created_at <= ?
                       GROUP BY method""",
                    (ts_from, ts_to),
                ).fetchall()
            }
            treasuries_list = []
            if has_accounting:
                tr_rows = conn.execute(
                    """SELECT t.*, a.code AS account_code, a.name AS account_name, a.balance AS balance
                       FROM treasury_accounts t
                       JOIN accounts a ON a.id = t.account_id
                       WHERE t.active = 1
                       ORDER BY t.id"""
                ).fetchall()
                treasuries_list = [dict(r) for r in tr_rows]

            shifts_rows = conn.execute(
                """SELECT sh.*, u.name AS user_name,
                          COALESCE((SELECT SUM(p.amount) FROM payments p JOIN sales s ON s.id=p.sale_id
                                    WHERE s.shift_id=sh.id AND p.method='cash'), 0) AS sales_total
                   FROM shifts sh
                   LEFT JOIN users u ON u.id = sh.user_id
                   WHERE sh.opened_at >= ? AND sh.opened_at <= ?
                   ORDER BY sh.id DESC LIMIT 100""",
                (ts_from, ts_to),
            ).fetchall()
            shifts_list = [dict(r) for r in shifts_rows]

            inflow_total = (
                pays_by_method.get("cash", 0)
                + pays_by_method.get("wallet", 0)
                + vouchers_by_method.get("cash", 0)
                + vouchers_by_method.get("wallet", 0)
                + int(inst_paid_period["tot"] or 0)
                + repair_rev
            )
            outflow_total = (
                returns_total
                + period_supplier_payments_total
                + operating_expenses_total
                + int(used_row["tot"] or 0)
            )

            # 5) تقييم المخزون والنواقص وحركة الأصناف
            inv_val = conn.execute(
                """SELECT COUNT(*) active_count,
                          COALESCE(SUM(CASE WHEN qty>0 THEN qty ELSE 0 END), 0) total_units,
                          COALESCE(SUM(CASE WHEN qty>0 THEN qty * cost ELSE 0 END), 0) cost_valuation,
                          COALESCE(SUM(CASE WHEN qty>0 THEN qty * price ELSE 0 END), 0) retail_valuation,
                          COALESCE(SUM(CASE WHEN qty>0 AND qty<=min_qty THEN 1 ELSE 0 END), 0) low_count,
                          COALESCE(SUM(CASE WHEN qty<=0 THEN 1 ELSE 0 END), 0) out_count
                   FROM products WHERE active=1"""
            ).fetchone()
            low_stock_rows = conn.execute(
                """SELECT p.id, p.sku, p.name, p.qty, p.min_qty, p.cost, p.price, c.name AS category
                   FROM products p LEFT JOIN categories c ON c.id = p.category_id
                   WHERE p.active=1 AND p.qty <= p.min_qty
                   ORDER BY p.qty ASC, p.name LIMIT 150"""
            ).fetchall()
            moves_rows = conn.execute(
                """SELECT m.*, p.name AS product_name, p.sku AS product_sku, u.name AS user_name
                   FROM stock_movements m
                   JOIN products p ON p.id = m.product_id
                   LEFT JOIN users u ON u.id = m.user_id
                   WHERE m.created_at >= ? AND m.created_at <= ?
                   ORDER BY m.id DESC LIMIT 150""",
                (ts_from, ts_to),
            ).fetchall()

            return {
                "period": {"date_from": df, "date_to": dt},
                "modules_active": {
                    "purchases": has_purchases,
                    "accounting": has_accounting,
                    "installments": has_installments,
                    "repair": has_repair,
                    "buy_used": has_buy_used,
                },
                "pnl": {
                    "sales_count": int(s_row["n"] or 0),
                    "gross_sales": gross_sales,
                    "discounts": discounts,
                    "tax_collected": tax_collected,
                    "invoices_total": invoices_total,
                    "returns_count": int(ret_row["n"] or 0),
                    "returns_total": returns_total,
                    "net_sales_with_tax": net_sales_with_tax,
                    "net_sales_ex_tax": net_sales_ex_tax,
                    "cogs_goods": total_cogs_goods,
                    "gross_profit_goods": gross_profit_goods,
                    "repairs_count": int(rep_row["total_cnt"] or 0),
                    "repairs_delivered_count": int(rep_row["delivered_cnt"] or 0),
                    "repair_revenue": repair_rev,
                    "repair_parts_cost": repair_parts,
                    "repair_profit": repair_profit,
                    "installments_created_count": int(inst_fee_row["cnt"] or 0),
                    "installment_admin_fees": inst_fees,
                    "used_purchases_count": int(used_row["cnt"] or 0),
                    "used_purchases_total": int(used_row["tot"] or 0),
                    "operating_expenses_total": operating_expenses_total,
                    "expenses_by_category": expenses_by_category,
                    "expenses_list": expenses_list,
                    "total_gross_profit": total_gross_profit,
                    "net_profit": net_profit,
                    "invoices_profit_list": invoices_profit_list,
                    "items_profit_list": items_profit_list,
                },
                "receivables": {
                    "summary": {
                        "total_customers_debt": total_cust_debt,
                        "indebted_customers_count": indebted_cust_cnt,
                        "installments_remaining_total": inst_remaining_total,
                        "overdue_installments_total": inst_overdue_total,
                        "overdue_installments_count": inst_overdue_count,
                        "period_vouchers_total": vouchers_total,
                        "period_vouchers_count": len(vouchers_list),
                        "period_installments_collected": int(inst_paid_period["tot"] or 0),
                    },
                    "customers_debt_list": customers_debt_list,
                    "installments_list": installments_list,
                    "vouchers_list": vouchers_list,
                },
                "payables": {
                    "summary": {
                        "total_suppliers_debt": total_suppliers_debt,
                        "indebted_suppliers_count": len([x for x in suppliers_debt_list if int(x["balance"] or 0) > 0]),
                        "period_purchases_count": len(purchases_list),
                        "period_purchases_total": period_purchases_total,
                        "period_purchases_returns": period_purchases_returns,
                        "period_supplier_payments_total": period_supplier_payments_total,
                    },
                    "suppliers_debt_list": suppliers_debt_list,
                    "purchases_list": purchases_list,
                    "supplier_payments_list": supplier_payments_list,
                },
                "cashflow": {
                    "payments_in": {
                        "cash_sales": pays_by_method.get("cash", 0),
                        "wallet_sales": pays_by_method.get("wallet", 0),
                        "credit_sales": pays_by_method.get("credit", 0),
                        "customer_vouchers_cash": vouchers_by_method.get("cash", 0),
                        "customer_vouchers_wallet": vouchers_by_method.get("wallet", 0),
                        "installments_cash": int(inst_paid_period["cash_tot"] or 0),
                        "installments_wallet": int(inst_paid_period["wallet_tot"] or 0),
                        "repairs_revenue": repair_rev,
                    },
                    "payments_out": {
                        "returns_total": returns_total,
                        "supplier_payments": period_supplier_payments_total,
                        "operating_expenses": operating_expenses_total,
                        "used_device_purchases": int(used_row["tot"] or 0),
                    },
                    "inflow_total": inflow_total,
                    "outflow_total": outflow_total,
                    "net_period_cashflow": inflow_total - outflow_total,
                    "treasuries": treasuries_list,
                    "shifts_list": shifts_list,
                },
                "inventory": {
                    "valuation": {
                        "active_products_count": int(inv_val["active_count"] or 0),
                        "total_units": int(inv_val["total_units"] or 0),
                        "cost_valuation": int(inv_val["cost_valuation"] or 0),
                        "retail_valuation": int(inv_val["retail_valuation"] or 0),
                        "expected_gross_profit": int(inv_val["retail_valuation"] or 0) - int(inv_val["cost_valuation"] or 0),
                        "low_stock_count": int(inv_val["low_count"] or 0),
                        "out_of_stock_count": int(inv_val["out_count"] or 0),
                    },
                    "low_stock_list": [dict(r) for r in low_stock_rows],
                    "movements_list": [dict(r) for r in moves_rows],
                },
            }

    def report_export_excel(self, section="all", date_from=None, date_to=None):
        """تصدير التقرير المالي والتشغيلي الشامل إلى ملف Excel (.xlsx متعدد الأوراق) + CSV وحفظه في مجلد data/reports."""
        comp = self.report_comprehensive(date_from=date_from, date_to=date_to)
        df = comp["period"]["date_from"]
        dt = comp["period"]["date_to"]
        pnl = comp["pnl"]
        rec = comp["receivables"]
        pay = comp["payables"]
        cf = comp["cashflow"]
        inv = comp["inventory"]

        m_val = lambda cents: round(int(cents or 0) / 100.0, 2)

        # ورقة 1: الأرباح والخسائر والفواتير
        sheet_pnl = [
            ["بند قائمة الأرباح والخسائر التفصيلية", "القيمة (ج.م)", "ملاحظات / العدد"],
            ["الفترة من تاريخ", df, f"إلى تاريخ {dt}"],
            ["إجمالي المبيعات (قبل الخصم)", m_val(pnl["gross_sales"]), f"{pnl['sales_count']} فاتورة"],
            ["الخصومات الممنوحة", m_val(pnl["discounts"]), ""],
            ["مردودات ومرتجعات المبيعات", m_val(pnl["returns_total"]), f"{pnl['returns_count']} مرتجع"],
            ["صافي المبيعات (بدون ضريبة)", m_val(pnl["net_sales_ex_tax"]), ""],
            ["ضريبة القيمة المضافة المحصلة", m_val(pnl["tax_collected"]), ""],
            ["تكلفة البضاعة المباعة الفعلية (COGS)", m_val(pnl["cogs_goods"]), ""],
            ["مجمل ربح البضائع", m_val(pnl["gross_profit_goods"]), ""],
            ["إيرادات الصيانة المسلمة", m_val(pnl["repair_revenue"]), f"{pnl['repairs_delivered_count']} جهاز"],
            ["تكلفة قطع غيار الصيانة", m_val(pnl["repair_parts_cost"]), ""],
            ["صافي ربح الصيانة", m_val(pnl["repair_profit"]), ""],
            ["رسوم وفوائد عقود التقسيط الجديدة", m_val(pnl["installment_admin_fees"]), f"{pnl['installments_created_count']} عقد"],
            ["إجمالي مجمل الربح الكلي", m_val(pnl["total_gross_profit"]), ""],
            ["المصروفات التشغيلية والإدارية", m_val(pnl["operating_expenses_total"]), ""],
            ["صافي الربح النهائي للفترة", m_val(pnl["net_profit"]), ""],
            [],
            ["تفاصيل ربحية الفواتير خلال الفترة", "", "", "", "", "", ""],
            ["رقم الفاتورة", "التاريخ", "العميل", "إجمالي الفاتورة", "المرتجع", "تكلفة البضاعة (COGS)", "صافي الربح"],
        ]
        for iv in pnl["invoices_profit_list"]:
            sheet_pnl.append([
                iv["invoice_no"],
                iv["created_at"],
                iv.get("customer_name") or "عميل نقدي",
                m_val(iv["total"]),
                m_val(iv["returned_total"]),
                m_val(iv["cogs_total"]),
                m_val(iv["profit"]),
            ])

        # ورقة 2: ربحية الأصناف المباعة
        sheet_items = [
            ["كود الصنف (SKU)", "اسم الصنف", "الكمية المباعة الصافية", "صافي الإيراد", "إجمالي التكلفة", "صافي الربح", "نسبة الربح %"],
        ]
        for it in pnl["items_profit_list"]:
            sheet_items.append([
                it.get("sku") or "",
                it["name"],
                it["net_qty"],
                m_val(it["net_revenue"]),
                m_val(it["cost_total"]),
                m_val(it["profit"]),
                it["margin_pct"],
            ])

        # ورقة 3: مديونيات العملاء والأقساط والتحصيلات
        sheet_rec = [
            ["ملخص مديونيات العملاء والأقساط", "القيمة (ج.م)", "العدد"],
            ["إجمالي مديونيات الحسابات الجارية للعملاء", m_val(rec["summary"]["total_customers_debt"]), rec["summary"]["indebted_customers_count"]],
            ["إجمالي المتبقي في عقود التقسيط النشطة", m_val(rec["summary"]["installments_remaining_total"]), len(rec["installments_list"])],
            ["إجمالي الأقساط المتأخرة المستحقة فوراً", m_val(rec["summary"]["overdue_installments_total"]), rec["summary"]["overdue_installments_count"]],
            ["سندات القبض المحصلة خلال الفترة", m_val(rec["summary"]["period_vouchers_total"]), rec["summary"]["period_vouchers_count"]],
            ["أقساط محصلة خلال الفترة", m_val(rec["summary"]["period_installments_collected"]), ""],
            [],
            ["كشف العملاء المدينين (الحسابات الآجلة)", "", "", "", "", ""],
            ["اسم العميل", "رقم الهاتف", "العنوان", "عدد الفواتير", "إجمالي المسحوبات", "الرصيد المتبقي (المديونية)"],
        ]
        for c in rec["customers_debt_list"]:
            sheet_rec.append([
                c["name"],
                c.get("phone") or "",
                c.get("address") or "",
                c.get("invoices_count") or 0,
                m_val(c.get("total_purchases") or 0),
                m_val(c.get("balance") or 0),
            ])
        sheet_rec.append([])
        sheet_rec.append(["عقود التقسيط النشطة والمتأخرة", "", "", "", "", ""])
        sheet_rec.append(["رقم العقد", "اسم العميل", "الهاتف", "إجمالي العقد", "المتبقي", "عدد الأقساط المتأخرة", "تاريخ القسط القادم"])
        for ins in rec["installments_list"]:
            sheet_rec.append([
                ins["contract_no"],
                ins["customer_name"],
                ins.get("customer_phone") or "",
                m_val(ins["total_amount"]),
                m_val(ins["remaining_amount"]),
                ins.get("overdue_count") or 0,
                ins.get("next_due_date") or "",
            ])

        # ورقة 4: الموردون والمشتريات
        sheet_pay = [
            ["ملخص مديونيات الموردين والمشتريات", "القيمة (ج.م)", "العدد"],
            ["إجمالي مستحقات الموردين الحالية (AP)", m_val(pay["summary"]["total_suppliers_debt"]), pay["summary"]["indebted_suppliers_count"]],
            ["مشتريات الفترة", m_val(pay["summary"]["period_purchases_total"]), pay["summary"]["period_purchases_count"]],
            ["مرتجعات المشتريات خلال الفترة", m_val(pay["summary"]["period_purchases_returns"]), ""],
            ["سندات الصرف للموردين خلال الفترة", m_val(pay["summary"]["period_supplier_payments_total"]), len(pay["supplier_payments_list"])],
            [],
            ["كشف أرصدة الموردين", "", "", "", ""],
            ["كود المورد", "اسم المورد", "الشركة", "الهاتف", "الرصيد المستحق للمورد"],
        ]
        for sup in pay["suppliers_debt_list"]:
            sheet_pay.append([
                sup.get("code") or "",
                sup["name"],
                sup.get("company") or "",
                sup.get("phone") or "",
                m_val(sup["balance"]),
            ])

        # ورقة 5: السيولة والخزائن والمخزون
        sheet_cf = [
            ["حركة السيولة والخزائن وتقييم المخزون", "القيمة (ج.م)", "ملاحظات"],
            ["إجمالي المقبوضات النقدية والمحافظ بالفترة", m_val(cf["inflow_total"]), ""],
            ["إجمالي المدفوعات والمصروفات بالفترة", m_val(cf["outflow_total"]), ""],
            ["صافي التدفق النقدي للفترة", m_val(cf["net_period_cashflow"]), ""],
            ["قيمة المخزون الحالي بسعر التكلفة", m_val(inv["valuation"]["cost_valuation"]), f"{inv['valuation']['total_units']} قطعة"],
            ["قيمة المخزون الحالي بسعر البيع", m_val(inv["valuation"]["retail_valuation"]), f"{inv['valuation']['active_products_count']} صنف"],
            ["الربح المتوقع من المخزون المتاح", m_val(inv["valuation"]["expected_gross_profit"]), ""],
            [],
            ["أرصدة الخزائن والبنوك الحالية", "", ""],
            ["كود الحساب", "اسم الخزنة / البنك", "الرصيد الحالي (ج.م)"],
        ]
        for tr in cf["treasuries"]:
            sheet_cf.append([tr.get("account_code") or "", tr["name"], m_val(tr["balance"])])

        sheets_bundle = [
            ("الأرباح_والخسائر", sheet_pnl),
            ("ربحية_الأصناف", sheet_items),
            ("مديونيات_العملاء", sheet_rec),
            ("الموردون_والمشتريات", sheet_pay),
            ("السيولة_والمخزون", sheet_cf),
        ]
        xlsx_bytes = _build_native_xlsx_bytes(sheets_bundle)

        csv_io = io.StringIO()
        writer = csv.writer(csv_io)
        for sheet_title, rows in sheets_bundle:
            writer.writerow([f"=== {sheet_title} ==="])
            for r in rows:
                writer.writerow(r)
            writer.writerow([])
        csv_text = "\ufeff" + csv_io.getvalue()

        reports_dir = pathlib.Path(db.db_path()).parent / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        xlsx_name = f"TechZone_Financial_Report_{df}_to_{dt}_{stamp}.xlsx"
        xlsx_path = reports_dir / xlsx_name
        xlsx_path.write_bytes(xlsx_bytes)

        return {
            "ok": True,
            "file_name": xlsx_name,
            "file_path": str(xlsx_path),
            "xlsx_base64": base64.b64encode(xlsx_bytes).decode("ascii"),
            "csv_content": csv_text,
        }

    def report_export_pdf(self, title="التقرير المالي الشامل", date_from=None, date_to=None, pdf_image=None, img_w=1240, img_h=1754):
        """توليد وحفظ ملف التقرير المالي بصيغة PDF قياسية (A4) في مجلد data/reports وإرجاعه للواجهة."""
        self._perm_any("reports_sales_view", "reports_profit_view", "reports_shifts_view", "reports_movements_view")
        if pdf_image and isinstance(pdf_image, str) and "," in pdf_image:
            _validate_image_data_url(pdf_image, max_bytes=18 * 1024 * 1024)
            jpeg_bytes = base64.b64decode(pdf_image.split(",", 1)[1])
        else:
            jpeg_bytes = _FALLBACK_JPEG

        pdf_bytes = _jpeg_to_pdf_bytes(jpeg_bytes, _int(img_w, 1240), _int(img_h, 1754))
        reports_dir = pathlib.Path(db.db_path()).parent / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        df = (date_from or datetime.datetime.now().strftime("%Y-%m-%d")).strip()[:10]
        dt = (date_to or df).strip()[:10]
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        pdf_name = f"TechZone_Report_{df}_to_{dt}_{stamp}.pdf"
        pdf_path = reports_dir / pdf_name
        pdf_path.write_bytes(pdf_bytes)

        return {
            "ok": True,
            "file_name": pdf_name,
            "file_path": str(pdf_path),
            "pdf_base64": base64.b64encode(pdf_bytes).decode("ascii"),
        }

    def whatsapp_send_report(self, phone, title="التقرير المالي الشامل", date_from=None, date_to=None, summary_text="", pdf_image=None, img_w=1240, img_h=1754):
        """توليد ملف التقرير المالي PDF وإرساله عبر واتساب (عند تفعيل ميزة واتساب من الأدمن)."""
        self._perm_any("reports_sales_view", "reports_profit_view")
        with db.connect() as conn:
            st = self._settings(conn)
            if str(st.get("whatsapp_send_enabled", "1")).strip() == "0":
                raise ApiError("إرسال WhatsApp معطّل من قبل المدير")
            store_name = st.get("store_name", "تك زون للإلكترونيات")
            cur = st.get("currency", "ج.م")

        raw_phone = (phone or "").strip()
        digits = "".join(ch for ch in raw_phone if ch.isdigit())
        if not digits:
            raise ApiError("يرجى إدخال رقم موبايل المستلم (مثال: 010xxxxxxxx) لإرسال التقرير عبر واتساب")
        if digits.startswith("00"):
            digits = digits[2:]
        elif digits.startswith("01") and len(digits) == 11:
            digits = "2" + digits
        elif not digits.startswith("20") and len(digits) == 10:
            digits = "20" + digits

        pdf_res = self.report_export_pdf(
            title=title,
            date_from=date_from,
            date_to=date_to,
            pdf_image=pdf_image,
            img_w=img_w,
            img_h=img_h,
        )
        pdf_abs = str(pathlib.Path(pdf_res["file_path"]).resolve())

        if not summary_text:
            comp = self.report_comprehensive(date_from=date_from, date_to=date_to)
            pnl = comp["pnl"]
            rec = comp["receivables"]["summary"]
            pay = comp["payables"]["summary"]
            summary_text = (
                f"*{store_name} — {title}*\n"
                f"الفترة: {comp['period']['date_from']} إلى {comp['period']['date_to']}\n"
                f"• صافي المبيعات: {_fmt_money(pnl['net_sales_with_tax'])} {cur}\n"
                f"• مجمل الربح: {_fmt_money(pnl['total_gross_profit'])} {cur}\n"
                f"• المصروفات التشغيلية: {_fmt_money(pnl['operating_expenses_total'])} {cur}\n"
                f"• صافي الربح النهائي: {_fmt_money(pnl['net_profit'])} {cur}\n"
                f"• إجمالي مديونيات العملاء: {_fmt_money(rec['total_customers_debt'])} {cur}\n"
                f"• إجمالي متبقي الأقساط: {_fmt_money(rec['installments_remaining_total'])} {cur}\n"
                f"• إجمالي مستحقات الموردين: {_fmt_money(pay['total_suppliers_debt'])} {cur}\n"
                f"(مرفق ملف التقرير المالي الكامل بصيغة PDF)"
            )

        copied = _win32_copy_pdf_to_clipboard(pdf_abs)
        encoded_msg = urllib.parse.quote(summary_text)
        wa_Desktop_uri = f"whatsapp://send?phone={digits}&text={encoded_msg}"
        wa_web_url = f"https://web.whatsapp.com/send?phone={digits}&text={encoded_msg}"

        was_open = _find_whatsapp_hwnd() is not None
        if os.name == "nt":
            try:
                os.startfile(wa_Desktop_uri)
            except Exception:
                webbrowser.open(wa_web_url)
            if copied:
                import threading
                threading.Thread(
                    target=_win32_auto_paste_into_whatsapp,
                    args=(pdf_abs, was_open),
                    daemon=True,
                ).start()
        elif "PYTEST_CURRENT_TEST" not in os.environ and os.environ.get("DISPLAY"):
            try:
                webbrowser.open(wa_web_url)
            except Exception:
                pass

        return {
            "ok": True,
            "phone": digits,
            "pdf_name": pdf_res["file_name"],
            "pdf_path": pdf_abs,
            "clipboard_copied": bool(copied),
            "whatsapp_url": wa_web_url,
            "summary_text": summary_text,
        }
