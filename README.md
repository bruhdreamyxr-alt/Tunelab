# UniversalAudioStudio (TuneLab)

Windows desktop app for downloading audio/video, managing a queue/history, editing tags,
converting After Effects projects, and self-updating.

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
