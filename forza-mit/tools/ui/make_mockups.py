"""Render approval mockups of the Luna Glass UI over real game screenshots.

    cd tools/ui && uv run make_ui_assets.py && uv run make_mockups.py

Uses the exported brushes exactly like Slate does (box brushes 9-sliced from their 1x textures, image
brushes downsampled from 2x) and the real fonts, at 1920x1080 (Slate DPI scale 1.0). The layout
constants mirror the helpers in staging/CambridgeUIStyle.cpp, so what you approve here is what the
C++ draws. Output: tools/ui/mockups/{a..g}_*.png and overview.png.
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter

from uidraw import GENERATED, draw_text, hexc, nine_slice, text_width

HERE = Path(__file__).resolve().parent
OUT = HERE / "mockups"
BG = OUT / "bg"
W, H = 1920, 1080

META = json.loads((GENERATED / "brushes.json").read_text())
BR = META["brushes"]
_tex: dict[str, Image.Image] = {}


def tex(name):
    if name not in _tex:
        _tex[name] = Image.open(GENERATED / BR[name]["file"]).convert("RGBA")
    return _tex[name]


def rgb(hx, a=1.0):
    return hexc(hx, a)


# ------------------------------------------------------------------ primitives (= what Slate does)

def box(img, name, x, y, w, h, alpha=1.0):
    im = nine_slice(tex(name), BR[name]["margin_px"], w, h)
    if alpha < 1:
        im.putalpha(im.getchannel("A").point(lambda v: int(v * alpha)))
    img.alpha_composite(im, (int(x), int(y)))


def image(img, name, x, y, w=None, h=None, alpha=1.0, tint=None):
    sw, sh = BR[name]["size"]
    w, h = w or sw, h or sh
    im = tex(name).resize((int(w), int(h)), Image.Resampling.LANCZOS)
    if tint is not None:   # SImage ColorAndOpacity: multiply
        r, g, b, a = im.split()
        r = r.point(lambda v: int(v * tint[0])); g = g.point(lambda v: int(v * tint[1])); b = b.point(lambda v: int(v * tint[2]))
        im = Image.merge("RGBA", (r, g, b, a))
    if alpha < 1:
        im.putalpha(im.getchannel("A").point(lambda v: int(v * alpha)))
    img.alpha_composite(im, (int(round(x)), int(round(y))))


def tile_h(img, name, x, y, w):
    t = tex(name)
    strip = Image.new("RGBA", (int(w), t.height))
    for i in range(0, int(w), t.width):
        strip.paste(t, (i, 0))
    img.alpha_composite(strip, (int(x), int(y)))


def fill(img, x, y, w, h, colour):
    layer = Image.new("RGBA", (int(w), int(h)), tuple(int(c * 255) for c in colour))
    img.alpha_composite(layer, (int(x), int(y)))


def background(name, dim=0.0, blur=0.0):
    p = BG / name
    if p.exists():
        im = Image.open(p).convert("RGB").resize((W, H), Image.Resampling.LANCZOS)
    else:   # neutral fallback
        im = Image.new("RGB", (W, H), (70, 90, 110))
    if blur:
        im = im.filter(ImageFilter.GaussianBlur(blur))
    if dim:
        im = ImageEnhance.Brightness(im).enhance(1 - dim)
    return im.convert("RGBA")


# text styles (px = Slate pt * 4/3); names match the C++ text styles
WHITE, BLACK = rgb("#ffffff"), rgb("#000000")
NAVY = rgb("#0a246a")
DIM = rgb("#9ea3ad")
SHADOW = rgb("#000000", 0.7)


def T(img, xy, text, style, anchor="ls", fill_=None):
    st = STYLES[style]
    return draw_text(img, xy, text, st["family"], st["px"], fill_ or st["fill"], bold=st.get("bold", False), anchor=anchor,
                     shadow=st.get("shadow"), shadow_offset=st.get("so", (1, 1)), outline=st.get("outline", 0),
                     outline_fill=st.get("ofill"), tracking=st.get("tracking", 0))


STYLES = {
    "Title":        dict(family="pixel", px=16, bold=True, fill=WHITE, shadow=NAVY, so=(1, 1)),
    "Heading":      dict(family="pixel", px=24, bold=True, fill=NAVY),
    "Label":        dict(family="pixel", px=16, fill=BLACK),
    "LabelSel":     dict(family="pixel", px=16, fill=WHITE),
    "Value":        dict(family="pixel", px=16, bold=True, fill=BLACK),
    "Body":         dict(family="body", px=15, fill=rgb("#1e1e1e")),
    "BodyBold":     dict(family="body", px=15, bold=True, fill=rgb("#1e1e1e")),
    "Small":        dict(family="cond", px=14, fill=rgb("#5a5a55")),
    "Button":       dict(family="pixel", px=16, bold=True, fill=BLACK),
    "ButtonPrimary": dict(family="pixel", px=16, bold=True, fill=WHITE, shadow=rgb("#1f5a1f"), so=(1, 1)),
    "ButtonBig":    dict(family="pixel", px=24, bold=True, fill=WHITE, shadow=rgb("#1f5a1f"), so=(2, 2)),
    "Key":          dict(family="pixel", px=16, bold=True, fill=rgb("#222222")),
    "KeyDark":      dict(family="pixel", px=16, bold=True, fill=WHITE),
    "HudLabel":     dict(family="cond", px=15, fill=DIM, tracking=1),
    "HudLabelBright": dict(family="cond", px=15, fill=WHITE, tracking=1),
    "HudHint":      dict(family="pixel", px=16, fill=rgb("#e6e8ec"), shadow=SHADOW),
    "Timer":        dict(family="digits", px=48, fill=WHITE, shadow=rgb("#000000", 0.6), so=(3, 3)),
    "TimerSmall":   dict(family="digits", px=24, fill=WHITE, shadow=rgb("#000000", 0.6), so=(2, 2)),
    "DigitsInk":    dict(family="digits", px=24, fill=NAVY),
    "Speed":        dict(family="dots", px=96, bold=True, fill=WHITE, shadow=rgb("#000000", 0.5), so=(2, 3)),
    "SpeedGhost":   dict(family="dots", px=96, bold=True, fill=rgb("#ffffff", 0.09)),
    "Gear":         dict(family="digits", px=40, fill=WHITE, shadow=NAVY, so=(3, 3)),
    "Countdown":    dict(family="digits", px=176, fill=WHITE, outline=8, ofill=rgb("#0a246a"), shadow=rgb("#000000", 0.55), so=(10, 12)),
    "CountdownGo":  dict(family="digits", px=144, fill=rgb("#7ef07e"), outline=8, ofill=rgb("#14501a"), shadow=rgb("#000000", 0.55), so=(10, 12)),
    "SplitAhead":   dict(family="digits", px=24, fill=rgb("#14962e")),
    "SplitBehind":  dict(family="digits", px=24, fill=rgb("#d0301e")),
    "ToastTitle":   dict(family="pixel", px=16, bold=True, fill=BLACK),
    "ToastBody":    dict(family="body", px=14, fill=rgb("#222222")),
    "Fps":          dict(family="dots", px=26, bold=True, fill=rgb("#b8ff9a")),
    "ResultTime":   dict(family="digits", px=48, fill=NAVY, shadow=rgb("#ffffff", 0.9), so=(2, 2)),
    "Ribbon":       dict(family="pixel", px=24, bold=True, fill=rgb("#4a2a00"), shadow=rgb("#fff3a0"), so=(1, 1)),
    "Tray":         dict(family="pixel", px=16, fill=WHITE, shadow=NAVY),
}


# ------------------------------------------------------------------ composite helpers (mirror the C++ Make* functions)

TITLE_H = 30


def xp_window(img, x, y, w, h, title, icon=None, close=True, shadow=True):
    """MakeXPWindow: shadow, Luna title bar (icon + pixel title + red close), beige face. Returns the content rect."""
    if shadow:
        box(img, "shadow", x - 16, y - 12, w + 32, h + 32)
    box(img, "xp_titlebar", x, y, w, TITLE_H)
    tx = x + 10
    if icon:
        image(img, icon, x + 7, y + 3)
        tx = x + 7 + 24 + 7
    T(img, (tx, y + 20), title, "Title")
    if close:
        image(img, "xp_close_normal", x + w - 22 - 5, y + 4)
    box(img, "xp_window", x, y + TITLE_H, w, h - TITLE_H)
    return x + 3 + 12, y + TITLE_H + 12, w - 6 - 24, h - TITLE_H - 3 - 24


def xp_button(img, x, y, w, h, text, kind="normal", primary=False, icon=None, style=None):
    name = ("xp_start_" if primary else "xp_button_") + kind
    box(img, name, x, y, w, h)
    st = style or ("ButtonPrimary" if primary else "Button")
    tw = text_width(text, STYLES[st]["family"], STYLES[st]["px"], STYLES[st].get("bold", False))
    iw = (BR[icon]["size"][0] + 8) if icon else 0
    cx = x + (w - tw - iw) / 2
    if icon:
        ih = BR[icon]["size"][1]
        image(img, icon, cx, y + (h - ih) / 2)
        cx += iw
    cap = STYLES[st]["px"] * 0.625
    T(img, (cx, y + h / 2 + cap / 2 + (1 if kind == "pressed" else 0)), text, st)


def key_cap(img, x, y, text, dark=False, minw=26):
    """KeyCap: a key cap with a pixel label, or a chevron glyph when text is one of ^ v < >."""
    st = "KeyDark" if dark else "Key"
    chev = {"^": "chevron_up", "v": "chevron_down", "<": "chevron_left", ">": "chevron_right"}.get(text)
    tw = 12 if chev else text_width(text, "pixel", 16, True)
    w = max(minw, tw + 16)
    box(img, "key_cap_dark" if dark else "key_cap", x, y, w, 26)
    if chev:
        image(img, chev, x + (w - 12) / 2, y + 5, tint=(1, 1, 1) if dark else (0.13, 0.13, 0.13))
    else:
        T(img, (x + w / 2, y + 16), text, st, anchor="ms")
    return w


def key_hint(img, x, y, keys, label, dark=True, label_style="HudHint"):
    """KeyHint: one or more key caps / pad glyphs followed by a label. Returns the advance."""
    cx = x
    for k in keys:
        if k in ("pad_a", "pad_b"):
            image(img, k, cx, y + 1)
            cx += 24 + 4
        else:
            cx += key_cap(img, cx, y, k, dark) + 4
    if label:
        cx += 4
        cx += T(img, (cx, y + 18), label, label_style)
    return cx - x


def glass(img, x, y, w, h, name="glass_panel"):
    box(img, name, x, y, w, h)


def segments(img, x, y, n, frac, colours, seg_w=8, seg_h=14, gap=3, track="glass_track"):
    """MakeSegmentBar: n XP progress blocks in a trough."""
    tw = n * seg_w + (n - 1) * gap + 10
    box(img, track, x, y, tw, seg_h + 8)
    lit = frac * n
    for i in range(n):
        sx = x + 5 + i * (seg_w + gap)
        kind = colours(i, n) if i < round(lit) else "off"
        image(img, f"seg_{kind}", sx, y + 4)
    return tw


def rpm_colour(i, n):
    t = (i + 1) / n
    return "green" if t <= 0.7 else "amber" if t <= 0.88 else "red"


def balloon(img, x, y, w, h, tail="up", tail_x=24):
    """MakeToast body: XP balloon + tail. (x, y) is the body's top-left; returns the content rect."""
    box(img, "xp_balloon", x, y, w, h)
    if tail == "up":
        image(img, "xp_balloon_tail_up", x + tail_x, y - 11)
    elif tail == "down":
        image(img, "xp_balloon_tail_down", x + tail_x, y + h - 1)
    return x + 12, y + 10, w - 24, h - 20


