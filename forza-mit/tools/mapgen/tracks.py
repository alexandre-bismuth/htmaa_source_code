"""Time-trial routes on the real street network.

Usage:  uv run tracks.py mit_core
Output: CambridgeRacer/Tracks/<region>.json   (read by the game: UTimeTrialSubsystem)
        data/processed/<region>/tracks_preview.png

A route is a list of street intersections ("Massachusetts Ave & Vassar St"); consecutive ones are
joined by the shortest path on the TRANS_Centerlines graph. Gates are placed every GATE_SPACING m and
at corners; each is sized to the road surface (ray-cast against the BASEMAP_Roads polygons).
Coordinates are Unreal centimetres (X = east, Y = south), the same frame as the level.
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra
from shapely.geometry import LineString, MultiLineString, Point, shape
from shapely.ops import linemerge, nearest_points, unary_union
from shapely.prepared import prep

ROOT = Path(__file__).resolve().parents[2]
GATE_SPACING = 110.0      # m between gates on straights
CORNER_DEG = 35.0         # heading change (over ~30 m) that gets its own gate
CORNER_EXIT = 25.0        # m past the detected corner where its gate goes
START_AFTER = 60.0        # m from the first intersection to the start line
GRID_LANE_MAX = 5.0       # m right of the road centre for the start grid (at most)
LINE_STEP = 3.0           # m between racing-line points
LAT_G, BRAKE_G = 0.85, 0.75   # speed profile for the braking line (the STi does ~0.9 g / ~1.1 g)
V_MAX_KMH = 170.0

TRACKS = [
    {"id": "central_loop", "name": "Central Square Loop", "type": "circuit", "laps": 2,
     "via": [("Massachusetts Ave", "Western Ave"), ("Western Ave", "Franklin St"), ("Franklin St", "Brookline St"),
             ("Brookline St", "Massachusetts Ave"), ("Massachusetts Ave", "Western Ave")]},
    {"id": "memorial_sprint", "name": "Memorial Drive Sprint", "type": "sprint", "laps": 1,
     "via": [("Massachusetts Ave", "Memorial Dr"), ("Memorial Dr", "Ames St"), ("Memorial Dr", "Main St")]},
    {"id": "kendall_dash", "name": "Kendall - Central Dash", "type": "sprint", "laps": 1,
     "via": [("Main St", "Ames St"), ("Main St", "Windsor St"), ("Windsor St", "Massachusetts Ave")]},
    {"id": "mit_loop", "name": "MIT Loop", "type": "circuit", "laps": 2,
     "via": [("Massachusetts Ave", "Memorial Dr"), ("Massachusetts Ave", "Vassar St"), ("Vassar St", "Main St"),
             ("Main St", "Ames St"), ("Ames St", "Memorial Dr"), ("Memorial Dr", "Massachusetts Ave")]},
    {"id": "mit_loop_rev", "name": "MIT Loop Reverse", "type": "circuit", "laps": 1,
     # (the same loop started on Ames St: from Mass Ave / Memorial Dr it shared memorial_sprint's start box, whose
     # prompt always won, so this event could not be started from its marker)
     "via": [("Ames St", "Memorial Dr"), ("Main St", "Ames St"), ("Vassar St", "Main St"),
             ("Massachusetts Ave", "Vassar St"), ("Massachusetts Ave", "Memorial Dr"), ("Ames St", "Memorial Dr")]},
    {"id": "vassar_sprint", "name": "Vassar - Memorial Sprint", "type": "sprint", "laps": 1,
     "via": [("Massachusetts Ave", "Vassar St"), ("Vassar St", "Main St"), ("Main St", "Ames St"),
             ("Ames St", "Memorial Dr"), ("Memorial Dr", "Massachusetts Ave")]},
    # Stage B (Harvard): appended after the Stage A events so indices 0-5, cr.TT.Start N and saved best times
    # stay valid. Every Memorial Dr waypoint matters (without them Dijkstra cuts through Western Ave / Mass Ave;
    # Brookline St meets Memorial Dr 6 times near the BU Bridge, so it is not a waypoint).
    # Harvard Square: Mass Ave and JFK St meet at the tip of the kiosk plaza at a ~180 deg U-turn, so the loops
    # turn off JFK St at Mt Auburn St and use Dunster St instead (no event drives round the plaza tip)
    {"id": "harvard_sq_loop", "name": "Harvard Square Loop", "type": "circuit", "laps": 2,
     # (every event needs its own start box: this one starts on Memorial Dr west of Plympton St)
     "via": [("Plympton St", "Memorial Dr"), ("Memorial Dr", "JFK St"), ("JFK St", "Mt Auburn St"),
             ("Mt Auburn St", "Dunster St"), ("Dunster St", "Massachusetts Ave"), ("Massachusetts Ave", "Plympton St"),
             ("Plympton St", "Mt Auburn St"), ("Plympton St", "Memorial Dr")]},
    {"id": "harvard_yard_loop", "name": "Harvard Yard Loop", "type": "circuit", "laps": 2,
     "via": [("Massachusetts Ave", "Dunster St"), ("Massachusetts Ave", "Quincy St"), ("Quincy St", "Kirkland St"),
             ("Kirkland St", "Oxford St"), ("Oxford St", "Everett St"), ("Everett St", "Massachusetts Ave"),
             ("Massachusetts Ave", "Dunster St")]},
    {"id": "harvard_mit_sprint", "name": "Harvard - MIT", "type": "sprint", "laps": 1,
     "via": [("Massachusetts Ave", "Everett St"), ("Massachusetts Ave", "Prospect St"), ("Massachusetts Ave", "Amherst St")]},
    {"id": "mit_harvard_sprint", "name": "MIT - Harvard", "type": "sprint", "laps": 1,
     "via": [("Massachusetts Ave", "Amherst St"), ("Massachusetts Ave", "Prospect St"), ("Massachusetts Ave", "Everett St")]},
    {"id": "riverside_run", "name": "Memorial Drive Riverside", "type": "sprint", "laps": 1,
     "via": [("JFK St", "Memorial Dr"), ("Memorial Dr", "Western Ave"), ("Memorial Dr", "River St"),
             ("Memorial Dr", "Magazine St"), ("Memorial Dr", "Amesbury St"), ("Memorial Dr", "Massachusetts Ave"),
             ("Memorial Dr", "Ames St"), ("Memorial Dr", "Main St")]},
    {"id": "grand_tour", "name": "Cambridge Grand Tour", "type": "circuit", "laps": 1,
     # (starts on Broadway west of Prospect St: riverside_run already starts at JFK St / Memorial Dr)
     "via": [("Broadway", "Prospect St"), ("Broadway", "Quincy St"), ("Quincy St", "Massachusetts Ave"),
             ("Massachusetts Ave", "Dunster St"), ("Dunster St", "Mt Auburn St"), ("Mt Auburn St", "JFK St"),
             ("JFK St", "Memorial Dr"), ("Memorial Dr", "Western Ave"),
             ("Memorial Dr", "River St"), ("Memorial Dr", "Magazine St"), ("Memorial Dr", "Amesbury St"),
             ("Memorial Dr", "Massachusetts Ave"), ("Memorial Dr", "Main St"), ("Main St", "Broadway"),
             ("Broadway", "Prospect St")]},
]
MIN_GATE_GAP = 8.0         # m: minimum distance between consecutive gates
POST_CLEAR_M = 2.0         # m: racing-line points keep this far from a prop (pole, tree, signal...): 3 m apart, the
                           # segments between them then pass 1.5 m clear or more
TRIGGER_MAX = 20.0         # m: how far a checkpoint trigger reaches across the road from the gate centre (each side)
JUNCTION_SPREAD_M = 40.0   # two streets touching at points further apart than this meet at 2 junctions


def load(rdir, layer):
    return [(shape(f["geometry"]), f["properties"]) for f in json.loads((rdir / f"{layer}.geojson").read_text())["features"] if f.get("geometry")]


class Graph:
    def __init__(self, lines):
        self.nodes, self.index, self.edges = [], {}, {}
        rows, cols, w = [], [], []
        for line in lines:
            a, b = self.node(line.coords[0]), self.node(line.coords[-1])
            if a == b:
                continue
            for u, v, geom in ((a, b, line), (b, a, LineString(line.coords[::-1]))):
                if (u, v) not in self.edges or self.edges[(u, v)].length > geom.length:
                    self.edges[(u, v)] = geom
        for (u, v), g in self.edges.items():
            rows.append(u); cols.append(v); w.append(g.length)
        n = len(self.nodes)
        self.m = csr_matrix((w, (rows, cols)), shape=(n, n))

    def node(self, xy):
        key = (round(xy[0] / 1.0), round(xy[1] / 1.0))   # endpoints snap on a 1 m grid
        for dk in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1), (1, -1), (-1, 1)):
            k = (key[0] + dk[0], key[1] + dk[1])
            if k in self.index:
                return self.index[k]
        self.index[key] = len(self.nodes)
        self.nodes.append(xy[:2])
        return self.index[key]

    def nearest(self, pt):
        d = [math.hypot(x - pt.x, y - pt.y) for x, y in self.nodes]
        return int(np.argmin(d))

    def path(self, a, b):
        dist, pred = dijkstra(self.m, indices=a, return_predecessors=True)
        if not np.isfinite(dist[b]):
            raise ValueError(f"no route between nodes {a} and {b}")
        seq = [b]
        while seq[-1] != a:
            seq.append(pred[seq[-1]])
        seq = seq[::-1]
        coords = []
        for u, v in zip(seq[:-1], seq[1:]):
            c = list(self.edges[(u, v)].coords)
            coords += c if not coords else c[1:]
        return coords


def intersection(streets, a, b, near=None):
    """Where streets a and b meet. Two named streets can meet at several junctions; nearest_points() would pick
    one arbitrarily, so the contact points (pieces < 8 m apart) must lie within JUNCTION_SPREAD_M of each other
    (a divided road's two carriageways), unless near=(e, n) picks the junction closest to it."""
    la, lb = streets[a], streets[b]
    p, q = nearest_points(la, lb)
    if p.distance(q) > 8.0:
        raise ValueError(f"{a} and {b} don't meet (closest {p.distance(q):.0f} m)")
    contacts = [nearest_points(pa, pb)[0] for pa in getattr(la, "geoms", [la]) for pb in getattr(lb, "geoms", [lb])
                if pa.distance(pb) < 8.0]
    if near is not None:
        return min(contacts, key=lambda c: c.distance(Point(near)))
    spread = max((c1.distance(c2) for c1 in contacts for c2 in contacts), default=0.0)
    if spread > JUNCTION_SPREAD_M:
        raise ValueError(f"{a} and {b} meet at junctions {spread:.0f} m apart: give the via a 'near' hint")
    return p


def road_extent(roads, p, heading):
    """Distances (left, right) from p to the road edge, perpendicular to heading.
    A centreline point off the road surface (the median of a divided road, a traffic island) measures the
    right-hand carriageway instead (we drive on the right): left is then negative, the carriageway starting
    to the right of p - the gate / racing-line centre (left - right) / 2 lands in that carriageway, not on
    the median kerb (kendall_dash ran its line down a median into a traffic-light pole)."""
    nx, ny = -math.sin(heading), math.cos(heading)   # left normal
    on = lambda d: roads.contains(Point(p[0] + nx * d, p[1] + ny * d))   # d > 0: left, d < 0: right
    # a centreline running along the right-hand edge of a carriageway (median just to the right) counts as
    # off the road too: otherwise points a metre apart pick different carriageways and the smoothed line
    # ends up in the median between them
    centre_on = on(0.0)
    edge = 0.0
    while centre_on and edge < 1.5 and on(-(edge + 0.5)):
        edge += 0.5
    if not centre_on or edge < 1.5:
        first = 1 if not centre_on else int(edge / 0.5) + 2          # (past the edge, into the median)
        shift = next((k * 0.5 for k in range(first, 25) if on(-k * 0.5)), None)
        if shift is not None:
            left = 0.0
            while left < 16.0 and on(-shift + left + 0.5):
                left += 0.5
            right = 0.0
            while right < 16.0 and on(-shift - right - 0.5):
                right += 0.5
            if left + right >= 5.0:
                return [left - shift, right + shift]
        if not centre_on:
            return [3.0, 3.0]
    out = []
    for s in (1, -1):
        d = 0.0
        while d < 16.0 and on(s * (d + 0.5)):
            d += 0.5
        out.append(d)
    # at least 6 m of road, padded evenly (a per-side minimum would push a gate whose centreline runs along
    # a carriageway edge 3 m into the median beside it)
    pad = max(0.0, 6.0 - out[0] - out[1]) / 2.0
    return [out[0] + pad, out[1] + pad]


def gates_along(line, roads, closed):
    L = line.length
    pos = lambda s: np.array(line.interpolate(s % L if closed else min(max(s, 0), L)).coords[0])
    heading = lambda s: math.atan2(*(pos(s + 3) - pos(s - 3))[::-1])
    marks = [0.0]
    s = 0.0
    while s < L - 20:
        # step forward until the spacing is reached or a corner shows up
        step = 5.0
        nxt = s + step
        while nxt - s < GATE_SPACING and nxt < L - 20:
            dh = math.degrees(abs((heading(nxt + 15) - heading(nxt - 15) + math.pi) % (2 * math.pi) - math.pi))
            if dh > CORNER_DEG and nxt - s > 35:
                nxt += CORNER_EXIT      # gate at the corner exit, clear of the intersection box
                break
            nxt += step
        s = min(nxt, L)
        if L - s > 25 or not closed:
            marks.append(s)
    if not closed and marks[-1] < L - 1:
        marks.append(L)
    # near the end the step loop can place a mark only 5 m after the previous one: two gates that close read as
    # a double gate. Drop intermediate marks closer than MIN_GATE_GAP to the previous kept one (Stage A's
    # closest pair is 10 m, so events 0-5 are unchanged)
    kept = [marks[0]]
    for m in marks[1:-1]:
        if m - kept[-1] >= MIN_GATE_GAP:
            kept.append(m)
    marks = kept + marks[-1:] if len(marks) > 1 else kept
    gates = []
    for s in marks:
        p, h = pos(s), heading(s)
        # narrowest road section within +-8 m: a gate near an intersection must not span the cross street
        # (its pylons would stand in the roadway); the samples just outside the junction give the real width
        # (as intervals across the road, right positive: their intersection; if the samples disagree - a
        # median that starts or ends in the window - the section at the gate itself)
        ext = [road_extent(roads, pos(s + d), heading(s + d)) for d in (-8.0, -4.0, 0.0, 4.0, 8.0)]
        lo, hi = max(-e[0] for e in ext), min(e[1] for e in ext)
        if hi - lo < 4.0:
            lo, hi = -ext[2][0], ext[2][1]
        left, right = -lo, hi
        # centre the gate on the road surface, not the centreline (divided roads, offset lanes)
        off = (left - right) / 2
        cx, cy = p[0] - math.sin(h) * off, p[1] + math.cos(h) * off
        gates.append({"s": round(s, 1), "en": [cx, cy], "heading": h, "width": min(left + right, 26.0) + 2.0})
    return gates


def racing_line(line, roads, closed):
    """Road-centred points every LINE_STEP m with a target speed (km/h): the cornering limit from
    curvature (v = sqrt(a_lat * R)), then propagated backwards with braking (v^2 = v_next^2 + 2 a d)
    so the line turns yellow / red where you must brake for what comes next."""
    L = line.length
    n = int(L // LINE_STEP)
    s = np.arange(n) * LINE_STEP
    pos = np.array([line.interpolate(v).coords[0] for v in s])
    # centre on the road surface, smoothed (single points jump at intersections)
    off = []
    for i in range(n):
        d = pos[(i + 2) % n if closed else min(i + 2, n - 1)] - pos[(i - 2) % n if closed else max(i - 2, 0)]
        h = math.atan2(d[1], d[0])
        left, right = road_extent(roads, pos[i], h)
        off.append(((left - right) / 2, h))
    o = np.array([v for v, _ in off])
    k = 9
    o = np.convolve(np.pad(o, k, mode="wrap" if closed else "edge"), np.ones(2 * k + 1) / (2 * k + 1), mode="same")[k:-k]
    hs = np.array([h for _, h in off])
    pts = np.column_stack([pos[:, 0] - np.sin(hs) * o, pos[:, 1] + np.cos(hs) * o])
    # curvature from heading change over +-12 m
    w = 4
    idx = lambda i: i % n if closed else min(max(i, 0), n - 1)
    v = np.zeros(n)
    for i in range(n):
        a, b, c = pts[idx(i - w)], pts[i], pts[idx(i + w)]
        h1, h2 = math.atan2(*(b - a)[::-1]), math.atan2(*(c - b)[::-1])
        dh = abs((h2 - h1 + math.pi) % (2 * math.pi) - math.pi)
        ds = np.linalg.norm(b - a) + np.linalg.norm(c - b)
        R = ds / max(dh, 1e-4)
        v[i] = min(math.sqrt(LAT_G * 9.81 * R) * 3.6, V_MAX_KMH)
    if not closed:      # the curvature estimate is meaningless at the open ends
        v[:w] = v[w]
        v[-w:] = V_MAX_KMH
    # braking: backwards pass (twice round a circuit so the wrap is consistent)
    a = BRAKE_G * 9.81
    for _ in range(2 if closed else 1):
        for i in range(n - 2, -1, -1) if not closed else range(n - 1, -1, -1):
            j = idx(i + 1)
            v[i] = min(v[i], math.sqrt((v[j] / 3.6) ** 2 + 2 * a * LINE_STEP) * 3.6)
    return [[round(x * 100, 1), round(-y * 100, 1), round(float(vv), 1)] for (x, y), vv in zip(pts, v)]


def keep_line_clear(rline, islands, posts, lanes, closed):
    """road_extent centres the line on the whole road surface, traffic islands included, and cuts corners close to the
    kerb: along a planted median the line ran down the island and through its trees (grand_tour), and round the Mass
    Ave / Memorial Drive corner it passed 0.8 m from a lamp post. Move those stretches sideways into a lane clear of
    the props (`posts`: props.py's poles, trees, signals... buffered by the clearance) by the least that clears them,
    tapered over TAPER points before and after so the line bends gently. One side per stretch (stretches less than
    TAPER apart are one): the side needing the smaller shift - the carriageway the line already leans into (there is
    no traffic), the right-hand one on a tie. A stretch under 3 points (9 m) clipping a junction's corner island
    stays (moving it would detour the line round the corner)."""
    TAPER, MIN_RUN, MAX_SHIFT = 10, 3, 6.0
    base = np.array([(x / 100.0, -y / 100.0) for x, y, _ in rline])
    n = len(base)
    wrap = lambda i: i % n if closed else i
    rights = []
    for i in range(n):
        d = base[min(wrap(i + 3), n - 1)] - base[max(wrap(i - 3), 0)]
        rights.append(np.array([d[1], -d[0]]) / max(np.linalg.norm(d), 1e-6))
    rights = np.array(rights)
    blocked = lambda p: islands.contains(Point(p)) or posts.contains(Point(p))
    at_post = [posts.contains(Point(p)) for p in base]
    on = [at_post[i] or islands.contains(Point(base[i])) for i in range(n)]
    # stretches: blocked points, merged across gaps under TAPER points (a gap in a median, two posts in a row)
    hits = [i for i in range(n) if on[i]]
    runs = []
    for i in hits:
        if runs and i - runs[-1][-1] <= TAPER:
            runs[-1].extend(range(runs[-1][-1] + 1, i + 1))
        else:
            runs.append([i])
    if closed and len(runs) > 1 and runs[0][0] + n - runs[-1][-1] <= TAPER:
        last = runs.pop()
        runs[0] = last + list(range(last[-1] + 1, n)) + runs[0]
    runs = [r for r in runs if sum(on[i] for i in r) >= MIN_RUN or any(at_post[i] for i in r)]
    if not runs:
        return rline

    def envelope(plan):
        off = np.zeros(n)
        for side, run, req in plan:
            for i, r in zip(run, req):
                if not r:
                    continue
                for k in range(-TAPER, TAPER + 1):
                    j = wrap(i + k)
                    if 0 <= j < n and r * (1.0 - abs(k) / (TAPER + 1.0)) > abs(off[j]):
                        off[j] = side * r * (1.0 - abs(k) / (TAPER + 1.0))
        return off

    in_lane = lambda i, side, r: lanes.contains(Point(base[i] + side * r * rights[i]))
    plan = []
    for run in runs:
        options = []
        for side in (1, -1):
            # the least shift that puts each blocked point in a clear lane (the others: 0, raised below if needed)
            req = []
            for i in run:
                r = 0.0 if not on[i] else next((k * 0.5 for k in range(1, int(MAX_SHIFT * 2) + 1) if in_lane(i, side, k * 0.5)), None)
                req.append(r)
            if all(r is not None for r in req):
                options.append((max(req), -side, side, req))
        if options:
            plan.append(list(min(options)[2:3]) + [run, min(options)[3]])
    # the taper between blocked points can still graze an island's nose or a post: raise those points' shift until
    # the whole stretch is clear (or the shift limit)
    for _ in range(int(MAX_SHIFT * 2)):
        off = envelope(plan)
        changed = False
        for side, run, req in plan:
            for k, i in enumerate(run):
                if blocked(base[i] + off[i] * rights[i]) and abs(off[i]) + 0.5 <= MAX_SHIFT:
                    req[k] = abs(off[i]) + 0.5
                    changed = True
        if not changed:
            break
    off = envelope(plan)
    return [[round(x + off[j] * rights[j][0] * 100, 1), round(y - off[j] * rights[j][1] * 100, 1), v] if off[j] else [x, y, v]
            for j, (x, y, v) in enumerate(rline)]


def fit_gates_to_line(gates, rline):
    """The racing line must run through every gate (the autopilot and "back on track" follow it): where it
    passes outside a gate's inner 1.5 m - the gate measured one carriageway of a divided road, the smoothed
    line went down the other - recentre the gate on the line, keeping its width."""
    pts = np.array([(x / 100.0, -y / 100.0) for x, y, _ in rline])     # back to east / north metres
    for g in gates:
        c = np.array(g["en"])
        i = int(np.argmin(((pts - c) ** 2).sum(axis=1)))
        h = g["heading"]
        rx, ry = math.sin(h), -math.cos(h)                               # right of the heading
        lat = (pts[i][0] - c[0]) * rx + (pts[i][1] - c[1]) * ry
        if abs(lat) > g["width"] / 2 - 1.5:
            g["en"] = [c[0] + rx * lat, c[1] + ry * lat]


def trigger_span(roads, g):
    """(left, right) reach of the checkpoint trigger from the gate centre, in m: the road surface at the gate, at least
    the gate itself. Gates are sized to the narrowest section within +-8 m (their pylons stay clear of cross streets),
    so where the road is wider at the gate a player who drives round a pylon would miss the checkpoint."""
    h, (cx, cy), half = g["heading"], g["en"], g["width"] / 2
    nx, ny = -math.sin(h), math.cos(h)   # left normal
    out = []
    for side in (1, -1):
        # out to the last road point: across the gate span, then across gaps under 3 m (a median refuge, an island)
        d, last = 0.0, 0.0
        while d < TRIGGER_MAX and (d < half or d - last < 3.0):
            d += 0.5
            if roads.contains(Point(cx + side * nx * d, cy + side * ny * d)):
                last = d
        out.append(max(half, last))
    return out


def to_ue(g):
    e, n = g["en"]
    yaw = math.degrees(math.atan2(-math.sin(g["heading"]), math.cos(g["heading"])))   # UE yaw (Y = south)
    return {"x": round(e * 100, 1), "y": round(-n * 100, 1), "z": 0.0, "yaw": round(yaw, 2), "width": round(g["width"] * 100, 1)}


def main(region):
    rdir = ROOT / "data/processed" / region
    cl = load(rdir, "TRANS_Centerlines")
    streets = {}
    for g, p in cl:
        streets.setdefault(p.get("Street"), []).append(g)
    streets = {k: unary_union(v) for k, v in streets.items() if k}
    graph = Graph([g for g, _ in cl for g in (getattr(g, "geoms", [g]))])
    roads = prep(unary_union([g.buffer(0) for g, _ in load(rdir, "BASEMAP_Roads")]))
    road_l = load(rdir, "BASEMAP_Roads")
    island_geom = unary_union([g.buffer(0) for g, p in road_l if p.get("TYPE") == "RD-TRAF-ISLAND"])
    islands = prep(island_geom.buffer(-0.3))
    # (inside a lane: 1.8 m from the kerbs, as the car's centre is when it drives along one)
    # props (props.py, run before this) the car must clear: its half width plus a trunk / pole and a margin
    props_file = rdir / "props/props.json"
    post_geom = unary_union([Point(p["x"] / 100.0, -p["y"] / 100.0).buffer(POST_CLEAR_M, 8)
                             for p in (json.loads(props_file.read_text()) if props_file.exists() else [])])
    posts = prep(post_geom)
    lanes = prep(unary_union([g.buffer(0) for g, p in road_l if p.get("TYPE") != "RD-TRAF-ISLAND"])
                 .difference(island_geom).buffer(-1.8).difference(post_geom))

    out, preview = [], []
    for spec in TRACKS:
        pts = [intersection(streets, *v[:2], near=v[2] if len(v) > 2 else None) for v in spec["via"]]
        nodes = [graph.nearest(p) for p in pts]
        coords = []
        for a, b in zip(nodes[:-1], nodes[1:]):
            seg = graph.path(a, b)
            coords += seg if not coords else seg[1:]
        line = LineString(coords)
        closed = spec["type"] == "circuit"
        # start line a little after the first intersection; rotate a circuit so it starts there
        if closed:
            line = LineString([line.interpolate((START_AFTER + t) % line.length).coords[0] for t in np.arange(0, line.length, 2.0)] +
                              [line.interpolate(START_AFTER).coords[0]])
        else:
            line = LineString([line.interpolate(t).coords[0] for t in np.arange(START_AFTER, line.length, 2.0)] + [coords[-1]])
        gates = gates_along(line, roads, closed)
        rline = keep_line_clear(racing_line(line, roads, closed), islands, posts, lanes, closed)
        fit_gates_to_line(gates, rline)
        # start grid: 12 m behind the start line, in the right-hand half of the road (the middle of the right
        # half: the outer lane on a two-lane road, between the right lanes on Mass Ave, where the PlayerStart
        # is) - not on the centre line. The game draws the start box and its prompt zone around this point.
        h = gates[0]["heading"]
        lane = min(0.5 * (gates[0]["width"] - 2.0) / 2.0, GRID_LANE_MAX)
        at = lambda off: [gates[0]["en"][0] - 12 * math.cos(h) + off * math.sin(h),
                          gates[0]["en"][1] - 12 * math.sin(h) - off * math.cos(h)]
        # (the first of: the lane, nearer the centre, the centre, left of it, that is on the road surface)
        off = next((o for o in (lane, lane * 0.5, 0.0, -lane * 0.5, -lane) if roads.contains(Point(*at(o)))), 0.0)
        grid = {"en": at(off), "heading": h, "width": 0}
        out.append({"id": spec["id"], "name": spec["name"], "type": spec["type"], "laps": spec["laps"],
                    "length_m": round(line.length, 0), "start": to_ue(grid) | {"z": 60.0},
                    "gates": [to_ue(g) | {"trigger": [round(v * 100, 1) for v in trigger_span(roads, g)]} for g in gates],
                    "line": rline})
        preview.append((spec["name"], line, gates))
        sp = [p[2] for p in out[-1]["line"]]
        print(f"{spec['name']}: {line.length:.0f} m, {len(gates)} gates, {spec['laps']} lap(s), line {len(sp)} pts, "
              f"target speed {min(sp):.0f}..{max(sp):.0f} km/h")

    # every event needs its own start box (the game's start prompt takes the first event whose box the car is in)
    for i, a in enumerate(out):
        for b in out[:i]:
            d = math.hypot(a["start"]["x"] - b["start"]["x"], a["start"]["y"] - b["start"]["y"]) / 100.0
            if d < 15.0:
                raise SystemExit(f"start boxes of {b['id']} and {a['id']} are {d:.1f} m apart: give one another start")

    dest = ROOT / "CambridgeRacer/Tracks"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / f"{region}.json").write_text(json.dumps({"region": region, "tracks": out}, indent=1))

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, len(preview), figsize=(7 * len(preview), 7))
    road_geoms = [g.buffer(0) for g, _ in load(rdir, "BASEMAP_Roads")]
    for ax, (name, line, gates) in zip(axes, preview):
        for g in road_geoms:
            for poly in getattr(g, "geoms", [g]):
                ax.fill(*poly.exterior.xy, color="#ccc", lw=0)
        ax.plot(*line.xy, color="#1565c0", lw=2)
        for k, g in enumerate(gates):
            h, w = g["heading"], g["width"] / 2
            x, y = g["en"]
            ax.plot([x - math.sin(h) * w, x + math.sin(h) * w], [y + math.cos(h) * w, y - math.cos(h) * w], color="#ff8f00" if k else "#2e7d32", lw=2)
        ax.set_title(name); ax.set_aspect("equal"); ax.axis("off")
    fig.savefig(rdir / "tracks_preview.png", dpi=80, bbox_inches="tight")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "mit_core")
