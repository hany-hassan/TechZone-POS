"""شراء الأجهزة المستعملة وتذاكر الصيانة."""
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
    REPAIR_FLOW,
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


class ServicesMixin:

    # ---------------------------------------------------------- شراء مستعمل
    @staticmethod
    def _used_resolve_category_id(conn, device_type):
        if not device_type:
            return None
        cat_map = {"لابتوب": "لابتوبات", "اكسسوارات": "إكسسوارات", "اكسسوارت": "إكسسوارات", "جهاز لوحي": "أجهزة لوحية", "هاتف ذكي": "هواتف ذكية"}
        row = conn.execute("SELECT id FROM categories WHERE name=?", (cat_map.get(device_type, device_type),)).fetchone()
        return row["id"] if row else None

    def used_create(self, seller_name, model, serial=None, seller_phone=None, seller_id_no=None,
                    device_type=None, brand=None, condition=None, notes=None, buy_price=0,
                    storage=None, resale_price=None, to_inventory=True):
        u = self._perm("used_manage")
        seller_name = (seller_name or "").strip()
        model = (model or "").strip()
        if not seller_name or not model:
            raise ApiError("اسم البائع والموديل مطلوبان")
        serial = (serial or "").strip() or None
        buy = _money(buy_price)
        if buy <= 0:
            raise ApiError("سعر الشراء مطلوب")
        product_id = None
        seller_phone_clean = (seller_phone or "").strip() or None
        with db.connect() as conn:
            pos_tpl = self._load_templates(conn)["pos"]
            u_prefix = (pos_tpl.get("used_prefix") or "TRX-").strip() or "TRX-"
            cnt = conn.execute("SELECT COUNT(*) c FROM used_device_purchases").fetchone()["c"] + 1
            if u_prefix[-1].isdigit():
                ref = f"{u_prefix}{cnt:03d}"
            else:
                sep = "" if u_prefix.endswith(("-", "/", "_")) else "-"
                ref = f"{u_prefix}{sep}{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
            if conn.execute("SELECT 1 FROM used_device_purchases WHERE ref=?", (ref,)).fetchone():
                ref = f"{ref}-{cnt}"
            customer_id = _upsert_customer(conn, seller_name, seller_phone_clean)
            if to_inventory:
                if not serial:
                    raise ApiError("السيريال مطلوب لإضافة الجهاز للمخزون")
                if conn.execute("SELECT 1 FROM serials WHERE serial=?", (serial,)).fetchone():
                    raise ApiError("هذا الرقم التسلسلي مسجل مسبقاً في المخزون")
                cat_id = self._used_resolve_category_id(conn, device_type)
                name = f"{brand} {model}".strip() if brand else model
                cur = conn.execute(
                    """INSERT INTO products(sku, name, category_id, price, cost, qty, min_qty, tracked, notes, created_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (f"USED-{ref}", name, cat_id, _money(resale_price, 0), buy, 1, 1, 1,
                     f"مستعمل — {condition or 'بدون بيان'}" if condition else "مستعمل", db.now()),
                )
                product_id = cur.lastrowid
                conn.execute("INSERT INTO serials(product_id, serial, status, created_at) VALUES(?,?,?,?)",
                             (product_id, serial, "in_stock", db.now()))
                conn.execute(
                    """INSERT INTO stock_movements(created_at, user_id, product_id, serial_id, qty_change, qty_after, reason, ref)
                       VALUES(?,?,?,?,1,1,'used_purchase',?)""",
                    (db.now(), u["id"], product_id,
                     conn.execute("SELECT id FROM serials WHERE product_id=? AND serial=?", (product_id, serial)).fetchone()["id"],
                     ref),
                )
            cur_used = conn.execute(
                """INSERT INTO used_device_purchases(ref, user_id, created_at, seller_name, seller_phone, seller_id_no,
                    device_type, brand, model, serial, condition, notes, buy_price, storage, resale_price, product_id)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (ref, u["id"], db.now(), seller_name, seller_phone_clean, seller_id_no, device_type, brand,
                 model, serial, condition, notes, buy, storage, _money(resale_price) if resale_price not in (None, "") else None,
                 product_id),
            )
            return {"id": cur_used.lastrowid, "ref": ref, "product_id": product_id, "customer_id": customer_id}

    def used_update(self, id, seller_name, model, serial=None, seller_phone=None, seller_id_no=None,
                    device_type=None, brand=None, condition=None, notes=None, buy_price=0,
                    storage=None, resale_price=None):
        self._perm("used_manage")
        uid = _int(id)
        seller_name = (seller_name or "").strip()
        model = (model or "").strip()
        if not seller_name or not model:
            raise ApiError("اسم البائع والموديل مطلوبان")
        serial = (serial or "").strip() or None
        buy = _money(buy_price)
        if buy <= 0:
            raise ApiError("سعر الشراء مطلوب")
        seller_phone_clean = (seller_phone or "").strip() or None
        resale_val = _money(resale_price) if resale_price not in (None, "") else None
        with db.connect() as conn:
            row = conn.execute("SELECT * FROM used_device_purchases WHERE id=?", (uid,)).fetchone()
            if not row:
                raise ApiError("سجل الجهاز المستعمل غير موجود")
            customer_id = _upsert_customer(conn, seller_name, seller_phone_clean)
            if row["product_id"]:
                if not serial:
                    raise ApiError("السيريال مطلوب للجهاز المضاف للمخزون")
                if serial != row["serial"] and conn.execute(
                    "SELECT 1 FROM serials WHERE serial=? AND product_id!=?", (serial, row["product_id"])
                ).fetchone():
                    raise ApiError("هذا الرقم التسلسلي مسجل مسبقاً في المخزون")
                cat_id = self._used_resolve_category_id(conn, device_type)
                name = f"{brand} {model}".strip() if brand else model
                conn.execute(
                    """UPDATE products SET name=?, category_id=?, price=?, cost=?, notes=? WHERE id=?""",
                    (name, cat_id, _money(resale_price, 0), buy,
                     f"مستعمل — {condition or 'بدون بيان'}" if condition else "مستعمل", row["product_id"]),
                )
                if serial != row["serial"] and row["serial"]:
                    conn.execute(
                        "UPDATE serials SET serial=? WHERE product_id=? AND serial=?",
                        (serial, row["product_id"], row["serial"]),
                    )
            conn.execute(
                """UPDATE used_device_purchases
                   SET seller_name=?, seller_phone=?, seller_id_no=?, device_type=?, brand=?,
                       model=?, serial=?, condition=?, notes=?, buy_price=?, storage=?, resale_price=?
                   WHERE id=?""",
                (seller_name, seller_phone_clean, seller_id_no, device_type, brand,
                 model, serial, condition, notes, buy, storage, resale_val, uid),
            )
            return {"id": uid, "ref": row["ref"], "product_id": row["product_id"], "customer_id": customer_id}

    def used(self, q=None, limit=100, offset=0):
        self._perm_any("used_view", "used_manage")
        limit, offset = _int(limit, 100), _int(offset, 0)
        where, args = ["1=1"], []
        if q:
            where.append("(u.ref LIKE ? OR u.seller_name LIKE ? OR u.serial LIKE ? OR u.model LIKE ?)")
            args += [f"%{q}%"] * 4
        with db.connect() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM used_device_purchases u WHERE {' AND '.join(where)}", args
            ).fetchone()[0]
            rows = conn.execute(
                f"""SELECT u.* FROM used_device_purchases u WHERE {' AND '.join(where)}
                    ORDER BY u.id DESC LIMIT ? OFFSET ?""",
                args + [limit, offset],
            ).fetchall()
            return {"rows": [dict(r) for r in rows], "total": total}

    def used_stats(self):
        self._perm_any("used_view", "used_manage")
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        with db.connect() as conn:
            t = conn.execute(
                "SELECT COUNT(*) n, COALESCE(SUM(buy_price),0) sum FROM used_device_purchases WHERE created_at LIKE ?",
                (f"{today}%",),
            ).fetchone()
            stock = conn.execute("SELECT COALESCE(SUM(qty),0) n FROM products WHERE active=1").fetchone()["n"]
            return {"today_count": t["n"], "today_paid": t["sum"], "in_stock": stock}

    # ---------------------------------------------------------- صيانة
    def repair_create(self, customer_name, customer_phone, device_type, problem, address=None,
                       serial=None, accessories=None, notes=None, priority=0, cost=0):
        u = self._perm("repair_create")
        for f, v in (("customer_name", customer_name), ("customer_phone", customer_phone),
                     ("device_type", device_type), ("problem", problem)):
            if not (v or "").strip():
                raise ApiError("حقل مطلوب: " + f)
        with db.connect() as conn:
            pos_tpl = self._load_templates(conn)["pos"]
            r_prefix = (pos_tpl.get("repair_prefix") or "RPR-").strip() or "RPR-"
            cnt = conn.execute("SELECT COUNT(*) c FROM repairs").fetchone()["c"] + 1
            if r_prefix[-1].isdigit():
                ref = f"{r_prefix}{cnt:03d}"
            else:
                sep = "" if r_prefix.endswith(("-", "/", "_")) else "-"
                ref = f"{r_prefix}{sep}{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
            if conn.execute("SELECT 1 FROM repairs WHERE ref=?", (ref,)).fetchone():
                ref = f"{ref}-{cnt}"
            _upsert_customer(conn, customer_name.strip(), customer_phone.strip())
            cur = conn.execute(
                """INSERT INTO repairs(ref, user_id, created_at, updated_at, customer_name, customer_phone, address,
                    device_type, serial, problem, accessories, notes, status, priority, cost)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?, 'received',?,?)""",
                (ref, u["id"], db.now(), db.now(), customer_name.strip(), customer_phone.strip(), address,
                 device_type, serial, problem.strip(), accessories, notes,
                 1 if priority else 0, _money(cost)),
            )
            return {"id": cur.lastrowid, "ref": ref}

    def repairs(self, q=None, status=None, limit=100, offset=0):
        self._perm("repair_view")
        limit, offset = _int(limit, 100), _int(offset, 0)
        where, args = ["1=1"], []
        if status and status in REPAIR_FLOW:
            where.append("r.status=?")
            args.append(status)
        if q:
            where.append("(r.ref LIKE ? OR r.customer_name LIKE ? OR r.serial LIKE ?)")
            args += [f"%{q}%"] * 3
        with db.connect() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM repairs r WHERE {' AND '.join(where)}", args).fetchone()[0]
            rows = conn.execute(
                f"""SELECT r.*, u.name user_name FROM repairs r JOIN users u ON u.id=r.user_id
                    WHERE {' AND '.join(where)} ORDER BY r.id DESC LIMIT ? OFFSET ?""",
                args + [limit, offset],
            ).fetchall()
            return {"rows": [dict(r) for r in rows], "total": total}

    def repair(self, id):
        self._perm("repair_view")
        with db.connect() as conn:
            r = conn.execute(
                """SELECT r.*, u.name user_name FROM repairs r JOIN users u ON u.id=r.user_id WHERE r.id=?""",
                (_int(id),),
            ).fetchone()
            if not r:
                raise ApiError("التذكرة غير موجودة")
            parts = [dict(p) for p in conn.execute("SELECT * FROM repair_parts WHERE repair_id=?", (r["id"],))]
            d = dict(r)
            d["parts"] = parts
            d["transitions"] = REPAIR_FLOW.get(r["status"], [])
            return d

    def repair_set_status(self, id, status):
        self._perm("repair_edit")
        if status not in REPAIR_FLOW:
            raise ApiError("حالة غير معروفة")
        with db.connect() as conn:
            r = conn.execute("SELECT * FROM repairs WHERE id=?", (_int(id),)).fetchone()
            if not r:
                raise ApiError("التذكرة غير موجودة")
            if status not in REPAIR_FLOW.get(r["status"], []):
                raise ApiError(f"انتقال غير مسموح: {r['status']} ← {status}")
            conn.execute("UPDATE repairs SET status=?, updated_at=? WHERE id=?", (status, db.now(), r["id"]))
            return {"status": status}

    def repair_add_part(self, repair_id, product_id, qty=1):
        self._perm("repair_edit")
        rid, pid, q = _int(repair_id), _int(product_id), _int(qty, 1)
        if q <= 0:
            raise ApiError("كمية غير صالحة")
        with db.connect() as conn:
            r = conn.execute("SELECT * FROM repairs WHERE id=?", (rid,)).fetchone()
            if not r:
                raise ApiError("التذكرة غير موجودة")
            if r["status"] in ("delivered", "rejected"):
                raise ApiError("لا يمكن إضافة قطع لتذكرة منتهية")
            p = conn.execute("SELECT * FROM products WHERE id=? AND active=1", (pid,)).fetchone()
            if not p:
                raise ApiError("القطعة غير موجودة")
            if p["qty"] < q:
                raise ApiError(f"مخزون غير كافٍ للقطعة (المتوفر {p['qty']})")
            unit = p["cost"] if p["cost"] > 0 else p["price"]
            conn.execute("UPDATE products SET qty=qty-? WHERE id=?", (q, pid))
            after = conn.execute("SELECT qty FROM products WHERE id=?", (pid,)).fetchone()[0]
            conn.execute(
                """INSERT INTO stock_movements(created_at, user_id, product_id, qty_change, qty_after, reason, ref)
                   VALUES(?,?,?,?,?,?,?)""",
                (db.now(), self._user()["id"], pid, -q, after, "repair_part", r["ref"]),
            )
            conn.execute(
                """INSERT INTO repair_parts(repair_id, product_id, name, qty, unit_price, line_total)
                   VALUES(?,?,?,?,?,?)""",
                (rid, pid, p["name"], q, unit, unit * q),
            )
            conn.execute("UPDATE repairs SET cost=cost+?, updated_at=? WHERE id=?", (unit * q, db.now(), rid))
            return {"cost": conn.execute("SELECT cost FROM repairs WHERE id=?", (rid,)).fetchone()["cost"]}

    def repair_update(self, id, customer_name=None, customer_phone=None, device_type=None, problem=None,
                      address=None, serial=None, accessories=None, notes=None, priority=None, cost=None):
        """تعديل بيانات تذكرة صيانة مع حماية الوضع المالي للتذاكر المسلمة."""
        self._perm("repair_edit")
        rid = _int(id)
        with db.connect() as conn:
            r = conn.execute("SELECT * FROM repairs WHERE id=?", (rid,)).fetchone()
            if not r:
                raise ApiError("التذكرة غير موجودة")
            cname = (customer_name if customer_name is not None else r["customer_name"] or "").strip()
            cphone = (customer_phone if customer_phone is not None else r["customer_phone"] or "").strip()
            dtype = (device_type if device_type is not None else r["device_type"] or "").strip()
            prob = (problem if problem is not None else r["problem"] or "").strip()
            if not cname or not cphone or not dtype or not prob:
                raise ApiError("اسم العميل ورقم الهاتف ونوع الجهاز ووصف العطل حقول مطلوبة")
            new_cost = _money(cost) if cost is not None else r["cost"]
            if r["status"] == "delivered" and cost is not None and new_cost != r["cost"]:
                raise ApiError("لا يمكن تعديل التكلفة المالية لتذكرة صيانة تم تسليمها بالفعل حفاظاً على الوضع المالي")
            _upsert_customer(conn, cname, cphone)
            conn.execute(
                """UPDATE repairs
                   SET customer_name=?, customer_phone=?, address=?, device_type=?, serial=?,
                       problem=?, accessories=?, notes=?, priority=?, cost=?, updated_at=?
                   WHERE id=?""",
                (
                    cname,
                    cphone,
                    address if address is not None else r["address"],
                    dtype,
                    serial if serial is not None else r["serial"],
                    prob,
                    accessories if accessories is not None else r["accessories"],
                    notes if notes is not None else r["notes"],
                    (1 if priority else 0) if priority is not None else r["priority"],
                    new_cost,
                    db.now(),
                    rid,
                ),
            )
        return self.repair(rid)

    def repair_delete(self, id):
        """حذف تذكرة صيانة إذا لم تؤثر على الوضع المالي (غير مسلمة بتكلفة مالية) مع استرجاع قطع الغيار للمخزون."""
        u = self._perm("repair_delete")
        rid = _int(id)
        with db.connect() as conn:
            r = conn.execute("SELECT * FROM repairs WHERE id=?", (rid,)).fetchone()
            if not r:
                raise ApiError("التذكرة غير موجودة")
            if r["status"] == "delivered" and (r["cost"] or 0) > 0:
                raise ApiError("لا يمكن حذف تذكرة صيانة تم تسليمها وتحصيل قيمتها لأن ذلك يؤثر على الوضع المالي")
            parts = conn.execute("SELECT * FROM repair_parts WHERE repair_id=?", (rid,)).fetchall()
            for pt in parts:
                if pt["product_id"]:
                    conn.execute("UPDATE products SET qty=qty+? WHERE id=?", (pt["qty"], pt["product_id"]))
                    row_after = conn.execute("SELECT qty FROM products WHERE id=?", (pt["product_id"],)).fetchone()
                    if row_after:
                        conn.execute(
                            """INSERT INTO stock_movements(created_at, user_id, product_id, qty_change, qty_after, reason, ref)
                               VALUES(?,?,?,?,?,?,?)""",
                            (db.now(), u["id"], pt["product_id"], pt["qty"], row_after["qty"], "repair_cancel", r["ref"]),
                        )
            conn.execute("DELETE FROM repair_parts WHERE repair_id=?", (rid,))
            conn.execute("DELETE FROM repairs WHERE id=?", (rid,))
            return True

