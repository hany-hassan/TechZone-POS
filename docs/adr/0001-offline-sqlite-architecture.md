# ADR 0001: Autonomous Offline Desktop Architecture using Python, pywebview, and SQLite

## Status
Accepted

## Date
2026-10-15

## Deciders
TechZone Engineering Team & Store Management

## Context
Retail electronics and repair businesses in Egypt require an ultra-responsive, fail-safe point of sale and service tracking system. Internet connectivity in commercial districts is occasionally erratic, electricity disruptions occur, and stores operate on modest Windows PC hardware without dedicated IT administrators or cloud infrastructure budgets. 

The software must guarantee zero operational downtime, zero monthly subscription costs, immediate startup, and simple single-file deployment.

## Decision
We chose a local desktop architecture composed of:
1. **Python 3.13** as the runtime language.
2. **Standard Library `sqlite3`** with strict single-file ACID transactions in `data/shop.db`.
3. **`pywebview` 6.2.1** utilizing the native Windows Edge WebView2 engine for HTML5/CSS3 rendering.
4. **PyInstaller** for bundling into a single, standalone `TechZone.exe` binary.

## Alternatives Considered
- **Electron (Node.js + Chromium):** Rejected due to excessive memory footprint (500MB+ baseline), larger executable sizes (>150MB), complex multi-process IPC, and slow boot times on entry-level shop hardware.
- **Client-Server Web App (FastAPI / Django + PostgreSQL):** Rejected because it requires hosting, network maintenance, service management, and exposes the shop to network failure vulnerabilities.
- **C# / .NET Desktop (WPF / WinForms):** Rejected because rapid UI customization and rich Arabic layout animations are significantly faster and cleaner in modern CSS/HTML than XAML, and AI agent workflows are more adept with web technologies.

## Consequences
- **Positive:**
  - 100% offline operational guarantee.
  - Zero ongoing hosting or database subscription fees.
  - Instant application launch with negligible RAM consumption (~60-120MB).
  - Single executable distribution with trivial backup (copying `shop.db`).
- **Negative / Trade-offs:**
  - Single-user concurrent access (one active cashier session per terminal).
  - No automatic multi-branch synchronization (deferred to future export/sync tools).
  - Backend and frontend communication is limited to the single `window.pywebview.api.call` bridge.
