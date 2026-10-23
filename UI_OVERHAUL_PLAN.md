# UI Overhaul Plan — 2026 Modernization

## Goals
- Modern, 2026-grade visual language (glassmorphism-lite, soft shadows, generous spacing, refined typography) that works across **all existing themes** (presets + "My Theme" custom editor).
- Preserve the theme system: every colour still comes from the palette; no hardcoded hex in widgets.
- Preserve source-level test guards (`test_ui_wiring.py`) — no dropped bindings, no new messagebox show* calls.

## Phases

### Phase 1 — Design tokens (non-breaking)
- Add to `ui_theme.py`: spacing scale (`SPACE_1..6`), radius scale (`RADIUS_SM/MD/LG/XL`), elevation tokens, motion durations, type scale (`TYPE_DISPLAY/TITLE/BODY/CAPTION`).
- Keep existing `UITheme` constants as aliases for backward compat.
- Add `_shadow_color()` helper for soft drop shadows per palette luminance.

### Phase 2 — Component library
- Create `ui_components.py` with themed primitives: `Card`, `Button` (variants), `Input`, `SegmentedControl`, `Toast`, `Dialog`, `DataTable`, `EmptyState`, `Skeleton`.
- Each primitive reads from `self._palette` and registers for live re-theme.

### Phase 3 — Layout shell
- Redesign sidebar: collapsible rail, grouped nav, search/command palette (Ctrl+K), user/theme switcher.
- Top bar: breadcrumbs + global actions + status.
- Content area: responsive grid with max-width container.

### Phase 4 — Page redesigns (one at a time)
1. History (cards + virtualized list + filters)
2. Queue (live progress rows, bulk actions)
3. Updates (version timeline, release notes)
4. Downloader, AEP converter, Studio, Performance, Settings

### Phase 5 — Motion & polish
- Subtle enter/exit transitions, skeleton loaders, toast stack, keyboard shortcuts, focus rings, reduced-motion respect.

## Constraints
- No Tk widget creation in `ui_theme.py` (keep pure).
- All new widgets must re-theme via existing `_iter_widgets`/palette application path.
- Run `pyflakes` + compile + `test_ui_wiring.py` after each phase.

## First concrete step
Implement Phase 1 tokens in `ui_theme.py` (aliases only, no behaviour change), then Phase 2 Card/Button primitives in a new module.