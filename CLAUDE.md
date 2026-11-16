@AGENTS.md

# Claude Code — TechZone POS Session Guide

## Session start ritual

1. Read `AGENTS.md` — the single source of truth for the whole project.
2. Read the current phase in `docs/ROADMAP.md` — find the first phase with ⬜ or 🟡.
3. Read the "read before starting" docs listed for that phase.
4. Skim `docs/OPEN-QUESTIONS.md` for anything blocking the current phase.
5. Run `python app/selfcheck.py` to confirm baseline (expect 195/195 PASS + `contract ok`).

## How to talk to the owner

- **Language:** Egyptian Arabic (عامية مصرية). Use Arabic for explanations, keep code and commands in English.
- **Non-technical framing:** Hany works with AI agents, not a professional developer. Explain what you changed and why in plain Arabic.
- **Report real numbers:** After any change, run selfcheck and report the actual pass/fail count. Never claim tests passed without running them.

## Working style

- **Plan first:** For multi-file changes, write a short plan and get approval before editing.
- **Narrow checks first:** Before a large refactor, verify the specific area you are changing works.
- **Small vertical slices:** Complete one feature or fix end-to-end (backend + frontend + selfcheck) before moving to the next.
- **Never claim tests passed without running them.** Always `python app/selfcheck.py`.
- **Stop after two identical failures.** If the same error appears twice, report it to Hany and ask for guidance instead of looping.

## Visual work checks

- The app runs inside a pywebview window. To preview in a browser, run `python app/main.py` and connect via the HTTP bridge.
- All UI is Arabic RTL. Check that text alignment, icons, and layout look correct in both light and dark modes.

## Record decisions

- Any architectural or design decision → create an ADR in `docs/adr/NNNN-short-title.md`.
- Any assumption about unknown requirements → add to `docs/OPEN-QUESTIONS.md`.
- Any code change → update `AGENTS.md` changelog (newest first) in the same commit.

## Key commands

| Task | Command |
|---|---|
| Run the app | `python app/main.py` |
| Run all checks | `python app/selfcheck.py` |
| Rebuild Tailwind CSS | `npx tailwindcss -i web/tailwind.css -o web/app.css --minify` |
| Build .exe | `build-exe.bat` |
| Push to GitHub | `push-github.bat` |

## Non-negotiable rules

- Never add external runtime dependencies (no React, no Electron, no npm packages used at runtime).
- Never add network calls — the app is 100% offline.
- All fonts and icons must be local files in `web/fonts/`.
- Never put secrets, passwords, or customer data in code or commits.
- Never disable or skip selfcheck tests.
- Always update `AGENTS.md` in the same commit as any code change.
- Money values are INTEGER minor units (1 LE = 100 qirsh). Never use float for money.
- All SQL must be parameterized. No string interpolation in queries.