# ------------------------------------------------------------------ HUD pieces

def hud_header(img, x, y, w, title, icon=None, right=None, right_badge="gear_badge_green"):
    """HudHeader: Luna title-bar chip on top of a glass body (xp_titlebar, 30 high)."""
    box(img, "xp_titlebar", x, y, w, 30)
    tx = x + 10
    if icon:
        image(img, icon, x + 7, y + 3)
        tx = x + 38
    T(img, (tx, y + 20), title, "Title")
    if right:
        rw = text_width(right, "pixel", 16, True) + 18
        box(img, right_badge, x + w - rw - 5, y + 4, rw, 22)
        T(img, (x + w - 5 - rw / 2, y + 20), right, "Title", anchor="ms")


def speed_cluster(img, speed=87, gear="3", rpm=0.62, assists=("TC SPORT", "AUTO", "ABS ON"), boost=0.4):
    """Bottom-right driving HUD: Luna header (car + assists) over glass with dot-matrix speed, gear badge, rpm blocks."""
    pw, ph = 392, 30 + 164
    x, y = W - 32 - pw, H - 28 - ph
    hud_header(img, x, y, pw, "Impreza STI", icon="icon_car")
    T(img, (x + pw - 12, y + 20), "   ".join(assists), "HudLabelBright", anchor="rs")
    glass(img, x, y + 30, pw, ph - 30, "glass_panel_bottom")
    by = y + 30
    # gear badge
    gx, gy = x + pw - 18 - 76, by + 16
    box(img, "gear_badge_red" if gear == "R" else "gear_badge_blue", gx, gy, 76, 84)
    T(img, (gx + 38 + 2, gy + 42 + 14), gear, "Gear", anchor="ms")
    T(img, (gx + 38, gy + 84 - 9), "GEAR", "HudLabelBright", anchor="ms")
    # speed: dot-matrix digits over unlit "888" ghost dots, right-aligned against the badge
    sx = gx - 18
    T(img, (sx, by + 86), "888", "SpeedGhost", anchor="rs")
    T(img, (sx, by + 86), f"{speed}", "Speed", anchor="rs")
    T(img, (x + 20, by + 34), "KM/H", "HudLabel")
    # rpm blocks + boost
    n = 30
    segments(img, x + 18, by + 106, n, rpm, rpm_colour, seg_w=8, gap=3)
    T(img, (x + 20, by + 152), "RPM", "HudLabel")
    T(img, (x + 64, by + 152), f"{int(rpm * 8000):,}".replace(",", " "), "HudLabelBright")
    T(img, (x + pw - 18 - 12 * 9 - 10 - 8, by + 152), "BOOST", "HudLabel", anchor="rs")
    segments(img, x + pw - 18 - 12 * 9 - 10 + 2, by + 137, 12, boost, lambda i, n_: "blue", seg_w=6, seg_h=14, gap=3)
    return x, y


