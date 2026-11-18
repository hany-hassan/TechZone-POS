@AGENTS.md

# Claude Code & AI Agents — TechZone POS & ERP Session Guide

## Session start ritual

1. Read `AGENTS.md` — the single source of truth for the whole project.
2. Read the **Mandatory Modular Plug-and-Play Architecture Rule** below before touching any module, database table, or API endpoint.
3. Read the current phase in `docs/ROADMAP.md` — find the first phase with ⬜ or 🟡.
4. Skim `docs/OPEN-QUESTIONS.md` for anything blocking the current phase.
5. Run `python app/selfcheck.py` to confirm baseline (expect 293/293 PASS + `contract ok`).

---

## ⚠️ MANDATORY ARCHITECTURAL RULE: Modular Plug-and-Play (هندسة الأقسام المعزولة)

**This rule is a strict, non-negotiable condition for ANY AI model or developer when creating, modifying, adding, or deleting any section/module now and in the future:**

1. **Complete Isolation (Zero-Overhead When Disabled):**
   - Every feature module (`pos`, `sales_quotes`, `inventory`, `customers`, `installments`, `purchases`, `accounting`, `history`, `repair`, `buy_used`, `reports`, `staff`, or any future module) MUST operate as an independent, self-contained Plug-and-Play unit.
   - When a module is disabled from `owner.html` (`modules.enabled = 0`), it MUST incur **zero database queries, zero background hooks, and zero performance overhead** on POS or any other active module.
   - Cross-module hooks (such as `app/erp_hooks.py`) MUST check `is_module_active(api, conn, "<module_key>")` using the in-memory `api._module_enabled()` cache (`O(1)`) as their very first line before executing a single SQL statement.
2. **Registration in the Module Registry & Server Guard:**
   - **Database Registry (`app/db.py` → `DEFAULT_MODULES`):** Any new module must be registered in `DEFAULT_MODULES` with its `key`, Arabic `title`, `icon`, `color`, `url`, `perm_keys`, `sort_order`, and `enabled` state.
   - **Server-Side Dispatcher Guard (`app/modules_map.py`):** Every public method in `Api` MUST be mapped in `API_MODULE_MAP` to its owning module key (or placed in `CORE_METHODS` if it is an always-on OS/auth method). `Api.call()` blocks any call to a disabled module on the server, even for `admin`.
   - **Explicit Dependency Map (`MODULE_REQUIRES` in `app/modules_map.py`):** Only declare hard structural dependencies where strictly required. Optional integrations (e.g., `accounting` listening to `pos` or `purchases`, or `reports` reading `purchases` and `accounting`) MUST be loosely coupled via runtime `is_module_active` checks so either module can be enabled or disabled independently without breaking the other.
3. **Domain Mixin & Frontend Encapsulation:**
   - Backend logic for a module must live in its own dedicated mixin file (`app/api_<module>.py`) and be composed into `app/api.py`.
   - Frontend UI for a module must live in its own standalone HTML page (`web/<module>.html`) calling `pageInit('<module>')` at startup, which automatically verifies both module activation (`UI_CONFIG.modules`) and user permissions.
   - Deleting, disabling, or adding a module must never leave broken imports, orphan SQL joins, or UI crashes in `desktop.html`, `owner.html`, `reports.html`, or `pos.html`.

---

## How to talk to the owner

- **Language:** Arabic (العربية / عامية مصرية واضحة). Use Arabic for explanations, keep code and commands in English.
- **Non-technical framing:** Explain what you changed and why in clear Arabic.
- **Report real numbers:** After any change, run `python app/selfcheck.py` and report the actual pass/fail count. Never claim tests passed without running them.

## Working style

- **Plan first:** For multi-file changes, write a short plan before editing.
- **Small vertical slices:** Complete one feature or fix end-to-end (backend + frontend + selfcheck + docs) before moving to the next.
- **Never claim tests passed without running them.** Always run `python app/selfcheck.py`.
- **Stop after two identical failures.** If the same error appears twice, report it and ask for guidance instead of looping.

## Record decisions & mandatory documentation

- Any architectural or design decision → create/update an ADR in `docs/adr/`.
- **Any code change, addition, modification, or deletion → MUST be documented in `AGENTS.md`, `README.md`, and the relevant `docs/*.md` files in the same turn/commit.**

