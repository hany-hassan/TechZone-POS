"""
سكريبت التقاط لقطات شاشة لجميع صفحات نظام تك زون للإلكترونيات وحفظها في screenshots/
يعمل على قاعدة بيانات مؤقتة غنية بالبيانات التجريبية دون المساس بقاعدة التشغيل الفعلية.
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT_DIR, "app"))

_TMP_DIR = tempfile.mkdtemp(prefix="tz_snap_")
os.environ["SHOP_DB"] = os.path.join(_TMP_DIR, "snap.db")

import api
import api_common
import db

SCREENSHOTS_DIR = os.path.join(ROOT_DIR, "screenshots")
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

api_instance = api.Api()


class TechZoneServer(SimpleHTTPRequestHandler):
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".woff2": "font/woff2",
        ".woff": "font/woff",
        ".ttf": "font/ttf",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=os.path.join(ROOT_DIR, "web"), **kwargs)

    def do_POST(self):
        if self.path == "/api/call":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            data = json.loads(body)
            name = data.get("name")
            payload = data.get("payload")
            res = api_instance.call(name, payload)
            out = json.dumps(res, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)
        else:
            self.send_error(404)

    def log_message(self, format, *args):
        pass


def run_server():
    httpd = HTTPServer(("127.0.0.1", 0), TechZoneServer)
    port = httpd.server_address[1]
    return httpd, port


def seed_demo_activity():
    api_instance.login(username="admin", pin="1234")
    api_instance.shift_open(opening_cash=1500)
    prods = [p for p in api_instance.products_search(q="", limit=30) if p["qty"] >= 5 and not p["tracked"]]
    prods.sort(key=lambda x: -x["price"])
    p1 = prods[0]["id"]
    p2 = prods[1]["id"]
    c1 = api_instance.customers_save(name="محمد علي محمود", phone="01012345678")["id"]
    t1 = round((prods[0]["price"] / 100.0) * 1.14, 2)
    cash1 = round(t1 * 0.4, 2)
    cred1 = round(t1 - cash1, 2)
    t2 = round(((prods[1]["price"] * 2) / 100.0) * 1.14, 2)
    api_instance.sale_create(
        customer_name="محمد علي محمود",
        customer_phone="01012345678",
        items=[{"product_id": p1, "qty": 1, "unit_price": prods[0]["price"] / 100.0}],
        payments=[{"method": "cash", "amount": cash1}, {"method": "credit", "amount": cred1}],
    )
    api_instance.sale_create(
        customer_name="عميل نقدي",
        items=[{"product_id": p2, "qty": 2, "unit_price": prods[1]["price"] / 100.0}],
        payments=[{"method": "cash", "amount": t2}],
    )
    api_instance.installment_create(
        customer_id=c1,
        title="تقسيط جهاز مكتبي ديل أوبتيبليكس",
        principal=5000,
        down_payment=1000,
        down_method="cash",
        fee_type="percent",
        fee_value=10,
        months=6,
    )
    api_instance.quotation_save(
        doc_type="quote",
        customer_name="شركة النور للتوريدات",
        customer_phone="01099887766",
        items=[{"product_id": p1, "name": prods[0]["name"], "qty": 2, "unit_price": prods[0]["price"] / 100.0}],
    )
    api_instance.repair_create(
        customer_name="كريم سامي",
        customer_phone="01122334455",
        device_type="لابتوب HP Pavilion",
        problem="تغيير شاشة + تنظيف وصيانة تبريد",
        cost=850,
    )
    api_instance.used_create(
        seller_name="طارق حسن",
        seller_phone="01234567890",
        seller_id_no="29501011234567",
        device_type="هاتف",
        brand="Apple",
        model="iPhone 13 128GB",
        serial="356789012345678",
        condition="ممتاز",
        buy_price=18500,
        resale_price=21500,
    )
    api_instance.db_backup(reason="demo_snapshot")
    api_instance.owner_setup(passphrase="DemoOwner#2026")
    api_common._STATE["owner"] = {"until": time.time() + 3600, "backed_up": False}


PAGES = [
    ("01_login_screen.png", "index.html", 2500, (1440, 900)),
    ("02_desktop_os.png", "desktop.html", 3500, (1440, 900)),
    ("03_pos_cashier.png", "pos.html", 3000, (1440, 900)),
    ("04_sales_invoices.png", "sales_quotes.html", 3000, (1440, 900)),
    ("05_inventory_management.png", "inventory.html", 3000, (1440, 900)),
    ("06_customers_debt.png", "customers.html", 3000, (1440, 900)),
    ("07_customer_statement.png", "customer_details.html?id=1", 3000, (1440, 900)),
    ("08_maintenance_repair.png", "repair.html", 3000, (1440, 900)),
    ("09_buy_used_devices.png", "buy_used.html", 3000, (1440, 900)),
    ("10_operations_history.png", "history.html", 3000, (1440, 900)),
    ("11_financial_reports.png", "reports.html", 3000, (1440, 900)),
    ("12_staff_permissions.png", "staff.html", 3000, (1440, 900)),
    ("13_employee_profile.png", "profile.html", 3000, (1440, 900)),
    ("14_system_settings.png", "settings.html?tab=store", 3000, (1440, 900)),
    ("15_invoice_studio.png", "settings.html?tab=invoices", 3500, (1440, 900)),
    ("16_receipt_preview.png", "receipt.html?id=1", 3000, (1440, 900)),
    ("17_installments.png", "installments.html", 3000, (1440, 900)),
    ("18_backups_restore.png", "settings.html?tab=backups", 3000, (1440, 900)),
    ("19_owner_modules.png", "owner.html", 3000, (1440, 900)),
    ("20_owner_profiles.png", "owner.html?tab=profiles", 3000, (1440, 900)),
]


def main():
    print("Seeding temporary snapshot DB...")
    seed_demo_activity()
    print("Starting background server on dynamic port...")
    httpd, port = run_server()
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    time.sleep(0.5)
    print(f"Server started on port {port}.")

    chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    if not os.path.exists(chrome_path):
        chrome_path = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    temp_profile = os.path.join(_TMP_DIR, "chrome_snap")

    try:
        for filename, page_url, budget_ms, (w, h) in PAGES:
            dest_path = os.path.join(SCREENSHOTS_DIR, filename)
            url = f"http://127.0.0.1:{port}/{page_url}"
            print(f"Capturing {filename} from {page_url}...")

            args = [
                chrome_path,
                "--headless=new",
                "--disable-gpu",
                f"--window-size={w},{h}",
                f"--virtual-time-budget={budget_ms}",
                f"--user-data-dir={temp_profile}",
                f"--screenshot={dest_path}",
                url,
            ]

            p = subprocess.run(args, capture_output=True, text=True, timeout=25)
            if os.path.exists(dest_path) and os.path.getsize(dest_path) > 0:
                print(f" -> OK: {filename} ({os.path.getsize(dest_path)} bytes)")
            else:
                print(f" -> FAILED: {filename}. stderr: {p.stderr}")
    finally:
        httpd.shutdown()
        shutil.rmtree(_TMP_DIR, ignore_errors=True)

    print("All captures completed.")


if __name__ == "__main__":
    main()
