# ADR 0002: Arabic RTL Interface with Pre-compiled Tailwind CSS and Vanilla JavaScript

## Status
Accepted

## Date
2026-10-15

## Deciders
TechZone Engineering Team & Store Management

## Context
TechZone OS requires an Arabic-first Right-to-Left (RTL) desktop operating system interface featuring smooth window management, reactive shopping carts, dynamic invoice studio previews, and dark/light mode toggles. 

Heavy frontend frameworks (React, Vue, Angular) necessitate build pipelines, bundlers, node runtime dependencies, and complex hydration lifecycles that complicate a simple desktop WebView embedded environment.

## Decision
1. **Vanilla JavaScript (ES6+):** Use lightweight, browser-native JavaScript without external framework abstractions.
2. **Pre-compiled Tailwind CSS (`web/app.css`):** Develop using Tailwind CSS utility classes and commit the compiled `web/app.css` directly to Git.
3. **Local WOFF2 Fonts & Icons:** Store all 23 Arabic fonts (`Cairo`, `IBM Plex Sans Arabic`) and `Material Icons` locally in `web/fonts/`.

## Alternatives Considered
- **React / Next.js / Vite:** Rejected due to runtime bundling requirements, larger file sizes, added debugging layers across iframes, and explicit project constraints prohibiting bundlers and runtime frameworks.
- **Bootstrap 5:** Rejected because custom macOS/Windows 11 hybrid window styling and bespoke invoice studio controls are more cumbersome to customize compared to utility-first Tailwind CSS.
- **CDN-loaded fonts & icons (Google Fonts):** Rejected outright because the application must work 100% offline without external network dependencies.

## Consequences
- **Positive:**
  - Zero build step required during application startup or runtime.
  - Zero network requests; zero font flicker or FOIT/FOUT.
  - Transparent debugging directly inside the WebView2 DevTools inspector.
  - Full consistency between source development and production EXE packaging.
- **Negative / Trade-offs:**
  - New UI utility classes require running `npx tailwindcss` to rebuild `web/app.css` before committing.
  - State management across multiple iframes relies on postMessage / parent bridge coordination rather than reactive stores.
