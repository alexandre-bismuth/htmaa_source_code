"""Sky dome texture from the Poly Haven HDRI (tools/mapgen/fetch_sky.py).

Run:    $BLENDER -b --factory-startup -P tools/blender/make_sky.py
Output: data/processed/common/sky/sky.exr  (equirect, linear half float, read by tools/unreal/build_level.py)
        data/processed/common/sky/sky.json (sun position in the image, sky levels)
- The sun disc is clamped to a bright glow: the directional light is the sun (in the sky light it would light the
  shade a second time, from the sun's side).
- Below the horizon the "puresky" edit is a blurred mirror image: replaced by the horizon colour, darkening downwards
  (seen only past the edge of the map).
"""
import json
import math
from pathlib import Path

import bpy
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "data/raw/sky/rustig_koppie_puresky_8k.hdr"   # tools/mapgen/fetch_sky.py ASSET
OUT = ROOT / "data/processed/common/sky"
SUN_CAP = 6.0      # sun disc capped at this many times the brightest cloud tops (99.9th percentile of the sky)
SUN_YAW = -40.0    # where the game puts the photo's sun (the light's yaw: the sun stands in the south-west)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    img = bpy.data.images.load(str(SRC))
    w, h = img.size
    px = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(px)
    rgb = px.reshape(h, w, 4)[::-1, :, :3].copy()     # Blender rows are bottom-up: row 0 = zenith here
    del px
    lum = rgb @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    upper = lum[: h // 2]

    # the sun: centroid of the brightest pixels
    thr = np.partition(upper.ravel(), -400)[-400]
    ys, xs = np.nonzero(upper >= thr)
    u_sun, v_sun = (xs.mean() + 0.5) / w, (ys.mean() + 0.5) / h
    elev = 90.0 - v_sun * 180.0

    # clamp the disc (keep the hue)
    away = upper[:, :]
    clouds = float(np.percentile(away[::4, ::4], 99.9))
    cap = SUN_CAP * clouds
    scale = np.minimum(1.0, cap / np.maximum(lum, 1e-6))
    rgb *= scale[..., None]

    # below the horizon: horizon colour per column (the 2 degrees above it), smoothed, fading to 45 % over 25 degrees
    hz = h // 2
    band = rgb[hz - int(h * 2 / 180): hz].mean(axis=0)               # (w, 3)
    k = 64
    pad = np.concatenate([band[-k:], band, band[:k]])
    kernel = np.ones(2 * k + 1, np.float32) / (2 * k + 1)
    band = np.stack([np.convolve(pad[:, c], kernel, "same")[k:-k] for c in range(3)], -1)
    rows = np.arange(h - hz, dtype=np.float32)[:, None, None]
    fade = 1.0 - 0.55 * np.clip(rows / (h * 25 / 180), 0.0, 1.0)
    rgb[hz:] = band[None] * fade
    # soften the seam at the horizon over 1 degree
    s = int(h / 180)
    t = np.linspace(0.0, 1.0, s, dtype=np.float32)[:, None, None]
    rgb[hz - s: hz] = rgb[hz - s: hz] * (1 - t) + band[None] * t

    sky = float(np.median(lum[int(h * 0.1): int(h * 0.4): 4, ::4]))    # median sky (10-70 deg up), before the clamp
    out = bpy.data.images.new("sky", w, h, alpha=True, float_buffer=True)
    rgba = np.concatenate([rgb, np.ones((h, w, 1), np.float32)], -1)[::-1]
    out.pixels.foreach_set(rgba.ravel())
    scene = bpy.context.scene
    scene.view_settings.view_transform = "Standard"
    s_ = scene.render.image_settings
    s_.file_format = "OPEN_EXR"
    s_.color_depth = "16"
    s_.exr_codec = "ZIP"
    s_.color_mode = "RGB"
    out.save_render(str(OUT / "sky.exr"), scene=scene)
    meta = {"source": SRC.name, "license": "CC0 (Poly Haven: Greg Zaal, sky edit Jarod Guest)", "size": [w, h],
            "sun_u": round(u_sun, 5), "sun_v": round(v_sun, 5), "sun_elevation_deg": round(elev, 2), "sun_yaw_deg": SUN_YAW,
            "median_sky": sky, "cloud_tops": clouds, "sun_cap": cap}
    (OUT / "sky.json").write_text(json.dumps(meta, indent=2))
    print("SKY", json.dumps(meta))


main()
