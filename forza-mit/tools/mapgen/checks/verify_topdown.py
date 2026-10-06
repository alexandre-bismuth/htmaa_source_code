"""Offline top-down renders of a region's EXPORTED meshes (data/processed/<region>/meshes/*.glb), for checking
Stage B without opening the game.

Usage (from tools/mapgen):  uv run checks/verify_topdown.py mit_core <out_dir>
Writes:
  overview.png      whole play area + ring: roads, facades coloured by facade style, boundary walls (red),
                    region polygon (dashed), spawn, event starts, the Cambridge St underpass location
  zoom_*.png        the same at street scale with the orthophoto underneath
"""
import json
import struct
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import LineCollection, PolyCollection
from PIL import Image

sys.path.insert(0, ".")
from geo import ROOT, region_polygon  # noqa: E402

Image.MAX_IMAGE_PIXELS = None
STYLE_COL = {"brick_red": "#c0392b", "brick_buff": "#e0a458", "brick_georgian": "#ff2d95", "limestone": "#d8d2b8",
             "concrete": "#8e9aa6", "glass": "#3fa7ff", "metal": "#5f6b7a", "siding": "#7fd36b", "wall": "#6d4c41"}
GROUND_COL = {"road": "#3a3f47", "ground_grass": "#1f3b28", "ground_sidewalk": "#6b6f74", "ground_paved": "#565a60",
              "ground_parking": "#4a4d52", "water": "#1d4f8f"}


def read_glb(path):
    b = path.read_bytes()
    jl = struct.unpack_from("<I", b, 12)[0]
    doc = json.loads(b[20:20 + jl])
    bin_off = 20 + jl + 8
    acc = doc["accessors"]; views = doc["bufferViews"]
    prim = doc["meshes"][0]["primitives"][0]

    def arr(i, dt, n):
        a, v = acc[i], views[acc[i]["bufferView"]]
        return np.frombuffer(b, dt, a["count"] * n, bin_off + v["byteOffset"]).reshape(-1, n) if n > 1 else \
            np.frombuffer(b, dt, a["count"], bin_off + v["byteOffset"])
    pos = arr(prim["attributes"]["POSITION"], np.float32, 3)
    idx = arr(prim["indices"], np.uint32, 1).reshape(-1, 3)
    en = np.column_stack([pos[:, 0], -pos[:, 2], pos[:, 1]]).astype(np.float64)   # glTF (E, Up, S) -> E, N, U
    return en, idx


def load_class(mdir, cls, pivot):
    tris = []
    for p in sorted(mdir.glob(f"{cls}__*.glb")):
        en, idx = read_glb(p)
        en[:, 0] += pivot[0]; en[:, 1] += pivot[1]
        tris.append(en[idx])
    return np.concatenate(tris) if tris else np.zeros((0, 3, 3))


def wall_segments(tris):
    """Vertical facade triangles -> their horizontal extent as a 2D segment (top-down outline)."""
    xy = tris[:, :, :2]
    d01 = np.linalg.norm(xy[:, 0] - xy[:, 1], axis=1); d12 = np.linalg.norm(xy[:, 1] - xy[:, 2], axis=1)
    d02 = np.linalg.norm(xy[:, 0] - xy[:, 2], axis=1)
    k = np.argmax(np.column_stack([d01, d12, d02]), axis=1)
    a = np.where(k[:, None] == 1, xy[:, 1], xy[:, 0]); b = np.where(k[:, None] == 0, xy[:, 1], xy[:, 2])
    keep = np.maximum(np.maximum(d01, d12), d02) > 0.3
    return np.stack([a[keep], b[keep]], 1)


