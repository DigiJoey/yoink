# Yoink

A Windows desktop app for downloading videos from YouTube, Instagram, Facebook, X, and most other sites yt-dlp supports.

**[Download the latest release](https://github.com/DigiJoey/yoink/releases/latest)** · grab `YoinkSetup.exe`, double-click, install.

## Features

- Paste any YouTube, Instagram, Facebook, or X link. The app supports about a thousand sites in total via yt-dlp.
- Single videos, playlists, and channels. Channels prompt you for how many recent videos to fetch.
- MP4 with quality choice (720p, 1080p, 4K, Max) or MP3 with bitrate choice (128, 192, 320 kbps).
- Filename templates with tag chips (`{title}`, `{channel}`, `{n}`, `{playlist}`, `{quality}`, `{upload_date}`, etc.). Use `/` for subfolders.
- Clip range with separate hour, minute, second fields. Auto-fills from URLs that contain `?t=...`.
- Subtitles in any language, embedded into the video file.
- SponsorBlock segment preview on each thumbnail; mark or remove on download.
- Cookies from your browser (Chrome, Firefox, Edge, Brave) for age-gated, members-only, or private content.
- Bandwidth limiting and concurrent downloads (1, 2, or 3 in parallel).
- Drag-and-drop URLs onto the window. Reorder the queue by dragging cards. Right-click any card for copy URL, open in browser, remove, and more.
- Per-video cancel and retry buttons.
- Download history that survives reinstalls.
- Self-update from inside the app (yt-dlp from PyPI; Yoink from this repo's GitHub Releases).
- System tray with "hide window, keep downloading" mode.
- Dark UI with YouTube-style accents.

## Install

1. Go to the [latest release](https://github.com/DigiJoey/yoink/releases/latest).
2. Download `YoinkSetup.exe` from the Assets list.
3. Run it. The installer asks for an install location and offers Desktop shortcut and "launch at startup" options.
4. The first launch opens to a paste field. You are ready.

Yoink uses Windows' built-in WebView2 runtime. Modern Windows already has it. On older systems the installer may prompt you to install it once.

## How to use

1. Paste a video link in the **Source** field at the top.
2. Click **Scan** (or hit Ctrl+Enter). Thumbnails appear below.
3. Click any card to deselect it if you do not want it. Click again to reselect.
4. Pick **MP4** or **MP3** in Format. Pick a quality.
5. Confirm the **Destination** folder, or click **Browse** to pick one.
6. (Optional) Set a **Clip range** if you only want a portion of the video.
7. Click the red **Download** button (or hit Ctrl+D).

You can paste another URL while videos are already in the queue; new ones append. Right-click any card for more options (copy URL, open in browser, remove from queue). Drag cards to reorder them; if it is a playlist, the file numbers reflect the new order.

To run Yoink in the background while keeping downloads going, click the eye-off icon in the top-right. The window hides and a tray icon appears. Click the tray icon to bring the window back. Closing with the X cancels everything.

## Settings

The gear icon opens settings. Tabs:

- **Organization** — filename template with tag chips and a live preview.
- **Format** — default video quality, default MP3 bitrate, embed thumbnail and metadata into files.
- **Subtitles** — toggle on, list languages.
- **SponsorBlock** — off, mark only, or remove. Pick which categories count.
- **Downloads** — concurrent count, bandwidth cap, open destination when done, skip already-downloaded.
- **Authentication** — cookies from a browser, or a custom cookies.txt file path.
- **History** — past downloads with click-to-open. Clear list, or clear list and the archive.
- **Help** — full guide to every feature.
- **About** — versions, update buttons, settings export/import, log file, reset.

## Troubleshooting

- **A download fails with a "format not available" or similar error.** Update yt-dlp (Settings → About → "Check for updates" next to yt-dlp). YouTube changes regularly and yt-dlp updates fix it.
- **Stories, members-only, age-gated, or private videos fail.** Set Cookies from browser in Authentication, pick the browser you are logged into. No need to watch anything first, just be logged in to that account.
- **Windows SmartScreen warns when running the installer.** Click "More info" then "Run anyway". The installer is unsigned because code-signing certificates cost money for a free tool.
- **Logs and settings live in `%LOCALAPPDATA%\Yoink\`**. Open the data folder from About if you need to inspect them.

## License

[MIT](LICENSE).

---

# For developers

The rest of this file is for people building from source or contributing.

## Repo layout

```
.
├── README.md          # This file
├── CHANGELOG.md       # Per-release notes
├── LICENSE
├── main.py            # Entry point (pywebview window + system tray)
├── app.py             # FastAPI backend (yt-dlp + progress tracking)
├── paths.py           # Shared user-data filesystem paths
├── make_icon.py       # Generates app.ico
├── build.py           # Builds dist/Yoink/Yoink.exe with PyInstaller
├── installer.iss      # Inno Setup script for the installer
├── requirements.txt
├── launch.vbs         # Silent launcher for development (uses .venv)
├── setup.bat          # First-time dev setup
├── app.ico
├── static/            # HTML, CSS, JS for the UI
└── .github/workflows/release.yml  # Auto-build and publish on tag push
```

## Run from source

```powershell
.\setup.bat        # one-time: creates .venv and installs Python deps
.\launch.vbs       # silent launcher (no terminal window)
```

Setup needs Python 3.13. If you do not have it: `winget install Python.Python.3.13`.

## Build a standalone .exe

```powershell
.\.venv\Scripts\python.exe build.py
```

Produces `dist/Yoink/Yoink.exe`. Self-contained; copy the folder anywhere and run it without Python.

If `ffmpeg.exe` is on your PATH (or installed via `winget install yt-dlp.FFmpeg`), the build copies it next to `Yoink.exe` automatically so audio extraction and video merging work on machines without ffmpeg installed.

## Build the installer

```powershell
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" installer.iss
# or system-wide install:
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
```

Output lands in `Output/YoinkSetup.exe`. Free Inno Setup download: https://jrsoftware.org/isinfo.php

## Release flow (manual)

1. Bump `APP_VERSION` in `main.py`.
2. Add an entry to `CHANGELOG.md`.
3. Commit and push.
4. Build the .exe and the installer (steps above).
5. On GitHub, draft a new release. Tag `v1.0.x` (matching APP_VERSION), attach `Output/YoinkSetup.exe`, paste the changelog entry as the body, publish.

## Release flow (automated)

The repo has a GitHub Actions workflow at `.github/workflows/release.yml`. Push a tag matching `v*` and Actions will build the .exe, compile the installer, and publish a release with the asset attached, automatically.

```powershell
git tag v1.0.1
git push --tags
# wait ~6 minutes, then check the Releases page
```

## Update mechanics

- **yt-dlp** updates inside the frozen .exe by fetching the latest wheel from PyPI directly and extracting it into a writable override directory under `%LOCALAPPDATA%\Yoink\yt_dlp_override\`. At startup, that path is prepended to `sys.path` so the override is loaded before the bundled version.
- **Yoink itself** updates by hitting this repo's GitHub Releases API, finding the newest tag, downloading the `YoinkSetup.exe` asset, and running it. The installer's `CloseApplications=yes` and `RestartApplications=yes` handle the close-and-reopen dance.

## Notes

- WebView2 is a system component on modern Windows. Older Windows may need it installed: https://developer.microsoft.com/en-us/microsoft-edge/webview2/
- User data (settings, history, log, window position, yt-dlp override) lives in `%LOCALAPPDATA%\Yoink\`. Survives reinstalls.
- The `_internal/` folder next to `Yoink.exe` is PyInstaller's runtime stash. Do not delete it.
