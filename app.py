import asyncio
import json
import logging
import re
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

# When frozen by PyInstaller, data files live in sys._MEIPASS.
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    BASE = Path(sys._MEIPASS)
else:
    BASE = Path(__file__).parent

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
        "ignoreerrors": True,
    }

    # Authentication: custom cookie file overrides browser cookies if set
    if o.cookieFile and Path(o.cookieFile).exists():
        opts["cookiefile"] = o.cookieFile
    elif o.cookies != "off":
        opts["cookiesfrombrowser"] = (o.cookies,)

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
            _append_history({
                "id": vid,
                "title": info_dict.get("title") or "Unknown",
                "uploader": info_dict.get("uploader") or info_dict.get("channel"),
                "url": info_dict.get("webpage_url") or info_dict.get("original_url"),
                "filepath": d.get("filename") or d.get("info_dict", {}).get("_filename"),
                "format": req.format,
                "quality": req.quality,
                "completed_at": datetime.now().isoformat(timespec="seconds"),
            })

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
