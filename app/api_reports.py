"""التقارير المالية والإدارية وحركة المخزون."""
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
    _customer_debt_summary,
    _customers_enriched_cte,
    _fmt_money,
    _format_doc_seq,
    _int,
    _jpeg_to_pdf_bytes,
    _money,
    _upsert_customer,
    _validate_image_data_url,
    _win32_auto_paste_into_whatsapp,
    _win32_copy_pdf_to_clipboard,
    _find_whatsapp_hwnd,
)


class ReportsMixin:
    # ---------------------------------------------------------- تقارير
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
                        - p.cost * (i.qty - COALESCE((SELECT SUM(ri.qty) FROM sale_return_items ri WHERE ri.sale_item_id=i.id), 0))
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
                """SELECT p.id, p.name, p.sku, p.qty, p.min_qty, c.name category
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
