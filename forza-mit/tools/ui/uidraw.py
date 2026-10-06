"""Small raster toolkit shared by make_ui_assets.py and make_mockups.py.

Everything is drawn with signed-distance shapes in float RGBA (premultiplied), so any brush can be
re-rendered at any scale (1x for Slate box brushes, 2x for image brushes) with clean anti-aliasing.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[2]
FONTS = ROOT / "CambridgeRacer" / "UI" / "Fonts"
GENERATED = ROOT / "CambridgeRacer" / "UI" / "Generated"


# ------------------------------------------------------------------ colours

def hexc(s: str, a: float = 1.0) -> tuple[float, float, float, float]:
    s = s.lstrip("#")
    return (int(s[0:2], 16) / 255, int(s[2:4], 16) / 255, int(s[4:6], 16) / 255, a)


def mix(c1, c2, t: float):
    return tuple(c1[i] * (1 - t) + c2[i] * t for i in range(4))


def scale_rgb(c, k: float):
    return (min(1.0, c[0] * k), min(1.0, c[1] * k), min(1.0, c[2] * k), c[3])


# ------------------------------------------------------------------ fields

def _grid(w: int, h: int):
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    return xs + 0.5, ys + 0.5


def rrect_sdf(w: int, h: int, box, radii) -> np.ndarray:
    """Signed distance (pixels) to a rounded rectangle box=(x0,y0,x1,y1), radii=(tl,tr,br,bl) or float."""
    if np.isscalar(radii):
        radii = (radii,) * 4
    x, y = _grid(w, h)
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    hx, hy = (x1 - x0) / 2, (y1 - y0) / 2
    px, py = x - cx, y - cy
    tl, tr, br, bl = radii
    r = np.where(px < 0, np.where(py < 0, tl, bl), np.where(py < 0, tr, br)).astype(np.float32)
    r = np.minimum(r, min(hx, hy))
    qx = np.abs(px) - hx + r
    qy = np.abs(py) - hy + r
    outside = np.sqrt(np.maximum(qx, 0) ** 2 + np.maximum(qy, 0) ** 2)
    inside = np.minimum(np.maximum(qx, qy), 0)
    return outside + inside - r


def cov(sdf: np.ndarray) -> np.ndarray:
    return np.clip(0.5 - sdf, 0.0, 1.0)


def circle_sdf(w: int, h: int, cx: float, cy: float, r: float) -> np.ndarray:
    x, y = _grid(w, h)
    return np.sqrt((x - cx) ** 2 + (y - cy) ** 2) - r


def polygon_cov(w: int, h: int, pts, ss: int = 4) -> np.ndarray:
    """Anti-aliased polygon coverage by supersampling."""
    im = Image.new("L", (w * ss, h * ss), 0)
    ImageDraw.Draw(im).polygon([(x * ss, y * ss) for x, y in pts], fill=255)
    im = im.resize((w, h), Image.Resampling.BOX)
    return np.asarray(im, dtype=np.float32) / 255.0


def vgrad(w: int, h: int, stops, y0: float = 0.0, y1: float | None = None) -> np.ndarray:
    """Vertical gradient (HxWx4, straight alpha). stops = [(t, rgba), ...] with t in 0..1 over [y0, y1]."""
    y1 = h if y1 is None else y1
    _, y = _grid(w, h)
    t = np.clip((y - y0) / max(1e-6, (y1 - y0)), 0, 1)
    return _ramp(t, stops)


def hgrad(w: int, h: int, stops, x0: float = 0.0, x1: float | None = None) -> np.ndarray:
    x1 = w if x1 is None else x1
    x, _ = _grid(w, h)
    t = np.clip((x - x0) / max(1e-6, (x1 - x0)), 0, 1)
    return _ramp(t, stops)


def radial(w: int, h: int, cx: float, cy: float, r: float, stops) -> np.ndarray:
    x, y = _grid(w, h)
    t = np.clip(np.sqrt((x - cx) ** 2 + (y - cy) ** 2) / r, 0, 1)
    return _ramp(t, stops)


def _ramp(t: np.ndarray, stops) -> np.ndarray:
    ts = np.array([s[0] for s in stops], dtype=np.float32)
    cs = np.array([s[1] for s in stops], dtype=np.float32)
    out = np.empty(t.shape + (4,), dtype=np.float32)
    for c in range(4):
        out[..., c] = np.interp(t, ts, cs[:, c])
    return out


# ------------------------------------------------------------------ canvas

class Canvas:
    """Premultiplied float RGBA canvas."""

    def __init__(self, w: int, h: int):
        self.w, self.h = w, h
        self.px = np.zeros((h, w, 4), dtype=np.float32)

    def paint(self, colour, coverage: np.ndarray | float = 1.0) -> "Canvas":
        """Alpha-over a colour (rgba tuple) or a straight-alpha HxWx4 array through a coverage mask."""
        if isinstance(colour, np.ndarray):
            src = colour.astype(np.float32).copy()
        else:
            src = np.empty((self.h, self.w, 4), dtype=np.float32)
            src[...] = colour
        a = src[..., 3] * coverage
        src_p = src[..., :3] * a[..., None]
        self.px[..., :3] = src_p + self.px[..., :3] * (1 - a[..., None])
        self.px[..., 3] = a + self.px[..., 3] * (1 - a)
        return self

    def erase(self, coverage: np.ndarray) -> "Canvas":
        self.px *= (1 - coverage)[..., None]
        return self

    def image(self) -> Image.Image:
        a = self.px[..., 3:4]
        rgb = np.where(a > 1e-6, self.px[..., :3] / np.maximum(a, 1e-6), 0)
        out = np.concatenate([rgb, a], axis=-1)
        return Image.fromarray((np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8), "RGBA")

    def paste(self, im: Image.Image, x: int, y: int) -> "Canvas":
        layer = Image.new("RGBA", (self.w, self.h), (0, 0, 0, 0))
        layer.alpha_composite(im, (x, y)) if 0 <= x and 0 <= y else layer.paste(im, (x, y), im)
        arr = np.asarray(layer, dtype=np.float32) / 255.0
        return self.paint(arr, 1.0)


def blur_cov(c: np.ndarray, radius: float) -> np.ndarray:
    im = Image.fromarray((np.clip(c, 0, 1) * 255).astype(np.uint8), "L").filter(ImageFilter.GaussianBlur(radius))
    return np.asarray(im, dtype=np.float32) / 255.0


# ------------------------------------------------------------------ pixel art

def pixel_art(rows: list[str], palette: dict[str, tuple], cell: int) -> Image.Image:
    """rows of characters -> RGBA image, each character a cell x cell block ('.' = transparent)."""
    h, w = len(rows), max(len(r) for r in rows)
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch in palette:
                c = palette[ch]
                im.putpixel((x, y), tuple(int(v * 255 + 0.5) for v in c))
    return im.resize((w * cell, h * cell), Image.Resampling.NEAREST)


# ------------------------------------------------------------------ 9-slice (what Slate does with a Box brush)

def nine_slice(im: Image.Image, margins_px, w: int, h: int) -> Image.Image:
    """Stretch a box brush like Slate: corners keep texel size, edges stretch along one axis, centre both."""
    l, t, r, b = margins_px
    W, H = im.size
    w, h = max(1, int(round(w))), max(1, int(round(h)))
    # clamp margins when the target is smaller than the corners (Slate halves them)
    if l + r > w:
        l = r = w // 2
    if t + b > h:
        t = b = h // 2
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    xs_src = [0, l, W - r, W]
    ys_src = [0, t, H - b, H]
    xs_dst = [0, l, w - r, w]
    ys_dst = [0, t, h - b, h]
    for i in range(3):
        for j in range(3):
            sx0, sx1 = xs_src[i], xs_src[i + 1]
            sy0, sy1 = ys_src[j], ys_src[j + 1]
            dx0, dx1 = xs_dst[i], xs_dst[i + 1]
            dy0, dy1 = ys_dst[j], ys_dst[j + 1]
            if sx1 <= sx0 or sy1 <= sy0 or dx1 <= dx0 or dy1 <= dy0:
                continue
            piece = im.crop((sx0, sy0, sx1, sy1)).resize((dx1 - dx0, dy1 - dy0), Image.Resampling.BILINEAR)
            out.paste(piece, (dx0, dy0))
    return out


# ------------------------------------------------------------------ fonts

_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def font(name: str, px: float) -> ImageFont.FreeTypeFont:
    key = (name, int(round(px)))
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(str(FONTS / name), key[1])
    return _font_cache[key]


PIXEL_DIGIT_SCALE = 0.75   # Press Start 2P digits inside the Silkscreen "Pixel" composite (C++ ScalingFactor)


def _pixel_runs(text: str, px: float, bold: bool):
    letters = font("Silkscreen-Bold.ttf" if bold else "Silkscreen-Regular.ttf", px)
    digits = font("PressStart2P-Regular.ttf", px * PIXEL_DIGIT_SCALE)
    for ch in text:
        yield ch, (digits if ch.isdigit() else letters)


def text_width(text: str, family: str, px: float, bold: bool = False, tracking: float = 0.0) -> float:
    if family == "pixel":
        return sum(f.getlength(ch) + tracking for ch, f in _pixel_runs(text, px, bold)) - (tracking if text else 0)
    f = font(_family_file(family, bold), px)
    return f.getlength(text) + tracking * max(0, len(text) - 1)


def _family_file(family: str, bold: bool) -> str:
    return {
        "pixel": "Silkscreen-Bold.ttf" if bold else "Silkscreen-Regular.ttf",
        "digits": "PressStart2P-Regular.ttf",
        "dots": "Doto-Black.ttf" if bold else "Doto-Bold.ttf",
        "body": "OpenSans-Bold.ttf" if bold else "OpenSans-Regular.ttf",
        "cond": "OpenSansCondensed-Bold.ttf",
    }[family]


def draw_text(img: Image.Image, xy, text: str, family: str, px: float, fill, bold: bool = False,
              anchor: str = "ls", shadow=None, shadow_offset=(1, 1), outline: int = 0, outline_fill=None,
              tracking: float = 0.0):
    """Draw text with its baseline at xy (anchor 'ls' / 'ms' / 'rs' = left / middle / right on baseline).

    family 'pixel' = the Silkscreen + Press Start 2P digits composite, like the C++ "Pixel" font.
    """
    x, y = xy
    wdt = text_width(text, family, px, bold, tracking)
    if anchor[0] == "m":
        x -= wdt / 2
    elif anchor[0] == "r":
        x -= wdt
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))   # draw on a layer, then composite (ImageDraw does not blend alpha)
    d = ImageDraw.Draw(layer)
    to8 = lambda c: tuple(int(v * 255 + 0.5) for v in c) if isinstance(c[0], float) else c

    def runs():
        if family == "pixel":
            cx = x
            for ch, f in _pixel_runs(text, px, bold):
                yield cx, ch, f
                cx += f.getlength(ch) + tracking
        elif tracking:
            f = font(_family_file(family, bold), px)
            cx = x
            for ch in text:
                yield cx, ch, f
                cx += f.getlength(ch) + tracking
        else:
            yield x, text, font(_family_file(family, bold), px)

    passes = []
    if shadow is not None:
        passes.append((shadow_offset, shadow, outline, shadow))
    passes.append(((0, 0), fill, outline, outline_fill))
    for (ox, oy), col, ow, ocol in passes:
        for cx, s, f in runs():
            kw = {}
            if ow:
                kw = dict(stroke_width=ow, stroke_fill=to8(ocol) if ocol is not None else to8(col))
            d.text((cx + ox, y + oy), s, font=f, fill=to8(col), anchor="ls", **kw)
    img.alpha_composite(layer)
    return wdt
