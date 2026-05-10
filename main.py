import os
import sys
from pathlib import Path

# Inject the user-writable yt-dlp override directory onto sys.path BEFORE any
# module imports yt_dlp. The frozen .exe ships its own bundled yt_dlp inside
# _internal/, but that is read-only. To support in-place yt-dlp updates,
# the updater extracts a fresh wheel to this directory; sys.path is searched
# in order, so the override is loaded first when present.
def _override_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "Yoink" / "yt_dlp_override"
    return Path.home() / ".yoink" / "yt_dlp_override"

_ovr = _override_dir()
if _ovr.exists() and (_ovr / "yt_dlp").is_dir():
    sys.path.insert(0, str(_ovr))

import ctypes
import io
import json
import logging
import shutil
import socket
import subprocess
import threading
import time
import urllib.request
import zipfile

import uvicorn
import webview
from PIL import Image

from app import app
from paths import LOG_FILE, WINDOW_STATE, default_videos_dir

logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("yoink.main")

PORT = 8765
URL = f"http://127.0.0.1:{PORT}"

# When running as a PyInstaller bundle, data files live in sys._MEIPASS.
# When running from source, they sit next to this script.
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    BASE = Path(sys._MEIPASS)
    EXE_DIR = Path(sys.executable).parent
else:
    BASE = Path(__file__).parent
    EXE_DIR = BASE

# A bundled ffmpeg.exe sits next to Yoink.exe (not inside _MEIPASS).
# Prepend its directory to PATH so yt-dlp can find it without external installs.
if sys.platform == "win32" and (EXE_DIR / "ffmpeg.exe").exists():
    os.environ["PATH"] = str(EXE_DIR) + os.pathsep + os.environ.get("PATH", "")

ICON = BASE / "app.ico"
WIN_TITLE = "Yoink"
APP_ID = "joeyg.yoink.youtube.1"
APP_VERSION = "1.0.4"

# GitHub repo for self-update checks. Edit this when the project goes public.
# Format: "owner/repo". The release is expected to attach YoinkSetup.exe as an asset.
GITHUB_REPO = "DigiJoey/yoink"


def load_window_state() -> dict:
    if WINDOW_STATE.exists():
        try:
            return json.loads(WINDOW_STATE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_window_state():
    if not state.window:
        return
    # The window's width/height accessor calls into the GUI thread. If the
    # window has already been torn down (or has not finished initializing),
    # the underlying call returns None and unpacking fails. Treat that as
    # "nothing to save" silently rather than logging a noisy traceback.
    try:
        w = state.window.width
        h = state.window.height
        x = state.window.x
        y = state.window.y
    except Exception:
        return
    if not w or not h:
        return
    try:
        WINDOW_STATE.write_text(json.dumps({
            "width": int(w),
            "height": int(h),
            "x": int(x) if x is not None else None,
            "y": int(y) if y is not None else None,
        }), encoding="utf-8")
    except Exception:
        log.exception("Failed to save window state")


def set_app_user_model_id():
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass


def set_taskbar_icon():
    if sys.platform != "win32" or not ICON.exists():
        return
    user32 = ctypes.windll.user32
    LR_LOADFROMFILE = 0x00000010
    LR_DEFAULTSIZE = 0x00000040
    IMAGE_ICON = 1
    WM_SETICON = 0x0080
    ICON_SMALL, ICON_BIG = 0, 1
    hwnd = user32.FindWindowW(None, WIN_TITLE)
    if not hwnd:
        return
    hicon = user32.LoadImageW(
        0, str(ICON), IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE
    )
    if not hicon:
        return
    user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon)
    user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon)


def wait_for_port(port: int, timeout: float = 10.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def run_server():
    config = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="critical")
    uvicorn.Server(config).run()


