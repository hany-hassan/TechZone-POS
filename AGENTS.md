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
| [`docs/OPEN-QUESTIONS.md`](docs/OPEN-QUESTIONS.md) | Pending architectural questions and design decisions | Arabic |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | System architecture, IPC bridge, sequence flows, and directory tree | English |
| [`docs/DATA-MODEL.md`](docs/DATA-MODEL.md) | 19 tables schema, minor-unit money rules, and 16-permission matrix | English |
| [`docs/STACK.md`](docs/STACK.md) | Pinned runtime stack, versions, and upgrade policies | English |
| [`docs/CODING-STANDARDS.md`](docs/CODING-STANDARDS.md) | Coding style, SQL guidelines, money formatting, and RTL conventions | English |
| [`docs/TESTING.md`](docs/TESTING.md) | Selfcheck automation (104 checks), test gates, and manual QA | English |
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
| Execute Automated Selfcheck (108 tests) | `python app/selfcheck.py` |
| Recompile Tailwind CSS | `npx tailwindcss -i web/tailwind.css -o web/app.css --minify` |
| Build Standalone EXE | Double-click `build-exe.bat` or run `.\build-exe.bat` |
| Push Updates to GitHub | Double-click `push-github.bat` or run `.\push-github.bat` |

---

## 5. System Architecture & Directory Tree

```
project001/
├── app/
│   ├── main.py          # Entry point: pywebview window setup & branding
│   ├── api.py           # Backend Api class (69+ methods dispatched via bridge)
│   ├── db.py            # SQLite schema (19 tables), connection wrapper, seed, migration
│   └── selfcheck.py     # Comprehensive automated regression suite (104 checks)
├── web/
│   ├── index.html       # Smart login screen (auto role/user detection by PIN)
│   ├── desktop.html     # TechZone OS hybrid desktop shell (dock, start menu, iframes)
│   ├── pos.html         # High-speed retail POS cashier
│   ├── sales_quotes.html# Official B2B A4 sales invoices & price quotations
│   ├── inventory.html   # Product catalog, stock tracking, and serial numbers
│   ├── customers.html   # Customer database, debt totals, and ledger shortcuts
│   ├── customer_details.html # Customer debt statements & payment vouchers
│   ├── repair.html      # Maintenance lifecycle ticketing & spare parts
│   ├── buy_used.html    # Used device purchasing, trade-ins, and anti-theft IDs
│   ├── history.html     # Operations history, returns, and multi-filter ledger
│   ├── reports.html     # Daily/monthly financials, shift logs, and net profits
│   ├── staff.html       # Employee administration & 16-permission matrix
│   ├── profile.html     # Employee personal profile, PIN, and desktop theme setup
│   ├── settings.html    # Store info, tax toggle, login mode, and invoice studio
│   ├── receipt.html     # Thermal 80mm & A4 preview and WhatsApp sharing
│   ├── app.js           # Bridge api() caller, permissions, and invoice builder
│   ├── app.css          # Pre-compiled Tailwind CSS bundle
│   └── fonts/           # 23 local WOFF2 font files
├── data/
│   ├── shop.db          # Operating SQLite database (git-ignored)
│   └── receipts/        # Generated PDF invoices and vouchers
├── docs/                # Comprehensive engineering and requirements documentation
├── tools/               # Data import and screenshot automation utilities
├── icon.ico             # Official application executable and window icon
├── TechZone.spec        # PyInstaller packaging configuration
├── build-exe.bat        # Automated single-click EXE builder
└── push-github.bat      # Automated single-click Git/GitHub synchronization
```

---

## 6. Permissions Matrix (16 Granular Keys)

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

---

## 7. Non-Negotiable Engineering Rules

1. **All Money in Minor Units:** Always store and compute currency as `INTEGER` minor units (`1 LE = 100 qirsh`). Never use floating-point types for financial transactions.
2. **100% Parameterized SQL:** Never concatenate or interpolate raw user strings into SQL queries. Always use `?` placeholders.
3. **Server-Side Authorization:** Never rely on frontend JavaScript checks for access control. Always enforce `_perm(key)` inside `app/api.py`.
4. **Offline Purity:** Never introduce external network calls, CDNs, or runtime cloud dependencies.
5. **No Bundlers / No Heavy Frameworks:** Vanilla JavaScript and pre-compiled CSS only.
6. **Selfcheck Verification:** Every change must maintain 114/114 passing tests in `python app/selfcheck.py`.
7. **Commit Documentation:** Always update `AGENTS.md` and document changes in the same commit.

---

## 8. Changelog

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
