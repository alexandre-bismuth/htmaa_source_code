"""Minimap / full-screen map assets and the GPS road graph for forza-MIT.

Usage (reuses the tools/mapgen uv environment):

    cd tools/mapgen && uv run ../minimap/make_map.py [region]        # default region: mit_core

Everything is read from the data, nothing about the region is hard-coded: the playable area is the region's
`bbox_lonlat` in tools/mapgen/config.json minus water, the backdrop is its `context_bbox_lonlat`, and the GIS
layers come from data/processed/<region>/ (+ context/). Re-run after the region or its data change.

Outputs
  CambridgeRacer/UI/Generated/minimap_<region>_detail.png   playable region + margin, ~0.5 m/px (max 4096 px)
  CambridgeRacer/UI/Generated/minimap_<region>_wide.png     whole backdrop (context box), ~2 m/px (max 4096 px)
  CambridgeRacer/UI/Generated/minimap_<region>.json         layer bounds (UE cm), playable bounds, label anchors
  CambridgeRacer/UI/Generated/minimap_*.png                 HUD icons (player arrow, pin, event badge, ...)
  CambridgeRacer/UI/Generated/minimap_<region>_preview.png  (check image: wide layer + labels + road graph)
  CambridgeRacer/Tracks/<region>_roads.json                 routing graph (committed): nodes + edges in UE cm

The Generated folder is gitignored; the game loads the PNGs at runtime (UMinimapSubsystem). Style: "Luna Glass"
(tools/ui/README.md) - dark blue-grey ground, light roads with dark outlines, soft building blocks, Luna-blue
water, the area outside the play boundary dimmed. Street names are not baked: they are exported as anchors and
drawn by Slate at a constant screen size on the full map.

Coordinates: local East/North metres (tools/mapgen/geo.py Frame) -> UE cm X = e * 100, Y = -n * 100.
Image rows go north -> south, so a layer's top-left is (X0, Y0) = (e0 * 100, -n1 * 100) and texture
UV = ((X - X0) / (X1 - X0), (Y - Y0) / (Y1 - Y0)).
"""
from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "tools" / "mapgen"))
sys.path.insert(0, str(ROOT / "tools" / "ui"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import PathPatch  # noqa: E402
from matplotlib.path import Path as MPath  # noqa: E402
from PIL import Image  # noqa: E402
from shapely.geometry import LineString, MultiPoint, MultiPolygon, Point, Polygon, box, shape  # noqa: E402
from shapely.geometry.polygon import orient  # noqa: E402
from shapely.ops import linemerge, transform, unary_union  # noqa: E402

from geo import CONFIG, Frame, boston_tiles, region_polygon  # noqa: E402

GENERATED = ROOT / "CambridgeRacer" / "UI" / "Generated"
TRACKS = ROOT / "CambridgeRacer" / "Tracks"

DETAIL_MPP, WIDE_MPP = 0.5, 2.0        # target metres per pixel
DETAIL_MAX_PX = 6144                  # texture size caps (the m/px grows instead); Stage B detail = 4.3 x 3.8 km
WIDE_MAX_PX = 4096                    # -> 0.71 m/px detail (CPU RGBA mip chain ~180 MB), 2 m/px wide
DETAIL_MARGIN_M = 150.0               # detail layer = playable bounds + this

# ------------------------------------------------------------------ palette (sRGB)
BG = "#0b0d11"            # outside the data
CITY = "#1a1e26"          # land without Cambridge GIS (Boston)
GROUND = "#1c2622"        # Cambridge land left over = grass in game
PARK = "#1f3a2a"
PAVED = "#252c36"         # sidewalks, plazas, parking
ROAD = "#aeb7c5"
ROAD_EDGE = "#0c0f14"
ISLAND = "#2a3340"
BUILDING = "#3a4352"
BUILDING_EDGE = "#56617a"
SHADOW = "#06080b"
WATER = "#15457f"
WATER_EDGE = "#2f78d0"
DIM = (0.0, 0.0, 0.0, 0.42)           # outside the play boundary
BOUNDARY = (0.24, 0.58, 1.0, 0.55)    # Luna light blue

# area / water labels (lat, lon); dropped when outside the backdrop
AREA_LABELS = [
    ("Charles River", 42.3562, -71.0813, "water"),
    ("Kendall Square", 42.3627, -71.0858, "area"),
    ("Central Square", 42.3654, -71.1036, "area"),
    ("Killian Court", 42.3596, -71.0918, "area"),
    ("Back Bay", 42.3503, -71.0810, "area"),
    ("Beacon Hill", 42.3588, -71.0690, "area"),
    ("Harvard Square", 42.3732, -71.1189, "area"),
    ("Harvard Yard", 42.3744, -71.1167, "area"),
    ("Cambridge Common", 42.3770, -71.1205, "area"),
    ("Radcliffe Quad", 42.3820, -71.1245, "area"),
    ("Riverside", 42.3680, -71.1130, "area"),
    ("Cambridgeport", 42.3600, -71.1060, "area"),
    ("Mid-Cambridge", 42.3725, -71.1060, "area"),
    ("Inman Square", 42.3736, -71.1003, "area"),
    ("Allston", 42.3640, -71.1260, "area"),
]


# ------------------------------------------------------------------ data

def load(d: Path, layer: str):
    p = d / f"{layer}.geojson"
    if not p.exists():
        return []
    out = []
    for f in json.loads(p.read_text())["features"]:
        if not f.get("geometry"):
            continue
        g = shape(f["geometry"])
        if g.geom_type in ("Polygon", "MultiPolygon"):
            g = g.buffer(0)
        out.append((g, f["properties"] or {}))
    return out


def polys(g):
    if g is None or g.is_empty:
        return
    for p in getattr(g, "geoms", [g]):
        if isinstance(p, Polygon):
            if p.area > 0.5:
                yield p
        elif hasattr(p, "geoms"):
            yield from polys(p)


def lines_of(g):
    if g is None or g.is_empty:
        return
    for p in getattr(g, "geoms", [g]):
        if isinstance(p, LineString):
            yield p
        elif hasattr(p, "geoms"):
            yield from lines_of(p)


def lonlat_box(frame: Frame, bbox):
    lon0, lat0, lon1, lat1 = bbox
    return transform(lambda x, y, z=None: frame.to_en(x, y), box(lon0, lat0, lon1, lat1))


class MapData:
    def __init__(self, region: str):
        self.region = region
        self.frame = Frame()
        spec = CONFIG["regions"][region]
        self.rdir = ROOT / "data" / "processed" / region
        cdir = self.rdir / "context"
        self.region_poly = region_polygon(region, self.frame)   # the lon/lat bbox unless the region has a "playable" block
        has_ctx = spec.get("context_bbox_lonlat") and cdir.exists()
        self.ctx_poly = lonlat_box(self.frame, spec["context_bbox_lonlat"]) if has_ctx else self.region_poly
        # the context layers cover the whole context box (incl. the region); fall back to the region's own data
        self.src = cdir if has_ctx else self.rdir

        water_core = unary_union([g for g, _ in load(self.rdir, "HYDRO_WaterBodies")] or [Polygon()])
        self.playable = self.region_poly.difference(water_core)

        self.water = [g for g, _ in load(self.src, "HYDRO_WaterBodies")]
        self.water_names = [(g, p.get("NAME")) for g, p in load(self.src, "HYDRO_WaterBodies")]
        roads = load(self.src, "BASEMAP_Roads")
        self.roads = [g for g, p in roads if p.get("TYPE") != "RD-TRAF-ISLAND"]
        self.islands = [g for g, p in roads if p.get("TYPE") == "RD-TRAF-ISLAND"]
        self.bridges = [g for g, _ in load(self.src, "BASEMAP_Bridges")]
        self.paved = [g for layer in ("BASEMAP_Sidewalks", "BASEMAP_Plazas", "BASEMAP_PublicFootpaths", "BASEMAP_PrivateWalkways",
                                      "BASEMAP_ImperviousOther", "BASEMAP_ParkingLots", "BASEMAP_Driveways")
                      for g, _ in load(self.src, layer)]
        self.parks = [g for g, _ in load(self.src, "BASEMAP_Vegetation")]
        self.buildings = [g for g, _ in load(self.src, "BASEMAP_Buildings")]
        self.centerlines = load(self.src, "TRANS_Centerlines")

        # Boston (no Cambridge GIS across the river): land farther than ~15 m from any Cambridge road or building
        # is plain "city" ground (land connects around the ends of the river, so components don't separate it)
        land = self.ctx_poly.difference(unary_union(self.water or [Polygon()]))
        cover = unary_union([g.buffer(30, quad_segs=2) for g in self.roads + self.buildings] or [Polygon()]).buffer(-15)
        self.cambridge = cover
        self.city = [p for p in polys(land.difference(cover)) if p.area > 2000.0]
        self.boston = self._boston_footprints() if self.city else []
        print(f"{region}: {len(self.buildings)} buildings, {len(self.paved)} paved, {len(self.roads)} road polygons, "
              f"{len(self.boston)} Boston footprints, source {self.src.relative_to(ROOT)}")

    def _boston_footprints(self):
        """Convex hull of each City of Boston 3D model (tools/mapgen/fetch_boston.sh); fine at backdrop scale."""
        tiles = boston_tiles(self.region)   # the region's own list (Stage B adds Allston E-4 / F-4)
        if not tiles:
            return []
        try:
            import buildings3d
            models = buildings3d.load_boston(tiles, self.ctx_poly, self.frame)
        except Exception as e:     # raw data not fetched: the Boston side stays plain city ground
            print(f"  (no Boston footprints: {e})")
            return []
        city = unary_union(self.city)
        out = []
        for b in models:
            hull = MultiPoint(b.vertices[:, :2]).convex_hull if len(b.vertices) >= 3 else None
            if hull is not None and hull.area > 4.0 and city.contains(hull.centroid):
                out.append(hull)
        return out


# ------------------------------------------------------------------ rendering

def to_path(geoms):
    """Shapely polygons -> one compound matplotlib Path (exteriors CCW, holes CW, non-zero fill = union)."""
    verts, codes = [], []
    for g in geoms:
        for p in polys(g):
            p = orient(p, 1.0)
            for ring in [p.exterior, *p.interiors]:
                c = np.asarray(ring.coords)
                if len(c) < 4:
                    continue
                verts.extend(c.tolist())
                codes.extend([MPath.MOVETO] + [MPath.LINETO] * (len(c) - 2) + [MPath.CLOSEPOLY])
    return MPath(verts, codes) if verts else None


def line_path(lines):
    verts, codes = [], []
    for ln in lines:
        c = np.asarray(ln.coords)
        if len(c) < 2:
            continue
        verts.extend(c.tolist())
        codes.extend([MPath.MOVETO] + [MPath.LINETO] * (len(c) - 1))
    return MPath(verts, codes) if verts else None


class Plot:
    def __init__(self, bounds, mpp):
        e0, n0, e1, n1 = bounds
        self.w = int(math.ceil((e1 - e0) / mpp))
        self.h = int(math.ceil((n1 - n0) / mpp))
        e1, n0 = e0 + self.w * mpp, n1 - self.h * mpp          # keep the top-left corner, whole pixels
        self.bounds = (e0, n0, e1, n1)
        self.mpp = mpp
        self.fig = plt.figure(figsize=(self.w / 100, self.h / 100), dpi=100)
        self.fig.patch.set_facecolor(BG)
        self.ax = self.fig.add_axes([0, 0, 1, 1])
        self.ax.set_xlim(e0, e1)
        self.ax.set_ylim(n0, n1)
        self.ax.axis("off")
        self.ax.set_facecolor(BG)
        self.view = box(e0 - 50, n0 - 50, e1 + 50, n1 + 50)

    def pts(self, metres):
        """A width in metres -> matplotlib points (lines are centred on the path: pass the full width)."""
        return metres / self.mpp * 0.72

    def clip(self, geoms):
        out = []
        for g in geoms:
            if g.intersects(self.view):
                out.append(g if self.view.contains(g) else g.intersection(self.view))
        return out

    def fill(self, geoms, color, edge=None, edge_m=0.0, alpha=1.0, z=0, min_px=0.0, offset=(0.0, 0.0)):
        geoms = self.clip(geoms)
        if min_px > 0:
            geoms = [g for g in geoms if g.area >= (min_px * self.mpp) ** 2]
        if offset != (0.0, 0.0):
            from shapely import affinity
            geoms = [affinity.translate(g, *offset) for g in geoms]
        path = to_path(geoms)
        if path is None:
            return
        self.ax.add_patch(PathPatch(path, facecolor=color, edgecolor=edge or "none", lw=self.pts(edge_m) if edge else 0,
                                    alpha=alpha, zorder=z, joinstyle="round", antialiased=True))

    def stroke(self, lines, color, width_m, z=0, alpha=1.0, min_px=0.0):
        path = line_path(lines)
        if path is None:
            return
        lw = max(self.pts(width_m), min_px * 0.72)
        self.ax.add_patch(PathPatch(path, facecolor="none", edgecolor=color, lw=lw, alpha=alpha, zorder=z,
                                    capstyle="round", joinstyle="round"))

    def image(self) -> Image.Image:
        self.fig.canvas.draw()
        a = np.asarray(self.fig.canvas.buffer_rgba())
        plt.close(self.fig)
        im = Image.fromarray(a[..., :3].copy(), "RGB")
        assert im.size == (self.w, self.h), (im.size, self.w, self.h)
        return im


def render(data: MapData, bounds, mpp):
    pl = Plot(bounds, mpp)
    px = mpp                                   # one pixel in metres: outlines never get thinner than ~1 px
    pl.fill([data.ctx_poly], GROUND, z=1)
    pl.fill(data.city, CITY, z=2)
    pl.fill(data.parks, PARK, z=3)
    pl.fill(data.paved, PAVED, z=4)
    road_edge = max(1.4, 1.6 * px)
    pl.fill(data.roads + data.bridges, ROAD_EDGE, edge=ROAD_EDGE, edge_m=road_edge * 2, z=5)
    pl.fill(data.roads + data.bridges, ROAD, z=6)
    pl.fill(data.islands, ISLAND, z=7)
    pl.fill(data.water, WATER, edge=WATER_EDGE, edge_m=max(1.2, 1.2 * px), z=8)
    # bridges over the water again (the water polygon covers their piers)
    pl.fill(data.bridges, ROAD_EDGE, edge=ROAD_EDGE, edge_m=road_edge * 2, z=9)
    pl.fill(data.bridges, ROAD, z=10)
    # buildings: a soft drop shadow (south-east), then the block with a lighter rim
    blds = data.buildings + data.boston
    pl.fill(blds, SHADOW, alpha=0.55, z=11, offset=(max(1.5, 1.2 * px), -max(1.5, 1.2 * px)), min_px=1.5)
    pl.fill(blds, BUILDING, edge=BUILDING_EDGE, edge_m=max(0.6, 0.9 * px), z=12, min_px=1.0)
    # outside the play boundary: dimmed, with a thin Luna-blue line on the boundary
    view = box(*pl.bounds).buffer(10)
    pl.fill([view.difference(data.playable)], DIM[:3], alpha=DIM[3], z=20)
    pl.stroke([ln for p in polys(data.playable) for ln in [p.exterior, *p.interiors]], BOUNDARY[:3],
              max(1.5, 1.5 * px), z=21, alpha=BOUNDARY[3])
    return pl.image(), pl.bounds


def ue_bounds(bounds):
    e0, n0, e1, n1 = bounds
    return {"x0": round(e0 * 100, 1), "y0": round(-n1 * 100, 1), "x1": round(e1 * 100, 1), "y1": round(-n0 * 100, 1)}


def layer_bounds(poly, margin, mpp_target, max_px):
    e0, n0, e1, n1 = poly.bounds
    e0, n0, e1, n1 = e0 - margin, n0 - margin, e1 + margin, n1 + margin
    mpp = max(mpp_target, max(e1 - e0, n1 - n0) / max_px)
    return (e0, n0, e1, n1), mpp


# ------------------------------------------------------------------ labels

def street_labels(data: MapData, bounds):
    """One label per ~400 m of every named street piece (>= 70 m), angle along the street (screen degrees,
    north-up, clockwise from +x, kept within -90..90 so text reads left to right)."""
    view = box(*bounds)
    by_name = defaultdict(list)
    for g, p in data.centerlines:
        name = (p.get("Street") or "").strip()
        if name:
            by_name[name].extend(lines_of(g.intersection(view)))
    out = []
    for name, ls in by_name.items():
        merged = linemerge(list(lines_of(unary_union(ls)))) if ls else None
        pieces = [ln for ln in lines_of(merged) if ln.length >= 70.0]
        total = sum(ln.length for ln in pieces)
        for ln in pieces:
            n = max(1, int(ln.length // 400.0))
            for k in range(n):
                s = (k + 0.5) / n * ln.length
                a, b = ln.interpolate(max(0.0, s - 15.0)), ln.interpolate(min(ln.length, s + 15.0))
                ang = math.degrees(math.atan2(-(b.y - a.y), b.x - a.x))
                if ang > 90.0:
                    ang -= 180.0
                elif ang <= -90.0:
                    ang += 180.0
                c = ln.interpolate(s)
                inside = data.playable.contains(c)
                out.append({"t": name, "x": round(c.x * 100), "y": round(-c.y * 100), "a": round(ang, 1),
                            "k": "street", "p": 0 if inside else 1, "w": round(total)})
    out.sort(key=lambda d: (d["p"], -d["w"]))
    for d in out:
        del d["w"]
    return out


def area_labels(data: MapData, bounds):
    view = box(*bounds)
    out = []
    for text, lat, lon, kind in AREA_LABELS:
        e, n = data.frame.to_en(lon, lat)
        if view.contains(Point(float(e), float(n))):
            out.append({"t": text, "x": round(float(e) * 100), "y": round(-float(n) * 100), "a": 0.0, "k": kind, "p": 0})
    return out


# ------------------------------------------------------------------ road graph (GPS)

def road_graph(data: MapData):
    """Routing graph from the region's TRANS_Centerlines, clipped to the playable area (region minus water,
    so no routes over walled-off bridges), noded at every crossing (the game is flat: all intersections are
    at grade), with degree-2 chains of the same street merged. One-way restrictions are ignored."""
    core = load(data.rdir, "TRANS_Centerlines")
    keep = data.playable.buffer(2.0)
    named = []
    for g, p in core:
        for ln in lines_of(g.intersection(keep)):
            if ln.length > 1.0:
                named.append((ln, (p.get("Street") or "").strip()))
    noded = list(lines_of(unary_union([ln for ln, _ in named])))

    def name_of(seg):
        mid = seg.interpolate(0.5, normalized=True)
        return min(named, key=lambda t: t[0].distance(mid))[1]

    nodes, index = [], {}

    def node(xy):
        key = (round(xy[0] * 2), round(xy[1] * 2))       # 0.5 m snap
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                k = (key[0] + dx, key[1] + dy)
                if k in index:
                    return index[k]
        index[key] = len(nodes)
        nodes.append(xy)
        return index[key]

    edges = []
    for seg in noded:
        if seg.length < 0.5:
            continue
        a, b = node(seg.coords[0]), node(seg.coords[-1])
        if a == b:
            continue
        edges.append([a, b, name_of(seg), list(seg.coords)])

    # merge degree-2 nodes joining two edges of the same street
    changed = True
    while changed:
        changed = False
        inc = defaultdict(list)
        for i, e in enumerate(edges):
            if e is None:
                continue
            inc[e[0]].append(i)
            inc[e[1]].append(i)
        for n, es in inc.items():
            if len(es) != 2 or es[0] == es[1]:
                continue
            e1, e2 = edges[es[0]], edges[es[1]]
            if e1 is None or e2 is None or e1[2] != e2[2]:
                continue
            c1 = e1[3] if e1[1] == n else e1[3][::-1]
            c2 = e2[3] if e2[0] == n else e2[3][::-1]
            a = e1[0] if e1[1] == n else e1[1]
            b = e2[1] if e2[0] == n else e2[0]
            if a == b:
                continue
            edges[es[0]] = [a, b, e1[2], c1 + c2[1:]]
            edges[es[1]] = None
            changed = True
            break
    edges = [e for e in edges if e is not None]
    used = sorted({e[0] for e in edges} | {e[1] for e in edges})
    remap = {old: i for i, old in enumerate(used)}
    streets = sorted({e[2] for e in edges if e[2]})
    sidx = {s: i for i, s in enumerate(streets)}

    # connectivity report
    adj = defaultdict(set)
    for e in edges:
        adj[remap[e[0]]].add(remap[e[1]])
        adj[remap[e[1]]].add(remap[e[0]])
    seen, comps = set(), []
    for s in range(len(used)):
        if s in seen:
            continue
        stack, comp = [s], 0
        seen.add(s)
        while stack:
            u = stack.pop()
            comp += 1
            for v in adj[u]:
                if v not in seen:
                    seen.add(v)
                    stack.append(v)
        comps.append(comp)

    # keep the main network only: pieces cut off by the boundary can't be routed to or from
    comp_of, comp_len = {}, defaultdict(float)
    for root in range(len(used)):
        if root in comp_of:
            continue
        stack = [root]
        comp_of[root] = root
        while stack:
            u = stack.pop()
            for v in adj[u]:
                if v not in comp_of:
                    comp_of[v] = root
                    stack.append(v)
    for a, b, _, coords in edges:
        comp_len[comp_of[remap[a]]] += LineString(coords).length
    main_comp = max(comp_len, key=comp_len.get)
    edges = [e for e in edges if comp_of[remap[e[0]]] == main_comp]
    used = sorted({e[0] for e in edges} | {e[1] for e in edges})
    remap = {old: i for i, old in enumerate(used)}

    out_edges = []
    for a, b, name, coords in edges:
        ln = LineString(coords).simplify(0.3)
        pts = [[round(x * 100), round(-y * 100)] for x, y in ln.coords]
        out_edges.append({"a": remap[a], "b": remap[b], "s": sidx.get(name, -1), "pts": pts})
    out_nodes = [[round(nodes[i][0] * 100), round(-nodes[i][1] * 100)] for i in used]
    total = sum(LineString(c).length for _, _, _, c in edges)
    print(f"road graph: {len(out_nodes)} nodes, {len(out_edges)} edges, {len(streets)} streets, {total:.0f} m, "
          f"components {sorted(comps, reverse=True)}")
    return {"region": data.region, "units": "UE cm, X east, Y south", "streets": streets, "nodes": out_nodes,
            "edges": out_edges}


# ------------------------------------------------------------------ HUD icons (2x textures, Luna Glass)

def make_icons():
    from uidraw import Canvas, circle_sdf, cov, draw_text, hexc, pixel_art, polygon_cov, rrect_sdf, blur_cov

    icons = {}
    navy, blue, light = hexc("#0a246a"), hexc("#0058ee"), hexc("#3d95ff")
    white, black = hexc("#ffffff"), hexc("#000000")

    def icon(name, size):
        def deco(fn):
            icons[name] = (size, fn)
            return fn
        return deco

    def scaled(pts, s):
        return [(x * s, y * s) for x, y in pts]

    @icon("minimap_player", (28, 28))
    def _player(s):
        W, H = int(28 * s), int(28 * s)
        c = Canvas(W, H)
        arrow = [(14, 2.5), (24.5, 25), (14, 19.5), (3.5, 25)]
        shadow = blur_cov(polygon_cov(W, H, scaled([(x, y + 1.2) for x, y in arrow], s)), 1.6 * s)
        c.paint(hexc("#000000", 0.55), shadow)
        c.paint(navy, polygon_cov(W, H, scaled(arrow, s)))
        inner = [(14, 6.2), (21.4, 22.0), (14, 17.9), (6.6, 22.0)]
        c.paint(white, polygon_cov(W, H, scaled(inner, s)))
        c.paint(hexc("#bcd8ff"), polygon_cov(W, H, scaled([(14, 6.2), (14, 17.9), (6.6, 22.0)], s)))
        return c.image()

    @icon("minimap_pin", (26, 34))
    def _pin(s):
        W, H = int(26 * s), int(34 * s)
        c = Canvas(W, H)
        body = [(13 + 11 * math.cos(t), 12 + 11 * math.sin(t)) for t in np.linspace(math.radians(140), math.radians(400), 40)]
        pts = [(13, 32.5)] + body
        c.paint(hexc("#000000", 0.5), blur_cov(polygon_cov(W, H, scaled([(x, y + 1.0) for x, y in pts], s)), 1.4 * s))
        c.paint(white, polygon_cov(W, H, scaled(pts, s)))
        inner = [(13 + 9 * math.cos(t), 12 + 9 * math.sin(t)) for t in np.linspace(math.radians(145), math.radians(395), 40)]
        c.paint(hexc("#7b2fe0"), polygon_cov(W, H, scaled([(13, 29.5)] + inner, s)))
        c.paint(hexc("#a565ff"), cov(circle_sdf(W, H, 13 * s, 10.5 * s, 7.5 * s)) * 0.6)
        c.paint(white, cov(circle_sdf(W, H, 13 * s, 12 * s, 3.6 * s)))
        return c.image()

    def badge(s, size, flag_cells):
        W = H = int(size * s)
        c = Canvas(W, H)
        r = size / 2 - 1.5
        c.paint(hexc("#000000", 0.5), blur_cov(cov(circle_sdf(W, H, W / 2, H / 2 + 1.2 * s, r * s)), 1.5 * s))
        c.paint(white, cov(circle_sdf(W, H, W / 2, H / 2, r * s)))
        from uidraw import vgrad
        grad = vgrad(W, H, [(0.0, hexc("#6fb1ff")), (0.25, hexc("#3d95ff")), (0.6, hexc("#0058ee")), (1.0, hexc("#0040c0"))])
        c.paint(grad, cov(circle_sdf(W, H, W / 2, H / 2, (r - 1.6) * s)))
        flag = [
            "KKKKKKKKK",
            "KWKWKWKWK",
            "KKWKWKWKK",
            "KWKWKWKWK",
            "KKWKWKWKK",
            "KKKKKKKKK",
            "KG.......",
            "KG.......",
            "KK.......",
        ]
        pal = {"K": hexc("#141414"), "W": white, "G": hexc("#9a9a9a")}
        im = pixel_art(flag, pal, max(1, int(round(flag_cells * s))))
        c.paste(im, (W - im.width) // 2 + int(1 * s), (H - im.height) // 2)
        return c.image()

    icon("minimap_event", (26, 26))(lambda s: badge(s, 26, 1.5))
    icon("minimap_event_lg", (40, 40))(lambda s: badge(s, 40, 2.5))

    # landmark tags (GTA-style blips): accent disc in a white ring with the landmark's pixel icon
    # (tools/ui/landmark_art.py; accents from Tracks/*_landmarks.json, tools/minimap/landmarks.py)
    from landmark_art import icon_image, shade, hex_rgba
    accents = {}
    for p in sorted(TRACKS.glob("*_landmarks.json")):
        for lm in json.loads(p.read_text()).get("landmarks", []):
            accents.setdefault(lm["icon"], lm["accent"])

    def landmark_badge(s, size, name, accent_hex, cell):
        from uidraw import vgrad
        W = H = int(size * s)
        c = Canvas(W, H)
        r = size / 2 - 1.5
        acc = hex_rgba(accent_hex)
        f = lambda rgb: tuple(v / 255 for v in rgb[:3]) + (1.0,)
        c.paint(hexc("#000000", 0.55), blur_cov(cov(circle_sdf(W, H, W / 2, H / 2 + 1.2 * s, r * s)), 1.5 * s))
        c.paint(white, cov(circle_sdf(W, H, W / 2, H / 2, r * s)))
        c.paint(hexc("#0b0d11"), cov(circle_sdf(W, H, W / 2, H / 2, (r - 1.4) * s)))
        grad = vgrad(W, H, [(0.0, f(shade(acc, 1.45))), (0.35, f(acc)), (1.0, f(shade(acc, 0.62)))])
        c.paint(grad, cov(circle_sdf(W, H, W / 2, H / 2, (r - 2.2) * s)))
        im = icon_image(name, accent_hex)
        k = max(1, int(round(cell * s)))
        im = im.resize((im.width * k, im.height * k), Image.Resampling.NEAREST)
        c.paste(im, (W - im.width) // 2, (H - im.height) // 2)
        return c.image()

    for name, acc in accents.items():
        icon(name, (26, 26))((lambda n, a: lambda s: landmark_badge(s, 26, n, a, 1.0))(name, acc))
        icon(f"{name}_lg", (40, 40))((lambda n, a: lambda s: landmark_badge(s, 40, n, a, 1.5))(name, acc))

    @icon("minimap_gate", (14, 14))
    def _gate(s):
        W = H = int(14 * s)
        c = Canvas(W, H)
        c.paint(hexc("#000000", 0.85), cov(circle_sdf(W, H, W / 2, H / 2, 6.5 * s)))
        c.paint(white, cov(circle_sdf(W, H, W / 2, H / 2, 4.8 * s)))
        return c.image()

    @icon("minimap_north", (22, 22))
    def _north(s):
        W = H = int(22 * s)
        c = Canvas(W, H)
        c.paint(hexc("#000000", 0.45), blur_cov(cov(circle_sdf(W, H, W / 2, H / 2 + 1 * s, 10 * s)), 1.2 * s))
        c.paint(white, cov(circle_sdf(W, H, W / 2, H / 2, 10 * s)))
        c.paint(navy, cov(circle_sdf(W, H, W / 2, H / 2, 8.6 * s)))
        im = c.image()
        draw_text(im, (W / 2 + 0.5 * s, H / 2 + 5 * s), "N", "pixel", 16 * s, (1.0, 1.0, 1.0, 1.0), bold=True, anchor="ms")
        return im

    @icon("minimap_edge", (16, 16))
    def _edge(s):
        W = H = int(16 * s)
        c = Canvas(W, H)
        tri = [(8, 1.5), (14.5, 13.5), (8, 10.5), (1.5, 13.5)]
        c.paint(hexc("#000000", 0.9), polygon_cov(W, H, scaled(tri, s)))
        c.paint(white, polygon_cov(W, H, scaled([(8, 4.2), (12.2, 12.0), (8, 9.8), (3.8, 12.0)], s)))
        return c.image()

    @icon("minimap_dot", (8, 8))
    def _dot(s):
        W = H = int(8 * s)
        c = Canvas(W, H)
        c.paint(white, cov(circle_sdf(W, H, W / 2, H / 2, 3.6 * s)))
        return c.image()

    @icon("map_cursor", (44, 44))
    def _cursor(s):
        W = H = int(44 * s)
        c = Canvas(W, H)
        k = hexc("#000000", 0.8)
        m = W / 2
        for (x0, y0, x1, y1) in [(2, 21, 15, 23), (29, 21, 42, 23), (21, 2, 23, 15), (21, 29, 23, 42)]:
            c.paint(k, cov(rrect_sdf(W, H, ((x0 - 1) * s, (y0 - 1) * s, (x1 + 1) * s, (y1 + 1) * s), 1.5 * s)))
        ring_o, ring_i = cov(circle_sdf(W, H, m, m, 9.5 * s)), cov(circle_sdf(W, H, m, m, 6.5 * s))
        c.paint(k, ring_o - ring_i)
        for (x0, y0, x1, y1) in [(2, 21, 15, 23), (29, 21, 42, 23), (21, 2, 23, 15), (21, 29, 23, 42)]:
            c.paint(white, cov(rrect_sdf(W, H, (x0 * s, y0 * s, x1 * s, y1 * s), 1.0 * s)))
        c.paint(white, cov(circle_sdf(W, H, m, m, 8.5 * s)) - cov(circle_sdf(W, H, m, m, 7.0 * s)))
        c.paint(hexc("#ffd54a"), cov(circle_sdf(W, H, m, m, 1.8 * s)))
        return c.image()

    pal = {"K": hexc("#141414"), "W": white, "B": light, "E": blue, "N": navy, "G": hexc("#3ddc5a"), "Y": hexc("#ffd23f"),
           "w": hexc("#d8d8d8"), "R": hexc("#e23b1c"), "g": hexc("#9a9a9a")}
    PIXEL = {
        "minimap_icon": [            # folded map with a red pin (title chips)
            "........KKK.",
            "KKKKKKKKRRRK",
            "KwWKBBKKRWRK",
            "KwWKBBBKRRRK",
            "KwWWKBBBKRK.",
            "KwWWKBBBBKK.",
            "KwWWWKBBBBKK",
            "KBBwWKBBBBwK",
            "KBBBwWKBBBwK",
            "KBBBBwWKBBwK",
            "KKKKKKKKKKKK",
            "............",
        ],
        "minimap_turn_left": [
            "............",
            "...KK.......",
            "..KWK.......",
            ".KWWKKKKK...",
            "KWWWWWWWWK..",
            ".KWWKKKKWWK.",
            "..KWK...KWK.",
            "...KK...KWK.",
            "........KWK.",
            "........KWK.",
            "........KWK.",
            "........KKK.",
        ],
        "minimap_turn_straight": [
            ".....KK.....",
            "....KWWK....",
            "...KWWWWK...",
            "..KWWWWWWK..",
            "..KKKWWKKK..",
            "....KWWK....",
            "....KWWK....",
            "....KWWK....",
            "....KWWK....",
            "....KWWK....",
            "....KWWK....",
            "....KKKK....",
        ],
        "minimap_arrive": [
            "KKKKKKKKKKK.",
            "KWWKKWWKKWK.",
            "KWWKKWWKKWK.",
            "KKKWWKKWWKK.",
            "KKKWWKKWWKK.",
            "KWWKKWWKKWK.",
            "KWWKKWWKKWK.",
            "KKKKKKKKKKK.",
            "Kg..........",
            "Kg..........",
            "Kg..........",
            "KK..........",
        ],
    }
    PIXEL["minimap_turn_right"] = [row[::-1] for row in PIXEL["minimap_turn_left"]]
    for name, rows in PIXEL.items():
        icon(name, (24, 24))((lambda r: lambda s: pixel_art(r, pal, int(round(2 * s))))(rows))

    meta = {}
    for name, (size, fn) in icons.items():
        im = fn(2)
        assert im.size == (size[0] * 2, size[1] * 2), (name, im.size, size)
        im.save(GENERATED / f"{name}.png", optimize=True)
        meta[name] = list(size)
    return meta


# ------------------------------------------------------------------ preview

def preview(region, wide_img, wide_b, labels, graph):
    """Wide layer at ~1/2 scale with the label anchors and the road graph drawn over it (sanity check)."""
    from PIL import ImageDraw
    k = 2
    im = wide_img.resize((wide_img.width * k // 2, wide_img.height * k // 2), Image.Resampling.LANCZOS)
    sx = im.width / (wide_b["x1"] - wide_b["x0"])
    sy = im.height / (wide_b["y1"] - wide_b["y0"])
    P = lambda x, y: ((x - wide_b["x0"]) * sx, (y - wide_b["y0"]) * sy)
    d = ImageDraw.Draw(im)
    for e in graph["edges"]:
        d.line([P(x, y) for x, y in e["pts"]], fill=(61, 149, 255), width=2)
    for x, y in graph["nodes"]:
        px, py = P(x, y)
        d.ellipse([px - 2, py - 2, px + 2, py + 2], fill=(255, 210, 63))
    for lb in labels:
        px, py = P(lb["x"], lb["y"])
        col = (255, 255, 255) if lb["k"] == "street" and lb["p"] == 0 else (150, 160, 175)
        d.text((px, py), lb["t"], fill=col, anchor="mm")
    im.save(GENERATED / f"minimap_{region}_preview.png")


# ------------------------------------------------------------------ main

def main(region):
    GENERATED.mkdir(parents=True, exist_ok=True)
    data = MapData(region)

    detail_b, detail_mpp = layer_bounds(data.playable, DETAIL_MARGIN_M, DETAIL_MPP, DETAIL_MAX_PX)
    wide_b, wide_mpp = layer_bounds(data.ctx_poly, 0.0, WIDE_MPP, WIDE_MAX_PX)
    layers = []
    wide_img = None
    for name, b, mpp in [("wide", wide_b, wide_mpp), ("detail", detail_b, detail_mpp)]:
        img, real = render(data, b, mpp)
        f = f"minimap_{region}_{name}.png"
        img.save(GENERATED / f, optimize=False, compress_level=6)
        layers.append({"name": name, "file": f, "size": [img.width, img.height], "m_per_px": round(mpp, 4), **ue_bounds(real)})
        print(f"  {f}: {img.width}x{img.height} px, {mpp:.3f} m/px")
        if name == "wide":
            wide_img = img

    labels = area_labels(data, wide_b) + street_labels(data, wide_b)
    icons = make_icons()
    pe0, pn0, pe1, pn1 = data.playable.bounds
    meta = {
        "region": region,
        "units": "UE cm, X east, Y south; a layer spans x0..x1 (left..right) and y0..y1 (top..bottom)",
        "layers": layers,
        "playable": ue_bounds((pe0, pn0, pe1, pn1)),
        "labels": labels,
        "icons": icons,
    }
    (GENERATED / f"minimap_{region}.json").write_text(json.dumps(meta, indent=1))
    print(f"  minimap_{region}.json: {len(labels)} labels, {len(icons)} icons")

    graph = road_graph(data)
    TRACKS.mkdir(parents=True, exist_ok=True)
    (TRACKS / f"{region}_roads.json").write_text(json.dumps(graph, separators=(",", ":")))
    print(f"  Tracks/{region}_roads.json: {(TRACKS / f'{region}_roads.json').stat().st_size // 1024} KB")
    preview(region, wide_img, layers[0], labels, graph)


def icons_only(region):
    """Regenerate only the icon PNGs and merge their sizes into the existing minimap_<region>.json (no map render,
    the road graph is left alone): `uv run ../minimap/make_map.py mit_core --icons-only`."""
    path = GENERATED / f"minimap_{region}.json"
    meta = json.loads(path.read_text())
    meta.setdefault("icons", {}).update(make_icons())
    path.write_text(json.dumps(meta, indent=1))
    print(f"  minimap_{region}.json: {len(meta['icons'])} icons")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--icons-only" in sys.argv:
        icons_only(args[0] if args else "mit_core")
    else:
        main(args[0] if args else "mit_core")
