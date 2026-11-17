# TechZone POS & Shop OS — AI Agent Source of Truth (AGENTS.md)

> **Mandatory Update Rule:** Any change, addition, or deletion in the project (logic, DB schema, API, or frontend) MUST be documented in `AGENTS.md` in the same commit — update the affected section and append an entry to `## Changelog` (newest first). Historical changelog entries prior to today are archived in [`CHANGELOG_ARCHIVE.md`](CHANGELOG_ARCHIVE.md).

---

## 1. Project Overview & Rules

**TechZone POS** is an offline-first retail, sales, inventory, and repair management operating system tailored specifically for Egyptian technology shops and service centers.
- **Language & Direction:** Native Arabic UI (`dir="rtl"`), supporting both Light and Dark modes synchronized across desktop and floating windows.
- **Market Fit:** Egyptian Pound (`LE` / `ج.م`), optional 14% VAT toggle, localized payment methods (Cash, InstaPay, Vodafone Cash, Bank Transfer), and installment customer debt ledgers.
- **Form Factor:** Single maximized `pywebview` desktop window hosting a hybrid desktop environment (**TechZone OS — Windows 11 + macOS blend**) with multi-window floating iframes, widgets, Start menu, and dock.
- **Zero Cloud / Zero Runtime Network:** 100% offline. All fonts, icons, and assets are local (`web/fonts/`). No external runtime JS frameworks or cloud dependencies.

---

## 2. Documentation Map (Read Before You Code)

Detailed technical specifications are modularized in the `docs/` directory:

