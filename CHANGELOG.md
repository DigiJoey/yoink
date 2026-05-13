# Changelog

All notable changes to Yoink are tracked here. The newest release is at the top.

## v1.1.0 — 2026-05-12

### Added
- **Tools panel.** New wrench icon in the header opens a Tools modal
  with five utilities that work on local files:
  - *Trim*: clip a range out of a local video using the same engine
    introduced for clip downloads in this release. Fastest (stream
    copy) and Frame-accurate (re-encode) modes available.
  - *Extract audio*: pull audio out of a video as MP3, WAV, FLAC, or
    AAC. Bitrate selectable for MP3.
  - *Speed change*: 0.5x to 2x speed presets plus custom factor. Audio
    pitch is preserved via ffmpeg's atempo filter.
  - *Merge*: concat multiple videos into one. Stream-copies when codecs
    match, re-encodes otherwise.
  - *Convert format*: container swap between MP4, MKV, WebM, MOV.
    Stream-copy by default with re-encode fallback when needed.
- **Settings reorg.** Tabs are grouped with section headers:
  *Configuration* (Organization, Format, Subtitles, SponsorBlock,
  Downloads, Authentication), *Records & diagnostics* (History, Logs),
  and *Meta* (Help, About). The old Compress tab is gone — Compress
  now lives in the Tools modal alongside the new utilities.
- **Diagnostics consolidation.** Open log file and Open data folder
  buttons moved from the About tab to the Logs tab toolbar. Easier to
  find when actually debugging something.

### Changed (clip downloads)
- Clip downloads use yt-dlp's normal parallel-fragment downloader by
  default and trim the file locally with ffmpeg afterward. v1.0.9
  flipped the re-encode flag but clip downloads were still slow because
  yt-dlp's clip-range mode uses a single HTTP connection and YouTube
  throttles single streams. Parallel fragment download saturates the
  line, then the local trim takes seconds (stream-copy) or about the
  clip's duration (re-encode). Progress bars also now move during clip
  downloads in the two "full download" modes, because the native
  downloader fires the same progress hooks as a normal download.
- The old `clipPrecision` (Fast/Precise) setting is replaced with
  `clipMode` (Fastest/Frame-accurate/Bandwidth-light) in the Downloads
  tab. Default is **Fastest**.
  - *Fastest*: full parallel download + ffmpeg `-c copy` trim.
    Keyframe-aligned cuts (within ~2 seconds of the requested time).
  - *Frame-accurate*: full parallel download + ffmpeg re-encode of the
    clip. Exact timestamps. Cut step runs at ~realtime of the clip.
  - *Bandwidth-light*: keeps the v1.0.9 behaviour (range-only download
    via FFmpegFD with stream-copy). Slow on fast lines because of
    YouTube's per-connection throttling; useful only for tiny clips
    out of huge videos on a slow connection.
- The backend emits `cut_progress`, `cut_done`, and `cut_error` events
  during the local trim step. The download card UI does not yet show
  these — the card flips to "done" when yt-dlp finishes and the trim
  happens in the background. For Fastest mode this is unnoticeable;
  for Frame-accurate on long clips it can briefly mislead. UX polish
  for that is deferred.

## v1.0.10 — 2026-05-12

### Fixed
- v1.0.9 broke downloads entirely when the user had Skip
  already-downloaded enabled. The "silent download failure" guard
  added in v1.0.8 fired on every legitimate archive skip: yt-dlp
  saw "has already been recorded in the archive", returned cleanly
  without firing a progress hook, and the guard then raised
  `Download finished without writing a file`. The guard was based
  on a misdiagnosis (the actual issue was the slow re-encode that
  v1.0.9 fixed properly) so it has been removed.

### Added
- **Logs tab** in Settings, between Help and About. Shows the
  contents of `yoink.log` live, with Refresh, Copy, and Clear log
  buttons. The Clear button truncates the file; the next log entry
  appears immediately.

## v1.0.9 — 2026-05-12

