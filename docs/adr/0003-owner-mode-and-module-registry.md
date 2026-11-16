# ADR-0003: Owner Mode, Recovery Key & Database-Driven Module Registry

## Status
Accepted

## Date
2026-11-16

## Deciders
Project Owner (Hany), Engineering Agent

## Context
TechZone POS previously hardcoded its 13 UI sections in `web/desktop.html` (`OS_APPS`) and `web/app.js` (`NAV`), and treated the shop `admin` role as the highest authority. To deploy the same codebase across multiple business types (electronics retail, general retail, restaurant, pharmacy) and prevent shop staff or shop managers from altering the program's structure or locking out access, we needed:
1. An authority level above `admin` (**Owner Mode**) protected by an independent passphrase with a simple offline recovery path.
2. Dynamic enable/disable, edit, clone-from-template, delete, and reorder controls over modules.
3. Server-side enforcement so disabled modules cannot be invoked even via direct console calls.

## Decision
1. **Owner Mode (`owner_auth`, `owner_audit_log`, `app/api_owner.py`)**:
   - Independent `_STATE["owner"]` session with a 10-minute sliding idle timeout, cleared on `logout()` and window close (`window.events.closed`).
   - Passphrase (≥ 8 chars) and a one-time 20-character recovery key (`XXXXX-XXXXX-XXXXX-XXXXX`) are stored as PBKDF2-HMAC-SHA256 (200,000 iterations) salted hashes.
   - Persistent 5-attempt / 15-minute lockout (`owner_auth.fail_state`).
   - Either secret can reset a forgotten shop `admin` PIN (`owner_reset_admin_pin`).
   - Every structural change takes one automatic `before_structure_change` backup per owner session and appends an entry to `owner_audit_log`.
2. **Database Module Registry & Server Guard (`modules`, `ui_labels`, `app/modules_map.py`, `app/profiles.py`)**:
   - `modules` table stores the 13 built-in sections (`settings`, `profile`, `receipt` marked `is_core=1`) plus custom template clones (`c_<slug>`).
   - `Api.call()` checks `API_MODULE_MAP` before dispatching any method, rejecting calls to disabled modules even for `admin`.
   - `selfcheck.py` asserts every public `Api` method is classified in either `API_MODULE_MAP` or `CORE_METHODS`.
   - `BUSINESS_PROFILES` in `app/profiles.py` provides dry-run diff preview and non-destructive switching between `retail_electronics`, `generic_shop`, `restaurant`, and `pharmacy`.

## Alternatives Considered
- **Full WYSIWYG page builder:** Rejected as over-scoped; template clones (`module_clone`) sharing existing tables cover section duplication with zero maintenance overhead.
- **Hardware-locked licensing / SQLCipher encryption:** Rejected per owner decision to keep protection simple and programmatic for offline local deployment (shipped as `TechZone.exe`).

## Consequences
- **Positive:** Shop structure is configurable at runtime without code edits; disabled modules are strictly blocked server-side; forgotten admin PINs and owner passphrases are recoverable offline; existing databases migrate additively.
- **Negative / Trade-offs:** Template clones share the same underlying database tables as their source module; restaurant/pharmacy profiles only hide/rename existing retail screens (domain-specific workflows like restaurant tables or pharmacy batch expiry remain future work). Offline local SQLite/source access by an OS administrator remains outside the software-only threat boundary.
