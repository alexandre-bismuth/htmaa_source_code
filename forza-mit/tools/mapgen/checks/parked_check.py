"""Offline check of the parked cars in data/processed/<region>/props/props.json (props.py place_parked) against the
events in CambridgeRacer/Tracks/<region>.json and the map, measured on each car's footprint rectangle (length x width
incl. mirrors, from data/processed/common/props/parked_cars.json), not its centre:
  - distance to every event's racing line (polyline, circuits closed) >= MIN_LINE_M
  - outside every gate band (gate width + SIDE_M across, ALONG_M each side along the route) and every start box
    (start grid -> start line, + START_M), and >= SPAWN_M from the free-roam start and the PlayerStart
  - body on the carriageway (kerbside cars) or in a lot / on the ground (lot cars), not in a building, no two cars
    overlapping
Prints a summary (exit code 1 on any violation) and writes data/processed/<region>/checks/parked_<view>.png.
The margins are independent of props.py's constants on purpose (this is the referee).
Usage (tools/mapgen): uv run checks/parked_check.py mit_core"""
import json
import math
import sys

sys.path.insert(0, ".")
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from shapely.geometry import LineString, Point, Polygon, shape
from shapely.ops import unary_union
from shapely.prepared import prep
from shapely.strtree import STRtree

from geo import ROOT

MIN_LINE_M, ALONG_M, SIDE_M, START_M, SPAWN_M = 3.5, 4.5, 2.5, 10.0, 20.0
region = sys.argv[1] if len(sys.argv) > 1 else "mit_core"
rdir = ROOT / "data/processed" / region
load = lambda l: json.loads((rdir / f"{l}.geojson").read_text())["features"]
fleet = json.loads((ROOT / "data/processed/common/props/parked_cars.json").read_text())["types"]
props = json.loads((rdir / "props/props.json").read_text())
cars = [p for p in props if p["type"].startswith("parked_")]
tracks = json.loads((ROOT / f"CambridgeRacer/Tracks/{region}.json").read_text())
en = lambda x, y: (x / 100.0, -y / 100.0)


def rect(cx, cy, yaw_ue, L, W):
    a = math.radians(-yaw_ue)
    hx, hy = math.cos(a), math.sin(a)
    return Polygon([(cx + hx * L / 2 * s1 - hy * W / 2 * s2, cy + hy * L / 2 * s1 + hx * W / 2 * s2)
                    for s1, s2 in ((1, 1), (-1, 1), (-1, -1), (1, -1))])


feet, bodies = [], []
for c in cars:
    t = fleet[c["type"][7:]]
    wm = 2 * max(abs(t["bounds_m"][0][1]), t["bounds_m"][1][1])
    cx, cy = en(c["x"], c["y"])
    feet.append(rect(cx, cy, c["yaw"], t["length_m"], wm))
    bodies.append(rect(cx, cy, c["yaw"], t["length_m"], t["width_m"]))
lines, gates, starts = {}, [], []
for t in tracks["tracks"]:
    pts = [en(p[0], p[1]) for p in t["line"]]
    if t["type"] == "circuit":
        pts.append(pts[0])
    lines[t["id"]] = LineString(pts)
    for g in t["gates"]:
        c = en(g["x"], g["y"])
        gates.append((t["id"], rect(c[0], c[1], g["yaw"], 2 * ALONG_M, g["width"] / 100.0 + 2 * SIDE_M)))
    s0, g0 = np.array(en(t["start"]["x"], t["start"]["y"])), t["gates"][0]
    c1 = np.array(en(g0["x"], g0["y"]))
    d = c1 - s0
    yaw = -math.degrees(math.atan2(d[1], d[0])) if np.linalg.norm(d) > 0.1 else g0["yaw"]
    mid = (s0 + c1) / 2
    starts.append((t["id"], rect(mid[0], mid[1], yaw, float(np.linalg.norm(d)) + 2 * START_M, g0["width"] / 100.0 + 2 * SIDE_M)))
spawns = [Point(en(tracks["free_roam"]["x"], tracks["free_roam"]["y"]))]
mf = rdir / "meshes/manifest.json"
if mf.exists():
    sp = json.loads(mf.read_text())["spawn"]["ue_cm"]
    spawns.append(Point(en(sp[0], sp[1])))

