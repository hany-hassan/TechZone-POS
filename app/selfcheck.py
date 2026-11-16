"""فحص assert واحد قابل للتشغيل: python app/selfcheck.py — يطبع PASS ويعيد 0."""
import os
import pathlib
import re
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["SHOP_DB"] = _tmp.name

import api as api_mod
import db

N = 0


def check(name, cond):
    global N
    assert cond, f"FAIL: {name}"
    N += 1
    print(f"PASS {N}: {name}")


def call(a, name, payload=None):
    return a.call(name, payload)


a = api_mod.Api()

# 1) دخول صحيح ورمز خاطئ
r = call(a, "login", {"username": "admin", "pin": "1234"})
check("admin login ok", r["ok"] and r["data"]["role"] == "admin")
r = call(a, "login", {"username": "admin", "pin": "9999"})
check("wrong pin rejected", (not r["ok"]) and "غير صحيح" in r["error"])
r = call(a, "login", {"username": "nope", "pin": "1234"})
check("unknown user rejected", not r["ok"])

# 2) رفض إداري للكاشير الافتراضي
call(a, "login", {"username": "cashier", "pin": "1111"})
r = call(a, "product_save", {"sku": "X", "name": "X"})
check("cashier admin-call rejected", (not r["ok"]) and "للمدير" in r["error"])
r = call(a, "sale_return", {"sale_id": 1, "items": []})
check("cashier return rejected", (not r["ok"]) and "للمدير" in r["error"])
r = call(a, "report_daily", {})
check("cashier report rejected", (not r["ok"]) and "للمدير" in r["error"])

# 2b) حفظ تفضيلات حجم البلوك للمستخدم (user_pref_save)
sample_wp = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
r_pref = call(a, "user_pref_save", {
    "card_size": 180,
    "custom_bg": sample_wp,
    "accent_color": "#7c3aed",
    "desktop_layout": {"pos": {"x": 800, "y": 40}},
})
check("user custom_bg & accent & layout saved", r_pref["ok"] and r_pref["data"]["wallpaper"] == "custom" and r_pref["data"]["accent_color"] == "#7c3aed" and "pos" in r_pref["data"]["desktop_layout"])
check("user card_size pref saved", r_pref["ok"] and r_pref["data"]["card_size"] == 180)
# اختبار الخروج والدخول بمستخدم آخر ثم العودة لنفس المستخدم والتأكد أن session() يعيد كل التفضيلات المحفوظة
call(a, "logout")
call(a, "login", {"username": "admin", "pin": "1234"})
admin_sess = call(a, "session")["data"]["user"]
check("admin has own clean prefs", admin_sess["accent_color"] is None and admin_sess["custom_bg"] is None)
call(a, "logout")
call(a, "login", {"username": "cashier", "pin": "1111"})
cashier_sess = call(a, "session")["data"]["user"]
check("session persists custom_bg, accent_color, desktop_layout & card_size across logout/login",
      cashier_sess["card_size"] == 180
      and cashier_sess["wallpaper"] == "custom"
      and cashier_sess["custom_bg"] == sample_wp
      and cashier_sess["accent_color"] == "#7c3aed"
      and "pos" in (cashier_sess["desktop_layout"] or ""))

# 3) إضافة/تعديل منتج مع صورة وبحث (اسم/باركود/سيريال)
call(a, "login", {"username": "admin", "pin": "1234"})
sample_img = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
r = call(a, "product_save", {"sku": "TST-001", "name": "منتج فحص", "price": 100, "cost": 60, "min_qty": 5, "image": sample_img})
check("product add with image", r["ok"])
pid = r["data"]["id"]
check("product image stored", call(a, "product", {"id": pid})["data"]["image"] == sample_img)
r = call(a, "product_save", {"id": pid, "sku": "TST-001", "name": "منتج فحص معدل", "price": 120, "cost": 60, "image": sample_img})
check("product edit", r["ok"])
r = call(a, "products_search", {"q": "فحص معدل"})
check("search by name & returns image", r["ok"] and any(x["id"] == pid and x["image"] == sample_img for x in r["data"]))
r = call(a, "products_search", {"q": "TST-001"})
check("search by sku", r["ok"] and any(x["id"] == pid for x in r["data"]))
call(a, "serial_add", {"product_id": pid, "serial": "SN-SELF-1"})
r = call(a, "products_search", {"q": "SN-SELF-1"})
check("search by serial", r["ok"] and any(x["id"] == pid for x in r["data"]))

# 4) بيع ناجح يخصم المخزون ويكتب الحركة والدفع (مع اختبار تفعيل وإيقاف الضريبة)
call(a, "shift_open", {"opening_cash": 100})
call(a, "product_adjust", {"id": pid, "qty_change": 20, "reason": "فحص"})
call(a, "settings_save", {"tax_enabled": "1", "tax_rate": "15", "pos_card_size": "160"})
before = call(a, "product", {"id": pid})["data"]["qty"]
# سعر 120 للوحدة × 2 = 240، ضريبة 15% = 36، إجمالي 276 (ندخل 300 في الكاش فيحسب الباقي 24 تلقائياً)
r = call(a, "sale_create", {
    "items": [{"product_id": pid, "qty": 2}],
    "discount": 0,
    "payments": [{"method": "cash", "amount": 300}],
    "customer_name": "عميل بدون هاتف",
})
check("sale ok (overpaid cash auto-change)", r["ok"])
sale_id = r["data"]["sale_id"]
check("invoice format", r["data"]["invoice_no"].startswith("INV-"))
after = call(a, "product", {"id": pid})["data"]["qty"]
check("stock deducted", after == before - 2)
with db.connect() as c:
    mv = c.execute("SELECT * FROM stock_movements WHERE product_id=? AND reason='sale' ORDER BY id DESC LIMIT 1",
                   (pid,)).fetchone()
    check("movement written", mv is not None and mv["qty_change"] == -2 and mv["qty_after"] == after)
    pay = c.execute("SELECT * FROM payments WHERE sale_id=?", (sale_id,)).fetchone()
    check("payment written", pay is not None and pay["amount"] == 27600 and pay["change"] == 2400)
    s = c.execute("SELECT * FROM sales WHERE id=?", (sale_id,)).fetchone()
    check("tax correct", s["tax"] == 3600 and s["total"] == 27600)

# 4a-2) اختبار تعديل خصم فاتورة مدفوعة (sale_discount) وتقرير الوردية التفصيلي (shift_summary)
r_sdisc = call(a, "sale_discount", {"sale_id": sale_id, "discount": 40})
check("sale_discount on paid invoice ok", r_sdisc["ok"] and r_sdisc["data"]["discount"] == 4000 and r_sdisc["data"]["total"] == 23000)

# 4b) اختبار إيقاف الضريبة (tax_enabled = 0) + الدفع بالمحفظة برقم مرجعي + الدفع الآجل بإلزام العميل
call(a, "settings_save", {"tax_enabled": "0"})
r_no_ref = call(a, "sale_create", {
    "items": [{"product_id": pid, "qty": 1}],
    "payments": [{"method": "wallet", "amount": 120}],
})
check("wallet without ref_no rejected", (not r_no_ref["ok"]) and "مرجعية" in r_no_ref["error"])

r_no_cust = call(a, "sale_create", {
    "items": [{"product_id": pid, "qty": 1}],
    "payments": [{"method": "credit", "amount": 120}],
})
check("credit without customer rejected", (not r_no_cust["ok"]) and "العميل" in r_no_cust["error"])

r_credit_wallet = call(a, "sale_create", {
    "items": [{"product_id": pid, "qty": 2}],  # 2 * 120 = 240 (tax_enabled=0 -> total=240)
    "payments": [
        {"method": "wallet", "amount": 100, "ref_no": "VF-998877"},
        {"method": "credit", "amount": 140},
    ],
    "customer_name": "عميل آجل فحص",
    "customer_phone": "01055465603",
})
check("tax disabled + wallet ref + credit sale ok", r_credit_wallet["ok"])
cw_sale_id = r_credit_wallet["data"]["sale_id"]
cw_sale = call(a, "sale", {"id": cw_sale_id})["data"]
check("zero tax when disabled", cw_sale["tax"] == 0 and cw_sale["total"] == 24000)

# 4c) كشف حساب المديونية وسندات القبض (customer_payment_create / customer_payment_delete)
cust_search = call(a, "customers_search", {"q": "عميل آجل فحص"})["data"]
check("credit customer found with debt", len(cust_search) == 1 and cust_search[0]["debt"] == 14000)
credit_cid = cust_search[0]["id"]

r_overpay_debt = call(a, "customer_payment_create", {"customer_id": credit_cid, "amount": 500, "method": "cash"})
check("overpaying debt rejected", not r_overpay_debt["ok"])

r_voucher = call(a, "customer_payment_create", {
    "customer_id": credit_cid,
    "amount": 60,
    "method": "wallet",
    "ref_no": "INSTA-1122",
    "notes": "دفعة أولى",
})
check("receipt voucher created", r_voucher["ok"] and r_voucher["data"]["remaining_debt"] == 8000)
hist_after = call(a, "customer_history", {"id": credit_cid})["data"]
check("customer ledger updated", hist_after["customer"]["debt"] == 8000 and len(hist_after["ledger"]) == 2)

# 4d) اختبار ملخص إغلاق الوردية التفصيلي (shift_summary)
sh_sum = call(a, "shift_summary")
check("shift_summary ok & lists operations", sh_sum["ok"] and len(sh_sum["data"]["operations"]) >= 3 and sh_sum["data"]["wallet_sales"] == 10000 and sh_sum["data"]["credit_sales"] == 14000)

# 5) رفض بيع عند نقص المخزون
call(a, "settings_save", {"tax_enabled": "1", "tax_rate": "15"})
r = call(a, "sale_create", {"items": [{"product_id": pid, "qty": 10 ** 9}],
                           "payments": [{"method": "cash", "amount": 1}]})
check("oversell rejected", (not r["ok"]) and "مخزون" in r["error"])

# 6) رفض بيع بلا وردية مفتوحة
call(a, "shift_close", {"counted_cash": 100})
r = call(a, "sale_create", {"items": [{"product_id": pid, "qty": 1}],
                            "payments": [{"method": "cash", "amount": 138}]})
