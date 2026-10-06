"""Generate a tileable water normal map (filtered noise heightfield -> normals). CC0, ours.
Usage: uv run make_water_normal.py   -> data/processed/common/water_normal.png"""
from pathlib import Path
import numpy as np
from PIL import Image

N = 1024
rng = np.random.default_rng(7)
k = np.fft.fftfreq(N)[:, None] ** 2 + np.fft.fftfreq(N)[None, :] ** 2
spec = (rng.normal(size=(N, N)) + 1j * rng.normal(size=(N, N))) * np.exp(-k * 900.0) * (k > 0) / np.maximum(k, 1e-6) ** 0.25
h = np.real(np.fft.ifft2(spec))
h = (h - h.min()) / (h.max() - h.min())
gx = (np.roll(h, -1, 1) - np.roll(h, 1, 1)) * 6.0
gy = (np.roll(h, -1, 0) - np.roll(h, 1, 0)) * 6.0
n = np.stack([-gx, -gy, np.ones_like(h)], -1)
n /= np.linalg.norm(n, axis=-1, keepdims=True)
out = Path(__file__).resolve().parents[2] / "data/processed/common"
out.mkdir(parents=True, exist_ok=True)
Image.fromarray(((n * 0.5 + 0.5) * 255).astype(np.uint8)).save(out / "water_normal.png")
print("ok")
