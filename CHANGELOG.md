# Changelog

All notable changes to Yoink are tracked here. The newest release is at the top.

## v1.0.3 — 2026-05-11

### Fixed
- yt-dlp was still reporting "ffmpeg is not installed" on format merges in
  v1.0.2. Now passes the **directory** containing ffmpeg.exe and
  ffprobe.exe to yt-dlp via `ffmpeg_location` instead of the file path,
  which some yt-dlp versions on Windows did not accept. Also widens the
  ffmpeg search to several candidate locations and logs each attempt at
  startup so failures are diagnosable from `yoink.log`.

## v1.0.2 — 2026-05-10

### Fixed
- Pass an explicit `ffmpeg_location` to yt-dlp instead of relying on PATH
  prepending. Clip-range downloads were aborting with "ffmpeg is not
  installed" even when `ffmpeg.exe` was bundled next to `Yoink.exe`,
  because yt-dlp's PATH lookup did not see our modification reliably.
- Bundle `ffprobe.exe` alongside `ffmpeg.exe` so the Compress feature
  can read video durations.

### Changed
- Failed cards now show a small "Read error" link that opens the full
  yt-dlp message in a modal, with a Copy button. Long tracebacks no
  longer overflow the card.

## v1.0.1 — 2026-05-07

### Added
- **Compress tab** in Settings. Pick local video files via a native file
  dialog, choose either a CRF-23 quality compression or a target size cap
  (50 / 100 / 250 / 500 / 1000 MB), and re-encode with the bundled ffmpeg.
  Output saves next to the input by default; an output folder can be picked.
- **Auto-compress on download.** Settings, Downloads tab, "Compress if larger
  than" option. After a video finishes downloading, if the file exceeds the
  cap, ffmpeg re-encodes it in place to fit.
- **Default destination setting.** Settings, Downloads tab. The Destination
  field on the homepage now reflects this default at every launch and is
  treated as a one-time override for the current session.

### Changed
- The default destination on first run now uses the actual location of the
  Windows Videos library via the shell API, instead of hardcoding
  `C:\Users\<name>\Videos`. Users with their library on a different drive
  get the correct path automatically.

### Fixed
- Download errors no longer get silently swallowed. yt-dlp's `ignoreerrors`
  was on, which hid format failures (including missing-ffmpeg merges)
  behind an empty status. Failed videos now report the actual reason.

## v1.0.0 — 2026-05-07

First public release.

### Features
- Download videos from YouTube, Instagram, Facebook, X, and most other sites yt-dlp supports.
- MP4 with quality choice (720p, 1080p, 4K, Max) or MP3 with bitrate choice (128, 192, 320 kbps).
- Filename template with tag chips (`{title}`, `{channel}`, `{n}`, `{playlist}`, `{quality}`, `{upload_date}`, `{download_date}`, `{id}`, `{ext}`). Slashes create subfolders.
- Clip range with separate hours, minutes, seconds inputs. Auto-fills from URL `?t=...`.
- Subtitles with language list, embedded into the file.
- SponsorBlock segment preview on each thumbnail; mark or remove on download.
- Cookies from browser, or a custom cookies.txt file.
- Concurrent downloads (1, 2, or 3 in parallel).
- Bandwidth limiting.
- Skip already-downloaded videos.
- Open destination folder when finished.
- Append-style queue: paste another link to add more, dedupe by id.
- Per-video cancel and retry buttons.
- Drag-and-drop URLs onto the window. Keyboard shortcuts (Ctrl+Enter to scan, Ctrl+D to download).
- System tray when minimised. Window position remembered.
- Download history with ability to clear list or list+archive.
- Yoink self-update via GitHub Releases. yt-dlp self-update via PyPI.
- Help and About tabs in settings.
