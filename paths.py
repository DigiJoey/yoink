"""Shared filesystem paths used by both main.py and app.py.

Stores user data outside the install directory so updates and uninstalls
do not clobber it.
"""
import os
import sys
from pathlib import Path


def _user_data() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "Yoink"
    return Path.home() / ".yoink"


USER_DATA = _user_data()
try:
    USER_DATA.mkdir(parents=True, exist_ok=True)
except Exception:
    USER_DATA = Path.home() / ".yoink"
    USER_DATA.mkdir(parents=True, exist_ok=True)

ARCHIVE_FILE = USER_DATA / "downloaded.txt"
HISTORY_FILE = USER_DATA / "history.json"
WINDOW_STATE = USER_DATA / "window.json"
LOG_FILE = USER_DATA / "yoink.log"


def default_videos_dir() -> Path:
    return Path.home() / "Videos"
