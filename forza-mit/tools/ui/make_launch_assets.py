"""Images for the launch menu (SCambridgeLaunchScreen), into CambridgeRacer/UI/Generated (gitignored):

    launch_bg.png   2560 x 1440: the STi in front of the MIT buildings (docs/figures/01), softly blurred, darkened on the
                    left behind the title and buttons and along the bottom behind the key bar
    neil_mii.png    Neil as a full-body Mii carrying the driver's helmet (make_neil_mii.py, --variant), cropped to the
                    figure and padded on the left to NEIL_ASPECT (width / height): the game draws it NEIL_SIZE at 1080p,
                    right- and bottom-anchored (SCambridgeLaunchScreen)
and the engine's startup splash, CambridgeRacer/Content/Splash/Splash.bmp (gitignored with Content/): shown by macOS
from the double-click until the game window opens with the launch menu (drop -nosplash from the command line)

    cd tools/ui && uv run make_launch_assets.py [--variant game|classic|tucked|wave|tall]

Needs rsvg-convert (brew install librsvg) for the Mii. The approval mockup is make_launch_mockups.py (design D).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

import make_neil_mii
from uidraw import GENERATED, Canvas, draw_text, hexc, hgrad, vgrad

ROOT = Path(__file__).resolve().parents[2]
BG_SOURCE = ROOT / "docs" / "figures" / "01_car_front_three_quarter.jpg"
W, H = 2560, 1440
NEIL_ASPECT = 0.5          # keep in step with CUI_IMAGE("neil_mii", 434, 868) in CambridgeUIStyle.cpp


def backdrop() -> Image.Image:
    im = Image.open(BG_SOURCE).convert("RGB").resize((W, H), Image.Resampling.LANCZOS)
    im = im.filter(ImageFilter.GaussianBlur(2.7)).convert("RGBA")
    shade = Canvas(W, H)
    shade.paint(hgrad(W, H, [(0, hexc("#000814", 0.78)), (0.42, hexc("#000814", 0.35)), (0.6, hexc("#000814", 0.0)),
                             (1, hexc("#000814", 0.25))]), 1.0)
    bottom = np.zeros((H, W, 4), np.float32)
    bottom[H - 400:] = vgrad(W, 400, [(0, hexc("#000814", 0.0)), (1, hexc("#000814", 0.6))])
    shade.paint(bottom, 1.0)
    im.alpha_composite(shade.image())
    return im.convert("RGB")


def splash(bg: Image.Image) -> Image.Image:
    """640 x 360: the launch menu's backdrop with the title, like a small window of the menu."""
    w, h = 640, 360
    im = bg.resize((w, h), Image.Resampling.LANCZOS).convert("RGBA")
    white, navy = hexc("#ffffff"), hexc("#0a246a")
    x = 36
    x += draw_text(im, (x, 92), "FORZA ", "pixel", 40, white, bold=True, shadow=navy, shadow_offset=(2, 2))
    x += draw_text(im, (x, 96), "@", "digits", 30, white, shadow=navy, shadow_offset=(2, 2))
    draw_text(im, (x, 92), " MIT", "pixel", 40, white, bold=True, shadow=navy, shadow_offset=(2, 2))
    draw_text(im, (38, 120), "CAMBRIDGE, MASSACHUSETTS", "cond", 13, hexc("#c9d6f2"), tracking=2)
    draw_text(im, (38, 326), "STARTING THE ENGINE...", "pixel", 12, white, shadow=hexc("#000000", 0.7))
    return im.convert("RGB")


def crop_figure(png: Path) -> None:
    """Crop the Mii to its pixels (+4 px), then pad on the left (or the top) to NEIL_ASPECT, the brush's aspect."""
    im = Image.open(png).convert("RGBA")
    x0, y0, x1, y1 = im.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
    x0, y0, x1, y1 = max(0, x0 - 4), max(0, y0 - 4), min(im.width, x1 + 4), min(im.height, y1 + 4)
    fig = im.crop((x0, y0, x1, y1))
    w, h = fig.size
    tw, th = (round(h * NEIL_ASPECT), h) if w / h < NEIL_ASPECT else (w, round(w / NEIL_ASPECT))
    out = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    out.alpha_composite(fig, (tw - w, th - h))       # (right and bottom aligned: the feet and the right edge stay put)
    out.save(png, optimize=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="game", choices=sorted(make_neil_mii.VARIANTS))
    ap.add_argument("--out", type=Path, default=GENERATED)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    bg = backdrop()
    bg.save(a.out / "launch_bg.png", optimize=True)
    print("wrote", a.out / "launch_bg.png")
    splash_dir = ROOT / "CambridgeRacer" / "Content" / "Splash"
    splash_dir.mkdir(parents=True, exist_ok=True)
    splash(bg).save(splash_dir / "Splash.bmp")
    print("wrote", splash_dir / "Splash.bmp")
    png = make_neil_mii.render(make_neil_mii.VARIANTS[a.variant], a.out, "neil_mii", 1400)
    crop_figure(png)
    print("wrote", png)


if __name__ == "__main__":
    main()
