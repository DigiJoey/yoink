const $ = sel => document.querySelector(sel);
const $$ = sel => document.querySelectorAll(sel);
const native = () => window.pywebview && window.pywebview.api;

window.addEventListener("error", e => {
  console.error(e.error || e.message);
  try { setStatus(`UI error: ${e.message}`, true); } catch {}
});
window.addEventListener("unhandledrejection", e => {
  console.error(e.reason);
  try { setStatus(`UI error: ${e.reason?.message || e.reason}`, true); } catch {}
});

let videos = [];
let selected = new Set();
let playlistUrl = null;

// Default destination filled by backend on first launch (per-machine path).
$("#dest").value = localStorage.getItem("dest") || "";
$("#dest").addEventListener("input", e => localStorage.setItem("dest", e.target.value));

/* ---- Settings ---- */
const Settings = {
  defaults: {
    embedMetadata: true,
    defaultVideoQuality: "1080",
    defaultMp3Bitrate: "192",
    filenameTemplate: "{n} - {title}",
    subtitles: false,
    subtitleLangs: "en",
    sbMode: "off",
    sbCategories: ["sponsor", "selfpromo"],
    concurrent: "1",
    openWhenDone: false,
    cookies: "off",
    cookieFile: "",
    rateLimit: "off",
    skipDownloaded: true,
  },
  get(key) {
    const raw = localStorage.getItem(`opt.${key}`);
    if (raw === null) return this.defaults[key];
    try { return JSON.parse(raw); } catch { return raw; }
  },
  set(key, val) {
    localStorage.setItem(`opt.${key}`, JSON.stringify(val));
  },
  all() {
    const o = {};
    for (const k of Object.keys(this.defaults)) o[k] = this.get(k);
    return o;
  },
};

function setSegActive(name, value) {
  const seg = document.querySelector(`[data-name="${name}"]`);
  if (!seg) return;
  seg.querySelectorAll(".seg-btn").forEach(b =>
    b.classList.toggle("active", b.dataset.value === value));
}

function initSettingsUI() {
  $$('[data-opt]').forEach(el => {
    const key = el.dataset.opt;
    const val = Settings.get(key);
    if (el.type === "checkbox") {
      el.checked = !!val;
    } else {
      el.value = val;
    }
    el.addEventListener("change", () => {
      const v = el.type === "checkbox" ? el.checked : el.value;
      Settings.set(key, v);
      // When defaults change, update homepage controls to match
      if (key === "defaultVideoQuality") setSegActive("resolution", v);
      if (key === "defaultMp3Bitrate") setSegActive("bitrate", v);
    });
  });

  const sbBox = $('[data-opt-group="sbCategories"]');
  if (sbBox) {
    const cats = new Set(Settings.get("sbCategories"));
    sbBox.querySelectorAll('input[type="checkbox"]').forEach(cb => {
      cb.checked = cats.has(cb.dataset.cat);
      cb.addEventListener("change", () => {
        const out = Array.from(sbBox.querySelectorAll('input:checked')).map(c => c.dataset.cat);
        Settings.set("sbCategories", out);
      });
    });
  }
}
initSettingsUI();

// Initialize homepage Quality control from saved defaults
setSegActive("resolution", Settings.get("defaultVideoQuality"));
setSegActive("bitrate", Settings.get("defaultMp3Bitrate"));

/* ---- Filename template UI ---- */
const TEMPLATE_SAMPLE = {
  "{title}": "How To Train Your Dragon",
  "{channel}": "DreamWorks",
  "{n}": "01",
  "{playlist}": "My Favorites",
  "{quality}": "1080p",
  "{upload_date}": "2024-03-15",
  "{download_date}": new Date().toISOString().slice(0, 10),
  "{id}": "dQw4w9WgXcQ",
  "{ext}": "mp4",
};
function renderTemplatePreview() {
  const tmplEl = $("#filename-template");
  const previewEl = $("#template-preview");
  if (!tmplEl || !previewEl) return;
  let out = tmplEl.value || "{n}{title}";
  for (const [tag, val] of Object.entries(TEMPLATE_SAMPLE)) {
    out = out.split(tag).join(val);
  }
  if (!out.endsWith(".mp4") && !out.endsWith(".mp3")) out += ".mp4";
  previewEl.textContent = out;
}
$("#filename-template").addEventListener("input", renderTemplatePreview);
renderTemplatePreview();

$$(".tag-chip").forEach(b => {
  b.addEventListener("click", () => {
    const input = $("#filename-template");
    const tag = b.dataset.tag;
    const start = input.selectionStart ?? input.value.length;
    const end = input.selectionEnd ?? input.value.length;
    input.value = input.value.slice(0, start) + tag + input.value.slice(end);
    input.focus();
    const pos = start + tag.length;
    input.setSelectionRange(pos, pos);
    Settings.set("filenameTemplate", input.value);
    renderTemplatePreview();
  });
});

/* ---- URL time auto-extract & clip input validation ---- */
function parseYTTimeStr(s) {
  if (!s) return null;
  s = String(s);
  if (/^\d+$/.test(s)) return parseInt(s, 10);
  const m = s.match(/^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$/);
  if (!m || (!m[1] && !m[2] && !m[3])) return null;
  return (parseInt(m[1] || 0, 10) * 3600) +
         (parseInt(m[2] || 0, 10) * 60) +
         parseInt(m[3] || 0, 10);
}
function getWidgetSeconds(widget) {
  const parts = widget.querySelectorAll("input");
  const h = parseInt(parts[0].value || "0", 10);
  const m = parseInt(parts[1].value || "0", 10);
  const s = parseInt(parts[2].value || "0", 10);
  return h * 3600 + m * 60 + s;
}

