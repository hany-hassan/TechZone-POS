"""Backend Api: كل دوال النظام + dispatcher واحد للواجهة (window.pywebview.api.call)."""
import datetime
import hmac
import json
import os
import pathlib
import sqlite3
import sys
import time
import traceback
from decimal import Decimal, ROUND_HALF_UP

import db

# حالة الجلسة (مستخدم واحد، نافذة واحدة) — الدور والصلاحيات تُقرأ من هنا وليس من JS
_STATE = {"user": None, "owner": None}

# مدة خمول جلسة المالك الرئيسي بالثواني (10 دقائق)
OWNER_SESSION_TTL = 600

# حماية من هجمات التخمين (brute-force) على تسجيل الدخول
_LOGIN_ATTEMPTS = {}  # key -> {"count": int, "locked_until": float}


class ApiError(Exception):
    pass


def _money(v, default=0):
    """عرض/مبالغ من الواجهة (وحدات كاملة 123.45) → INTEGER وحدات صغرى."""
    if v in (None, ""):
        return int(default)
    if isinstance(v, bool):
        raise ApiError("قيمة مبلغ غير صالحة")
    try:
        d = Decimal(str(v).strip()).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        raise ApiError("قيمة مبلغ غير صالحة")
    return int(d * 100)


def _int(v, default=0):
    if v in (None, ""):
        return int(default)
    try:
        return int(v)
    except Exception:
        raise ApiError("قيمة عددية غير صالحة")


def _validate_image_data_url(s, max_bytes=None):
    """التحقق من صحة data URL صورة (magic bytes) وحجمها."""
    if not isinstance(s, str) or not s.startswith("data:image/"):
        raise ApiError("صيغة الصورة غير صالحة (يجب أن تكون data:image/)")
    # رفض SVG/HTML
    if "svg" in s[:40].lower() or "html" in s[:40].lower():
        raise ApiError("صيغة الصورة غير مدعومة")
    if "," not in s:
        raise ApiError("صيغة الصورة غير صالحة")
    import base64
    try:
        b64_part = s.split(",", 1)[1]
        raw = base64.b64decode(b64_part, validate=True)
    except Exception:
        raise ApiError("بيانات الصورة غير صالحة (base64)")
    if max_bytes is not None and len(raw) > max_bytes:
        raise ApiError("حجم الصورة يتجاوز الحد المسموح")
    # magic bytes
    if raw.startswith(b"\xff\xd8\xff"):
        return True
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return True
    if raw.startswith(b"GIF87a") or raw.startswith(b"GIF89a"):
        return True
    if raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
        return True
    raise ApiError("صيغة الصورة غير مدعومة (JPEG/PNG/GIF/WebP فقط)")



# 1x1 white JPEG fallback for headless/CLI tests when canvas image is not passed
_FALLBACK_JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00"
    b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
    b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a"
    b"\x1f\x1e\x1d\x1a\x1c\x1c $.\' \",#\x1c\x1c(7),01444\x1f\'9=82<.342"
    b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4"
    b"\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b"
    b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xfb\xd2\x8a(\x03\xff\xd9"
)



def _win32_copy_pdf_to_clipboard(filepath: str) -> bool:
    """نسخ ملف الـ PDF إلى حافظة ويندوز (CF_HDROP = 15) مع التحقق والاحتياطي عبر PowerShell."""
    if os.name != "nt":
        return False
    import ctypes
    from ctypes import wintypes
    import struct
    import subprocess
    import time

    abs_path = str(pathlib.Path(filepath).resolve())
    CF_HDROP = 15
    GMEM_MOVEABLE = 0x0002
    GMEM_ZEROINIT = 0x0040

    kernel32 = ctypes.windll.kernel32
    user32 = ctypes.windll.user32

    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HANDLE
    kernel32.GlobalLock.argtypes = [wintypes.HANDLE]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HANDLE]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.argtypes = []
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
    user32.IsClipboardFormatAvailable.restype = wintypes.BOOL

    header = struct.pack("<IiiII", 20, 0, 0, 0, 1)
    path_bytes = abs_path.encode("utf-16le") + b"\x00\x00\x00\x00"
    payload = header + path_bytes

    for _ in range(8):
        if user32.OpenClipboard(None):
            try:
                user32.EmptyClipboard()
                h_global = kernel32.GlobalAlloc(GMEM_MOVEABLE | GMEM_ZEROINIT, len(payload))
                if h_global:
                    ptr = kernel32.GlobalLock(h_global)
                    if ptr:
                        ctypes.memmove(ptr, payload, len(payload))
                        kernel32.GlobalUnlock(h_global)
                        if user32.SetClipboardData(CF_HDROP, h_global):
                            return True
            finally:
                user32.CloseClipboard()
        time.sleep(0.06)

    # احتياطي عبر PowerShell Set-Clipboard -LiteralPath (يدعم UWP وWin32 Shell DataObject)
    try:
        ps_path = abs_path.replace("'", "''")
        subprocess.run(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", f"Set-Clipboard -LiteralPath '{ps_path}'"],
            timeout=4,
            check=False,
        )
        return bool(user32.IsClipboardFormatAvailable(CF_HDROP))
    except Exception:
        return False


