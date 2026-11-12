# TechZone Stack

> Last verified: 2026-11-12

TechZone is a fully offline POS and shop-management system targeting Egyptian electronics retailers. Every dependency listed below ships with the app or is used only at build time — **zero network calls at runtime**.

## Runtime

| Component | Version | Role |
|---|---|---|
| **Python** | 3.13.5 | Application runtime; single entry point `app/main.py` |
| **sqlite3** | stdlib (bundled with Python 3.13) | Local database engine; all data lives in `data/shop.db` |
| **pywebview** | 6.2.1 | Desktop window host; renders the UI via Microsoft WebView2 on Windows |
| **ctypes / Win32 API** | stdlib | Native clipboard access (`CF_HDROP`) for copying generated PDF invoices and pasting directly into WhatsApp desktop |

## Frontend

| Component | Version | Role |
|---|---|---|
| **HTML / CSS / vanilla JS** | — | 15 standalone HTML pages; no frameworks, no bundler, no npm runtime dependencies |
| **Tailwind CSS** | 3.4.17 | Utility-first CSS framework — **dev-only**; compiled output `web/app.css` is checked into git |
| **Local fonts (woff2)** | — | 23 font files in `web/fonts/`: Cairo, IBM Plex Sans Arabic, Material Icons — no Google Fonts CDN calls |

## Build & Packaging

| Tool | Role |
|---|---|
| **PyInstaller** | Bundles everything into a single `TechZone.exe` (`--windowed --onefile`); build script: `build-exe.bat` |
| **npx tailwindcss** | Rebuilds `web/app.css` from `web/tailwind.css` when styles change (dev workstation only) |

## Explicitly Excluded

The following are **not** used anywhere in TechZone and must not be introduced:

- React, Vue, Angular, or any JS framework
- Electron, Tauri, or Rust-based shells
- .NET / WPF / WinForms
- Node.js runtime or npm runtime packages
- Any bundler (webpack, vite, esbuild)
- Any external network call or CDN at runtime
- Any Python runtime dependency beyond the standard library + pywebview

## Architecture at a Glance

```
┌──────────────────────────────────────────────┐
│  pywebview window  (WebView2, maximized)     │
│  ┌────────────────────────────────────────┐  │
│  │  15 HTML pages + app.js + app.css      │  │
│  │  (vanilla JS, Tailwind-compiled CSS)   │  │
│  └───────────┬────────────────────────────┘  │
│              │ window.pywebview.api.call()    │
│  ┌───────────▼────────────────────────────┐  │
│  │  app/api.py  (69+ API functions)       │  │
│  │  ├─ Permissions: _perm(key)            │  │
│  │  ├─ PDF generation (A4 + thermal)      │  │
│  │  └─ WhatsApp sharing (ctypes CF_HDROP) │  │
│  └───────────┬────────────────────────────┘  │
│              │ sqlite3                       │
│  ┌───────────▼────────────────────────────┐  │
│  │  data/shop.db  (19 tables)             │  │
│  └────────────────────────────────────────┘  │
└──────────────────────────────────────────────┘
```
