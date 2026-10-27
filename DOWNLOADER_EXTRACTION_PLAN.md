# Downloader page extraction plan

## Goal
Move the Downloader page out of `ui.py` into `pages/downloader.py` as a
`DownloaderPageMixin`, matching the existing queue/history/updates mixins.

## Status
- Step 1: done (stub mixin created and wired).
- Step 2: done (handlers moved; construction remains in `__init__`).
- Step 3: deferred (construction tightly coupled; low benefit - landing page).
- Step 4: done (probe green; cleanup pass).

## Remaining
- Optional: move preview/studio handlers to a Studio mixin.
- Optional: revisit Step 3 if startup/layout consistency becomes a priority.
