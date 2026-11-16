# Deployment & Distribution Guide — TechZone POS

## 1. Target Environment & Prerequisites

TechZone POS is designed as an autonomous, self-contained desktop system requiring **no internet connectivity**, **no external database servers**, and **no runtime software dependencies** on client machines.

### Hardware & Operating System Specifications
- **Operating System:** Windows 10 (Build 1809 or later) or Windows 11 (64-bit).
- **Architecture:** x86_64 / amd64.
- **Display Resolution:** Optimized for standard 1360×860 desktop screens and touch POS monitors (min supported: 360×500 for compact windows).
- **Runtime Component:** Microsoft Edge WebView2 Evergreen Runtime (pre-installed natively on modern Windows 10/11 updates).
- **Memory & Storage:** Minimum 2 GB RAM, 250 MB free disk space for runtime and database growth.

---

## 2. Packaging Architecture (`PyInstaller`)

The production artifact is a single, portable executable generated via PyInstaller:

```
dist/
└── TechZone.exe     (~45 - 55 MB standalone executable)
```

### 2.1 PyInstaller Bundle Specification (`TechZone.spec`)
- **Mode:** `--onefile --windowed`
- **Icon:** Embedded `icon.ico`
- **Asset Bundling:**
  - `web/` → `sys._MEIPASS/web` (contains all HTML, compiled CSS, vanilla JS, and local WOFF2 font assets).
  - `icon.ico` → `sys._MEIPASS/icon.ico`
- **Runtime Path Resolution:**
  - When frozen (`getattr(sys, 'frozen', False)`): web assets are resolved from `sys._MEIPASS/web`.
  - Database (`data/shop.db`) and receipts (`data/receipts/`) are resolved relative to the executable's directory (`pathlib.Path(sys.executable).parent / 'data'`). This ensures user data survives executable updates without overwriting.

---

## 3. Build & Release Workflow

### 3.1 One-Click Build Script (`build-exe.bat`)
To compile a fresh production executable from the local development workspace:
1. Double-click `build-exe.bat` or execute in PowerShell:
   ```powershell
   .\build-exe.bat
   ```
2. The batch script performs:
   - Verification of Python 3.13 and PyInstaller availability.
   - Cleans previous temporary build directories (`build/TechZone`).
   - Packages all assets and writes the updated executable to `dist\TechZone.exe`.

### 3.2 Automated Git & GitHub Backup (`push-github.bat`)
To stage, commit, and push project updates safely to the remote GitHub repository:
```powershell
.\push-github.bat
```

---

## 4. Shop Installation & Deployment Steps

Installing TechZone on a new store terminal takes less than 2 minutes:

1. **Copy Files:** Copy `dist\TechZone.exe` to the shop's target folder (e.g. `C:\TechZone\`).
2. **Desktop Shortcut:** Right-click `TechZone.exe` → *Send to* → *Desktop (create shortcut)*.
3. **Launch:** Run the executable. On first launch:
   - TechZone automatically initializes the SQLite schema (`data\shop.db`) with Egyptian localized seed values.
   - Creates the receipt storage directory (`data\receipts\`).
   - Opens the smart login interface (`index.html`).
4. **Default Logins & Owner Setup (Change Immediately):**
   - **Admin:** PIN `1234` (first-run modal forces changing it to a secure PIN)
   - **Cashier:** PIN `1111`
   - **Owner Mode (Recommended for software deployers):** Long-press the store logo/name for 2 seconds on the login screen (or Start Menu header) to set up the independent Owner passphrase and store the one-time recovery key securely.
5. **Printer Configuration:** Connect the thermal printer (80mm USB / Network) and standard office printer (A4). Ensure the Windows Default Printer is assigned as desired.

---

## 5. Backup, Maintenance & Disaster Recovery

### 5.1 Built-In & Routine Database Backups
All store operations, customer ledgers, installment contracts, invoices, inventory, and settings reside in a single SQLite file:
```
data\shop.db
data\backups\    (automatic startup, shift-close, pre-restore & pre-fresh snapshots)
```
- **Automatic Rotation:** TechZone uses the ACID SQLite Online Backup API to save automatic snapshots on daily startup, cashier shift closure, and before structural/profile rebuilds (retaining the latest 30 snapshots automatically).
- **Safe In-App Restore:** Managers (`settings_manage`) can restore any snapshot from `settings.html?tab=backups` after `PRAGMA quick_check` validation and an automatic `before_restore` safety backup.
- **External Copy Routine:** Also copy `data\shop.db` / `data\backups\` to an external USB flash drive at the close of every business day.
- **Pre-Update Backup:** Before replacing `TechZone.exe` with a newer version, always take a snapshot via `settings.html` or copy `data\shop.db`.

### 5.2 Automatic Database Schema Migrations
TechZone includes non-destructive schema migrations in `app/db.py`:
- Newly introduced columns (`_ensure_schema_columns`) and structural migrations (`_migrate_customers`, `customer_ledger`, `installments`, `modules`, `business_profiles`) execute automatically on application launch.
- Existing sales, customers, and inventory data remain intact across software updates.