function setWidgetSeconds(widget, totalSec) {
  totalSec = Math.max(0, Math.floor(totalSec || 0));
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  const parts = widget.querySelectorAll("input");
  parts[0].value = String(h).padStart(2, "0");
  parts[1].value = String(m).padStart(2, "0");
  parts[2].value = String(s).padStart(2, "0");
}

function bindTimeWidget(widget) {
  const inputs = Array.from(widget.querySelectorAll("input"));
  inputs.forEach((input, i) => {
    // Clicking or focusing a field selects its content so typing overwrites
    const selectAll = () => input.select();
    input.addEventListener("focus", selectAll);
    input.addEventListener("click", selectAll);

    // Filter to digits, auto-advance when full
    input.addEventListener("input", () => {
      const v = input.value.replace(/\D/g, "");
      if (v !== input.value) input.value = v;
      // Cap individual field to its sensible max
      const max = i === 0 ? 99 : 59;
      if (input.value.length === 2) {
        const n = parseInt(input.value, 10);
        if (n > max) input.value = String(max).padStart(2, "0");
        if (inputs[i + 1]) inputs[i + 1].focus();
      }
    });

    input.addEventListener("blur", () => {
      if (!input.value) input.value = "00";
      else if (input.value.length === 1) input.value = "0" + input.value;
    });

    input.addEventListener("keydown", e => {
      if (e.key === "Backspace" && !input.value && i > 0) {
        e.preventDefault();
        const prev = inputs[i - 1];
        prev.focus();
        prev.value = "";
      } else if (e.key === "ArrowRight" && input.selectionStart === input.value.length && i < inputs.length - 1) {
        e.preventDefault();
        inputs[i + 1].focus();
      } else if (e.key === "ArrowLeft" && input.selectionStart === 0 && i > 0) {
        e.preventDefault();
        const prev = inputs[i - 1];
        prev.focus();
        prev.setSelectionRange(prev.value.length, prev.value.length);
      } else if (e.key === ":" || e.key === "Tab") {
        // Colon jumps to next field like a time picker
        if (e.key === ":" && i < inputs.length - 1) {
          e.preventDefault();
          inputs[i + 1].focus();
        }
      }
    });
  });
}
function extractTimesFromUrl(url) {
  try {
    const u = new URL(url);
    const t = u.searchParams.get("t") || u.searchParams.get("start");
    const e = u.searchParams.get("end");
    return { start: parseYTTimeStr(t), end: parseYTTimeStr(e) };
  } catch {
    return { start: null, end: null };
  }
}
function autoFillTimesFromUrl() {
  const { start, end } = extractTimesFromUrl($("#url").value);
  if (start != null) setWidgetSeconds($("#clip-start"), start);
  if (end != null) setWidgetSeconds($("#clip-end"), end);
}
$("#url").addEventListener("input", autoFillTimesFromUrl);

bindTimeWidget($("#clip-start"));
bindTimeWidget($("#clip-end"));

/* Settings modal open/close */
$("#settings-btn").addEventListener("click", openSettings);
$("#help-btn").addEventListener("click", () => {
  openSettings();
  const helpTab = document.querySelector('[data-tab="help"]');
  if (helpTab) helpTab.click();
});
$("#settings-close").addEventListener("click", closeSettings);
$("#settings-backdrop").addEventListener("click", closeSettings);
document.addEventListener("keydown", e => {
  if (e.key === "Escape" && $("#settings-modal").classList.contains("open")) closeSettings();
});
function openSettings() {
  $("#settings-modal").classList.add("open");
  $("#settings-modal").setAttribute("aria-hidden", "false");
  $("#settings-backdrop").classList.add("show");
}
function closeSettings() {
  $("#settings-modal").classList.remove("open");
  $("#settings-modal").setAttribute("aria-hidden", "true");
  $("#settings-backdrop").classList.remove("show");
}

/* Settings tab switching */
$$('.nav-item').forEach(b => {
  b.addEventListener('click', () => {
    const tab = b.dataset.tab;
    $$('.nav-item').forEach(x => x.classList.toggle('active', x === b));
    $$('.settings-page').forEach(p => p.classList.toggle('active', p.dataset.page === tab));
  });
});

/* ---- Status readout (no-op if element removed) ---- */
function setReadout(text) {
  const el = $("#rec-status");
  if (!el) return;
  const t = String(text || "");
  el.textContent = t.charAt(0).toUpperCase() + t.slice(1).toLowerCase();
}

/* ---- pywebview-only buttons ---- */
$("#tray-btn").style.display = "none";
$("#browse-btn").style.display = "none";
$("#open-folder-btn").style.display = "none";

$("#tray-btn").addEventListener("click", () => native() && native().hide_to_tray());

$("#browse-btn").addEventListener("click", async () => {
  if (!native()) return;
  const path = await native().pick_folder($("#dest").value || "");
  if (path) {
    $("#dest").value = path;
    localStorage.setItem("dest", path);
  }
});

$("#open-folder-btn").addEventListener("click", () => {
  const path = $("#dest").value.trim();
  if (path && native()) native().open_folder(path);
});

$("#update-btn").addEventListener("click", async () => {
  if (!native()) {
    setUpdateResult("Updates only available inside the desktop app.", "err");
    return;
  }
  const btn = $("#update-btn");
  btn.classList.add("updating");
  btn.disabled = true;
  setUpdateResult("Checking…");
  try {
    const r = await native().check_update();
    $("#version-num").textContent = r.version || "?";
    if (r.status === "updated") {
      setUpdateResult(r.message, "ok");
    } else if (r.status === "current") {
      setUpdateResult(r.message, "ok");
    } else {
      setUpdateResult(r.message || "Update failed.", "err");
    }
  } finally {
    btn.classList.remove("updating");
    btn.disabled = false;
  }
});

