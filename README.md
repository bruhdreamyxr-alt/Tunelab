# TuneLab

TuneLab is a Windows desktop app for downloading audio and video from the web,
managing a download queue and history, editing media tags, remixing audio
(slowed + reverb), converting After Effects projects/presets across versions,
and keeping itself up to date.

## Features

- **Downloader**: paste a URL or search text; download audio (MP3) or video (MP4);
  inline status, progress in the taskbar, embedded preview, cancel.
- **Queue**: batch downloads with reorder/skip/retry, persisted across restarts.
- **History**: SQLite-backed, searchable, sortable, list/gallery views, re-download,
  prune missing files.
- **Studio**: slowed + reverb remix with speed/reverb sliders and export.
- **AEP Converter**: convert `.aep` projects and `.ffx` presets between
  After Effects 2022–2026.
- **Update Center**: app updates (GitHub releases), yt-dlp engine updates,
  skip/undo skip, release notes browser.
- **Appearance & Performance**: color themes (incl. custom palette), sidebar/motion
  prefs, aria2 tuning, fragment concurrency, cache clearing.

## Run from source

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python main.py
```

## Tests

```
.venv\Scripts\python -m pytest -q
```

## Build

See `UniversalAudioStudio.spec`, `installer_200.iss`, and `.github/workflows/release.yml`.

## Data location

Runtime data (history, queue, prefs, caches) lives in `%APPDATA%/AudioDownloader`.