def main(region, out):
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    rdir = ROOT / "data/processed" / region; mdir = rdir / "meshes"
    man = json.loads((mdir / "manifest.json").read_text()); pivot = man["pivot_en_m"]
    rp = region_polygon(region)
    classes = sorted({p.name.split("__")[0] for p in mdir.glob("*.glb")})
    data = {c: load_class(mdir, c, pivot) for c in classes}
    tracks = ROOT / "CambridgeRacer/Tracks" / f"{region}.json"
    alt = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    tr = json.loads((alt or tracks).read_text())["tracks"] if (alt or tracks).exists() else []
    meta = json.loads((rdir / "ortho/ortho.json").read_text())
    ortho = Image.open(rdir / "ortho/ortho.jpg")

    def draw(ax, bounds, lw_scale=1.0, with_ortho=False, ground=True, ctx=True):
        e0, n0, e1, n1 = bounds
        if with_ortho:
            r = meta["m_per_px"]
            c0, r0 = int((e0 - meta["east_min_m"]) / r), int((meta["north_max_m"] - n1) / r)
            crop = ortho.crop((c0, r0, c0 + int((e1 - e0) / r), r0 + int((n1 - n0) / r)))
            ax.imshow(crop, extent=(e0, e1, n0, n1), alpha=0.55, zorder=0)
        if ground:
            for c, col in GROUND_COL.items():
                for pre in ([""] + (["ctx_"] if ctx else [])):
                    t = data.get(pre + c)
                    if t is not None and len(t):
                        sel = (t[:, :, 0].max(1) > e0) & (t[:, :, 0].min(1) < e1) & (t[:, :, 1].max(1) > n0) & (t[:, :, 1].min(1) < n1)
                        ax.add_collection(PolyCollection(t[sel][:, :, :2], fc=col, ec="none", alpha=0.55 if with_ortho else (1.0 if not pre else 0.6), zorder=1))
        for pre, alpha in (("ctx_", 0.55), ("", 1.0)):
            if pre and not ctx:
                continue
            for s, col in STYLE_COL.items():
                t = data.get(f"{pre}facade_{s}")
                if t is None or not len(t):
                    continue
                sel = (t[:, :, 0].max(1) > e0) & (t[:, :, 0].min(1) < e1) & (t[:, :, 1].max(1) > n0) & (t[:, :, 1].min(1) < n1)
                ax.add_collection(LineCollection(wall_segments(t[sel]), colors=col, lw=0.6 * lw_scale, alpha=alpha, zorder=3))
        b = data.get("boundary")
        if b is not None and len(b):
            ax.add_collection(LineCollection(wall_segments(b), colors="#ff1744", lw=1.6 * lw_scale, zorder=5))
        x, y = rp.exterior.xy
        ax.plot(x, y, color="white", lw=0.6, ls="--", zorder=6)
        sp = man["spawn"]["en_m"]; ax.plot(*sp, marker="*", ms=14, color="yellow", mec="k", zorder=8)
        for i, t in enumerate(tr):
            s = t["start"]; ax.plot(s["x"] / 100, -s["y"] / 100, marker="o", ms=6, color="#00e5ff" if i >= 6 else "#ffd600", mec="k", zorder=8)
            if e0 < s["x"] / 100 < e1 and n0 < -s["y"] / 100 < n1:
                ax.text(s["x"] / 100 + 15, -s["y"] / 100 + 15, f"{i}:{t['id']}", fontsize=7, color="w", zorder=9,
                        bbox=dict(fc="k", ec="none", alpha=0.6, pad=1))
        ax.plot(-1020, 980, marker="x", ms=12, mew=2.5, color="#ff9100", zorder=8)
        ax.set_xlim(e0, e1); ax.set_ylim(n0, n1); ax.set_aspect("equal"); ax.set_facecolor("#0b0d11")

    # overview
    e0, n0, e1, n1 = rp.bounds
    fig, ax = plt.subplots(figsize=(22, 20), dpi=110)
    draw(ax, (e0 - 300, n0 - 250, e1 + 300, n1 + 300), lw_scale=0.5)
    from matplotlib.lines import Line2D
    ax.legend(handles=[Line2D([], [], color=c, lw=3, label=s) for s, c in STYLE_COL.items()] +
              [Line2D([], [], color="#ff1744", lw=3, label="boundary wall"),
               Line2D([], [], color="w", ls="--", label="region polygon"),
               Line2D([], [], marker="*", color="yellow", ls="", ms=12, label="spawn"),
               Line2D([], [], marker="o", color="#ffd600", ls="", label="Stage A event start"),
               Line2D([], [], marker="o", color="#00e5ff", ls="", label="new event start"),
               Line2D([], [], marker="x", color="#ff9100", ls="", ms=10, label="Cambridge St underpass (removed)")],
              loc="lower left", fontsize=11, facecolor="#222", labelcolor="w")
    st = man["buildings"]["styles"]
    ax.set_title(f"{region}: exported meshes top-down (facade colour = style; ctx ring faded)  styles {st}", fontsize=11)
    fig.savefig(out / "overview.png", bbox_inches="tight"); plt.close(fig)
    print("wrote", out / "overview.png")

    zooms = {"harvard_yard": (-1150, 880, 330), "harvard_sq_river": (-1150, 450, 420), "underpass": (-1040, 975, 140),
             "east_cambridge_blocks": (1840, 210, 170), "somerville_edge": (-300, 1500, 450), "cambridgeport": (-150, -900, 380),
             "radcliffe_quad": (-1550, 1650, 330), "bu_bridge": (-520, -1450, 220), "inman_north_wall": (220, 760, 330)}
    for name, (ce, cn, h) in zooms.items():
        fig, ax = plt.subplots(figsize=(12, 12), dpi=110)
        draw(ax, (ce - h, cn - h, ce + h, cn + h), lw_scale=1.6, with_ortho=True)
        ax.set_title(f"{region} {name} @ EN ({ce}, {cn}); facade colour = style, red = boundary wall", fontsize=10)
        fig.savefig(out / f"zoom_{name}.png", bbox_inches="tight"); plt.close(fig)
        print("wrote", out / f"zoom_{name}.png")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