def _find_whatsapp_hwnd():
    """البحث الدقيق عن مقبض نافذة واتساب الرئيسية المرئية (بأبعاد >= 300x300) على ويندوز."""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32

    def _title_of(hwnd):
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return ""
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value.replace("\u200e", "").replace("\u200f", "").strip()

    def _is_wa_title(title: str) -> bool:
        if not title:
            return False
        tl = title.lower()
        return ("whatsapp" in tl or "واتساب" in title) and "techzone" not in tl and "تك زون" not in title

    # 1) إذا كانت النافذة النشطة حالياً هي واتساب بالفعل، أعدها فوراً
    fg = user32.GetForegroundWindow()
    if fg and user32.IsWindowVisible(fg) and _is_wa_title(_title_of(fg)):
        return fg

    # 2) البحث بين جميع النوافذ المرئية واستبعاد النوافذ المساعدة الصغيرة (0x0 أو < 300px)
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    candidates = []

    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            title = _title_of(hwnd)
            if _is_wa_title(title):
                rect = wintypes.RECT()
                w = h = 0
                if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                    w = rect.right - rect.left
                    h = rect.bottom - rect.top
                is_iconic = bool(user32.IsIconic(hwnd))
                if is_iconic or (w >= 300 and h >= 300):
                    # أولوية لتطبيق WhatsApp Desktop (العنوان الدقيق) ثم نوافذ المتصفح
                    prio = 0 if title.lower() in ("whatsapp", "واتساب") else 1
                    candidates.append((prio, 1 if is_iconic else 0, -(w * h), hwnd))
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    if not candidates:
        return None
    candidates.sort()
    return candidates[0][3]