function setUpdateResult(msg, kind = "") {
  const el = $("#update-result");
  el.textContent = msg;
  el.classList.remove("ok", "err");
  if (kind) el.classList.add(kind);
}

window.addEventListener("pywebviewready", async () => {
  $("#tray-btn").style.display = "";
  $("#browse-btn").style.display = "";
  $("#open-folder-btn").style.display = "";
  try {
    const v = await native().yt_dlp_version();
    $("#version-num").textContent = v || "?";
    const ytdlpAbout = $("#about-ytdlp-version");
    if (ytdlpAbout) ytdlpAbout.textContent = v || "?";
  } catch {}
  try {
    if (typeof native().yoink_version === "function") {
      const yv = await native().yoink_version();
      const yvAbout = $("#about-yoink-version");
      if (yvAbout) yvAbout.textContent = yv || "?";
    }
  } catch {}
  try {
    if (!localStorage.getItem("dest")) {
      const dest = await native().default_destination();
      if (dest) {
        $("#dest").value = dest;
        localStorage.setItem("dest", dest);
      }
    }
  } catch {}
});

/* ---- History tab ---- */
$("#history-btn").addEventListener("click", () => {
  openSettings();
  const tab = document.querySelector('[data-tab="history"]');
  if (tab) tab.click();
  loadHistory();
});

async function loadHistory() {
  const list = $("#history-list");
  if (!list) return;
  list.innerHTML = '<p class="history-empty">Loading…</p>';
  try {
    const r = await fetch("/api/history");
    const data = await r.json();
    const entries = data.entries || [];
    if (!entries.length) {
      list.innerHTML = '<p class="history-empty">No downloads yet.</p>';
      return;
    }
    list.innerHTML = "";
    for (const e of entries) {
      const row = document.createElement("div");
      row.className = "history-row";
      row.title = e.filepath || "";
      const dateStr = e.completed_at ? new Date(e.completed_at).toLocaleString() : "";
      row.innerHTML = `
        <div class="h-title">${escapeHtml(e.title || "Unknown")}</div>
        <div class="h-meta">
          <span>${escapeHtml(e.uploader || "")}</span>
          <span>${escapeHtml((e.format || "").toUpperCase())}${e.quality ? " · " + escapeHtml(e.quality) : ""}</span>
          <span>${escapeHtml(dateStr)}</span>
        </div>`;
      row.addEventListener("click", () => {
        if (e.filepath && native()) native().open_folder(e.filepath.replace(/[\\/][^\\/]*$/, ""));
      });
      list.appendChild(row);
    }
  } catch (err) {
    list.innerHTML = `<p class="history-empty">Could not load history: ${err.message}</p>`;
  }
}
$("#history-refresh")?.addEventListener("click", loadHistory);
$("#history-clear")?.addEventListener("click", async () => {
  if (!confirm("Clear the history list? Already-downloaded videos will stay marked so they will not redownload.")) return;
  await fetch("/api/history/clear", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({clear_archive: false}) });
  loadHistory();
});
$("#history-clear-all")?.addEventListener("click", async () => {
  if (!confirm("Clear the history list AND the archive? Yoink will no longer skip videos you have already downloaded.")) return;
  await fetch("/api/history/clear", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({clear_archive: true}) });
  loadHistory();
});

/* ---- About tab buttons ---- */
$("#open-log")?.addEventListener("click", () => native() && native().open_log());
$("#open-data")?.addEventListener("click", () => native() && native().open_user_data());
$("#reset-settings")?.addEventListener("click", () => {
  if (!confirm("Reset all settings and clear the destination field? This will not delete any downloaded files or history.")) return;
  Object.keys(localStorage).filter(k => k.startsWith("opt.") || k === "dest").forEach(k => localStorage.removeItem(k));
  location.reload();
});

$("#check-yoink-update")?.addEventListener("click", async () => {
  if (!native() || typeof native().check_yoink_update !== "function") {
    setYoinkUpdateResult("Update check is only available in the desktop app.", "err");
    return;
  }
  const btn = $("#check-yoink-update");
  btn.classList.add("updating");
  btn.disabled = true;
  setYoinkUpdateResult("Checking GitHub for the latest release…");
  try {
    const r = await native().check_yoink_update();
    if (r.status === "current") {
      setYoinkUpdateResult(r.message, "ok");
    } else if (r.status === "available") {
      const notes = (r.release_notes || "").slice(0, 240);
      const installable = !!r.installer_url;
      setYoinkUpdateResult(
        `New release available: v${r.latest} (you have v${r.current})${notes ? "\n\n" + notes : ""}`
      );
      if (installable) {
        const ok = confirm(`Yoink v${r.latest} is available (you are on v${r.current}).\n\nDownload and install now? Yoink will close while the installer runs.`);
        if (ok) {
          setYoinkUpdateResult("Downloading installer… Yoink will close shortly.");
          await native().download_yoink_update(r.installer_url);
        }
      } else {
        setYoinkUpdateResult(
          `New release v${r.latest} is available, but no installer asset was attached. Visit the release page to download manually.`,
          "err"
        );
      }
    } else {
      setYoinkUpdateResult(r.message || "Update check failed.", "err");
    }
  } finally {
    btn.classList.remove("updating");
    btn.disabled = false;
  }
});

function setYoinkUpdateResult(msg, kind = "") {
  const el = $("#yoink-update-result");
  if (!el) return;
  el.textContent = msg;
  el.classList.remove("ok", "err");
  if (kind) el.classList.add(kind);
}

/* ---- Custom cookies file picker ---- */
$("#cookie-pick")?.addEventListener("click", async () => {
  if (!native() || typeof native().pick_cookies_file !== "function") return;
  const path = await native().pick_cookies_file();
  if (path) {
    const inp = $("#cookie-file");
    inp.value = path;
    inp.dispatchEvent(new Event("change"));
  }
});

