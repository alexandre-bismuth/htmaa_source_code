"""Neil (HTMAA's instructor) as a full-body Mii carrying the STi driver's helmet, for the launch menu.

Drawn as SVG (Mii-style flat shapes with soft gradients) and rasterised with rsvg-convert (Homebrew librsvg).
The helmet is the in-game driver's helmet (tools/blender/sti_textures.py helmet()): white shell, blue crown band
edged in gold, blue lower swoosh with a gold line, a gold four-point star on the side, dark visor.

    uv run make_neil_mii.py [--variant NAME] [--out DIR] [--height PX] [--all]

Writes neil_mii.svg / neil_mii.png (transparent, 5:7 portrait) into DIR (default: CambridgeRacer/UI/Generated);
--all writes every variant as neil_mii_<name>.png (design review).
"""

from __future__ import annotations

import argparse
import math
import random
import subprocess
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

SKIN = "#f6d2b0"
SKIN_SHADE = "#e8b48c"
SKIN_DEEP = "#d99c74"
HAIR = "#a6a29b"
HAIR_LIGHT = "#cdc9c1"
HAIR_DARK = "#77736d"
BEARD = "#c9c4bc"
BEARD_DARK = "#9a958e"
MOUSTACHE = "#7f7871"
BROW = "#6e665e"
FRAME = "#8b9098"
SHIRT = "#dfe7da"
SHIRT_STRIPE = "#b7c8b4"
SHIRT_SHADE = "#c3d0bf"
DENIM = "#4469a3"
DENIM_DARK = "#2e4c80"
DENIM_LIGHT = "#6f92c8"
STITCH = "#d9a253"
BELT = "#5b3a22"
SHOE = "#4a3426"
WHITE = "#f3f5f8"
BLUE = "#10389e"
GOLD = "#e8b41c"

VB_W, VB_H = 1000, 1400       # viewBox (portrait)


@dataclass
class Variant:
    name: str
    hair: str = "cloud"        # cloud | receding
    pose: str = "hip"          # hip: helmet against the hip, gripped by the chin bar | tuck: forearm across it
    side: int = -1             # helmet on the viewer's left (-1, Neil's right hand) or right (+1)
    free: str = "down"         # the other arm: down | wave
    head: float = 1.0          # head scale (Wii Mii 1.0, taller Switch-style ~0.84)
    legs: float = 1.0          # leg / torso length scale
    hand: bool = True          # hip pose: the hand gripping the chin bar shows (False: hidden behind the helmet)


VARIANTS = {
    "classic": Variant("classic"),
    "tucked": Variant("tucked", pose="tuck"),
    "wave": Variant("wave", side=1, free="wave"),
    "tall": Variant("tall", hair="receding", head=0.84, legs=1.22),
    # the game's Neil (user's pick, 2026-10-08): the classic pose and hair, taller, the hand hidden behind the helmet
    "game": Variant("game", head=0.84, legs=1.22, hand=False),
}


def star(cx: float, cy: float, r: float, inner: float = 0.3, rot: float = 0.0) -> str:
    pts = []
    for i in range(8):
        a = math.pi / 4 * i - math.pi / 2 + rot
        rr = r if i % 2 == 0 else r * inner
        pts.append(f"{cx + rr * math.cos(a):.1f},{cy + rr * math.sin(a):.1f}")
    return "M" + " L".join(pts) + " Z"


def curls(cx: float, cy: float, rx: float, ry: float, a0: float, a1: float, n: int, r: float, jitter: float = 0.0):
    """Circles along an elliptical arc (degrees, 0 = +x, 90 = down): the scalloped outline of curly hair."""
    out = []
    for i in range(n):
        t = i / max(1, n - 1)
        a = math.radians(a0 + (a1 - a0) * t)
        k = 1.0 + jitter * math.sin(i * 2.7)
        out.append((cx + rx * math.cos(a), cy + ry * math.sin(a), r * k))
    return out


