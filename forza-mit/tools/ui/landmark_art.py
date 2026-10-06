"""Pixel art shared by the landmark signs (tools/ui/make_landmark_signs.py) and the map tags
(tools/minimap/make_map.py): 16x16 icons as character grids, the accent palettes, and a 1-px outline helper.

Grids: 'W' = icon fill (white), 'S' = icon shade (light accent grey), 'A' = accent, '.' = empty. The dark outline is
added around the shape by outline(), so the grids only hold the silhouette.
"""
from __future__ import annotations

import numpy as np
from PIL import Image

# hammer (Architecture Shop): claw hammer at 45 degrees, claw top left, striking face right, handle to the bottom left
HAMMER = [
    ".......S........",
    "....W...S.......",
    ".....W.WWS......",
    "......WWWWS.....",
    ".......WWWWS....",
    "........WWWWWS..",
    ".......WSWWWWWS.",
    "......WS..WWWWW.",
    ".....WS...WWWW..",
    "....WS.....WW...",
    "...WS...........",
    "..WS............",
    ".WS.............",
    "WS..............",
    "................",
    "................",
]

# mortarboard (HTMAA Lectures): the board seen from slightly above, the cap under it, the tassel on the right
MORTARBOARD = [
    "................",
    "................",
    ".......WW.......",
    ".....WWWWWW.....",
    "...WWWWWWWWWW...",
    ".WWWWWWWAAAAAW..",
    "...WWWWWWWWWWA..",
    ".....SSWWSS..A..",
    "....WWSSSSWW.A..",
    "....WWWWWWWW.A..",
    "....WWWWWWWW.AA.",
    "....SWWWWWWS.AA.",
    ".....SSSSSS.....",
    "................",
    "................",
    "................",
]

ICONS = {"landmark_arch": HAMMER, "landmark_htmaa": MORTARBOARD}


def hex_rgba(s: str, a: float = 1.0):
    s = s.lstrip("#")
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16), int(round(a * 255)))


def shade(rgb, k: float):
    """Scale an (r, g, b[, a]) colour towards black (k < 1) or white (k > 1)."""
    r, g, b = rgb[:3]
    if k <= 1:
        out = (r * k, g * k, b * k)
    else:
        t = k - 1
        out = (r + (255 - r) * t, g + (255 - g) * t, b + (255 - b) * t)
    return tuple(int(max(0, min(255, round(v)))) for v in out) + tuple(rgb[3:4] or (255,))


def icon_image(name: str, accent_hex: str, fill=(255, 255, 255, 255), outline_col=(8, 10, 16, 255)) -> Image.Image:
    """The 16x16 icon at 1 px per cell, with a 1-px dark outline (18x18 image)."""
    rows = ICONS[name]
    accent = hex_rgba(accent_hex)
    pal = {"W": fill, "S": shade(accent, 1.72), "A": accent}
    h, w = len(rows), len(rows[0])
    cells = [(x, y) for y, row in enumerate(rows) for x, ch in enumerate(row) if ch in pal]
    x0, x1 = min(c[0] for c in cells), max(c[0] for c in cells)
    y0, y1 = min(c[1] for c in cells), max(c[1] for c in cells)
    ox, oy = (w - (x1 - x0 + 1)) // 2 - x0, (h - (y1 - y0 + 1)) // 2 - y0      # centre the drawing in the grid
    im = Image.new("RGBA", (w + 2, h + 2), (0, 0, 0, 0))
    for x, y in cells:
        im.putpixel((x + ox + 1, y + oy + 1), pal[rows[y][x]])
    return outline(im, outline_col)


def outline(im: Image.Image, col, diagonal: bool = False) -> Image.Image:
    """1-px outline in col around the opaque pixels (4-neighbourhood; 8 with diagonal)."""
    a = np.asarray(im)[..., 3] > 127
    grown = a.copy()
    shifts = [(0, 1), (0, -1), (1, 0), (-1, 0)] + ([(1, 1), (1, -1), (-1, 1), (-1, -1)] if diagonal else [])
    for dy, dx in shifts:
        grown |= np.roll(np.roll(a, dy, 0), dx, 1)
    ring = grown & ~a
    out = np.asarray(im).copy()
    out[ring] = col
    return Image.fromarray(out, "RGBA")


def nearest(im: Image.Image, k: int) -> Image.Image:
    return im.resize((im.width * k, im.height * k), Image.Resampling.NEAREST)