/* ---- Drag and drop URLs ---- */
window.addEventListener("dragover", e => { e.preventDefault(); });
window.addEventListener("drop", e => {
  e.preventDefault();
  const text = e.dataTransfer?.getData("text/plain") || e.dataTransfer?.getData("text/uri-list") || "";
  const url = text.trim().split(/\s+/)[0];
  if (url && /^https?:\/\//i.test(url)) {
    $("#url").value = url;
    fetchInfo();
  }
});

/* ---- Keyboard shortcuts ---- */
document.addEventListener("keydown", e => {
  if (e.ctrlKey && e.key === "Enter") {
    e.preventDefault();
    fetchInfo();
  } else if (e.ctrlKey && (e.key === "d" || e.key === "D")) {
    e.preventDefault();
    if (!$("#download").disabled) startDownload();
  }
});

/* ---- Clear queue ---- */
$("#clear-queue")?.addEventListener("click", () => {
  videos = [];
  selected.clear();
  playlistUrl = null;
  $("#grid").innerHTML = "";
  $("#footer").classList.add("hidden");
  $("#grid-toolbar").classList.add("hidden");
  document.body.classList.remove("has-transport");
  hideStatus();
});

/* ---- Queue reordering ---- */
function moveVideo(draggedId, targetId, before) {
  const dragIdx = videos.findIndex(v => v.id === draggedId);
  const targetIdx = videos.findIndex(v => v.id === targetId);
  if (dragIdx < 0 || targetIdx < 0) return;
  const [moved] = videos.splice(dragIdx, 1);
  let newIdx = videos.findIndex(v => v.id === targetId);
  if (!before) newIdx += 1;
  videos.splice(newIdx, 0, moved);
  renderGrid();
  applyFilter();
}

/* ---- Search/filter ---- */
function applyFilter() {
  const q = ($("#grid-search")?.value || "").trim().toLowerCase();
  $$("#grid .card").forEach(c => {
    if (!q) { c.style.display = ""; return; }
    const v = videos.find(x => x.id === c.dataset.id);
    const hay = ((v?.title || "") + " " + (v?.uploader || "")).toLowerCase();
    c.style.display = hay.includes(q) ? "" : "none";
  });
}
$("#grid-search")?.addEventListener("input", applyFilter);

function updateGridToolbarVisibility() {
  // Show search bar once the grid is more than one row of cards
  $("#grid-toolbar").classList.toggle("hidden", videos.length < 7);
}

/* ---- Right-click context menu ---- */
const cardMenu = $("#card-menu");
let cardMenuVideo = null;
function showCardMenu(x, y, v) {
  cardMenuVideo = v;
  // Toggle "open file/folder" buttons based on whether the card is done
  const card = document.querySelector(`.card[data-id="${v.id}"]`);
  const isDone = !!(card && card.classList.contains("done") && v.filepath);
  cardMenu.querySelectorAll('[data-shows-when="done"]').forEach(b => {
    b.style.display = isDone ? "" : "none";
  });
  cardMenu.hidden = false;
  // Position, clamping to viewport
  const w = cardMenu.offsetWidth;
  const h = cardMenu.offsetHeight;
  const left = Math.min(x, window.innerWidth - w - 8);
  const top = Math.min(y, window.innerHeight - h - 8);
  cardMenu.style.left = left + "px";
  cardMenu.style.top = top + "px";
}
function hideCardMenu() {
  cardMenu.hidden = true;
  cardMenuVideo = null;
}
cardMenu.querySelectorAll("button").forEach(b => {
  b.addEventListener("click", () => {
    const action = b.dataset.action;
    const v = cardMenuVideo;
    hideCardMenu();
    if (!v) return;
    if (action === "copy-url") {
      navigator.clipboard.writeText(v.url).catch(() => {});
    } else if (action === "open-url") {
      if (native()) native().open_folder(v.url);
      else window.open(v.url, "_blank");
    } else if (action === "open-file" && v.filepath && native()) {
      native().open_folder(v.filepath);
    } else if (action === "open-folder" && v.filepath && native()) {
      const folder = v.filepath.replace(/[\\/][^\\/]*$/, "");
      native().open_folder(folder);
    } else if (action === "remove") {
      removeVideo(v.id);
    }
  });
});
document.addEventListener("click", e => {
  if (!cardMenu.contains(e.target)) hideCardMenu();
});
document.addEventListener("keydown", e => {
  if (e.key === "Escape") hideCardMenu();
});

function removeVideo(vid) {
  videos = videos.filter(v => v.id !== vid);
  selected.delete(vid);
  const card = document.querySelector(`.card[data-id="${vid}"]`);
  if (card) card.remove();
  updateDownloadBtn();
  updateGridToolbarVisibility();
  if (!videos.length) {
    $("#footer").classList.add("hidden");
    document.body.classList.remove("has-transport");
  }
}

/* ---- Settings export/import ---- */
$("#export-settings")?.addEventListener("click", () => {
  const data = {};
  Object.keys(localStorage).filter(k => k.startsWith("opt.") || k === "dest").forEach(k => {
    data[k] = localStorage.getItem(k);
  });
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "yoink-settings.json";
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
});

