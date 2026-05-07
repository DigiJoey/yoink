"""Generate app.ico (multi-size Windows icon). Run once."""
from pathlib import Path
from PIL import Image, ImageDraw


def make(size: int) -> Image.Image:
    s = size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # YouTube-style rounded red rectangle (centered, 7:5 aspect inside canvas)
    rw = s * 0.86
    rh = s * 0.62
    rx = (s - rw) / 2
    ry = (s - rh) / 2

    # Vertical gradient simulated with horizontal bands (top: brighter, bottom: deeper)
    # Falls back to a single fill at very small sizes where bands disappear
    if s >= 32:
        bands = max(8, int(rh / 2))
        from PIL import ImageDraw as _D
        for i in range(bands):
            t = i / max(bands - 1, 1)
            r = int(round(255 * (1 - 0.28 * t)))   # 255 -> ~184
            g = int(round(40 * (1 - t)))            # 40 -> 0
            b = int(round(45 * (1 - t)))            # 45 -> 0
            band_top = ry + (rh / bands) * i
            band_bot = ry + (rh / bands) * (i + 1) + 0.5
            d.rectangle((rx, band_top, rx + rw, band_bot), fill=(r, g, b, 255))
        # Re-apply rounded mask by drawing rounded rect outline + masking
        # Simpler: draw rounded rect on top with no fill is not possible; instead,
        # we redraw the rect with the gradient embedded by using a mask.
        mask = Image.new("L", (s, s), 0)
        md = ImageDraw.Draw(mask)
        md.rounded_rectangle(
            (rx, ry, rx + rw, ry + rh),
            radius=max(2, int(s * 0.16)),
            fill=255,
        )
        # Composite: keep gradient pixels only where mask is set
        out = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        out.paste(img, (0, 0), mask)
        img = out
        d = ImageDraw.Draw(img)
    else:
        # Tiny sizes: flat YouTube red
        d.rounded_rectangle(
            (rx, ry, rx + rw, ry + rh),
            radius=max(2, int(s * 0.16)),
            fill=(228, 0, 0, 255),
        )

    # White triangle pointing down ("download"), centered on the rect
    cx = s / 2
    cy = s / 2
    tw = s * 0.135   # half-width of base
    th = s * 0.21    # height
    d.polygon(
        [
            (cx - tw, cy - th / 2),
            (cx + tw, cy - th / 2),
            (cx, cy + th / 2),
        ],
        fill=(255, 255, 255, 255),
    )
    return img


def main():
    sizes = [256, 128, 64, 48, 32, 24, 16]
    imgs = [make(s) for s in sizes]
    out = Path(__file__).parent / "app.ico"
    imgs[0].save(
        out,
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=imgs[1:],
    )
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
