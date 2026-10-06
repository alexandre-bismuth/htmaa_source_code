"""Offline time-trial event check (what a human player experiences), for every event in CambridgeRacer/Tracks/<region>.json:
  - the start grid is on the drivable road and inside the playable region
  - every gate: centre on the road, the checkpoint trigger reaches the road edge on both sides (driving round a post
    still counts), posts not inside a building, gate across the route (heading vs racing line), racing line passes through it, gates in route order
  - spacing between consecutive gates; racing line on the road surface (share of points), no point inside a building
  - the route stays inside the playable region (never behind an invisible wall)
Writes a per-event table and data/processed/<region>/checks/events_<id>.png.
Usage (tools/mapgen): uv run checks/gate_check.py mit_core"""
import json, math, sys
sys.path.insert(0, ".")
import numpy as np
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
from shapely.geometry import Point, LineString
from shapely.ops import unary_union
from shapely.prepared import prep
import build_meshes as bm
from geo import ROOT, region_polygon

region = sys.argv[1] if len(sys.argv) > 1 else "mit_core"
rdir = ROOT / "data/processed" / region
OUT = ROOT / "data/processed" / (sys.argv[1] if len(sys.argv) > 1 else "mit_core") / "checks"
OUT.mkdir(parents=True, exist_ok=True)
roads_l = bm.load(rdir, "BASEMAP_Roads")
paved = unary_union([g for g, p in roads_l if p.get("TYPE") != "RD-TRAF-ISLAND"])
islands = unary_union([g for g, p in roads_l if p.get("TYPE") == "RD-TRAF-ISLAND"])
drivable = paved.difference(islands)
drv = prep(drivable); drv_pad = prep(drivable.buffer(0.6))
blds = unary_union([g for g, _ in bm.load(rdir, "BASEMAP_Buildings")]); bld = prep(blds)
rp = region_polygon(region); rpp = prep(rp)
tracks = json.loads((ROOT / f"CambridgeRacer/Tracks/{region}.json").read_text())["tracks"]
en = lambda x, y: (x / 100.0, -y / 100.0)
problems_total = 0
print(f"{'#':>2} {'id':20s} {'len m':>6} {'gates':>5} {'spacing min/med/max m':>22} {'line on road':>12} {'issues'}")
for k, t in enumerate(tracks):
    issues = []
    sg = Point(en(t["start"]["x"], t["start"]["y"]))
    if not drv.contains(sg): issues.append("start grid off the road")
    if not rpp.contains(sg): issues.append("start grid outside region")
    line = np.array([en(p[0], p[1]) for p in t["line"]])
    L = LineString(line if t["type"] != "circuit" else np.vstack([line, line[:1]]))
    on_road = np.mean([drv_pad.contains(Point(p)) for p in line])
    in_bld = sum(bld.contains(Point(p)) for p in line)
    out_reg = sum(not rpp.contains(Point(p)) for p in line)
    if on_road < 0.97: issues.append(f"line only {on_road:.0%} on road")
    if in_bld: issues.append(f"{in_bld} line pts in buildings")
    if out_reg: issues.append(f"{out_reg} line pts outside region")
    gs = t["gates"]; s_prev = -1.0; spac = []; prev = None
    for i, g in enumerate(gs):
        c = np.array(en(g["x"], g["y"])); yaw = math.radians(g["yaw"])
        fwd = np.array([math.cos(yaw), -math.sin(yaw)])              # UE yaw -> EN heading (Y south)
        left = np.array([-fwd[1], fwd[0]]); w = g["width"] / 200.0
        a, b = c + left * w, c - left * w
        tag = f"g{i}"
        if not drv_pad.contains(Point(c)): issues.append(f"{tag} centre off road")
        # the checkpoint trigger (tracks.py trigger_span; the game's CrossedGate) reaches across the road at the gate,
        # past the posts where the road is wider than the gate (gates are sized to the narrowest section nearby)
        tl, tr = (v / 100.0 for v in g.get("trigger", [g["width"] / 2] * 2))
        for name, post, end in (("L", a, c + left * max(w, tl)), ("R", b, c - left * max(w, tr))):
            # a trigger ending well inside the carriageway: a player driving round that end misses the checkpoint
            if drivable.buffer(-1.5).contains(Point(end)): issues.append(f"{tag} checkpoint end {name} inside the carriageway")
            if bld.contains(Point(post)): issues.append(f"{tag} post {name} in a building")
        s = L.project(Point(c)); d = L.distance(Point(c))
        if d > w - 1.0: issues.append(f"{tag} line {d:.1f} m from centre (half width {w:.1f})")
        q0, q1 = L.interpolate(max(s - 3, 0)), L.interpolate(min(s + 3, L.length))
        h = math.atan2(q1.y - q0.y, q1.x - q0.x)
        dh = abs((h - math.atan2(fwd[1], fwd[0]) + math.pi) % (2 * math.pi) - math.pi)
        if math.degrees(dh) > 35: issues.append(f"{tag} heading {math.degrees(dh):.0f} deg off the route")
        if i > 0 and s < s_prev - 1 and not (t["type"] == "circuit" and i == len(gs) - 1): issues.append(f"{tag} out of order")
        if prev is not None: spac.append(float(np.linalg.norm(c - prev)))
        s_prev, prev = s, c
    sp = (min(spac), float(np.median(spac)), max(spac)) if spac else (0, 0, 0)
    if sp[2] > 160: issues.append(f"gap {sp[2]:.0f} m")
    problems_total += len(issues)
    print(f"{k:>2} {t['id']:20s} {t['length_m']:>6.0f} {len(gs):>5} {sp[0]:>6.0f}/{sp[1]:>5.0f}/{sp[2]:>6.0f}      {on_road:>8.1%}   {'; '.join(issues) if issues else 'OK'}")
    if k >= 6:
        e0, n0 = line.min(0) - 80; e1, n1 = line.max(0) + 80
        fig, ax = plt.subplots(figsize=(10, 10 * (n1 - n0) / max(e1 - e0, 1)), dpi=90)
        from matplotlib.patches import PathPatch
        from matplotlib.path import Path as MPath
        from shapely.geometry import box
        win = box(e0, n0, e1, n1)
        for q in bm.polys(drivable.intersection(win)):
            ax.add_patch(PathPatch(MPath.make_compound_path(*[MPath(np.asarray(r.coords)) for r in [q.exterior, *q.interiors]]), fc="#9aa3ad", ec="none"))
        for q in bm.polys(blds.intersection(win)):
            ax.fill(*q.exterior.xy, fc="#c97b63", ec="none", alpha=0.7)
        ax.plot(*rp.exterior.xy, color="red", lw=1.5)
        ax.plot(line[:, 0], line[:, 1], color="#1565c0", lw=1.5)
        for i, g in enumerate(gs):
            c = np.array(en(g["x"], g["y"])); yaw = math.radians(g["yaw"]); fwd = np.array([math.cos(yaw), -math.sin(yaw)])
            left = np.array([-fwd[1], fwd[0]]); w = g["width"] / 200.0
            ax.plot(*zip(c + left * w, c - left * w), color="#2e7d32" if i == 0 else "#ff8f00", lw=2.5)
        ax.plot(*sg.xy, "*", ms=14, color="yellow", mec="k")
        ax.set_xlim(e0, e1); ax.set_ylim(n0, n1); ax.set_aspect("equal")
        ax.set_title(f"{k}: {t['name']} ({t['length_m']:.0f} m, {len(gs)} gates, {t['laps']} lap(s)); start = star")
        fig.savefig(OUT / f"events_{t['id']}.png", bbox_inches="tight"); plt.close(fig)
print("total issues:", problems_total)