check("no-shift sale rejected", (not r["ok"]) and "وردية" in r["error"])
call(a, "shift_open", {"opening_cash": 0})

# 7) مرتجع يعيد المخزون
s = call(a, "sale", {"id": sale_id})["data"]
item_id = s["items"][0]["id"]
r = call(a, "sale_return", {"sale_id": sale_id, "items": [{"sale_item_id": item_id, "qty": 1}], "reason": "فحص"})
check("return ok", r["ok"] and r["data"]["total"] == 12000)
check("return restores stock", call(a, "product", {"id": pid})["data"]["qty"] == after - 2 + 1)
with db.connect() as c:
    mv = c.execute("SELECT * FROM stock_movements WHERE product_id=? AND reason='return' ORDER BY id DESC LIMIT 1",
                   (pid,)).fetchone()
    check("return movement", mv is not None and mv["qty_change"] == 1)

# 8) نص إيصال 80 عموداً
t = call(a, "receipt_text", {"id": cw_sale_id})["data"]
check("receipt 80 cols & includes wallet ref", all(len(line) <= 80 for line in t.splitlines()) and "VF-998877" in t)

# 8b) فحص إرسال الفاتورة عبر واتساب (whatsapp_send_invoice) وحفظ ملف الإيصال بدون أخطاء pathlib
import webbrowser
_orig_wb_open = webbrowser.open
webbrowser.open = lambda url, *a, **kw: True
try:
    r_wa = call(a, "whatsapp_send_invoice", {"sale_id": cw_sale_id, "phone": "01055465603"})
    check("whatsapp_send_invoice ok & saves valid PDF file + company message", r_wa["ok"] and r_wa["data"]["phone"] == "201055465603" and "لديك فاتورة من" in r_wa["data"]["message"] and r_wa["data"]["pdf_file"].endswith(".pdf") and pathlib.Path(r_wa["data"]["pdf_file"]).read_bytes().startswith(b"%PDF-1.4"))
finally:
    webbrowser.open = _orig_wb_open

# 9) شراء جهاز مستعمل يضيف سيريالاً للمخزون كمنتج متتبّع
r = call(a, "used_create", {"seller_name": "بائع فحص", "model": "Test Phone X",
                            "serial": "SN-USED-SELF-1", "buy_price": 500, "resale_price": 900})
check("used purchase ok", r["ok"] and r["data"]["product_id"])
used_pid = r["data"]["product_id"]
with db.connect() as c:
    sn = c.execute("SELECT * FROM serials WHERE serial='SN-USED-SELF-1'").fetchone()
    up = c.execute("SELECT * FROM products WHERE id=?", (used_pid,)).fetchone()
    check("used serial in stock & tracked", sn is not None and sn["status"] == "in_stock" and up["tracked"] == 1)

# 10) تذكرة صيانة + انتقال مرفوض + قطعة تخصم
r = call(a, "repair_create", {"customer_name": "عميل فحص", "customer_phone": "01000000000",
                              "device_type": "لابتوب", "problem": "لا يعمل"})
check("repair created", r["ok"])
rid = r["data"]["id"]
r = call(a, "repair_set_status", {"id": rid, "status": "delivered"})
check("bad transition rejected", (not r["ok"]) and "غير مسموح" in r["error"])
r = call(a, "repair_set_status", {"id": rid, "status": "in_review"})
check("good transition ok", r["ok"])
pq = call(a, "product", {"id": pid})["data"]["qty"]
r = call(a, "repair_add_part", {"repair_id": rid, "product_id": pid, "qty": 1})
check("part added", r["ok"])
check("part deducts stock", call(a, "product", {"id": pid})["data"]["qty"] == pq - 1)

# 11) أرقام تقرير يومي/شهري مطابقة لحساب يدوي
import datetime
today = datetime.datetime.now().strftime("%Y-%m-%d")
d = call(a, "report_daily", {"date": today})["data"]
with db.connect() as c:
    m = c.execute("SELECT COUNT(*) n, COALESCE(SUM(total),0) t FROM sales WHERE created_at LIKE ?",
                  (f"{today}%",)).fetchone()
    check("daily matches manual", d["sales"]["count"] == m["n"] and d["sales"]["total"] == m["t"])
now = datetime.datetime.now()
mo = call(a, "report_monthly", {"year": now.year, "month": now.month})["data"]
with db.connect() as c:
    m = c.execute("SELECT COUNT(*) n, COALESCE(SUM(total),0) t FROM sales WHERE created_at >= ? AND created_at < ?",
                  (f"{now.year:04d}-{now.month:02d}-01",
                   (datetime.date(now.year, now.month, 1) + datetime.timedelta(days=32)).replace(day=1).strftime("%Y-%m-%d"))).fetchone()
    check("monthly matches manual", mo["sales"]["count"] == m["n"] and mo["sales"]["total"] == m["t"])

# 11b) فحص report_top و report_profit و sale_modify_from_cart وملخص مديونيات العملاء
r_top = call(a, "report_top", {"limit": 10})
check("report_top ok (no ambiguous qty)", r_top["ok"] and isinstance(r_top["data"], list))
r_prof = call(a, "report_profit", {})
check("report_profit ok", r_prof["ok"] and "goods_profit" in r_prof["data"])

# فحص تعديل الفاتورة من داخل سلة المشتريات (sale_modify_from_cart) مع توثيق المعدل والوقت
cw_full = call(a, "sale", {"id": cw_sale_id})["data"]
cw_item_id = cw_full["items"][0]["id"]
r_mod = call(a, "sale_modify_from_cart", {
    "sale_id": cw_sale_id,
    "items": [{"sale_item_id": cw_item_id, "qty": 1, "unit_price": 100}],
    "discount": 10,
    "reason": "مرتجع قطعة مع خصم من السلة",
})
check("sale_modify_from_cart ok & logs modifier", r_mod["ok"] and r_mod["data"]["modified_by_name"] == "المدير" and r_mod["data"]["returned_total"] == 12000)

cl_res = call(a, "customers_list", {"limit": 50, "offset": 0})
check("customers_list includes global debt/paid summary", cl_res["ok"] and "summary" in cl_res["data"] and "total_debt" in cl_res["data"]["summary"])