## Key commands

| Task | Command |
|---|---|
| Run the app | `python app/main.py` |
| Run all checks (293 checks) | `python app/selfcheck.py` |
| Rebuild Tailwind CSS | `npx tailwindcss -i web/tailwind.css -o web/app.css --minify` |
| Build .exe | `build-exe.bat` |
| Build Setup Installer | `build-installer.bat` |
| Push to GitHub | `push-github.bat` |

## Non-negotiable rules

- **Enforce Modular Plug-and-Play isolation** on every new or modified feature.
- Never add external runtime dependencies (no React, no Electron, no npm packages used at runtime).
- Never add network calls — the app is 100% offline.
- All fonts and icons must be local files in `web/fonts/`.
- Never put secrets, passwords, or customer data in code or commits.
- Never disable or skip selfcheck tests.
- Always update `AGENTS.md` and `README.md` in the same commit as any code change.
- Money values are INTEGER minor units (1 LE = 100 qirsh). Never use float for money in the database.
- All SQL must be parameterized. No string interpolation in queries.


---

## 🔒 الشرط الأساسي الإلزامي: هندسة الأقسام المعزولة (Modular Plug-and-Play — Zero-Overhead Isolation) وسجل التحديثات الشامل

> **قاعدة معمارية صارمة لكل نموذج ذكاء اصطناعي (AI Agent) أو مطور يعمل على المشروع الآن وفيما بعد:**
> 1. **العزل التام للأقسام (`Modular Plug-and-Play / Zero-Overhead Isolation`):** أي قسم حالي أو مستقبلي (مثل `purchases`، `accounting`، `installments`، `repair`، `buy_used`، `reports` أو أي قسم جديد) يجب أن يعمل عبر خطافات معزولة (`app/erp_hooks.py` و`is_module_active(conn, 'module_key')`) بحيث إذا تم إيقاف القسم من `system_modules` أو لم يكن مفعلاً في نشاط المتجر، يعمل باقي النظام بنسبة 100% دون أي خطأ أو بطء أو اعتمادية إجبارية.
> 2. **التوثيق الإلزامي الفوري مع كل طلب:** أي تعديل أو إضافة أو حذف في الكود أو الواجهات أو قاعدة البيانات يجب توثيقه فوراً في `AGENTS.md` و`CLAUDE.md` و`README.md` وكافة ملفات `docs/*.md`، ويتم فحص ذلك آلياً في `app/selfcheck.py`.

### سجل التحديثات المعمارية والميزات الموثقة
- **فصل قيد إيراد المبيعات عن قيد تكلفة البضاعة المباعة (`sales` vs `sales_cogs`):** في `app/erp_hooks.py`، يُسجل قيد فاتورة البيع (`source_table='sales'`) بمبلغ الفاتورة الفعلي فقط، بينما يُسجل قيد الجرد المستمر لتكلفة البضاعة المباعة (`source_table='sales_cogs'`) كقيد مستقل لمنع تضخم إجمالي القيد في دفتر اليومية.
- **حماية معالج الترصيد الافتتاحي الآلي (`has_opening_entry`):** في `app/api_accounting.py` و`web/accounting.html`، يتحقق النظام من وجود قيد افتتاحي مرحّل (`kind='opening' AND status='posted'`) ويمنع تكرار التشغيل من الخلفية والواجهة.
- **إدارة شجرة الحسابات الكاملة والسحب والإفلات (`account_save`, `account_delete`, `account_move`):** إضافة وتعديل وحذف الحسابات (بشرط عدم وجود حركات أو حسابات فرعية) وتحريك الحسابات بالسحب والإفلات (Drag-and-Drop) مع إعادة بناء الأرصدة آلياً، بالإضافة إلى طباعة A4 شاملة لكل تبويبات المحاسبة وسندات القيد.
- **مركز التقارير والتحليلات المالية الشامل (`report_comprehensive`):** في `app/api_reports.py` و`web/reports.html`، استخراج تقارير الأرباح والخسائر، مديونيات العملاء وأعمار الديون، مستحقات الموردين، تقييم المخزون، وحركة الخزائن، مع التصدير إلى **Excel الأصلي (`.xlsx` متعدد الأوراق + `.csv`)** و**PDF (A4)** والطباعة المباشرة والإرسال عبر **واتساب (`whatsapp_send_report`)**.
- **تخصيص أيقونات سطح المكتب وشريط المهام لكل مستخدم (`_hidden_desktop` & `_hidden_taskbar`):** في `web/profile.html` و`web/desktop.html` و`app/api_auth.py`، حفظ تفضيلات إظهار/إخفاء الأيقونات لكل مستخدم بشكل مستقل داخل `users.desktop_layout` دون التأثير على باقي المستخدمين، مع تنسيق متجاوب كامل في `web/app.css`.
- **التحكم في سلوك زر الإغلاق (`X`) والتصغير إلى شريط النظام بجوار الساعة (`close_exit_app`):** في `app/main.py` و`web/settings.html` و`app/db.py`، خيار `close_exit_app` (الافتراضي `'0'`) يخفي النافذة عند الضغط على `X` ويبقي البرنامج يعمل في شريط النظام (System Tray / `.NET WinForms NotifyIcon`) بجوار الساعة مع قائمة سياقية عربية («إظهار نافذة البرنامج» / «إغلاق البرنامج نهائياً»)، وعند تفعيله (`'1'`) يغلق البرنامج نهائياً.


