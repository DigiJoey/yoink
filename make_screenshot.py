"""Capture a real screenshot of the Yoink UI with placeholder data.

Boots the actual FastAPI server, opens the page in a headless Chromium via
Playwright, injects fake video data via JavaScript, and saves a full-page
screenshot at exact pixel dimensions (no DPI surprises, no monitor-size
clipping). All data is fake; nothing private is included.

Output: docs/screenshot.png

Requirements (one-time, already installed in the dev venv):
    pip install playwright
    playwright install chromium
"""
import socket
import sys
import threading
import time
from pathlib import Path

import uvicorn
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from app import app  # noqa: E402

PORT = 8773  # avoid clashing with a running dev instance on 8765
OUT = ROOT / "docs" / "screenshot.png"


def _wait_port(port: int, timeout: float = 10.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def _run_server():
    uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="critical")
    ).run()


# Mock data, populated through the app's own renderGrid + helpers so the
# resulting markup is identical to the real app.
INJECT_JS = r"""
(function () {
  function thumb(c1, c2) {
    var svg = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 9'><defs>"
      + "<linearGradient id='g' x1='0' y1='0' x2='0' y2='1'>"
      + "<stop offset='0' stop-color='" + c1 + "'/>"
      + "<stop offset='1' stop-color='" + c2 + "'/></linearGradient></defs>"
      + "<rect width='16' height='9' fill='url(%23g)'/></svg>";
    return "data:image/svg+xml;utf8," + encodeURIComponent(svg).replace(/'/g, "%27");
  }

  document.getElementById("dest").value = "C:\\Users\\You\\Videos\\Yoink";

  // Pywebview-only buttons are hidden until that event fires; force-show them
  // for the screenshot so the masthead matches what real users see.
  ["tray-btn", "browse-btn", "open-folder-btn"].forEach(function (id) {
    var el = document.getElementById(id);
    if (el) el.style.display = "";
  });

  videos = [
    { id: "d1", title: "Best Way To Train Your Dragon - Trailer",
      uploader: "DreamWorks Animation", duration: 138, url: "#",
      platform: "youtube", thumbnail: thumb("#3a0a0a", "#0f0f0f"),
      filesize_approx: 38 * 1024 * 1024, is_live: false },
    { id: "d2", title: "10 Tips For Better Smartphone Photos",
      uploader: "PhotographyTips", duration: 754, url: "#",
      platform: "youtube", thumbnail: thumb("#1a3a5a", "#0f0f0f"),
      filesize_approx: 216 * 1024 * 1024, is_live: false },
    { id: "d3", title: "Sunset Timelapse Reel",
      uploader: "naturefilms", duration: 45, url: "#",
      platform: "instagram", thumbnail: thumb("#5a1f6e", "#cc4070"),
      filesize_approx: 14 * 1024 * 1024, is_live: false },
    { id: "d4", title: "Live coding stream highlights",
      uploader: "@devacademy", duration: 68, url: "#",
      platform: "twitter", thumbnail: thumb("#1a1a1a", "#404040"),
      filesize_approx: 22 * 1024 * 1024, is_live: false }
  ];
  selected = new Set(videos.map(function (v) { return v.id; }));
  renderGrid();
  document.getElementById("footer").classList.remove("hidden");
  document.body.classList.add("has-transport");
  updateDownloadBtn();
  setStatus("Added 4 videos to the queue.");

  var c2 = document.querySelector('.card[data-id="d2"]');
  if (c2) {
    c2.classList.add("downloading");
    c2.querySelector(".card-progress").classList.remove("hidden");
    c2.querySelectorAll(".vu span").forEach(function (s, i) {
      s.classList.toggle("lit", i < 10);
    });
    c2.querySelector(".card-pct").textContent = "62%";
    c2.querySelector(".card-speed").textContent = "4.3 MB/s";
  }
  var c3 = document.querySelector('.card[data-id="d3"]');
  if (c3) {
    c3.classList.add("done");
    c3.querySelector(".card-progress").classList.remove("hidden");
    c3.querySelectorAll(".vu span").forEach(function (s) { s.classList.add("lit"); });
    c3.querySelector(".card-pct").textContent = "✓ done";
  }
})();
"""


def main():
    OUT.parent.mkdir(exist_ok=True)
    threading.Thread(target=_run_server, daemon=True).start()
    if not _wait_port(PORT):
        raise RuntimeError("Backend did not start")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1320, "height": 1100},
            device_scale_factor=2,  # crisp on retina/HiDPI
        )
        page = context.new_page()
        page.goto(f"http://127.0.0.1:{PORT}/")
        # Let fonts/styles settle
        page.wait_for_load_state("networkidle")
        time.sleep(1.0)
        page.evaluate(INJECT_JS)
        time.sleep(0.5)
        # full_page=True captures the entire scroll height, regardless of viewport.
        page.screenshot(path=str(OUT), full_page=True)
        print(f"Wrote {OUT}")
        browser.close()


if __name__ == "__main__":
    main()
