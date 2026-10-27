# Changelog

## 2.9.6 — 2026-10-27

### Fixed
- Removed legacy Google Drive manifest step from release workflow.

## 2.9.5 — 2026-10-27

### Full changelog (2.9.2 → 2.9.5)

#### Added
- Add-to-Queue (MP3) and (MP4) buttons; queue no longer auto-starts on add.
- Select All / Deselect All in the queue page.
- DownloaderPageMixin extraction (handlers moved out of ui.py).
- README with run/test/build instructions.

#### Fixed
- MP4 queue items no longer skipped due to prior MP3 history.
- Queue add button overlap and double-add.
- Scrollbar hover reveal and transparent scroll-well canvas color.
- Crimson theme hover contrast.
- AEP target-year radio chips wrap so 2026 is visible.
- Queue toolbar split into two rows; bottom padding increased.
- Tooltips disabled by default for cleaner UI.
- Engine card spacing in Performance page.
- Inno Setup install step PowerShell syntax in release workflow.
- Simplified Inno Setup install step in release workflow.

#### Changed
- Queue toolbar simplified.
- Renamed repository to Tunelab.

## 2.9.4 — 2026-10-27

### Fixed
- Simplified Inno Setup install step in release workflow.

## 2.9.3 — 2026-10-27

### Fixed
- Inno Setup install step PowerShell syntax in release workflow.

## 2.9.2 — 2026-10-27

### Added
- Add-to-Queue (MP3) and (MP4) buttons; queue no longer auto-starts on add.
- Select All / Deselect All in the queue page.
- DownloaderPageMixin extraction (handlers moved out of ui.py).
- README with run/test/build instructions.

### Fixed
- MP4 queue items no longer skipped due to prior MP3 history.
- Queue add button overlap and double-add.
- Scrollbar hover reveal and transparent scroll-well canvas color.
- Crimson theme hover contrast.
- AEP target-year radio chips wrap so 2026 is visible.
- Queue toolbar split into two rows; bottom padding increased.
- Tooltips disabled by default for cleaner UI.
- Engine card spacing in Performance page.

### Changed
- Queue toolbar simplified.
- Renamed repository to Tunelab.

## 2.9.1 — 2026-10-23

### Fixed
- Reverted `downloader.py` and `ui.py` to the stable v2.8.0 state, undoing the 2.9.0 regressions:
  - `success_callback` now passes the actual produced file path (not the folder), so the UI opens the correct file after download
  - `open_in_file_manager` uses `os.startfile` on Windows before `explorer.exe`, fixing Explorer failing to open download folders
  - Removed the black square that appeared on the clear button
- Declared the missing `history_view` preference (`"list"`) in `_default_prefs()` so the history tab's list/gallery choice persists across restarts

### Changed
- `version.py` bumped from 2.9.0 to 2.9.1

### CI
- `release.yml`: cache pip dependencies, shallow clone, cache Inno Setup, skip redundant test re-run on tag pushes, combined artifact upload