# 12) settings اسم المحل + عملة مصر + مفاتيح التخصيص
st = call(a, "settings", {})["data"]
check("store name & EGP currency setting", st.get("store_name") == "تك زون للإلكترونيات" and st.get("currency") == "ج.م")
r = call(a, "settings_save", {"store_email": "shop@example.com"})
check("new key saved", r["ok"] and r["data"].get("store_email") == "shop@example.com")
check("new key readable", call(a, "settings", {})["data"].get("store_email") == "shop@example.com")
r = call(a, "settings_save", {"receipt_show_barcode": "0"})
check("show flag zero saved", r["ok"] and r["data"].get("receipt_show_barcode") == "0")
check("show flag zero readable", call(a, "settings", {})["data"].get("receipt_show_barcode") == "0")
r = call(a, "settings_save", {"receipt_logo": "not-an-image"})
check("bad logo rejected", (not r["ok"]))
r = call(a, "settings_save", {"receipt_logo": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="})
check("logo saved", r["ok"])

# 13) إدارة العملاء والموظفين والصلاحيات المخصصة لكل موظف
rc = call(a, "customers_save", {"name": "خالد العمري", "phone": "01055123456"})
check("customer save ok", rc["ok"] and rc["data"]["id"] > 0)
cid = rc["data"]["id"]
rc_dup = call(a, "customers_save", {"name": "خالد العمري", "phone": "01055123456"})
check("duplicate customer rejected", (not rc_dup["ok"]) and "مسجل مسبقاً" in rc_dup["error"])
rc_one = call(a, "customer", {"id": cid})
check("customer single fetch ok", rc_one["ok"] and rc_one["data"]["name"] == "خالد العمري")

ru = call(a, "user_save", {
    "username": "cashier2",
    "name": "سالم علي",
    "role": "cashier",
    "pin": "2222",
    "permissions": {"inventory_edit": True, "reports_view": False, "pos_item_discount": True},
})
check("custom permission user save ok", ru["ok"] and ru["data"]["id"] > 0)
uid2 = ru["data"]["id"]

# تسجيل الدخول بالموظف المخصص والتأكد أنه يستطيع تعديل المخزون وعمل خصم ولا يستطيع فتح التقارير
call(a, "login", {"username": "cashier2", "pin": "2222"})
r_allowed = call(a, "categories_save", {"name": "فئة صلاحية خاصة"})
check("custom perm allowed inventory_edit", r_allowed["ok"])
r_disc_allowed = call(a, "sale_discount", {"sale_id": sale_id, "discount": 10})
check("custom perm allowed pos_item_discount", r_disc_allowed["ok"])
r_denied = call(a, "report_daily", {})
check("custom perm denied reports_view", not r_denied["ok"])

call(a, "login", {"username": "admin", "pin": "1234"})
ru_del = call(a, "user_delete", {"id": uid2})
check("user delete ok", ru_del["ok"])

# 13b) فحص قسم المبيعات وعروض الأسعار وقوالب الفواتير (A4 + POS Thermal)
tpl_res = call(a, "templates_get", {})
check("templates_get ok (a4 + pos)", tpl_res["ok"] and "a4" in tpl_res["data"] and "pos" in tpl_res["data"] and tpl_res["data"]["a4"]["theme"] == "taqnia_wave")
tpl_save = call(a, "templates_save", {"a4": {"company_title": "تقنية -Technology", "currency_symbol": "LE", "invoice_prefix": "N00", "quote_prefix": "Q00"}, "pos": {"paper_width": "80mm"}})
check("templates_save ok & prefix N00 seq", tpl_save["ok"] and tpl_save["data"]["a4"]["currency_symbol"] == "LE" and tpl_save["data"]["next_invoice_no"].startswith("N00"))

pm_save = call(a, "payment_methods_save", {"methods": [
    {"id": "cash", "name": "نقدي", "base_type": "cash"},
    {"id": "plan3", "name": "3 دفعات مع دفعة مقدمة", "base_type": "cash"},
    {"id": "plan2", "name": "دفعتين", "base_type": "wallet"},
]})
check("payment_methods_save ok", pm_save["ok"] and any(m["name"] == "3 دفعات مع دفعة مقدمة" for m in pm_save["data"]))

q_create = call(a, "quotation_save", {
    "doc_type": "quote",
    "customer_name": "فاروق مجدي شحاته",
    "customer_phone": "01099887766",
    "doc_date": "2026-08-26",
    "due_date": "2026-08-26",
    "source_ref": "تقنية - Technology/0004",
    "signal_ref": "تقنية - Technology/0004",
    "items": [
        {"sku": "HDD 500", "name": "هارددسك 500 مكتبي HDD 500", "qty": 1, "unit_price": 650, "tax_label": "Zero Rated 0%", "tax_rate": 0},
        {"sku": "CABLE RG58 100M", "name": "كابل كاميرا 100 متر CABLE RG58 100M", "qty": 1, "unit_price": 1260, "tax_label": "", "tax_rate": 0},
        {"sku": "Power Supply 12V 20A", "name": "Power Supply 12V 20A", "qty": 1, "unit_price": 310, "tax_label": "", "tax_rate": 0},
        {"sku": "PNC AND DC CAMERA", "name": "PNC AND DC CAMERA", "qty": 8, "unit_price": 10, "tax_label": "", "tax_rate": 0},
        {"sku": "HP 24 LCD", "name": "شاشة HP 24 LCD", "qty": 1, "unit_price": 1770, "tax_label": "Zero Rated 0%", "tax_rate": 0},
        {"sku": "DVR HIKVISION 8 CH", "name": "دفي ار 8 قناة هيكفيجن DVR HIKVISION 8 CH", "qty": 1, "unit_price": 2550, "tax_label": "", "tax_rate": 0},
    ],
})
check("quotation_save ok (total 6620.00)", q_create["ok"] and q_create["data"]["total"] == 662000 and q_create["data"]["status"] == "draft")
qid = q_create["data"]["id"]

q_conv = call(a, "quotation_convert_to_sale", {"id": qid, "paid_amount": 5000, "payment_method": "cash", "payment_method_label": "3 دفعات مع دفعة مقدمة", "payment_plan_note": "دفعة مقدمة 5000 والباقي على دفعتين"})
check("quotation_convert_to_sale ok (paid 5000, due 1620, prefix N00)", q_conv["ok"] and q_conv["data"]["status"] == "converted" and q_conv["data"]["paid_amount"] == 500000 and q_conv["data"]["due_amount"] == 162000 and q_conv["data"]["quote_no"].startswith("N00") and q_conv["data"]["payment_method_label"] == "3 دفعات مع دفعة مقدمة")

q_list = call(a, "quotations", {})
check("quotations list & summary ok", q_list["ok"] and q_list["data"]["summary"]["invoices_count"] >= 1)

# 13c) فحص الدخول بالرمز السري فقط (التعرف التلقائي على المدير أو الكاشير) وإعدادات الدخول والصفحة الافتراضية لكل مستخدم
call(a, "login", {"username": "admin", "pin": "1234"})
call(a, "settings_save", {"store_name": "متجر النور للكمبيوتر", "login_mode": "pin_only", "default_start_page": "sales_quotes", "default_start_mode": "window", "os_default_theme": "light"})
lcfg = call(a, "login_config")
check("login_config returns dynamic store_name, login_mode & sanitized users without role",
      lcfg["ok"] and lcfg["data"]["store_name"] == "متجر النور للكمبيوتر"
      and lcfg["data"]["login_mode"] == "pin_only"
      and all("role" not in u for u in lcfg["data"]["users"]))

call(a, "logout")
# دخول المدير بالرمز السري فقط بدون اسم مستخدم
r_pin_admin = call(a, "login", {"pin": "1234"})
check("PIN-only login auto-detects admin & falls back to admin default_start_page",
      r_pin_admin["ok"] and r_pin_admin["data"]["username"] == "admin"
      and r_pin_admin["data"]["role"] == "admin"
      and r_pin_admin["data"]["effective_start_page"] == "sales_quotes")

# رفض تكرار نفس الرمز السري لمستخدم آخر
r_dup_pin = call(a, "user_save", {"username": "dupuser", "name": "مستخدم مكرر", "role": "cashier", "pin": "1111"})
check("duplicate PIN across users rejected", (not r_dup_pin["ok"]) and "رمز سري فريد" in r_dup_pin["error"])

# دخول الكاشير بالرمز السري فقط وتخصيص صفحة البداية والوضع الليلي/النهاري الخاص به
call(a, "logout")
r_pin_cashier = call(a, "login", {"pin": "1111"})
check("PIN-only login auto-detects cashier", r_pin_cashier["ok"] and r_pin_cashier["data"]["username"] == "cashier" and r_pin_cashier["data"]["role"] == "cashier")
r_upref = call(a, "user_pref_save", {"start_page": "repair", "start_mode": "maximized", "theme_mode": "dark"})
check("user start_page & theme_mode saved", r_upref["ok"] and r_upref["data"]["start_page"] == "repair" and r_upref["data"]["theme_mode"] == "dark")

call(a, "logout")
r_pin_cashier2 = call(a, "login", {"pin": "1111"})
check("cashier login uses personal start_page over admin default",
      r_pin_cashier2["ok"] and r_pin_cashier2["data"]["effective_start_page"] == "repair"
      and r_pin_cashier2["data"]["effective_start_mode"] == "maximized"
      and r_pin_cashier2["data"]["theme_mode"] == "dark")

# فحص صفحة الملف الشخصي للموظف (profile_save: تغيير الاسم، الصورة الشخصية، الرمز السري، وصفحة البداية)
sample_av = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
r_prof = call(a, "profile_save", {
    "name": "أحمد محمد المعدل",
    "current_pin": "1111",
    "new_pin": "5566",
    "avatar": sample_av,
    "start_page": "customers",
    "start_mode": "window",
})
check("profile_save updates name, avatar, PIN & start_page",
      r_prof["ok"] and r_prof["data"]["name"] == "أحمد محمد المعدل"
      and r_prof["data"]["avatar"] == sample_av
      and r_prof["data"]["effective_start_page"] == "customers")

call(a, "logout")
r_new_pin_login = call(a, "login", {"pin": "5566"})
check("login with new employee PIN works & returns avatar",
      r_new_pin_login["ok"] and r_new_pin_login["data"]["name"] == "أحمد محمد المعدل"
      and r_new_pin_login["data"]["avatar"] == sample_av)
# إعادة الرمز السري الافتراضي للكاشير
call(a, "profile_save", {"name": "أحمد محمد", "current_pin": "5566", "new_pin": "1111"})

# التحقق من وجود صفحات settings.html و staff.html و profile.html وفصل الإعدادات عن reports.html و receipt.html
check("settings.html, staff.html & profile.html exist",
      (ROOT / "web" / "settings.html").exists()
      and (ROOT / "web" / "staff.html").exists()
      and (ROOT / "web" / "profile.html").exists())
check("reports.html is dedicated to reports only (no staff-zone)",
      "staff-zone" not in (ROOT / "web" / "reports.html").read_text(encoding="utf-8"))
check("receipt.html is dedicated to receipt preview only (no custom-form)",
      "custom-form" not in (ROOT / "web" / "receipt.html").read_text(encoding="utf-8"))

# إعادة اسم المحل الافتراضي بعد الفحص وفحص الميزات الـ 10 الجديدة
call(a, "logout")
call(a, "login", {"pin": "1234"})
call(a, "settings_save", {"store_name": "تك زون للإلكترونيات", "tax_enabled": "0"})

# (أ) مصمم القوالب أُزيل من sales_quotes.html وأصبح حصرياً في settings.html
sq_html = (ROOT / "web" / "sales_quotes.html").read_text(encoding="utf-8")
check("sales_quotes.html has no pane-templates (designer in settings only)",
      "id=\"pane-templates\"" not in sq_html and "settings.html?tab=invoices" in sq_html)

# (ب) عند إيقاف الضرائب (tax_enabled=0) يتم تصفير الضرائب في عروض الأسعار والفواتير حتى لو أُرسل tax_rate=14
q_notax = call(a, "quotation_save", {
    "doc_type": "quote",
    "customer_name": "عميل بدون ضريبة",
    "customer_phone": "01099887766",
    "items": [{"name": "شاشة سامسونج", "qty": 1, "unit_price": 1000, "tax_rate": 14}],
})
check("quotation_save forces zero tax when tax_enabled=0",
      q_notax["ok"] and q_notax["data"]["tax"] == 0 and q_notax["data"]["total"] == 100000)

# (ج) إلغاء عرض السعر (quotation_cancel) مسموح، بينما إلغاء الفاتورة المعتمدة مرفوض لحماية الدورة المالية
q_cancel_res = call(a, "quotation_cancel", {"id": q_notax["data"]["id"]})
check("quotation_cancel marks quote as cancelled",
      q_cancel_res["ok"] and q_cancel_res["data"]["status"] == "cancelled")
q_cancel_inv_err = call(a, "quotation_cancel", {"id": qid})
check("quotation_cancel rejects converted invoice to protect financial cycle",
      not q_cancel_inv_err["ok"])

# (د) بادئات التسلسل المخصصة لجميع الفواتير والإيصالات (POS + صيانة + سند قبض + شراء مستعمل) + ربط البائع بالعملاء
r_tpl_prefs = call(a, "templates_save", {
    "pos": {
        "pos_invoice_prefix": "POS26-",
        "repair_prefix": "TKT-",
        "voucher_prefix": "VCH-",
        "used_prefix": "USD-",
    }
})
check("templates_save saves pos/repair/voucher/used prefixes",
      r_tpl_prefs["ok"]
      and r_tpl_prefs["data"]["pos"]["pos_invoice_prefix"] == "POS26-"
      and r_tpl_prefs["data"]["pos"]["repair_prefix"] == "TKT-"
      and r_tpl_prefs["data"]["pos"]["voucher_prefix"] == "VCH-"
      and r_tpl_prefs["data"]["pos"]["used_prefix"] == "USD-")

r_pos_pref_sale = call(a, "sale_create", {
    "items": [{"product_id": pid, "qty": 1}],
    "payments": [{"method": "cash", "amount": 550}],
})
check("sale_create uses pos_invoice_prefix POS26-",
      r_pos_pref_sale["ok"] and r_pos_pref_sale["data"]["invoice_no"].startswith("POS26-"))

r_used_cust = call(a, "used_create", {
    "seller_name": "بائع مسجل تلقائياً",
    "seller_phone": "01555666777",
    "model": "iPad Air 5",
    "buy_price": 8000,
    "to_inventory": False,
})
check("used_create uses used_prefix USD- & registers seller in customers",
      r_used_cust["ok"]
      and r_used_cust["data"]["ref"].startswith("USD-")
      and r_used_cust["data"]["customer_id"] is not None)
c_search_used = call(a, "customers_search", {"q": "01555666777"})
check("seller from used_create found via customers_search",
      c_search_used["ok"] and any(c["name"] == "بائع مسجل تلقائياً" for c in c_search_used["data"]))

# (هـ) تذكرة صيانة ببادئة TKT- + تعديل التذكرة (repair_update) + حذف تذكرة غير مسلمة (repair_delete) + منع حذف تذكرة مسلمة بتكلفة
r_rep2 = call(a, "repair_create", {
    "customer_name": "عميل صيانة 2",
    "customer_phone": "01122334455",
    "device_type": "لابتوب لينوفو",
    "problem": "تغيير كيبورد",
    "cost": 450,
})
check("repair_create uses repair_prefix TKT-",
      r_rep2["ok"] and r_rep2["data"]["ref"].startswith("TKT-"))
rid2 = r_rep2["data"]["id"]
r_rep_upd = call(a, "repair_update", {
    "id": rid2,
    "problem": "تغيير كيبورد وتنظيف مروحة",
    "cost": 550,
})
check("repair_update updates problem and cost",
      r_rep_upd["ok"] and r_rep_upd["data"]["cost"] == 55000 and "مروحة" in r_rep_upd["data"]["problem"])
r_rep_del_ok = call(a, "repair_delete", {"id": rid2})
check("repair_delete deletes undelivered repair ticket", r_rep_del_ok["ok"])
call(a, "repair_set_status", {"id": rid, "status": "repaired"})
call(a, "repair_set_status", {"id": rid, "status": "delivered"})
r_rep_del_delivered_err = call(a, "repair_delete", {"id": rid})
check("repair_delete blocks deleting delivered paid repair ticket", not r_rep_del_delivered_err["ok"])

# (و) سجل المبيعات والمرتجعات (sales & sales_stats & history_suggestions) يعرض الكل والتاريخ والأتوكمبليت
r_hist_all = call(a, "sales", {"all_dates": True, "limit": 50})
kinds_found = {(row.get("kind"), row.get("sub_kind")) for row in r_hist_all["data"]["rows"]}
check("history sales(all_dates=True) includes pos, b2b, quote, and repair",
      r_hist_all["ok"]
      and ("sale", "pos") in kinds_found
      and ("sale", "b2b") in kinds_found
      and ("quote", "quote") in kinds_found
      and ("repair", "repair") in kinds_found)
r_hist_sug = call(a, "history_suggestions", {"q": "N00"})
check("history_suggestions autocomplete works",
      r_hist_sug["ok"] and len(r_hist_sug["data"]) >= 1)

# (ز) التقارير المالية (report_daily) تدعم من تاريخ إلى تاريخ (date_from / date_to)
r_rep_range = call(a, "report_daily", {"date_from": today, "date_to": today})
check("report_daily supports date_from & date_to",
      r_rep_range["ok"] and r_rep_range["data"]["sales"]["count"] >= 1)

# (ح) التحقق من رفع خلفية سطح المكتب في profile.html وتخطيط الحقول في staff.html
pf_html = (ROOT / "web" / "profile.html").read_text(encoding="utf-8")
stf_html = (ROOT / "web" / "staff.html").read_text(encoding="utf-8")
check("profile.html has custom wallpaper upload & staff.html has non-overlapping staff-fields-grid",
      "pf-custom-bg-file" in pf_html and "staff-fields-grid" in stf_html)

# إعادة البادئات للافتراضي
call(a, "templates_save", {"reset_pos": True})

# (ط) فحص سلامة صياغة JavaScript في web/app.js و web/index.html لمنع أي خطأ SyntaxError يوقف شاشة الدخول
app_js_text = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
idx_html_text = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
pos_html_text = (ROOT / "web" / "pos.html").read_text(encoding="utf-8")
check("web/app.js has no duplicate const st declaration & index.html has pin-input + login-error-box",
      app_js_text.count("const globalTaxEnabled = st.tax_enabled") == 2
      and "id=\"pin-input\"" in idx_html_text
      and "id=\"login-error-box\"" in idx_html_text
      and "id=\"modal-force-pin\"" in idx_html_text)

# (ي) فحص مستمع الباركود السريع في شاشة الكاشير pos.html
check("pos.html has global barcode listener & fast scanner handler",
      "handleBarcodeScan" in pos_html_text
      and "lastBarcodeInputTime" in pos_html_text)

# (ك) فحص النسخ الاحتياطي التلقائي لقاعدة البيانات واستعراض النسخ
call(a, "login", {"username": "cashier", "pin": "1111"})
check("cashier db_backup denied", not call(a, "db_backup")["ok"])
check("cashier backups_list denied", not call(a, "backups_list")["ok"])
check("cashier db_restore denied", not call(a, "db_restore", {"backup_name": "dummy"})["ok"])

call(a, "login", {"username": "admin", "pin": "1234"})
b_res = call(a, "db_backup", {"reason": "test_selfcheck"})
check("db_backup creates valid backup file and records size",
      b_res["ok"] and b_res["data"]["name"].startswith("shop_") and b_res["data"]["size_bytes"] > 0)
b_list = call(a, "backups_list", {})
check("backups_list returns available backup snapshots",
      b_list["ok"] and len(b_list["data"]) >= 1 and any("test_selfcheck" in x["name"] for x in b_list["data"]))

res_restore = call(a, "db_restore", {"backup_name": b_res["data"]["name"]})
check("db_restore restores snapshot safely with pre-backup",
      res_restore["ok"] and res_restore["data"].get("safety_backup") is not None)

st_html_text = (ROOT / "web" / "settings.html").read_text(encoding="utf-8")
check("settings.html has manager backups UI tab and table",
      "spane-backups" in st_html_text and "btn-create-backup-now" in st_html_text and "btn-restore-backup" in st_html_text and "backups-tbody" in st_html_text)

# (ل) فحص كشف الرمز السري الافتراضي للأدمن وإلزام تغييره
adm_log = call(a, "login", {"username": "admin", "pin": "1234"})
check("admin login with default PIN flags force_change_pin=True",
      adm_log["ok"] and adm_log["data"].get("force_change_pin") is True)

# (م) فحص تحديث الرمز السري الإداري عبر profile_save بمعامل pin الجديد
save_pin_res = call(a, "profile_save", {"pin": "5566", "current_pin": "1234"})
check("profile_save with pin alias updates PIN and clears force_change_pin",
      save_pin_res["ok"] and save_pin_res["data"].get("force_change_pin") is False)
# استعادة الرمز إلى 1234 للحفاظ على حالة الاختبار
call(a, "profile_save", {"new_pin": "1234", "current_pin": "5566"})

# (ن) فحص نافذة معاينة المستند المحفوظ في sales_quotes.html ووجود فئات CSS المجمعة في app.css
sq_html_text = (ROOT / "web" / "sales_quotes.html").read_text(encoding="utf-8")
app_css_text = (ROOT / "web" / "app.css").read_text(encoding="utf-8")
check("sales_quotes.html doc-modal has constrained scrollable A4 preview & exit/back controls",
      'id="doc-modal-card"' in sq_html_text
      and 'id="modal-btn-close"' in sq_html_text
      and 'id="modal-btn-back-bottom"' in sq_html_text
      and "closeDocModal" in sq_html_text
      and "scrollTop = 0" in sq_html_text
      and "max-w-4xl" in app_css_text
      and "min-h-0" in app_css_text)

# (س) فحص حماية حذف العميل المدين أو المرتبط بفواتير + تصفية المديونيات والأداء
debt_list = call(a, "customers_list", {"limit": 50, "offset": 0, "debt_only": True})
check("customers_list debt_only filters only indebted customers",
      debt_list["ok"] and all(r["debt"] > 0 for r in debt_list["data"]["rows"])
      and debt_list["data"]["total"] == debt_list["data"]["summary"]["debt_customers_count"])

# محاولة حذف عميل عليه مديونية أو فواتير يجب أن ترفض، بينما عميل نظيف يُحذف بنجاح
if debt_list["data"]["rows"]:
    indebted_id = debt_list["data"]["rows"][0]["id"]
    del_indebted = call(a, "customers_delete", {"id": indebted_id})
    check("customers_delete blocks deleting indebted customer", not del_indebted["ok"])
clean_cust = call(a, "customers_save", {"name": "عميل قابل للحذف", "phone": "01999888777"})
check("clean customer created for delete check", clean_cust["ok"])
del_clean = call(a, "customers_delete", {"id": clean_cust["data"]["id"]})
check("customers_delete allows deleting clean customer with no history", del_clean["ok"])

# اختبار سرعة customers_list على 1000 عميل في قاعدة اختبار
import time as _time
with db.connect() as _c:
    _now = db.now()
    _c.executemany(
        "INSERT INTO customers(name, phone, created_at) VALUES(?,?,?)",
        [(f"عميل سرعة {i}", f"018{i:08d}", _now) for i in range(1000)],
    )
_t0 = _time.perf_counter()
_perf_res = call(a, "customers_list", {"limit": 50, "offset": 0})
_elapsed = _time.perf_counter() - _t0
check(f"customers_list handles 1000+ customers fast ({_elapsed*1000:.1f}ms < 500ms)",
      _perf_res["ok"] and _perf_res["data"]["summary"]["total_customers"] >= 1000 and _elapsed < 0.5)

# (ع) فحص customers_search مع limit وتعديل شراء مستعمل (used_update) وتمرير buy_used.html
cs_lim = call(a, "customers_search", {"q": "", "limit": 8})
check("customers_search accepts limit=8 and caps results", cs_lim["ok"] and len(cs_lim["data"]) <= 8)

u_created = call(a, "used_create", {
    "seller_name": "بائع للتعديل", "seller_phone": "01012340000",
    "device_type": "هاتف ذكي", "brand": "Apple", "model": "iPhone 13",
    "serial": "SN-USED-UPD-1", "condition": "جيد جداً",
    "buy_price": 10000, "resale_price": 13500, "to_inventory": True,
})
check("used_create returns id for update test", u_created["ok"] and bool(u_created["data"].get("id")))
if u_created["ok"]:
    u_upd = call(a, "used_update", {
        "id": u_created["data"]["id"],
        "seller_name": "بائع معدل", "seller_phone": "01012340000",
        "device_type": "هاتف ذكي", "brand": "Apple", "model": "iPhone 13 Pro",
        "serial": "SN-USED-UPD-2", "condition": "ممتاز",
        "buy_price": 11000, "resale_price": 14500,
    })
    check("used_update edits purchase and syncs linked product/serial", u_upd["ok"])
    with db.connect() as _c:
        _sn2 = _c.execute("SELECT * FROM serials WHERE serial='SN-USED-UPD-2'").fetchone()
        _pr2 = _c.execute("SELECT * FROM products WHERE id=?", (u_created["data"]["product_id"],)).fetchone()
        check("used_update synced product cost/price/serial",
              _sn2 is not None and _pr2 is not None and _pr2["cost"] == 1100000 and _pr2["price"] == 1450000)

bu_html_text = (ROOT / "web" / "buy_used.html").read_text(encoding="utf-8")
check("buy_used.html has min-h-0 scroll fix & edit support",
      "lg:grid-rows-[minmax(0,1fr)]" in bu_html_text
      and "min-h-0" in bu_html_text
      and "startEditUsed" in bu_html_text
      and "used_update" in bu_html_text)

# (ف) فحص دفتر الأستاذ (customer_ledger) وتحديث أرصدة العملاء والترحيل التلقائي (Phase C)
call(a, "settings_save", {"tax_enabled": "0"})
call(a, "product_adjust", {"id": pid, "qty_change": 10, "reason": "فحص دفتر الأستاذ"})
if not (call(a, "shift").get("data") or {}).get("shift"):
    call(a, "shift_open", {"opening_cash": 0})
lg_cust = call(a, "customers_save", {"name": "عميل دفتر الأستاذ", "phone": "01777666555"})
check("ledger test customer created", lg_cust["ok"])
lg_cid = lg_cust["data"]["id"]

# 1) فاتورة آجلة بقيمة 240 جنيه (2 وحدة × 120) -> قيد credit_sale = 24000
lg_sale = call(a, "sale_create", {
    "items": [{"product_id": pid, "qty": 2}],
    "payments": [{"method": "credit", "amount": 240}],
    "customer_name": "عميل دفتر الأستاذ",
    "customer_phone": "01777666555",
})
check("ledger credit sale created", lg_sale["ok"])
lg_sid = lg_sale["data"]["sale_id"]
with db.connect() as _c:
    _crow = _c.execute("SELECT total_purchases, credit_total, paid_total, debt FROM customers WHERE id=?", (lg_cid,)).fetchone()
    _lrows = _c.execute("SELECT * FROM customer_ledger WHERE customer_id=? ORDER BY id", (lg_cid,)).fetchall()
    check("customer_ledger recorded credit_sale & updated cached debt",
          _crow["debt"] == 24000 and _crow["credit_total"] == 24000 and len(_lrows) == 1
          and _lrows[0]["kind"] == "credit_sale" and _lrows[0]["debit"] == 24000 and _lrows[0]["balance_after"] == 24000)

# 2) سند قبض 100 جنيه -> الرصيد يصبح 14000 (voucher)
lg_pay = call(a, "customer_payment_create", {
    "customer_id": lg_cid, "amount": 100, "method": "cash", "notes": "سداد جزئي"
})
check("ledger payment voucher ok", lg_pay["ok"] and lg_pay["data"]["remaining_debt"] == 14000)
lg_vid = lg_pay["data"]["id"]

# 3) حذف سند القبض -> يسجل قيد عكسي adjustment ويعود الرصيد إلى 24000
lg_pdel = call(a, "customer_payment_delete", {"id": lg_vid})
check("ledger voucher delete ok", lg_pdel["ok"])
with db.connect() as _c:
    _crow2 = _c.execute("SELECT debt, paid_total FROM customers WHERE id=?", (lg_cid,)).fetchone()
    _l2 = _c.execute("SELECT kind, debit, credit, balance_after FROM customer_ledger WHERE customer_id=? ORDER BY id DESC LIMIT 1", (lg_cid,)).fetchone()
    check("customer_payment_delete reversed balance via adjustment entry",
          _crow2["debt"] == 24000 and _crow2["paid_total"] == 0
          and _l2["kind"] == "adjustment" and _l2["debit"] == 10000 and _l2["balance_after"] == 24000)

# 4) مرتجع جزئي على الفاتورة الآجلة (1 وحدة = 12000) -> قيد return_credit والرصيد 12000
lg_sdet = call(a, "sale", {"id": lg_sid})["data"]
lg_si_id = lg_sdet["items"][0]["id"]
lg_ret = call(a, "sale_return", {
    "sale_id": lg_sid, "items": [{"sale_item_id": lg_si_id, "qty": 1}], "reason": "تعديل كمية"
})
check("ledger partial return on credit sale ok", lg_ret["ok"] and lg_ret["data"]["total"] == 12000)
with db.connect() as _c:
    _crow3 = _c.execute("SELECT debt, credit_total FROM customers WHERE id=?", (lg_cid,)).fetchone()
    _l3 = _c.execute("SELECT kind, credit, balance_after FROM customer_ledger WHERE customer_id=? ORDER BY id DESC LIMIT 1", (lg_cid,)).fetchone()
    check("sale_return appended return_credit & lowered cached debt",
          _crow3["debt"] == 12000 and _crow3["credit_total"] == 12000
          and _l3["kind"] == "return_credit" and _l3["credit"] == 12000 and _l3["balance_after"] == 12000)

# 5) تحويل عرض سعر بآجل جزئي يسجل قيداً في customer_ledger
lg_q = call(a, "quotation_save", {
    "doc_type": "quote",
    "customer_name": "عميل دفتر الأستاذ",
    "customer_phone": "01777666555",
    "items": [{"product_id": pid, "name": "صنف عرض", "qty": 1, "unit_price": 200}],
    "paid_amount": 50,
    "payment_method": "cash",
})
check("ledger test quote saved", lg_q["ok"])
lg_qconv = call(a, "quotation_convert_to_sale", {"id": lg_q["data"]["id"], "paid_amount": 50, "payment_method": "cash"})
check("quote converted to partial-credit sale", lg_qconv["ok"])
with db.connect() as _c:
    _crow4 = _c.execute("SELECT debt FROM customers WHERE id=?", (lg_cid,)).fetchone()
    check("converted credit quote increased customer debt & ledger", _crow4["debt"] == 27000)

# 6) محاكاة ترحيل _migrate_customer_ledger عند مسح دفتر الأستاذ وإعادة تشغيل الاتصال
with db.connect() as _c:
    _c.execute("DELETE FROM customer_ledger")
    _c.execute("UPDATE customers SET total_purchases=0, credit_total=0, paid_total=0, debt=0")
    _c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES('customer_ledger_migrated', '0')")
db._INITIALIZED_DBS.discard(db.db_path())
with db.connect() as _c:
    _migrated_flag = _c.execute("SELECT value FROM settings WHERE key='customer_ledger_migrated'").fetchone()["value"]
    _crow_mig = _c.execute("SELECT debt, credit_total FROM customers WHERE id=?", (lg_cid,)).fetchone()
    _lcount_mig = _c.execute("SELECT COUNT(*) FROM customer_ledger WHERE customer_id=?", (lg_cid,)).fetchone()[0]
    check("_migrate_customer_ledger accurately backfills debt and ledger rows",
          _migrated_flag == "1" and _crow_mig["debt"] == 27000 and _crow_mig["credit_total"] == 27000 and _lcount_mig >= 2)

# 13c) فحص نظام الأقساط المتكامل (المرحلة D): الصلاحيات، العقود المباشرة، التحصيل، الإلغاء، تحويل فاتورة آجلة، التنبيهات، وواتساب
# أ) فحص صلاحيات الكاشير: مسموح بالعرض وممنوع من إنشاء/تحصيل/إلغاء الأقساط افتراضياً
call(a, "login", {"username": "cashier", "pin": "1111"})
check("cashier can view installments_list", call(a, "installments_list")["ok"])
check("cashier denied installment_create", not call(a, "installment_create", {
    "customer_name": "عميل مرفوض", "title": "جهاز", "principal": 1000, "months": 2
})["ok"])
call(a, "login", {"username": "admin", "pin": "1234"})

# ب) إنشاء منتج ومخزون مخصص + عميل مخصص + فتح عقد تقسيط مباشر بـ 10% زيادة على 3 شهور
ip_cat = call(a, "categories")["data"][0]["id"]
ip_res = call(a, "product_save", {
    "name": "هاتف فحص تقسيط D", "sku": "INST-TEST-D1", "category_id": ip_cat,
    "cost": 800, "price": 1200, "min_qty": 1, "tracked": 0,
})
check("installment test product created", ip_res["ok"])
inst_pid = ip_res["data"]["id"]
call(a, "product_adjust", {"id": inst_pid, "qty_change": 4, "reason": "رصيد اختبار أقساط"})

ic_res = call(a, "customers_save", {"name": "عميل أقساط اختبار", "phone": "01022334455"})
check("installment test customer created", ic_res["ok"])
inst_cid = ic_res["data"]["id"]

# مقدم 200 من 1200 -> المتبقي الأساسي 1000، زيادة 10% = 100، المقسّط = 1100 ج.م على 3 أقساط (110000 قرش)
p_standalone = call(a, "installment_create", {
    "customer_id": inst_cid,
    "product_id": inst_pid,
    "qty": 1,
    "down_payment": 200,
    "down_method": "cash",
    "fee_type": "percent",
    "fee_value": 10,
    "months": 3,
    "frequency": "monthly",
    "start_date": "2020-01-01",  # تاريخ ماضٍ لاختبار تنبيهات التأخير
    "national_id": "29901010123456",
    "guarantor_name": "ضامن اختبار",
    "guarantor_phone": "01122334455",
})
check("standalone installment_create succeeds", p_standalone["ok"] and p_standalone["data"]["financed_total"] == 110000)
plan_id = p_standalone["data"]["id"]
plan_det = call(a, "installment_detail", {"id": plan_id})["data"]
plan_items = plan_det["items"]
check("installment schedule sums exactly to financed_total & deducts stock",
      len(plan_items) == 3
      and sum(it["amount"] for it in plan_items) == 110000
      and call(a, "product", {"id": inst_pid})["data"]["qty"] == 3)
check("standalone installment syncs customer debt & prevents customer deletion",
      call(a, "customer_history", {"id": inst_cid})["data"]["customer"]["debt"] == 110000
      and not call(a, "customers_delete", {"id": inst_cid})["ok"])

# ج) فحص التنبيهات وتذكير واتساب
al_res = call(a, "installment_alerts")
check("installment_alerts detects overdue installment",
      al_res["ok"] and al_res["data"]["overdue_count"] >= 1 and al_res["data"]["overdue_amount"] >= 110000)

import webbrowser as _wb_inst
_orig_wb_inst = _wb_inst.open
_wb_inst.open = lambda url, *args, **kwargs: True
try:
    wa_inst = call(a, "installment_whatsapp_reminder", {"plan_id": plan_id, "open_app": False})
    check("installment_whatsapp_reminder returns message & EG phone",
          wa_inst["ok"] and wa_inst["data"]["phone"] == "201022334455" and p_standalone["data"]["plan_no"] in wa_inst["data"]["message"])
finally:
    _wb_inst.open = _orig_wb_inst

# د) تحصيل الأقساط + رفض الزيادة عن المتبقي + رفض المحفظة بلا مرجع + مطابقة تقرير الوردية
check("installment_pay rejects overpay", not call(a, "installment_pay", {"plan_id": plan_id, "amount": 5000, "method": "cash"})["ok"])
check("installment_pay rejects wallet without ref_no", not call(a, "installment_pay", {"plan_id": plan_id, "amount": 100, "method": "wallet"})["ok"])

pay1 = call(a, "installment_pay", {"plan_id": plan_id, "amount": 500, "method": "cash", "notes": "دفعة أولى"})
check("installment_pay partial/multi-item allocates cleanly",
      pay1["ok"] and pay1["data"]["remaining_total"] == 60000 and pay1["data"]["status"] == "active")
sh_inst = call(a, "shift_summary")
check("shift_summary includes cash_installments (down + installment payment)",
      sh_inst["ok"] and sh_inst["data"]["cash_installments"] >= 70000)
check("cannot cancel installment plan after payments", not call(a, "installment_cancel", {"plan_id": plan_id})["ok"])

pay2 = call(a, "installment_pay", {"plan_id": plan_id, "amount": 600, "method": "wallet", "ref_no": "IPAY-7788"})
check("installment_pay settles full plan & zeroes customer debt",
      pay2["ok"] and pay2["data"]["status"] == "completed" and pay2["data"]["remaining_total"] == 0
      and call(a, "customer_history", {"id": inst_cid})["data"]["customer"]["debt"] == 0)

# هـ) فحص إلغاء عقد غير مدفوع وإعادة المخزون وعكس قيد الدفتر
p_cancel_res = call(a, "installment_create", {
    "customer_id": inst_cid, "product_id": inst_pid, "qty": 1,
    "down_payment": 0, "fee_type": "fixed", "fee_value": 100, "months": 2,
})
check("second installment plan created & stock decremented",
      p_cancel_res["ok"] and call(a, "product", {"id": inst_pid})["data"]["qty"] == 2
      and call(a, "customer_history", {"id": inst_cid})["data"]["customer"]["debt"] == 130000)
cancel_ok = call(a, "installment_cancel", {"plan_id": p_cancel_res["data"]["id"], "reason": "عدول العميل"})
check("installment_cancel restores stock & reverses customer debt",
      cancel_ok["ok"] and call(a, "product", {"id": inst_pid})["data"]["qty"] == 3
      and call(a, "customer_history", {"id": inst_cid})["data"]["customer"]["debt"] == 0)

# و) تحويل فاتورة آجلة قائمة إلى أقساط بدون ازدواج في المديونية
# فاتورة بـ 1000 ج.م آجل بالكامل، ثم تحويلها بأقساط مع مقدم 200 ج.م ورسوم ثابتة 100 ج.م -> إجمالي المقسّط والمديونية = 900 ج.م (90000 قرش)
call(a, "settings_save", {"tax_enabled": "0"})
inv_sale = call(a, "sale_create", {
    "customer_name": "عميل أقساط اختبار",
    "customer_phone": "01022334455",
    "items": [{"product_id": inst_pid, "qty": 1, "unit_price": 1000}],
    "payments": [{"method": "credit", "amount": 1000}],
})
check("credit sale for installment conversion created", inv_sale["ok"])
elig_before = call(a, "installment_eligible_sales", {"customer_id": inst_cid})
check("installment_eligible_sales lists credit sale before conversion",
      elig_before["ok"] and any(x["id"] == inv_sale["data"]["sale_id"] for x in elig_before["data"]))
p_conv = call(a, "installment_create", {
    "customer_id": inst_cid,
    "sale_id": inv_sale["data"]["sale_id"],
    "down_payment": 200,
    "down_method": "cash",
    "fee_type": "fixed",
    "fee_value": 100,
    "months": 3,
})
elig_after = call(a, "installment_eligible_sales", {"customer_id": inst_cid})
hist_conv = call(a, "customer_history", {"id": inst_cid})["data"]
check("sale conversion prevents double-counting debt & removes from eligible list",
      p_conv["ok"]
      and p_conv["data"]["financed_total"] == 90000
      and hist_conv["customer"]["debt"] == 90000
      and hist_conv["ledger"][0]["balance_after"] == 90000
      and not any(x["id"] == inv_sale["data"]["sale_id"] for x in elig_after["data"]))

# ز) التحقق من صفحة installments.html وتكامل المودالات والصلاحيات
inst_html_text = (ROOT / "web" / "installments.html").read_text(encoding="utf-8")
check("installments.html exists with create/detail/pay modals",
      "id=\"create-modal\"" in inst_html_text and "id=\"detail-modal\"" in inst_html_text and "id=\"pay-modal\"" in inst_html_text)

# 13b) وضع المالك الرئيسي — المرحلة 1 (المصادقة، القفل، مفتاح الاسترداد، وتصفير رمز المدير)
call(a, "login", {"username": "cashier", "pin": "1111"})
check("owner_setup rejected for cashier", not call(a, "owner_setup", {"passphrase": "OwnerSecret#2026"})["ok"])
check("owner_setup rejects short passphrase", (call(a, "login", {"username": "admin", "pin": "1234"})["ok"] and not call(a, "owner_setup", {"passphrase": "short"})["ok"]))
ow_setup = call(a, "owner_setup", {"passphrase": "OwnerSecret#2026"})
rec_key_1 = ow_setup.get("data", {}).get("recovery_key", "") if ow_setup["ok"] else ""
check("owner_setup succeeds for admin & returns one-time recovery key",
      ow_setup["ok"] and len(rec_key_1) >= 20 and call(a, "owner_status")["data"]["active"])
check("owner_setup cannot run twice", not call(a, "owner_setup", {"passphrase": "AnotherSecret#2026"})["ok"])
check("owner logout clears owner session & admin cannot call owner-only methods",
      call(a, "owner_logout")["ok"] and not call(a, "owner_audit_list", {})["ok"] and not call(a, "owner_change_passphrase", {"old_passphrase": "OwnerSecret#2026", "new_passphrase": "NewSecret#2026"})["ok"])
check("logout clears owner session too",
      call(a, "owner_login", {"passphrase": "OwnerSecret#2026"})["ok"] and call(a, "logout")["ok"] and not call(a, "owner_status")["data"]["active"])
# اختبار القفل بعد 5 محاولات خاطئة واستمراره عبر مثيل جديد
for _ in range(4):
    call(a, "owner_login", {"passphrase": "WrongOwnerSecret"})
lock_resp = call(a, "owner_login", {"passphrase": "WrongOwnerSecret"})
a_reloaded = api_mod.Api()
lock_persist = call(a_reloaded, "owner_login", {"passphrase": "OwnerSecret#2026"})
check("owner lockout triggers on 5th wrong attempt & persists across reconnect",
      (not lock_resp["ok"]) and "[LOCKED:" in lock_resp["error"] and (not lock_persist["ok"]) and "[LOCKED:" in lock_persist["error"])
# مسح القفل لاختبار الاسترداد وتصفير رمز المدير
with db.connect() as _oc:
    _oc.execute("UPDATE owner_auth SET fail_state='{\"count\":0,\"locked_until\":0}' WHERE id=1")
ow_rec = call(a, "owner_recover", {"recovery_key": rec_key_1, "new_passphrase": "RecoveredOwner#2026"})
rec_key_2 = ow_rec.get("data", {}).get("recovery_key", "") if ow_rec["ok"] else ""
check("owner_recover rotates recovery key & invalidates old key",
      ow_rec["ok"] and rec_key_2 and rec_key_2 != rec_key_1 and not call(a, "owner_recover", {"recovery_key": rec_key_1, "new_passphrase": "Xyz123456"})["ok"])
# اختبار انتهاء صلاحية جلسة المالك بعد المهلة
import api_common as _api_common_mod
_orig_time_fn = _api_common_mod.time.time
try:
    _api_common_mod._STATE["owner"] = {"until": _orig_time_fn() + 10, "backed_up": False}
    _api_common_mod.time.time = lambda: _orig_time_fn() + 120
    check("owner session expires after idle timeout", not call(a, "owner_audit_list", {})["ok"])
finally:
    _api_common_mod.time.time = _orig_time_fn
# تصفير رمز المدير بعبارة المرور وبمفتاح الاسترداد + التحقق من عدم كشف التجزئات
rst_weak = call(a, "owner_reset_admin_pin", {"secret": "RecoveredOwner#2026", "new_pin": "1234"})
rst_pass = call(a, "owner_reset_admin_pin", {"secret": "RecoveredOwner#2026", "new_pin": "7531"})
rst_rec = call(a, "owner_reset_admin_pin", {"secret": rec_key_2, "new_pin": "8642"})
check("owner_reset_admin_pin enforces PIN strength & works with passphrase and recovery key",
      (not rst_weak["ok"]) and rst_pass["ok"] and rst_rec["ok"] and call(a, "login", {"username": "admin", "pin": "8642"})["ok"])
call(a, "owner_login", {"passphrase": "RecoveredOwner#2026"})
aud_rows = call(a, "owner_audit_list", {"limit": 20})
_raw_dump = repr(aud_rows) + repr(call(a, "owner_status"))
check("audit log records owner actions & secrets never leak in responses",
      aud_rows["ok"] and len(aud_rows["data"]) >= 4 and "RecoveredOwner#2026" not in _raw_dump and "pass_hash" not in _raw_dump and "recovery_hash" not in _raw_dump)
call(a, "owner_logout")

# 13c) سجل الأقسام والحارس الخادمي — المرحلة 2
import modules_map as _mmap
_public_api_methods = {n for n in dir(api_mod.Api) if not n.startswith("_") and callable(getattr(api_mod.Api, n)) and n != "call"}
_unclassified = _public_api_methods - (set(_mmap.API_MODULE_MAP.keys()) | set(_mmap.CORE_METHODS))
check(f"every public Api method is classified in modules_map ({len(_public_api_methods)} methods)", not _unclassified)
if _unclassified:
    print("UNCLASSIFIED METHODS:", _unclassified)

call(a, "owner_login", {"passphrase": "RecoveredOwner#2026"})
m_all = call(a, "modules_all")
check("modules_all returns 13 seeded builtin modules", m_all["ok"] and len(m_all["data"]) == 13)
check("core modules (settings/profile/receipt) cannot be disabled",
      (not call(a, "module_toggle", {"key": "settings", "enabled": False})["ok"])
      and (not call(a, "module_toggle", {"key": "profile", "enabled": False})["ok"])
      and (not call(a, "module_toggle", {"key": "receipt", "enabled": False})["ok"]))
check("dependent module toggle refused (inventory while pos/repair/quotes/installments active)",
      not call(a, "module_toggle", {"key": "inventory", "enabled": False})["ok"])
for _dep_mod in ("pos", "sales_quotes", "installments", "repair"):
    assert call(a, "module_toggle", {"key": _dep_mod, "enabled": False})["ok"]
tog_inv_off = call(a, "module_toggle", {"key": "inventory", "enabled": False})
ui_off = call(a, "ui_config")
check("disabling inventory blocks products_search/product_save even for admin while core works",
      tog_inv_off["ok"]
      and (not call(a, "products_search", {"q": ""})["ok"])
      and (not call(a, "product_save", {"sku": "BLK-1", "name": "Blocked"})["ok"])
      and call(a, "session")["ok"]
      and call(a, "settings")["ok"]
      and ui_off["ok"]
      and not any(m["key"] == "inventory" for m in ui_off["data"]["modules"]))
check("disabled module rejected as default_start_page in settings_save",
      not call(a, "settings_save", {"default_start_page": "inventory"})["ok"])
# إعادة التفعيل عبر modules_reset_defaults واستعادة الترتيب
rst_mods = call(a, "modules_reset_defaults", {})
reord = call(a, "module_reorder", {"keys": ["inventory", "pos"]})
check("re-enable & reorder restore ui_config and inventory API access",
      rst_mods["ok"]
      and reord["ok"]
      and reord["data"][0]["key"] == "inventory"
      and call(a, "products_search", {"q": ""})["ok"])
call(a, "modules_reset_defaults", {})
# اختبار الترحيل غير المدمر على قاعدة بيانات موجودة مسبقاً دون جدول modules
with db.connect() as _mc:
    _mc.execute("DROP TABLE modules")
    _mc.commit()
db._INITIALIZED_DBS.discard(os.environ["SHOP_DB"])
with db.connect() as _mc2:
    _c1 = _mc2.execute("SELECT COUNT(*) c FROM modules").fetchone()["c"]
    db.seed_modules_if_empty(_mc2)
    _c2 = _mc2.execute("SELECT COUNT(*) c FROM modules").fetchone()["c"]
    _p_cnt = _mc2.execute("SELECT COUNT(*) c FROM products").fetchone()["c"]
check("idempotent module migration preserves existing data and seeds 13 modules once",
      _c1 == 13 and _c2 == 13 and _p_cnt > 0)
call(a, "owner_logout")

# 13d) تعديل ونسخ وحذف الأقسام — المرحلة 3
call(a, "owner_login", {"passphrase": "RecoveredOwner#2026"})
cln = call(a, "module_clone", {"source_key": "inventory", "title": "مخزون فرعي", "params": "category_id=2"})
cln_key = cln["data"]["key"] if cln["ok"] else ""
check("module_clone creates custom alias opening source page with params",
      cln["ok"]
      and cln_key.startswith("c_")
      and cln["data"]["url"] == "inventory.html"
      and cln["data"]["full_url"] == "inventory.html?category_id=2"
      and not cln["data"]["is_builtin"]
      and cln["data"]["perm_keys"] == ["inventory_view", "inventory_edit"])
check("module validation rejects bad icon, color, params & empty title",
      (not call(a, "module_clone", {"source_key": "inventory", "title": "bad icon", "icon": "bad icon!"})["ok"])
      and (not call(a, "module_clone", {"source_key": "inventory", "title": "bad col", "color": "javascript:alert(1)"})["ok"])
      and (not call(a, "module_clone", {"source_key": "inventory", "title": "bad par", "params": "x=<script>"})["ok"])
      and (not call(a, "module_save", {"key": cln_key, "title": "   "})["ok"]))
msave = call(a, "module_save", {"key": cln_key, "title": "مخزون محدث", "icon": "category", "color": "#2563eb", "params": "cat=5"})
check("module_save updates metadata & params on custom clone",
      msave["ok"] and msave["data"]["title"] == "مخزون محدث" and msave["data"]["full_url"] == "inventory.html?cat=5")
check("module_delete refuses builtin/core modules & deletes custom clone",
      (not call(a, "module_delete", {"key": "pos"})["ok"])
      and (not call(a, "module_delete", {"key": "settings"})["ok"])
      and call(a, "module_delete", {"key": cln_key})["ok"]
      and not any(m["key"] == cln_key for m in call(a, "modules_all")["data"]))
_bkp_dir = pathlib.Path(os.environ["SHOP_DB"]).parent / "backups"
_has_struct_bkp = _bkp_dir.exists() and any("before_structure_change" in p.name for p in _bkp_dir.glob("*.db"))
_aud_actions = {x["action"] for x in call(a, "owner_audit_list", {"limit": 50})["data"]}
check("automatic pre-structure backup created & audit log tracks clone/save/delete",
      _has_struct_bkp and {"module_clone", "module_save", "module_delete"}.issubset(_aud_actions))
call(a, "owner_logout")

# 13e) ملفات النشاط التجاري والمسميات — المرحلة 4
call(a, "owner_login", {"passphrase": "RecoveredOwner#2026"})
profs = call(a, "profiles_list")
check("profiles_list returns 4 business profiles with demo catalogs",
      profs["ok"] and len(profs["data"]) == 4 and all(p["demo_count"] >= 10 for p in profs["data"]))
# إضافة نسخة مخصصة قبل تغيير النشاط للتأكد من بقائها، وضبط صفحة البداية على repair لاختبار التراجع التلقائي
_custom_keep = call(a, "module_clone", {"source_key": "inventory", "title": "نسخة دائمة"})["data"]["key"]
call(a, "settings_save", {"default_start_page": "repair"})
dry = call(a, "profile_apply", {"key": "restaurant", "dry_run": True})
ui_before_dry = call(a, "ui_config")["data"]
check("profile_apply dry_run=True previews diff without modifying DB",
      dry["ok"]
      and dry["data"]["dry_run"]
      and not dry["data"]["applied"]
      and dry["data"]["demo_count"] >= 10
      and ui_before_dry["profile"] == "retail_electronics"
      and any(m["key"] == "repair" for m in ui_before_dry["modules"]))
ph_apply = call(a, "profile_apply", {"key": "pharmacy", "dry_run": False, "apply_demo": True})
ui_ph = call(a, "ui_config")["data"]
st_ph = call(a, "settings")["data"]
ph_prods = call(a, "products_search", {"q": "", "limit": 100})["data"]
ph_cats = [c["name"] for c in call(a, "categories")["data"]]
check("profile_apply pharmacy configures modules/labels, preserves clones & resets disabled start page",
      ph_apply["ok"]
      and ph_apply["data"]["applied"]
      and ui_ph["profile"] == "pharmacy"
      and not any(m["key"] in ("repair", "sales_quotes", "installments", "buy_used") for m in ui_ph["modules"])
      and any(m["key"] == _custom_keep for m in ui_ph["modules"])
      and ui_ph["labels"].get("module_inventory") == "الأدوية والمستلزمات"
      and st_ph.get("default_start_page") == "pos")
check("pharmacy apply seeds pharmacy demo products & hides electronics demo items/categories",
      any(p["sku"] == "PHM-PAN-EX" for p in ph_prods)
      and not any(p["sku"] == "MBP-M2-16" for p in ph_prods)
      and "مسكنات وخافض حرارة" in ph_cats
      and "لابتوبات" not in ph_cats)
# إضافة وتعديل وحذف قالب مخصص بالكامل مع بياناته التجريبية
_bad_dep_prof = call(a, "owner_profile_save", {"label": "قالب ناقص", "modules_enabled": ["pos"]})
_dup_sku_prof = call(a, "owner_profile_save", {
    "label": "قالب مكرر",
    "modules_enabled": ["pos", "inventory"],
    "demo_catalog": [
        {"sku": "DUP-1", "name": "صنف 1", "category": "فئة", "price": "10", "cost": "5", "qty": 5},
        {"sku": "DUP-1", "name": "صنف 2", "category": "فئة", "price": "20", "cost": "10", "qty": 5},
    ],
})
_new_prof = call(a, "owner_profile_save", {
    "key": "p_bakery",
    "label": "مخبز وحلواني",
    "description": "مخبوزات طازجة",
    "modules_enabled": ["pos", "inventory", "history", "reports"],
    "module_titles": {"inventory": "المخبوزات والخامات"},
    "labels": {"product_singular": "قطعة"},
    "default_start_page": "pos",
    "demo_catalog": [
        {"sku": "BKR-CRS-1", "name": "كرواسون زبدة", "category": "مخبوزات", "price": "35.50", "cost": "18.00", "qty": 25, "min_qty": 5},
    ],
})
_edit_prof = call(a, "owner_profile_save", {
    "key": "p_bakery",
    "label": "مخبز وحلواني محدث",
    "modules_enabled": ["pos", "inventory", "history"],
    "module_titles": {"inventory": "أصناف المخبز"},
    "labels": {"product_singular": "صنف"},
    "demo_catalog": [
        {"sku": "BKR-CRS-1", "name": "كرواسون زبدة فرنساوي", "category": "مخبوزات", "price": "40", "cost": "20", "qty": 30, "min_qty": 5},
    ],
})
_apply_bakery = call(a, "profile_apply", {"key": "p_bakery", "dry_run": False, "apply_demo": True})
_bakery_prods = call(a, "products_search", {"q": "BKR-CRS-1"})["data"]
check("owner_profile_save validates dependencies/SKUs, creates, edits & applies custom profile with demo items",
      (not _bad_dep_prof["ok"])
      and (not _dup_sku_prof["ok"])
      and _new_prof["ok"]
      and _edit_prof["ok"]
      and _edit_prof["data"]["label"] == "مخبز وحلواني محدث"
      and _apply_bakery["ok"]
      and len(_bakery_prods) == 1
      and _bakery_prods[0]["price"] == 4000
      and call(a, "ui_config")["data"]["labels"].get("product_singular") == "صنف")
_del_active_refused = call(a, "owner_profile_delete", {"key": "p_bakery"})
rst_prof = call(a, "profile_apply", {"key": "retail_electronics", "dry_run": False, "apply_demo": True})
_del_inactive_ok = call(a, "owner_profile_delete", {"key": "p_bakery"})
_rst_defs_ok = call(a, "owner_profiles_reset_defaults")
ui_ret = call(a, "ui_config")["data"]
ret_prods = call(a, "products_search", {"q": "", "limit": 100})["data"]
check("switching back to retail_electronics restores electronics catalog, owner_profile_delete guards active & deletes inactive",
      (not _del_active_refused["ok"])
      and rst_prof["ok"]
      and _del_inactive_ok["ok"]
      and _rst_defs_ok["ok"]
      and ui_ret["profile"] == "retail_electronics"
      and len([m for m in ui_ret["modules"] if m["is_builtin"]]) == 13
      and ui_ret["labels"] == {}
      and any(p["sku"] == "MBP-M2-16" for p in ret_prods)
      and not any(p["sku"] == "BKR-CRS-1" for p in ret_prods))
check("labels_save validates keys/length and updates ui_config labels",
      (not call(a, "labels_save", {"labels": {"unknown_key": "X"}})["ok"])
      and (not call(a, "labels_save", {"labels": {"product_singular": "x" * 41}})["ok"])
      and call(a, "labels_save", {"labels": {"product_singular": "صنف"}})["ok"]
      and call(a, "ui_config")["data"]["labels"].get("product_singular") == "صنف"
      and call(a, "labels_save", {"labels": {"product_singular": ""}})["ok"]
      and "product_singular" not in call(a, "ui_config")["data"]["labels"])
call(a, "module_delete", {"key": _custom_keep})

# اختبار exclusive_demo في إخفاء الفئات الفارغة + اختبار fresh_db مع نقل انتقائي للبيانات وبدونه
call(a, "categories_save", {"name": "فئة فارغة اختبارية"})
_excl_apply = call(a, "profile_apply", {"key": "pharmacy", "dry_run": False, "apply_demo": True, "exclusive_demo": True})
_excl_cats = [c["name"] for c in call(a, "categories")["data"]]
check("exclusive_demo hides empty non-profile categories too",
      _excl_apply["ok"] and "فئة فارغة اختبارية" not in _excl_cats and "مسكنات وخافض حرارة" in _excl_cats)
call(a, "profile_apply", {"key": "retail_electronics", "dry_run": False, "apply_demo": True, "exclusive_demo": False})

# اختبار إنشاء قاعدة جديدة نظيفة مع نقل العملاء فقط أولاً (قبل المسح الكامل)
_fresh_cust = call(a, "profile_apply", {
    "key": "pharmacy",
    "dry_run": False,
    "apply_demo": True,
    "fresh_db": True,
    "carry_over": {"products": False, "customers": True, "sales": False, "repairs": False},
})
with db.connect() as _fc:
    _fc_fk = _fc.execute("PRAGMA foreign_key_check").fetchall()
    _fc_custs = _fc.execute("SELECT COUNT(*) c FROM customers").fetchone()["c"]
    _fc_sales = _fc.execute("SELECT COUNT(*) c FROM sales").fetchone()["c"]
    _fc_prods = _fc.execute("SELECT COUNT(*) c FROM products").fetchone()["c"]
    _fc_users = _fc.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
check("fresh_db with selective customer carry-over keeps users & customers/debt, wipes sales & seeds demo only",
      _fresh_cust["ok"]
      and _fresh_cust["data"]["fresh_db"]
      and _fresh_cust["data"]["backup_file"]
      and "before_fresh_profile_db" in _fresh_cust["data"]["backup_file"]
      and not _fc_fk
      and _fc_users >= 2
      and _fc_custs > 0
      and _fc_sales == 0
      and _fc_prods == 11)

# اختبار إنشاء قاعدة جديدة فارغة تماماً (المستخدمون + البيانات التجريبية للنشاط فقط)
_fresh_empty = call(a, "profile_apply", {
    "key": "restaurant",
    "dry_run": False,
    "apply_demo": True,
    "fresh_db": True,
    "carry_over": {"products": False, "customers": False, "sales": False, "repairs": False},
    "reset_store_info": True,
})
with db.connect() as _fe:
    _fe_fk = _fe.execute("PRAGMA foreign_key_check").fetchall()
    _fe_custs = _fe.execute("SELECT COUNT(*) c FROM customers").fetchone()["c"]
    _fe_sales = _fe.execute("SELECT COUNT(*) c FROM sales").fetchone()["c"]
    _fe_repairs = _fe.execute("SELECT COUNT(*) c FROM repairs").fetchone()["c"]
    _fe_cats = _fe.execute("SELECT COUNT(*) c FROM categories").fetchone()["c"]
    _fe_prods = _fe.execute("SELECT COUNT(*) c FROM products").fetchone()["c"]
    _fe_users = _fe.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    _fe_own = _fe.execute("SELECT COUNT(*) c FROM owner_auth").fetchone()["c"]
check("fresh_db empty keeps users & owner_auth only + restaurant demo catalog with zero FK errors",
      _fresh_empty["ok"]
      and not _fe_fk
      and _fe_users >= 2
      and _fe_own == 1
      and _fe_custs == 0
      and _fe_sales == 0
      and _fe_repairs == 0
      and _fe_cats == 6
      and _fe_prods == 11)

call(a, "owner_logout")

# 13f) التحقق من واجهات وضع المالك وإغلاق الجلسة عند إغلاق النافذة — المرحلة 5
_own_html = (ROOT / "web" / "owner.html").read_text(encoding="utf-8")
_idx_html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
_desk_html = (ROOT / "web" / "desktop.html").read_text(encoding="utf-8")
_main_py = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
check("owner.html contains setup, recovery, tabs (modules/profiles/labels/security/audit) & idle timer",
      all(tok in _own_html for tok in ("view-setup", "view-recovery-reveal", "opane-modules", "opane-profiles", "opane-labels", "opane-security", "opane-audit", "modal-profile-form", "syncOwnerTimer")))
check("index.html & desktop.html wire long-press owner entry, reset-admin modal & dynamic UI_CONFIG",
      "modal-reset-admin-pin" in _idx_html and "owner.html" in _idx_html and "start-owner-trigger" in _desk_html and "UI_CONFIG.modules" in _desk_html)
check("pages include data-label hooks and main.py clears owner state on window close",
      all("data-label=" in (ROOT / "web" / fn).read_text(encoding="utf-8") for fn in ("pos.html", "inventory.html", "customers.html", "repair.html", "buy_used.html"))
      and "_on_window_closed" in _main_py and '_STATE["owner"] = None' in _main_py)

# 14) تطابق العقد: كل api('NAME') في الواجهة موجود في Api
names = set()
for p in list((ROOT / "web").glob("*.html")) + [ROOT / "web" / "desktop.html", ROOT / "web" / "sales_quotes.html", ROOT / "web" / "settings.html", ROOT / "web" / "staff.html", ROOT / "web" / "profile.html", ROOT / "web" / "app.js"]:
    if not p.exists(): continue
    names |= set(re.findall(r"api\(\s*['\"]([A-Za-z_]+)", p.read_text(encoding="utf-8")))
real = {n for n in dir(api_mod.Api) if not n.startswith("_") and callable(getattr(api_mod.Api, n)) and n != "call"}
missing = names - real
check(f"contract ok ({len(names)} names)", not missing)
if missing:
    print("MISSING:", missing)

# 15) مسار القاعدة بجانب المشروع + ترحيل القديمة لمرة واحدة
_shop_db_saved = os.environ.pop("SHOP_DB", None)
try:
    p = pathlib.Path(db.db_path())
    check("db beside project", p.name == "shop.db" and p.parent.name == "data" and ROOT in p.parents)
    with tempfile.TemporaryDirectory() as td:
        legacy = pathlib.Path(td) / "legacy.db"
        target = pathlib.Path(td) / "new.db"
        legacy.write_bytes(b"fake-legacy-db")
        os.environ["SHOP_DB"] = str(target)
        os.environ["SHOP_DB_LEGACY"] = str(legacy)
        try:
            db._migrate_once()
            check("legacy migrated", target.read_bytes() == b"fake-legacy-db")
        finally:
            os.environ.pop("SHOP_DB_LEGACY", None)
finally:
    if _shop_db_saved is not None:
        os.environ["SHOP_DB"] = _shop_db_saved

print(f"\nALL {N} CHECKS PASSED")