def defs() -> str:
    return """<defs>
  <radialGradient id="face" cx="0.45" cy="0.38" r="0.7">
    <stop offset="0" stop-color="#fbe0c6"/><stop offset="0.7" stop-color="%s"/><stop offset="1" stop-color="%s"/>
  </radialGradient>
  <radialGradient id="hair" cx="0.4" cy="0.3" r="0.75">
    <stop offset="0" stop-color="%s"/><stop offset="0.55" stop-color="%s"/><stop offset="1" stop-color="%s"/>
  </radialGradient>
  <linearGradient id="beard" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="%s"/><stop offset="1" stop-color="#b3aea6"/>
  </linearGradient>
  <linearGradient id="shirt" x1="0" y1="0" x2="1" y2="0">
    <stop offset="0" stop-color="%s"/><stop offset="0.35" stop-color="%s"/><stop offset="1" stop-color="%s"/>
  </linearGradient>
  <pattern id="stripes" width="14" height="14" patternUnits="userSpaceOnUse">
    <rect width="14" height="14" fill="%s"/><rect x="0" width="3" height="14" fill="%s" opacity="0.55"/>
  </pattern>
  <linearGradient id="torso" x1="0" y1="0" x2="1" y2="0">
    <stop offset="0" stop-color="#000" stop-opacity="0.10"/><stop offset="0.3" stop-color="#fff" stop-opacity="0.10"/>
    <stop offset="0.7" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity="0.14"/>
  </linearGradient>
  <linearGradient id="denim" x1="0" y1="0" x2="1" y2="0">
    <stop offset="0" stop-color="%s"/><stop offset="0.3" stop-color="%s"/><stop offset="0.55" stop-color="%s"/><stop offset="1" stop-color="%s"/>
  </linearGradient>
  <linearGradient id="belt" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#7a5234"/><stop offset="0.5" stop-color="%s"/><stop offset="1" stop-color="#3f2716"/>
  </linearGradient>
  <linearGradient id="buckle" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#f4f6f9"/><stop offset="0.5" stop-color="#b9bec7"/><stop offset="1" stop-color="#8b919c"/>
  </linearGradient>
  <radialGradient id="shoe" cx="0.4" cy="0.3" r="0.8">
    <stop offset="0" stop-color="#7a5a45"/><stop offset="1" stop-color="%s"/>
  </radialGradient>
  <radialGradient id="shell" cx="0.38" cy="0.3" r="0.8">
    <stop offset="0" stop-color="#ffffff"/><stop offset="0.6" stop-color="%s"/><stop offset="1" stop-color="#c9ced8"/>
  </radialGradient>
  <linearGradient id="visor" x1="0" y1="0" x2="0.3" y2="1">
    <stop offset="0" stop-color="#3a4b66"/><stop offset="0.5" stop-color="#16202f"/><stop offset="1" stop-color="#0b1119"/>
  </linearGradient>
  <linearGradient id="blue" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#2554c4"/><stop offset="1" stop-color="%s"/>
  </linearGradient>
  <filter id="soft" x="-20%%" y="-50%%" width="140%%" height="200%%"><feGaussianBlur stdDeviation="10"/></filter>
</defs>""" % (SKIN, SKIN_SHADE, HAIR_LIGHT, HAIR, HAIR_DARK, BEARD, SHIRT_SHADE, SHIRT, SHIRT_SHADE, SHIRT, SHIRT_STRIPE,
              DENIM_DARK, DENIM_LIGHT, DENIM, DENIM_DARK, BELT, SHOE, WHITE, BLUE)


# ------------------------------------------------------------------ head

