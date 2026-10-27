"""Tileable water normal map (CC0, ours) for tools/unreal/shaders/water.hlsl.
Usage: uv run make_water_normal.py
  -> data/processed/common/water_waves.png   wind ripples: Phillips spectrum (wind along +x, short crests),
     one tile = WAVES_TILE_M of water surface (water.hlsl tiles it at 0.9, 2.9 and 8.5 m: three octaves).
     RG = slope normal (DirectX convention like the Poly Haven sets), B = z, A = 0.5 + height / 2 (normalised, for
     foam / sparkle masks).
"""
from pathlib import Path

import numpy as np
from PIL import Image

OUT = Path(__file__).resolve().parents[2] / "data/processed/common"


WAVES_TILE_M = 4.0


def waves(N=1024, tile_m=WAVES_TILE_M, wind_ms=1.2, rms_slope=0.16, seed=11):
    rng = np.random.default_rng(seed)
    f = np.fft.fftfreq(N, d=tile_m / N)                       # cycles per metre
    kx, ky = np.meshgrid(2 * np.pi * f, 2 * np.pi * f)        # kx along x (columns)
    k = np.hypot(kx, ky)
    L = wind_ms ** 2 / 9.81    # slope spectrum peaks at ~2 pi L (~0.9 m at 1.2 m/s): several ripples per tile, so the
                               # tile's own fundamental does not dominate (at 3 m/s it did: coarse streaks)
    kk = np.maximum(k, 1e-6)
    cosw = kx / kk
    # short-crested ripples: broad directional spread (cos^2 alone gave long parallel crests that read as streaks
    # at grazing angles), some energy upwind
    ph = np.exp(-1.0 / (kk * L) ** 2) / kk ** 4 * (0.3 + 0.7 * cosw ** 2) * np.exp(-(kk * 0.012) ** 2)   # damp < ~1 cm
    ph[cosw < 0] *= 0.5
    ph[0, 0] = 0.0
    amp = np.sqrt(ph / 2.0)
    hk = amp * (rng.normal(size=(N, N)) + 1j * rng.normal(size=(N, N)))
    h = np.real(np.fft.ifft2(hk))
    sx = np.real(np.fft.ifft2(1j * kx * hk))
    sy = np.real(np.fft.ifft2(1j * ky * hk))
    s = rms_slope / np.sqrt((sx ** 2 + sy ** 2).mean())
    sx, sy = sx * s, sy * s
    n = np.stack([-sx, sy, np.ones_like(sx)], -1)              # image rows go down = -y in the DX convention
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    hn = (h - h.mean()) / (4.0 * h.std())
    rgba = np.concatenate([n * 0.5 + 0.5, (0.5 + hn[..., None] / 2.0).clip(0, 1)], -1)
    Image.fromarray((rgba * 255 + 0.5).clip(0, 255).astype(np.uint8), "RGBA").save(OUT / "water_waves.png")
    print(f"water_waves.png {N} px = {tile_m} m, wind {wind_ms} m/s (L {L:.2f} m), rms slope {rms_slope}")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    waves()
