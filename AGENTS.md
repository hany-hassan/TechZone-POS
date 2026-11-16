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
| [`docs/DATA-MODEL.md`](docs/DATA-MODEL.md) | 19 tables schema, minor-unit money rules, and 16-permission matrix | English |
| [`docs/STACK.md`](docs/STACK.md) | Pinned runtime stack, versions, and upgrade policies | English |
| [`docs/CODING-STANDARDS.md`](docs/CODING-STANDARDS.md) | Coding style, SQL guidelines, money formatting, and RTL conventions | English |
| [`docs/TESTING.md`](docs/TESTING.md) | Selfcheck automation (115 checks), test gates, and manual QA | English |
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
| Execute Automated Selfcheck (190 tests) | `python app/selfcheck.py` |
| Recompile Tailwind CSS | `npx tailwindcss -i web/tailwind.css -o web/app.css --minify` |
| Build Standalone EXE | Double-click `build-exe.bat` or run `.\build-exe.bat` |
| Push Updates to GitHub | Double-click `push-github.bat` or run `.\push-github.bat` |

---

## 5. System Architecture & Directory Tree

```
project001/
├── app/
│   ├── main.py          # Entry point: pywebview window setup, branding & session cleanup on close
│   ├── api.py           # Facade Api class composing 8 domain mixins (plus re-exports)
│   ├── api_common.py    # Shared state, money/format helpers, phone normalization, PDF/WhatsApp Win32 & ledger helpers
│   ├── api_auth.py      # AuthSettingsMixin: login, users, permissions, profile & settings/backups
│   ├── api_owner.py     # OwnerMixin: owner auth, module registry, profiles, labels & audit log
│   ├── modules_map.py   # API_MODULE_MAP, CORE_METHODS & MODULE_REQUIRES server guard map
│   ├── profiles.py      # BUSINESS_PROFILES presets & DEFAULT_LABELS/LABEL_KEYS allowlist
│   ├── api_inventory.py # InventoryMixin: categories, products, serials & stock adjustments
│   ├── api_customers.py # CustomersMixin: customer CRM, debt summary, ledger history & vouchers
│   ├── api_installments.py # InstallmentsMixin: installment contracts, schedules, collections, alerts & WhatsApp reminders
│   ├── api_sales.py     # SalesMixin: shifts, POS checkout, returns, modifications & WhatsApp invoice
│   ├── api_quotes.py    # QuotesMixin: B2B quotations, A4 invoices & conversion to sales
│   ├── api_services.py  # ServicesMixin: repair workshop lifecycle & used device purchases
│   ├── api_reports.py   # ReportsMixin: daily/monthly financials & top-selling reports
│   ├── db.py            # SQLite schema (27 tables), connection wrapper, seed, migration & backups
│   └── selfcheck.py     # Comprehensive automated regression suite (190 checks)
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
│   ├── staff.html       # Employee administration & 18-permission matrix
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
├── tools/               # Data import and screenshot automation utilities
├── icon.ico             # Official application executable and window icon
├── TechZone.spec        # PyInstaller packaging configuration
├── build-exe.bat        # Automated single-click EXE builder
└── push-github.bat      # Automated single-click Git/GitHub synchronization
```

---

## 6. Permissions Matrix (18 Granular Keys)

The administrator (`role='admin'`) possesses unrestricted system access. All other staff members (`role='cashier'`) have individual booleans stored in `users.permissions`:
1. `pos_sell`: Process POS transactions and checkout.
2. `pos_price`: Modify item sale prices on the fly in the cart.
3. `pos_item_discount`: Apply per-item discounts in the cart.
4. `sales_return`: Process returns on existing invoices.
5. `sales_all`: View all employee sales in the operations ledger.
6. `inventory_view`: Open and inspect inventory catalog.
7. `inventory_edit`: Create, edit, and delete products and categories.
8. `cost_view`: View wholesale purchase costs and profit margins.
9. `customers_view`: Access customer list and account summaries.
10. `customers_edit`: Add/edit customers and create payment vouchers.
11. `customers_delete`: Delete customer records and payment vouchers.
12. `repair_view`: Access maintenance workshop tickets.
13. `repair_edit`: Receive devices, update repair status, and deliver.
14. `used_manage`: Purchase and evaluate used customer devices.
15. `reports_view`: Access financial summaries, profits, and shift audits.
16. `settings_manage`: Edit store profile, tax rules, and employee accounts.
17. `installments_view`: View installment contracts, schedules, and reminders.
18. `installments_manage`: Create, collect payments on, and cancel installment contracts.

---

## 7. Non-Negotiable Engineering Rules

1. **All Money in Minor Units:** Always store and compute currency as `INTEGER` minor units (`1 LE = 100 qirsh`). Never use floating-point types for financial transactions.
2. **100% Parameterized SQL:** Never concatenate or interpolate raw user strings into SQL queries. Always use `?` placeholders.
3. **Server-Side Authorization:** Never rely on frontend JavaScript checks for access control. Always enforce `_perm(key)` inside `app/api.py`.
4. **Offline Purity:** Never introduce external network calls, CDNs, or runtime cloud dependencies.
5. **No Bundlers / No Heavy Frameworks:** Vanilla JavaScript and pre-compiled CSS only.
6. **Selfcheck Verification:** Every change must maintain all passing tests in `python app/selfcheck.py` (currently 190 checks).
7. **Commit Documentation:** Always update `AGENTS.md` and document changes in the same commit.

---

## 8. Changelog

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
