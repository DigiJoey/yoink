"""Build a standalone Windows distribution of Yoink using PyInstaller.

Usage:
    .venv\\Scripts\\python.exe build.py

Output:
    dist/Yoink/Yoink.exe   (plus an _internal/ folder with bundled files)

Optional ffmpeg bundling:
    If ffmpeg.exe is on PATH or installed via winget (yt-dlp.FFmpeg),
    it gets copied alongside Yoink.exe so MP3 extraction and video merging
    work on machines without ffmpeg installed.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
DIST_DIR = ROOT / "dist" / "Yoink"


def ensure_pyinstaller():
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("Installing PyInstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])


def find_ffmpeg() -> Path | None:
    # 1. PATH
    path = shutil.which("ffmpeg")
    if path:
        return Path(path)
    # 2. winget install location for yt-dlp.FFmpeg
    localappdata = os.environ.get("LOCALAPPDATA", "")
    if localappdata:
        wg = Path(localappdata) / "Microsoft" / "WinGet" / "Packages"
        if wg.exists():
            matches = list(wg.glob("yt-dlp.FFmpeg*/**/ffmpeg.exe"))
            if matches:
                return matches[0]
    return None


def build():
    ensure_pyinstaller()

    # Clean previous build artefacts
    for d in (ROOT / "build", ROOT / "dist"):
        if d.exists():
            print(f"Removing {d}")
            shutil.rmtree(d)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--icon=app.ico",
        "--name=Yoink",
        "--add-data=static;static",
        "--add-data=app.ico;.",
        "--collect-all=yt_dlp",
        "--collect-all=webview",
        "--collect-submodules=pystray",
        "--hidden-import=pystray._win32",
        "main.py",
    ]
    print("Running:", " ".join(cmd))
    subprocess.check_call(cmd, cwd=ROOT)

    # Bundle ffmpeg next to Yoink.exe
    ffmpeg = find_ffmpeg()
    if ffmpeg and ffmpeg.exists():
        dst = DIST_DIR / "ffmpeg.exe"
        print(f"Bundling ffmpeg from {ffmpeg} -> {dst}")
        shutil.copy2(ffmpeg, dst)
    else:
        print("\nWARNING: ffmpeg.exe was not found on PATH or in winget.")
        print("Yoink.exe will run, but MP3 extraction and video+audio merging will fail")
        print("on machines without ffmpeg installed. To fix, install ffmpeg and rerun")
        print("this script, or copy ffmpeg.exe into dist/Yoink/ manually before packaging.\n")

    print(f"\nBuild complete: {DIST_DIR / 'Yoink.exe'}")


if __name__ == "__main__":
    build()