$("#import-settings")?.addEventListener("click", () => {
  $("#import-file").click();
});
$("#import-file")?.addEventListener("change", async e => {
  const file = e.target.files?.[0];
  if (!file) return;
  try {
    const text = await file.text();
    const data = JSON.parse(text);
    if (typeof data !== "object" || !data) throw new Error("Invalid file");
    if (!confirm("Replace your current settings with the contents of this file?")) return;
    Object.keys(localStorage).filter(k => k.startsWith("opt.") || k === "dest").forEach(k => localStorage.removeItem(k));
    for (const [k, v] of Object.entries(data)) {
      if (typeof k === "string" && (k.startsWith("opt.") || k === "dest")) {
        localStorage.setItem(k, String(v));
      }
    }
    location.reload();
  } catch (err) {
    setStatus(`Import failed: ${err.message}`, true);
  } finally {
    e.target.value = "";
  }
});

/* ---- Segmented controls ---- */
$$(".seg").forEach(seg => {
  seg.addEventListener("click", e => {
    const btn = e.target.closest(".seg-btn");
    if (!btn || btn.disabled) return;
    seg.querySelectorAll(".seg-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    if (seg.dataset.name === "format") syncQualityForFormat();
  });
});
function syncQualityForFormat() {
  const isMp3 = segValue("format") === "mp3";
  $("#seg-resolution").hidden = isMp3;
  $("#seg-bitrate").hidden = !isMp3;
}
syncQualityForFormat();

function segValue(name) {
  return document.querySelector(`[data-name="${name}"] .seg-btn.active`).dataset.value;
}

/* ---- Fetch info ---- */
$("#fetch").addEventListener("click", fetchInfo);
$("#url").addEventListener("keydown", e => { if (e.key === "Enter") fetchInfo(); });

async function fetchInfo() {
  const url = $("#url").value.trim();
  if (!url) return;
  $("#fetch").disabled = true;
  setStatus("Scanning source…");
  setReadout("scanning");

  // Channel detection: ask up front how many to fetch so we do not pull thousands.
  let limit = null;
  if (/youtube\.com\/(@|c\/|user\/|channel\/)/i.test(url)) {
    const ans = prompt(
      "This looks like a channel. How many of the most recent videos should Yoink fetch?\n\nEnter a number (1 to 500), or leave empty to cancel.",
      "20"
    );
    if (ans == null) {
      $("#fetch").disabled = false;
      setReadout("standby");
      hideStatus();
      return;
    }
    const n = parseInt(ans, 10);
    if (!isNaN(n) && n > 0) limit = Math.min(500, n);
  }

  try {
    const r = await fetch("/api/info", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, limit }),
    });
    if (!r.ok) throw new Error((await r.json()).detail || "Failed to fetch");
    const data = await r.json();
    const fetched = data.videos || [];
    if (!fetched.length) {
      setStatus("No videos found at that URL.", true);
      setReadout("error");
      return;
    }
    // Warn if any of the fetched entries is a live broadcast
    const liveCount = fetched.filter(v => v.is_live).length;
    if (liveCount > 0) {
      const ok = confirm(
        `${liveCount} of these ${liveCount === 1 ? "is a live stream" : "are live streams"}.\n\nLive streams download in real time and may never finish until the stream ends. Continue anyway?`
      );
      if (!ok) {
        $("#fetch").disabled = false;
        setReadout("standby");
        hideStatus();
        return;
      }
    }

    // Queue behaviour: append new videos, dedupe by id, keep existing ones.
    const existing = new Set(videos.map(v => v.id));
    const newOnes = fetched.filter(v => !existing.has(v.id));
    videos = videos.concat(newOnes);
    if (data.playlist_url && !playlistUrl) playlistUrl = data.playlist_url;

    // Auto-select the freshly added videos
    for (const v of newOnes) selected.add(v.id);

    appendCards(newOnes, existing.size);
    fetchSponsorBlock(newOnes.map(v => v.id));
    updateGridToolbarVisibility();

    if (newOnes.length === 0) {
      setStatus(`Already in the queue: ${fetched.length} video${fetched.length === 1 ? "" : "s"} from that link.`);
    } else if (data.playlist_title) {
      setStatus(`Added ${newOnes.length} video${newOnes.length === 1 ? "" : "s"} from playlist: ${data.playlist_title}`);
    } else if (newOnes.length === 1) {
      hideStatus();
    } else {
      setStatus(`Added ${newOnes.length} video${newOnes.length === 1 ? "" : "s"} to the queue.`);
    }

    // Clear the URL field so the next paste lands clean
    $("#url").value = "";

    setReadout("ready");
    $("#footer").classList.remove("hidden");
    document.body.classList.add("has-transport");
    updateDownloadBtn();
  } catch (e) {
    setStatus(`Error: ${e.message}`, true);
    setReadout("error");
  } finally {
    $("#fetch").disabled = false;
  }
}

/* ---- SponsorBlock segment fetch (after info loads) ---- */
async function fetchSponsorBlock(idsArg) {
  const ids = (idsArg && idsArg.length) ? idsArg : videos.map(v => v.id);
  if (!ids.length) return;
  try {
    const r = await fetch("/api/sponsorblock", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ video_ids: ids }),
    });
    if (!r.ok) return;
    const data = await r.json();
    for (const [vid, segs] of Object.entries(data.segments || {})) {
      if (segs && segs.length) renderSbForCard(vid, segs);
    }
  } catch {}
}

