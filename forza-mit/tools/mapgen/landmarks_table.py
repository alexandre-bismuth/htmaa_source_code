"""Landmark facade overrides (round v2): the famous buildings on the race routes styled like themselves.

Keys are the City of Cambridge 3D catalog Building_ID (BldgID; MIT buildings are 668-<number> etc.), looked up in
build_meshes.py before the generic MIT / Harvard / assessor rules. Each entry gives the facade class for the whole
model and optional height rules: wall faces whose centre is above z_m (metres above the model's ground) get another
class (white-painted wooden belfries and cupolas over brick towers). Roof faces (domes, cupolas, spires) keep the
roof shader, which maps the orthophoto: Lowell's blue dome and Dunster's red cap come from the real roof colour.

Sources (checked 2026-10-26): Archipedia / SAH (Memorial Hall: red brick with horizontal bands of black brick and
sandstone, polychrome slate roof; Lowell House's blue-capped bell tower; Dunster's crimson-and-gold Tom Tower
copy; Eliot's green-domed cupola), MIT Technology Review / List Art (Building 10: ten Ionic columns on Killian Court,
Indiana limestone), the classes' own notes in tools/unreal/materials.json.
"""

# new facade classes introduced with this table (each has a materials.json entry and a mesh class facade_<name>)
LANDMARK_CLASSES = ["granite", "brick_victorian", "brick_blank", "brick_clinker", "white_trim", "white_panel", "stone_blank"]

LANDMARKS = {
    # ---- Harvard Yard
    "318-13": {"name": "Memorial Church", "style": "brick_georgian", "above": [(29.0, "white_trim")]},   # white wooden steeple stages
    "318-14": {"name": "Harvard Hall", "style": "brick_georgian", "above": [(17.0, "white_trim")]},      # white cupola
    "318-18": {"name": "Massachusetts Hall", "style": "brick_georgian"},
    "318-16": {"name": "University Hall", "style": "granite"},             # Bulfinch, white Chelmsford granite
    "318-29": {"name": "Boylston Hall", "style": "granite"},
    "318-24": {"name": "Widener Library", "style": "brick_georgian"},      # red brick + limestone, colonnade (hero mesh)
    "318-23": {"name": "Emerson Hall", "style": "brick_georgian"},
    "318-17": {"name": "Sever Hall", "style": "brick_clinker"},            # Richardson: deep red-orange brick, dark frames
    "318-3": {"name": "Holden Chapel", "style": "brick_georgian"},
    # ---- Memorial Hall (catalogued as Annenberg Hall): High Victorian Gothic polychrome brick
    "266-20": {"name": "Memorial Hall", "style": "brick_victorian"},
    # ---- river Houses: Neo-Georgian brick, white belfry stage under Lowell's blue dome
    "424-3": {"name": "Lowell House", "style": "brick_georgian", "above": [(35.0, "white_trim")]},
    "513-1": {"name": "Dunster House", "style": "brick_georgian"},
    "437-13": {"name": "Eliot House", "style": "brick_georgian"},
    # ---- MIT
    "668-10": {"name": "Building 10 (Great Dome)", "style": "limestone"},
    "668-7": {"name": "Building 7 (Lobby 7)", "style": "limestone"},
    "737-2": {"name": "Baker House (W7)", "style": "brick_clinker"},       # Aalto: dark, irregular clinker brick
    "708-12": {"name": "MIT Chapel (W15)", "style": "brick_blank"},        # windowless brick cylinder
    "708-13": {"name": "Kresge Auditorium (W16)", "style": "glass"},       # glass walls under the concrete shell
    "672-5": {"name": "Wiesner Building / Media Lab (E15)", "style": "white_panel"},   # Pei: white aluminium grid
    "668-32": {"name": "Stata Center (32)", "style": "metal", "wall_nz": 0.35},   # Gehry's leaning walls stay walls
    "668-54": {"name": "Green Building (54)", "style": "concrete"},
}

# slender structures (chimneys, stair towers) and park monuments have no windows
SLENDER_MAX_M2 = 30.0          # footprint below this and taller than SLENDER_MIN_H -> windowless
SLENDER_MIN_H = 10.0
MONUMENT_MAX_M2 = 120.0        # no BldgID, no name, no POI, small and taller than 6 m: a monument / structure
MONUMENT_MIN_H = 6.0


def windowless(style):
    """The windowless class for a style: brick stays brick, everything else light dressed stone (the garden-wall
    class "wall" is a dark granite: the Common's Soldiers' Monument read as a black slab in it)."""
    return "brick_blank" if style.startswith("brick") else "stone_blank"


def face_rule(entry):
    """Per-face style function for build_meshes.add_building_faces, or None."""
    rules = sorted(entry.get("above", []))
    if not rules:
        return None
    import numpy as np

    def f(centroid, normal):
        out = np.full(len(centroid), entry["style"], dtype=object)
        for z, st in rules:
            out[centroid[:, 2] > z] = st
        return out
    return f
