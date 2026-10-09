"""Design options for the launch menu (Launch Open World / Timed Race / Options + Neil's Mii), as 1920x1080 mockups.

    cd tools/ui && uv run make_neil_mii.py && uv run make_launch_mockups.py [--out DIR]

Uses the real brushes (UI/Generated), fonts and the make_mockups.py primitives, so every option is buildable in Slate.
Writes launch_{a,b,c,d}_*.png and launch_overview.png.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

import make_mockups as mm
from make_mockups import H, W, box, image, key_hint, rgb, T, text_width, xp_button, xp_window
from uidraw import GENERATED, Canvas, cov, draw_text, hexc, hgrad, radial, rrect_sdf, vgrad, circle_sdf

ROOT = Path(__file__).resolve().parents[2]
FIG = ROOT / "docs" / "figures"
WHITE = rgb("#ffffff")
NAVY = rgb("#0a246a")

OPTIONS = [
    ("Launch Open World", "icon_car_lg", "Free roam from the HTMAA lectures (Media Lab, E14)"),
    ("Timed Race", "icon_flag_lg", "12 time trials across MIT and Harvard"),
    ("Options", "icon_cog_lg", "Graphics, driving assists, wheel and controls"),
]
TIP = "Grab your helmet! The open world starts right outside the HTMAA lectures."
LOADING = 0.64


# ------------------------------------------------------------------ helpers

def layer(w, h, colour, sdf_cov):
    c = Canvas(w, h)
    c.paint(colour, sdf_cov)
    return c.image()


def rrect(img, x, y, w, h, r, colour, border=None, bw=0.0, glow=None):
    """Rounded rectangle: colour = rgba or HxWx4 gradient (local coords); optional border and outer glow."""
    pad = 24 if glow else 2
    cw, ch = int(w + 2 * pad), int(h + 2 * pad)
    c = Canvas(cw, ch)
    sdf = rrect_sdf(cw, ch, (pad, pad, pad + w, pad + h), r)
    if glow:
        from uidraw import blur_cov
        c.paint(glow, blur_cov(cov(sdf + 3), 8))
    if isinstance(colour, np.ndarray):
        full = np.zeros((ch, cw, 4), np.float32)
        full[pad:pad + colour.shape[0], pad:pad + colour.shape[1]] = colour[: ch - pad, : cw - pad]
        c.paint(full, cov(sdf))
    else:
        c.paint(colour, cov(sdf))
    if border:
        c.paint(border, np.clip(cov(sdf) - cov(sdf + bw), 0, 1))
    img.alpha_composite(c.image(), (int(x - pad), int(y - pad)))


def grad_img(w, h, kind, stops, **kw):
    if kind == "v":
        arr = vgrad(w, h, stops)
    elif kind == "h":
        arr = hgrad(w, h, stops)
    else:
        arr = radial(w, h, kw["cx"], kw["cy"], kw["r"], stops)
    c = Canvas(w, h)
    c.paint(arr, 1.0)
    return c.image()


def mii(size):
    im = Image.open(GENERATED / "neil_mii.png").convert("RGBA")
    return im.resize((size, size), Image.Resampling.LANCZOS)


def wallpaper(name, dim=0.0, blur=0.0):
    im = Image.open(FIG / name).convert("RGB").resize((W, H), Image.Resampling.LANCZOS)
    if blur:
        im = im.filter(ImageFilter.GaussianBlur(blur))
    if dim:
        im = ImageEnhance.Brightness(im).enhance(1 - dim)
    return im.convert("RGBA")


def power_button(img, x, y, d=40):
    """Red XP power button (the Welcome screen's 'Turn off computer')."""
    rrect(img, x, y, d, d, 8, vgrad(d, d, [(0, hexc("#f08a62")), (0.5, hexc("#d4502a")), (1, hexc("#a8300f"))]), border=rgb("#ffffff", 0.85), bw=2)
    c = Canvas(d, d)
    cx = cy = d / 2
    ring = np.clip(cov(circle_sdf(d, d, cx, cy + 1, d * 0.27)) - cov(circle_sdf(d, d, cx, cy + 1, d * 0.27 - 3.2)), 0, 1)
    gap = cov(rrect_sdf(d, d, (cx - 4.5, cy - d * 0.36, cx + 4.5, cy), 2))
    ring = np.clip(ring - gap, 0, 1)
    bar = cov(rrect_sdf(d, d, (cx - 1.6, cy - d * 0.32, cx + 1.6, cy + 1), 1.6))
    c.paint(WHITE, np.clip(ring + bar, 0, 1))
    img.alpha_composite(c.image(), (int(x), int(y)))


def xp_progress(img, x, y, n, frac, seg="green"):
    return mm.segments(img, x, y, n, frac, lambda i, n: seg, seg_w=8, seg_h=14, gap=3, track="xp_progress_track")


def picture_tile(img, x, y, size, inner, border="#ffffff", glow=None, radius=10, bw=4):
    """XP user-picture frame: rounded tile with a thick border; inner is an RGBA image drawn inside."""
    rrect(img, x, y, size, size, radius, vgrad(size, size, [(0, hexc("#eaf2ff")), (1, hexc("#b4cdf3"))]), border=rgb(border), bw=bw, glow=glow)
    pad = bw + 2
    im = inner.resize((size - 2 * pad, size - 2 * pad), Image.Resampling.LANCZOS)
    mask = Canvas(size - 2 * pad, size - 2 * pad)
    mask.paint(WHITE, cov(rrect_sdf(size - 2 * pad, size - 2 * pad, (0, 0, size - 2 * pad, size - 2 * pad), radius - 3)))
    m = mask.image().getchannel("A")
    a = Image.composite(im, Image.new("RGBA", im.size, (0, 0, 0, 0)), m)
    img.alpha_composite(a, (int(x + pad), int(y + pad)))


def taskbar(img, tray_text, start_pressed=False, loading=True):
    tb = 40
    box(img, "xp_taskbar", 0, H - tb, W, tb)
    box(img, "xp_startbtn", 0, H - tb, 196, tb)
    if start_pressed:
        mm.fill(img, 0, H - tb, 196, tb, rgb("#0b3d0b", 0.25))
    image(img, "icon_flag", 12, H - tb + 8)
    draw_text(img, (44, H - tb + 27), "forza-MIT", "pixel", 16, WHITE, bold=True, shadow=rgb("#1f5a1f"))
    tw = 420 if loading else 230
    box(img, "xp_tray", W - tw, H - tb, tw, tb)
    if loading:
        T(img, (W - tw + 16, H - tb + 26), "Loading map", "Tray")
        xp_progress(img, W - tw + 150, H - tb + 9, 14, LOADING)
        T(img, (W - 20, H - tb + 26), "14:32", "Tray", anchor="rs")
    else:
        T(img, (W - tw / 2, H - tb + 26), tray_text, "Tray", anchor="ms")


def balloon_text(img, x, y, w, title, body, tail="up", tail_x=30, icon="icon_info"):
    lines = wrap(body, "body", 15, w - 24)
    h = 46 + 20 * len(lines)
    cx, cy, cw, ch = mm.balloon(img, x, y, w, h, tail=tail, tail_x=tail_x)
    image(img, icon, cx, cy)
    T(img, (cx + 32, cy + 17), title, "ToastTitle")
    for i, ln in enumerate(lines):
        T(img, (cx, cy + 44 + 20 * i), ln, "ToastBody")
    return h


def wrap(text, family, px, width):
    words, lines, cur = text.split(), [], ""
    for wd in words:
        t = (cur + " " + wd).strip()
        if text_width(t, family, px) > width and cur:
            lines.append(cur)
            cur = wd
        else:
            cur = t
    if cur:
        lines.append(cur)
    return lines


def key_hints(img, x, y, dark=True, style="HudHint"):
    for keys, label in [(["^", "v"], "Select"), (["ENTER"], "Go"), (["ESC"], "Back")]:
        x += key_hint(img, x, y, keys, label, dark=dark, label_style=style) + 26
    return x


# ------------------------------------------------------------------ A: the XP Welcome screen

def design_a():
    img = Image.new("RGBA", (W, H), hexc_8("#5a7edc"))
    img.alpha_composite(grad_img(W, H, "r", [(0, hexc("#a9c6f7", 0.9)), (0.55, hexc("#7d9be6", 0.35)), (1, hexc("#5a7edc", 0.0))], cx=430, cy=330, r=1050))
    top, bot = 96, 96
    img.alpha_composite(grad_img(W, top, "v", [(0, hexc("#00268a")), (1, hexc("#0a3cad"))]), (0, 0))
    img.alpha_composite(grad_img(W, 3, "h", [(0, hexc("#3d63c9")), (0.35, hexc("#b5ccff")), (0.5, hexc("#ffffff")), (0.65, hexc("#b5ccff")), (1, hexc("#3d63c9"))]), (0, top))
    img.alpha_composite(grad_img(W, bot, "v", [(0, hexc("#0a3cad")), (1, hexc("#00268a"))]), (0, H - bot))
    img.alpha_composite(grad_img(W, 3, "h", [(0, hexc("#3d63c9")), (0.3, hexc("#f2a65a")), (0.5, hexc("#ffe0b8")), (0.7, hexc("#f2a65a")), (1, hexc("#3d63c9"))]), (0, H - bot - 3))
    # divider
    img.alpha_composite(grad_img(2, 700, "v", [(0, hexc("#ffffff", 0)), (0.5, hexc("#ffffff", 0.85)), (1, hexc("#ffffff", 0))]), (1000, 190))

    # left: logo + the three choices
    x0 = 300
    image(img, "icon_flag_lg", x0, 196, 64, 64)
    draw_text(img, (x0 + 84, 248), "FORZA-MIT", "pixel", 56, WHITE, bold=True, shadow=NAVY, shadow_offset=(3, 3))
    draw_text(img, (x0 + 2, 318), "To begin, choose how you want to drive.", "body", 22, rgb("#ffffff", 0.92))
    y = 370
    for i, (label, icon, desc) in enumerate(OPTIONS):
        sel = i == 0
        if sel:
            rrect(img, x0 - 18, y - 10, 640, 132, 14, hgrad(640, 132, [(0, hexc("#1d47b0", 0.95)), (0.7, hexc("#3762cc", 0.6)), (1, hexc("#5a7edc", 0.0))]))
            img.alpha_composite(grad_img(560, 1, "h", [(0, hexc("#ffffff", 0.5)), (1, hexc("#ffffff", 0))]), (x0 - 4, y - 9))
        picture_tile(img, x0, y, 112, icon_tile(icon, 112), border="#ffc23d" if sel else "#ffffff", glow=rgb("#ffb000", 0.7) if sel else None)
        draw_text(img, (x0 + 140, y + 54), label.upper(), "pixel", 30, WHITE, bold=True, shadow=NAVY, shadow_offset=(2, 2))
        draw_text(img, (x0 + 142, y + 90), desc, "body", 18, rgb("#dfe9ff"))
        y += 150

    # right: Neil
    px, py, ps = 1130, 210, 420
    picture_tile(img, px, py, ps, mii(512), border="#ffffff", radius=16, bw=5)
    draw_text(img, (px, py + ps + 58), "NEIL", "pixel", 40, WHITE, bold=True, shadow=NAVY, shadow_offset=(3, 3))
    draw_text(img, (px + 2, py + ps + 92), "How to Make (Almost) Anything", "body", 20, rgb("#dfe9ff"))
    balloon_text(img, px, py + ps + 120, ps, "Neil", TIP, tail="up", tail_x=60)

    # bottom band: turn off (left), loading + keys (right)
    power_button(img, 60, H - 70)
    draw_text(img, (114, H - 42), "Turn off forza-MIT", "pixel", 18, WHITE, shadow=NAVY)
    kx = key_hints(img, 760, H - 63, dark=True, style="Tray")
    draw_text(img, (W - 560, H - 42), f"LOADING CAMBRIDGE  {int(LOADING*100)}%", "pixel", 16, WHITE, shadow=NAVY)
    xp_progress(img, W - 260, H - 60, 18, LOADING)
    return img


def hexc_8(h):
    return tuple(int(v * 255) for v in hexc(h))


def icon_tile(icon, size):
    """Icon centred on the tile's sky gradient (the picture inside a frame)."""
    t = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    s = int(size * 0.62)
    im = mm.tex(icon).resize((s, s), Image.Resampling.LANCZOS)
    t.alpha_composite(im, ((size - s) // 2, (size - s) // 2))
    return t


# ------------------------------------------------------------------ B: an XP window on the desktop

def design_b():
    img = wallpaper("06_car_rear_harvard_bridge_skyline.jpg")
    taskbar(img, "")
    ww, wh = 1200, 650
    x, y = (W - ww) // 2, (H - 40 - wh) // 2 - 10
    cx, cy, cw, ch = xp_window(img, x, y, ww, wh, "forza-MIT", icon="icon_flag")
    # left pane: heading + three big buttons with a line of help each
    T(img, (cx + 14, cy + 40), "WELCOME TO CAMBRIDGE", "Heading")
    draw_text(img, (cx + 16, cy + 72), "MIT and Harvard, street by street. Choose how you want to drive:", "body", 16, rgb("#333333"))
    by = cy + 110
    kinds = [("focus", True), ("normal", False), ("normal", False)]
    for (label, icon, desc), (kind, primary) in zip(OPTIONS, kinds):
        xp_button(img, cx + 14, by, 470, 74, label, kind=kind, primary=primary, icon=icon.replace("_lg", ""), style="ButtonBig" if primary else None)
        draw_text(img, (cx + 18, by + 100), desc, "body", 15, rgb("#4a4a45"))
        by += 136
    # right pane: group box with Neil
    gx, gy, gw, gh = cx + 540, cy + 6, cw - 540, ch - 10
    box(img, "xp_groupbox", gx, gy + 10, gw, gh - 10)
    mm.fill(img, gx + 14, gy, 120, 22, rgb("#ece9d8"))
    T(img, (gx + 22, gy + 17), "INSTRUCTOR", "Value")
    px0, py0, pw, ph = gx + 20, gy + 40, gw - 40, gh - 70
    box(img, "xp_panel", px0, py0, pw, ph)
    im = mii(470)
    top = py0 + ph - 2 - 470 + 40           # the shirt runs off the panel's bottom edge
    crop = im.crop((0, 0, 470, py0 + ph - 2 - top))
    img.alpha_composite(crop, (int(px0 + (pw - 470) / 2 + 30), int(top)))
    balloon_text(img, px0 + 16, py0 + 14, pw - 32, "Neil", TIP, tail="down", tail_x=pw - 200)
    return img


# ------------------------------------------------------------------ C: the XP Start menu

def design_c():
    img = wallpaper("07_killian_court_great_dome.jpg", dim=0.1)
    taskbar(img, "14:32", start_pressed=True, loading=False)
    mw, mh = 1060, 760
    x, y = 0, H - 40 - mh
    # shadow + body
    box(img, "shadow", x - 10, y - 10, mw + 24, mh + 20)
    # header
    hh = 92
    rrect(img, x, y, mw, hh + 20, 12, vgrad(mw, hh + 20, [(0, hexc("#3f8cf3")), (0.12, hexc("#1c5fd9")), (0.85, hexc("#1550c4")), (1, hexc("#0f45b5"))]))
    picture_tile(img, x + 18, y + 14, 66, icon_tile("icon_flag_lg", 66), border="#ffffff", radius=6, bw=3)
    draw_text(img, (x + 100, y + 60), "forza-MIT", "pixel", 32, WHITE, bold=True, shadow=NAVY, shadow_offset=(2, 2))
    img.alpha_composite(grad_img(mw, 3, "h", [(0, hexc("#1550c4")), (0.4, hexc("#f2a65a")), (0.6, hexc("#ffd29c")), (1, hexc("#1550c4"))]), (x, y + hh))
    # columns
    lw = 560
    body_y, body_h = y + hh + 3, mh - hh - 3 - 64
    mm.fill(img, x, body_y, lw, body_h, rgb("#ffffff"))
    mm.fill(img, x + lw, body_y, mw - lw, body_h, rgb("#d3e5fa"))
    mm.fill(img, x + lw, body_y, 1, body_h, rgb("#95bdee"))
    iy = body_y + 24
    for i, (label, icon, desc) in enumerate(OPTIONS):
        sel = i == 0
        if sel:
            mm.fill(img, x + 8, iy - 8, lw - 16, 104, rgb("#316ac5"))
        image(img, icon, x + 30, iy + 8, 64, 64)
        draw_text(img, (x + 116, iy + 40), label.upper(), "pixel", 24, WHITE if sel else rgb("#000000"), bold=True)
        draw_text(img, (x + 117, iy + 70), desc, "body", 16, rgb("#dfe9ff") if sel else rgb("#6b6b66"))
        iy += 124
        if i < len(OPTIONS) - 1:
            img.alpha_composite(grad_img(lw - 60, 1, "h", [(0, hexc("#c9c9c9", 0)), (0.5, hexc("#c9c9c9")), (1, hexc("#c9c9c9", 0))]), (x + 30, iy - 12))
    # "All events" like XP's All Programs
    ay = body_y + body_h - 70
    img.alpha_composite(grad_img(lw - 60, 1, "h", [(0, hexc("#c9c9c9", 0)), (0.5, hexc("#c9c9c9")), (1, hexc("#c9c9c9", 0))]), (x + 30, ay - 14))
    draw_text(img, (x + 170, ay + 24), "ALL 12 EVENTS", "pixel", 20, rgb("#000000"), bold=True)
    rrect(img, x + 380, ay + 4, 30, 26, 6, vgrad(30, 26, [(0, hexc("#5fd35f")), (1, hexc("#2e8b2e"))]))
    image(img, "chevron_right", x + 389, ay + 11, tint=(1, 1, 1))
    # right column: Neil
    balloon_text(img, x + lw + 30, body_y + 22, mw - lw - 60, "Neil", TIP, tail="down", tail_x=300)
    im = mii(400)
    img.alpha_composite(im, (x + lw + (mw - lw - 400) // 2, body_y + 110))
    draw_text(img, (x + lw + 40, body_y + 548), "NEIL", "pixel", 32, NAVY, bold=True)
    draw_text(img, (x + lw + 41, body_y + 578), "How to Make (Almost) Anything", "body", 16, rgb("#3b4f78"))
    # footer: loading at the left, turn off at the right
    fy = y + mh - 64
    rrect(img, x, fy, mw, 64, 0, vgrad(mw, 64, [(0, hexc("#3a80f0")), (0.15, hexc("#1c5fd9")), (1, hexc("#1048b8"))]))
    draw_text(img, (x + 24, fy + 40), f"LOADING CAMBRIDGE  {int(LOADING*100)}%", "pixel", 16, WHITE, shadow=NAVY)
    xp_progress(img, x + 290, fy + 21, 16, LOADING)
    power_button(img, x + mw - 230, fy + 12)
    draw_text(img, (x + mw - 180, fy + 40), "Turn Off", "pixel", 18, WHITE, shadow=NAVY)
    # key hints on the desktop
    key_hints(img, 1180, H - 90, dark=True, style="HudHint")
    return img


# ------------------------------------------------------------------ D: Forza-style hero, Luna Glass

def title(img, x, y, px):
    """FORZA @ MIT: Silkscreen's own @ reads as an 'e' at this size, so the @ comes from Press Start 2P."""
    x += draw_text(img, (x, y), "FORZA ", "pixel", px, WHITE, bold=True, shadow=NAVY, shadow_offset=(4, 4))
    x += draw_text(img, (x, y - 2), "@", "digits", px * 0.78, WHITE, shadow=NAVY, shadow_offset=(4, 4))
    draw_text(img, (x, y), " MIT", "pixel", px, WHITE, bold=True, shadow=NAVY, shadow_offset=(4, 4))


def design_d(variant="classic", height=600, x=1460):
    img = wallpaper("01_car_front_three_quarter.jpg", blur=2)
    img.alpha_composite(grad_img(W, H, "h", [(0, hexc("#000814", 0.78)), (0.42, hexc("#000814", 0.35)), (0.6, hexc("#000814", 0.0)), (1, hexc("#000814", 0.25))]))
    img.alpha_composite(grad_img(W, 300, "v", [(0, hexc("#000814", 0)), (1, hexc("#000814", 0.6))]), (0, H - 300))
    title(img, 120, 190, 80)
    draw_text(img, (124, 236), "CAMBRIDGE, MASSACHUSETTS", "cond", 24, rgb("#c9d6f2"), tracking=4)
    y = 320
    for i, (label, icon, desc) in enumerate(OPTIONS):
        sel = i == 0
        name = "xp_start_focus" if sel else "xp_blue_normal"
        box(img, name, 120, y, 600, 96)
        image(img, icon, 150, y + 18, 60, 60)
        draw_text(img, (236, y + 60), label.upper(), "pixel", 32, WHITE, bold=True, shadow=rgb("#1f5a1f") if sel else NAVY, shadow_offset=(2, 2))
        y += 120
    mm.glass(img, 120, y + 6, 600, 74)
    draw_text(img, (144, y + 52), OPTIONS[0][2], "body", 18, rgb("#f2f3f5"))
    # Neil, full body, standing further back on the street to the right of the car
    im = Image.open(GENERATED / f"neil_mii_{variant}.png").convert("RGBA")
    im = im.resize((round(height * im.width / im.height), height), Image.Resampling.LANCZOS)
    img.alpha_composite(im, (x, H - 70 - height))
    # bottom glass bar: keys + loading
    mm.glass(img, 120, H - 96, 1020, 60, "glass_pill")
    key_hints(img, 150, H - 79, dark=True)
    draw_text(img, (630, H - 57), f"LOADING CAMBRIDGE  {int(LOADING*100)}%", "pixel", 16, WHITE)
    mm.segments(img, 880, H - 77, 20, LOADING, lambda i, n: "blue")
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "mockups")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    shots = {"launch_d_hero": design_d()}
    for name, im in shots.items():
        im.convert("RGB").save(a.out / f"{name}.png")
    if len(shots) < 4:
        print("launch mockups ->", a.out)
        return
    tw, th = 960, 540
    ov = Image.new("RGB", (2 * tw + 12, 2 * th + 12), (24, 24, 28))
    for i, (n, im) in enumerate(shots.items()):
        ov.paste(im.convert("RGB").resize((tw, th), Image.Resampling.LANCZOS), ((i % 2) * (tw + 12), (i // 2) * (th + 12)))
    ov.save(a.out / "launch_overview.png")
    print("launch mockups ->", a.out)


if __name__ == "__main__":
    main()
