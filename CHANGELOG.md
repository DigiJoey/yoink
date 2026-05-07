# Changelog

All notable changes to Yoink are tracked here. The newest release is at the top.

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