def fps_chip(img):
    x, y = 18, 16
    box(img, "glass_pill", x, y, 212, 32)
    draw_text(img, (x + 14, y + 23), "60", "dots", 24, rgb("#b8ff9a"), bold=True)
    draw_text(img, (x + 50, y + 22), "FPS", "cond", 14, DIM)
    draw_text(img, (x + 86, y + 22), "16.6 MS", "cond", 14, DIM)
    draw_text(img, (x + 146, y + 22), "GPU 9.8", "cond", 14, DIM)


def race_header(img, title="MIT LOOP", timer="1:12.408", lap=(1, 2), gate=(17, 40), best="1:41.183"):
    """Top-centre race panel: Luna header (event + lap badge) over glass: pixel timer, gate blocks, gate / best line."""
    pw = 480
    x, y = (W - pw) // 2, 20
    hud_header(img, x, y, pw, title, icon="icon_flag", right=f"LAP {lap[0]}/{lap[1]}")
    glass(img, x, y + 30, pw, 140, "glass_panel_bottom")
    T(img, (x + pw / 2, y + 30 + 66), timer, "Timer", anchor="ms")
    n = 40
    sw, gap = 8, 3
    tw = n * sw + (n - 1) * gap + 10
    segments(img, x + (pw - tw) / 2, y + 30 + 84, n, gate[0] / gate[1], lambda i, n_: "blue", seg_w=sw, gap=gap)
    T(img, (x + (pw - tw) / 2 + 2, y + 30 + 128), f"GATE {gate[0]}/{gate[1]}", "HudLabelBright")
    if best:
        T(img, (x + (pw + tw) / 2 - 2, y + 30 + 128), f"BEST  {best}", "HudLabel", anchor="rs")
    return x, y, pw


