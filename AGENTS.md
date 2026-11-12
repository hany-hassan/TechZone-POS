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
| Execute Automated Selfcheck (104 tests) | `python app/selfcheck.py` |
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
6. **Selfcheck Verification:** Every change must maintain 104/104 passing tests in `python app/selfcheck.py`.
7. **Commit Documentation:** Always update `AGENTS.md` and document changes in the same commit.

---

## 8. Changelog

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