def _win32_send_ctrl_v() -> int:
    """إرسال ضغطة Ctrl+V عبر SendInput القياسي بحجم بنية Win32 الدقيق (40 بايت 64-bit / 28 بايت 32-bit) مع احتياطي keybd_event."""
    import ctypes
    from ctypes import wintypes
    import time

    INPUT_KEYBOARD = 1
    KEYEVENTF_KEYUP = 0x0002
    VK_LCONTROL = 0xA2
    VK_CONTROL = 0x11
    VK_V = 0x56

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", ctypes.c_int32),
            ("dy", ctypes.c_int32),
            ("mouseData", ctypes.c_uint32),
            ("dwFlags", ctypes.c_uint32),
            ("time", ctypes.c_uint32),
            ("dwExtraInfo", ctypes.c_size_t),
        ]

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", ctypes.c_uint16),
            ("wScan", ctypes.c_uint16),
            ("dwFlags", ctypes.c_uint32),
            ("time", ctypes.c_uint32),
            ("dwExtraInfo", ctypes.c_size_t),
        ]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [
            ("uMsg", ctypes.c_uint32),
            ("wParamL", ctypes.c_uint16),
            ("wParamH", ctypes.c_uint16),
        ]

    class _INPUT_UNION(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", ctypes.c_uint32), ("union", _INPUT_UNION)]

    user32 = ctypes.windll.user32
    user32.SendInput.argtypes = [ctypes.c_uint32, ctypes.POINTER(INPUT), ctypes.c_int]
    user32.SendInput.restype = ctypes.c_uint32

    scan_ctrl = user32.MapVirtualKeyW(VK_LCONTROL, 0)
    scan_v = user32.MapVirtualKeyW(VK_V, 0)

    def _key(vk, scan, flags=0):
        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        inp.union.ki = KEYBDINPUT(vk, scan, flags, 0, 0)
        return inp

    seq = (INPUT * 4)(
        _key(VK_LCONTROL, scan_ctrl, 0),
        _key(VK_V, scan_v, 0),
        _key(VK_V, scan_v, KEYEVENTF_KEYUP),
        _key(VK_LCONTROL, scan_ctrl, KEYEVENTF_KEYUP),
    )
    sent = int(user32.SendInput(4, seq, ctypes.sizeof(INPUT)) or 0)
    if sent != 4:
        user32.keybd_event(VK_CONTROL, user32.MapVirtualKeyW(VK_CONTROL, 0), 0, 0)
        time.sleep(0.03)
        user32.keybd_event(VK_V, scan_v, 0, 0)
        time.sleep(0.03)
        user32.keybd_event(VK_V, scan_v, KEYEVENTF_KEYUP, 0)
        time.sleep(0.03)
        user32.keybd_event(VK_CONTROL, user32.MapVirtualKeyW(VK_CONTROL, 0), KEYEVENTF_KEYUP, 0)
    time.sleep(0.06)
    return sent


def _win32_auto_paste_into_whatsapp(pdf_abs: str, was_already_open: bool = False):
    """تفعيل نافذة واتساب الرئيسية في المقدمة دون إفساد التركيز ولصق ملف الـ PDF كمرفق عبر Ctrl+V."""
    if os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes
    import time

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    # 1) انتظار ظهور نافذة واتساب وتصدرها للمقدمة (حتى 5 ثوانٍ)
    wa_hwnd = None
    t0 = time.monotonic()
    while (time.monotonic() - t0) < 5.0:
        wa_hwnd = _find_whatsapp_hwnd()
        if wa_hwnd and user32.GetForegroundWindow() == wa_hwnd:
            break
        if wa_hwnd and (time.monotonic() - t0) >= 1.2:
            break
        time.sleep(0.08)

    if not wa_hwnd:
        wa_hwnd = _find_whatsapp_hwnd()

    # 2) انتظار اكتمال فتح المحادثة وإدراج النص داخل واتساب
    time.sleep(0.95 if was_already_open else 2.40)

    # 3) تصدير نافذة واتساب للمقدمة فقط إذا لم تكن في المقدمة (مع عدم إلغاء التكبير Maximize)
    if wa_hwnd:
        try:
            if user32.IsIconic(wa_hwnd):
                user32.ShowWindow(wa_hwnd, 9)  # SW_RESTORE فقط إذا كانت مصغرة في شريط المهام
            fg_hwnd = user32.GetForegroundWindow()
            if fg_hwnd != wa_hwnd:
                user32.AllowSetForegroundWindow(-1)
                fg_tid = user32.GetWindowThreadProcessId(fg_hwnd, None) if fg_hwnd else 0
                wa_tid = user32.GetWindowThreadProcessId(wa_hwnd, None)
                cur_tid = kernel32.GetCurrentThreadId()
                if fg_tid and fg_tid != cur_tid:
                    user32.AttachThreadInput(cur_tid, fg_tid, True)
                if wa_tid and wa_tid != cur_tid:
                    user32.AttachThreadInput(cur_tid, wa_tid, True)
                user32.BringWindowToTop(wa_hwnd)
                user32.SetForegroundWindow(wa_hwnd)
                if wa_tid and wa_tid != cur_tid:
                    user32.AttachThreadInput(cur_tid, wa_tid, False)
                if fg_tid and fg_tid != cur_tid:
                    user32.AttachThreadInput(cur_tid, fg_tid, False)
                time.sleep(0.18)
        except Exception:
            pass

    # 4) تأكيد وجود ملف الـ PDF في الحافظة قبل اللصق مباشرة
    copied_ok = _win32_copy_pdf_to_clipboard(pdf_abs)
    time.sleep(0.10)

    # 5) إذا كانت نافذة واتساب ما زالت ليست في المقدمة، انقر في منتصفها الآمن لتفعيلها دون الضغط على أي زر
    if wa_hwnd and user32.GetForegroundWindow() != wa_hwnd:
        rect = wintypes.RECT()
        if user32.GetWindowRect(wa_hwnd, ctypes.byref(rect)):
            win_w = rect.right - rect.left
            win_h = rect.bottom - rect.top
            if win_w >= 300 and win_h >= 300:
                user32.SetCursorPos(rect.left + (win_w // 2), rect.top + (win_h // 2))
                time.sleep(0.03)
                user32.mouse_event(0x0002, 0, 0, 0, 0)
                time.sleep(0.02)
                user32.mouse_event(0x0004, 0, 0, 0, 0)
                time.sleep(0.15)

    # 6) تنفيذ لصق المرفق Ctrl+V مباشرة في نافذة واتساب النشطة
    sent = _win32_send_ctrl_v()

    # سجل تشخيصي خفيف في مجلد receipts لمراجعة أي حالة خاصة
    try:
        log_file = pathlib.Path(pdf_abs).parent / "whatsapp_paste_debug.log"
        log_file.write_text(
            f"ts={db.now()}\npdf={pdf_abs}\nwas_open={was_already_open}\n"
            f"wa_hwnd={wa_hwnd}\nfg_hwnd={user32.GetForegroundWindow()}\n"
            f"copied_ok={copied_ok}\nsend_input_sent={sent}\n",
            encoding="utf-8",
        )
    except Exception:
        pass


def _jpeg_to_pdf_bytes(jpeg_bytes: bytes, img_w: int, img_h: int) -> bytes:
    """تحويل صورة الفاتورة (JPEG) إلى ملف PDF 1.4 قياسي (يدعم A4 للفواتير الرسمية وعروض الأسعار أو 80mm لإيصال الكاشير)."""
    img_w = max(1, int(img_w or 720))
    img_h = max(1, int(img_h or 1000))
    if img_w >= 900:
        pdf_w = 595.0  # Standard A4 width in points
        pdf_h = round(pdf_w * (img_h / img_w), 2)
    else:
        pdf_w = 226.77  # 80mm thermal width in points
        pdf_h = round(pdf_w * (img_h / img_w), 2)

    objs = []
    objs.append(b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n")
    objs.append(b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n")
    objs.append(
        (
            f"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {pdf_w} {pdf_h}] "
            f"/Resources << /XObject << /Im0 4 0 R >> >> /Contents 5 0 R >>\nendobj\n"
        ).encode("ascii")
    )
    img_head = (
        f"4 0 obj\n<< /Type /XObject /Subtype /Image /Width {img_w} /Height {img_h} "
        f"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length {len(jpeg_bytes)} >>\nstream\n"
    ).encode("ascii")
    objs.append(img_head + jpeg_bytes + b"\nendstream\nendobj\n")

    content_stream = f"q\n{pdf_w} 0 0 {pdf_h} 0 0 cm\n/Im0 Do\nQ\n".encode("ascii")
    objs.append(
        f"5 0 obj\n<< /Length {len(content_stream)} >>\nstream\n".encode("ascii")
        + content_stream
        + b"\nendstream\nendobj\n"
    )

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for o in objs:
        offsets.append(len(out))
        out.extend(o)

    xref_pos = len(out)
    out.extend(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode("ascii"))
    for off in offsets:
        out.extend(f"{off:010d} 00000 n \n".encode("ascii"))
    out.extend(
        f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode("ascii")
    )
    return bytes(out)


def _fmt_money(minor: int) -> str:
    """دالة تنسيق واحدة: وحدات صغرى → نص عرض."""
    return f"{(minor / 100):,.2f}"


def _format_doc_seq(prefix: str, seq_num: int) -> str:
    """توليد رقم الفاتورة أو عرض السعر تلقائياً حسب البادئة المحددة من المدير (مثل N00 -> N001 أو الفات/2026/ -> الفات/2026/00001)."""
    p = (prefix or "").strip()
    if not p:
        p = "INV-"
    if p[-1].isdigit():
        return f"{p}{seq_num}"
    return f"{p}{seq_num:05d}"


REPAIR_FLOW = {
    "received": ["in_review", "rejected"],
    "in_review": ["pending_approval", "repaired", "rejected"],
    "pending_approval": ["in_review", "repaired", "rejected"],
    "repaired": ["delivered"],
    "rejected": [],
    "delivered": [],
}


def _upsert_customer(conn, name, phone=None):
    """إدراج أو استرجاع معرف العميل بأمان مع دعم الهاتف الفارغ."""
    name = (name or "").strip()
    if not name:
        return None
    phone = (phone or "").strip() or None
    row = conn.execute(
        "SELECT id, phone FROM customers WHERE name=? AND (phone=? OR (? IS NULL AND phone IS NULL) OR phone IS NULL) ORDER BY id LIMIT 1",
        (name, phone, phone),
    ).fetchone()
    if row:
        if phone and not row["phone"]:
            try:
                conn.execute("UPDATE customers SET phone=? WHERE id=?", (phone, row["id"]))
            except sqlite3.IntegrityError:
                pass
        return row["id"]
    cur = conn.execute(
        "INSERT INTO customers(name, phone, created_at) VALUES(?,?,?)",
        (name, phone, db.now()),
    )
    return cur.lastrowid


def _customer_debt_summary(conn, cust_row) -> dict:
    """حساب إجمالي المشتريات، إجمالي الآجل الصافي، إجمالي المسدد بسندات قبض، والمديونية المتبقية للعميل."""
    cid = cust_row["id"]
    cname = cust_row["name"]
    cphone = cust_row["phone"]
    sales = conn.execute(
        """SELECT s.id, s.invoice_no, s.created_at, s.total, s.status
            FROM sales s
            WHERE s.customer_id=?
               OR (s.customer_id IS NULL AND s.customer_name=?)
               OR (? IS NOT NULL AND ? != '' AND s.customer_phone=?)
            ORDER BY s.id DESC""",
        (cid, cname, cphone, cphone, cphone),
    ).fetchall()

    # جمع المدفوعات دفعة واحدة (تجنب N+1)
    sale_ids = [s["id"] for s in sales]
    pay_map = {}
    ret_map = {}
    if sale_ids:
        placeholders = ",".join("?" for _ in sale_ids)
        for p in conn.execute(
            f"SELECT sale_id, method, COALESCE(SUM(amount),0) AS amt FROM payments WHERE sale_id IN ({placeholders}) GROUP BY sale_id, method",
            sale_ids,
        ).fetchall():
            pay_map.setdefault(p["sale_id"], {})[p["method"]] = p["amt"]
        for r in conn.execute(
            f"SELECT sale_id, COALESCE(SUM(total),0) AS amt FROM sale_returns WHERE sale_id IN ({placeholders}) GROUP BY sale_id",
            sale_ids,
        ).fetchall():
            ret_map[r["sale_id"]] = r["amt"]

    total_purchases = 0
    credit_total = 0
    sales_out = []
    for s in sales:
        d = dict(s)
        pm = pay_map.get(d["id"], {})
        credit_amt = pm.get("credit", 0)
        cash_amt = pm.get("cash", 0)
        wallet_amt = pm.get("wallet", 0)
        ret_amt = ret_map.get(d["id"], 0)
        net_total = max(0, d["total"] - ret_amt)
        net_credit = max(0, credit_amt - ret_amt)
        d["credit_amt"] = credit_amt
        d["cash_amt"] = cash_amt
        d["wallet_amt"] = wallet_amt
        d["ret_amt"] = ret_amt
        d["net_total"] = net_total
        d["net_credit"] = net_credit
        total_purchases += net_total
        credit_total += net_credit
        sales_out.append(d)

    vouchers = conn.execute(
        """SELECT cp.*, u.name AS user_name, s.invoice_no
           FROM customer_payments cp
           LEFT JOIN users u ON u.id=cp.user_id
           LEFT JOIN sales s ON s.id=cp.sale_id
           WHERE cp.customer_id=?
           ORDER BY cp.id DESC""",
        (cid,),
    ).fetchall()
    vouchers_out = [dict(v) for v in vouchers]
    inst_row = conn.execute(
        """SELECT COUNT(*) AS plans_count,
                  COALESCE(SUM(CASE WHEN sale_id IS NULL THEN principal ELSE 0 END), 0) AS standalone_principal,
                  COALESCE(SUM(ledger_charge), 0) AS ledger_charge
           FROM installment_plans
           WHERE customer_id=? AND status != 'cancelled'""",
        (cid,),
    ).fetchone()
    inst_paid_row = conn.execute(
        """SELECT COALESCE(SUM(ip.amount), 0) AS inst_paid
           FROM installment_payments ip
           JOIN installment_plans p ON p.id = ip.plan_id
           WHERE ip.customer_id=? AND p.status != 'cancelled'""",
        (cid,),
    ).fetchone()
    inst_charges = inst_row["ledger_charge"] if inst_row else 0
    inst_paid = inst_paid_row["inst_paid"] if inst_paid_row else 0
    standalone_principal = inst_row["standalone_principal"] if inst_row else 0
    total_purchases += standalone_principal
    credit_total += inst_charges
    paid_total = sum(v["amount"] for v in vouchers_out) + inst_paid
    debt = max(0, credit_total - paid_total)
    return {
        "total_purchases": total_purchases,
        "credit_total": credit_total,
        "paid_total": paid_total,
        "debt": debt,
        "inst_charges": inst_charges,
        "inst_paid": inst_paid,
        "inst_plans_count": inst_row["plans_count"] if inst_row else 0,
        "sales": sales_out,
        "vouchers": vouchers_out,
    }


def _customers_enriched_cte(cust_filter_sql: str = "") -> str:
    """بناء CTE موحد لحساب المشتريات والآجل والسداد والمديونية بكفاءة SQL دون حلقات N+1."""
    return f"""
    WITH target_customers AS (
        SELECT id, name, phone, created_at FROM customers {cust_filter_sql}
    ),
    cust_sales_links AS (
        SELECT s.customer_id AS cid, s.id AS sid
        FROM sales s
        JOIN target_customers tc ON tc.id = s.customer_id
        UNION
        SELECT tc.id AS cid, s.id AS sid
        FROM target_customers tc
        JOIN sales s ON s.customer_id IS NULL AND s.customer_name = tc.name
        UNION
        SELECT tc.id AS cid, s.id AS sid
        FROM target_customers tc
        JOIN sales s ON tc.phone IS NOT NULL AND tc.phone != '' AND s.customer_phone = tc.phone
    ),
    sale_credit AS (
        SELECT p.sale_id, COALESCE(SUM(p.amount), 0) AS credit_amt
        FROM payments p
        WHERE p.method = 'credit' AND p.sale_id IN (SELECT sid FROM cust_sales_links)
        GROUP BY p.sale_id
    ),
    sale_ret AS (
        SELECT r.sale_id, COALESCE(SUM(r.total), 0) AS ret_amt
        FROM sale_returns r
        WHERE r.sale_id IN (SELECT sid FROM cust_sales_links)
        GROUP BY r.sale_id
    ),
    cust_sales_agg AS (
        SELECT l.cid,
               COALESCE(SUM(MAX(0, s.total - COALESCE(sr.ret_amt, 0))), 0) AS total_purchases,
               COALESCE(SUM(MAX(0, COALESCE(sc.credit_amt, 0) - COALESCE(sr.ret_amt, 0))), 0) AS credit_total
        FROM cust_sales_links l
        JOIN sales s ON s.id = l.sid
        LEFT JOIN sale_credit sc ON sc.sale_id = s.id
        LEFT JOIN sale_ret sr ON sr.sale_id = s.id
        GROUP BY l.cid
    ),
    cust_paid AS (
        SELECT cp.customer_id AS cid, COALESCE(SUM(cp.amount), 0) AS paid_total
        FROM customer_payments cp
        JOIN target_customers tc ON tc.id = cp.customer_id
        GROUP BY cp.customer_id
    ),
    enriched AS (
        SELECT tc.id, tc.name, tc.phone, tc.created_at,
               COALESCE(csa.total_purchases, 0) AS total_purchases,
               COALESCE(csa.credit_total, 0) AS credit_total,
               COALESCE(cp.paid_total, 0) AS paid_total,
               MAX(0, COALESCE(csa.credit_total, 0) - COALESCE(cp.paid_total, 0)) AS debt
        FROM target_customers tc
        LEFT JOIN cust_sales_agg csa ON csa.cid = tc.id
        LEFT JOIN cust_paid cp ON cp.cid = tc.id
    )
    """


def _resolve_sale_customer_id(conn, sale_row):
    """إرجاع معرف العميل المرتبط بفاتورة بيع (أو مطابقته بالهاتف/الاسم للفواتير القديمة)."""
    if not sale_row:
        return None
    if sale_row["customer_id"]:
        return sale_row["customer_id"]
    phone = (sale_row["customer_phone"] or "").strip() if "customer_phone" in sale_row.keys() else ""
    name = (sale_row["customer_name"] or "").strip() if "customer_name" in sale_row.keys() else ""
    if phone:
        r = conn.execute("SELECT id FROM customers WHERE phone=? LIMIT 1", (phone,)).fetchone()
        if r:
            return r["id"]
    if name:
        r = conn.execute("SELECT id FROM customers WHERE name=? LIMIT 1", (name,)).fetchone()
        if r:
            return r["id"]
    return None


def _sale_net_credit(conn, sale_id: int) -> int:
    """حساب صافي المبلغ الآجل المتبقي على فاتورة واحدة بعد المرتجعات."""
    cr = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM payments WHERE sale_id=? AND method='credit'",
        (sale_id,),
    ).fetchone()[0]
    ret = conn.execute(
        "SELECT COALESCE(SUM(total), 0) FROM sale_returns WHERE sale_id=?",
        (sale_id,),
    ).fetchone()[0]
    return max(0, cr - ret)


def _refresh_customer_cache(conn, customer_id: int) -> dict | None:
    """تحديث الأعمدة المخزّنة لملخص حساب العميل داخل نفس المعاملة."""
    if not customer_id:
        return None
    cust = conn.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone()
    if not cust:
        return None
    summary = _customer_debt_summary(conn, cust)
    conn.execute(
        "UPDATE customers SET total_purchases=?, credit_total=?, paid_total=?, debt=? WHERE id=?",
        (summary["total_purchases"], summary["credit_total"], summary["paid_total"], summary["debt"], customer_id),
    )
    return summary


def _append_ledger_entry(
    conn,
    customer_id: int,
    kind: str,
    ref: str,
    debit: int = 0,
    credit: int = 0,
    sale_id: int | None = None,
    voucher_id: int | None = None,
    plan_id: int | None = None,
    method: str | None = None,
    ref_no: str | None = None,
    notes: str | None = None,
    user_id: int | None = None,
    user_name: str | None = None,
    created_at: str | None = None,
) -> int:
    """إضافة قيد جديد في دفتر الأستاذ (customer_ledger) وتحديث رصيد العميل المخزّن."""
    if not customer_id:
        return 0
    last = conn.execute(
        "SELECT balance_after FROM customer_ledger WHERE customer_id=? ORDER BY id DESC LIMIT 1",
        (customer_id,),
    ).fetchone()
    if last is not None:
        prev_bal = last["balance_after"]
    else:
        row = conn.execute("SELECT debt FROM customers WHERE id=?", (customer_id,)).fetchone()
        prev_bal = row["debt"] if row else 0
    bal_after = max(0, prev_bal + int(debit or 0) - int(credit or 0))
    conn.execute(
        """INSERT INTO customer_ledger
           (customer_id, created_at, kind, ref, sale_id, voucher_id, plan_id, debit, credit, balance_after, method, ref_no, notes, user_id, user_name)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            customer_id,
            created_at or db.now(),
            kind,
            ref,
            sale_id,
            voucher_id,
            plan_id,
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
    _refresh_customer_cache(conn, customer_id)
    return bal_after


def _sync_sale_ledger_delta(conn, sale_row, prev_net_credit: int, user=None, reason_prefix: str = "تعديل فاتورة آجلة") -> None:
    """تسجيل قيد تسوية في دفتر الأستاذ عند تغيّر صافي الآجل لفاتورة بعد مرتجع أو خصم."""
    cid = _resolve_sale_customer_id(conn, sale_row)
    if not cid:
        return
    new_net_credit = _sale_net_credit(conn, sale_row["id"])
    delta = prev_net_credit - new_net_credit
    uid = user["id"] if user else None
    uname = user["name"] if user else None
    if delta > 0:
        _append_ledger_entry(
            conn, cid, "return_credit", sale_row["invoice_no"],
            credit=delta, sale_id=sale_row["id"],
            notes=f"{reason_prefix} ({sale_row['invoice_no']})",
            user_id=uid, user_name=uname,
        )
    elif delta < 0:
        _append_ledger_entry(
            conn, cid, "adjustment", sale_row["invoice_no"],
            debit=-delta, sale_id=sale_row["id"],
            notes=f"{reason_prefix} ({sale_row['invoice_no']})",
            user_id=uid, user_name=uname,
        )
    else:
        _refresh_customer_cache(conn, cid)


def _normalize_eg_phone(raw_phone: str) -> str:
    """تطبيع رقم الهاتف المصري لصيغة واتساب الدولية (2010...)."""
    digits = "".join(ch for ch in (raw_phone or "").strip() if ch.isdigit())
    if not digits:
        return ""
    if digits.startswith("00"):
        digits = digits[2:]
    elif digits.startswith("01") and len(digits) == 11:
        digits = "2" + digits
    elif not digits.startswith("20") and len(digits) == 10:
        digits = "20" + digits
    return digits


class _BaseApiMixin:
    # ---------------------------------------------------------- صلاحيات
    def _user(self):
        u = _STATE["user"]
        if not u:
            raise ApiError("يجب تسجيل الدخول أولاً")
        if not u.get("is_active", True):
            _STATE["user"] = None
            raise ApiError("تم إيقاف هذا الحساب من قبل الإدارة")
        return u

    def _has_perm(self, key: str) -> bool:
        u = _STATE["user"]
        if not u or not u.get("is_active", True):
            return False
        if u["role"] == "admin":
            return True
        return bool((u.get("permissions") or {}).get(key, False))

    def _perm(self, key: str):
        u = self._user()
        if u["role"] == "admin":
            return u
        if not (u.get("permissions") or {}).get(key, False):
            raise ApiError("ممنوع: للمدير أو لمن يملك الصلاحية فقط")
        return u

    def _perm_any(self, *keys):
        u = self._user()
        if u["role"] == "admin":
            return u
        perms = u.get("permissions") or {}
        if not any(perms.get(k, False) for k in keys):
            raise ApiError("ممنوع: للمدير أو لمن يملك الصلاحية فقط")
        return u

    def _perm_all(self, *keys):
        u = self._user()
        if u["role"] == "admin":
            return u
        perms = u.get("permissions") or {}
        if not all(perms.get(k, False) for k in keys):
            raise ApiError("ممنوع: للمدير أو لمن يملك جميع الصلاحيات المطلوبة")
        return u

    def _scope_check(self, record_user_id, all_perm: str, own_perm: str | None = None, err_msg: str = "ممنوع: لا يمكنك عرض سجلات موظفين آخرين"):
        u = self._user()
        if u["role"] == "admin" or self._has_perm(all_perm):
            return u
        if record_user_id == u["id"] and (own_perm is None or self._has_perm(own_perm)):
            return u
        raise ApiError(err_msg)

    def _admin(self):
        u = self._user()
        if u["role"] != "admin":
            raise ApiError("ممنوع: للمدير فقط")
        return u

    def _owner_is_active(self) -> bool:
        own = _STATE.get("owner")
        if not own:
            return False
        if float(own.get("until", 0) or 0) <= time.time():
            _STATE["owner"] = None
            return False
        return True

    def _owner(self):
        if not self._owner_is_active():
            raise ApiError("وضع المالك الرئيسي غير نشط أو انتهت الجلسة — يرجى تسجيل الدخول")
        _STATE["owner"]["until"] = time.time() + OWNER_SESSION_TTL
        return _STATE["owner"]

    def _owner_backup_once(self) -> None:
        own = _STATE.get("owner")
        if own and not own.get("backed_up"):
            db.backup_database("before_structure_change")
            own["backed_up"] = True

    def _audit(self, conn, action: str, target: str | None = None, details: dict | None = None) -> None:
        conn.execute(
            "INSERT INTO owner_audit_log(ts, action, target, details) VALUES(?,?,?,?)",
            (db.now(), str(action), target, json.dumps(details or {}, ensure_ascii=False)),
        )

    def _log_activity(
        self,
        conn,
        action: str,
        entity_type: str,
        entity_id=None,
        summary: str = "",
        details: dict | None = None,
        module_key: str = "core",
    ) -> None:
        """تسجيل العمليات الحساسة واليومية في سجل الرقابة الشامل (activity_audit_log) بشكل معزول وآمن."""
        try:
            u = _STATE.get("user") or {}
            conn.execute(
                """INSERT INTO activity_audit_log(created_at, user_id, user_name, role, module_key, action, entity_type, entity_id, summary, details)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    db.now(),
                    u.get("id"),
                    u.get("name") or u.get("username") or "النظام",
                    u.get("role") or "system",
                    str(module_key or "core"),
                    str(action),
                    str(entity_type),
                    str(entity_id) if entity_id is not None else None,
                    str(summary or action),
                    json.dumps(details or {}, ensure_ascii=False),
                ),
            )
        except Exception:
            pass

    def _settings(self, conn):
        cache = getattr(self, "_settings_cache", None)
        if cache is None:
            cache = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM settings")}
            self._settings_cache = cache
        return cache

    def _modules_rows(self, conn=None) -> list[dict]:
        cache = getattr(self, "_modules_cache", None)
        if cache is None:
            if conn is None:
                with db.connect() as c:
                    rows = c.execute("SELECT * FROM modules ORDER BY sort_order ASC, key ASC").fetchall()
            else:
                rows = conn.execute("SELECT * FROM modules ORDER BY sort_order ASC, key ASC").fetchall()
            parsed = []
            for r in rows:
                d = dict(r)
                try:
                    p = json.loads(d.get("perm_keys") or "[]")
                    d["perm_keys"] = p if isinstance(p, list) else []
                except Exception:
                    d["perm_keys"] = []
                d["enabled"] = bool(d.get("enabled", 1))
                d["is_core"] = bool(d.get("is_core", 0))
                d["is_builtin"] = bool(d.get("is_builtin", 1))
                parsed.append(d)
            self._modules_cache = parsed
            cache = parsed
        return cache

    def _module_enabled(self, key: str) -> bool:
        for m in self._modules_rows():
            if m["key"] == key:
                return bool(m["enabled"])
        return False

    def _enabled_module_keys(self, conn=None) -> set[str]:
        return {m["key"] for m in self._modules_rows(conn) if m["enabled"]}

    def _first_enabled_module(self, conn=None) -> str:
        for m in self._modules_rows(conn):
            if m["enabled"]:
                return m["key"]
        return "desktop"

    def _open_shift(self, conn, user_id):
        return conn.execute(
            "SELECT * FROM shifts WHERE user_id=? AND closed_at IS NULL ORDER BY id DESC LIMIT 1",
            (user_id,),
        ).fetchone()