### Added
- **Clip cut precision** setting in Settings, Downloads tab. The old
  behaviour was equivalent to "Precise" and was the reason a 7-minute
  clip took 8 minutes to download: `force_keyframes_at_cuts=True` makes
  yt-dlp tell ffmpeg to re-encode the entire clip on CPU so cuts land
  on the exact requested timestamp. Re-encoding HD on CPU runs at
  about real-time, hence the long wait.
- New default is "Fast": ffmpeg uses `-c copy` with HTTP range requests,
  so only the clip's bytes are downloaded and no re-encoding happens.
  Cuts snap to the nearest keyframe (typically <2s off the requested
  time) but the download finishes at network speed. "Precise" is still
  selectable for users who need frame-accurate cuts.

## v1.0.8 — 2026-05-12

### Fixed
- Enable yt-dlp's `remote_components: ["ejs:github"]` so it can fetch
  the EJS challenge-solver script from yt-dlp's GitHub releases at
  runtime. v1.0.7 shipped deno (the JS runtime) but yt-dlp still
  warned `Remote components challenge solver script (deno) and NPM
  package (deno) were skipped. n challenge solving failed: Some
  formats may be missing.` Without the solver script, n-sig
  decryption fails on many YouTube formats and ffmpeg ends up
  downloading from broken URLs, which manifested as silent failures
  on clip-range downloads.

## v1.0.7 — 2026-05-12

### Fixed
- v1.0.6 was supposed to bundle deno.exe but the CI's `choco install deno`
  step either failed silently or installed it somewhere `find_deno()`
  did not check. Installed v1.0.6 still logged "deno not found on PATH"
  on first download. The workflow now uses the official
  `denoland/setup-deno@v2` action, which downloads the real standalone
  deno binary and puts it on PATH. `find_deno()` picks it up via
  `shutil.which("deno")` and bundles it next to Yoink.exe.

## v1.0.6 — 2026-05-11

### Added
- Discord-friendly compression targets: 10 MB (Discord free), 25 MB,
  50 MB (Nitro Basic), 500 MB (Nitro). Available both in the Compress
  tab dropdown and in the Downloads tab "Compress if larger than"
  setting.
- For very small targets, audio bitrate now scales down so more of the
  size budget can go to video: 64 kbps audio at <=10 MB, 96 kbps at
  <=25 MB, 128 kbps otherwise.
- Bundle **deno.exe** next to Yoink.exe. yt-dlp's YouTube extractor
  recently deprecated non-JS extraction; without a JS runtime, some
  formats become unavailable and the log fills with EJS warnings.
  `build.py` now searches winget (DenoLand.Deno) and PATH, validates
  the binary by running `--version`, and bundles it. Startup logs a
  deno verification line for parity with the ffmpeg check.

## v1.0.5 — 2026-05-11

### Fixed
- **The real cause of all the ffmpeg failures**: the `yt-dlp.FFmpeg`
  winget package ships its `bin/ffmpeg.exe` as a Chocolatey-style shim,
  not the actual ffmpeg binary. When `build.py` copied that file into
  the install folder it kept being a shim, which printed
  `Cannot find file at '..\lib\ffmpeg\tools\ffmpeg\bin\ffmpeg.exe'`
  and exited non-zero on every invocation. Yoink shipped a broken
  ffmpeg from day one of bundling.
- `build.py` now prefers `Gyan.FFmpeg` and `BtbN.FFmpeg` (real static
  builds) over `yt-dlp.FFmpeg`, also checks Chocolatey's real binary
  location and common manual install paths, and **validates each
  candidate by running `-version`** before accepting it. Shims get
  filtered out automatically.

## v1.0.4 — 2026-05-11

### Fixed
- Revert to passing the **file path** of ffmpeg.exe to yt-dlp via
  `ffmpeg_location`. v1.0.3 passed the directory, which yt-dlp on Windows
  combines with bare program names (e.g. `<dir>/ffmpeg` with no `.exe`),
  causing the version probe to fail and yt-dlp to declare "ffmpeg is not
  installed".
- At startup, actually execute `ffmpeg -version` and log the result so the
  next failure mode (AV blocking, broken binary, encoding issues) is
  immediately visible in `yoink.log`.

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
