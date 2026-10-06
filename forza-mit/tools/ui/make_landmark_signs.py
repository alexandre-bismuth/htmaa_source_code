"""Floating landmark signs (8-bit, "Luna Glass"): one panel + one bouncing arrow + one light pillar per landmark.

    cd tools/ui && uv run make_landmark_signs.py        # after tools/minimap/landmarks.py (reads its json)

Reads  CambridgeRacer/Tracks/<region>_landmarks.json   (label, subtitle, icon, accent per landmark)
Writes CambridgeRacer/UI/Generated/landmark_<id>_panel.png   256x64 art px x K: icon block + pixel title on glass
       CambridgeRacer/UI/Generated/landmark_<id>_arrow.png   64x64 art px x K: chunky down arrow (2x2-px cells)
       CambridgeRacer/UI/Generated/landmark_<id>_beam.png    soft light pillar (not pixel art)
       CambridgeRacer/UI/Generated/landmark_signs.json       layout for the game (ALandmarkActor)
       tools/ui/mockups/landmark_signs.png                    preview on a game screenshot

The art is drawn at 1 texel per "art pixel" with the pixel fonts at their native size (Press Start 2P 8 px,
Silkscreen 8 px) and no anti-aliasing, then scaled up K x nearest-neighbour, so the game's mipmapped
trilinear sampling keeps hard pixel edges. The glow halo is added after the upscale (smooth). PNGs are straight
alpha: the material uses rgb as emissive and a as opacity.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from landmark_art import hex_rgba, icon_image, nearest, outline, shade
from uidraw import FONTS, GENERATED

ROOT = Path(__file__).resolve().parents[2]
TRACKS = ROOT / "CambridgeRacer" / "Tracks"
MOCKUPS = Path(__file__).resolve().parent / "mockups"

K = 4                      # texels per art pixel
M_PER_ART_PX = 0.12        # world size of one art pixel at scale 1 (ALandmarkActor scales with distance)
PANEL_CANVAS = (256, 64)
ARROW_CANVAS = (64, 64)
BEAM_SIZE = (32, 256)

INK = (8, 10, 16, 255)                   # outline
GLASS = (18, 20, 24)                     # Glass.Fill #121418
WHITE = (255, 255, 255, 255)


def text_mask(text: str, font_file: str, size: int) -> np.ndarray:
    """Binary (no AA) mask of text in a pixel font at its native size, cropped to the ink."""
    from PIL import ImageFont
    f = ImageFont.truetype(str(FONTS / font_file), size)
    l, t, r, b = f.getbbox(text)
    im = Image.new("L", (r - l + 2, b - t + 2), 0)
    ImageDraw.Draw(im).text((-l + 1, -t + 1), text, font=f, fill=255)
    a = np.asarray(im) > 110
    ys, xs = np.nonzero(a)
    return a[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def put_mask(px: np.ndarray, mask: np.ndarray, x: int, y: int, col):
    h, w = mask.shape
    px[y:y + h, x:x + w][mask] = col


def glow(img: Image.Image, accent, radius: float, strength: float) -> Image.Image:
    """Soft accent halo behind img (both at texel resolution)."""
    a = img.getchannel("A").filter(ImageFilter.GaussianBlur(radius))
    arr = np.asarray(a, dtype=np.float32) / 255.0 * strength
    halo = np.zeros(arr.shape + (4,), np.uint8)
    halo[..., 0], halo[..., 1], halo[..., 2] = accent[:3]
    halo[..., 3] = np.clip(arr * 255, 0, 255).astype(np.uint8)
    out = Image.fromarray(halo, "RGBA")
    out.alpha_composite(img)
    return out


def panel(lm) -> tuple[Image.Image, dict]:
    accent = hex_rgba(lm["accent"])
    title = text_mask(lm["label"], "PressStart2P-Regular.ttf", 8)
    sub = text_mask(lm["subtitle"], "Silkscreen-Regular.ttf", 8)
    block_w, h = 26, 28
    pad_l, pad_r = 6, 7
    w = block_w + pad_l + max(title.shape[1], sub.shape[1]) + pad_r
    W, H = PANEL_CANVAS
    x0 = (W - (w + 2)) // 2
    y0 = 14                                   # outline top; the tail hangs below
    px = np.zeros((H, W, 4), np.uint8)

    # glass body with a 1-px light top edge and a slightly darker bottom band
    gx0, gx1 = x0 + 1 + block_w, x0 + 1 + w
    for y in range(y0 + 1, y0 + 1 + h):
        t = (y - y0 - 1) / (h - 1)
        k = 1.0 if t < 0.72 else 0.82
        px[y, gx0:gx1] = (*[int(c * k) for c in GLASS], 235)
    px[y0 + 1, gx0:gx1] = (92, 98, 110, 245)
    px[y0 + 2, gx0:gx1] = (40, 44, 52, 240)

    # icon block: banded accent gradient (XP title-bar gloss: light top, deep bottom), 1-px highlight / shadow
    bands = [1.45, 1.32, 1.18, 1.0, 1.0, 0.92, 0.86, 0.80, 0.74, 0.68]
    for y in range(y0 + 1, y0 + 1 + h):
        i = min(len(bands) - 1, (y - y0 - 1) * len(bands) // h)
        px[y, x0 + 1:gx0] = shade(accent, bands[i])
    px[y0 + 1, x0 + 1:gx0] = shade(accent, 1.7)
    px[y0 + 1:y0 + 1 + h, x0 + 1] = shade(accent, 1.55)
    px[y0 + 1:y0 + 1 + h, gx0 - 1] = shade(accent, 0.5)

    icon = np.asarray(icon_image(lm["icon"], lm["accent"]))
    ix, iy = x0 + 1 + (block_w - icon.shape[1]) // 2, y0 + 1 + (h - icon.shape[0]) // 2
    m = icon[..., 3] > 0
    px[iy:iy + icon.shape[0], ix:ix + icon.shape[1]][m] = icon[m]

    # title (white, accent-dark 1-px drop shadow) and subtitle (light accent)
    tx, ty = gx0 + pad_l, y0 + 1 + 5
    sh = np.zeros((title.shape[0] + 1, title.shape[1] + 1), bool)
    sh[1:, 1:] = title
    put_mask(px, sh, tx, ty, (*shade(accent, 0.35)[:3], 255))
    put_mask(px, title, tx, ty, WHITE)
    sy = ty + title.shape[0] + 5
    put_mask(px, sub, tx, sy, shade(accent, 1.45))
    # a pixel underline between title and subtitle, accent, fading out in 2-px steps
    uy = ty + title.shape[0] + 2
    for i, x in enumerate(range(tx, tx + title.shape[1])):
        if (x - tx) % 2 == 0 or (x - tx) < title.shape[1] * 0.5:
            px[uy, x] = (*accent[:3], 200 if (x - tx) < title.shape[1] * 0.5 else 110)

    # tail (pointer) under the middle, glass coloured
    cx = x0 + 1 + w // 2
    tail_rows = 5
    for r in range(tail_rows):
        half = tail_rows - 1 - r
        px[y0 + 1 + h + r, cx - half:cx + half + 1] = (*[int(c * 0.82) for c in GLASS], 235)

    # outline with 1-px notched (pixel-rounded) corners
    img = Image.fromarray(px, "RGBA")
    a = px[..., 3] > 0
    for (cx_, cy_) in [(x0 + 1, y0 + 1), (gx1 - 1, y0 + 1), (x0 + 1, y0 + h), (gx1 - 1, y0 + h)]:
        a[cy_, cx_] = False
        px[cy_, cx_] = 0
    img = outline(Image.fromarray(px, "RGBA"), INK, diagonal=False)
    tail_tip = y0 + 1 + h + tail_rows        # first row below the tail's last pixel (outline row)

    big = nearest(img, K)
    big = glow(big, shade(accent, 1.15), radius=3.2 * K, strength=0.85)
    meta = {"file": f"landmark_{lm['id']}_panel.png", "canvas": [W, H], "box": [x0, y0, x0 + w + 2, y0 + h + 2],
            "tail_y": tail_tip + 1}
    return big, meta


ARROW = [
    "....AAAAA....",
    "....AAAAA....",
    "....AAAAA....",
    "....AAAAA....",
    "AAAAAAAAAAAAA",
    ".AAAAAAAAAAA.",
    "..AAAAAAAAA..",
    "...AAAAAAA...",
    "....AAAAA....",
    ".....AAA.....",
    "......A......",
]


def arrow(lm) -> tuple[Image.Image, dict]:
    accent = hex_rgba(lm["accent"])
    hi, lo, glint = shade(accent, 1.5), shade(accent, 0.62), WHITE
    rows = len(ARROW)
    cols = len(ARROW[0])
    cell = np.zeros((rows, cols, 4), np.uint8)
    for y, row in enumerate(ARROW):
        xs = [x for x, ch in enumerate(row) if ch == "A"]
        for x in xs:
            col = accent
            if x == xs[0] or (y >= 4 and x == xs[0] + 1 and len(xs) > 6):
                col = hi
            if x == xs[-1] or (y >= 4 and x == xs[-1] - 1 and len(xs) > 6):
                col = lo
            cell[y, x] = col
    cell[0, 5] = glint
    cell[1, 5] = glint
    cell[5, 2] = shade(accent, 1.7)
    img = Image.fromarray(cell, "RGBA").resize((cols * 3, rows * 3), Image.Resampling.NEAREST)
    padded = Image.new("RGBA", (img.width + 2, img.height + 2), (0, 0, 0, 0))
    padded.alpha_composite(img, (1, 1))
    img = outline(padded, INK, diagonal=True)
    W, H = ARROW_CANVAS
    can = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ox, oy = (W - img.width) // 2, (H - img.height) // 2
    can.alpha_composite(img, (ox, oy))
    big = glow(nearest(can, K), shade(accent, 1.2), radius=3.0 * K, strength=1.0)
    meta = {"file": f"landmark_{lm['id']}_arrow.png", "canvas": [W, H], "top_y": oy, "tip_y": oy + img.height}
    return big, meta


def beam(lm) -> tuple[Image.Image, dict]:
    accent = hex_rgba(lm["accent"])
    w, h = BEAM_SIZE
    x = (np.arange(w) + 0.5 - w / 2)[None, :]
    y = ((np.arange(h) + 0.5) / h)[:, None]           # 0 = top (at the arrow), 1 = ground
    core = np.exp(-(x / 1.6) ** 2) * 0.75 + np.exp(-(x / 6.0) ** 2) * 0.35
    vert = np.clip(y / 0.25, 0, 1) ** 1.5 * np.clip((1 - y) / 0.04, 0, 1) * (0.55 + 0.45 * y)
    a = np.clip(core * vert, 0, 1)
    col = np.array(shade(accent, 1.25)[:3], np.float32)
    whiteness = np.clip(np.exp(-(x / 1.0) ** 2), 0, 1)[..., None]
    rgb = col * (1 - whiteness * 0.6) + 255 * whiteness * 0.6
    out = np.zeros((h, w, 4), np.uint8)
    out[..., :3] = np.broadcast_to(rgb, (h, w, 3)).astype(np.uint8)
    out[..., 3] = (a * 255).astype(np.uint8)
    return Image.fromarray(out, "RGBA"), {"file": f"landmark_{lm['id']}_beam.png", "size": [w, h]}


def preview(signs):
    bg_dir = MOCKUPS / "bg"
    bgs = sorted(bg_dir.glob("*.png")) if bg_dir.is_dir() else []
    bg = Image.open(bgs[0]).convert("RGBA").resize((1280, 720)) if bgs else Image.new("RGBA", (1280, 720), (90, 120, 160, 255))
    x = 120
    for panel_img, arrow_img, pm, am in signs:
        s = 0.5                                   # 2 screen px per art px at K = 4
        p = panel_img.resize((int(panel_img.width * s), int(panel_img.height * s)), Image.Resampling.BILINEAR)
        a = arrow_img.resize((int(arrow_img.width * s), int(arrow_img.height * s)), Image.Resampling.BILINEAR)
        bg.alpha_composite(p, (x, 120))
        ax = x + p.width // 2 - a.width // 2
        ay = 120 + int(pm["tail_y"] * K * s) - int(am["top_y"] * K * s) + 6
        bg.alpha_composite(a, (ax, ay))
        x += p.width + 40
    MOCKUPS.mkdir(exist_ok=True)
    bg.convert("RGB").save(MOCKUPS / "landmark_signs.png")


def main(region="mit_core"):
    doc = json.loads((TRACKS / f"{region}_landmarks.json").read_text())
    meta = {"k": K, "m_per_art_px": M_PER_ART_PX, "landmarks": {}}
    signs = []
    GENERATED.mkdir(parents=True, exist_ok=True)
    for lm in doc["landmarks"]:
        p_img, p_meta = panel(lm)
        a_img, a_meta = arrow(lm)
        b_img, b_meta = beam(lm)
        for im, m in [(p_img, p_meta), (a_img, a_meta), (b_img, b_meta)]:
            im.save(GENERATED / m["file"], optimize=True)
        meta["landmarks"][lm["id"]] = {"panel": p_meta, "arrow": a_meta, "beam": b_meta}
        signs.append((p_img, a_img, p_meta, a_meta))
        print(f"  {lm['id']}: panel {p_meta['box']}, arrow tip {a_meta['tip_y']}")
    (GENERATED / "landmark_signs.json").write_text(json.dumps(meta, indent=1))
    preview(signs)
    print(f"  landmark_signs.json + mockups/landmark_signs.png")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "mit_core")
