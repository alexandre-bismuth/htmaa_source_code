"""Small textures for the STi (PIL; run by build_sti.py through uv in the tools/mapgen environment):

    sti_plate.png          1024x512 sRGB   licence-plate artwork (fictional, non-governmental)
    sti_plate_normal.png   1024x512        plate normal map, OpenGL (+Y up): raised characters and stamped rim
    sti_tire_normal.png    4096x256        tyre sidewall normal map, OpenGL (+Y up): raised lettering, rim
                                           protector and ribs. U = angle around the wheel, V = radius band
                                           (see sti_wheels.TIRE_UV); the bottom quarter is flat for other faces.

    uv run --project tools/mapgen python tools/blender/sti_textures.py data/processed/common/car
"""
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = Path(sys.argv[1])
DIN = "/System/Library/Fonts/Supplemental/DIN Condensed Bold.ttf"
DINA = "/System/Library/Fonts/Supplemental/DIN Alternate Bold.ttf"
ARIALB = "/System/Library/Fonts/Supplemental/Arial Black.ttf"


def normal_from_height(h, k):
    dy, dx = np.gradient(h)
    nx, ny, nz = -dx * k, dy * k, np.ones_like(h)
    inv = 1.0 / np.sqrt(nx * nx + ny * ny + nz * nz)
    n = np.stack([nx * inv, ny * inv, nz * inv], -1)
    return Image.fromarray(((n * 0.5 + 0.5) * 255 + 0.5).astype(np.uint8))


def text_fit(draw, box, text, font_path, fill, mask_draw=None):
    x0, y0, x1, y1 = box
    size = 400
    f = ImageFont.truetype(font_path, size)
    while size > 8:
        f = ImageFont.truetype(font_path, size)
        l, t, r, b = draw.textbbox((0, 0), text, font=f)
        if r - l <= x1 - x0 and b - t <= y1 - y0:
            break
        size -= 4
    l, t, r, b = draw.textbbox((0, 0), text, font=f)
    pos = (x0 + (x1 - x0 - (r - l)) / 2 - l, y0 + (y1 - y0 - (b - t)) / 2 - t)
    draw.text(pos, text, font=f, fill=fill)
    if mask_draw is not None:
        mask_draw.text(pos, text, font=f, fill=255)


def plate():
    """Massachusetts-style colourway (user request): warm white, red script state name on top, big red raised
    'HTMAA', small red bottom line (neutral text, not the official slogan)."""
    W, H = 2048, 1024
    S = 2
    red = (196, 30, 42)
    base = np.ones((H * S, W * S, 3), np.float32) * np.array([246, 244, 236], np.float32)
    base *= np.linspace(1.0, 0.95, H * S)[:, None, None]        # reflective sheeting falloff
    img = Image.fromarray(base.astype(np.uint8))
    hm = Image.new("L", (W * S, H * S), 0)
    d, dm = ImageDraw.Draw(img), ImageDraw.Draw(hm)
    m = 40 * S
    dm.rounded_rectangle((m, m, W * S - m, H * S - m), radius=56 * S, outline=150, width=40 * S)   # stamped rim
    snell = ("/System/Library/Fonts/Supplemental/SnellRoundhand.ttc", 2)
    f = ImageFont.truetype(snell[0], 300, index=snell[1])

    def fit_font(box, text, fpath, index=0):
        x0, y0, x1, y1 = box
        size = 600
        while size > 8:
            ft = ImageFont.truetype(fpath, size, index=index)
            l, t, r, bb = d.textbbox((0, 0), text, font=ft)
            if r - l <= x1 - x0 and bb - t <= y1 - y0:
                return ft, (x0 + (x1 - x0 - (r - l)) / 2 - l, y0 + (y1 - y0 - (bb - t)) / 2 - t)
            size -= 6
        return ft, (x0, y0)

    ft, pos = fit_font((470 * S, 60 * S, 1578 * S, 230 * S), "Massachusetts", snell[0], snell[1])
    d.text(pos, "Massachusetts", font=ft, fill=red)
    # plate number: bold, stretched to fill ~82 % of the width and ~52 % of the height (as on a real MA plate)
    big = ImageFont.truetype(DINA, 800)
    tm = Image.new("L", (5600, 1400), 0)
    td, xx = ImageDraw.Draw(tm), 100
    for ch in "HTMAA":
        td.text((xx, 100), ch, font=big, fill=255, stroke_width=10, stroke_fill=255)
        xx += big.getlength(ch) + 110          # open letter spacing so the strokes never touch
    tm = tm.crop(tm.getbbox())
    bw, bh = int(0.82 * W * S), int(0.52 * H * S)
    tm = tm.resize((bw, bh), Image.LANCZOS)
    x0, y0 = (W * S - bw) // 2, int(0.262 * H * S)
    img.paste(Image.new("RGB", tm.size, red), (x0, y0), tm)
    hm.paste(Image.new("L", tm.size, 255), (x0, y0), tm)
    ft, pos = fit_font((620 * S, 868 * S, 1428 * S, 948 * S), "CAMBRIDGE \u00b7 MIT", "/System/Library/Fonts/Supplemental/Arial Bold.ttf")
    d.text(pos, "CAMBRIDGE \u00b7 MIT", font=ft, fill=red)
    # bolt holes (the 3D bolts sit on them): same fractions as before (150/1024, 60/512)
    for fx, fy in ((150 / 1024, 60 / 512), (874 / 1024, 60 / 512), (150 / 1024, 452 / 512), (874 / 1024, 452 / 512)):
        r = 24 * S
        bx, by = fx * W * S, fy * H * S
        d.ellipse((bx - r, by - r, bx + r, by + r), fill=(150, 150, 150))
    img.resize((W, H), Image.LANCZOS).save(OUT / "sti_plate.png", optimize=True)
    h = np.asarray(hm.resize((W, H), Image.LANCZOS).filter(ImageFilter.GaussianBlur(2.5)), np.float32) / 255.0
    normal_from_height(h, 6.0).save(OUT / "sti_plate_normal.png", optimize=True)


