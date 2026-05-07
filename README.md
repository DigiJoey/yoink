# Yoink

A Windows desktop app for downloading videos from YouTube, Instagram, Facebook, and X. Built on yt-dlp.

## Repo layout

```
.
├── README.md         # This file
├── main.py           # Entry point (pywebview window + system tray)
├── app.py            # FastAPI backend (yt-dlp + progress tracking)
├── paths.py          # Shared user-data paths
├── make_icon.py      # Generates app.ico
├── build.py          # Builds dist/Yoink/Yoink.exe with PyInstaller
├── installer.iss     # Inno Setup script for the installer
├── requirements.txt
├── launch.vbs        # Silent launcher for development (uses .venv)
├── setup.bat         # First-time dev setup
├── app.ico
└── static/           # HTML, CSS, JS for the UI
```

## Run from source (development)

```powershell
.\setup.bat        # one-time: creates .venv and installs Python deps
.\launch.vbs       # silent launcher (no terminal window)
```

Setup needs Python 3.13. If you do not have it: `winget install Python.Python.3.13`.

## Build a standalone .exe

```powershell
.\.venv\Scripts\python.exe build.py
```

This produces `dist/Yoink/Yoink.exe`. The folder is a self-contained app, you can copy it anywhere and run it without Python.

If `ffmpeg.exe` is on your `PATH` (or installed via `winget install yt-dlp.FFmpeg`), the build copies it next to `Yoink.exe` so audio extraction and video merging work on any machine.

## Build the installer

The installer wraps the dist folder into a single double-clickable `YoinkSetup.exe`.

1. Install Inno Setup (free): https://jrsoftware.org/isinfo.php
2. Build the .exe first: `python build.py` (see above)
3. Compile the installer. The path to `ISCC.exe` depends on whether you installed Inno Setup system-wide or per-user:

```powershell
# system-wide install
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
# OR per-user install (winget default)
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" installer.iss
```

The output lands in `Output/YoinkSetup.exe`.

That single `.exe` is what you can hand to anyone. They double-click, accept the wizard, and Yoink installs to Program Files with Start Menu and optional Desktop shortcuts. Uninstall is handled by the auto-generated uninstaller.

## Update flows

- **yt-dlp** (inside Yoink): Settings, Updates tab, Check for updates. The updater fetches the latest yt-dlp wheel from PyPI directly and extracts it into a writable override directory under `%LOCALAPPDATA%\Yoink\`. Restart Yoink after an update.
- **Yoink itself**: Settings, About tab, Check for Yoink updates. The updater hits this repo's GitHub Releases API, finds the newest tagged release, downloads its `YoinkSetup.exe` asset, and runs the installer. Yoink closes automatically and the installer reopens it after install.

## Cutting a release

1. Bump `APP_VERSION` in `main.py`.
2. Build the .exe and the installer (see sections above).
3. Tag a commit (e.g. `v1.0.1`) and push the tag: `git tag v1.0.1 && git push --tags`.
4. On GitHub, draft a new release using that tag, attach `Output/YoinkSetup.exe` as an asset.
5. Publish.

The auto-update checker looks for an asset named exactly `YoinkSetup.exe` (case-insensitive).

## Notes

- The `_internal/` folder next to `Yoink.exe` is PyInstaller's runtime stash. Do not delete it.
- `ffmpeg.exe`, when bundled, sits beside `Yoink.exe` and gets prepended to `PATH` automatically at startup.
- WebView2 (used for the window) is a system component on modern Windows. Older Windows may need the WebView2 runtime installed: https://developer.microsoft.com/en-us/microsoft-edge/webview2/
- User data (settings, history, log, window position, yt-dlp override) lives in `%LOCALAPPDATA%\Yoink\`. This survives reinstalls and is not part of the repo.
