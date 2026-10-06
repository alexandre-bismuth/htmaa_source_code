"""Leaf atlas with a real alpha channel for the Poly Haven jacaranda.

The glTF ships its leaf atlas as a JPEG on black (no alpha), so imported leaf cards render as
dark shards. This keys the black background out (alpha from max(R,G,B)) and dilates the leaf
colour into the cut-out area (push-pull), so mipmaps don't bleed black into the leaf edges.

Usage:  uv run make_leaf_alpha.py
Output: data/processed/common/props/jacaranda_leaves_rgba.png
"""
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "data/raw/models/jacaranda_tree/textures/jacaranda_tree_leaves_diff_2k.jpg"
OUT = ROOT / "data/processed/common/props/jacaranda_leaves_rgba.png"
KEY_LO, KEY_HI = 0.05, 0.12   # max(R,G,B) below LO -> transparent, above HI -> opaque


def push_pull(rgb, w):
    """Fill rgb where weight w == 0 with the weighted average of a coarser level (recursive)."""
    if min(rgb.shape[:2]) <= 1:
        return rgb
    h2, w2 = rgb.shape[0] // 2, rgb.shape[1] // 2
    ws = w[:h2 * 2, :w2 * 2].reshape(h2, 2, w2, 2).sum((1, 3))
    cs = (rgb[:h2 * 2, :w2 * 2] * w[:h2 * 2, :w2 * 2, None]).reshape(h2, 2, w2, 2, 3).sum((1, 3))
    coarse = np.where(ws[..., None] > 0, cs / np.maximum(ws, 1e-6)[..., None], 0.0)
    coarse = push_pull(coarse, np.minimum(ws, 1.0))
    up = np.repeat(np.repeat(coarse, 2, 0), 2, 1)
    up = np.pad(up, ((0, rgb.shape[0] - up.shape[0]), (0, rgb.shape[1] - up.shape[1]), (0, 0)), mode="edge")
    return rgb * w[..., None] + up * (1.0 - w[..., None])


def main():
    rgb = np.asarray(Image.open(SRC).convert("RGB"), dtype=np.float32) / 255.0
    alpha = np.clip((rgb.max(axis=2) - KEY_LO) / (KEY_HI - KEY_LO), 0.0, 1.0)
    # un-premultiply the dark fringe (edge pixels are leaf colour blended with black)
    colour = np.where(alpha[..., None] > 0, rgb / np.maximum(alpha, 0.35)[..., None], 0.0).clip(0, 1)
    filled = push_pull(colour, (alpha > 0.5).astype(np.float32))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    rgba = np.dstack([filled, alpha])
    Image.fromarray((rgba * 255 + 0.5).astype(np.uint8), "RGBA").save(OUT)
    print(f"{OUT}: coverage {alpha.mean():.1%}")


if __name__ == "__main__":
    main()
