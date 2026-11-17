# TechZone Testing Strategy

## Current: `selfcheck.py` (200 Assertions)

TechZone ships with a single integration-level test suite in `app/selfcheck.py`. It validates the database schema, API functions, permission boundaries, business logic, owner controls, and static frontend-to-backend contracts in one pass.

### Running the Tests

```bash
python app/selfcheck.py
```

A successful run prints each check with a ✓ and ends with:

```
ALL 200 CHECKS PASSED
```

Any failure raises `AssertionError` with a descriptive message identifying the broken invariant.

### What `selfcheck.py` Covers

| Area | Example checks |
|---|---|
| **DB schema** | All 28 tables exist; required columns & indices present; foreign keys valid |
| **Settings** | Default seed values populated (store name, currency, VAT rate, login mode, print/preview flags, invoice templates, `business_profile`); cashiers read runtime settings (`tax_enabled`, currency, print prefs) with security keys stripped |
| **Users & auth** | Admin account exists; PIN hashing and salt are non-empty; role values are `admin` or `cashier` |
| **Default PIN Security** | Admin login with default `1234` flags `force_change_pin=True`; `profile_save` with `pin` alias updates PIN and clears flag |
| **Owner Control & Structure** | Independent `owner_auth` passphrase setup, 5-attempt lockout, 10-min session expiry, recovery key rotation, admin PIN reset, audit logging, module registry CRUD/cloning, and `Api.call()` server-side disabled-module guard (`modules_map.py`) |
| **Business Profiles & Fresh DB** | Built-in & custom profile CRUD (`business_profiles`), editable `demo_catalog` switching, custom `ui_labels` overrides, `exclusive_demo` category visibility, and atomic `build_fresh_profile_db` selective carry-over / clean rebuild |
| **Permissions** | All 18 permission keys recognized (`installments_view`/`installments_manage` included); admin has full access; cashier permissions respect stored JSON; cashier blocked from backup and restore |
| **Database Backups & Restore** | `db_backup` creates valid zero-lock snapshot; `backups_list` enumerates snapshots; `db_restore` performs safe rollback with pre-restore safety snapshot |
| **Hardware & POS** | `pos.html` global barcode keydown listener (<85ms burst) registered in DOM |
| **Products & inventory** | SKU uniqueness; price/cost stored as integer minor units; `tracked` flag controls serial enforcement |
| **Sales flow** | Sale creation decrements stock; payment totals match sale total; returns restore quantities |
| **Quotations** | Quote creation, item linkage, status transitions |
| **Customers & installments** | Customer creation; unified `customer_ledger` debt tracking; `customer_payments` vouchers; installment plan scheduling, partial/full collection, cancellation, and alerts |
| **Repairs & used devices** | Ticket creation; part linkage; valid statuses; used device purchases |
| **Shifts** | Shift open/close; cash/wallet/installment counters; association with user; automatic shift-close backup trigger |
| **PDF generation** | Invoice and receipt PDF functions return valid bytes (PDF 1.4 header check) |
| **API dispatcher** | `call(name, payload)` routes to correct methods; contract check ensures all frontend `api()` calls (`109` names) exist on `Api` and all `Api` methods are classified in `modules_map.py` |

### Running selfcheck After Every Change

Every code or schema change **must** pass all 200 checks before being committed. The `AGENTS.md` changelog records the selfcheck result for each entry.

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
