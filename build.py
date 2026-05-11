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
from pathlib import Path  # noqa: F401

ROOT = Path(__file__).parent
DIST_DIR = ROOT / "dist" / "Yoink"


def ensure_pyinstaller():
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("Installing PyInstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])


def _deno_runs(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        r = subprocess.run(
            [str(path), "--version"],
            capture_output=True, text=True, timeout=10,
        )
        return r.returncode == 0 and "deno" in (r.stdout or "").lower()
    except Exception:
        return False


def find_deno() -> Path | None:
    """Find a usable deno.exe. yt-dlp's YouTube extractor needs a JS runtime;
    deno is the only one enabled by default. Prefer the real binary over
    package-manager shims so the file works when copied next to Yoink.exe."""
    candidates: list[Path] = []
    localappdata = os.environ.get("LOCALAPPDATA", "")
    if localappdata:
        wg = Path(localappdata) / "Microsoft" / "WinGet" / "Packages"
        if wg.exists():
            candidates += list(wg.glob("DenoLand.Deno*/**/deno.exe"))
    # Chocolatey: real binary lives in lib/; bin/ has a shim that breaks
    # when relocated. (Same gotcha that bit us with ffmpeg in v1.0.5.)
    candidates.append(Path("C:/ProgramData/chocolatey/lib/deno/tools/deno.exe"))
    # Common manual install path (deno's official installer)
    candidates.append(Path.home() / ".deno" / "bin" / "deno.exe")
    # Last resort: whatever is on PATH
    path_str = shutil.which("deno")
    if path_str:
        candidates.append(Path(path_str))
    for c in candidates:
        if _deno_runs(c):
            print(f"Verified deno at {c}")
            return c
        elif c.exists():
            print(f"Skipping {c} (does not run cleanly)")
    return None


def _ffmpeg_runs(path: Path) -> bool:
    """A candidate is only acceptable if running it actually emits version info.
    yt-dlp.FFmpeg ships a Chocolatey-style shim that fails when relocated; we
    must validate each candidate, not just check it exists."""
    if not path.exists():
        return False
    try:
        r = subprocess.run(
            [str(path), "-version"],
            capture_output=True, text=True, timeout=10,
        )
        return r.returncode == 0 and "ffmpeg version" in (r.stdout or "")
    except Exception:
        return False


def find_ffmpeg() -> Path | None:
    """Find a real (non-shim) ffmpeg.exe. Prefer Gyan.FFmpeg and BtbN
    distributions; fall back to chocolatey's real binary location, raw
    manual installs, and finally whatever is on PATH. Always verifies
    by running -version before returning a path."""
    candidates: list[Path] = []
    localappdata = os.environ.get("LOCALAPPDATA", "")
    if localappdata:
        wg = Path(localappdata) / "Microsoft" / "WinGet" / "Packages"
        if wg.exists():
            candidates += list(wg.glob("Gyan.FFmpeg*/**/bin/ffmpeg.exe"))
            candidates += list(wg.glob("BtbN.FFmpeg*/**/bin/ffmpeg.exe"))
            # yt-dlp.FFmpeg is last because its bin/ffmpeg.exe is a broken shim.
            candidates += list(wg.glob("yt-dlp.FFmpeg*/**/bin/ffmpeg.exe"))

    # Chocolatey: the file in bin/ is a shim; the real binary lives in lib/.
    candidates.append(
        Path("C:/ProgramData/chocolatey/lib/ffmpeg/tools/ffmpeg/bin/ffmpeg.exe")
    )
    # Common manual install paths
    for p in (
        "C:/ffmpeg/bin/ffmpeg.exe",
        "C:/Program Files/ffmpeg/bin/ffmpeg.exe",
    ):
        candidates.append(Path(p))

    # Last resort: whatever is on PATH
    path_str = shutil.which("ffmpeg")
    if path_str:
        candidates.append(Path(path_str))

    for c in candidates:
        if _ffmpeg_runs(c):
            print(f"Verified ffmpeg at {c}")
            return c
        elif c.exists():
            print(f"Skipping {c} (does not run cleanly)")
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

    # Bundle ffmpeg and ffprobe next to Yoink.exe
    ffmpeg = find_ffmpeg()
    if ffmpeg and ffmpeg.exists():
        dst = DIST_DIR / "ffmpeg.exe"
        print(f"Bundling ffmpeg from {ffmpeg} -> {dst}")
        shutil.copy2(ffmpeg, dst)
        # ffprobe sits next to ffmpeg in standard builds; copy it too so the
        # compress feature can probe video durations.
        probe = ffmpeg.with_name("ffprobe.exe" if ffmpeg.suffix.lower() == ".exe" else "ffprobe")
        if probe.exists():
            probe_dst = DIST_DIR / "ffprobe.exe"
            print(f"Bundling ffprobe from {probe} -> {probe_dst}")
            shutil.copy2(probe, probe_dst)
        else:
            print(f"NOTE: ffprobe not found next to ffmpeg at {probe}. Compress duration probing will fail.")
    else:
        print("\nWARNING: ffmpeg.exe was not found on PATH or in winget.")
        print("Yoink.exe will run, but MP3 extraction and video+audio merging will fail")
        print("on machines without ffmpeg installed. To fix, install ffmpeg and rerun")
        print("this script, or copy ffmpeg.exe into dist/Yoink/ manually before packaging.\n")

    # Bundle deno.exe next to Yoink.exe so yt-dlp's YouTube extractor has
    # a JS runtime. Without it, some formats become unavailable.
    deno = find_deno()
    if deno and deno.exists():
        dst = DIST_DIR / "deno.exe"
        print(f"Bundling deno from {deno} -> {dst}")
        shutil.copy2(deno, dst)
    else:
        print("\nWARNING: deno.exe was not found on PATH or in winget.")
        print("Install via `winget install DenoLand.Deno` and rebuild, or YouTube")
        print("format selection may degrade as yt-dlp deprecates non-JS extraction.\n")

    print(f"\nBuild complete: {DIST_DIR / 'Yoink.exe'}")


if __name__ == "__main__":
    build()
