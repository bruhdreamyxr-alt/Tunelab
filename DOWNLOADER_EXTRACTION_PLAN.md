# Downloader page extraction plan

## Goal
Move the Downloader page out of `ui.py` into `pages/downloader.py` as a
`DownloaderPageMixin`, matching the existing queue/history/updates mixins.

## Steps (each gated by tests + probe)

1. Create `pages/downloader.py` with a `DownloaderPageMixin` stub importing the
   same modules (`downloader`, `download_queue`, etc.).
2. Move self-contained handler groups first (download_mp3, download_mp4,
   cancel, preview, format/folder prefs, retry) into the mixin, leaving
   widget construction in `__init__`. Run full suite.
3. Move widget construction into `build_downloader_view()` and register it in
   `_LAZY_PAGES` (currently builds at startup because it is the landing page).
   Run full suite + `tools/probe_theme_follow.py`.
4. Remove now-unused imports/helpers from `ui.py`; verify `_themed_registry`
   and `_theme_roles` coverage for the new page.
5. Cleanup pass: dead legacy code, hardcoded fallback colors, `_theme_roles`
   gaps on other pages.

## Status
Deferred until after the in-progress big changes. Do not start mid-feature.
