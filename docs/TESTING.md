# TechZone Testing Strategy

## Current: `selfcheck.py` (114 Assertions)

TechZone ships with a single integration-level test suite in `app/selfcheck.py`. It validates the database schema, API functions, business-logic constraints, and data integrity in one pass.

### Running the Tests

```bash
python app/selfcheck.py
```

A successful run prints each check with a ✓ and ends with:

```
ALL 114 CHECKS PASSED
```

Any failure raises `AssertionError` with a descriptive message identifying the broken invariant.

### What `selfcheck.py` Covers

| Area | Example checks |
|---|---|
| **DB schema** | All 19 tables exist; required columns present; foreign keys valid |
| **Settings** | Default seed values populated (store name, currency, VAT rate, login mode, invoice templates) |
| **Users & auth** | Admin account exists; PIN hashing and salt are non-empty; role values are `admin` or `cashier` |
| **Default PIN Security** | Admin login with default `1234` flags `force_change_pin=True`; `profile_save` with `pin` alias updates PIN and clears flag |
| **Permissions** | All 16 permission keys recognized; admin has full access; cashier permissions respect the stored JSON; cashier blocked from backup and restore |
| **Database Backups & Restore** | `db_backup` creates valid zero-lock snapshot; `backups_list` enumerates snapshots; `db_restore` performs safe rollback with pre-restore safety snapshot |
| **Hardware & POS** | `pos.html` global barcode keydown listener (<85ms burst) registered in DOM |
| **Products & inventory** | SKU uniqueness; price/cost stored as integer minor units; `tracked` flag controls serial enforcement |
| **Sales flow** | Sale creation decrements stock; payment totals match sale total; returns restore quantities |
| **Quotations** | Quote creation, item linkage, status transitions |
| **Customers & payments** | Customer creation; balance tracking; `customer_payments` linked correctly |
| **Repairs** | Ticket creation; part linkage; status values valid |
| **Used device purchases** | Purchase record creation and field validation |
| **Shifts** | Shift open/close; cash counting fields; association with user; automatic shift-close backup trigger |
| **PDF generation** | Invoice and receipt PDF functions return valid bytes (PDF 1.4 header check) |
| **API dispatcher** | `call(name, payload)` routes to correct functions; contract check ensures all frontend `api()` calls exist on `Api` |

### Running selfcheck After Every Change

Every code or schema change **must** pass all 114 checks before being committed. The `AGENTS.md` changelog records the selfcheck result for each entry.

---

## Manual QA

Since TechZone has no automated browser tests, manual QA is performed in two environments:

1. **pywebview window** — the production runtime. Launch with `python app/main.py` and test the full flow: login → desktop → POS → sales → print → WhatsApp share.
2. **Browser via HTTP mock bridge** — `app.js` detects when running under `http://` (e.g., via `python -m http.server` in the `web/` directory or the screenshot tool) and routes `api()` calls through a `/api/call` HTTP endpoint. This is useful for rapid UI iteration but does not test pywebview-specific behavior (native clipboard, window chrome, PDF generation).

---

## Recommended Future Improvements

### Unit Tests with pytest

- Add `tests/` directory with pytest-based unit tests for `app/api.py` functions.
- Each API function should have at least one happy-path and one error-path test.
- Use an in-memory SQLite database (`:memory:`) seeded by `app/db.py` for isolation.
- Target: cover all 69+ API functions.

### Browser / E2E Tests with Playwright

- Add Playwright tests that launch the pywebview app (or serve `web/` over HTTP with the mock bridge) and validate full user flows:
  - Login with PIN → desktop loads → open POS → add item → complete sale → verify receipt.
  - Permission enforcement: cashier cannot access settings.
  - Theme toggle: dark/light mode applies everywhere.
  - RTL layout: no clipped or misaligned elements.
- Playwright's Chromium engine closely matches WebView2, making results representative.

### Linting

| Tool | Scope | Purpose |
|---|---|---|
| **ruff** | `app/*.py` | Python linting and formatting (fast, replaces flake8 + black) |
| **ESLint** | `web/app.js`, inline scripts | JS linting for unused variables, potential XSS via `innerHTML`, and style consistency |

### CI Pipeline

Currently there is no CI. A future GitHub Actions workflow should:

1. Run `python app/selfcheck.py` on every push.
2. Run pytest unit tests.
3. Run ruff and ESLint checks.
4. Optionally build the `.exe` with PyInstaller and verify it launches.
