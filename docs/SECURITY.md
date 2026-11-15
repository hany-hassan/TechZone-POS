# Security Policy and Controls — TechZone POS

## 1. Overview & Threat Model

TechZone POS is an **offline desktop system** designed for retail and repair electronics shops in Egypt. It operates within a single `pywebview` window powered by Microsoft Edge WebView2 on Windows 10/11.

Because the system is **100% offline** and binds to no public network interfaces, conventional web threats (remote brute force, DDoS, SSRF, cross-origin network sniffing) are not applicable in production. However, because it manages confidential retail, customer, financial, and repair data, strict physical, local, and privilege boundaries are required.

### Key Protected Assets
1. **Financial Records:** Cashier daily sales, net profits, price margins, drawer cash counting, customer ledger statements, debt settlements.
2. **Customer Personal Data:** Names, phone numbers, national identification numbers (mandatory for buying used electronic equipment).
3. **Inventory & Cost Secrets:** Supplier purchase costs, wholesale equipment cost bases, serial tracking.
4. **Administrative Credentials:** PIN hashes, manager role permissions, user role profiles.

### Primary Threat Vectors
- **Unauthorized Physical Access:** Unattended cashier station being used by unauthorized staff or customers.
- **Cashier Privilege Escalation:** Cashier attempting to view manager-level reports, cost prices, profit margins, or manipulate closed invoices.
- **PIN Brute-Force Guessing:** Rapid repeated PIN attempts on the login screen.
- **Malicious Local File Manipulation / Path Traversal:** Crafted invoice numbers or report paths attempting directory traversal.
- **Database File Theft:** Direct exfiltration of `data/shop.db` via USB thumb drives.

---

## 2. Implemented Security Controls

### 2.1 Authentication & Credential Storage
- **Cryptographic Hashing:** User PINs and passwords are protected using `hashlib.pbkdf2_hmac` with `SHA-256`, utilizing a unique 16-byte random salt per user and **200,000 iterations**.
- **No Plaintext Storage:** PINs are never persisted in plaintext, logs, or error responses.
- **Smart PIN-Only Login:** The system securely resolves identity and authorization level from the salted PIN hash without requiring pre-selection of role.

### 2.2 Brute-Force & Guessing Protections
- **Login Lockout Policy:** Configurable login lock mechanism (`login_max_attempts` default: 5, `login_lockout_minutes` default: 10 minutes).
- **Persistent Lockout State:** Failed attempt state and countdown timers are tracked in `settings` (`login_fail_state`) to prevent bypassing lockouts via application restarts.
- **Active Countdown & Input Freeze:** The UI disables inputs and shows remaining lockout seconds.
- **Mandatory Default PIN Protection:** On first run or whenever the administrative account uses default credentials (`1234`), a blocking modal (`#modal-force-pin`) prevents access to the system until a secure 4-8 digit PIN is configured and confirmed. Weak patterns (`1234`, `0000`, `1111`) are rejected.

### 2.3 Automated Backup & Disaster Recovery
- **ACID Zero-Lock Snapshots:** Automated SQLite Online Backup API (`src_conn.backup(dest_conn)`) guarantees consistent point-in-time snapshots without locking the database or interrupting POS sales.
- **Trigger Points:** Automatic backup on application startup (`daily_startup_backup`) and upon every cashier shift closure (`shift_close`).
- **Retention & Rotation:** Automatically maintains the latest 30 snapshots in `data/backups/`, pruning older files.
- **Safe In-App Database Restore (`db_restore`):** Managers can restore any snapshot directly from `settings.html`. Before overwriting, a safety snapshot (`shop_YYYYMMDD_HHMMSS_before_restore.db`) is generated, ensuring zero data loss even if an incorrect backup is selected. Integrity is verified with `PRAGMA quick_check` prior to restore.

### 2.4 Server-Side Authorization (`_perm`)
- **Backend-Enforced Authorization:** Authorization is verified strictly in Python (`app/api.py`) via `_perm(key)` and `_perm_any(*keys)`. Frontend checks in JavaScript (`hasPerm()`) are strictly for UI visibility and do not govern execution.
- **16 Granular Permissions:** Cashiers operate under least-privilege principles covering sales, price modification, discounts, returns, customer data, inventory, repairs, used devices, reports, and settings.
- **Database Backup & Restore Isolation:** Endpoints `db_backup`, `backups_list`, and `db_restore` require `settings_manage` authorization; cashiers are strictly blocked.
- **Immutable Historical Invoices:** Sales invoices (`sales`) cannot be deleted once committed. Adjustments must follow structured return procedures (`sale_returns`) with full audit traceability.

### 2.5 Injection and Input Defense
- **SQL Parameterization:** 100% of database queries in `app/api.py` and `app/db.py` use parameterized queries (`?`). String interpolation is strictly prohibited.
- **Safe Output Escaping:** Dynamic text inserted into invoice and receipt previews is sanitized via `esc()` to prevent injection.
- **Upload Validation & Magic Bytes:** Image uploads (logos, avatars, product pictures) are validated for Base64 integrity, size limits, and cryptographic magic bytes (rejecting HTML, SVG, and binary executables disguised as images).
- **Safe Filesystem Naming:** PDF invoice and report generation routines enforce strict character allowlisting (`safe_name`) to prevent directory traversal (`../`).

---

## 3. Regulatory & Privacy Considerations (Egyptian PDPL)

Under Egyptian Law No. 151 of 2020 (Personal Data Protection Law - PDPL):
- **Customer Phone & National ID:** Collected during used device trade-ins (`used_device_purchases`) and installment customer records. These are classified as personal data.
- **Data Minimization:** Only fields necessary for warranty service, invoice tracking, and anti-theft compliance are recorded.
- **Data Retention & Disposal:** Customer records should not be deleted arbitrarily if attached to active debt ledgers, but personal notes can be cleared upon customer request.

---

## 4. Security Action Plan (from Quality Audit)

The following items are scheduled for hardening in **Phase 2** of the project roadmap:

1. **Forced Default Credential Change:** Prompt mandatory PIN update on first run for default `admin` (1234) and `cashier` (1111) accounts.
2. **Read-Endpoint Authorization Audit:** Ensure all read queries (`sale`, `quotation`, `repair`, `customer`, `shift_summary`) check granular view permissions rather than basic session presence.
3. **Database at Rest Encryption:** Provide an optional transparent encryption wrapper (e.g., SQLCipher) or BitLocker storage guidance for `data/shop.db`.
4. **Session Idle Timeout:** Add an automatic desktop lock screen after configurable inactivity periods (e.g., 15 minutes of idle time).