def tyre():
    """Sidewall band: V from the bead (row H-1 of the band) to the shoulder (row 0)."""
    W, H = 4096, 256
    band = int(H * 0.75)                       # top 3/4 = sidewall, bottom 1/4 = flat
    S = 2
    hm = Image.new("L", (W * S, H * S), 0)
    d = ImageDraw.Draw(hm)
    # concentric ribs near the bead and below the shoulder
    for vv in (0.10, 0.13, 0.86, 0.89):
        y = int((1 - vv) * band * S)
        d.line((0, y, W * S, y), fill=70, width=2 * S)
    # lettering, twice around: size marking and a generic product line (no brands)
    for k in range(2):
        u0 = k * 0.5
        for text, uc, font, h0, h1 in (("PERFORMANCE RADIAL", 0.10, ARIALB, 0.38, 0.62),
                                       ("225/45R17  91W", 0.30, ARIALB, 0.40, 0.60),
                                       ("TUBELESS", 0.42, DINA, 0.44, 0.58)):
            w = 0.135 if len(text) > 12 else 0.07
            x0, x1 = (u0 + uc - w / 2) * W * S, (u0 + uc + w / 2) * W * S
            y0, y1 = (1 - h1) * band * S, (1 - h0) * band * S
            text_fit(d, (x0, y0, x1, y1), text, font, 255)
    h = np.asarray(hm.resize((W, H), Image.LANCZOS).filter(ImageFilter.GaussianBlur(0.8)), np.float32) / 255.0
    h[band:, :] = 0.0
    normal_from_height(h, 7.0).save(OUT / "sti_tire_normal.png", optimize=True)


def helmet():
    """Helmet shell livery on the (azimuth, elevation) UV of sti_driver.helmet: white with a blue crown band
    edged in gold, a blue lower band with a gold line, and a gold four-point star on each side."""
    W, H, S = 1024, 512, 2
    u = (np.arange(W * S) + 0.5) / (W * S)
    v = 1.0 - (np.arange(H * S) + 0.5) / (H * S)          # image row 0 = top = v 1
    az = (u - 0.5) * 2 * np.pi
    el = v * np.pi - np.pi / 2
    AZ, EL = np.meshgrid(az, el)
    dy = np.cos(EL) * np.sin(AZ)
    dz = np.sin(EL)
    white = np.array([238, 240, 243], np.float32)
    blue = np.array([16, 56, 158], np.float32)
    gold = np.array([232, 180, 28], np.float32)
    img = np.empty((H * S, W * S, 3), np.float32)
    img[:] = white
    dx = np.cos(EL) * np.cos(AZ)
    crown = (np.abs(dy) < 0.16) & (dz > 0.05)
    edge = (np.abs(dy) >= 0.17) & (np.abs(dy) < 0.20) & (dz > 0.05)
    # lower half blue, rising toward the back in a swoosh; a gold line rides on the boundary
    sweep = -0.10 + 0.22 * np.clip(-dx, 0, 1) ** 1.5
    low = dz < sweep
    lowline = (dz >= sweep) & (dz < sweep + 0.045)
    img[crown | low] = blue
    img[edge | lowline] = gold
    im = Image.fromarray(img.astype(np.uint8))
    d = ImageDraw.Draw(im)
    for side in (-1, 1):
        cu = (0.5 + side * math.radians(98) / (2 * np.pi)) * W * S
        cv = (1 - (math.radians(22) + np.pi / 2) / np.pi) * H * S
        R = 0.16 / (2 * np.pi) * W * S * 1.0
        pts = []
        for i in range(4):
            a = 2 * math.pi * i / 4 - math.pi / 2
            b = a + math.pi / 4
            pts.append((cu + R * math.cos(a), cv + R * math.sin(a)))
            pts.append((cu + 0.28 * R * math.cos(b), cv + 0.28 * R * math.sin(b)))
        d.polygon(pts, fill=tuple(int(x) for x in gold))
    im.resize((W, H), Image.LANCZOS).save(OUT / "sti_helmet.png", optimize=True)


plate()
tyre()
helmet()
print("textures written")