def hint_bar(img, items, y=None):
    """Bottom-centre glass pill with key hints."""
    widths = []
    tmp = Image.new("RGBA", (W, 60))
    for keys, label in items:
        widths.append(key_hint(tmp, 0, 0, keys, label))
    gap = 28
    total = sum(widths) + gap * (len(items) - 1) + 36
    x = (W - total) // 2
    y = y or H - 30 - 44
    box(img, "glass_pill", x, y, total, 44)
    cx = x + 18
    for (keys, label), wdt in zip(items, widths):
        key_hint(img, cx, y + 9, keys, label)
        cx += wdt + gap


# ------------------------------------------------------------------ mockups

def mock_settings():
    img = background("killian_court.png", dim=0.35, blur=8)
    # taskbar
    tb_h = 40
    box(img, "xp_taskbar", 0, H - tb_h, W, tb_h)
    box(img, "xp_startbtn", 0, H - tb_h, 196, tb_h)
    image(img, "icon_flag", 12, H - tb_h + 8)
    draw_text(img, (44, H - tb_h + 27), "forza-MIT", "pixel", 16, WHITE, bold=True, shadow=rgb("#1f5a1f"))
    box(img, "xp_tray", W - 230, H - tb_h, 230, tb_h)
    T(img, (W - 115, H - tb_h + 26), "60 FPS   14:32", "Tray", anchor="ms")
    fill(img, 210, H - tb_h + 5, 260, 30, rgb("#1e52ae"))
    image(img, "icon_cog", 220, H - tb_h + 8)
    T(img, (252, H - tb_h + 26), "Settings", "Tray")

    rows = [("Quality preset", "High"), ("Resolution scale", "100 %"), ("Shadows", "High"), ("Global illumination", "High"),
            ("Reflections", "High"), ("View distance", "Epic"), ("Post-processing", "High"), ("Effects", "High"),
            ("Foliage", "High"), ("Shading", "High"), ("Anti-aliasing", "High"), ("Textures", "High"),
            ("Volumetric clouds", "On"), ("Tree draw distance", "700 m"), ("Geometry detail", "Medium"),
            ("VSync", "Off"), ("Frame rate limit", "Unlimited"), ("Show FPS", "On")]
    rh = 32
    ww = 780
    wh = TITLE_H + 12 + 4 + 34 + (len(rows) * rh + 20) + 64 + 3
    x, y = (W - ww) // 2, (H - tb_h - wh) // 2
    cx, cy, cw, ch = xp_window(img, x, y, ww, wh, "Settings", icon="icon_cog")
    # tabs (IE style) sitting on the content panel
    tabs = [("Graphics", "icon_monitor"), ("Driving Assists", "icon_car"), ("Calibration", "icon_wheel")]
    tx = cx + 6
    ty = cy + 4
    py = ty + 34
    ph = len(rows) * rh + 20
    box(img, "xp_panel", cx, py, cw, ph)
    for i, (name, icon) in enumerate(tabs):
        tw = text_width(name, "pixel", 16, False) + 24 + 30
        active = i == 0
        h = 35 if active else 31
        box(img, "xp_tab_active" if active else ("xp_tab_hover" if i == 1 else "xp_tab_normal"), tx, ty + 34 - h + (1 if active else 0), tw, h)
        image(img, icon, tx + 10, ty + 34 - h + (h - 24) / 2 + 1)
        T(img, (tx + 40, ty + 34 - h + h / 2 + 6), name, "Label")
        tx += tw + 2
    ry = py + 10
    sel = 2
    for i, (label, value) in enumerate(rows):
        rx, rw = cx + 8, cw - 16
        if i == sel:
            box(img, "xp_select", rx, ry, rw, rh)
        elif i == 6:
            box(img, "xp_hover_row", rx, ry, rw, rh)
        elif i % 2 == 1:
            fill(img, rx, ry, rw, rh, rgb("#316ac5", 0.045))
        T(img, (rx + 18, ry + rh / 2 + 5), label, "LabelSel" if i == sel else "Label")
        # spinner: [<]  value  [>]
        bx = rx + rw - 10 - 26
        vw = 190
        for k, (bxx, chev) in enumerate([(bx - vw - 26, "chevron_left"), (bx, "chevron_right")]):
            state = "focus" if i == sel else "normal"
            box(img, f"xp_button_{state}", bxx, ry + 4, 26, rh - 8)
            image(img, chev, bxx + 7, ry + 4 + (rh - 8 - 12) / 2, tint=(0.08, 0.15, 0.42))
        vcx = bx - vw / 2
        T(img, (vcx, ry + rh / 2 + 5), value, "Value", anchor="ms", fill_=WHITE if i == sel else None)
        ry += rh
    # footer: key hints + resume button
    fy = py + ph + 14
    hx = cx + 2
    for keys, label in [(["TAB"], "Section"), (["^", "v"], "Select"), (["<", ">"], "Change"), (["ESC"], "Close")]:
        hx += key_hint(img, hx, fy + 4, keys, label, dark=False, label_style="Label") + 20
    xp_button(img, cx + cw - 150, fy - 2, 150, 38, "Resume", primary=True)
    return img