class App:
    def __init__(self):
        self.window: webview.Window | None = None
        self.tray = None

    # --- Tray / window ---
    def hide_to_tray(self):
        if self.window:
            self.window.hide()
            if self.tray:
                self.tray.visible = True

    def show_window(self):
        if self.window:
            self.window.show()
            if self.tray:
                self.tray.visible = False

    def notify(self, title: str, message: str = ""):
        if self.tray and self.tray.visible:
            try:
                self.tray.notify(message or title, title)
            except Exception:
                pass

    def quit(self):
        save_window_state()
        if self.tray:
            try:
                self.tray.stop()
            except Exception:
                pass
        os._exit(0)

    # --- defaults / paths ---
    def default_destination(self) -> str:
        return str(default_videos_dir())

    def yoink_version(self) -> str:
        return APP_VERSION

    def open_log(self) -> bool:
        try:
            os.startfile(str(LOG_FILE))
            return True
        except Exception:
            return False

    def open_user_data(self) -> bool:
        try:
            os.startfile(str(LOG_FILE.parent))
            return True
        except Exception:
            return False

    def pick_cookies_file(self) -> str | None:
        if not self.window:
            return None
        try:
            result = self.window.create_file_dialog(
                webview.OPEN_DIALOG,
                file_types=("Cookies file (*.txt)", "All files (*.*)"),
            )
        except Exception:
            return None
        if result and len(result) > 0:
            return str(result[0])
        return None

    def pick_video_files(self) -> list[str]:
        """Open a multi-select dialog and return chosen video file paths."""
        if not self.window:
            return []
        try:
            result = self.window.create_file_dialog(
                webview.OPEN_DIALOG,
                allow_multiple=True,
                file_types=(
                    "Video files (*.mp4;*.mkv;*.webm;*.mov;*.avi;*.flv;*.m4v)",
                    "All files (*.*)",
                ),
            )
        except Exception:
            return []
        return [str(p) for p in (result or [])]

    # --- Folder picker ---
    def pick_folder(self, current: str = "") -> str | None:
        if not self.window:
            return None
        try:
            result = self.window.create_file_dialog(
                webview.FOLDER_DIALOG,
                directory=current or "",
            )
        except Exception:
            return None
        if result and len(result) > 0:
            return str(result[0])
        return None

    # --- Open folder in file explorer ---
    def open_folder(self, path: str) -> bool:
        try:
            os.startfile(path)
            return True
        except Exception:
            return False

    # --- yt-dlp version + updater ---
    def yt_dlp_version(self) -> str:
        try:
            import yt_dlp
            return yt_dlp.version.__version__
        except Exception:
            return "unknown"

    def check_update(self) -> dict:
        """Update yt-dlp by fetching its latest wheel from PyPI and extracting
        into the user-data override directory. Works in frozen builds (no pip)."""
        try:
            with urllib.request.urlopen(
                "https://pypi.org/pypi/yt-dlp/json", timeout=20
            ) as r:
                meta = json.loads(r.read())
        except Exception as e:
            log.exception("PyPI metadata fetch failed")
            return {"status": "error", "message": f"Could not reach PyPI: {e}"}

        latest = meta.get("info", {}).get("version")
        if not latest:
            return {"status": "error", "message": "PyPI did not return a version."}

        current = self.yt_dlp_version()
        if current == latest:
            return {"status": "current", "version": current,
                    "message": f"Already up to date, v{current}."}

        # Find a pure-Python wheel for this release
        wheel_url = None
        for f in meta.get("releases", {}).get(latest, []):
            if f.get("packagetype") == "bdist_wheel":
                wheel_url = f.get("url")
                break
        if not wheel_url:
            return {"status": "error", "message": "No wheel found on PyPI."}

        override_dir = _ovr
        try:
            # Wipe and re-extract so we never end up with mixed-version files
            if override_dir.exists():
                shutil.rmtree(override_dir, ignore_errors=True)
            override_dir.mkdir(parents=True, exist_ok=True)
            with urllib.request.urlopen(wheel_url, timeout=180) as r:
                wheel_bytes = r.read()
            with zipfile.ZipFile(io.BytesIO(wheel_bytes)) as zf:
                zf.extractall(override_dir)
        except Exception as e:
            log.exception("yt-dlp wheel install failed")
            return {"status": "error", "message": f"Install failed: {e}"}

        return {"status": "updated", "version": latest,
                "message": f"Updated to v{latest}. Restart Yoink to use it."}

    def check_yoink_update(self) -> dict:
        """Look up the latest Yoink release on GitHub."""
        if "/" not in GITHUB_REPO or "your-" in GITHUB_REPO:
            return {"status": "error",
                    "message": "Update check is not configured for this build."}
        api = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        try:
            req = urllib.request.Request(
                api, headers={"User-Agent": "Yoink-update-checker"}
            )
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.loads(r.read())
        except Exception as e:
            log.exception("GitHub release check failed")
            return {"status": "error", "message": f"Could not reach GitHub: {e}"}

        latest_tag = (data.get("tag_name") or "").lstrip("v").strip()
        if not latest_tag:
            return {"status": "error", "message": "No release tag found."}
        installer_url = None
        for asset in data.get("assets", []):
            if asset.get("name", "").lower() == "yoinksetup.exe":
                installer_url = asset.get("browser_download_url")
                break
        if latest_tag == APP_VERSION:
            return {
                "status": "current",
                "current": APP_VERSION,
                "latest": latest_tag,
                "message": f"You are on the latest Yoink, v{APP_VERSION}.",
            }
        return {
            "status": "available",
            "current": APP_VERSION,
            "latest": latest_tag,
            "installer_url": installer_url,
            "release_url": data.get("html_url"),
            "release_notes": data.get("body") or "",
        }

    def download_yoink_update(self, installer_url: str) -> dict:
        """Download the installer to a temp file and launch it. The installer's
        CloseApplications setting kills the running Yoink so it can replace files."""
        if not installer_url:
            return {"status": "error", "message": "No installer URL."}
        try:
            import tempfile
            tmp = Path(tempfile.gettempdir()) / "YoinkSetup.exe"
            req = urllib.request.Request(
                installer_url, headers={"User-Agent": "Yoink-updater"}
            )
            with urllib.request.urlopen(req, timeout=300) as r:
                tmp.write_bytes(r.read())
            DETACHED_PROCESS = 0x00000008
            subprocess.Popen([str(tmp)], creationflags=DETACHED_PROCESS, close_fds=True)
            # Give the installer a moment to start, then quit ourselves
            threading.Timer(0.6, self.quit).start()
            return {"status": "launched"}
        except Exception as e:
            log.exception("Yoink update download/launch failed")
            return {"status": "error", "message": str(e)}


