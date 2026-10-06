"""Draw the STi livery and the paint normal map into the UV0 atlas laid out by sti_uv.py.

Run by build_sti.py through uv (PIL lives in the tools/mapgen environment):
    uv run --project tools/mapgen python tools/blender/sti_livery.py data/processed/common/car <layout.json>
Reads  the layout json written by sti_uv.py (island transforms, panel lines lifted onto the body; a temp file)
Writes sti_livery.png (4096^2 sRGB) and sti_paint_normal.png (OpenGL convention, +Y up).

Design (from the reference photo, sponsors omitted): WR Blue Mica; a yellow crescent over the doors with a
blue disc holding the Pleiades stars (one big four-point star, five small); two yellow comet tails over the rear
quarter; "SUBARU" on the lower rear doors and across the hood nose; small STi marks on the bumpers.
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = Path(sys.argv[1])
L = json.loads(Path(sys.argv[2] if len(sys.argv) > 2 else OUT / "sti_livery_layout.json").read_text())
TEX = L["tex"]
G = L["ground"]
ISL = L["islands"]
AXES = L["axes"]
SS = 3                                        # supersampling for decal edges

BLUE = (14, 56, 158)                          # WR Blue Mica (sRGB)
YELLOW = (255, 196, 0)
WHITE = (236, 238, 240)
PINK = (236, 58, 120)
FONT_BOLD = ("/System/Library/Fonts/Supplemental/Futura.ttc", 2)
FONT_XB = ("/System/Library/Fonts/Supplemental/Futura.ttc", 4)


class Island:
    def __init__(self, name):
        self.name = name
        d = ISL[name]
        self.x0, self.y0, self.s, self.umin, self.vmax = d["x0"], d["y0"], d["s"], d["umin"], d["vmax"]
        self.w, self.h = int(math.ceil(d["w"])) + 2, int(math.ceil(d["h"])) + 2
        self.layer = Image.new("RGBA", (self.w * SS, self.h * SS), (0, 0, 0, 0))
        self.draw = ImageDraw.Draw(self.layer)

    # projected (u, v) -> supersampled local pixels
    def px(self, u, v):
        return ((u - self.umin) * self.s * SS, (self.vmax - v) * self.s * SS)

    def car(self, a, b):
        """Decal coordinates -> pixels. side islands: (x, h); front/rear: (y, h); top: (x, y)."""
        if self.name == "left":
            return self.px(-a, b + G)
        if self.name == "right":
            return self.px(a, b + G)
        if self.name == "front":
            return self.px(a, b + G)
        if self.name == "rear":
            return self.px(-a, b + G)
        return self.px(-a, b)

    def poly(self, pts, fill):
        self.draw.polygon([self.car(a, b) for a, b in pts], fill=fill)

    def composite(self, img):
        small = self.layer.resize((self.w, self.h), Image.LANCZOS)
        img.alpha_composite(small, (int(round(self.x0)), int(round(self.y0))))


def ellipse_pts(cx, cy, rx, ry, n=360, a0=0.0, a1=2 * math.pi):
    return [(cx + rx * math.cos(a0 + (a1 - a0) * k / n), cy + ry * math.sin(a0 + (a1 - a0) * k / n)) for k in range(n + 1)]


def star_pts(cx, cy, r, inner=0.26, rot=0.0, n=4, k_curve=7):
    """Four-point star with concave flanks (Subaru Pleiades style)."""
    pts = []
    for i in range(n):
        a = rot + 2 * math.pi * i / n
        b = a + math.pi / n
        tip = (cx + r * math.cos(a), cy + r * math.sin(a))
        nxt = (cx + r * math.cos(a + 2 * math.pi / n), cy + r * math.sin(a + 2 * math.pi / n))
        mid = (cx + inner * r * math.cos(b), cy + inner * r * math.sin(b))
        for t in np.linspace(0, 1, k_curve, endpoint=False):     # quadratic bezier tip -> mid -> next tip
            pts.append(((1 - t) ** 2 * tip[0] + 2 * (1 - t) * t * mid[0] + t * t * nxt[0],
                        (1 - t) ** 2 * tip[1] + 2 * (1 - t) * t * mid[1] + t * t * nxt[1]))
    return pts


def text_mask(text, font, height_px, width_px=None, shear=0.0, tracking=0.0):
    f = ImageFont.truetype(font[0], 400, index=font[1])
    pad = 200
    widths = [f.getbbox(c)[2] - f.getbbox(c)[0] for c in text]
    total = sum(f.getlength(c) for c in text) + tracking * 400 * (len(text) - 1) + 2 * pad
    im = Image.new("L", (int(total), 400 + 2 * pad), 0)
    d = ImageDraw.Draw(im)
    x = pad
    for c in text:
        d.text((x, pad), c, font=f, fill=255)
        x += f.getlength(c) + tracking * 400
    im = im.crop(im.getbbox())
    if shear:
        w, h = im.size
        extra = int(abs(shear) * h)
        im = im.transform((w + extra, h), Image.AFFINE, (1, shear, -extra if shear > 0 else 0, 0, 1, 0),
                          resample=Image.BICUBIC)
        im = im.crop(im.getbbox())
    w, h = im.size
    if width_px is None:
        width_px = w * height_px / h
    return im.resize((max(1, int(width_px)), max(1, int(height_px))), Image.LANCZOS)


def put_text(isl, text, font, fill, a0, b0, a1, b1, shear=0.18, tracking=0.04):
    """Text into the box (a0, b0)-(a1, b1) in decal coordinates (centred, fit to height)."""
    p0, p1 = isl.car(a0, b0), isl.car(a1, b1)
    x0, x1 = sorted((p0[0], p1[0]))
    y0, y1 = sorted((p0[1], p1[1]))
    m = text_mask(text, font, y1 - y0, x1 - x0, shear=shear, tracking=tracking)
    col = Image.new("RGBA", m.size, fill + (255,))
    isl.layer.paste(col, (int(x0), int(y0)), m)


# --- the livery -------------------------------------------------------------------------------------
def swoosh_outline():
    """One continuous outline (side-view x, h) for the crescent and its upper tail: the outer edge is an
    ellipse that runs tangentially into the tail's top edge; the inner edge is the tail's bottom edge that
    runs tangentially into the blue disc carrying the stars. Both tips are pointed, no flat cuts."""
    ex, ey, rx, ry = -0.420, 0.636, 0.670, 0.328          # outer ellipse
    cx, cy, r = DISC                                      # inner disc (top tangent to the tail bottom)
    x_tip, h_tip = -1.86, 0.950
    top_h = lambda x: ey + ry - 0.014 * ((ex - x) / (ex - x_tip)) ** 2
    w0 = (ey + ry) - (cy + r)                             # tail thickness where it leaves the disc
    # lower crossing of the disc with the ellipse -> pointed lower tip
    phi = 0.0
    for k in range(0, 1800):
        phi = -math.radians(k * 0.1)
        x, y = cx + r * math.cos(phi), cy + r * math.sin(phi)
        if ((x - ex) / rx) ** 2 + ((y - ey) / ry) ** 2 > 1.0:
            break
    th0 = math.atan2((y - ey) / ry, (x - ex) / rx)
    pts = []
    for t in np.linspace(th0, math.pi / 2, 400):               # outer: lower tip -> front -> top
        pts.append((ex + rx * math.cos(t), ey + ry * math.sin(t)))
    for t in np.linspace(0, 1, 200)[1:]:                         # tail top edge -> tip
        x = ex + (x_tip - ex) * t
        pts.append((x, top_h(x)))
    for t in np.linspace(1, 0, 200)[1:]:                         # tail bottom edge, tip -> disc top
        x = cx + (x_tip - cx) * t
        w = w0 * (1 - t) ** 0.85
        pts.append((x, top_h(x) - w if x < ex else cy + r))
    for a in np.linspace(math.pi / 2, phi, 400):                # inner: disc arc, top -> front -> lower tip
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


DISC = (-0.560, 0.594, 0.311)


def side_livery(isl):
    isl.poly(swoosh_outline(), YELLOW + (255,))
    # second chevron: a slim lens-shaped streak under the first, pointed at both ends
    top, bot = [], []
    for t in np.linspace(0, 1, 160):
        x = -0.70 + (-1.66 + 0.70) * t
        hc = 0.848 + 0.050 * t + 0.006 * math.sin(math.pi * t)
        w = 0.040 * (math.sin(math.pi * min(1.0, t / 0.16) / 2) if t < 0.16 else (1 - (t - 0.16) / 0.84) ** 0.8)
        top.append((x, hc + w / 2))
        bot.append((x, hc - w / 2))
    isl.poly(top + bot[::-1], YELLOW + (255,))
    disc_c = DISC[:2]
    # Pleiades: one large four-point star, five small ones
    cx, cy = disc_c
    isl.poly(star_pts(cx + 0.115, cy + 0.065, 0.100), YELLOW + (255,))
    for dx, dy in ((0.030, 0.180), (0.140, 0.100), (0.040, 0.020), (0.170, -0.040), (0.070, -0.130)):
        isl.poly(star_pts(cx - dx, cy + dy, 0.042), YELLOW + (255,))
    # SUBARU along the bottom of the rear door, under the disc
    if isl.name == "left":
        put_text(isl, "SUBARU", FONT_BOLD, YELLOW, -0.545, 0.318, -0.845, 0.352)
    else:
        put_text(isl, "SUBARU", FONT_BOLD, YELLOW, -0.845, 0.318, -0.545, 0.352)


def front_livery(isl):
    put_text(isl, "SUBARU", FONT_BOLD, WHITE, -0.255, 0.758, 0.255, 0.800, shear=0.0, tracking=0.10)
    put_text(isl, "STi", FONT_XB, PINK, 0.555, 0.292, 0.665, 0.330, shear=0.15, tracking=0.0)


def rear_livery(isl):
    pass   # boot badges are 3D geometry now (sti_details.badges)


# --- panel lines -> groove mask (also darkens the colour) ----------------------------------------------
def island_weight(name, n):
    nx, ny, nz = n
    return {"left": ny, "right": -ny, "top": nz * 1.12, "front": nx, "rear": -nx}[name]


def project(name, p):
    (a, sa), (b, sb) = AXES[name]
    return sa * p[a], sb * p[b]


def grooves():
    """(groove mask, handle-dish mask), 0..255 at 1x; drawn at 2x per island, clipped to the island rectangle."""
    from PIL import ImageChops
    mask = Image.new("L", (TEX * 2, TEX * 2), 0)
    dish = Image.new("L", (TEX * 2, TEX * 2), 0)
    for name in ("left", "right", "top", "front", "rear"):
        i = ISL[name]
        ox, oy = int(i["x0"]) * 2, int(i["y0"]) * 2
        w, h = int(math.ceil(i["w"])) * 2 + 4, int(math.ceil(i["h"])) * 2 + 4
        layer = Image.new("L", (w, h), 0)
        d = ImageDraw.Draw(layer)

        def px(p):
            u, v = project(name, p)
            return ((i["x0"] + (u - i["umin"]) * i["s"]) * 2 - ox, (i["y0"] + (i["vmax"] - v) * i["s"]) * 2 - oy)

        for line in L["lines"]:
            lw = max(2, int(round(line["w"] * i["s"] * 2)))
            seg = []
            for p, n in line["pts"]:
                if island_weight(name, n) >= 0.30:
                    seg.append(px(p))
                else:
                    if len(seg) > 1:
                        d.line(seg, fill=255, width=lw, joint="curve")
                    seg = []
            if len(seg) > 1:
                d.line(seg, fill=255, width=lw, joint="curve")
        region = mask.crop((ox, oy, ox + w, oy + h))
        mask.paste(ImageChops.lighter(region, layer), (ox, oy))
        layer = Image.new("L", (w, h), 0)
        d = ImageDraw.Draw(layer)
        if name in ("left", "right"):
            for hx, hh in L["handles"]:
                cx, cy = px((hx, 0.0, hh + G))
                rx, ry = 0.085 * i["s"] * 2, 0.030 * i["s"] * 2
                d.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=255)
        region = dish.crop((ox, oy, ox + w, oy + h))
        dish.paste(ImageChops.lighter(region, layer), (ox, oy))
    return mask.resize((TEX, TEX), Image.LANCZOS), dish.resize((TEX, TEX), Image.LANCZOS)


def main():
    img = Image.new("RGBA", (TEX, TEX), BLUE + (255,))
    for name, fn in (("left", side_livery), ("right", side_livery), ("front", front_livery), ("rear", rear_livery)):
        isl = Island(name)
        fn(isl)
        isl.composite(img)
    # Panel gaps are real geometry now (boolean grooves) and the AO map adds the contact shading, so the
    # colour map stays clean: no painted-on gap lines. The normal map only carries the vinyl decal edges.
    col = np.asarray(img.convert("RGB"), np.float32)
    Image.fromarray(np.clip(col, 0, 255).astype(np.uint8)).save(OUT / "sti_livery.png", optimize=True)
    diff = np.abs(col - np.array(BLUE, np.float32)).max(-1)
    mask = np.clip(diff / 90.0, 0.0, 1.0)
    Image.fromarray((mask * 255 + 0.5).astype(np.uint8)).save(OUT / "sti_paint_mask.png", optimize=True)
    hmap = np.asarray(Image.fromarray((mask * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.9)),
                      np.float32) / 255.0
    dy, dx = np.gradient(hmap)                  # d/drow, d/dcol
    k = 1.6                                      # very subtle vinyl step
    nx, ny, nz = -dx * k, dy * k, np.ones_like(hmap)   # OpenGL: green = +v (image up) = -row
    inv = 1.0 / np.sqrt(nx * nx + ny * ny + nz * nz)
    nrm = np.stack([nx * inv, ny * inv, nz * inv], -1)
    Image.fromarray(((nrm * 0.5 + 0.5) * 255 + 0.5).astype(np.uint8)).save(OUT / "sti_paint_normal.png", optimize=True)
    print("livery written", OUT / "sti_livery.png")


main()
