# TechZone Coding Standards

Rules and conventions for all code in the TechZone POS system.

---

## Python (`app/*.py`)

### General

- **No type hints currently** — but they are recommended for all new code going forward.
- All SQL queries use **parameterized placeholders** (`?`) — never string interpolation.
- Money values are stored as **INTEGER minor units** (1 LE = 100 qirsh). Display conversion happens in the JS frontend.
- HTML output from Python (PDF templates, dynamic snippets) must use the `esc()` helper to prevent injection.
- Imports: standard library first, then pywebview, then project modules.

### File & Function Naming

- Filenames: `lowercase_with_underscores.py` (e.g., `api.py`, `selfcheck.py`).
- Functions: `snake_case` (e.g., `products_search`, `sale_create`).
- The API dispatcher `call(name, payload)` maps JS calls to Python functions — every public API function is registered there.

### Database

- Schema lives in `app/db.py` with auto-migration logic that adds new columns without data loss.
- 19 tables; see `AGENTS.md § 4` for the full schema.
- Always use `INTEGER` for monetary amounts and `TEXT` for ISO-8601 timestamps.
- Default seed data is Egyptian-market specific (LE currency, 14% VAT rate, Arabic UI defaults).

---

## JavaScript (`web/app.js`, inline `<script>` blocks)

### General

- **Vanilla JS only** — no frameworks, no npm runtime dependencies, no TypeScript.
- DOM manipulation via `getElementById`, `querySelector`, and `innerHTML` templating.
- **Known XSS risk**: `innerHTML` is used for rendering dynamic content. User-supplied strings (customer names, product names, notes) should be escaped before insertion. A future audit should replace raw `innerHTML` with safe templating or `textContent` where possible.
- The bridge function `api(name, payload)` wraps `window.pywebview.api.call()` and transparently supports iframe sub-windows and HTTP mock fallback for browser-based development.

### Permission Checks

- Use `hasPerm(key)` before showing or enabling UI elements that require a specific permission.
- The 16 permission keys are documented in `AGENTS.md § 5`.

### Theme & Accent

- `applyThemeEverywhere()` synchronizes dark/light mode across the desktop shell and all open sub-windows.
- `applyAccentColorEverywhere()` applies the user's chosen accent color globally.
- Never hard-code colors that should respect the theme — use Tailwind's `dark:` variants.

---

## CSS (`web/tailwind.css` → `web/app.css`)

- Source file: `web/tailwind.css` (Tailwind directives + `@font-face` declarations).
- Compiled output: `web/app.css` — **checked into git intentionally** so the app runs without Node.js at runtime.
- Rebuild command (dev workstation only):
  ```bash
  npx tailwindcss -i web/tailwind.css -o web/app.css --minify
  ```
- All 23 font files (Cairo, IBM Plex Sans Arabic, Material Icons) are local `.woff2` in `web/fonts/`.

---

## RTL & Localization

- The entire UI is **Arabic, right-to-left**. Every HTML page sets `dir="rtl"` on `<html>` or `<body>`.
- Use CSS **logical properties** (`margin-inline-start`, `padding-inline-end`, `border-inline-start`) instead of physical `left`/`right` wherever possible.
- Currency symbol: `ج.م` (or `LE` in English contexts).
- Code identifiers, variable names, function names, git commit messages, and comments are in **English**.
- UI labels, tooltips, placeholder text, and user-facing strings are in **Arabic**.

---

## HTML Pages (`web/*.html`)

- Each of the 15 pages is **standalone**: it loads `app.css` and `app.js` via `<link>` and `<script>` tags.
- Pages communicate with the Python backend exclusively through `api(name, payload)`.
- No page makes any external network request — all assets (fonts, icons, images) are local.
- Print styles: `@page { margin: 0; }` is injected for invoice and receipt printing to eliminate browser default headers/footers and margins.

---

## File Naming Conventions

| Type | Convention | Examples |
|---|---|---|
| Python modules | `lowercase_underscores.py` | `api.py`, `selfcheck.py`, `db.py` |
| HTML pages | `lowercase_underscores.html` | `pos.html`, `sales_quotes.html`, `buy_used.html` |
| JS/CSS assets | `lowercase.ext` | `app.js`, `app.css`, `tailwind.css` |
| Build scripts | `kebab-case.bat` | `build-exe.bat`, `push-github.bat` |
| Data directories | `lowercase/` | `data/`, `web/fonts/`, `screenshots/` |

---

## Prohibited Patterns

1. **No external network calls** at runtime — not even for fonts, analytics, or error reporting.
2. **No new Python runtime dependencies** beyond stdlib + pywebview without explicit approval.
3. **No npm packages** that ship to production.
4. **No raw SQL string concatenation** — always use parameterized queries.
5. **No `eval()`** in Python or JavaScript.
6. **No hard-coded absolute paths** — use `os.path` relative to `sys._MEIPASS` (frozen) or project root (dev).
