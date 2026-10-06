"""Generate the Slate brushes for the "Luna Glass" UI (XP Luna chrome + modern dark glass).

    cd tools/ui && uv run make_ui_assets.py

Writes into CambridgeRacer/UI/Generated/ (PNGs are gitignored, rerun after a clean checkout):

  <name>.png          the texture the C++ style loads
  <name>@2x.png       box brushes only: a 2x copy for mockups / future hi-DPI work (not loaded by Slate)
  brushes.json        size, texture size, 9-slice margins (slate units and UV fractions) of every brush
and the C++ table tools/ui/staging/CambridgeUIBrushes.inl that CambridgeUIStyle.cpp #includes.

Texture density (important, see README):
  box   brushes are exported at 1x. Slate draws box corners at their *texel* size
        (ElementBatcher: corner = TextureWidth * Margin), so a 2x texture would draw 2x corners.
  image brushes are exported at 2x and registered with their 1x ImageSize, so they stay crisp
        on hi-DPI / 1440p+ viewports.
  tile  brushes (repeating strips) are 1x: Slate tiles them by texel size too.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image

from uidraw import (GENERATED, Canvas, blur_cov, circle_sdf, cov, font, hexc, mix, pixel_art, polygon_cov,
                    radial, rrect_sdf, scale_rgb, vgrad)

HERE = Path(__file__).resolve().parent
STAGING = HERE / "staging"

# ------------------------------------------------------------------ palette (also exported to C++)

C = {
    # Windows XP Luna
    "Luna.BlueLight": "#3d95ff",
    "Luna.Blue": "#0058ee",
    "Luna.BlueMid": "#0050e0",
    "Luna.BlueDark": "#0040c0",
    "Luna.Frame": "#0831d9",
    "Luna.Navy": "#0a246a",
    "Luna.Face": "#ece9d8",
    "Luna.FaceDark": "#aca899",
    "Luna.Content": "#fdfcf7",
    "Luna.ContentBorder": "#7f9db9",
    "Luna.Selection": "#316ac5",
    "Luna.GreenLight": "#5fd35f",
    "Luna.Green": "#3c9a3c",
    "Luna.GreenDark": "#2e8b2e",
    "Luna.RedLight": "#e8734f",
    "Luna.Red": "#c9391c",
    "Luna.RedDark": "#b02e12",
    "Luna.Focus": "#ffd54a",
    "Luna.Hover": "#f8b330",
    "Luna.TabOrange": "#e68b2c",
    "Luna.Balloon": "#ffffe1",
    "Luna.Text": "#000000",
    "Luna.TextDim": "#5a5a55",
    # modern glass (alexandre-bismuth.github.io: #2e2e33 / #1d1e20)
    "Glass.Fill": "#121418",
    "Glass.Text": "#f2f3f5",
    "Glass.TextDim": "#9ea3ad",
    "Glass.Line": "#ffffff",
    # race semantics
    "Race.Ahead": "#3ddc5a",
    "Race.Behind": "#ff4f3f",
    "Race.Gold": "#ffd23f",
    "Race.Amber": "#ffb000",
}


def col(name: str, a: float = 1.0):
    return hexc(C[name], a)


# ------------------------------------------------------------------ registry

@dataclass
class Brush:
    name: str
    kind: str                     # box | image | tile
    size: tuple[int, int]         # slate units (1x)
    draw: Callable[[float], Image.Image]
    margin: tuple[int, int, int, int] = (0, 0, 0, 0)   # box: l, t, r, b in slate units (= 1x texels)
    note: str = ""
    extra: dict = field(default_factory=dict)


BRUSHES: list[Brush] = []


def brush(name, kind, size, margin=(0, 0, 0, 0), note=""):
    def deco(fn):
        BRUSHES.append(Brush(name, kind, size, fn, margin, note))
        return fn
    return deco


def canvas(size, s):
    return Canvas(int(round(size[0] * s)), int(round(size[1] * s)))


def rim(W, H, box, radii, dx=0.0, dy=0.0):
    """Crescent between a shape and the same shape shifted by (dx, dy): an inner edge highlight."""
    a = cov(rrect_sdf(W, H, box, radii))
    b = cov(rrect_sdf(W, H, (box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy), radii))
    return np.clip(a - b, 0, 1)


LUNA_TITLE = [(0.0, hexc("#3d95ff")), (0.18, hexc("#0058ee")), (0.82, hexc("#0050e0")), (1.0, hexc("#0040c0"))]

# ------------------------------------------------------------------ XP window chrome


@brush("xp_titlebar", "box", (32, 30), (10, 8, 10, 6), "Luna title bar, rounded top corners (r 8). Height 30 for dialogs, 26 for HUD headers.")
def _titlebar(s):
    sz = (32, 30)
    c = canvas(sz, s)
    W, H = c.w, c.h
    R = (8 * s, 8 * s, 0, 0)
    shape = cov(rrect_sdf(W, H, (0, 0, W, H + 8 * s), R))
    # the Luna profile is a thin light top band, a flat middle and a thin dark bottom band: 9-slice friendly
    stops = [(0.0, hexc("#5aa8ff")), (6 * s / H, hexc("#0a5df0")), (1 - 6 * s / H, hexc("#0050e0")), (1.0, hexc("#003db8"))]
    c.paint(vgrad(W, H, stops), shape)
    c.paint(hexc("#b8d8ff", 0.85), rim(W, H, (0, 0, W, H + 8 * s), R, dy=1.2 * s) * shape)
    c.paint(hexc("#ffffff", 0.18), rim(W, H, (0, 0, W, H + 8 * s), R, dx=1.0 * s) * shape)
    c.paint(hexc("#002a8c", 0.5), rim(W, H, (0, 0, W, H + 8 * s), R, dx=-1.0 * s) * shape)
    return c.image()


@brush("xp_window", "box", (32, 32), (6, 2, 6, 6), "Window face under a title bar: beige #ece9d8 with the 3 px Luna frame on the sides and bottom.")
def _window(s):
    c = canvas((32, 32), s)
    W, H = c.w, c.h
    outer = cov(rrect_sdf(W, H, (0, -8 * s, W, H), (0, 0, 4 * s, 4 * s)))
    inner = cov(rrect_sdf(W, H, (3 * s, -8 * s, W - 3 * s, H - 3 * s), (0, 0, 2 * s, 2 * s)))
    c.paint(vgrad(W, H, [(0, hexc("#0a5df0")), (1, hexc("#0831d9"))]), outer)
    c.paint(hexc("#002a8c", 0.55), rim(W, H, (0, -8 * s, W, H), (0, 0, 4 * s, 4 * s), dx=-0.8 * s, dy=-0.8 * s))
    c.erase(inner)
    c.paint(col("Luna.Face"), inner)
    return c.image()


@brush("xp_panel", "box", (16, 16), (4, 4, 4, 4), "Inset content panel (#fdfcf7, 1 px #7f9db9), like the XP window content area.")
def _panel(s):
    c = canvas((16, 16), s)
    W, H = c.w, c.h
    c.paint(col("Luna.ContentBorder"), cov(rrect_sdf(W, H, (0, 0, W, H), 2 * s)))
    inner = cov(rrect_sdf(W, H, (s, s, W - s, H - s), 1.2 * s))
    c.erase(inner).paint(col("Luna.Content"), inner)
    return c.image()


@brush("xp_groupbox", "box", (16, 16), (5, 5, 5, 5), "Etched XP group box frame (transparent centre).")
def _group(s):
    c = canvas((16, 16), s)
    W, H = c.w, c.h
    o = cov(rrect_sdf(W, H, (0.5 * s, 0.5 * s, W - 0.5 * s, H - 0.5 * s), 3 * s))
    i = cov(rrect_sdf(W, H, (1.5 * s, 1.5 * s, W - 1.5 * s, H - 1.5 * s), 2.5 * s))
    c.paint(hexc("#d0d0bf"), np.clip(o - i, 0, 1))
    i2 = cov(rrect_sdf(W, H, (2.5 * s, 2.5 * s, W - 2.5 * s, H - 2.5 * s), 2 * s))
    c.paint(hexc("#ffffff", 0.9), np.clip(i - i2, 0, 1))
    return c.image()


# ------------------------------------------------------------------ buttons

def _xp_button(s, state):
    c = canvas((24, 24), s)
    W, H = c.w, c.h
    R = 3.5 * s
    border = hexc("#003c74") if state != "disabled" else hexc("#c9c7ba")
    c.paint(border, cov(rrect_sdf(W, H, (0, 0, W, H), R)))
    inner_box = (s, s, W - s, H - s)
    inner = cov(rrect_sdf(W, H, inner_box, R - s))
    if state == "pressed":
        fill = vgrad(W, H, [(0, hexc("#d9d7cc")), (0.25, hexc("#e4e2d9")), (1, hexc("#f4f3ee"))])
    elif state == "disabled":
        fill = vgrad(W, H, [(0, hexc("#f5f4ea")), (1, hexc("#f5f4ea"))])
    else:
        fill = vgrad(W, H, [(0, hexc("#ffffff")), (0.2, hexc("#fcfcf9")), (0.75, hexc("#efeee7")), (1, hexc("#d8d3c4"))])
    c.erase(inner).paint(fill, inner)
    ring = np.clip(inner - cov(rrect_sdf(W, H, (3 * s, 3 * s, W - 3 * s, H - 3 * s), R - 3 * s)), 0, 1)
    if state == "hover":
        c.paint(vgrad(W, H, [(0, hexc("#ffe8a8")), (0.5, hexc("#f8b330")), (1, hexc("#e5971f"))]), ring)
    elif state == "focus":
        c.paint(vgrad(W, H, [(0, hexc("#cee0fb")), (1, hexc("#6b9ae0"))]), ring)
    elif state == "normal":
        c.paint(hexc("#ffffff", 0.9), rim(W, H, inner_box, R - s, dx=s, dy=s) * inner)
    elif state == "pressed":
        c.paint(hexc("#000000", 0.12), rim(W, H, inner_box, R - s, dx=s, dy=1.5 * s) * inner)
    return c.image()


for _st in ("normal", "hover", "pressed", "focus", "disabled"):
    brush(f"xp_button_{_st}", "box", (24, 24), (6, 6, 6, 6), "Classic beige XP push button (secondary actions, < > spinners).")(
        (lambda st: lambda s: _xp_button(s, st))(_st))


def _start_button(s, state, stops=None, border="#1c5a1c"):
    c = canvas((40, 40), s)
    W, H = c.w, c.h
    R = 10 * s
    k = {"normal": 1.0, "hover": 1.12, "pressed": 0.86, "focus": 1.06}[state]
    box = (0, 0, W, H)
    c.paint(hexc(border), cov(rrect_sdf(W, H, box, R)))
    ib = (s, s, W - s, H - s)
    inner = cov(rrect_sdf(W, H, ib, R - s))
    stops = stops or [(0.0, hexc("#8be98b")), (0.1, hexc("#5fd35f")), (0.5, hexc("#3c9a3c")), (1.0, hexc("#2e8b2e"))]
    c.erase(inner).paint(vgrad(W, H, [(t, scale_rgb(cc, k)) for t, cc in stops]), inner)
    if state != "pressed":
        gloss = cov(rrect_sdf(W, H, (3 * s, 2.5 * s, W - 3 * s, H * 0.5), (R - 3 * s, R - 3 * s, 2 * s, 2 * s)))
        c.paint(vgrad(W, H, [(0, hexc("#ffffff", 0.34)), (1, hexc("#ffffff", 0.06))], 2.5 * s, H * 0.5), gloss)
        c.paint(hexc("#ffffff", 0.35), rim(W, H, ib, R - s, dx=1.5 * s, dy=1.5 * s) * inner)
        c.paint(hexc("#000000", 0.25), rim(W, H, ib, R - s, dx=-1.5 * s, dy=-1.5 * s) * inner)
    else:
        c.paint(hexc("#000000", 0.35), rim(W, H, ib, R - s, dx=0, dy=3 * s) * inner)
    if state == "focus":
        ring = np.clip(inner - cov(rrect_sdf(W, H, (3 * s, 3 * s, W - 3 * s, H - 3 * s), R - 3 * s)), 0, 1)
        c.paint(col("Luna.Focus"), ring)
    return c.image()


for _st in ("normal", "hover", "pressed", "focus"):
    brush(f"xp_start_{_st}", "box", (40, 40), (12, 12, 12, 12), "Green Start-button primary action (gloss, r 10).")(
        (lambda st: lambda s: _start_button(s, st))(_st))

BLUE_STOPS = [(0.0, hexc("#6fb1ff")), (0.1, hexc("#3d95ff")), (0.5, hexc("#0058ee")), (1.0, hexc("#0040c0"))]
for _st in ("normal", "hover", "pressed", "focus"):
    brush(f"xp_blue_{_st}", "box", (40, 40), (12, 12, 12, 12), "Luna-blue glossy button (title-bar button colours): secondary HUD actions.")(
        (lambda st: lambda s: _start_button(s, st, BLUE_STOPS, "#0a246a"))(_st))


def _close_button(s, state):
    c = canvas((22, 22), s)
    W, H = c.w, c.h
    R = 4 * s
    c.paint(hexc("#ffffff"), cov(rrect_sdf(W, H, (0, 0, W, H), R)))
    ib = (1.5 * s, 1.5 * s, W - 1.5 * s, H - 1.5 * s)
    inner = cov(rrect_sdf(W, H, ib, R - 1.5 * s))
    k = {"normal": 1.0, "hover": 1.15, "pressed": 0.85}[state]
    stops = [(0, hexc("#e8734f")), (0.45, hexc("#c9391c")), (1, hexc("#b02e12"))]
    c.erase(inner).paint(vgrad(W, H, [(t, scale_rgb(cc, k)) for t, cc in stops]), inner)
    c.paint(hexc("#000000", 0.3), rim(W, H, ib, R - 1.5 * s, dx=-s, dy=-s) * inner)
    # the X: two thick strokes
    m, t = 6.5 * s, 1.35 * s
    def stroke(x0, y0, x1, y1):
        dx, dy = x1 - x0, y1 - y0
        L = math.hypot(dx, dy)
        nx, ny = -dy / L * t, dx / L * t
        return polygon_cov(W, H, [(x0 + nx, y0 + ny), (x1 + nx, y1 + ny), (x1 - nx, y1 - ny), (x0 - nx, y0 - ny)])
    x = np.clip(stroke(m, m, W - m, H - m) + stroke(W - m, m, m, H - m), 0, 1)
    c.paint(hexc("#5a1206", 0.6), np.roll(np.roll(x, int(s), 0), int(s), 1))
    c.paint(hexc("#ffffff"), x)
    return c.image()


for _st in ("normal", "hover", "pressed"):
    brush(f"xp_close_{_st}", "image", (22, 22), note="Red XP close button with its X glyph.")(
        (lambda st: lambda s: _close_button(s, st))(_st))


def _tab(s, state):
    c = canvas((24, 24), s)
    W, H = c.w, c.h
    R = (3.5 * s, 3.5 * s, 0, 0)
    ob = (0, 0, W, H + 6 * s)
    ib = (s, s, W - s, H + 6 * s)
    outer = cov(rrect_sdf(W, H, ob, R))
    inner = cov(rrect_sdf(W, H, ib, (2.5 * s, 2.5 * s, 0, 0)))
    c.paint(hexc("#919b9c"), outer)
    if state == "active":
        c.erase(inner).paint(hexc("#ffffff"), inner)
        band = cov(rrect_sdf(W, H, (0, 0, W, 3 * s), R))
        c.paint(vgrad(W, H, [(0, hexc("#ffc873")), (1, hexc("#e68b2c"))], 0, 3 * s), band)
    else:
        c.erase(inner).paint(vgrad(W, H, [(0, hexc("#ffffff")), (0.8, hexc("#ecebe6")), (1, hexc("#d8d4c4"))]), inner)
        if state == "hover":
            band = inner * cov(rrect_sdf(W, H, (0, 0, W, 3 * s), 0))
            c.paint(vgrad(W, H, [(0, hexc("#ffe08a")), (1, hexc("#ffc83c"))], s, 3 * s), band)
    return c.image()


for _st in ("normal", "hover", "active"):
    brush(f"xp_tab_{_st}", "box", (24, 24), (5, 5, 5, 2), "Internet-Explorer-style tab (open bottom edge sits on the content panel).")(
        (lambda st: lambda s: _tab(s, st))(_st))


@brush("xp_select", "box", (24, 24), (8, 5, 5, 5), "Selected row: Luna selection blue + a yellow focus bar on the left (gamepad cursor).")
def _select(s):
    c = canvas((24, 24), s)
    W, H = c.w, c.h
    R = 3 * s
    c.paint(hexc("#1c4aa0"), cov(rrect_sdf(W, H, (0, 0, W, H), R)))
    ib = (s, s, W - s, H - s)
    inner = cov(rrect_sdf(W, H, ib, R - s))
    c.erase(inner).paint(vgrad(W, H, [(0, hexc("#4a88ea")), (0.5, hexc("#316ac5")), (1, hexc("#2a5db3"))]), inner)
    c.paint(hexc("#ffffff", 0.25), rim(W, H, ib, R - s, dy=s) * inner)
    bar = cov(rrect_sdf(W, H, (2 * s, 3 * s, 5 * s, H - 3 * s), 1.5 * s))
    c.paint(col("Luna.Focus"), bar)
    return c.image()


@brush("xp_hover_row", "box", (24, 24), (5, 5, 5, 5), "Mouse-over row (faint Luna blue).")
def _hover_row(s):
    c = canvas((24, 24), s)
    W, H = c.w, c.h
    c.paint(hexc("#316ac5", 0.14), cov(rrect_sdf(W, H, (0, 0, W, H), 3 * s)))
    return c.image()


# ------------------------------------------------------------------ balloon tooltip (toasts)

@brush("xp_balloon", "box", (32, 32), (10, 10, 10, 10), "XP balloon tooltip body (#ffffe1, black 1 px, r 8). Pair with a tail image.")
def _balloon(s):
    c = canvas((32, 32), s)
    W, H = c.w, c.h
    R = 8 * s
    c.paint(hexc("#000000"), cov(rrect_sdf(W, H, (0, 0, W, H), R)))
    inner = cov(rrect_sdf(W, H, (s, s, W - s, H - s), R - s))
    c.erase(inner).paint(vgrad(W, H, [(0, hexc("#ffffec")), (1, hexc("#ffffe1"))]), inner)
    return c.image()


def _balloon_tail(s, up=True):
    c = canvas((20, 12), s)
    W, H = c.w, c.h
    apex, bl, br = (6 * s, 0.0), (3 * s, H + 1), (15 * s, H + 1)
    outer = polygon_cov(W, H, [apex, br, bl])
    inner = polygon_cov(W, H, [(apex[0] + 0.35 * s, apex[1] + 1.9 * s), (br[0] - 1.6 * s, br[1]), (bl[0] + 1.1 * s, bl[1])])
    c.paint(hexc("#000000"), outer)
    c.erase(inner).paint(hexc("#ffffec"), inner)
    im = c.image()
    return im if up else im.transpose(Image.Transpose.FLIP_TOP_BOTTOM)


brush("xp_balloon_tail_up", "image", (20, 12), note="Balloon tail pointing up; overlap its bottom row on the body's top border (body padding-top 11).")(lambda s: _balloon_tail(s, True))
brush("xp_balloon_tail_down", "image", (20, 12), note="Balloon tail pointing down; overlap its top row on the body's bottom border.")(lambda s: _balloon_tail(s, False))


# ------------------------------------------------------------------ modern glass

def _glass(s, radii):
    c = canvas((32, 32), s)
    W, H = c.w, c.h
    box = (0, 0, W, H)
    shape = cov(rrect_sdf(W, H, box, radii))
    c.paint(vgrad(W, H, [(0, hexc("#1c1f26", 0.80)), (1, hexc("#0e1014", 0.80))]), shape)
    inner = cov(rrect_sdf(W, H, (s, s, W - s, H - s), tuple(max(0, r - s) for r in radii)))
    c.paint(hexc("#ffffff", 0.13), np.clip(shape - inner, 0, 1))
    c.paint(hexc("#ffffff", 0.10), rim(W, H, (s, s, W - s, H - s), tuple(max(0, r - s) for r in radii), dy=s) * inner)
    return c.image()


brush("glass_panel", "box", (32, 32), (10, 10, 10, 10), "Dark translucent glass (80 %), hairline white border, r 10.")(lambda s: _glass(s, (10 * s,) * 4))
brush("glass_panel_bottom", "box", (32, 32), (10, 2, 10, 10), "Glass body under an xp_titlebar header (square top corners).")(lambda s: _glass(s, (0, 0, 10 * s, 10 * s)))
brush("glass_pill", "box", (32, 32), (14, 14, 14, 14), "Glass capsule for key hints / chips (r 14 = full pill up to 28 high).")(lambda s: _glass(s, (14 * s,) * 4))


@brush("shadow", "box", (64, 64), (24, 24, 24, 24), "Soft drop shadow; the window sits inset 16 px (offset 4 px up) inside it.")
def _shadow(s):
    c = canvas((64, 64), s)
    W, H = c.w, c.h
    shape = cov(rrect_sdf(W, H, (16 * s, 16 * s, W - 16 * s, H - 16 * s), 10 * s))
    c.paint(hexc("#000000", 0.55), blur_cov(shape, 6.5 * s))
    return c.image()


# ------------------------------------------------------------------ progress / rpm

@brush("xp_progress_track", "box", (24, 18), (5, 5, 5, 5), "XP progress bar trough (white, 1 px #686868, r 3).")
def _ptrack(s):
    c = canvas((24, 18), s)
    W, H = c.w, c.h
    R = 3.5 * s
    c.paint(hexc("#686868"), cov(rrect_sdf(W, H, (0, 0, W, H), R)))
    inner = cov(rrect_sdf(W, H, (s, s, W - s, H - s), R - s))
    c.erase(inner).paint(vgrad(W, H, [(0, hexc("#dcdcdc")), (0.3, hexc("#ffffff")), (1, hexc("#f4f4f4"))]), inner)
    return c.image()


@brush("glass_track", "box", (24, 18), (5, 5, 5, 5), "Dark trough for the rpm / progress blocks on glass.")
def _gtrack(s):
    c = canvas((24, 18), s)
    W, H = c.w, c.h
    R = 4 * s
    c.paint(hexc("#ffffff", 0.22), cov(rrect_sdf(W, H, (0, 0, W, H), R)))
    inner = cov(rrect_sdf(W, H, (s, s, W - s, H - s), R - s))
    c.erase(inner).paint(hexc("#000000", 0.55), inner)
    return c.image()


SEG = {
    "green": ("#e2fbd6", "#8ee87a", "#2fc52f", "#16961a"),
    "amber": ("#fff0c0", "#ffcb4a", "#f5a300", "#c27600"),
    "red": ("#ffd0c4", "#ff6a50", "#e3270e", "#9e1608"),
    "blue": ("#d6e8ff", "#6fb1ff", "#1f78ff", "#0b4fcf"),
}


def _seg(s, kind):
    c = canvas((8, 14), s)
    W, H = c.w, c.h
    box = (0.5 * s, 0.5 * s, W - 0.5 * s, H - 0.5 * s)
    shape = cov(rrect_sdf(W, H, box, 1.5 * s))
    if kind == "off":
        c.paint(hexc("#ffffff", 0.13), shape)
        c.paint(hexc("#ffffff", 0.10), rim(W, H, box, 1.5 * s, dy=s) * shape)
        return c.image()
    a, b, m, d = (hexc(x) for x in SEG[kind])
    c.paint(vgrad(W, H, [(0, a), (0.3, b), (0.55, m), (1, d)]), shape)
    c.paint(hexc("#ffffff", 0.55), rim(W, H, box, 1.5 * s, dy=s) * shape)
    return c.image()


for _k in ("green", "amber", "red", "blue", "off"):
    brush(f"seg_{_k}", "image", (8, 14), note="XP progress-bar block; rpm / reset-progress segment.")((lambda k: lambda s: _seg(s, k))(_k))


# ------------------------------------------------------------------ race furniture

@brush("flag_strip", "tile", (32, 16), note="Checkered strip, tile horizontally (ESlateBrushTileType::Horizontal).")
def _flag(s):
    s = 1
    im = Image.new("RGBA", (32, 16))
    for y in range(16):
        for x in range(32):
            on = ((x // 8) + (y // 8)) % 2 == 0
            im.putpixel((x, y), (18, 18, 20, 255) if on else (244, 244, 240, 255))
    return im


def _light(s, kind):
    c = canvas((64, 64), s)
    W, H = c.w, c.h
    cx = cy = 32 * s
    lit = {"red": "#ff2a1a", "amber": "#ffb000", "green": "#2ee84a", "blue": "#3d95ff"}.get(kind)
    if lit:
        glow = hexc(lit)
        c.paint(radial(W, H, cx, cy, 32 * s, [(0, (*glow[:3], 0.65)), (0.62, (*glow[:3], 0.45)), (1, (*glow[:3], 0.0))]), 1.0)
    # bezel
    c.paint(vgrad(W, H, [(0, hexc("#5a5d66")), (0.5, hexc("#1d1f24")), (1, hexc("#0c0d10"))], 8 * s, 56 * s), cov(circle_sdf(W, H, cx, cy, 22 * s)))
    lens = cov(circle_sdf(W, H, cx, cy, 18.5 * s))
    if lit:
        g = hexc(lit)
        c.paint(radial(W, H, cx - 3 * s, cy - 4 * s, 22 * s, [(0, mix(g, hexc("#ffffff"), 0.75)), (0.35, mix(g, hexc("#ffffff"), 0.2)), (0.8, g), (1, scale_rgb(g, 0.6))]), lens)
    else:
        c.paint(radial(W, H, cx - 3 * s, cy - 4 * s, 22 * s, [(0, hexc("#3a3d45")), (1, hexc("#121317"))]), lens)
    spec = blur_cov(cov(rrect_sdf(W, H, (22 * s, 19 * s, 34 * s, 26 * s), 4 * s)), 1.2 * s)
    c.paint(hexc("#ffffff", 0.55 if lit else 0.18), spec * lens)
    return c.image()


for _k in ("off", "red", "amber", "green", "blue"):
    brush(f"light_{_k}", "image", (64, 64), note="Start-light disc (44 px lens + glow halo).")((lambda k: lambda s: _light(s, k))(_k))


@brush("light_housing", "box", (40, 40), (14, 14, 14, 14), "Start-light gantry housing (dark, r 14).")
def _housing(s):
    c = canvas((40, 40), s)
    W, H = c.w, c.h
    R = 14 * s
    c.paint(hexc("#000000", 0.85), cov(rrect_sdf(W, H, (0, 0, W, H), R)))
    ib = (s, s, W - s, H - s)
    inner = cov(rrect_sdf(W, H, ib, R - s))
    c.erase(inner).paint(vgrad(W, H, [(0, hexc("#30333b", 0.92)), (1, hexc("#121317", 0.92))]), inner)
    c.paint(hexc("#ffffff", 0.16), rim(W, H, ib, R - s, dy=s) * inner)
    return c.image()


def _gear_badge(s, kind):
    c = canvas((48, 48), s)
    W, H = c.w, c.h
    R = 10 * s
    c.paint(hexc("#ffffff", 0.9), cov(rrect_sdf(W, H, (0, 0, W, H), R)))
    ib = (2 * s, 2 * s, W - 2 * s, H - 2 * s)
    inner = cov(rrect_sdf(W, H, ib, R - 2 * s))
    stops = {
        "blue": [(0, hexc("#3d95ff")), (0.18, hexc("#0058ee")), (0.82, hexc("#0050e0")), (1, hexc("#0040c0"))],
        "red": [(0, hexc("#ff8a63")), (0.2, hexc("#e0451f")), (0.8, hexc("#c9391c")), (1, hexc("#a42a10"))],
        "green": [(0, hexc("#7ee07e")), (0.2, hexc("#4cb84c")), (0.8, hexc("#3c9a3c")), (1, hexc("#2e8b2e"))],
    }[kind]
    c.erase(inner).paint(vgrad(W, H, stops), inner)
    gloss = cov(rrect_sdf(W, H, (4 * s, 3.5 * s, W - 4 * s, H * 0.48), (R - 4 * s, R - 4 * s, 3 * s, 3 * s)))
    c.paint(vgrad(W, H, [(0, hexc("#ffffff", 0.32)), (1, hexc("#ffffff", 0.04))], 3.5 * s, H * 0.48), gloss)
    return c.image()


for _k in ("blue", "red", "green"):
    brush(f"gear_badge_{_k}", "box", (48, 48), (14, 14, 14, 14), "Glossy Luna badge (gear indicator, lap counter, title chips).")((lambda k: lambda s: _gear_badge(s, k))(_k))


def _key_cap(s, dark):
    c = canvas((24, 26), s)
    W, H = c.w, c.h
    R = 5 * s
    c.paint(hexc("#000000", 0.9) if dark else hexc("#3a3a3a"), cov(rrect_sdf(W, H, (0, 0, W, H), R)))
    skirt = cov(rrect_sdf(W, H, (s, s, W - s, H - s), R - s))
    c.erase(skirt).paint(hexc("#15161a") if dark else hexc("#a9a597"), skirt)
    top = cov(rrect_sdf(W, H, (s, s, W - s, H - 4 * s), R - s))
    stops = [(0, hexc("#5a5f6c")), (1, hexc("#30333b"))] if dark else [(0, hexc("#ffffff")), (0.6, hexc("#f1efe7")), (1, hexc("#dcd8cb"))]
    c.erase(top).paint(vgrad(W, H, stops, s, H - 4 * s), top)
    c.paint(hexc("#ffffff", 0.25 if dark else 0.9), rim(W, H, (s, s, W - s, H - 4 * s), R - s, dy=s) * top)
    return c.image()


brush("key_cap", "box", (24, 26), (7, 6, 7, 9), "Light keyboard key cap (Enter, R, Esc) for beige dialogs. Text sits 2 px above centre.")(lambda s: _key_cap(s, False))
brush("key_cap_dark", "box", (24, 26), (7, 6, 7, 9), "Dark key cap for hints on glass.")(lambda s: _key_cap(s, True))


def _pad_button(s, letter, colour):
    c = canvas((24, 24), s)
    W, H = c.w, c.h
    g = hexc(colour)
    c.paint(hexc("#000000", 0.85), cov(circle_sdf(W, H, 12 * s, 12 * s, 11.5 * s)))
    face = cov(circle_sdf(W, H, 12 * s, 12 * s, 10.5 * s))
    c.paint(radial(W, H, 10 * s, 8 * s, 14 * s, [(0, mix(g, hexc("#ffffff"), 0.45)), (0.6, g), (1, scale_rgb(g, 0.6))]), face)
    im = c.image()
    from PIL import ImageDraw
    d = ImageDraw.Draw(im)
    f = font("Silkscreen-Bold.ttf", 16 * s)
    d.text((12 * s + 0.5 * s, 12 * s + 6 * s), letter, font=f, fill=(0, 0, 0, 120), anchor="ms")
    d.text((12 * s, 12 * s + 5.5 * s), letter, font=f, fill=(255, 255, 255, 255), anchor="ms")
    return im


brush("pad_a", "image", (24, 24), note="Gamepad A (green).")(lambda s: _pad_button(s, "A", "#36c43a"))
brush("pad_b", "image", (24, 24), note="Gamepad B (red).")(lambda s: _pad_button(s, "B", "#e8402a"))


@brush("ribbon_gold", "box", (48, 32), (14, 6, 14, 6), "Gold swallow-tail ribbon behind NEW BEST! (keep height 32).")
def _ribbon(s):
    c = canvas((48, 32), s)
    W, H = c.w, c.h
    n = 9 * s
    pts = [(0, 0), (W, 0), (W - n, H / 2), (W, H), (0, H), (n, H / 2)]
    outer = polygon_cov(W, H, pts)
    c.paint(hexc("#6b4500"), outer)
    k = 1.4 * s
    pts_i = [(k * 1.6, k), (W - k * 1.6, k), (W - n - k * 0.6, H / 2), (W - k * 1.6, H - k), (k * 1.6, H - k), (n + k * 0.6, H / 2)]
    inner = polygon_cov(W, H, pts_i)
    c.erase(inner).paint(vgrad(W, H, [(0, hexc("#fff6b0")), (0.35, hexc("#ffd23f")), (0.7, hexc("#f0ae00")), (1, hexc("#c08300"))]), inner)
    return c.image()


@brush("burst_gold", "image", (128, 128), note="Gold starburst behind the trophy on the results screen (spin it slowly).")
def _burst(s):
    c = canvas((128, 128), s)
    W, H = c.w, c.h
    cx = cy = 64 * s
    pts = []
    n = 16
    for i in range(n * 2):
        a = math.pi * i / n - math.pi / 2
        r = (62 if i % 2 == 0 else 44) * s
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    shape = polygon_cov(W, H, pts)
    c.paint(hexc("#7a5200", 0.9), shape)
    pts_i = [(cx + (x - cx) * 0.94, cy + (y - cy) * 0.94) for x, y in pts]
    inner = polygon_cov(W, H, pts_i)
    c.erase(inner).paint(radial(W, H, cx, cy, 62 * s, [(0, hexc("#fff7c2")), (0.45, hexc("#ffd23f")), (1, hexc("#e09a00"))]), inner)
    return c.image()


@brush("xp_taskbar", "box", (16, 40), (0, 6, 0, 4), "Luna taskbar strip (bottom of the pause screen).")
def _taskbar(s):
    c = canvas((16, 40), s)
    W, H = c.w, c.h
    c.paint(vgrad(W, H, [(0, hexc("#3168d5")), (0.05, hexc("#4993e6")), (0.12, hexc("#2b63d6")), (0.55, hexc("#245edc")), (0.9, hexc("#2158d0")), (1, hexc("#1941a5"))]), 1.0)
    top = np.zeros((H, W), np.float32)
    top[: max(1, int(round(s))), :] = 1
    c.paint(hexc("#0f3c9b"), top)
    return c.image()


@brush("xp_tray", "box", (16, 40), (4, 6, 1, 4), "Taskbar notification tray (clock / FPS area).")
def _tray(s):
    c = canvas((16, 40), s)
    W, H = c.w, c.h
    c.paint(vgrad(W, H, [(0, hexc("#1290e9")), (0.3, hexc("#0b63d0")), (0.9, hexc("#0c56c0")), (1, hexc("#08409b"))]), 1.0)
    e = np.zeros((H, W), np.float32)
    e[:, : max(1, int(round(s)))] = 1
    c.paint(hexc("#0a3c96"), e)
    e2 = np.zeros((H, W), np.float32)
    e2[:, int(round(s)): int(round(2 * s))] = 1
    c.paint(hexc("#1a8ee6"), e2)
    top = np.zeros((H, W), np.float32)
    top[: max(1, int(round(s))), :] = 1
    c.paint(hexc("#0f3c9b"), top)
    return c.image()


@brush("xp_startbtn", "box", (48, 40), (4, 10, 18, 10), "Taskbar Start button (rounded right end).")
def _startbtn(s):
    c = canvas((48, 40), s)
    W, H = c.w, c.h
    R = (0, 16 * s, 16 * s, 0)
    shape = cov(rrect_sdf(W, H, (-10 * s, 0, W, H), R))
    c.paint(vgrad(W, H, [(0, hexc("#7ee07e")), (0.08, hexc("#5fd35f")), (0.45, hexc("#3c9a3c")), (1, hexc("#2e8b2e"))]), shape)
    c.paint(hexc("#ffffff", 0.35), rim(W, H, (-10 * s, 0, W, H), R, dy=2 * s) * shape)
    c.paint(hexc("#000000", 0.3), rim(W, H, (-10 * s, 0, W, H), R, dx=-2 * s, dy=-2 * s) * shape)
    return c.image()


# ------------------------------------------------------------------ pixel-art icons (12 x 12 grid, 2 px per cell at 1x)

K = hexc("#141414")
PAL = {
    "K": K, "W": hexc("#ffffff"), "w": hexc("#d8d8d8"), "G": hexc("#9a9a9a"), "D": hexc("#4a4a4a"),
    "Y": hexc("#ffd23f"), "y": hexc("#e0a000"), "O": hexc("#f08a00"), "B": hexc("#3d95ff"), "b": hexc("#a9d0ff"),
    "N": hexc("#0a246a"), "R": hexc("#e23b1c"), "r": hexc("#ff8a63"), "g": hexc("#3ddc5a"), "E": hexc("#0058ee"),
}

ICONS = {
    "flag": [
        "KKKKKKKKKKK.",
        "KWWKKWWKKWK.",
        "KWWKKWWKKWK.",
        "KKKWWKKWWKK.",
        "KKKWWKKWWKK.",
        "KWWKKWWKKWK.",
        "KWWKKWWKKWK.",
        "KKKKKKKKKKK.",
        "KG..........",
        "KG..........",
        "KG..........",
        "KK..........",
    ],
    "trophy": [
        "..KKKKKKKK..",
        "KKKYYYYYyKKK",
        "KYKYWYYYyKyK",
        "KYKYWYYYyKyK",
        ".KKYWYYYyKK.",
        "...KYYYyK...",
        "....KYyK....",
        ".....KK.....",
        "....KYyK....",
        "...KKKKKK...",
        "..KyyyyyyK..",
        "..KKKKKKKK..",
    ],
    "clock": [
        "....KKKK....",
        "...KKGGKK...",
        "..KKWWWWKK..",
        ".KWWWWKWWWK.",
        ".KWWWWKWWWK.",
        "KWWWWWKWWWWK",
        "KWWWWWKKKWWK",
        "KWWWWWWWWWWK",
        ".KWWWWWWWWK.",
        ".KWWWWWWWWK.",
        "..KKWWWWKK..",
        "....KKKK....",
    ],
    "info": [
        "....KKKK....",
        "..KKBBBBKK..",
        ".KBBBWWBBBK.",
        ".KBBBWWBBBK.",
        "KBBBBBBBBBBK",
        "KBBBWWWBBBBK",
        "KBBBBWWBBBBK",
        "KBBBBWWBBBBK",
        ".KBBBWWBBBK.",
        ".KBBWWWWBBK.",
        "..KKBBBBKK..",
        "....KKKK....",
    ],
    "warn": [
        ".....KK.....",
        "....KYYK....",
        "....KYYK....",
        "...KYKKYK...",
        "...KYKKYK...",
        "..KYYKKYYK..",
        "..KYYKKYYK..",
        ".KYYYYYYYYK.",
        ".KYYYKKYYYK.",
        "KYYYYKKYYYYK",
        "KYYYYYYYYYYK",
        "KKKKKKKKKKKK",
    ],
    "monitor": [
        "KKKKKKKKKKKK",
        "KwwwwwwwwwwK",
        "KwbbbbbbbbwK",
        "KwbBBBBBBbwK",
        "KwbBBEEBBbwK",
        "KwbBEEEEBbwK",
        "KwbbbbbbbbwK",
        "KwwwwwwwwwwK",
        "KKKKKKKKKKKK",
        "....KGGK....",
        "..KKGGGGKK..",
        "..KKKKKKKK..",
    ],
    "car": [
        "............",
        "...KKKKKK...",
        "..KbbbbbbK..",
        "..KbBBBBbK..",
        ".KKKKKKKKKK.",
        "KRRRRRRRRRRK",
        "KRYYRRRRYYRK",
        "KRRRRRRRRRRK",
        "KRRKKKKKKRRK",
        "KKKK....KKKK",
        "KDDK....KDDK",
        "KKKK....KKKK",
    ],
    "wheel": [
        "...KKKKKK...",
        "..KDDDDDDK..",
        ".KDK....KDK.",
        "KDK......KDK",
        "KDKKKKKKKKDK",
        "KDDDDGGDDDDK",
        "KDK.KGGK.KDK",
        "KDK..KK..KDK",
        ".KDK.KK.KDK.",
        "..KDDDDDDK..",
        "...KKKKKK...",
        "............",
    ],
    "cog": [
        ".....KK.....",
        "..KK.KGK.KK.",
        "..KGKKGKKGK.",
        "...KGGGGGK..",
        "KKKGGKKKGGKK",
        "KGGGK...KGGK",
        "KGGGK...KGGK",
        "KKKGGKKKGGKK",
        "...KGGGGGK..",
        "..KGKKGKKGK.",
        "..KK.KGK.KK.",
        ".....KK.....",
    ],
    "reset": [
        "...KKKKK.K..",
        "..KgggggKgK.",
        ".KgKKKKKggK.",
        "KgK....KgggK",
        "KgK...KKKKKK",
        "KgK.........",
        "KgK.........",
        "KgK......KgK",
        ".KgK....KgK.",
        "..KgKKKKgK..",
        "...KggggK...",
        "....KKKK....",
    ],
}


def _icon(s, rows, size):
    cell = size / 12 * s
    im = pixel_art(rows, PAL, int(round(cell)))
    return im


for _name, _rows in ICONS.items():
    brush(f"icon_{_name}", "image", (24, 24), note="12x12 pixel-art icon, 2 px per cell.")((lambda r: lambda s: _icon(s, r, 24))(_rows))
    brush(f"icon_{_name}_lg", "image", (48, 48), note="12x12 pixel-art icon, 4 px per cell.")((lambda r: lambda s: _icon(s, r, 48))(_rows))


def _arrow(s, up):
    rows_up = [
        "....KK....",
        "...KggK...",
        "..KggggK..",
        ".KggggggK.",
        "KKKggggKKK",
        "..KggggK..",
        "..KggggK..",
        "..KggggK..",
        "..KKKKKK..",
        "..........",
    ]
    pal = dict(PAL)
    if not up:
        rows_up = rows_up[::-1]
        rows_up = rows_up[1:] + rows_up[:1]
        pal["g"] = hexc("#ff4f3f")
    else:
        pal["g"] = hexc("#3ddc5a")
    return pixel_art(rows_up, pal, int(round(2 * s)))


brush("arrow_up", "image", (20, 20), note="Green pixel arrow: ahead of best split.")(lambda s: _arrow(s, True))
brush("arrow_down", "image", (20, 20), note="Red pixel arrow: behind best split.")(lambda s: _arrow(s, False))


def _chevron(s, right):
    rows = [
        "..W...",
        "..WW..",
        "..WWW.",
        "..WWW.",
        "..WW..",
        "..W...",
    ]
    im = pixel_art(rows, PAL, int(round(2 * s)))
    return im if right else im.transpose(Image.Transpose.FLIP_LEFT_RIGHT)


brush("chevron_right", "image", (12, 12), note="White pixel chevron (tint it), for the < > value spinners.")(lambda s: _chevron(s, True))
brush("chevron_left", "image", (12, 12), note="White pixel chevron (tint it).")(lambda s: _chevron(s, False))
brush("chevron_down", "image", (12, 12), note="White pixel chevron (tint it), key-cap arrows.")(lambda s: _chevron(s, True).transpose(Image.Transpose.ROTATE_270))
brush("chevron_up", "image", (12, 12), note="White pixel chevron (tint it), key-cap arrows.")(lambda s: _chevron(s, True).transpose(Image.Transpose.ROTATE_90))


# ------------------------------------------------------------------ race guidance (tinted in C++: white fill, black outline)

def _outlined(size, s, pts, grow):
    """White polygon with a soft dark outline (the polygon scaled up around its centroid) and drop shadow."""
    c = canvas(size, s)
    W, H = c.w, c.h
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    big = [((x - cx) * grow + cx, (y - cy) * grow + cy) for x, y in pts]
    sc = lambda P, dx=0.0, dy=0.0: [((x + dx) * s, (y + dy) * s) for x, y in P]
    c.paint(hexc("#000000", 0.35), blur_cov(polygon_cov(W, H, sc(big, 0.0, 1.5)), 1.5 * s))
    c.paint(hexc("#05070c", 0.92), polygon_cov(W, H, sc(big)))
    c.paint(hexc("#ffffff"), polygon_cov(W, H, sc(pts)))
    return c.image()


@brush("guide_arrow", "image", (48, 48), note="Guidance arrow to the next checkpoint (points up; rotate + tint in C++).")
def _guide_arrow(s):
    return _outlined((48, 48), s, [(24, 6), (42, 40), (24, 31), (6, 40)], 1.16)


@brush("cp_marker", "image", (32, 32), note="Next-checkpoint marker drawn over the gate (tip at the bottom; tint in C++).")
def _cp_marker(s):
    c = canvas((32, 32), s)
    W, H = c.w, c.h
    sc = lambda P: [(x * s, y * s) for x, y in P]
    outer = [(16, 30), (4, 14), (9, 4), (23, 4), (28, 14)]
    inner = [(16, 22), (10, 13.5), (12.5, 9), (19.5, 9), (22, 13.5)]
    c.paint(hexc("#000000", 0.35), blur_cov(polygon_cov(W, H, sc([(x, y + 1.5) for x, y in outer])), 1.5 * s))
    big = [((x - 16) * 1.14 + 16, (y - 15) * 1.12 + 15) for x, y in outer]
    c.paint(hexc("#05070c", 0.92), polygon_cov(W, H, sc(big)))
    c.paint(hexc("#ffffff"), polygon_cov(W, H, sc(outer)))
    c.paint(hexc("#05070c", 0.85), polygon_cov(W, H, sc(inner)))
    return c.image()


@brush("route_car", "image", (16, 16), note="The car on the position-on-route bar (Luna blue dot, white ring).")
def _route_car(s):
    c = canvas((16, 16), s)
    W, H = c.w, c.h
    c.paint(hexc("#000000", 0.6), cov(circle_sdf(W, H, 8 * s, 8 * s, 7.5 * s)))
    c.paint(hexc("#ffffff"), cov(circle_sdf(W, H, 8 * s, 8 * s, 6.5 * s)))
    c.paint(radial(W, H, 7 * s, 6.5 * s, 6 * s, [(0, hexc("#9fd0ff")), (0.6, hexc("#3d95ff")), (1, hexc("#0058ee"))]), cov(circle_sdf(W, H, 8 * s, 8 * s, 4.5 * s)))
    return c.image()


@brush("route_ghost", "image", (14, 14), note="Ghost of the best run on the position-on-route bar (gold diamond).")
def _route_ghost(s):
    c = canvas((14, 14), s)
    W, H = c.w, c.h
    sc = lambda P: [(x * s, y * s) for x, y in P]
    c.paint(hexc("#000000", 0.6), polygon_cov(W, H, sc([(7, 0), (14, 7), (7, 14), (0, 7)])))
    c.paint(vgrad(W, H, [(0, hexc("#fff3a0")), (0.5, hexc("#ffd23f")), (1, hexc("#c08300"))]), polygon_cov(W, H, sc([(7, 1.8), (12.2, 7), (7, 12.2), (1.8, 7)])))
    return c.image()


@brush("edge_glow", "box", (64, 64), (30, 30, 30, 30), "Screen-edge glow (stretch full screen, tint): the checkpoint pass flash.")
def _edge_glow(s):
    c = canvas((64, 64), s)
    W, H = c.w, c.h
    y, x = np.mgrid[0:H, 0:W].astype(np.float32) + 0.5
    d = np.minimum(np.minimum(x, W - x), np.minimum(y, H - y)) / (30 * s)
    a = np.clip(1.0 - d, 0, 1) ** 2.2
    c.paint(hexc("#ffffff"), a)
    return c.image()


# ------------------------------------------------------------------ export

def tex_scale(b: Brush) -> int:
    return 2 if b.kind == "image" else 1


def export() -> dict:
    GENERATED.mkdir(parents=True, exist_ok=True)
    meta = {}
    for b in BRUSHES:
        k = tex_scale(b)
        im = b.draw(k)
        assert im.size == (b.size[0] * k, b.size[1] * k), (b.name, im.size, b.size, k)
        im.save(GENERATED / f"{b.name}.png", optimize=True)
        if b.kind == "box":
            b.draw(2).save(GENERATED / f"{b.name}@2x.png", optimize=True)
        l, t, r, bt = b.margin
        meta[b.name] = {
            "kind": b.kind,
            "file": f"{b.name}.png",
            "size": list(b.size),
            "texture": list(im.size),
            "margin_px": [l, t, r, bt],
            "margin_uv": [round(l / b.size[0], 6), round(t / b.size[1], 6), round(r / b.size[0], 6), round(bt / b.size[1], 6)],
            "note": b.note,
        }
    (GENERATED / "brushes.json").write_text(json.dumps({"colours": C, "brushes": meta}, indent=1))
    return meta


def write_inl(meta: dict) -> None:
    STAGING.mkdir(parents=True, exist_ok=True)
    lines = [
        "// GENERATED by tools/ui/make_ui_assets.py - do not edit; rerun the script instead.",
        "// Brush table for CambridgeUIStyle.cpp. Box margins are UV fractions of the (1x) texture.",
        "//   CUI_BOX(Name, Width, Height, MarginLeft, MarginTop, MarginRight, MarginBottom)",
        "//   CUI_IMAGE(Name, Width, Height)        2x texture drawn at Width x Height slate units",
        "//   CUI_TILE(Name, Width, Height)         1x texture tiled horizontally",
        "//   CUI_COLOR(Name, R, G, B)              sRGB 0-255",
        "",
    ]
    for name, m in meta.items():
        w, h = m["size"]
        if m["kind"] == "box":
            l, t, r, b = m["margin_uv"]
            lines.append(f'CUI_BOX("{name}", {w}, {h}, {l:.6f}f, {t:.6f}f, {r:.6f}f, {b:.6f}f)')
        elif m["kind"] == "image":
            lines.append(f'CUI_IMAGE("{name}", {w}, {h})')
        else:
            lines.append(f'CUI_TILE("{name}", {w}, {h})')
    lines.append("")
    for name, hx in C.items():
        r, g, b, _ = hexc(hx)
        lines.append(f'CUI_COLOR("{name}", {round(r * 255)}, {round(g * 255)}, {round(b * 255)})')
    (STAGING / "CambridgeUIBrushes.inl").write_text("\n".join(lines) + "\n")


def contact_sheet(meta: dict) -> None:
    out = HERE / "mockups"
    out.mkdir(exist_ok=True)
    cols, cell = 8, 150
    rows = (len(meta) + cols - 1) // cols
    sheet = Image.new("RGBA", (cols * cell, rows * cell), (0, 0, 0, 255))
    from PIL import ImageDraw
    d = ImageDraw.Draw(sheet)
    for i, (name, m) in enumerate(meta.items()):
        x, y = (i % cols) * cell, (i // cols) * cell
        bgc = (120, 130, 140, 255) if (i // cols + i) % 2 else (95, 105, 115, 255)
        d.rectangle([x, y, x + cell - 1, y + cell - 1], fill=bgc)
        im = Image.open(GENERATED / m["file"]).convert("RGBA")
        if m["kind"] == "box":
            from uidraw import nine_slice
            im = nine_slice(im, m["margin_px"], max(m["size"][0], 110), max(m["size"][1], 50))
        elif m["kind"] == "image":
            im = im.resize(tuple(m["size"]), Image.Resampling.LANCZOS)
        im.thumbnail((cell - 16, cell - 34))
        sheet.alpha_composite(im, (x + (cell - im.width) // 2, y + 8 + (cell - 34 - im.height) // 2))
        d.text((x + 4, y + cell - 20), name, fill=(255, 255, 255, 255), font=font("OpenSans-Regular.ttf", 11))
    sheet.save(out / "brush_sheet.png")


if __name__ == "__main__":
    m = export()
    write_inl(m)
    contact_sheet(m)
    print(f"{len(m)} brushes -> {GENERATED}")
    for name, v in m.items():
        if v["kind"] == "box":
            print(f"  {name:24s} box   {v['size'][0]:3d}x{v['size'][1]:<3d} margins l{v['margin_px'][0]} t{v['margin_px'][1]} r{v['margin_px'][2]} b{v['margin_px'][3]}")