def mock_freeroam():
    img = background("chase.png")
    fps_chip(img)
    speed_cluster(img, speed=87, gear="3", rpm=0.62)
    # welcome toast (balloon, no tail), bottom-left
    bw, bh = 452, 82
    bx, by = 32, H - 28 - bh
    cx, cy, cw, ch = balloon(img, bx, by, bw, bh, tail="none")
    image(img, "icon_info", cx, cy)
    T(img, (cx + 32, cy + 18), "Welcome to MIT", "ToastTitle")
    draw_text(img, (cx, cy + 42), "Drive into a blue start beacon to race an event.", "body", 14, rgb("#222222"))
    draw_text(img, (cx, cy + 61), "Esc: settings, driving assists and wheel calibration", "body", 14, rgb("#5a5a55"))
    return img


def mock_start_prompt():
    img = background("massave_street.png")
    speed_cluster(img, speed=0, gear="N", rpm=0.12)
    ww, wh = 680, 330
    x, y = (W - ww) // 2, 180
    cx, cy, cw, ch = xp_window(img, x, y, ww, wh, "MIT Loop.exe", icon="icon_flag")
    tile_h(img, "flag_strip", x + 3, y + TITLE_H, ww - 6)
    cy += 16
    # left: big icon on a Luna badge
    box(img, "gear_badge_blue", cx + 4, cy + 10, 104, 104)
    image(img, "icon_flag_lg", cx + 4 + 28, cy + 10 + 28)
    tx = cx + 132
    T(img, (tx, cy + 34), "MIT Loop", "Heading")
    draw_text(img, (tx, cy + 62), "Circuit  ·  3.8 km  ·  2 laps  ·  40 gates", "body", 16, rgb("#1e1e1e"))
    image(img, "icon_trophy", tx, cy + 76)
    draw_text(img, (tx + 32, cy + 95), "Personal best", "body", 16, rgb("#5a5a55"))
    T(img, (tx + 166, cy + 98), "1:41.183", "DigitsInk")
    # Start button: big green, focused (pulsing yellow ring), the whole width of the text column
    by = cy + 122
    bw = cw - 132 - 4
    xp_button(img, tx, by, bw, 60, "START RACE", primary=True, kind="focus", style="ButtonBig", icon="icon_flag")
    # how to press it, centred under the button
    items = [(["ENTER"], ""), (["pad_a"], ""), ([], "both paddles")]
    tmp = Image.new("RGBA", (800, 60))
    total = key_hint(tmp, 0, 0, ["ENTER"], "", dark=False) + 26 + key_hint(tmp, 0, 0, ["pad_a"], "", dark=False) + 26 + text_width("both paddles", "pixel", 16)
    hx, hy = tx + (bw - total) / 2, by + 72
    hx += key_hint(img, hx, hy, ["ENTER"], "", dark=False) + 8
    T(img, (hx, hy + 18), "/", "Label"); hx += 18
    hx += key_hint(img, hx, hy, ["pad_a"], "", dark=False) + 8
    T(img, (hx, hy + 18), "/", "Label"); hx += 18
    T(img, (hx, hy + 18), "both paddles", "Label")
    T(img, (cx + cw, cy + ch - 14), "Drive away to dismiss", "Small", anchor="rs")
    return img


