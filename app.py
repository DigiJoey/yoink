import asyncio
import json
import logging
import re
import shutil
import subprocess
import sys
import threading
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from queue import Empty, Queue
from typing import Any

import uvicorn
import yt_dlp
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from paths import ARCHIVE_FILE, HISTORY_FILE, LOG_FILE

logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("yoink")
ydl_log = logging.getLogger("yoink.ytdlp")


class _YDLLogger:
    """Forward yt-dlp's internal logging into our log file. yt-dlp expects
    debug/info/warning/error methods. Anything starting with [debug] should
    be filtered to debug level so the file does not get spammed."""

    def debug(self, msg):
        if msg.startswith("[debug] "):
            ydl_log.debug(msg)
        else:
            ydl_log.info(msg)

    def info(self, msg): ydl_log.info(msg)
    def warning(self, msg): ydl_log.warning(msg)
    def error(self, msg): ydl_log.error(msg)

# When frozen by PyInstaller, data files live in sys._MEIPASS.
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    BASE = Path(sys._MEIPASS)
else:
    BASE = Path(__file__).parent


def _locate_ffmpeg() -> str | None:
    """Return an absolute path to ffmpeg.exe. Order of preference:
    1. Sibling of the running executable (frozen, our installer bundles it there).
    2. Whatever is on PATH (winget install, manual install, etc).
    Caching the path lets us pass it explicitly to yt-dlp via `ffmpeg_location`,
    which is more reliable than letting yt-dlp guess from os.environ['PATH']."""
    if getattr(sys, "frozen", False):
        candidate = Path(sys.executable).parent / "ffmpeg.exe"
        if candidate.exists():
            return str(candidate)
    found = shutil.which("ffmpeg")
    if found:
        return found
    # Some Windows users only have ffmpeg via the winget yt-dlp package; try that
    if sys.platform == "win32":
        import os as _os
        winget = _os.environ.get("LOCALAPPDATA")
        if winget:
            for p in Path(winget, "Microsoft", "WinGet", "Packages").glob(
                "yt-dlp.FFmpeg*/**/ffmpeg.exe"
            ):
                return str(p)
    return None


FFMPEG_PATH: str | None = _locate_ffmpeg()

app = FastAPI()
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")