### تحديثات الميزات التشغيلية والأمنية (Barcode Label Studio, Auto-Lock on Idle, General Audit Log, POS Alerts & Credit Limits)
- **استوديو طباعة ملصقات الباركود والرفوف (`tzGenerateBarcodeSvg` & `tzBuildBarcodeLabelsPrintHtml` & `#modal-barcode-studio`):** في `web/app.js` و`web/inventory.html` و`web/purchases.html`، توليد باركود قياسي `Code-128B SVG` محلياً 100% بدون إنترنت مع طباعة ملصقات حرارية (`38×25 مم`، `50×25 مم`، `50×30 مم`) أو شبكة ملصقات `A4` من شاشة المخزون أو مباشرة لأصناف فواتير المشتريات (`printPurchaseBarcodes`).
- **قفل الشاشة التلقائي عند الخمول (`idle_lock_minutes` & `verify_lock_pin` & `#os-lock-overlay`):** في `web/desktop.html` و`web/settings.html` و`app/api_auth.py`، تتبع نشاط المستخدم في سطح المكتب والنوافذ الفرعية وقفل الشاشة تلقائياً بعد دقائق الخمول المحددة (أو يدوياً بزر «🔒 قفل») مع فك القفل برمز `PIN` الخاص بالمستخدم الحالي دون إغلاق النوافذ أو فقدان الفواتير المفتوحة.
- **سجل رقابة العمليات اليومية الشامل (`activity_audit_log` & `activity_audit_list` & `_log_activity`):** في `app/db.py` و`app/api_common.py` و`app/api_auth.py` و`web/settings.html` (تبويب «سجل رقابة العمليات Audit Log»)، تسجيل آلي معزول (`Modular Plug-and-Play`) لكافة العمليات الحساسة (إصدار وتعديل ومرتجعات المبيعات، إضافة وحذف المنتجات وتغيير الأسعار `product_price_change`، تعديل المخزون `stock_adjust`، العملاء وسندات القبض، تحديث الإعدادات، وفك قفل الشاشة) مع الفلترة والطباعة `A4`.
- **التنبيهات الصوتية والمرئية لنواقص المخزون وحد ائتمان العملاء (`tzPlayPosSound` & `pos_sound_enabled` & `pos_low_stock_alert` & `credit_limit` & `enforce_credit_limit`):** في `web/app.js` و`web/pos.html` و`web/customers.html` و`app/api_sales.py` و`app/api_customers.py`، نغمات صوتية تفاعلية عبر `WebAudio API` عند المسح والبيع والتحذير، وتنبيه فوري عند وصول رصيد الصنف للحد الأدنى أثناء البيع (`low_stock_items`)، وفحص حد الائتمان المخصص لكل عميل (`customers.credit_limit`) أو الافتراضي للمتجر (`customer_default_credit_limit`) مع خيار التنبيه أو المنع الإجباري (`enforce_credit_limit`).