def head(add, hx: float, hy: float, hair: str) -> None:
    """The head centred on (hx, hy): curly grey hair that stops above the ears, round glasses, grey beard."""
    # back hair: a curly cloud round the top and the sides, ending above the ear lobes
    tufts = curls(hx, hy - 10, 200, 165, 180, 360, 13, 56, 0.12)
    for side in (-1, 1):
        for (dx, dy, r) in ((214, 22, 46), (228, -32, 50), (200, -88, 54), (150, -140, 50)):
            tufts.append((hx + side * dx, hy + dy, r))
    jr = random.Random(11)        # messy, not a wig: jitter every curl a little
    tufts = [(x + jr.uniform(-8, 8), y + jr.uniform(-7, 5), r * jr.uniform(0.86, 1.08)) for (x, y, r) in tufts]
    add(f'<ellipse cx="{hx}" cy="{hy-25}" rx="215" ry="150" fill="{HAIR_DARK}"/>')
    for (x, y, r) in tufts:
        add(f'<circle cx="{x+5:.1f}" cy="{y+7:.1f}" r="{r:.1f}" fill="{HAIR_DARK}"/>')
    for (x, y, r) in tufts:
        add(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r*0.93:.1f}" fill="url(#hair)"/>')
        add(f'<path d="M {x-r*0.55:.1f} {y-r*0.25:.1f} A {r*0.6:.1f} {r*0.6:.1f} 0 0 1 {x+r*0.2:.1f} {y-r*0.6:.1f}" fill="none" '
            f'stroke="{HAIR_LIGHT}" stroke-width="5" stroke-linecap="round" opacity="0.8"/>')

    # ears
    for side in (-1, 1):
        add(f'<ellipse cx="{hx + side*172}" cy="{hy+45}" rx="30" ry="44" fill="{SKIN_SHADE}"/>')
        add(f'<ellipse cx="{hx + side*176}" cy="{hy+47}" rx="15" ry="25" fill="{SKIN_DEEP}" opacity="0.6"/>')

    # face
    add(f'<path d="M {hx-172} {hy} C {hx-172} {hy-130} {hx-90} {hy-195} {hx} {hy-195} '
        f'C {hx+90} {hy-195} {hx+172} {hy-130} {hx+172} {hy} '
        f'C {hx+172} {hy+125} {hx+115} {hy+222} {hx} {hy+228} '
        f'C {hx-115} {hy+222} {hx-172} {hy+125} {hx-172} {hy} Z" fill="url(#face)"/>')

    # beard (salt and pepper, full), then the mouth and the darker moustache
    add(f'<path d="M {hx-172} {hy+62} C {hx-168} {hy+170} {hx-100} {hy+262} {hx} {hy+266} '
        f'C {hx+100} {hy+262} {hx+168} {hy+170} {hx+172} {hy+62} '
        f'C {hx+160} {hy+95} {hx+140} {hy+112} {hx+110} {hy+122} '
        f'C {hx+70} {hy+140} {hx+30} {hy+128} {hx} {hy+130} '
        f'C {hx-30} {hy+128} {hx-70} {hy+140} {hx-110} {hy+122} '
        f'C {hx-140} {hy+112} {hx-160} {hy+95} {hx-172} {hy+62} Z" fill="url(#beard)"/>')
    rnd = random.Random(7)
    for k in range(40):
        a = rnd.uniform(0.15, math.pi - 0.15)
        rr = rnd.uniform(0.55, 0.95)
        x = hx + math.cos(a) * 165 * rr
        y = hy + 120 + math.sin(a) * 135 * rr
        fleck = BEARD_DARK if k % 3 else "#f2efe9"
        add(f'<ellipse cx="{x:.1f}" cy="{y:.1f}" rx="{rnd.uniform(2,4):.1f}" ry="{rnd.uniform(5,9):.1f}" '
            f'transform="rotate({rnd.uniform(-30,30):.0f} {x:.1f} {y:.1f})" fill="{fleck}" opacity="0.4"/>')
    my = hy + 168
    add(f'<path d="M {hx-72} {my-4} C {hx-50} {my+54} {hx+50} {my+54} {hx+72} {my-4} C {hx+35} {my+8} {hx-35} {my+8} {hx-72} {my-4} Z" fill="#8a2f2b"/>')
    add(f'<path d="M {hx-64} {my} C {hx-35} {my+9} {hx+35} {my+9} {hx+64} {my} L {hx+57} {my+15} C {hx+28} {my+22} {hx-28} {my+22} {hx-57} {my+15} Z" fill="#fbfbf6"/>')
    add(f'<path d="M {hx-30} {my+36} C {hx-12} {my+44} {hx+12} {my+44} {hx+30} {my+36} C {hx+12} {my+40} {hx-12} {my+40} {hx-30} {my+36} Z" fill="#c75b55"/>')
    mo = hy + 140
    add(f'<path d="M {hx-82} {mo+26} C {hx-70} {mo-8} {hx-25} {mo-12} {hx} {mo+4} C {hx+25} {mo-12} {hx+70} {mo-8} {hx+82} {mo+26} '
        f'C {hx+55} {mo+14} {hx+25} {mo+16} {hx} {mo+22} C {hx-25} {mo+16} {hx-55} {mo+14} {hx-82} {mo+26} Z" fill="{MOUSTACHE}"/>')

    # nose
    add(f'<path d="M {hx-20} {hy+95} C {hx-24} {hy+70} {hx-8} {hy+48} {hx} {hy+48} C {hx+8} {hy+48} {hx+24} {hy+70} {hx+20} {hy+95} '
        f'C {hx+10} {hy+104} {hx-10} {hy+104} {hx-20} {hy+95} Z" fill="{SKIN_SHADE}"/>')
    add(f'<ellipse cx="{hx-5}" cy="{hy+70}" rx="6" ry="12" fill="#fff" opacity="0.35"/>')

    # eyes (Mii: dark ovals with a highlight) and grey brows
    ey = hy + 30
    for side in (-1, 1):
        ex = hx + side * 68
        add(f'<ellipse cx="{ex}" cy="{ey}" rx="15" ry="20" fill="#2a1d16"/>')
        add(f'<circle cx="{ex+5}" cy="{ey-7}" r="5.5" fill="#fff"/>')
        add(f'<path d="M {ex-22} {ey-4} C {ex-14} {ey-20} {ex+14} {ey-20} {ex+22} {ey-4}" fill="none" stroke="#5a4636" stroke-width="3" opacity="0.5"/>')
        add(f'<path d="M {ex-16} {ey+28} C {ex-6} {ey+34} {ex+6} {ey+34} {ex+16} {ey+28}" fill="none" stroke="{SKIN_DEEP}" stroke-width="3" stroke-linecap="round" opacity="0.7"/>')
        bx = hx + side * 70
        add(f'<path d="M {bx - 34*side} {ey-46} C {bx - 12*side} {ey-60} {bx + 14*side} {ey-60} {bx + 34*side} {ey-48}" '
            f'fill="none" stroke="{BROW}" stroke-width="11" stroke-linecap="round"/>')

    # round wire glasses
    for side in (-1, 1):
        ex = hx + side * 68
        add(f'<circle cx="{ex}" cy="{ey+2}" r="47" fill="#e8f2ff" fill-opacity="0.18" stroke="{FRAME}" stroke-width="5.5"/>')
        add(f'<path d="M {ex - 30} {ey-26} A 40 40 0 0 1 {ex+6} {ey-38}" fill="none" stroke="#fff" stroke-width="4" stroke-linecap="round" opacity="0.6"/>')
        add(f'<path d="M {ex + side*47} {ey-6} L {hx + side*172} {ey-14}" stroke="{FRAME}" stroke-width="5" stroke-linecap="round"/>')
    add(f'<path d="M {hx-22} {ey-4} C {hx-10} {ey-16} {hx+10} {ey-16} {hx+22} {ey-4}" fill="none" stroke="{FRAME}" stroke-width="5" stroke-linecap="round"/>')

    # front hair: high forehead, curly fringe (receding: the top is thin, curls only toward the temples)
    top = hy - 158 if hair == "cloud" else hy - 182
    add(f'<path d="M {hx-178} {hy-10} C {hx-190} {hy-150} {hx-110} {hy-228} {hx} {hy-232} '
        f'C {hx+110} {hy-228} {hx+190} {hy-150} {hx+178} {hy-10} '
        f'C {hx+165} {hy-60} {hx+150} {hy-95} {hx+120} {hy-120} '
        f'C {hx+80} {hy-150} {hx+40} {top-2} {hx} {top} '
        f'C {hx-40} {top-2} {hx-80} {hy-150} {hx-120} {hy-120} '
        f'C {hx-150} {hy-95} {hx-165} {hy-60} {hx-178} {hy-10} Z" fill="url(#hair)"/>')
    if hair == "cloud":
        fringe = curls(hx, hy - 118, 150, 70, 196, 344, 9, 30, 0.2)
    else:
        fringe = curls(hx, hy - 110, 150, 62, 196, 236, 3, 30, 0.2) + curls(hx, hy - 110, 150, 62, 304, 344, 3, 30, 0.2) \
            + curls(hx, hy - 190, 110, 30, 215, 325, 5, 24, 0.25)
    for (x, y, r) in fringe:
        add(f'<circle cx="{x+3:.1f}" cy="{y+6:.1f}" r="{r:.1f}" fill="{HAIR_DARK}"/>')
    for (x, y, r) in fringe:
        add(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r*0.92:.1f}" fill="url(#hair)"/>')
        add(f'<path d="M {x-r*0.5:.1f} {y-r*0.2:.1f} A {r*0.6:.1f} {r*0.6:.1f} 0 0 1 {x+r*0.25:.1f} {y-r*0.55:.1f}" fill="none" '
            f'stroke="{HAIR_LIGHT}" stroke-width="4" stroke-linecap="round" opacity="0.8"/>')


# ------------------------------------------------------------------ helmet

def helmet(add, cx: float, cy: float, s: float, flip: bool = False) -> None:
    """Closed-face rally helmet seen from its side, visor toward -x (or +x when flipped). Local units ~330 wide."""
    sx = -s if flip else s
    add(f'<g transform="translate({cx:.1f} {cy:.1f}) scale({sx:.3f} {s:.3f})">')
    shell = ("M -150 20 C -158 -90 -70 -150 20 -150 C 120 -150 175 -75 170 20 "
             "C 168 85 140 130 85 145 L -60 150 C -115 148 -148 100 -150 20 Z")
    add(f'<clipPath id="shellclip{cx:.0f}"><path d="{shell}"/></clipPath>')
    add(f'<path d="{shell}" fill="url(#shell)"/>')
    add(f'<g clip-path="url(#shellclip{cx:.0f})">')
    add('<path d="M -200 95 C -60 105 80 80 200 -10 L 220 220 L -200 220 Z" fill="url(#blue)"/>')
    add(f'<path d="M -200 88 C -60 98 80 72 200 -18" fill="none" stroke="{GOLD}" stroke-width="9"/>')
    add(f'<path d="M -120 -95 C -60 -165 110 -170 185 -40" fill="none" stroke="{GOLD}" stroke-width="50"/>')
    add('<path d="M -120 -95 C -60 -165 110 -170 185 -40" fill="none" stroke="url(#blue)" stroke-width="36"/>')
    add('</g>')
    add('<path d="M -152 -18 C -145 -60 -110 -72 -55 -70 L -10 -66 C 5 -40 5 10 -8 35 L -140 38 C -152 25 -155 5 -152 -18 Z" '
        'fill="url(#visor)" stroke="#5d6675" stroke-width="5"/>')
    add('<path d="M -128 -40 C -110 -58 -70 -60 -30 -56" fill="none" stroke="#ffffff" stroke-width="8" stroke-linecap="round" opacity="0.45"/>')
    add('<circle cx="18" cy="-10" r="12" fill="#d7dbe2" stroke="#9aa1ad" stroke-width="3"/>')
    add(f'<path d="{star(90, 10, 34, 0.3)}" fill="{GOLD}" stroke="#b98a0e" stroke-width="2"/>')
    for i in range(3):
        add(f'<rect x="{-132 + i*18}" y="62" width="10" height="30" rx="5" fill="#2b3240" opacity="0.8"/>')
    add('<path d="M -60 -118 C -10 -138 60 -136 110 -110" fill="none" stroke="#fff" stroke-width="10" stroke-linecap="round" opacity="0.7"/>')
    add('</g>')


# ------------------------------------------------------------------ body

def sleeve(add, pts, width: float = 74) -> None:
    d = f"M {pts[0][0]:.1f} {pts[0][1]:.1f} " + " ".join(f"L {x:.1f} {y:.1f}" for x, y in pts[1:])
    add(f'<path d="{d}" fill="none" stroke="{SHIRT_SHADE}" stroke-width="{width+6}" stroke-linecap="round" stroke-linejoin="round"/>')
    add(f'<path d="{d}" fill="none" stroke="url(#stripes)" stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round"/>')


def hand(add, x: float, y: float, r: float = 34, thumb: int = 1) -> None:
    add(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{SKIN}"/>')
    add(f'<ellipse cx="{x + thumb*r*0.65:.1f}" cy="{y - r*0.25:.1f}" rx="{r*0.32:.1f}" ry="{r*0.5:.1f}" fill="{SKIN}" stroke="{SKIN_SHADE}" stroke-width="3"/>')
    add(f'<ellipse cx="{x - r*0.25:.1f}" cy="{y - r*0.35:.1f}" rx="{r*0.3:.1f}" ry="{r*0.2:.1f}" fill="#fff" opacity="0.35"/>')


def svg(v: Variant) -> str:
    parts: list[str] = [defs()]
    add = parts.append
    hx = VB_W / 2
    k = v.head
    hy = 330.0 + (1.0 - k) * 140      # a smaller head sits a little lower so the body has room
    neck_top = hy + 200 * k
    sh = neck_top + 70                  # shoulder line
    waist = sh + 268 * v.legs ** 0.5
    crotch = waist + 105
    hem = crotch + 245 * v.legs
    sole = hem + 52
    half = 152                          # shoulder half width
    whalf = 140                         # waist half width
    s = v.side

    # ground shadow
    add(f'<ellipse cx="{hx}" cy="{sole+6:.1f}" rx="250" ry="26" fill="#000" opacity="0.22" filter="url(#soft)"/>')

    # the free arm behind nothing: drawn after the torso. Shoes and jeans first.
    for side in (-1, 1):
        x = hx + side * 76
        add(f'<path d="M {x-74:.1f} {sole:.1f} C {x-80:.1f} {sole-50:.1f} {x-40:.1f} {hem-6:.1f} {x:.1f} {hem-6:.1f} '
            f'C {x+40:.1f} {hem-6:.1f} {x+80:.1f} {sole-50:.1f} {x+74:.1f} {sole:.1f} Z" fill="url(#shoe)"/>')
        add(f'<path d="M {x-60:.1f} {sole-14:.1f} C {x-30:.1f} {sole-4:.1f} {x+30:.1f} {sole-4:.1f} {x+60:.1f} {sole-14:.1f}" '
            f'fill="none" stroke="#2c1e15" stroke-width="5" opacity="0.6"/>')
    # jeans: hips, two legs with a gap, cuffs, seams and orange stitching
    gap = 7
    jeans = (f"M {hx-whalf} {waist} L {hx+whalf} {waist} C {hx+whalf+8} {waist+60} {hx+146} {crotch} {hx+144} {crotch+40} "
             f"L {hx+138} {hem} L {hx+gap} {hem} L {hx+gap} {crotch+10} C {hx+gap} {crotch} {hx-gap} {crotch} {hx-gap} {crotch+10} "
             f"L {hx-gap} {hem} L {hx-138} {hem} L {hx-144} {crotch+40} C {hx-146} {crotch} {hx-whalf-8} {waist+60} {hx-whalf} {waist} Z")
    add(f'<path d="{jeans}" fill="url(#denim)"/>')
    for side in (-1, 1):
        add(f'<path d="M {hx+side*72:.1f} {crotch+40:.1f} L {hx+side*72:.1f} {hem-8:.1f}" stroke="{DENIM_LIGHT}" stroke-width="18" opacity="0.18" stroke-linecap="round"/>')
        add(f'<rect x="{hx + (8 if side > 0 else -138):.1f}" y="{hem-26:.1f}" width="130" height="26" fill="{DENIM_DARK}" opacity="0.45"/>')
        add(f'<path d="M {hx + side*138:.1f} {hem-30:.1f} L {hx + side*8:.1f} {hem-30:.1f}" stroke="{STITCH}" stroke-width="3" stroke-dasharray="8 6" opacity="0.8"/>')
        # front pocket opening and the outer seam
        add(f'<path d="M {hx + side*(whalf-6):.1f} {waist+30:.1f} C {hx + side*(whalf-40):.1f} {waist+40:.1f} {hx + side*92:.1f} {waist+55:.1f} {hx + side*82:.1f} {waist+28:.1f}" '
            f'fill="none" stroke="{STITCH}" stroke-width="3" stroke-dasharray="8 6" opacity="0.85"/>')
        add(f'<path d="M {hx + side*(whalf-4):.1f} {waist+34:.1f} C {hx + side*(whalf-40):.1f} {waist+46:.1f} {hx + side*96:.1f} {waist+60:.1f} {hx + side*86:.1f} {waist+30:.1f}" '
            f'fill="none" stroke="{DENIM_DARK}" stroke-width="3"/>')
    add(f'<path d="M {hx-4} {waist+30} L {hx-4} {crotch-6} C {hx+10} {crotch-4} {hx+30} {crotch-20} {hx+34} {waist+70}" fill="none" stroke="{STITCH}" stroke-width="3" stroke-dasharray="8 6" opacity="0.85"/>')

    # torso: the shirt (tucked in), collar and placket
    torso = (f"M {hx-half} {sh+70} C {hx-half} {sh+20} {hx-half+30} {sh} {hx-80} {sh-6} L {hx} {sh+30} L {hx+80} {sh-6} "
             f"C {hx+half-30} {sh} {hx+half} {sh+20} {hx+half} {sh+70} L {hx+whalf+4} {waist+16} L {hx-whalf-4} {waist+16} Z")
    add(f'<path d="M {hx-58*k} {neck_top} L {hx-58*k} {sh+20} C {hx-30} {sh+40} {hx+30} {sh+40} {hx+58*k} {sh+20} L {hx+58*k} {neck_top} Z" fill="{SKIN_SHADE}"/>')
    add(f'<path d="{torso}" fill="url(#stripes)"/>')
    add(f'<path d="{torso}" fill="url(#torso)"/>')
    add(f'<path d="M {hx-82} {sh-8} L {hx} {sh+30} L {hx-30} {sh+78} L {hx-100} {sh+22} Z" fill="#eef2ea" stroke="{SHIRT_STRIPE}" stroke-width="3"/>')
    add(f'<path d="M {hx+82} {sh-8} L {hx} {sh+30} L {hx+30} {sh+78} L {hx+100} {sh+22} Z" fill="#eef2ea" stroke="{SHIRT_STRIPE}" stroke-width="3"/>')
    add(f'<path d="M {hx} {sh+30} L {hx} {waist+10}" stroke="{SHIRT_SHADE}" stroke-width="4"/>')
    for i in range(3):
        add(f'<circle cx="{hx+12}" cy="{sh+110 + i*(waist-sh-140)/2:.1f}" r="7" fill="#f7f9f4" stroke="{SHIRT_STRIPE}" stroke-width="2"/>')
    # belt with loops and a silver buckle
    add(f'<rect x="{hx-whalf-6}" y="{waist-6}" width="{2*whalf+12}" height="34" rx="6" fill="url(#belt)"/>')
    for dx in (-118, -60, 60, 118):
        add(f'<rect x="{hx+dx-6}" y="{waist-10}" width="12" height="42" rx="3" fill="{DENIM}" stroke="{DENIM_DARK}" stroke-width="2"/>')
    add(f'<rect x="{hx-28}" y="{waist-12}" width="56" height="46" rx="8" fill="url(#buckle)" stroke="#6f7580" stroke-width="2"/>')
    add(f'<rect x="{hx-16}" y="{waist}" width="32" height="22" rx="4" fill="url(#belt)"/>')
    add(f'<rect x="{hx-3}" y="{waist}" width="6" height="22" fill="#c3c8d0"/>')

    # the head (scaled about its centre)
    add(f'<g transform="translate({hx} {hy}) scale({k}) translate({-hx} {-hy})">')
    head(add, hx, hy, v.hair)
    add('</g>')

    # arms. Shoulders at (hx +- 135, sh + 40); a hand hangs at the hip
    shy = sh + 44
    hip_y = waist + 40
    fx = -s                      # the free arm's side
    if v.free == "wave":
        sleeve(add, [(hx + fx*132, shy), (hx + fx*215, shy - 40), (hx + fx*258, shy - 170)])
        hand(add, hx + fx*262, shy - 210, thumb=-fx)
        for i in range(2):
            a0 = shy - 230 - i * 26
            add(f'<path d="M {hx + fx*(305 + i*22):.1f} {a0:.1f} C {hx + fx*(318 + i*22):.1f} {a0+20:.1f} {hx + fx*(318 + i*22):.1f} {a0+48:.1f} {hx + fx*(305 + i*22):.1f} {a0+68:.1f}" '
                f'fill="none" stroke="#ffffff" stroke-width="7" stroke-linecap="round" opacity="0.8"/>')
    else:
        sleeve(add, [(hx + fx*132, shy), (hx + fx*170, shy + 130), (hx + fx*178, hip_y - 20)])
        hand(add, hx + fx*180, hip_y + 8, thumb=-fx)

    hs = 0.74 * (1.0 if v.head >= 1.0 else 0.92)
    if v.pose == "tuck":
        # cradled at the hip: the upper arm behind the helmet, the forearm under its front, the hand on the near side
        cxh, cyh = hx + s*205, hip_y - 34
        sleeve(add, [(hx + s*132, shy), (hx + s*200, shy + 110), (hx + s*262, cyh + 50)])
        helmet(add, cxh, cyh, hs, flip=s > 0)
        sleeve(add, [(hx + s*262, cyh + 50), (hx + s*190, cyh + 100), (hx + s*150, cyh + 96)], width=70)
        hand(add, hx + s*138, cyh + 92, thumb=-s)
    else:
        # held against the hip: the arm hangs down behind it, the hand grips the chin bar from below
        cxh, cyh = hx + s*214, hip_y - 6
        sleeve(add, [(hx + s*132, shy), (hx + s*180, shy + 120), (hx + s*236, cyh + 40)])
        helmet(add, cxh, cyh, hs, flip=s > 0)
        if v.hand:
            hand(add, hx + s*262, cyh + 88, thumb=-s)

    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {VB_W} {VB_H}" width="{VB_W}" height="{VB_H}">\n'
            + "\n".join(parts) + "\n</svg>\n")


def render(v: Variant, out: Path, stem: str, height: int) -> Path:
    src = out / f"{stem}.svg"
    src.write_text(svg(v))
    png = out / f"{stem}.png"
    w = round(height * VB_W / VB_H)
    subprocess.run(["rsvg-convert", "-w", str(w), "-h", str(height), "-o", str(png), str(src)], check=True)
    return png


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "CambridgeRacer" / "UI" / "Generated")
    ap.add_argument("--variant", default="game", choices=sorted(VARIANTS))
    ap.add_argument("--height", type=int, default=1400)
    ap.add_argument("--all", action="store_true", help="every variant as neil_mii_<name>.png")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    if a.all:
        for name, v in VARIANTS.items():
            print("wrote", render(v, a.out, f"neil_mii_{name}", a.height))
    else:
        print("wrote", render(VARIANTS[a.variant], a.out, "neil_mii", a.height))


if __name__ == "__main__":
    main()