@app.middleware("http")
async def no_cache(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static/") or request.url.path == "/":
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
    return response

JOBS: dict[str, Queue] = {}
# video_id -> True when the user has requested a cancellation. The download
# hook checks this and raises to abort the active video, then the entry is
# cleared. Keyed by id alone since YouTube IDs are globally unique enough.
CANCELLATIONS: dict[str, bool] = {}


class _Cancelled(Exception):
    """Raised from the progress hook to abort a single video download."""


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


# -------- Info --------

class InfoRequest(BaseModel):
    url: str
    limit: int | None = None  # cap on entries returned, useful for channels


def _detect_platform(url: str | None) -> str:
    if not url:
        return "unknown"
    u = url.lower()
    if "youtube.com" in u or "youtu.be" in u:
        return "youtube"
    if "instagram.com" in u:
        return "instagram"
    if "facebook.com" in u or "fb.watch" in u:
        return "facebook"
    if "twitter.com" in u or "x.com" in u:
        return "twitter"
    return "unknown"


def _pick_thumbnail(entry: dict) -> str | None:
    thumb = entry.get("thumbnail")
    if thumb:
        return thumb
    thumbs = entry.get("thumbnails")
    if thumbs and isinstance(thumbs, list):
        scored = sorted(
            thumbs,
            key=lambda t: (
                t.get("preference") if isinstance(t.get("preference"), (int, float)) else 0,
                t.get("width") or 0,
            ),
        )
        if scored:
            return scored[-1].get("url")
    return None


@app.post("/api/info")
def info(req: InfoRequest):
    opts = {
        "quiet": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
        "no_warnings": True,
    }
    if req.limit and req.limit > 0:
        opts["playlistend"] = int(req.limit)
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            data = ydl.extract_info(req.url, download=False)
    except Exception as e:
        raise HTTPException(400, str(e))

    is_playlist = data.get("_type") == "playlist"
    entries = data.get("entries") or [data]
    src_platform = _detect_platform(req.url)
    videos = []
    for idx, e in enumerate(entries, start=1):
        if not e:
            continue
        vid_id = e.get("id")
        if not vid_id:
            continue

        page_url = e.get("webpage_url") or e.get("url")
        platform = _detect_platform(page_url) if page_url else src_platform
        if platform == "unknown":
            platform = src_platform

        thumb = _pick_thumbnail(e)
        if not thumb and platform == "youtube":
            thumb = f"https://i.ytimg.com/vi/{vid_id}/hqdefault.jpg"

        if not page_url and platform == "youtube":
            page_url = f"https://www.youtube.com/watch?v={vid_id}"
        if not page_url:
            page_url = req.url

        videos.append({
            "id": vid_id,
            "index": idx if is_playlist else None,
            "title": e.get("title") or "Unknown",
            "thumbnail": thumb,
            "duration": e.get("duration"),
            "url": page_url,
            "uploader": e.get("uploader") or e.get("channel"),
            "platform": platform,
            "is_live": bool(e.get("is_live") or e.get("live_status") in ("is_live", "is_upcoming")),
            "filesize_approx": e.get("filesize_approx") or e.get("filesize"),
        })
    return {
        "playlist_url": req.url if is_playlist else None,
        "playlist_title": data.get("title") if is_playlist else None,
        "is_channel": bool(
            data.get("_type") == "playlist" and (
                "channel" in (req.url or "").lower()
                or "/@" in (req.url or "")
                or "/c/" in (req.url or "")
                or "/user/" in (req.url or "")
            )
        ),
        "videos": videos,
    }


# -------- SponsorBlock segment lookup --------

class SBRequest(BaseModel):
    video_ids: list[str]


SB_CATEGORIES = [
    "sponsor", "selfpromo", "interaction",
    "intro", "outro", "preview", "music_offtopic", "filler",
]


def _fetch_sb(video_id: str) -> list[dict]:
    cats = json.dumps(SB_CATEGORIES)
    url = (
        "https://sponsor.ajay.app/api/skipSegments?"
        f"videoID={video_id}&categories={urllib.parse.quote(cats)}"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "yt-capture/1.0"})
        with urllib.request.urlopen(req, timeout=4) as r:
            data = json.loads(r.read())
        return [
            {
                "category": s.get("category"),
                "start": s["segment"][0],
                "end": s["segment"][1],
            }
            for s in data
            if "segment" in s
        ]
    except Exception:
        return []


class CompressRequest(BaseModel):
    files: list[str]
    target_size_mb: int | None = None  # None means use crf-based quality compression
    crf: int = 23
    output_dir: str = ""               # "" means save next to input


def _ffprobe_path() -> str:
    """ffprobe ships next to ffmpeg in standard builds. Return its absolute path
    when ffmpeg has been resolved, falling back to bare 'ffprobe' for PATH lookup."""
    if FFMPEG_PATH:
        sibling = Path(FFMPEG_PATH).with_name("ffprobe.exe" if sys.platform == "win32" else "ffprobe")
        if sibling.exists():
            return str(sibling)
    return "ffprobe"


def _ffmpeg_path() -> str:
    return FFMPEG_PATH or "ffmpeg"


