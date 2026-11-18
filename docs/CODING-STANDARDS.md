# TechZone Coding Standards & Modular Plug-and-Play Rules

Rules and conventions for all code in the TechZone POS & ERP system.

---

## 1. Mandatory Modular Plug-and-Play Architecture (هندسة الأقسام المعزولة)

Every AI model and developer working on TechZone POS MUST adhere to the **Modular Plug-and-Play (Zero-Overhead Isolation)** architecture whenever creating, modifying, adding, or deleting any module:

1. **Self-Contained Domain Mixins & Pages:**
   - Each functional section (`pos`, `sales_quotes`, `inventory`, `customers`, `installments`, `purchases`, `accounting`, `history`, `repair`, `buy_used`, `reports`, `staff`) must encapsulate its backend endpoints in `app/api_<module>.py` and its UI in `web/<module>.html`.
2. **Server-Side Module Guard (`app/modules_map.py` & `app/api.py`):**
   - Every non-core public `Api` method must be mapped to its module key in `API_MODULE_MAP` (`app/modules_map.py`).
   - `Api.call()` checks `self._module_enabled(mod)` from the in-memory `self._modules_cache` (`O(1)`) before executing any method. If a module is disabled in `owner.html`, all its API methods are blocked server-side even for `admin`.
3. **Zero-Overhead Cross-Module Hooks (`app/erp_hooks.py`):**
   - Core operational modules (`pos`, `inventory`, `customers`, `repair`, `buy_used`, `installments`) must never hard-depend on optional ERP modules (`purchases`, `accounting`).
   - Any cross-module hook in `app/erp_hooks.py` MUST check `if not is_module_active(api, conn, "accounting"): return None` on its first line so disabled modules add **0 ms and 0 SQL queries** to POS checkout or other operations.
   - Cross-module analytics (such as `report_comprehensive` in `app/api_reports.py`) must check `erp_hooks.is_module_active(self, conn, "<module>")` before querying optional module tables.
4. **Separation of Invoice Revenue vs. Perpetual Inventory COGS Entries:**
   - When `accounting` is active, auto-posted journal entries for sales (`on_sale_created`), sales returns (`on_sale_returned`), standalone installments (`on_installment_created`), and delivered repairs (`on_repair_delivered`) MUST separate the **Financial Invoice/Revenue entry** (`source_table='sales'`, whose debit/credit total equals the exact invoice total) from the **Perpetual Inventory Cost (COGS) entry** (`source_table='sales_cogs'`). Never merge revenue and COGS into a single journal entry header, as that inflates the displayed journal entry total above the actual sale price.

---

## 2. Python (`app/*.py`)

### General

- All SQL queries use **parameterized placeholders** (`?`) — never string interpolation.
- Money values are stored as **INTEGER minor units** (1 LE = 100 qirsh). Display conversion happens in the JS frontend or formatted export helpers.
- HTML output from Python (PDF templates, dynamic snippets) must use escaping helpers to prevent injection.
- Imports: standard library first, then pywebview, then project modules.

### File & Function Naming

- Filenames: `lowercase_with_underscores.py` (e.g., `api_purchases.py`, `api_accounting.py`, `erp_hooks.py`, `selfcheck.py`).
- Functions: `snake_case` (e.g., `purchase_save`, `accounting_opening_apply`, `report_comprehensive`).
- The API dispatcher `call(name, payload)` maps JS calls to Python functions — every public API function must be classified in `app/modules_map.py`.

### Database

- Schema lives in `app/db.py` (52 tables) with non-destructive auto-migration logic (`_ensure_schema_columns`) that adds new tables/columns without data loss.
- Always use `INTEGER` for monetary amounts and `TEXT` for ISO-8601 timestamps.
- Default seed data is Egyptian-market specific (`ج.م` currency, 14% VAT rate, 1%/3% WHT withholding tax support, Arabic UI defaults, 38-account standard Arabic Chart of Accounts).

---

## 3. JavaScript (`web/app.js`, inline `<script>` blocks)

### General

- **Vanilla JS only** — no frameworks, no npm runtime dependencies, no TypeScript.
- DOM manipulation via `getElementById`, `querySelector`, and `innerHTML` templating using `esc()` on all dynamic strings.
- The bridge function `api(name, payload)` wraps `window.pywebview.api.call()` and transparently supports iframe sub-windows.

### Permission & Module Checks

- Every module page calls `await pageInit('<module_key>')` at startup to verify authentication, module activation, and user permissions.
- Use `hasPerm(key)` before showing or enabling UI elements that require a specific permission (63 granular permission keys across 12 groups in `app/permissions.py`).

### Theme & Accent

- `applyThemeEverywhere()` synchronizes dark/light mode across the desktop shell and all open sub-windows.
- `applyAccentColorEverywhere()` applies the user's chosen accent color globally.

---

## 4. CSS (`web/tailwind.css` → `web/app.css`)

- Source file: `web/tailwind.css` (Tailwind directives + `@font-face` declarations).
- Compiled output: `web/app.css` — **checked into git intentionally** so the app runs without Node.js at runtime.
- All 23 font files (Cairo, IBM Plex Sans Arabic, Material Icons) are local `.woff2` in `web/fonts/`.

---

## 5. RTL, Printing & Localization

- The entire UI is **Arabic, right-to-left** (`dir="rtl"`).
- Currency symbol: `ج.م` (or `LE` in English contexts).
- Every financial and accounting screen must support clean **A4 printing (`@media print`)** and, where applicable, export to **Excel (`.xlsx` / `.csv`)**, **PDF (`A4`)**, and **WhatsApp PDF sharing** (respecting the admin `whatsapp_send_enabled` setting).

---

## 6. Prohibited Patterns

1. **No violation of Modular Plug-and-Play isolation** — never hardwire cross-module calls without `erp_hooks.is_module_active` guards and `modules_map.py` registration.
2. **No external network calls** at runtime — not even for fonts, analytics, or error reporting.
3. **No new Python runtime dependencies** beyond stdlib + pywebview without explicit approval (even `.xlsx` and `.pdf` exports are built natively using Python's standard library).
4. **No npm packages** that ship to production.
5. **No raw SQL string concatenation** — always use parameterized queries.
6. **No `eval()`** in Python or JavaScript.
7. **No undocumented changes** — every addition, modification, or deletion must be recorded in `AGENTS.md`, `README.md`, and `docs/*.md`.