roads_l = [(shape(f["geometry"]).buffer(0), f["properties"].get("TYPE")) for f in load("BASEMAP_Roads") if f.get("geometry")]
cw = unary_union([g for g, t in roads_l if t != "RD-TRAF-ISLAND"]).difference(unary_union([g for g, t in roads_l if t == "RD-TRAF-ISLAND"]))
cw_p = prep(cw.buffer(0.05))
blds = prep(unary_union([shape(f["geometry"]).buffer(0) for f in load("BASEMAP_Buildings") if f.get("geometry")]).buffer(-0.2))

bad = {"line": [], "gate": [], "start": [], "spawn": [], "kerbside_off_road": [], "building": [], "overlap": []}
min_line = []
ltree = STRtree(list(lines.values()))
lnames = list(lines)
for k, (c, fp, bd) in enumerate(zip(cars, feet, bodies)):
    near = ltree.query(fp.buffer(MIN_LINE_M + 5))
    d = min([fp.distance(lines[lnames[i]]) for i in near] or [99.0])
    min_line.append(d)
    if d < MIN_LINE_M:
        bad["line"].append((k, round(d, 2)))
    for tid, g in gates:
        if g.intersects(fp):
            bad["gate"].append((k, tid))
    for tid, s in starts:
        if s.intersects(fp):
            bad["start"].append((k, tid))
    if any(sp.distance(fp) < SPAWN_M for sp in spawns):
        bad["spawn"].append(k)
    if c.get("src") != "lot" and not cw_p.contains(bd):
        bad["kerbside_off_road"].append(k)
    if blds.intersects(bd):
        bad["building"].append(k)
btree = STRtree(bodies)
for k, bd in enumerate(bodies):
    for j in btree.query(bd):
        if j > k and bodies[j].intersection(bd).area > 0.05:
            bad["overlap"].append((k, int(j)))

src = {}
for c in cars:
    src[c.get("src", "?")] = src.get(c.get("src", "?"), 0) + 1
types = {}
for c in cars:
    types[c["type"]] = types.get(c["type"], 0) + 1
ml = np.array(min_line) if min_line else np.array([99.0])
print(f"parked cars: {len(cars)}  by source {dict(sorted(src.items()))}")
print(f"by type {dict(sorted(types.items()))}")
print(f"racing-line clearance (footprint incl. mirrors -> nearest line of {len(lines)} events): min {ml.min():.2f} m, "
      f"p1 {np.percentile(ml, 1):.2f} m, within 6 m: {(ml < 6).sum()}")
viol = 0
for k, v in bad.items():
    print(f"  {k:18s} {len(v):5d}  {v[:6] if v else ''}")
    viol += len(v)
print("RESULT", "OK" if viol == 0 else f"{viol} VIOLATIONS")

# plots round each event start + a few street views
OUT = rdir / "checks"
OUT.mkdir(parents=True, exist_ok=True)
views = {"central": (-120, -330, 180, -30), "harvard": (-1350, 550, -1050, 850), "kendall": (1300, -650, 1600, -350),
         "cport": (-480, -1030, -220, -770), "mit": (800, -1150, 1100, -850)}
fig, axs = plt.subplots(1, len(views), figsize=(8 * len(views), 8))
for ax, (name, bb) in zip(axs, views.items()):
    for g in getattr(cw, "geoms", [cw]):
        if g.bounds[2] < bb[0] or g.bounds[0] > bb[2] or g.bounds[3] < bb[1] or g.bounds[1] > bb[3]:
            continue
        x, y = g.exterior.xy
        ax.fill(x, y, color="#ccc", lw=0)
        for h in g.interiors:
            x, y = h.xy
            ax.fill(x, y, color="white", lw=0)
    for tid, g in gates + starts:
        x, y = g.exterior.xy
        ax.fill(x, y, color="#fc8", alpha=0.5, lw=0)
    for l in lines.values():
        x, y = l.xy
        ax.plot(x, y, "k-", lw=0.7)
    for fp, c in zip(feet, cars):
        if bb[0] - 10 < fp.centroid.x < bb[2] + 10 and bb[1] - 10 < fp.centroid.y < bb[3] + 10:
            x, y = fp.exterior.xy
            ax.fill(x, y, color={"meter": "red", "lot": "green", "resid": "blue", "arterial": "purple"}.get(c.get("src"), "orange"), lw=0)
    ax.set_xlim(bb[0], bb[2])
    ax.set_ylim(bb[1], bb[3])
    ax.set_aspect("equal")
    ax.set_title(name)
plt.tight_layout()
plt.savefig(OUT / "parked_views.png", dpi=70)
sys.exit(0 if viol == 0 else 1)