function renderSbForCard(videoId, segs) {
  const card = document.querySelector(`.card[data-id="${videoId}"]`);
  if (!card) return;
  const video = videos.find(v => v.id === videoId);
  const dur = video?.duration;
  if (!dur) return;

  // Build mini-strip on the thumbnail
  const thumb = card.querySelector(".card-thumb");
  let track = thumb.querySelector(".card-sb-track");
  if (!track) {
    track = document.createElement("div");
    track.className = "card-sb-track";
    thumb.appendChild(track);
  }
  track.innerHTML = "";
  for (const s of segs) {
    const el = document.createElement("span");
    el.className = "seg";
    el.dataset.cat = s.category;
    const start = (s.start / dur) * 100;
    const end = (s.end / dur) * 100;
    el.style.setProperty("--start", start.toFixed(2));
    el.style.setProperty("--end", end.toFixed(2));
    el.title = `${s.category} · ${formatTime(s.start)}–${formatTime(s.end)}`;
    track.appendChild(el);
  }

  // Summary chips below the title
  const meta = card.querySelector(".card-meta");
  let summary = meta.querySelector(".card-sb-summary");
  if (!summary) {
    summary = document.createElement("div");
    summary.className = "card-sb-summary";
    const insertBefore = meta.querySelector(".card-progress");
    meta.insertBefore(summary, insertBefore);
  }
  summary.innerHTML = "";
  // Group by category, sum durations
  const groups = {};
  for (const s of segs) {
    if (!groups[s.category]) groups[s.category] = { count: 0, total: 0 };
    groups[s.category].count++;
    groups[s.category].total += s.end - s.start;
  }
  for (const [cat, info] of Object.entries(groups)) {
    const chip = document.createElement("span");
    chip.className = "sb-chip";
    chip.dataset.cat = cat;
    chip.textContent = `${cat} ${info.count}× · ${formatTime(info.total)}`;
    chip.title = `${info.count} segment${info.count > 1 ? "s" : ""}, total ${formatTime(info.total)}`;
    summary.appendChild(chip);
  }
}

function formatTime(s) {
  s = Math.round(s);
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${String(sec).padStart(2, "0")}`;
}

/* ---- Platform badges ---- */
const PLATFORM_ICONS = {
  youtube: '<svg viewBox="0 0 14 14" width="12" height="12"><path d="M5 3.5 L5 10.5 L11 7 Z" fill="white"/></svg>',
  instagram: '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="white" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="5"/><circle cx="12" cy="12" r="4.2"/><circle cx="17.5" cy="6.5" r="1" fill="white" stroke="none"/></svg>',
  facebook: '<svg viewBox="0 0 24 24" width="14" height="14" fill="white"><path d="M14 9h3V6h-3c-1.66 0-3 1.34-3 3v2H8v3h3v7h3v-7h2.5l.5-3H14V9z"/></svg>',
  twitter: '<svg viewBox="0 0 24 24" width="12" height="12" fill="white"><path d="M14.7 10.4 22 2h-2l-6.3 7.3L8.6 2H2l7.7 11.2L2 22h2l6.7-7.7 5.4 7.7H22l-7.3-11.6zM12 13.3l-1-1.4L4.7 3.4h2.4l4.6 6.5 1 1.4 6.6 9.3h-2.4L12 13.3z"/></svg>',
};
function platformBadge(platform) {
  const icon = PLATFORM_ICONS[platform];
  if (!icon) return "";
  const labels = { youtube: "YouTube", instagram: "Instagram", facebook: "Facebook", twitter: "X" };
  return `<div class="platform-badge ${platform}" title="${labels[platform] || platform}">${icon}</div>`;
}

/* ---- Grid render ---- */
const SEG_COUNT = 16;
const vuSegments = () => Array.from({ length: SEG_COUNT }, () => "<span></span>").join("");

function estimateSize(v) {
  // Fall back to a heuristic when yt-dlp did not return filesize_approx.
  if (v.filesize_approx) return v.filesize_approx;
  if (!v.duration) return null;
  const fmt = segValue("format");
  if (fmt === "mp3") {
    const kbps = parseInt(segValue("bitrate"), 10) || 192;
    return v.duration * kbps * 125; // bytes
  }
  // MB per minute for various MP4 qualities, rough averages
  const mbPerMin = { "720": 2.5, "1080": 4.5, "4k": 18, "best": 6 }[segValue("resolution")] || 4.5;
  return (v.duration / 60) * mbPerMin * 1024 * 1024;
}

function formatBytes(b) {
  if (b == null) return "";
  if (b < 1024) return `${b} B`;
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(0)} KB`;
  if (b < 1024 * 1024 * 1024) return `${(b / 1024 / 1024).toFixed(0)} MB`;
  return `${(b / 1024 / 1024 / 1024).toFixed(1)} GB`;
}

