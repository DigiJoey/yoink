"""Generate Yoink logo images (icon + wordmark).

Outputs:
    docs/logo-light.png  (dark text, for light backgrounds)
    docs/logo-dark.png   (white text, for dark backgrounds)

Run:
    .venv\\Scripts\\python.exe make_logo.py

The font is Mona Sans Black, fetched directly from Google Fonts. The trick is
to send an old User-Agent string with the CSS request; Google then serves a
TTF URL instead of woff2, and PIL can read TTF directly.
"""
import re
import urllib.request
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

ROOT = Path(__file__).parent
OUT_DIR = ROOT / "docs"
OUT_DIR.mkdir(exist_ok=True)
FONT_CACHE = ROOT / ".font-cache" / "MonaSans-Black.ttf"

# Hi-res canvas
W, H = 1600, 480

GF_CSS_URL = "https://fonts.googleapis.com/css?family=Mona+Sans:900&display=swap"
# Old IE user agent → Google Fonts serves a TTF URL instead of woff2
OLD_UA = "Mozilla/4.0 (compatible; MSIE 6.0; Windows NT 5.1)"


def _format_from_bytes(data: bytes) -> str:
    if data[:4] == b"\x00\x01\x00\x00" or data[:4] == b"true":
        return "ttf"
    if data[:4] == b"OTTO":
        return "otf"
    if data[:4] == b"wOFF":
        return "woff"
    if data[:4] == b"wOF2":
        return "woff2"
    return "?"


def fetch_mona_sans() -> Path | None:
    if FONT_CACHE.exists() and FONT_CACHE.stat().st_size > 50000:
        return FONT_CACHE

    # Try a series of UAs from oldest to newest. Google Fonts picks the format
    # the requester can handle. IE6 only supports TTF/EOT, so it gets TTF.
    uas = [
        ("IE6 Win XP", "Mozilla/4.0 (compatible; MSIE 6.0; Windows NT 5.1)"),
        ("Old Safari", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_5_8) AppleWebKit/531.21.10"),
        ("Old Firefox", "Mozilla/5.0 (Windows NT 5.1; rv:8.0) Gecko/20100101 Firefox/8.0"),
    ]

    for label, ua in uas:
        try:
            print(f"Fetching Google Fonts CSS as {label}")
            req = urllib.request.Request(GF_CSS_URL, headers={"User-Agent": ua})
            with urllib.request.urlopen(req, timeout=20) as r:
                css = r.read().decode("utf-8")
            m = re.search(r"src:\s*url\(([^)]+)\)", css)
            if not m:
                continue
            font_url = m.group(1)
            req2 = urllib.request.Request(font_url, headers={"User-Agent": ua})
            with urllib.request.urlopen(req2, timeout=60) as r:
                data = r.read()
            fmt = _format_from_bytes(data)
            print(f"Got {len(data)} bytes, format={fmt}")
            if fmt in ("ttf", "otf"):
                FONT_CACHE.parent.mkdir(parents=True, exist_ok=True)
                FONT_CACHE.write_bytes(data)
                print(f"Saved {FONT_CACHE}")
                return FONT_CACHE
            if fmt == "woff2":
                # WOFF2 is brotli-compressed TTF/OTF. Try to decode it if the
                # `brotli` library is available.
                try:
                    import brotli  # type: ignore
                except ImportError:
                    print("WOFF2 received but brotli not installed. Try: pip install brotli")
                    continue
                # WOFF2 has its own header; decode requires fonttools too.
                try:
                    from fontTools.ttLib import TTFont  # type: ignore
                    from io import BytesIO
                    buf = BytesIO(data)
                    f = TTFont(buf)
                    out_buf = BytesIO()
                    f.flavor = None
                    f.save(out_buf)
                    FONT_CACHE.parent.mkdir(parents=True, exist_ok=True)
                    FONT_CACHE.write_bytes(out_buf.getvalue())
                    print(f"Decoded WOFF2 to {FONT_CACHE}")
                    return FONT_CACHE
                except ImportError:
                    print("WOFF2 received but fonttools not installed. Try: pip install fonttools brotli")
                    continue
        except Exception as e:
            print(f"  {label} failed: {e}")
            continue
    return None


def get_font(size: int) -> ImageFont.FreeTypeFont:
    f = fetch_mona_sans()
    if f and f.exists():
        try:
            return ImageFont.truetype(str(f), size)
        except Exception as e:
            print(f"Could not load Mona Sans ({e})")
    for sys_font in ("ariblk.ttf", "arialbd.ttf", "impact.ttf"):
        p = Path("C:/Windows/Fonts") / sys_font
        if p.exists():
            print(f"Falling back to {p}")
            return ImageFont.truetype(str(p), size)
    return ImageFont.load_default()