| Document | Purpose | Language |
|---|---|---|
| [`docs/README.md`](docs/README.md) | Documentation index and overview | Arabic |
| [`docs/PRD.md`](docs/PRD.md) | Product requirements, personas, scope, and page functional specs | Arabic |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | Phased roadmap, quality gates, and milestone checklists | Arabic |
| [`docs/IMPLEMENTATION-PLAN.md`](docs/IMPLEMENTATION-PLAN.md) | Step-by-step technical plan for security, shop features & refactoring | Arabic |
| [`docs/OWNER-CONTROL-PLAN.md`](docs/OWNER-CONTROL-PLAN.md) | Owner mode, module registry, business profiles & recovery key implementation plan | English |
| [`docs/OPEN-QUESTIONS.md`](docs/OPEN-QUESTIONS.md) | Pending architectural questions and design decisions | Arabic |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | System architecture, IPC bridge, sequence flows, and directory tree | English |
| [`docs/DATA-MODEL.md`](docs/DATA-MODEL.md) | 31 tables schema, minor-unit money rules, and 49-permission matrix | English |
| [`docs/STACK.md`](docs/STACK.md) | Pinned runtime stack, versions, and upgrade policies | English |
| [`docs/CODING-STANDARDS.md`](docs/CODING-STANDARDS.md) | Coding style, SQL guidelines, money formatting, and RTL conventions | English |
| [`docs/TESTING.md`](docs/TESTING.md) | Selfcheck automation (234 checks), test gates, and manual QA | English |
| [`docs/SECURITY.md`](docs/SECURITY.md) | Threat model, PBKDF2 hashing, lockout rules, and Egyptian PDPL | English |
| [`docs/DESIGN-SYSTEM.md`](docs/DESIGN-SYSTEM.md) | TechZone OS color tokens, Arabic typography, layout, and invoice specs | English |
| [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | Standalone .exe compilation (PyInstaller), backup routines, and setup | English |
| [`docs/adr/`](docs/adr/) | Architectural Decision Records (ADRs) | English |

---

## 3. Technology Stack

- **Runtime:** Python 3.13.5 (64-bit)
- **Database:** Standard library `sqlite3` (schema in `app/db.py`, DB file in `data/shop.db`)
- **Desktop Window:** `pywebview` 6.2.1 powered by Microsoft Edge WebView2 Evergreen
- **System Integration:** Windows `ctypes.windll` for clipboard `CF_HDROP` binary file copies (direct WhatsApp desktop PDF pasting)
- **Frontend:** Semantic HTML5, Vanilla ES6+ JavaScript, pre-compiled Tailwind CSS (`web/app.css` committed to Git)
- **Fonts & Icons:** Local 23 `.woff2` files in `web/fonts/` (Cairo, IBM Plex Sans Arabic, Material Icons)
- **Packaging:** PyInstaller single-file windowed binary (`build-exe.bat` → `dist/TechZone.exe`)

---

## 4. Key Commands

| Task | Command |
|---|---|
| Launch Dev Application | `python app/main.py` |
| Execute Automated Selfcheck (234 tests) | `python app/selfcheck.py` |
| Recompile Tailwind CSS | `npx tailwindcss -i web/tailwind.css -o web/app.css --minify` |
| Build Standalone EXE | Double-click `build-exe.bat` or run `.\build-exe.bat` |
| Build Windows Setup Installer | Double-click `build-installer.bat` or run `.\build-installer.bat` (outputs `dist/TechZone-Setup-v2.0.0.exe` + `SHA256SUMS.txt`) |
| Push Updates to GitHub | Double-click `push-github.bat` or run `.\push-github.bat` |

---

## 5. System Architecture & Directory Tree

```
project001/
├── app/
│   ├── main.py          # Entry point: pywebview window setup, branding & session cleanup on close
│   ├── api.py           # Facade Api class composing 8 domain mixins (plus re-exports)
│   ├── api_common.py    # Shared state, money/format helpers, phone normalization, PDF/WhatsApp Win32 & ledger helpers
│   ├── api_auth.py      # AuthSettingsMixin: login, users, permissions/presets/audit, profile & settings/backups
│   ├── api_owner.py     # OwnerMixin: owner auth, module registry, profiles, labels & audit log
│   ├── permissions.py   # Canonical 49-permission registry, 10 groups, 7 role presets & strict cashier baseline
│   ├── modules_map.py   # API_MODULE_MAP, CORE_METHODS & MODULE_REQUIRES server guard map
│   ├── profiles.py      # DEFAULT_BUSINESS_PROFILES (with demo_catalog) & DEFAULT_LABELS/LABEL_KEYS
│   ├── fresh_db.py      # Clean per-profile DB builder with selective data carry-over & safety backup
│   ├── api_inventory.py # InventoryMixin: categories, products, serials & stock adjustments
│   ├── api_customers.py # CustomersMixin: customer CRM, debt summary, ledger history & vouchers
│   ├── api_installments.py # InstallmentsMixin: installment contracts, schedules, collections, alerts & WhatsApp reminders
│   ├── api_sales.py     # SalesMixin: shifts (incl. Blind Close), POS checkout, returns, modifications & WhatsApp invoice
│   ├── api_quotes.py    # QuotesMixin: B2B quotations, A4 invoices & conversion to sales
│   ├── api_services.py  # ServicesMixin: repair workshop lifecycle & used device purchases
│   ├── api_reports.py   # ReportsMixin: daily/monthly financials & top-selling reports
│   ├── db.py            # SQLite schema (31 tables), connection wrapper, seed, migration & backups
│   └── selfcheck.py     # Comprehensive automated regression suite (234 checks)
├── web/
│   ├── index.html       # Smart login screen (auto role/user detection by PIN, force-PIN & owner recovery)
│   ├── owner.html       # Hidden owner control panel (setup, login, recovery, security & audit log)
│   ├── desktop.html     # TechZone OS hybrid desktop shell (dock, start menu, iframes)
│   ├── pos.html         # High-speed retail POS cashier (with global hardware barcode listener)
│   ├── sales_quotes.html# Official B2B A4 sales invoices & price quotations
│   ├── inventory.html   # Product catalog, stock tracking, and serial numbers
│   ├── customers.html   # Customer database, debt totals, and ledger shortcuts
│   ├── customer_details.html # Customer debt statements, installment contracts & payment vouchers
│   ├── installments.html # Installment contracts, pre-sale calculator, collection & overdue tracking
│   ├── repair.html      # Maintenance lifecycle ticketing & spare parts
│   ├── buy_used.html    # Used device purchasing, trade-ins, and anti-theft IDs
│   ├── history.html     # Operations history, returns, and multi-filter ledger
│   ├── reports.html     # Daily/monthly financials, shift logs, and net profits
│   ├── staff.html       # Employee administration, 7 job presets, perm audit log & 49-permission console
│   ├── profile.html     # Employee personal profile, PIN, and desktop theme setup
│   ├── settings.html    # Store info, tax toggle, login mode, invoice studio & database backups/restore hub
│   ├── receipt.html     # Thermal 80mm & A4 preview and WhatsApp sharing
│   ├── app.js           # Bridge api() caller, permissions, and invoice builder
│   ├── app.css          # Pre-compiled Tailwind CSS bundle
│   └── fonts/           # 23 local WOFF2 font files
├── data/
│   ├── shop.db          # Operating SQLite database (git-ignored)
│   ├── backups/         # Automated (startup + shift close) & manual ACID SQLite snapshots
│   └── receipts/        # Generated PDF invoices and vouchers (git-ignored)
├── docs/                # Comprehensive engineering and requirements documentation
├── installer/           # Inno Setup 6 Windows installer script (TechZone.iss)
├── tools/               # Data import and screenshot automation utilities
├── icon.ico             # Official application executable and window icon
├── TechZone.spec        # PyInstaller packaging configuration
├── build-exe.bat        # Automated single-click EXE builder
├── build-installer.bat  # Full release builder (EXE + Inno Setup + SHA256SUMS.txt)
└── push-github.bat      # Automated single-click Git/GitHub synchronization
```

---

## 6. Permissions Matrix (49 Granular Keys in 10 Groups)

The administrator (`role='admin'`) possesses unrestricted system access (for enabled modules). All non-admin staff (`role='cashier'`) have normalized boolean flags synchronized between `users.permissions` (JSON cache), the normalized `user_permissions` table, and `users.is_active` / `users.job_preset`. Canonical definitions live in `app/permissions.py`:

- **Strict Cashier Baseline (`cashier_strict`, default for new cashiers and v2 migration):** `pos_sell`, `shift_manage`, `receipt_view`, `customers_quick_pick` (`True`); all other 45 keys `False` (includes **Blind Close** mode where `shift_summary_view=False` hides expected cash/diff, and name/phone-only customer quick-pick with zero debt exposure).
- **7 Built-in Job Presets (`permission_roles`):** `cashier_strict`, `senior_cashier`, `sales_b2b`, `inventory_clerk`, `technician`, `accountant`, `store_manager`.

1. **POS & Shifts (`pos`, 9):** `pos_sell`, `shift_manage`, `shift_summary_view`, `pos_item_discount`, `pos_invoice_discount`, `pos_price`, `pos_credit_sale`, `pos_whatsapp`, `pos_categories_manage`.
2. **History, Returns & Receipts (`history`, 6):** `receipt_view`, `history_view_own`, `history_view_all`, `sales_return_own`, `sales_return`, `sales_post_discount`.
3. **B2B Sales & Quotes (`quotes`, 4):** `quotes_view`, `quotes_create_edit`, `quotes_convert`, `quotes_cancel_delete`.
4. **Customers & Debt (`customers`, 6):** `customers_quick_pick`, `customers_view`, `customers_debt_view`, `customers_edit`, `customers_payment`, `customers_delete`.
5. **Installments (`installments`, 4):** `installments_view`, `installments_collect`, `installments_create`, `installments_cancel`.
6. **Inventory & Costs (`inventory`, 5):** `inventory_view`, `inventory_edit`, `inventory_adjust`, `serials_view`, `cost_view`.
7. **Repair Workshop (`repair`, 4):** `repair_view`, `repair_create`, `repair_edit`, `repair_delete`.
8. **Used Devices (`buy_used`, 2):** `used_view`, `used_manage`.
9. **Reports (`reports`, 4):** `reports_sales_view`, `reports_profit_view`, `reports_shifts_view`, `reports_movements_view`.
10. **Staff, Settings & Backups (`admin`, 5):** `staff_view`, `staff_manage`, `settings_view_edit`, `templates_manage`, `backups_manage`.

---

## 7. Non-Negotiable Engineering Rules

1. **All Money in Minor Units:** Always store and compute currency as `INTEGER` minor units (`1 LE = 100 qirsh`). Never use floating-point types for financial transactions.
2. **100% Parameterized SQL:** Never concatenate or interpolate raw user strings into SQL queries. Always use `?` placeholders.
3. **Server-Side Authorization:** Never rely on frontend JavaScript checks for access control. Always enforce `_perm(key)` inside `app/api*.py`.
4. **Offline Purity:** Never introduce external network calls, CDNs, or runtime cloud dependencies.
5. **No Bundlers / No Heavy Frameworks:** Vanilla JavaScript and pre-compiled CSS only.
6. **Selfcheck Verification:** Every change must maintain all passing tests in `python app/selfcheck.py` (currently 234 checks).
7. **Commit Documentation:** Always update `AGENTS.md` and document changes in the same commit.

---

## 8. Changelog

### 2026-11-17 — Inventory Display Fix & Stocktake Report (`main`)
- **Inventory Blank Page Root-Cause Fix (`web/inventory.html`)**:
  1. Fixed fatal `SyntaxError: Identifier 'CAN_EDIT' has already been declared` where line 141 (`let CAN_EDIT = false;`) and line 384 (`let CAN_EDIT = false, ...`) both declared `CAN_EDIT`, aborting the entire `<script>` so stats, categories, and products never loaded.
  2. Fixed `m2-ok` and `openSerials()` permission guards to recognize `CAN_ADJUST` (`inventory_adjust`), hid `#btn-serials` when lacking both `serials_view`/`inventory_adjust`/`inventory_edit`, and added an empty-state table fallback.
- **Stocktake / Available vs. Out-of-Stock Filtering & Print Sheet (`app/api_inventory.py`, `app/api_reports.py`, `web/inventory.html`, `web/app.css`)**:
  1. Added `stock="available"` (`qty > 0`) filter in `InventoryMixin.products()` and `in_stock` / `total_qty` counters in `ReportsMixin.stock_stats()`.
  2. Added one-click quick stocktake filter pills (`الكل`, `الموجود (> 0)`, `مخزون منخفض`, `المنتهي (0)`), clickable KPI summary cards, and `#modal-stocktake` ("جرد المخزون — الموجود مقابل المنتهي") with live search, summary counters, and printable A4 stocktake sheet via `TZOS.printHtml` / `tzPrintPage`.
- **Verification (`app/selfcheck.py`)**: Added stocktake filter/stats tests and full `web/*.html` inline JS `node --check` validation (`234/234` passing, `contract ok (112 names)`).
- **Responsive Topbar Gap Fix (`web/desktop.html`)**: Narrowed `.hidden` override from `.top-btn.hidden` to `#top-settings-btn.hidden, #os-shift-pill.hidden, .ctx-item.hidden` so `#top-tile-btn`, `#top-showdesk-btn`, and `#top-wp-btn` (`hidden sm:inline-flex` / `hidden md:inline-flex`) render normally on desktop topbar without leaving empty space.

### 2026-11-17 — Desktop Context Menu & Topbar Settings Visibility Sync (`main`)
- **Desktop Context Menu Mirroring Start Menu (`web/desktop.html`, `web/app.css`, `app/selfcheck.py`)**:
  1. Fixed CSS specificity override where `.top-btn { display: inline-flex; }` and `.ctx-item { display: flex; }` appeared after `app.css` and overrode `.hidden`, keeping `#top-settings-btn` and unpermitted context items visible; added `.top-btn.hidden, .ctx-item.hidden { display: none !important; }` plus `max-height`/`overflow-y` on `#os-ctx-menu`.
  2. Replaced hardcoded `[data-ctx-app]` shortcuts in `#os-ctx-menu` (including duplicate bottom `settings`) with dynamic `TZOS.renderCtxMenu()` rendering `#os-ctx-apps` directly from `PERMITTED_APPS` so the right-click menu matches the Start Menu (`renderStartMenu`) and active module/user permissions identically. Rebuilt `web/app.css` and added selfcheck assertion (`232/232` passing).

### 2026-11-17 — Granular RBAC Overhaul (49 Permissions, 10 Groups, Blind Close, Zero-Leak Hardening & Staff Console) (`main`)
- **Canonical Permission Registry & Schema (`app/permissions.py`, `app/db.py`, `app/fresh_db.py`)**:
  1. Created `app/permissions.py` defining **49 granular permissions** across **10 groups**, `STRICT_CASHIER_PERMS` (`pos_sell`, `shift_manage`, `receipt_view`, `customers_quick_pick`), and **7 built-in job presets** (`cashier_strict`, `senior_cashier`, `sales_b2b`, `inventory_clerk`, `technician`, `accountant`, `store_manager`).
  2. Restructured SQLite schema to **31 tables**: added `user_permissions`, `permission_roles`, and `perm_audit_log`, added `users.is_active` and `users.job_preset`, updated `DEFAULT_MODULES` `perm_keys`, and added idempotent `_migrate_strict_permissions_v2()` (resetting existing non-admin accounts to `cashier_strict`). Updated `app/fresh_db.py` to carry over `user_permissions`, `permission_roles`, and `perm_audit_log`.
- **Backend Zero-Leak Enforcement (`app/api_common.py`, `app/api_auth.py`, `app/api_sales.py`, `app/api_customers.py`, `app/api_inventory.py`, `app/api_quotes.py`, `app/api_services.py`, `app/api_installments.py`, `app/api_reports.py`, `app/modules_map.py`)**:
  1. Enforced `is_active` session/login checks, added `_perm_all()` / `_scope_check()`, and added `permissions_schema()`, `user_toggle_active()`, and `perm_audit_list()`.
  2. Eliminated cross-employee/module data leaks: `shift()` hides store-wide `today` sales without `history_view_all`/`reports_sales_view`; `sale()`/`quotation()`/`sale_discount()`/`sale_modify_from_cart()`/`sale_return()` enforce record ownership unless `history_view_all`/`sales_return` is held; `sale_create()` validates server-side catalog prices (`pos_price`), invoice discount (`pos_invoice_discount`), and credit sales (`pos_credit_sale`).
  3. Implemented **name/phone-only customer quick-pick** (`customers_quick_pick` without `customers_debt_view` redacts `debt` and ledger fields) and **Blind Close (الجرد الأعمى)** when `shift_summary_view=False` (added `cash_inst` to `shift_close` expected cash, stores accurate `expected_cash`/`diff` for admins, redacts from response).
- **Frontend Security Guards & Comprehensive Staff Console (`web/staff.html`, `web/app.js`, `web/desktop.html`, `web/pos.html`, `web/history.html`, `web/repair.html`, `web/receipt.html`, `web/*.html`, `web/app.css`)**:
  1. Fixed `CURRENT_USER.permissions.includes(...)` TypeError bugs in `history.html` and `repair.html`, added `pageInit()` guards across `sales_quotes.html`, `history.html`, `repair.html`, and `receipt.html`, filtered desktop KPIs/context menu by permissions, and added Blind Close + debt redaction in `pos.html`.
  2. Rewrote `web/staff.html` with preset selector buttons, perm-copy between staff, live permission search, 10 collapsible categorized groups with dependency resolution & risk badges, active/suspended account toggling, and permission audit log tab; recompiled `web/app.css`.
- **Verification (`app/selfcheck.py`)**: Updated permission expectations and added strict-RBAC, zero-leak, Blind Close, account activation, audit log, and v2 migration tests (`231/231` passing, `contract ok (112 names)`).

### 2026-11-17 — Cashier Tax Settings Fix, In-App POS Print Preview & Silent Direct Print (`main`)
- **Cashier Tax / Runtime Settings Fix (`app/api_auth.py`, `web/pos.html`, `web/settings.html`)**:
  1. Fixed root cause where `AuthSettingsMixin.settings()` required `settings_manage`, causing `pageInit()` to silently set `SETTINGS = {}` for cashiers and leaving `TAX_ON = SETTINGS.tax_enabled !== '0'` (`true`) even when tax was disabled in Settings.
  2. Allowed any authenticated user (`self._user()`) to read store/runtime settings via `settings()`, stripping sensitive security keys (`login_fail_state`, `login_max_attempts`, `login_lockout_minutes`, `customer_ledger_migrated`) when lacking `settings_manage` (while `settings_save()` still requires `settings_manage`).
  3. Added `syncSettingsRuntime()` in `web/pos.html` and wired `settings.html` save broadcast to update `window.top.SETTINGS` and refresh open POS iframes live.
- **In-App POS Print Preview & Silent Direct Printing (`app/db.py`, `app/api_auth.py`, `app/modules_map.py`, `web/app.js`, `web/desktop.html`, `web/pos.html`, `web/settings.html`, `web/receipt.html`, `web/history.html`, `web/repair.html`, `web/sales_quotes.html`, `web/app.css`)**:
  1. Added settings `pos_print_preview` (default `'1'`), `print_show_dialog` (default `'0'`), and `print_printer_name` (default `''`) in `db.py` and `settings_save()`.
  2. Implemented `printers_list()` (via Windows `winspool.drv`) and `silent_print()` (via WebView2 `CoreWebView2.PrintAsync`, falling back to dialog only if WebView2 isn't active), registered in `CORE_METHODS` (`app/modules_map.py`).
  3. Added `#pos-print-preview-modal` in `web/pos.html` (thermal 80mm/58mm + A4 preview toggle, Print button, format-aware WhatsApp PDF button sending A4 PDF via `renderA4DocumentToJpeg` when A4 is selected, Close without printing) shown after sale completion/lookup/modification when `pos_print_preview !== '0'`.
  4. Added `tzPrintPage()` in `web/app.js` and updated `TZOS.printHtml()` + standalone print handlers to print silently by default (`print_show_dialog === '0'`) or open the Windows printer selection dialog when enabled (`print_show_dialog === '1'`).
  5. Added the "إعدادات الطباعة ومعاينة الفواتير" control card in `web/settings.html` and recompiled `web/app.css`.
- **Verification (`app/selfcheck.py`)**: Added 5 automated checks covering cashier settings read, security key stripping, print settings persistence, `printers_list`/`silent_print`, and frontend contract; all `200/200` checks pass (`contract ok (109 names)`).

### 2026-11-16 — Windows Setup Installer (Inno Setup 6) & GitHub Release v2.0.0 (`main`)
- **Installer (`installer/TechZone.iss`, `build-installer.bat`)**:
  1. Created Inno Setup 6 installer script producing `dist/TechZone-Setup-v2.0.0.exe` (Arabic + English wizard, `icon.ico`, `WizardStyle=modern`, LZMA2/ultra64 compression, consistent `AppId` for seamless in-place upgrades preserving `data/`).
  2. Configured `PrivilegesRequired=lowest` with optional all-users elevation dialog (`PrivilegesRequiredOverridesAllowed=dialog`), `users-modify` permissions on `data/`, `data/backups/`, and `data/receipts/`, Desktop/Start Menu/optional autostart shortcuts, and WebView2 Runtime availability check.
  3. Added `build-installer.bat` automating PyInstaller EXE build + Inno Setup compile + `dist/SHA256SUMS.txt` checksum generation.
- **Verification & Release**: Built `dist/TechZone.exe` (`20,265,326` bytes) and `dist/TechZone-Setup-v2.0.0.exe` (`21,572,929` bytes) with verified `icon.ico`, confirmed `python app/selfcheck.py` passes (`195/195`), and published GitHub Release `v2.0.0`.

### 2026-11-16 — Documentation Sync, 20-Screen Preview Pack & Layout Polish (`main`)
- **UI & Tooling (`web/buy_used.html`, `web/owner.html`, `tools/take_screenshots.py`)**:
  1. Fixed standalone flex shell on `web/buy_used.html` (`flex flex-col md:flex-row`) so the sidebar and main workspace render side by side on desktop screens.
  2. Added `?tab=` URL query initialization support in `web/owner.html` (`modules`, `profiles`, `labels`, `security`, `audit`).
  3. Updated `tools/take_screenshots.py` to seed an isolated temporary `SHOP_DB` (including installments, repairs, used device purchase, quotation, backup snapshot, and active Owner Mode session) and captured 20 up-to-date preview PNGs in `screenshots/` (`01`..`20`).
- **Documentation Sync (`README.md`, `CLAUDE.md`, `AGENTS.md`, `docs/*.md`)**: Updated `README.md` (all 20 sections + screenshots + 18 accurate permissions + architecture + backups + installments + Owner Mode/business profiles) and aligned `CLAUDE.md`, `docs/README.md`, `docs/PRD.md`, `docs/ARCHITECTURE.md`, `docs/DATA-MODEL.md`, `docs/SECURITY.md`, `docs/TESTING.md`, `docs/DEPLOYMENT.md`, `docs/IMPLEMENTATION-PLAN.md`, and `docs/ROADMAP.md` with current counts (28 tables, 18 permissions, 17 pages, 8 mixins, 195 selfcheck checks).
- **Verification (`app/selfcheck.py`)**: Ran `python app/selfcheck.py` after final edits (`195/195` checks passing, `contract ok (107 names)`).

### 2026-11-16 — Owner Control Enhancement (Isolated Worktree): Fresh Clean DB per Profile & Empty-Category Fix
- **Fresh Profile Database Builder (`app/fresh_db.py`, `app/api_owner.py`)**:
  1. Added `build_fresh_profile_db()` and `fresh_db` / `carry_over` / `reset_store_info` options to `profile_apply()`.
  2. Always takes a full `before_fresh_profile_db` SQLite backup before replacing the live DB atomically via SQLite Online Backup API after running `PRAGMA foreign_key_check`.
  3. Always preserves `users`, `owner_auth`, `owner_audit_log`, `business_profiles`, `settings`, and target `modules`/`ui_labels`; optionally carries over selected operational groups (`products`, `customers` with clean `OPEN-BAL` adjustment rows when sales are omitted, `sales`, `repairs`), or creates a clean DB with only users + profile demo catalog.
- **Categories Visibility Fix (`app/api_inventory.py`)**: Updated `InventoryMixin.categories()` to hide empty non-profile categories (`HAVING COUNT(p.id) > 0`) when `hide_empty_categories='1'` (`exclusive_demo`), resetting cleanly when disabled or when a new category is created.
- **Owner UI (`web/owner.html`, `web/app.css`)**: Upgraded profile preview/apply panel (`#profile-preview-box`) with DB mode selector (in-place vs. fresh clean DB) and selective carry-over checklist; rebuilt `web/app.css`.
- **Verification (`app/selfcheck.py`)**: Added 3 checks covering `exclusive_demo` category hiding, selective customer carry-over `fresh_db`, and clean empty `fresh_db` (`195/195` passing, `contract ok (107 names)`).

### 2026-11-16 — Owner Control Enhancement (Isolated Worktree): Editable Business Profiles CRUD & Per-Profile Demo Catalogs
- **Database Schema (`app/db.py`, `app/profiles.py`, `app/api_inventory.py`)**:
  1. Added `business_profiles` table seeded idempotently from `DEFAULT_BUSINESS_PROFILES` with realistic Egyptian-market `demo_catalog` datasets (stored in minor units) for `retail_electronics` (14 items), `generic_shop` (10 items), `restaurant` (11 items), and `pharmacy` (11 items).
  2. Added `demo_profile` column on `products` and `categories` (plus non-destructive `ALTER TABLE` migration) and updated `InventoryMixin.categories()` so inactive demo categories stay hidden while shop-created categories (`demo_profile IS NULL`) remain visible.
- **Full Profile CRUD & Demo Switching (`app/api_owner.py`, `app/modules_map.py`)**:
  1. Added `owner_profile_save()` (create/edit any profile: enabled modules with `MODULE_REQUIRES` validation, custom per-module titles, label overrides, default start page, and editable `demo_catalog` items), `owner_profile_delete()` (guards active/last profile), and `owner_profiles_reset_defaults()`.
  2. Updated `profile_apply()` to support `apply_demo` and `exclusive_demo` flags, toggling profile demo products safely via `active=0/1` without breaking invoice/repair foreign keys.
- **Owner UI (`web/owner.html`, `web/app.css`)**: Added "إضافة قالب نشاط جديد", "تعديل" (full modal `#modal-profile-form` for modules, module titles, labels, and demo catalog rows), "حذف", "استعادة القوالب الافتراضية", and demo-mode checkboxes in the apply preview; recompiled `web/app.css`.
- **Verification (`app/selfcheck.py`)**: Added checks for per-profile demo switching and full profile create/edit/apply/delete/reset; `192/192` checks pass (`contract ok (107 names)`).

### 2026-11-16 — Owner Control Phase 5 (Isolated Worktree): Hardening, CSS Rebuild & Documentation
- **Hardening (`app/main.py`, `web/owner.html`, `web/app.css`)**:
  1. Added `window.events.closed` hook in `app/main.py` clearing `_STATE["owner"]` and `_STATE["user"]` on native window close.
  2. Synced sliding idle-timeout badge (`syncOwnerTimer()`) across owner dashboard actions in `web/owner.html` and recompiled `web/app.css`.
- **Documentation & ADR**: Updated `docs/DATA-MODEL.md`, `docs/SECURITY.md`, `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`, and `docs/OPEN-QUESTIONS.md`, and added `docs/adr/0003-owner-mode-and-module-registry.md`.
- **Verification (`app/selfcheck.py`, stress DB copy)**: Added 3 Phase 5 checks (`190/190` passing, `contract ok (104 names)`), and verified non-destructive migration on a temporary copy of `data/shop.db` (3,001 customers, 30,002 sales, 13 modules seeded in `127.01ms`).

### 2026-11-16 — Owner Control Phase 4 (Isolated Worktree): Business Profiles & Custom Labels
- **Profiles & Labels Registry (`app/profiles.py`, `app/db.py`, `app/api_owner.py`)**:
  1. Added `ui_labels` table and `app/profiles.py` defining `BUSINESS_PROFILES` (`retail_electronics`, `generic_shop`, `restaurant`, `pharmacy`) and `DEFAULT_LABELS`/`LABEL_KEYS`.
  2. Implemented `profiles_list()`, `profile_apply(dry_run=True/False)` (diff preview, untouched custom clones, safe `default_start_page` fallback), and `labels_save()` (allowlist + 40-char limit), and wired `ui_labels` into `ui_config()`.
- **Frontend Labels & Profile UI (`web/app.js`, `web/owner.html`, `web/pos.html`, `web/inventory.html`, `web/customers.html`, `web/repair.html`, `web/buy_used.html`)**:
  1. Added `DEFAULT_LABELS`, `t()`, and `applyLabels()` in `app.js` plus `[data-label]` hooks on core page titles.
  2. Added "نوع النشاط" (preview & apply) and "المسميات" tabs to `web/owner.html`.
- **Verification (`app/selfcheck.py`)**: Added 5 Phase 4 checks; `187/187` checks pass (`contract ok (104 names)`).

### 2026-11-16 — Owner Control Phase 3 (Isolated Worktree): Edit, Clone & Delete Sections
- **Backend Validation & CRUD (`app/api_owner.py`)**: Added `_validate_module_fields()` (regex checks on icon/color/params, title length, permission key allowlist), `module_save()`, `module_clone()` (`c_<slug>` unique alias inheriting source page & permissions), and `module_delete()` (custom clones only; builtin/core deletions refused).
- **Frontend UI (`web/owner.html`, `web/desktop.html`)**:
  1. Added Edit and Clone modal (`#modal-module-form`) with color presets, optional query `params`, explicit shared-data notice, and Delete confirmation for custom clones.
  2. Updated `desktop.html` `openUrlInApp()` to match `full_url` cleanly.
- **Verification (`app/selfcheck.py`)**: Added 5 Phase 3 checks (clone params, input validation, edit, delete protection, pre-change backup + audit trail); `182/182` checks pass (`contract ok (101 names)`).

### 2026-11-16 — Owner Control Phase 2 (Isolated Worktree): Module Registry & Server-Side Guard
- **Database Schema & Seeding (`app/db.py`)**: Added `modules` table (`DEFAULT_MODULES` for all 13 built-in sections; `settings`, `profile`, `receipt` marked `is_core=1`), idempotent `seed_modules_if_empty()`, and `business_profile` / `structure_version` settings.
- **Server-Side Guard (`app/modules_map.py`, `app/api.py`, `app/api_common.py`)**:
  1. Created `modules_map.py` classifying all 100 public `Api` methods into `API_MODULE_MAP` or `CORE_METHODS`, plus `MODULE_REQUIRES` dependency rules.
  2. Added pre-dispatch guard in `Api.call()` blocking disabled module methods even for `admin`.
- **Owner Module API & Dynamic Start Pages (`app/api_owner.py`, `app/api_auth.py`)**:
  1. Added `ui_config`, `modules_all`, `module_toggle` (enforces core protection & dependency checks + automatic pre-change backup), `module_reorder`, and `modules_reset_defaults`.
  2. Replaced hardcoded start-page sets in `api_auth.py` with dynamic enabled-module validation and safe fallback.
- **Frontend Dynamic Registry (`web/app.js`, `web/desktop.html`, `web/owner.html`, `web/pos.html`, `web/settings.html`, `web/profile.html`, `web/staff.html`)**:
  1. `app.js` loads `ui_config`, builds `NAV` dynamically, and enforces direct-page open guard in `pageInit()`.
  2. `desktop.html` derives `PERMITTED_APPS` from `UI_CONFIG.modules`, guards widgets when modules are disabled, and falls back cleanly.
  3. Added "الأقسام والهيكلة" tab to `web/owner.html` (toggle, up/down reorder, factory reset) and dynamic start-page dropdowns in `settings.html`, `profile.html`, and `staff.html`.
- **Verification (`app/selfcheck.py`)**: Added 8 Phase 2 checks including `modules_map` completeness check; `177/177` checks pass (`contract ok (98 names)`).

### 2026-11-16 — Owner Control Phase 1 (Isolated Worktree): Owner Auth, Recovery Key & Admin PIN Reset
- **Isolated Branch/Worktree**: Executed on branch `feat/phase-a-performance` in `../project001-worker/` per `docs/OWNER-CONTROL-PLAN.md`.
- **Database Schema (`app/db.py`)**: Added `owner_auth` and `owner_audit_log` tables (additive schema + `_ensure_schema_columns`), plus `hash_secret()` PBKDF2-SHA256 helper.
- **Backend Owner Session & Mixin (`app/api_common.py`, `app/api_auth.py`, `app/api_owner.py`, `app/api.py`)**:
  1. Added independent `_STATE["owner"]` session with 10-minute sliding idle timeout (`OWNER_SESSION_TTL = 600`), cleared on `logout()` and `owner_logout()`.
  2. Implemented `OwnerMixin`: `owner_status`, `owner_setup` (admin-only first run, returns one-time 20-char recovery key), `owner_login` (5-attempt / 15-min persistent DB lockout), `owner_logout`, `owner_change_passphrase`, `owner_recover` (rotates recovery key), `owner_reset_admin_pin` (accepts passphrase or recovery key, enforces PIN strength & uniqueness), and `owner_audit_list`.
- **Frontend (`web/owner.html`, `web/index.html`, `web/desktop.html`)**:
  1. Created `web/owner.html` (first-run setup wizard, one-time recovery key reveal, owner login + lockout countdown, recovery flow, passphrase change, and audit log viewer).
  2. Added 2-second long-press entry on store logo/name in `web/index.html` and Start Menu header in `web/desktop.html`, plus "نسيت رمز المدير؟" modal in `web/index.html`.
- **Verification (`app/selfcheck.py`)**: Added 11 Phase 1 checks; `169/169` checks pass (`contract ok (93 names)`).

### 2026-11-15 — Phase D (Isolated Worktree): Installments Management System (نظام الأقساط)
- **Isolated Branch/Worktree**: Executed on branch `feat/phase-a-performance` in `../project001-worker/` keeping `main` and production DB untouched.
- **Database Schema, Indexes & Ledger Integration (`app/db.py`, `app/api_common.py`, `app/api_customers.py`, `app/api_sales.py`)**:
  1. Added `installment_plans`, `installment_items`, and `installment_payments` tables plus 8 performance indexes (`idx_inst_plans_*`, `idx_inst_items_*`, `idx_inst_pay_*`) and `customer_ledger.plan_id` column with automatic schema migration.
  2. Added `installments_view` (`True` default) and `installments_manage` (`False` default) to `DEFAULT_CASHIER_PERMS` (`18` total keys) and `installment_prefix` (`INS-`) to `DEFAULT_POS_TEMPLATE`.
  3. Updated `_customer_debt_summary()`, `_migrate_customer_ledger()`, `customers_delete()` guard, `customer_history()`, and `shift_summary()` (`cash_installments`, `wallet_installments`) to unify installment balances, down payments, and collections with zero double-counting when converting existing credit sales (`sale_id`).
- **Installments Domain Engine (`app/api_installments.py`, `app/api.py`)**:
  1. Implemented `InstallmentsMixin`: `installment_alerts`, `installments_list`, `installment_eligible_sales`, `installment_detail`, `installment_create` (direct/inventory with stock/serial deduction & credit-sale conversion, %/fixed fees, monthly/weekly/custom schedules with exact minor-unit rounding), `installment_pay` (partial/multi-item allocation with `INP-` receipts), `installment_cancel` (unpaid plans only, reversing ledger/stock), and `installment_whatsapp_reminder` (using shared `_normalize_eg_phone` helper in `app/api_common.py`).
- **Frontend UI & OS Shell Integration (`web/installments.html`, `web/desktop.html`, `web/app.js`, `web/staff.html`, `web/settings.html`, `web/customer_details.html`, `web/app.css`)**:
  1. Built `web/installments.html` with KPI cards, overdue/upcoming alert filters, pre-sale calculator & live schedule preview, contract details/collection/cancellation modals, printable contract & receipt views, WhatsApp reminder triggers, and `?plan_id=` / `?customer_id=` deep-linking.
  2. Registered app icon (`نظام الأقساط`) in `web/desktop.html` & `web/app.js`, start-page/permission controls in `web/staff.html` & `web/settings.html`, customer installments table + fixed ledger navigation in `web/customer_details.html`, and recompiled `web/app.css`.
- **Verification (`app/selfcheck.py`, stress DB)**:
  - Added Phase D automated checks (permissions, standalone schedule/stock/debt sync, overdue alerts, WhatsApp reminder, partial/full collections & shift reconciliation, unpaid cancellation, credit-sale conversion with zero double-counting, and UI modal checks): `158/158` checks passing (`contract ok (85 names)`).
  - Verified auto-migration and query latency on `../project001-worker/data/shop.db` (3,001 customers, 30,002 sales): schema migration `106.71ms`, `installment_alerts` `3.77ms`, `installments_list` `5.25ms`, `customers_list` `5.95ms`.

### 2026-11-15 — Phase B & Phase C (Isolated Worktree): API Domain Modularization, Customer Ledger & Cached Balances
- **Isolated Branch/Worktree**: Continued on branch `feat/phase-a-performance` in `../project001-worker/` keeping `main` and production DB untouched.
- **Phase B — Backend API Modularization & WhatsApp Reliability (`app/api*.py`)**:
  1. Split `app/api.py` (~3,100 lines) into focused domain mixins while preserving the exact `Api` public surface (78 contracted methods verified): `app/api_common.py`, `app/api_auth.py` (`AuthSettingsMixin`), `app/api_inventory.py` (`InventoryMixin`), `app/api_customers.py` (`CustomersMixin`), `app/api_sales.py` (`SalesMixin`), `app/api_quotes.py` (`QuotesMixin`), `app/api_services.py` (`ServicesMixin`), and `app/api_reports.py` (`ReportsMixin`), with `app/api.py` acting as a thin facade + re-export module.
  2. Added `pdf_dir` to `whatsapp_send_invoice` and `whatsapp_send_quote` return payloads for direct local PDF folder access.
- **Phase C — Customer Accounting Ledger (`customer_ledger`) & Cached Debt Columns (`app/db.py`, `app/api_common.py`, `app/api_customers.py`, `app/api_sales.py`, `app/api_quotes.py`)**:
  1. **Schema & Auto-Migration (`app/db.py`)**: Added cached summary columns (`total_purchases`, `credit_total`, `paid_total`, `debt`) on `customers`, created `customer_ledger` table (`credit_sale`, `voucher`, `return_credit`, `adjustment`, `installment_charge`, `installment_payment`) with performance indexes (`idx_customers_debt`, `idx_ledger_cust_id`, `idx_ledger_sale`, `idx_ledger_voucher`), and added one-time `_migrate_customer_ledger()` backfill.
  2. **Transactional Ledger Sync**: Updated `sale_create`, `_convert_quote_to_sale_in_tx`, `sale_discount`, `sale_modify_from_cart`, `sale_return`, `customer_payment_create`, and `customer_payment_delete` to append immutable ledger rows (`_append_ledger_entry` / `_sync_sale_ledger_delta`) and refresh cached customer totals (`_refresh_customer_cache`) inside the same SQLite transaction.
  3. **Fast O(1) Reads**: Updated `customers_list`, `customers_search`, and `customer_history` to read cached customer balances and pre-computed `customer_ledger` rows directly (with legacy fallback).
- **Verification & Stress Benchmarks (`app/selfcheck.py`)**:
  - Expanded `app/selfcheck.py` with Phase C ledger & migration checks (`137/137` checks passed).
  - Stress-tested `../project001-worker/data/shop.db` (3,000 customers, 30,002 sales): historical ledger backfill completed in `223.9ms` (13,500 ledger rows); `customers_list(50)` `1.31ms`, `customers_list(debt_only=True)` `1.43ms`, `customers_search` `0.91ms`, indebted `customer_history` `1.75ms`, and `used()` `1.19ms`.

### 2026-11-15 — Fix: Used Devices Purchase (`buy_used.html`) Scroll Freeze, Add Crash & Edit Support
- **Issues**:
  1. `<main>` in `web/buy_used.html` had `lg:h-[calc(100vh-4rem)] overflow-hidden` without `min-h-0` or bounded grid rows (`lg:grid-rows-[minmax(0,1fr)]`), freezing page scrolling and clipping the bottom form fields/button (`إتمام الشراء`) and table.
  2. Seller autocomplete called `api('customers_search', { q, limit: 8 })`, failing because `Api.customers_search` did not accept `limit`.
  3. No edit capability existed for recorded used device purchases.
- **Fixes**:
  1. Added `limit=20` parameter (clamped `1..100`) to `Api.customers_search()` and added `Api.used_update()` (with linked `products` & `serials` synchronization) in `app/api.py`.
  2. Rebuilt `web/buy_used.html` flex/grid scroll hierarchy (`min-h-0`, `lg:grid-rows-[minmax(0,1fr)]`, `shrink-0` cards, responsive scroll), added row edit (`تعديل`) workflow + cancel banner, and submit button lock state; recompiled `web/app.css`.
  3. Added regression checks in `app/selfcheck.py` (all 125/125 checks passing).

### 2026-11-15 — Phase A (Isolated Worktree): Customers Performance, DB PRAGMAs/Indexes & Delete Protection
- **Isolated Branch/Worktree**: Executed on branch `feat/phase-a-performance` in `../project001-worker/` keeping `main` untouched.
- **SQL Set-Based Customer Debt Aggregation (`app/api.py`)**: Replaced the N+1 Python loop in `customers_list()` and `customers_search()` with a shared SQL CTE (`_customers_enriched_cte`) computing totals, `debt_only` filtering, and `LIMIT/OFFSET` directly in SQLite (reducing 3,000-customer/30,000-sale benchmark from ~12.4s to <100ms, and fixing missing `total_purchases` in `customers_search()`).
- **Customer Accounting Protection (`app/api.py`)**: Updated `customers_delete()` to refuse deleting customers with unpaid debt or existing sales/payment vouchers (preventing silent `customer_payments` cascade loss and orphaned debt).
- **SQLite Tuning & Performance Indexes (`app/db.py`)**: Enabled `synchronous=NORMAL`, `temp_store=MEMORY`, `cache_size=-16000` per connection, moved `journal_mode=WAL` to one-time initialization, and added `_PERFORMANCE_INDEXES` (`customers(name, phone)`, `sales(customer_phone)`, partial `sales(customer_name) WHERE customer_id IS NULL`, `sales(doc_type, status)`, `payments(method, sale_id)`, `products(active, name)`, `products(sku)`).
- **UI Search Debounce (`web/customers.html`)**: Added 200ms debounce on search input and avoided redundant `customers_list` calls when `summary` is already loaded.
- **Verification (`app/selfcheck.py`)**: Added checks 113–117 covering `debt_only`, `customers_delete` guard, and 1,000+ customer speed test; all 120/120 checks pass.

### 2026-11-15 — Fix: WhatsApp A4 PDF Layout Now Matches Preview (WYSIWYG)
- **Issue**: `renderA4DocumentToJpeg()` in `web/app.js` re-drew the invoice by hand on a Canvas (different fonts, spacing, columns), so the WhatsApp PDF differed from the HTML preview.
- **Fix**: It now renders the exact `buildA4InvoiceHtml()` output via SVG `foreignObject` (794px x2) with local IBM Plex woff2 fonts embedded as base64 (offline). Old canvas renderer kept as `renderA4DocumentToJpegLegacy` fallback. Backend unchanged; 115/115 checks pass.

### 2026-11-15 — Fix: Saved Document A4 Preview Cropping & Exit/Back Trap in Sales & Quotations
- **Issue**: After saving or previewing a saved invoice/quotation in `web/sales_quotes.html` (`#doc-modal`), uncompiled Tailwind classes (`max-w-4xl`, `max-h-[94vh]`) in `web/app.css` left `#doc-modal` height unconstrained (`~1220px`), pushing the header/close button and top/bottom of the A4 template off-screen so users saw a cropped document and could only exit by refreshing.
- **Executed Fix**:
  1. **Scrollable Modal Card & Explicit CSS Safeguards (`web/sales_quotes.html`)**: Added explicit `#doc-modal`, `#doc-modal-card` (`max-width: 900px; max-height: 92vh`), and `#modal-doc-body` (`flex: 1 1 0%; min-height: 0; overflow-y: auto`) rules plus `scrollTop = 0` reset on `openDocModal()`, ensuring the full A4 template renders cleanly from top to bottom matching `#live-a4-preview`.
  2. **Accessible Exit & Back Navigation (`web/sales_quotes.html`, `web/history.html`, `web/receipt.html`)**: Added `closeDocModal()`, prominent top (`#modal-btn-close`) and sticky bottom (`#modal-btn-back-bottom`) back/close buttons, backdrop click and `Escape` key dismissal, `?view=<id>` deep-linking from `web/history.html`, and a back button in `web/receipt.html`.
  3. **Tailwind CSS Recompilation (`web/app.css`)**: Rebuilt `web/app.css` via `npx tailwindcss -i web/tailwind.css -o web/app.css --minify` so `max-w-4xl`, `max-h-[92vh]`, `max-h-52`, `max-h-64`, `min-w-[180px]`, and `min-h-0` are compiled.
  4. **Regression Verification (`app/selfcheck.py`)**: Added check verifying `#doc-modal-card`, `#modal-btn-close`, `#modal-btn-back-bottom`, `closeDocModal`, `scrollTop = 0`, and compiled CSS utilities. All 115 checks pass.

### 2026-11-12 — Safe In-App Database Restore (`db_restore`) with Pre-Restore Safety Snapshots
- **Goal & Request**: Implement and explain database restore functionality: provide safe in-app snapshot restoration for the manager with automatic pre-restore safety backups, integrity checks, and explain emergency manual file recovery.
- **Executed Work**:
  1. **Safe Database Restoration Engine (`app/db.py`)**: Added `restore_database(backup_name)` using SQLite Online Backup API in reverse (`bck_conn.backup(dest_conn)`), prefixed by an automated pre-restore safety snapshot (`shop_YYYYMMDD_HHMMSS_before_restore.db`) to ensure zero data loss, along with `PRAGMA quick_check` verification.
  2. **Backend API Endpoint (`app/api.py`)**: Added `db_restore` gated by `settings_manage` (manager only, denied for cashiers).
  3. **Manager UI Control (`web/settings.html`)**: Added "استرجاع هذه النسخة" action button for each snapshot with confirmation modal, live feedback, and state reloading.
  4. **Regression Verification (`app/selfcheck.py`)**: Added automated checks 105 and 108 verifying cashier denial and successful safe restoration cycle. All 114 checks pass.

### 2026-11-12 — Manager Backups UI Hub in Settings & Cashier Permission Gates
- **Goal & Request**: Provide a dedicated manager visual interface for database backups (`db_backup` & `backups_list`) in `web/settings.html`, and ensure strict access control where this feature is accessible only to the manager (`settings_manage`) and completely blocked for cashiers.
- **Executed Work**:
  1. **Manager Backups UI Tab (`web/settings.html`)**: Added a 4th tab "النسخ الاحتياطي وقاعدة البيانات" featuring:
     - Real-time status cards: Automated backup health badge, total snapshots count, total size formatted in KB/MB, and local storage directory path (`data/backups/`).
     - Action buttons: "أخذ نسخة احتياطية فورية الآن" with loading state and toast feedback, and "تحديث القائمة".
     - Backups audit table: Lists all snapshots with file names, reasons (daily startup, shift close, manual admin), formatted timestamps, file sizes, and integrity status.
  2. **Access Control Enforcement**: Confirmed `settings.html` and endpoints `db_backup` / `backups_list` are gated exclusively by `settings_manage` / `admin`. Cashiers cannot see the settings app or invoke the endpoints.
  3. **Regression Tests (`app/selfcheck.py`)**: Added checks 103, 104, 107 verifying cashier denial for `db_backup` and `backups_list`, and DOM verification for `settings.html` backup components. All 112 checks pass.

### 2026-11-12 — Fix: Resolve Parameter Mismatch & Unresponsiveness in Default PIN Change Modal
- **Issue**: Attempting to change default admin PIN from modal dialog `#modal-force-pin` failed with error `"معاملات غير صالحة للطلب"` due to keyword argument mismatch (`pin` passed instead of `new_pin`), leaving the dialog unclosed and appearing frozen.
- **Executed Fix**:
  1. **Backend Signature (`app/api.py`)**: Added `pin=None` keyword parameter alias to `profile_save()`, automatically routing to `new_pin`. Synchronized `_STATE["user"]["force_change_pin"]` after profile update.
  2. **Frontend UI UX (`web/index.html`)**: Sent both `new_pin` and `pin` in payload, added Enter key navigation between new/confirm PIN fields, disabled button with visual state during save, and smoothly cleared `force_change_pin` upon redirect.
  3. **Automated Regression (`app/selfcheck.py`)**: Added Check 106 verifying `profile_save` with `pin` keyword updates the PIN and clears `force_change_pin`. All 109 checks pass.

### 2026-11-12 — Automated DB Backups, Mandatory Default PIN Change, & POS Global Barcode Scanner
- **Goal & Request**: Execute the highest-priority security and operational improvements from the implementation roadmap: automated snapshot backups, default credential protection, and cashier high-speed hardware scanning.
- **Executed Work**:
  1. **Automated SQLite Online Backups (`app/db.py`, `app/api.py`, `app/main.py`)**:
     - Added `backup_database(reason)` using SQLite's native online backup API (`src_conn.backup(dest_conn)`) to ensure zero-lock ACID consistent copies in `data/backups/shop_YYYYMMDD_HHMMSS_{reason}.db`.
     - Automated backup trigger on every cashier shift closure (`shift_close()`) and daily on app startup (`daily_startup_backup()`).
     - Added `_rotate_backups` retention policy maintaining the latest 30 snapshots and pruning older files.
     - Added admin API endpoints `db_backup` and `backups_list` with `settings_manage` authorization.
  2. **Mandatory First-Run Default PIN Protection (`app/api.py`, `web/index.html`)**:
     - Added server-side detection in `login()`: if admin account uses the seeded default PIN (`1234`), sets `force_change_pin: True`.
     - Added clean modal dialog (`#modal-force-pin`) in `web/index.html` blocking access until the admin sets a strong, non-default PIN (4-8 digits) with confirmation.
  3. **Global Barcode Scanner Listener in POS (`web/pos.html`)**:
     - Added global high-speed keydown listener (< 85ms burst detection) that captures USB/Bluetooth barcode scanner inputs without requiring focus in the search box.
     - Automatically resolves exact SKU/barcode match and adds product directly to cart via `addToCart()`.
  4. **Regression Verification (`app/selfcheck.py`)**:
     - Expanded test suite from 104 to 108 checks covering backup creation, backup listing, forced PIN change flags, and barcode listener DOM verification. All 108 checks pass.

### 2026-11-12 — Complete Project-Kickstart Documentation Suite & Architecture Alignment
- **Goal & Request**: Conduct comprehensive project analysis using `/project-kickstart` skill, formalize missing engineering documentation, establish quality baselines from the code audit, archive historical logs, and provide actionable development recommendations.
- **Executed Work**:
  1. **Documentation Suite Creation (`docs/`)**: Authored 12 structured project documents adhering to project-kickstart standards:
     - `docs/PRD.md` — Product requirements document (Arabic).
     - `docs/ROADMAP.md` — Multi-phase development roadmap with test gates (Arabic).
     - `docs/OPEN-QUESTIONS.md` — Open architectural and business decisions log (Arabic).
     - `docs/ARCHITECTURE.md` — System architecture, sequence flows, IPC bridge, and module layouts.
     - `docs/DATA-MODEL.md` — Schema specifications for all 19 tables and access control matrix.
     - `docs/STACK.md` — Verified technical stack versions and upgrade constraints.
     - `docs/CODING-STANDARDS.md` — Coding guidelines, money math, SQL, and RTL styling rules.
     - `docs/TESTING.md` — Testing strategy, regression checks, and future test harness plans.
     - `docs/SECURITY.md` — Threat modeling, PBKDF2 hashing, brute-force lockout, and Egyptian PDPL compliance.
     - `docs/DESIGN-SYSTEM.md` — TechZone OS design language, color tokens, and invoice specifications.
     - `docs/DEPLOYMENT.md` — Packaging, distribution, Windows Edge WebView2 runtime, and backup guide.
     - `docs/README.md` — Complete bilingual documentation index.
  2. **Architectural Decision Records (`docs/adr/`)**: Established ADR framework (`0000-template.md`, `0001-offline-sqlite-architecture.md`, `0002-arabic-rtl-tailwind.md`).
  3. **AI Agent Guides & Standards**: Added `CLAUDE.md` session guide, `.editorconfig`, and archived older changelogs into `CHANGELOG_ARCHIVE.md` to keep `AGENTS.md` lean.
- 104/104 selfcheck tests passing (`app/selfcheck.py`).