function buildCardElement(v, i) {
  const card = document.createElement("article");
  card.className = "card" + (selected.has(v.id) ? " selected" : "");
  card.dataset.id = v.id;
  card.style.setProperty("--i", i);
  card.draggable = true;
  const thumbSrc = v.thumbnail || "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 9'><rect width='16' height='9' fill='%23272727'/></svg>";
  const size = estimateSize(v);
  card.innerHTML = `
    <div class="card-thumb">
      <img src="${thumbSrc}" loading="lazy" alt="">
      <div class="card-check"></div>
      ${platformBadge(v.platform)}
      ${v.is_live ? `<div class="card-live">Live</div>` : ""}
      ${v.duration ? `<div class="card-duration">${formatDuration(v.duration)}</div>` : ""}
    </div>
    <div class="card-meta">
      <h3 class="card-title">${escapeHtml(v.title)}</h3>
      ${v.uploader ? `<p class="card-channel">${escapeHtml(v.uploader)}</p>` : ""}
      ${size ? `<div class="card-info"><span class="card-size">~${formatBytes(size)}</span></div>` : ""}
      <div class="card-progress hidden">
        <div class="vu">${vuSegments()}</div>
        <div class="card-stats">
          <span class="card-pct">--</span>
          <span class="card-speed"></span>
        </div>
        <div class="card-actions">
          <button class="card-cancel" type="button">Cancel</button>
          <button class="card-retry" type="button">Retry</button>
          <button class="card-open" type="button">Open</button>
        </div>
      </div>
    </div>
  `;
  card.addEventListener("click", e => {
    if (e.target.closest(".card-cancel, .card-retry, .card-open")) return;
    toggleSelect(v.id);
  });
  card.querySelector(".card-cancel").addEventListener("click", e => {
    e.stopPropagation();
    cancelVideo(v.id);
  });
  card.querySelector(".card-retry").addEventListener("click", e => {
    e.stopPropagation();
    retryVideo(v.id);
  });
  card.querySelector(".card-open").addEventListener("click", e => {
    e.stopPropagation();
    if (v.filepath && native()) native().open_folder(v.filepath);
  });
  card.addEventListener("contextmenu", e => {
    e.preventDefault();
    showCardMenu(e.pageX, e.pageY, v);
  });
  // Drag and drop handlers for queue reordering
  card.addEventListener("dragstart", e => {
    card.classList.add("dragging");
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", v.id);
  });
  card.addEventListener("dragend", () => {
    card.classList.remove("dragging");
    document.querySelectorAll(".drop-target-before, .drop-target-after").forEach(c => {
      c.classList.remove("drop-target-before", "drop-target-after");
    });
  });
  card.addEventListener("dragover", e => {
    e.preventDefault();
    const dragging = document.querySelector(".card.dragging");
    if (!dragging || dragging === card) return;
    const r = card.getBoundingClientRect();
    const before = (e.clientX - r.left) < r.width / 2;
    card.classList.toggle("drop-target-before", before);
    card.classList.toggle("drop-target-after", !before);
  });
  card.addEventListener("dragleave", () => {
    card.classList.remove("drop-target-before", "drop-target-after");
  });
  card.addEventListener("drop", e => {
    e.preventDefault();
    const draggedId = e.dataTransfer.getData("text/plain");
    if (!draggedId || draggedId === v.id) return;
    const before = card.classList.contains("drop-target-before");
    card.classList.remove("drop-target-before", "drop-target-after");
    moveVideo(draggedId, v.id, before);
  });
  return card;
}

function cancelVideo(vid) {
  const card = document.querySelector(`.card[data-id="${vid}"]`);
  if (card) {
    card.classList.add("cancelling");
    const speed = card.querySelector(".card-speed");
    if (speed) speed.textContent = "cancelling…";
  }
  fetch("/api/cancel", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ video_id: vid }),
  }).catch(() => {});
}

let lastDownloadParams = null;

function retryVideo(vid) {
  const v = videos.find(x => x.id === vid);
  if (!v || !lastDownloadParams) return;
  const card = document.querySelector(`.card[data-id="${vid}"]`);
  if (card) {
    card.classList.remove("error", "cancelled", "cancelling", "done", "downloading");
    card.querySelectorAll(".vu span").forEach(s => s.classList.remove("lit"));
    const pct = card.querySelector(".card-pct");
    if (pct) pct.textContent = "--";
    const sp = card.querySelector(".card-speed");
    if (sp) sp.textContent = "";
    card.querySelector(".card-progress").classList.remove("hidden");
    card.classList.add("downloading");
  }
  fetch("/api/download", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      ...lastDownloadParams,
      urls: [v.url],
      video_ids: [v.id],
      is_playlist: false,
    }),
  })
    .then(r => r.json())
    .then(({ job_id }) => listenProgress(job_id, true))
    .catch(e => setStatus(`Retry failed: ${e.message}`, true));
}

function appendCards(newVideos, startIndex = 0) {
  const grid = $("#grid");
  newVideos.forEach((v, i) => grid.appendChild(buildCardElement(v, startIndex + i)));
}

function renderGrid() {
  const grid = $("#grid");
  grid.innerHTML = "";
  videos.forEach((v, i) => grid.appendChild(buildCardElement(v, i)));
}

function toggleSelect(id) {
  if (selected.has(id)) selected.delete(id);
  else selected.add(id);
  document.querySelector(`.card[data-id="${id}"]`).classList.toggle("selected");
  updateDownloadBtn();
}

$("#select-all").addEventListener("click", () => {
  selected = new Set(videos.map(v => v.id));
  $$(".card").forEach(c => c.classList.add("selected"));
  updateDownloadBtn();
});
$("#select-none").addEventListener("click", () => {
  selected.clear();
  $$(".card").forEach(c => c.classList.remove("selected"));
  updateDownloadBtn();
});

function updateDownloadBtn() {
  const n = selected.size;
  const total = videos.length;
  $("#download").disabled = n === 0;
  $("#download .rec-count").textContent = n > 0 ? `× ${n}` : "";
  $("#sel-count").innerHTML = `<strong>${n}</strong> of <strong>${total}</strong> selected`;
}

/* ---- Clip range ---- */
function parseTime(str) {
  if (!str || !str.trim()) return null;
  const t = str.trim();
  if (!/^[\d:.\s]+$/.test(t)) return NaN;
  const parts = t.split(":").map(p => parseFloat(p.trim()));
  if (parts.some(p => isNaN(p) || p < 0)) return NaN;
  if (parts.length === 1) return parts[0];
  if (parts.length === 2) return parts[0] * 60 + parts[1];
  if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
  return NaN;
}

$("#clip-clear").addEventListener("click", () => {
  setWidgetSeconds($("#clip-start"), 0);
  setWidgetSeconds($("#clip-end"), 0);
});

/* ---- Start download ---- */
$("#download").addEventListener("click", startDownload);

