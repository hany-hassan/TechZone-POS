# TechZone Testing Strategy & Modular Verification

## Mandatory Testing & Documentation Rule for AI Agents

Every modification, addition, or deletion in the project MUST:
1. Respect the **Modular Plug-and-Play (Zero-Overhead Isolation)** architecture (`DEFAULT_MODULES`, `API_MODULE_MAP`, and `erp_hooks.is_module_active`).
2. Be documented in `AGENTS.md`, `CLAUDE.md`, `README.md`, and `docs/*.md` in the same turn/commit.
3. Pass all assertions in `python app/selfcheck.py` (currently **293 checks**).

---

## Automated Regression Suite: `app/selfcheck.py` (293 Assertions)

### Running the Tests

```bash
python app/selfcheck.py
```

A successful run ends with:

```
ALL 293 CHECKS PASSED
```

### What `selfcheck.py` Covers

| Area | Verified Invariants |
|---|---|
| **DB Schema (52 Tables)** | All 52 tables (Core POS, Installments, Owner Mode, RBAC, Purchases & Suppliers, Double-Entry Accounting) exist with foreign keys and WAL mode |
| **Modular Plug-and-Play Isolation** | Disabling `purchases` and `accounting` via `module_toggle` blocks their APIs server-side while POS sales run with zero journal entry queries or overhead (`erp_hooks.is_module_active`) |
| **Permissions & Zero-Leak RBAC** | All **63 permissions** across **12 groups** and **7 job presets** (`app/permissions.py`); strict cashier isolation & Blind Close (`shift_summary_view=False`) |
| **Purchases & WAC Cost Engine** | Suppliers CRUD, Purchase Orders (`PO`), Purchase Invoices (`PUR`) with landed shipping cost & Weighted Average Cost (`WAC`), 14% VAT input, 1%/3% WHT, Purchase Returns (`PRET`), Supplier Payments (`SPY`), and AP Aging |
| **Double-Entry Accounting** | 38-account standard Arabic Chart of Accounts (`accounts_tree`), Add/Edit/Guarded Delete (`account_delete`) & Drag-and-Drop reparenting (`account_move`), separated Sale Invoice Revenue vs. `sales_cogs` journal entries matching exact invoice total, Single-Run Opening Balance Wizard guard (`has_opening_entry`), Treasuries & Transfers, Expenses, Fiscal Years/Periods, General Ledger, Trial Balance, Income Statement, Balance Sheet & Tax Report |
| **Comprehensive Financial Reports** | `report_comprehensive` (Detailed P&L, invoice-by-invoice & item-by-item profitability, customer receivables & installments, supplier payables, cashflow & shifts, inventory valuation), `report_export_excel` (native 5-sheet `.xlsx` + `.csv`), `report_export_pdf` (`A4 PDF`), and `whatsapp_send_report` |
| **Per-User Desktop & Taskbar Icons** | `profile_save` / `user_pref_save` stores `_hidden_desktop` and `_hidden_taskbar` in `users.desktop_layout` for the active user only without affecting other users |
| **Window Close (X) & System Tray** | `close_exit_app` setting defaults to `'0'` (hide window to Windows System Tray next to clock via `.NET WinForms NotifyIcon` in `app/main.py`) and toggles to `'1'` (exit completely on `X`) in `web/settings.html` |
| **Frontend JS Syntax & API Contract** | Every inline `<script>` in `web/*.html` (19 pages) passes `node --check`, every frontend `api('...')` call exists on `Api`, every public `Api` method (181 methods) is mapped in `app/modules_map.py`, and all core documentation files contain the Modular Plug-and-Play specification |


### تحديثات الميزات التشغيلية والأمنية (Barcode Label Studio, Auto-Lock on Idle, General Audit Log, POS Alerts & Credit Limits)
- **استوديو طباعة ملصقات الباركود والرفوف (`tzGenerateBarcodeSvg` & `tzBuildBarcodeLabelsPrintHtml` & `#modal-barcode-studio`):** في `web/app.js` و`web/inventory.html` و`web/purchases.html`، توليد باركود قياسي `Code-128B SVG` محلياً 100% بدون إنترنت مع طباعة ملصقات حرارية (`38×25 مم`، `50×25 مم`، `50×30 مم`) أو شبكة ملصقات `A4` من شاشة المخزون أو مباشرة لأصناف فواتير المشتريات (`printPurchaseBarcodes`).
- **قفل الشاشة التلقائي عند الخمول (`idle_lock_minutes` & `verify_lock_pin` & `#os-lock-overlay`):** في `web/desktop.html` و`web/settings.html` و`app/api_auth.py`، تتبع نشاط المستخدم في سطح المكتب والنوافذ الفرعية وقفل الشاشة تلقائياً بعد دقائق الخمول المحددة (أو يدوياً بزر «🔒 قفل») مع فك القفل برمز `PIN` الخاص بالمستخدم الحالي دون إغلاق النوافذ أو فقدان الفواتير المفتوحة.
- **سجل رقابة العمليات اليومية الشامل (`activity_audit_log` & `activity_audit_list` & `_log_activity`):** في `app/db.py` و`app/api_common.py` و`app/api_auth.py` و`web/settings.html` (تبويب «سجل رقابة العمليات Audit Log»)، تسجيل آلي معزول (`Modular Plug-and-Play`) لكافة العمليات الحساسة (إصدار وتعديل ومرتجعات المبيعات، إضافة وحذف المنتجات وتغيير الأسعار `product_price_change`، تعديل المخزون `stock_adjust`، العملاء وسندات القبض، تحديث الإعدادات، وفك قفل الشاشة) مع الفلترة والطباعة `A4`.
- **التنبيهات الصوتية والمرئية لنواقص المخزون وحد ائتمان العملاء (`tzPlayPosSound` & `pos_sound_enabled` & `pos_low_stock_alert` & `credit_limit` & `enforce_credit_limit`):** في `web/app.js` و`web/pos.html` و`web/customers.html` و`app/api_sales.py` و`app/api_customers.py`، نغمات صوتية تفاعلية عبر `WebAudio API` عند المسح والبيع والتحذير، وتنبيه فوري عند وصول رصيد الصنف للحد الأدنى أثناء البيع (`low_stock_items`)، وفحص حد الائتمان المخصص لكل عميل (`customers.credit_limit`) أو الافتراضي للمتجر (`customer_default_credit_limit`) مع خيار التنبيه أو المنع الإجباري (`enforce_credit_limit`).
