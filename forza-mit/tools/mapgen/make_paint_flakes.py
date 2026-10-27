"""Tileable metallic-flake normal map for the STi car paint (under the clear coat). CC0, ours.
Usage: uv run make_paint_flakes.py   -> data/processed/common/car/paint_flakes_normal.png

Jittered-grid Voronoi flakes (periodic, so the tile repeats seamlessly). Each flake is a flat platelet
with a random tilt (half-normal, ~18 deg sigma) in a random direction; ~40 % of the area is binder
(flat normal) so the sparkle is sparse. Random tilts are symmetric, so the OpenGL/DirectX green
convention doesn't matter. The car material tiles it ~50x over the 5 m-per-UV livery atlas
(10 cm tile, ~1.5 mm flakes) and fades it out with distance (tools/unreal/shaders/carpaint.hlsl).
"""
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.spatial import cKDTree

N = 512          # texture size
CELL = 7         # px per grid cell (one flake per cell)
SIGMA = np.radians(18.0)
rng = np.random.default_rng(11)

g = N // CELL
cx, cy = np.meshgrid(np.arange(g), np.arange(g))
sites = (np.stack([cx, cy], -1).reshape(-1, 2) + rng.uniform(0.1, 0.9, (g * g, 2))) * (N / g)
tree = cKDTree(sites, boxsize=N)
py, px = np.mgrid[0:N, 0:N] + 0.5
d, idx = tree.query(np.stack([px.ravel() % N, py.ravel() % N], -1))
d, idx = d.reshape(N, N), idx.reshape(N, N)

theta = np.abs(rng.normal(0.0, SIGMA, len(sites)))
phi = rng.uniform(0.0, 2 * np.pi, len(sites))
radius = rng.uniform(0.35, 0.6, len(sites)) * (N / g)      # flake size vs cell: leaves binder between flakes
fn = np.stack([np.sin(theta) * np.cos(phi), np.sin(theta) * np.sin(phi), np.cos(theta)], -1)
n = fn[idx]
n[d > radius[idx]] = (0.0, 0.0, 1.0)
img = ((n * 0.5 + 0.5) * 255 + 0.5).astype(np.uint8)
out = Path(__file__).resolve().parents[2] / "data/processed/common/car"
out.mkdir(parents=True, exist_ok=True)
Image.fromarray(img).save(out / "paint_flakes_normal.png")
print("ok", img.shape, "flakes", len(sites), "coverage", float((d <= radius[idx]).mean()))

# --- orange peel: the clear coat's very subtle micro-waviness (tileable, periodic by FFT filtering) -----------
# Band-limited noise (wavelength ~25-60 px on the 512 tile; the car material tiles it ~60x per 5 m UV unit, so
# ~2-5 mm bumps), turned into a weak normal map. Same OpenGL/DirectX remark as above (isotropic noise).
rng2 = np.random.default_rng(23)
white = rng2.standard_normal((N, N))
fy = np.fft.fftfreq(N)[:, None]
fx = np.fft.fftfreq(N)[None, :]
f = np.sqrt(fx * fx + fy * fy)
band = np.exp(-((f - 1 / 40.0) / (1 / 80.0)) ** 2)            # peak at a 40 px wavelength
h = np.real(np.fft.ifft2(np.fft.fft2(white) * band))
h /= np.abs(h).max()
gy, gx = np.gradient(h)
# wrap-around gradient at the tile edges (periodic)
gx[:, 0] = (h[:, 1] - h[:, -1]) / 2
gx[:, -1] = (h[:, 0] - h[:, -2]) / 2
gy[0, :] = (h[1, :] - h[-1, :]) / 2
gy[-1, :] = (h[0, :] - h[-2, :]) / 2
k = 6.0                                                         # max tilt ~ a few degrees before the shader's scale
nrm = np.stack([-gx * k, gy * k, np.ones_like(h)], -1)
nrm /= np.linalg.norm(nrm, axis=-1, keepdims=True)
Image.fromarray(((nrm * 0.5 + 0.5) * 255 + 0.5).astype(np.uint8)).save(out / "paint_orangepeel_normal.png")
print("ok orange peel", nrm.shape, "max tilt deg", float(np.degrees(np.arccos(nrm[..., 2].min()))))