def mock_race():
    img = background("chase.png")
    race_header(img)
    # split toast: XP balloon under the timer
    bw, bh = 300, 78
    bx, by = (W - bw) // 2, 20 + 30 + 140 + 22
    cx, cy, cw, ch = balloon(img, bx, by, bw, bh, tail="up", tail_x=bw // 2 - 8)
    image(img, "arrow_up", cx + 2, cy + 6)
    T(img, (cx + 32, cy + 26), "-0.42", "SplitAhead")
    T(img, (cx + cw, cy + 22), "GATE 17", "ToastTitle", anchor="rs")
    draw_text(img, (cx + 2, cy + 52), "Ahead of your best run", "body", 14, rgb("#222222"))
    speed_cluster(img, speed=112, gear="4", rpm=0.83, boost=0.75)
    hint_bar(img, [(["R"], "Back on track"), (["ENTER"], "Restart"), (["BKSP"], "Leave")])
    return img


def mock_countdown(phase="2"):
    img = background("chase.png", dim=0.18)
    race_header(img, timer="0:00.000", gate=(0, 40), best="1:41.183")
    # light gantry
    n = 4
    lw = n * 64 + (n - 1) * 8 + 40
    gx, gy = (W - lw) // 2, 290
    box(img, "light_housing", gx, gy, lw, 64 + 28)
    lit = {"3": 1, "2": 2, "1": 3, "GO": 4}[phase]
    for i in range(n):
        kind = ("green" if phase == "GO" else "red") if i < lit else "off"
        image(img, f"light_{kind}", gx + 20 + i * 72, gy + 14)
    # digit (pops in: scale 1.6 -> 1.0, fades over the second)
    if phase == "GO":
        T(img, (W / 2, gy + 64 + 28 + 190), "GO!", "CountdownGo", anchor="ms")
    else:
        T(img, (W / 2, gy + 64 + 28 + 210), phase, "Countdown", anchor="ms")
    # get-ready balloon (countdown only)
    bw, bh = 380, 50 if phase != "GO" else 0
    bx, by = (W - bw) // 2, gy + 64 + 28 + 250
    if bh:
        cx, cy, cw, ch = balloon(img, bx, by, bw, bh, tail="none")
        image(img, "icon_info", cx, cy + 3)
        T(img, (cx + 32, cy + 21), "Rev it up! Launch on GO", "ToastTitle")
    speed_cluster(img, speed=0 if phase != "GO" else 6, gear="1", rpm=0.74, boost=0.2)
    return img


def mock_reset():
    img = background("killian_court.png", dim=0.12)
    race_header(img, timer="1:27.902", gate=(21, 40))
    speed_cluster(img, speed=0, gear="1", rpm=0.1, boost=0.0)
    ww, wh = 560, 156
    x, y = (W - ww) // 2, 380
    cx, cy, cw, ch = xp_window(img, x, y, ww, wh, "Back on track", icon="icon_reset", close=False)
    image(img, "icon_reset_lg", cx + 4, cy + 6)
    T(img, (cx + 72, cy + 22), "Before gate 22", "Label")
    draw_text(img, (cx + 72, cy + 44), "The clock keeps running - get ready to go!", "body", 14, rgb("#5a5a55"))
    n = 28
    n = 26
    tw = segments(img, cx + 72, cy + 58, n, 0.64, lambda i, n_: "green", seg_w=9, gap=2, track="xp_progress_track")
    box(img, "gear_badge_blue", cx + cw - 64, cy + 4, 64, 64)
    T(img, (cx + cw - 32 + 2, cy + 4 + 32 + 12), "2", "TimerSmall", anchor="ms")
    return img


def mock_results():
    img = background("chase.png", dim=0.3, blur=3)
    # confetti (SCambridgeConfetti)
    rnd = random.Random(7)
    cols = ["#3d95ff", "#5fd35f", "#ffd23f", "#e8734f", "#ffffff", "#0058ee"]
    for _ in range(140):
        cx_, cy_ = rnd.uniform(200, W - 200), rnd.uniform(40, 760)
        s = rnd.choice([6, 8, 10])
        fill(img, cx_, cy_, s, s * rnd.choice([1, 2]) // 1, rgb(rnd.choice(cols), 0.95))
    ww, wh = 700, 452
    x, y = (W - ww) // 2, 200
    cx, cy, cw, ch = xp_window(img, x, y, ww, wh, "Results - MIT Loop", icon="icon_trophy")
    tile_h(img, "flag_strip", x + 3, y + TITLE_H, ww - 6)
    cy += 16
    # trophy on a gold burst
    image(img, "burst_gold", cx - 2, cy + 6, 150, 150)
    image(img, "icon_trophy_lg", cx - 2 + 75 - 24, cy + 6 + 75 - 24)
    tx = cx + 170
    T(img, (tx, cy + 30), "FINISHED", "Heading")
    T(img, (tx - 2, cy + 98), "1:41.183", "ResultTime")
    # NEW BEST ribbon
    rw = text_width("NEW BEST!", "pixel", 24, True) + 52
    box(img, "ribbon_gold", tx, cy + 114, rw, 32)
    T(img, (tx + rw / 2, cy + 114 + 25), "NEW BEST!", "Ribbon", anchor="ms")
    image(img, "arrow_up", tx + rw + 14, cy + 120)
    T(img, (tx + rw + 40, cy + 138), "-2.305", "SplitAhead")
    draw_text(img, (tx + rw + 40 + 4, cy + 156), "vs previous best 1:43.488", "body", 13, rgb("#5a5a55"))
    # lap table
    py = cy + 180
    box(img, "xp_panel", cx, py, cw, 2 * 34 + 44)
    T(img, (cx + 16, py + 24), "LAP", "Value", fill_=rgb("#0a246a"))
    T(img, (cx + 140, py + 24), "TIME", "Value", fill_=rgb("#0a246a"))
    T(img, (cx + 330, py + 24), "VS BEST LAP", "Value", fill_=rgb("#0a246a"))
    fill(img, cx + 10, py + 34, cw - 20, 1, rgb("#aca899"))
    laps = [("1", "0:51.204", "-0.882", True, False), ("2", "0:49.979", "-1.423", True, True)]
    for i, (n, t, d, ahead, best) in enumerate(laps):
        ry = py + 40 + i * 34
        if best:
            fill(img, cx + 6, ry, cw - 12, 32, rgb("#ffd23f", 0.22))
        T(img, (cx + 16, ry + 22), n, "Label")
        T(img, (cx + 140, ry + 22), t, "Value")
        T(img, (cx + 330, ry + 22), d, "Value", fill_=rgb("#14962e") if ahead else rgb("#d0301e"))
        if best:
            image(img, "icon_trophy", cx + cw - 150, ry + 4)
            T(img, (cx + cw - 118, ry + 22), "Best lap", "Label")
    # buttons
    by = y + wh - 3 - 12 - 50
    xp_button(img, cx + cw - 250, by, 250, 50, "RACE AGAIN", primary=True, kind="focus")
    key_cap(img, cx + cw - 250 - 12 - 70, by + 12, "ENTER")
    xp_button(img, cx, by + 6, 170, 38, "Free roam")
    key_cap(img, cx + 180, by + 12, "BKSP")
    return img


def main():
    OUT.mkdir(exist_ok=True)
    shots = {
        "a_settings": mock_settings(),
        "b_freeroam_hud": mock_freeroam(),
        "c_start_prompt": mock_start_prompt(),
        "d_race_hud": mock_race(),
        "e_countdown": mock_countdown("2"),
        "e2_countdown_go": mock_countdown("GO"),
        "f_back_on_track": mock_reset(),
        "g_results": mock_results(),
    }
    for name, im in shots.items():
        im.convert("RGB").save(OUT / f"{name}.png")
    # overview grid
    tw, th = 640, 360
    names = list(shots)
    cols = 2
    rows = math.ceil(len(names) / cols)
    ov = Image.new("RGB", (cols * tw, rows * th), (20, 20, 24))
    for i, n in enumerate(names):
        ov.paste(shots[n].convert("RGB").resize((tw, th), Image.Resampling.LANCZOS), ((i % cols) * tw, (i // cols) * th))
    ov.save(OUT / "overview.png")
    print("mockups ->", OUT)


if __name__ == "__main__":
    main()