def _ffprobe_duration(path: Path) -> float | None:
    """Return the video's duration in seconds via ffprobe, or None if it failed."""
    try:
        result = subprocess.run(
            [_ffprobe_path(), "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
            capture_output=True, text=True, timeout=20,
            creationflags=0x08000000 if sys.platform == "win32" else 0,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return float(data.get("format", {}).get("duration") or 0) or None
    except Exception:
        log.exception("ffprobe failed for %s", path)
    return None


def _compress_video(
    in_path: Path,
    out_path: Path,
    target_size_mb: int | None,
    crf: int,
    progress_cb,
) -> bool:
    """Re-encode a video with ffmpeg. Reports progress 0..1 via progress_cb.

    Returns True on success. The caller is responsible for replacing or moving
    the resulting file as desired."""
    if not in_path.exists():
        return False
    out_path.parent.mkdir(parents=True, exist_ok=True)

    duration = _ffprobe_duration(in_path)

    cmd = [_ffmpeg_path(), "-y", "-i", str(in_path),
           "-c:v", "libx264", "-preset", "medium"]
    if target_size_mb and duration and duration > 0:
        # Reserve ~128 kbps for audio, give the rest to video.
        audio_kbps = 128
        target_kbits = target_size_mb * 8192
        video_kbps = max(int(target_kbits / duration) - audio_kbps, 100)
        cmd += ["-b:v", f"{video_kbps}k", "-maxrate", f"{int(video_kbps * 1.5)}k",
                "-bufsize", f"{video_kbps * 2}k",
                "-c:a", "aac", "-b:a", f"{audio_kbps}k"]
    else:
        cmd += ["-crf", str(crf), "-c:a", "aac", "-b:a", "128k"]
    cmd += ["-movflags", "+faststart", "-progress", "pipe:1", "-nostats", str(out_path)]

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
        creationflags=0x08000000 if sys.platform == "win32" else 0,
    )
    last = 0.0
    try:
        for line in proc.stdout:
            line = line.strip()
            if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
                try:
                    val = int(line.split("=", 1)[1])
                    seconds = val / 1_000_000 if line.startswith("out_time_us=") else val / 1_000
                    if duration:
                        p = max(0.0, min(1.0, seconds / duration))
                        if p - last >= 0.01 or p >= 0.999:
                            last = p
                            try:
                                progress_cb(p)
                            except Exception:
                                pass
                except Exception:
                    pass
    finally:
        proc.wait()
    return proc.returncode == 0


@app.post("/api/compress")
def compress_videos(req: CompressRequest):
    job_id = uuid.uuid4().hex
    q: Queue = Queue()
    JOBS[job_id] = q

    def run():
        try:
            for raw in req.files:
                inp = Path(raw)
                if not inp.exists():
                    q.put({"status": "compress_error", "file": raw, "error": "File not found"})
                    continue

                out_dir = Path(req.output_dir) if req.output_dir else inp.parent
                out_path = out_dir / f"{inp.stem} (compressed).mp4"
                # Avoid clobbering: if the target exists, append a counter.
                if out_path.exists():
                    i = 2
                    while True:
                        candidate = out_dir / f"{inp.stem} (compressed {i}).mp4"
                        if not candidate.exists():
                            out_path = candidate
                            break
                        i += 1

                def cb(p, _file=raw):
                    q.put({"status": "compress_progress", "file": _file, "progress": p})

                ok = _compress_video(inp, out_path, req.target_size_mb, req.crf, cb)
                if ok and out_path.exists():
                    q.put({"status": "compress_done", "file": raw,
                           "output": str(out_path), "size": out_path.stat().st_size})
                else:
                    q.put({"status": "compress_error", "file": raw,
                           "error": "ffmpeg failed (see log file)"})
            q.put({"status": "all_done"})
        except Exception as e:
            log.exception("Compress job failed")
            q.put({"status": "error", "error": str(e)})
        finally:
            q.put(None)

    threading.Thread(target=run, daemon=True).start()
    return {"job_id": job_id}


def _load_history() -> list[dict]:
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            log.exception("Failed to read history file")
    return []


def _save_history(entries: list[dict]):
    try:
        HISTORY_FILE.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    except Exception:
        log.exception("Failed to write history file")


def _append_history(entry: dict):
    entries = _load_history()
    entries.insert(0, entry)
    if len(entries) > 1000:  # keep history bounded
        entries = entries[:1000]
    _save_history(entries)


@app.get("/api/history")
def history():
    return {"entries": _load_history()}


class ClearHistoryRequest(BaseModel):
    clear_archive: bool = False


@app.post("/api/history/clear")
def clear_history(req: ClearHistoryRequest):
    _save_history([])
    if req.clear_archive and ARCHIVE_FILE.exists():
        try:
            ARCHIVE_FILE.unlink()
        except Exception:
            log.exception("Failed to clear archive file")
    return {"ok": True}


@app.post("/api/sponsorblock")
def sponsorblock(req: SBRequest):
    out: dict[str, list] = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        for vid, segs in zip(req.video_ids, pool.map(_fetch_sb, req.video_ids)):
            out[vid] = segs
    return {"segments": out}


# -------- Download --------

class DownloadOptions(BaseModel):
    embedMetadata: bool = True
    mp3Bitrate: str = "192"
    filenameTemplate: str = "{n} - {title}"
    subtitles: bool = False
    subtitleLangs: str = "en"
    sbMode: str = "off"           # off | mark | remove
    sbCategories: list[str] = ["sponsor", "selfpromo"]
    concurrent: int = 1
    openWhenDone: bool = False
    cookies: str = "off"          # off | chrome | firefox | edge | brave
    cookieFile: str = ""          # path to custom cookies.txt (overrides browser cookies if set)
    rateLimit: str = "off"        # off | 500K | 1M | 2M | 5M | 10M
    skipDownloaded: bool = True   # use the archive file to skip already-downloaded videos
    maxFileSizeMB: int = 0        # 0 = off; otherwise compress after download if file exceeds this


class DownloadRequest(BaseModel):
    urls: list[str]
    video_ids: list[str] = []  # parallel to urls; lets us emit per-video errors
    format: str
    resolution: str
    quality: str = ""
    destination: str
    is_playlist: bool = False
    clip_start: float | None = None
    clip_end: float | None = None
    options: DownloadOptions = DownloadOptions()


class CancelRequest(BaseModel):
    video_id: str


@app.post("/api/cancel")
def cancel_video(req: CancelRequest):
    CANCELLATIONS[req.video_id] = True
    return {"ok": True}


def convert_template(
    user_template: str,
    is_playlist: bool,
    quality: str,
    index_override: int | None = None,
) -> str:
    """Convert user template (with {tag} placeholders) to a yt-dlp output template.

    When index_override is given, {n} and {playlist_index} substitute that
    explicit number (zero-padded) instead of yt-dlp's playlist_index. This is
    how queue reordering renumbers files: each video downloads with its own
    template, baking in its current queue position.
    """
    t = user_template or "{n}{title}"
    today = datetime.now().strftime("%Y-%m-%d")

    # Conditional tags depend on context
    if index_override is not None:
        n_str = f"{index_override:02d}"
        t = t.replace("{n}", n_str)
        t = t.replace("{playlist_index}", n_str)
        if is_playlist:
            t = t.replace("{playlist}", "%(playlist_title)s")
        else:
            t = t.replace("{playlist}", "")
    elif is_playlist:
        t = t.replace("{n}", "%(playlist_index)02d")
        t = t.replace("{playlist_index}", "%(playlist_index)02d")
        t = t.replace("{playlist}", "%(playlist_title)s")
    else:
        t = t.replace("{n}", "")
        t = t.replace("{playlist_index}", "")
        t = t.replace("{playlist}", "")

    # Direct field substitutions
    t = t.replace("{title}", "%(title)s")
    t = t.replace("{channel}", "%(uploader)s")
    t = t.replace("{id}", "%(id)s")
    t = t.replace("{upload_date}", "%(upload_date>%Y-%m-%d)s")
    t = t.replace("{download_date}", today)
    t = t.replace("{quality}", quality or "")
    t = t.replace("{ext}", "%(ext)s")

    # Auto-append extension
    if "%(ext)s" not in t:
        t = t + ".%(ext)s"

    # Clean up segments (folders) that became empty or only have separators
    parts = t.split("/")
    cleaned = []
    for p in parts:
        p = p.strip()
        # Trim leading/trailing separators left over from removed tags
        p = re.sub(r'^[\s\-]+', '', p)
        p = re.sub(r'[\s\-]+$', '', p)
        if p:
            cleaned.append(p)
    t = "/".join(cleaned) if cleaned else "%(title)s.%(ext)s"
    return t


def build_opts(
    req: DownloadRequest,
    hook,
    index_override: int | None = None,
) -> dict[str, Any]:
    o = req.options
    dest = Path(req.destination)
    dest.mkdir(parents=True, exist_ok=True)

    template = convert_template(
        o.filenameTemplate, req.is_playlist, req.quality, index_override
    )
    outtmpl = str(dest / template)

    opts: dict[str, Any] = {
        "outtmpl": outtmpl,
        "progress_hooks": [hook],
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "concurrent_fragment_downloads": 4,
        # Do NOT swallow errors. Each video downloads in its own _do_one call,
        # so a raised DownloadError gets caught and surfaced as a card error
        # instead of disappearing into the void.
        "ignoreerrors": False,
        # Funnel yt-dlp's own log output into our log file. Without this,
        # warnings about missing ffmpeg or unavailable formats are silenced
        # by quiet=True and the user has no way to tell what failed.
        "logger": _YDLLogger(),
    }

    # Authentication: custom cookie file overrides browser cookies if set
    if o.cookieFile and Path(o.cookieFile).exists():
        opts["cookiefile"] = o.cookieFile
    elif o.cookies != "off":
        opts["cookiesfrombrowser"] = (o.cookies,)

    # Explicitly tell yt-dlp where ffmpeg lives so it does not depend on PATH.
    # Without this, clip ranges and format merging fail with
    # "ffmpeg is not installed" even when ffmpeg.exe is sitting next to Yoink.
    if FFMPEG_PATH:
        opts["ffmpeg_location"] = FFMPEG_PATH

    # Rate limiting (bytes per second)
    if o.rateLimit and o.rateLimit != "off":
        try:
            n = o.rateLimit.upper().rstrip("BPS").rstrip("/S").strip()
            mult = 1
            if n.endswith("K"):
                mult, n = 1024, n[:-1]
            elif n.endswith("M"):
                mult, n = 1024 * 1024, n[:-1]
            elif n.endswith("G"):
                mult, n = 1024 * 1024 * 1024, n[:-1]
            opts["ratelimit"] = int(float(n) * mult)
        except (ValueError, AttributeError):
            pass

    # Skip already-downloaded videos
    if o.skipDownloaded:
        opts["download_archive"] = str(ARCHIVE_FILE)

    postprocessors: list[dict] = []

    if req.format == "mp3":
        opts["format"] = "bestaudio/best"
        postprocessors.append({
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": o.mp3Bitrate,
        })
    else:
        height = {"720": 720, "1080": 1080, "4k": 2160}.get(req.resolution)
        if height:
            opts["format"] = f"bv*[height<={height}]+ba/b[height<={height}]"
        else:
            opts["format"] = "bv*+ba/b"
        opts["merge_output_format"] = "mp4"

    # SponsorBlock
    if o.sbMode in ("mark", "remove") and o.sbCategories:
        postprocessors.append({"key": "SponsorBlock", "categories": o.sbCategories})
        if o.sbMode == "mark":
            postprocessors.append({
                "key": "ModifyChapters",
                "sponsorblock_chapter_title": "[SponsorBlock]: %(category_names)l",
            })
        else:
            postprocessors.append({
                "key": "ModifyChapters",
                "remove_sponsor_segments": o.sbCategories,
            })

    # Subtitles
    if o.subtitles:
        opts["writesubtitles"] = True
        opts["writeautomaticsub"] = True
        langs = [s.strip() for s in o.subtitleLangs.split(",") if s.strip()]
        if langs:
            opts["subtitleslangs"] = langs
        if req.format != "mp3":
            postprocessors.append({"key": "FFmpegEmbedSubtitle"})

    # Metadata + thumbnail embedding
    if o.embedMetadata:
        opts["writethumbnail"] = True
        postprocessors.append({"key": "FFmpegMetadata", "add_metadata": True})
        postprocessors.append({"key": "EmbedThumbnail"})

    if postprocessors:
        opts["postprocessors"] = postprocessors

    # Clip range
    if req.clip_start is not None or req.clip_end is not None:
        start = req.clip_start
        end = req.clip_end

        def ranges_func(info_dict, ydl):
            return [{
                "start_time": start if start is not None else 0,
                "end_time": end if end is not None else (info_dict.get("duration") or 0),
            }]

        opts["download_ranges"] = ranges_func
        opts["force_keyframes_at_cuts"] = True

    return opts


@app.post("/api/download")
def download(req: DownloadRequest):
    job_id = uuid.uuid4().hex
    q: Queue = Queue()
    JOBS[job_id] = q

    finished_files: dict[str, str] = {}

    def hook(d):
        info_dict = d.get("info_dict") or {}
        vid = info_dict.get("id")
        # Abort the in-flight download if the user clicked cancel on this card.
        if vid and CANCELLATIONS.get(vid):
            raise _Cancelled(f"Cancelled video {vid}")
        status = d.get("status")
        q.put({
            "status": status,
            "downloaded_bytes": d.get("downloaded_bytes"),
            "total_bytes": d.get("total_bytes") or d.get("total_bytes_estimate"),
            "speed": d.get("speed"),
            "eta": d.get("eta"),
            "video_id": vid,
            "video_title": info_dict.get("title"),
            "filename": d.get("filename") if status == "finished" else None,
        })
        if status == "finished" and vid:
            fname = d.get("filename") or d.get("info_dict", {}).get("_filename")
            if fname:
                finished_files[vid] = fname
            _append_history({
                "id": vid,
                "title": info_dict.get("title") or "Unknown",
                "uploader": info_dict.get("uploader") or info_dict.get("channel"),
                "url": info_dict.get("webpage_url") or info_dict.get("original_url"),
                "filepath": fname,
                "format": req.format,
                "quality": req.quality,
                "completed_at": datetime.now().isoformat(timespec="seconds"),
            })

    def _maybe_compress(vid: str | None):
        """If the user set a max-size cap and the resulting file exceeds it,
        re-encode it in place to fit. MP4 video output only."""
        cap = int(req.options.maxFileSizeMB or 0)
        if cap <= 0 or not vid:
            return
        fname = finished_files.get(vid)
        if not fname:
            return
        path = Path(fname)
        if not path.exists():
            return
        size_mb = path.stat().st_size / (1024 * 1024)
        if size_mb <= cap:
            return
        # Skip compression for non-MP4 outputs; we only re-encode video.
        if path.suffix.lower() not in (".mp4", ".mkv", ".webm", ".mov"):
            return
        tmp_out = path.with_name(path.stem + ".compress.tmp.mp4")
        log.info("Compressing %s (%.1f MB > %d MB cap)", path.name, size_mb, cap)
        ok = _compress_video(path, tmp_out, cap, 23, lambda p: q.put({
            "status": "compress_progress", "video_id": vid, "progress": p,
        }))
        if ok and tmp_out.exists():
            try:
                path.unlink()
                tmp_out.rename(path)
                q.put({"status": "compress_done", "video_id": vid,
                       "size": path.stat().st_size, "output": str(path)})
            except Exception as e:
                log.exception("Replace after compress failed")
                q.put({"status": "compress_error", "video_id": vid, "error": str(e)})
        else:
            try:
                tmp_out.unlink(missing_ok=True)
            except Exception:
                pass
            q.put({"status": "compress_error", "video_id": vid,
                   "error": "ffmpeg failed (see log)"})

    concurrent = max(1, min(int(req.options.concurrent or 1), 4))

    def _do_one(url: str, vid: str | None, position: int | None):
        # Skip immediately if cancellation arrived before download started
        if vid and CANCELLATIONS.get(vid):
            q.put({"status": "video_error", "video_id": vid, "error": "cancelled"})
            CANCELLATIONS.pop(vid, None)
            return
        try:
            # Per-call opts lets us bake in this video's queue position so the
            # filename template's {n} reflects the user's possibly-reordered queue.
            opts = build_opts(req, hook, index_override=position)
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
            _maybe_compress(vid)
        except _Cancelled:
            q.put({"status": "video_error", "video_id": vid, "error": "cancelled"})
        except Exception as e:
            log.exception("Download failed for %s", url)
            q.put({"status": "video_error", "video_id": vid, "error": str(e)})
        finally:
            if vid:
                CANCELLATIONS.pop(vid, None)

    def run():
        try:
            ids = req.video_ids + [None] * (len(req.urls) - len(req.video_ids))
            # Position is 1-based and reflects the queue order coming from the frontend.
            # When the user is downloading a playlist, this becomes {n} in filenames.
            triples = [
                (url, vid, (i + 1) if req.is_playlist else None)
                for i, (url, vid) in enumerate(zip(req.urls, ids))
            ]
            if concurrent <= 1 or len(triples) <= 1:
                for url, vid, pos in triples:
                    _do_one(url, vid, pos)
            else:
                with ThreadPoolExecutor(max_workers=concurrent) as pool:
                    list(pool.map(lambda p: _do_one(*p), triples))
            q.put({"status": "all_done",
                   "open_when_done": req.options.openWhenDone,
                   "destination": req.destination})
        except Exception as e:
            log.exception("Job failed")
            q.put({"status": "error", "error": str(e)})
        finally:
            q.put(None)

    threading.Thread(target=run, daemon=True).start()
    return {"job_id": job_id}


@app.get("/api/progress/{job_id}")
async def progress(job_id: str):
    if job_id not in JOBS:
        raise HTTPException(404)
    q = JOBS[job_id]
    loop = asyncio.get_running_loop()

    async def stream():
        try:
            while True:
                try:
                    event = await loop.run_in_executor(None, lambda: q.get(timeout=15))
                except Empty:
                    yield ": ping\n\n"
                    continue
                if event is None:
                    break
                yield f"data: {json.dumps(event)}\n\n"
        finally:
            JOBS.pop(job_id, None)

    return StreamingResponse(stream(), media_type="text/event-stream")


if __name__ == "__main__":
    port = 8765
    print(f"\n  Yoink running at http://127.0.0.1:{port}\n")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
