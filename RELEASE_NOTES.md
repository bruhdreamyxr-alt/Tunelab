# Release Notes - v2.9.4

## Added
- Add-to-Queue (MP3) and (MP4) buttons; queue no longer auto-starts on add.
- Select All / Deselect All in the queue page.
- DownloaderPageMixin extraction (handlers moved out of ui.py).
- README with run/test/build instructions.

## Fixed
- MP4 queue items no longer skipped due to prior MP3 history.
- Queue add button overlap and double-add.
- Scrollbar hover reveal and transparent scroll-well canvas color.
- Crimson theme hover contrast.
- AEP target-year radio chips wrap so 2026 is visible.
- Queue toolbar split into two rows; bottom padding increased.
- Tooltips disabled by default for cleaner UI.
- Engine card spacing in Performance page.
- Inno Setup install step PowerShell syntax in release workflow.

## Changed
- Queue toolbar simplified.
- Renamed repository to Tunelab.
- Simplified Inno Setup install step in release workflow.