class JsApi:
    """Thin wrapper exposed to JavaScript. Holds no native objects so pywebview
    does not recurse into WebView2 COM attributes when it builds the JS bridge."""

    def __init__(self, app: "App"):
        self._app = app

    def hide_to_tray(self): return self._app.hide_to_tray()
    def show_window(self): return self._app.show_window()
    def notify(self, title, message=""): return self._app.notify(title, message)
    def pick_folder(self, current=""): return self._app.pick_folder(current)
    def open_folder(self, path): return self._app.open_folder(path)
    def yt_dlp_version(self): return self._app.yt_dlp_version()
    def check_update(self): return self._app.check_update()
    def default_destination(self): return self._app.default_destination()
    def yoink_version(self): return self._app.yoink_version()
    def open_log(self): return self._app.open_log()
    def open_user_data(self): return self._app.open_user_data()
    def pick_cookies_file(self): return self._app.pick_cookies_file()
    def pick_video_files(self): return self._app.pick_video_files()
    def check_yoink_update(self): return self._app.check_yoink_update()
    def download_yoink_update(self, installer_url): return self._app.download_yoink_update(installer_url)


state = App()


def setup_tray():
    import pystray

    if ICON.exists():
        image = Image.open(ICON)
    else:
        image = Image.new("RGB", (64, 64), (230, 57, 70))

    icon = pystray.Icon(
        "yoink",
        image,
        "Yoink",
        menu=pystray.Menu(
            pystray.MenuItem("Show", lambda i, it: state.show_window(), default=True),
            pystray.MenuItem("Quit", lambda i, it: state.quit()),
        ),
    )
    icon.visible = False
    state.tray = icon
    threading.Thread(target=icon.run, daemon=True).start()


def main():
    set_app_user_model_id()

    threading.Thread(target=run_server, daemon=True).start()
    if not wait_for_port(PORT, 10.0):
        raise RuntimeError("Backend did not start in time")

    setup_tray()

    icon_path = str(ICON) if ICON.exists() else None

    saved = load_window_state()
    state.window = webview.create_window(
        WIN_TITLE,
        URL,
        width=saved.get("width") or 1200,
        height=saved.get("height") or 820,
        x=saved.get("x"),
        y=saved.get("y"),
        min_size=(720, 560),
        background_color="#0f0f0f",
        js_api=JsApi(state),
    )

    def on_shown():
        for _ in range(20):
            if ctypes.windll.user32.FindWindowW(None, WIN_TITLE):
                break
            time.sleep(0.05)
        set_taskbar_icon()

    state.window.events.shown += on_shown

    webview.start(debug=False, icon=icon_path)
    state.quit()


if __name__ == "__main__":
    main()