async function startDownload() {
  const chosen = videos.filter(v => selected.has(v.id));
  if (!chosen.length) return;
  const urls = chosen.map(v => v.url);
  const isPlaylist = !!playlistUrl;

  // Read clip range from the time widgets; zero on either end means "no clip"
  const startSec = getWidgetSeconds($("#clip-start"));
  const endSec = getWidgetSeconds($("#clip-end"));
  const clipStart = startSec > 0 ? startSec : null;
  const clipEnd = endSec > 0 ? endSec : null;
  if (clipStart != null && clipEnd != null && clipEnd <= clipStart) {
    setStatus("Clip end must be after clip start.", true);
    return;
  }

  $("#download").disabled = true;
  $("#fetch").disabled = true;
  document.body.classList.add("recording");
  setReadout("recording");
  $$(".card").forEach(c => {
    if (selected.has(c.dataset.id)) {
      c.querySelector(".card-progress").classList.remove("hidden");
      c.classList.remove("done", "error", "cancelled", "cancelling");
      c.classList.add("downloading");
      c.querySelectorAll(".vu span").forEach(s => s.classList.remove("lit"));
    }
  });
  // Build options: strip default* keys, inject the active homepage bitrate
  const opts = Settings.all();
  delete opts.defaultVideoQuality;
  delete opts.defaultMp3Bitrate;
  opts.mp3Bitrate = segValue("bitrate");

  // Compute quality label for {quality} tag in filename templates
  const fmt = segValue("format");
  const qualityLabel = fmt === "mp3"
    ? `${segValue("bitrate")}kbps`
    : ({ "720": "720p", "1080": "1080p", "4k": "4K", "best": "Max" }[segValue("resolution")] || segValue("resolution"));

  // Save params for per-video retry
  lastDownloadParams = {
    format: fmt,
    resolution: segValue("resolution"),
    quality: qualityLabel,
    destination: $("#dest").value.trim(),
    clip_start: clipStart,
    clip_end: clipEnd,
    options: opts,
  };

  try {
    const r = await fetch("/api/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        urls,
        video_ids: chosen.map(v => v.id),
        format: fmt,
        resolution: segValue("resolution"),
        quality: qualityLabel,
        destination: $("#dest").value.trim(),
        is_playlist: isPlaylist,
        clip_start: clipStart,
        clip_end: clipEnd,
        options: opts,
      }),
    });
    if (!r.ok) throw new Error((await r.json()).detail || "Failed");
    const { job_id } = await r.json();
    listenProgress(job_id);
  } catch (e) {
    setStatus(`Error: ${e.message}`, true);
    setReadout("error");
    document.body.classList.remove("recording");
    $("#download").disabled = false;
    $("#fetch").disabled = false;
  }
}

function endRun(state) {
  document.body.classList.remove("recording");
  setReadout(state);
  $("#download").disabled = false;
  $("#fetch").disabled = false;
}

function listenProgress(job_id, isRetry = false) {
  const es = new EventSource(`/api/progress/${job_id}`);
  es.onmessage = e => {
    const ev = JSON.parse(e.data);

    if (ev.status === "all_done") {
      if (!isRetry) {
        setStatus("All downloads complete.");
        endRun("complete");
        if (ev.open_when_done && ev.destination && native()) {
          native().open_folder(ev.destination);
        }
        if (native()) native().notify("Yoink", "All downloads complete.");
      }
      es.close();
      return;
    }
    if (ev.status === "error") {
      setStatus(`Error: ${ev.error}`, true);
      if (!isRetry) endRun("error");
      es.close();
      return;
    }

    if (ev.status === "video_error") {
      const card = ev.video_id && document.querySelector(`.card[data-id="${ev.video_id}"]`);
      if (card) {
        card.classList.remove("downloading");
        const isCancel = (ev.error || "").toLowerCase().includes("cancel");
        card.classList.add(isCancel ? "cancelled" : "error");
        const pct = card.querySelector(".card-pct");
        const sp = card.querySelector(".card-speed");
        if (pct) pct.textContent = isCancel ? "cancelled" : "failed";
        if (sp) sp.textContent = isCancel ? "" : (ev.error || "").slice(0, 60);
      }
      return;
    }

    const card = ev.video_id && document.querySelector(`.card[data-id="${ev.video_id}"]`);
    if (!card) return;
    const progressBox = card.querySelector(".card-progress");
    const pctEl = card.querySelector(".card-pct");
    const speedEl = card.querySelector(".card-speed");
    const segs = card.querySelectorAll(".vu span");

    progressBox.classList.remove("hidden");

    if (ev.status === "downloading" && ev.total_bytes) {
      const p = (ev.downloaded_bytes / ev.total_bytes) * 100;
      const lit = Math.round((p / 100) * segs.length);
      segs.forEach((s, i) => s.classList.toggle("lit", i < lit));
      pctEl.textContent = `${p.toFixed(0)}%`;
      const speed = ev.speed ? `${(ev.speed / 1e6).toFixed(1)} MB/s` : "";
      const eta = ev.eta ? `${ev.eta}s` : "";
      speedEl.textContent = [speed, eta].filter(Boolean).join(" · ");
    } else if (ev.status === "finished") {
      segs.forEach(s => s.classList.add("lit"));
      pctEl.textContent = "✓ done";
      speedEl.textContent = "";
      card.classList.remove("downloading", "error", "cancelled");
      card.classList.add("done");
      // Stash the resulting file path on the video so the per-card Open
      // button and the right-click menu can use it.
      const v = videos.find(x => x.id === ev.video_id);
      if (v) {
        if (ev.filename) v.filepath = ev.filename;
        if (ev.video_title) v.title = ev.video_title;
      }
    }
  };
  es.onerror = () => { es.close(); };
}

/* ---- Status banner ---- */
function setStatus(msg, isError = false) {
  const el = $("#status");
  el.textContent = msg;
  el.classList.remove("hidden", "error");
  if (isError) el.classList.add("error");
}
function hideStatus() { $("#status").classList.add("hidden"); }

function formatDuration(s) {
  s = Math.floor(s);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  return h
    ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`
    : `${m}:${String(sec).padStart(2, "0")}`;
}
function escapeHtml(s) {
  return s.replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}