def _interp(stops, t):
    """Linear interpolate between (offset, (r,g,b)) stops at parameter t in [0,1]."""
    for i in range(len(stops) - 1):
        t1, c1 = stops[i]
        t2, c2 = stops[i + 1]
        if t <= t2:
            f = (t - t1) / (t2 - t1) if t2 > t1 else 0.0
            return (
                int(c1[0] + (c2[0] - c1[0]) * f),
                int(c1[1] + (c2[1] - c1[1]) * f),
                int(c1[2] + (c2[2] - c1[2]) * f),
            )
    return stops[-1][1]


def _clip_alpha(img: Image.Image, mask: Image.Image) -> Image.Image:
    """Multiply the image's alpha channel by mask. Both must be the same size."""
    r, g, b, a = img.split()
    a = ImageChops.multiply(a, mask)
    return Image.merge("RGBA", (r, g, b, a))


def draw_icon(canvas: Image.Image, x: int, y: int, w: int, h: int):
    """Render the icon exactly like the in-app SVG: vertical red gradient with
    a soft top sheen, plus a white play-down triangle."""
    radius = int(w * 0.16)

    # 1. Three-stop vertical gradient red, drawn line by line.
    stops = [
        (0.00, (0xFF, 0x2A, 0x2F)),
        (0.55, (0xE6, 0x00, 0x08)),
        (1.00, (0xB4, 0x00, 0x00)),
    ]
    grad = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    for py in range(h):
        col = _interp(stops, py / max(h - 1, 1))
        gd.line([(0, py), (w, py)], fill=col + (255,))

    # 2. Mask the gradient to the rounded-rect outline.
    rect_mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(rect_mask).rounded_rectangle(
        (0, 0, w, h), radius=radius, fill=255
    )
    grad = _clip_alpha(grad, rect_mask)

    # 3. Top sheen: a smaller rounded rect filled with white that fades from
    #    ~22% alpha at top to 0 at bottom. Inset by a few pixels so the
    #    rounded edges read as a separate highlighted lip.
    pad = max(2, int(w * 0.028))
    sheen_h = int(h * 0.24)
    sheen_full = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sheen_full)
    for py in range(sheen_h):
        a = int(56 * (1 - py / max(sheen_h - 1, 1)))  # 56 ≈ 0.22*255
        sd.line(
            [(pad, pad + py), (w - pad, pad + py)],
            fill=(255, 255, 255, a),
        )
    sheen_mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(sheen_mask).rounded_rectangle(
        (pad, pad, w - pad, pad + sheen_h),
        radius=int(w * 0.13),
        fill=255,
    )
    sheen_full = _clip_alpha(sheen_full, sheen_mask)

    # 4. Composite gradient + sheen + triangle.
    layer = Image.alpha_composite(grad, sheen_full)
    cx = w / 2
    cy = h / 2
    tw = w * 0.18
    th = h * 0.42
    ImageDraw.Draw(layer).polygon(
        [(cx - tw, cy - th / 2), (cx + tw, cy - th / 2), (cx, cy + th / 2)],
        fill=(255, 255, 255, 255),
    )
    canvas.paste(layer, (x, y), layer)


def render(text_color: tuple, out_path: Path):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Font sized so cap-height roughly matches icon height
    font_size = 320
    font = get_font(font_size)

    # Use the actual rendered bbox for "Yoink" to align icon to the cap-height
    text = "Yoink"
    bbox = d.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    # Icon size: match the rendered cap-height of the wordmark (visually balanced)
    icon_h = text_h
    icon_w = int(icon_h * 4 / 3)  # 4:3 aspect, like app.ico
    icon_x = 80
    icon_y = (H - icon_h) // 2

    draw_icon(img, icon_x, icon_y, icon_w, icon_h)

    # Place the text so its rendered bbox vertically centres on the icon
    gap = int(icon_h * 0.22)
    text_x = icon_x + icon_w + gap
    # bbox[1] is the offset from the drawing y to the visible top of the text;
    # subtract it so the visible top of the text aligns with icon_y.
    text_y = icon_y - bbox[1]
    d.text((text_x, text_y), text, font=font, fill=text_color)

    # Trim trailing transparent space on the right for a tight bounding box,
    # keeping symmetric left/right padding equal to icon_x.
    visible = img.getbbox()
    if visible:
        right = min(visible[2] + icon_x, W)
        img = img.crop((0, 0, right, H))

    img.save(out_path)
    print(f"Wrote {out_path}  ({img.size[0]}x{img.size[1]})")


def main():
    render((15, 15, 15, 255), OUT_DIR / "logo-light.png")
    render((255, 255, 255, 255), OUT_DIR / "logo-dark.png")


if __name__ == "__main__":
    main()
