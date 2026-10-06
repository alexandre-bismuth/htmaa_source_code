"""Species / variant parameters for tree_gen.py (see that module for the meaning of each key).

Units: metres, degrees. Leaf colours are sRGB swatches (summer, Boston). `genera` are the city
inventory's Genus values (note the inventory spells Platanus "Planatus").
"""
import copy

# ---------------------------------------------------------------------------- shared defaults
BASE = {
    "lumpiness": 0.14, "env_tol": (0.88, 1.08), "tip_radius": 0.004, "bark_edge": 0.045,
    "flare": 0.35, "buttress": 0.12, "buttress_lobes": 5,
    "min_branch_z": 1.0, "shell": 2.2, "interior_cull": 0.75,
    "leaf_roughness": 0.55, "leaf_translucency": 0.3,
    "levels": [
        # 0 trunk
        {"seg": 0.3, "tropism": 0.3, "wobble": 0.012, "tip_frac": 0.25, "taper_pow": 0.8},
        # 1 limbs
        {"seg": 0.35, "tropism": 0.04, "wobble": 0.07, "droop": 0.0, "count": 9, "per_m": 1.0,
         "range": (0.0, 1.0), "angle": (60, 40), "angle_sd": 8, "length_mode": "reach", "length": 1.0,
         "length_clip": (1.0, 12.0), "radius_ratio": 0.55, "tip_frac": 0.1, "top_shrink": 0.3},
        # 2 branches
        {"seg": 0.3, "tropism": 0.04, "wobble": 0.12, "per_m": 3.5, "range": (0.15, 1.0), "angle": (55, 40),
         "length_mode": "reach", "length": 0.85, "length_clip": (0.4, 5.0), "radius_ratio": 0.5, "roll_bias": 15, "roll_sd": 35},
        # 3 twigs (leaf bearing)
        {"seg": 0.22, "tropism": 0.15, "wobble": 0.18, "per_m": 8.0, "range": (0.08, 1.0), "angle": (50, 40),
         "length_mode": "abs", "length": (0.3, 0.8), "length_clip": (0.15, 1.2), "radius_ratio": 0.45,
         "roll_bias": 20, "roll_sd": 40, "leafy": True, "alternate": False},
    ],
}


def merge(a, b):
    out = copy.deepcopy(a)
    for k, v in b.items():
        if k == "levels":
            lv = copy.deepcopy(out["levels"])
            for i, d in enumerate(v):
                if i < len(lv):
                    lv[i].update(d)
                else:
                    lv.append(d)
            out["levels"] = lv
        elif isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = {**out[k], **v}
        else:
            out[k] = copy.deepcopy(v)
    return out


# ---------------------------------------------------------------------------- species
OAK = merge(BASE, {
    "species": "Quercus rubra / palustris (northern red oak, pin oak)",
    "genera": ["Quercus"],
    "bark": "Bark001", "bark_tint": [0.95, 0.95, 0.95],
    "leaf": {"shape": "oak", "length": 0.2, "width": 0.85, "petiole": 0.15, "petiole_angle": 50,
             "tip_cluster": 4, "tip_angle": 35, "per_node": 1, "droop": 0.15, "bend": 0.15, "fold": 0.2,
             "face_up": 1.0, "face_out": 0.7, "parent_from": 0.6},
    "leaf_colors": [(0.20, 0.31, 0.09), (0.17, 0.27, 0.08), (0.25, 0.35, 0.11)],
    "leaf_roughness": 0.45,
})

HONEYLOCUST = merge(BASE, {
    "species": "Gleditsia triacanthos var. inermis (honey locust)",
    "genera": ["Gleditsia", "Styphnoloblum", "Gymnocladus", "Koelreuteria", "Fraxinus", "Cladrastis"],
    "bark": "bark_brown_02",
    "lumpiness": 0.22, "shell": 1.6, "interior_cull": 0.85,
    "leaf": {"shape": "pinnate", "length": 0.28, "pairs": 5, "leaflet": 0.08, "width": 0.42,
             "leaflet_angle": 65, "petiole": 0.1, "petiole_angle": 55, "tip_cluster": 3, "tip_angle": 30,
             "per_node": 1, "droop": 0.35, "bend": 0.25, "face_up": 1.0, "face_out": 0.5, "parent_from": 0.5},
    "leaf_colors": [(0.36, 0.45, 0.13), (0.30, 0.40, 0.11), (0.42, 0.50, 0.16)],
    "leaf_roughness": 0.6,
    "levels": [{}, {"wobble": 0.12, "tropism": 0.1}, {"wobble": 0.2, "per_m": 2.8},
               {"wobble": 0.3, "per_m": 6.0, "length": (0.25, 0.6)}],
})

PLANE = merge(BASE, {
    "species": "Platanus x acerifolia (London plane) / P. occidentalis",
    "genera": ["Planatus", "Platanus", "Liriodendron", "Aesculus"],
    "bark": "Bark009", "bark_tint": [0.64, 0.66, 0.56], "twig_tint": (0.6, 0.5, 0.42),
    "leaf": {"shape": "palmate", "length": 0.2, "width": 0.95, "petiole": 0.35, "petiole_angle": 60,
             "tip_cluster": 2, "tip_angle": 35, "per_node": 1, "droop": 0.25, "bend": 0.12, "fold": 0.12,
             "face_up": 1.0, "face_out": 0.6, "parent_from": 0.6},
    "leaf_colors": [(0.24, 0.34, 0.11), (0.21, 0.31, 0.10), (0.28, 0.38, 0.13)],
})

BIRCH = merge(BASE, {
    "species": "Betula nigra / populifolia / papyrifera (river, gray, paper birch)",
    "genera": ["Betula", "Populus", "Salix", "Alnus"],
    "bark": "birch_white", "twig_tint": (0.32, 0.24, 0.2),
    "flare": 0.15, "buttress": 0.05, "shell": 1.6,
    "leaf": {"shape": "birch", "length": 0.085, "width": 0.8, "petiole": 0.25, "petiole_angle": 60,
             "tip_cluster": 2, "tip_angle": 30, "per_node": 1, "droop": 0.5, "bend": 0.15, "fold": 0.1,
             "face_up": 0.9, "face_out": 0.6, "parent_from": 0.5},
    "leaf_colors": [(0.28, 0.39, 0.12), (0.24, 0.35, 0.10), (0.33, 0.43, 0.14)],
    "leaf_translucency": 0.35,
    "levels": [{}, {"wobble": 0.1, "droop": 0.25}, {"wobble": 0.15, "droop": 0.5, "tropism": -0.05},
               {"droop": 0.8, "tropism": -0.2, "length": (0.25, 0.6)}],
})

ELM = merge(BASE, {
    "species": "Ulmus americana (American elm) / Zelkova serrata",
    "genera": ["Ulmus", "Zelkova", "Celtis"],
    "bark": "Bark004", "bark_tint": [0.78, 0.76, 0.74],
    "leaf": {"shape": "birch", "length": 0.12, "width": 0.75, "petiole": 0.1, "petiole_angle": 55,
             "tip_cluster": 2, "tip_angle": 30, "per_node": 1, "arrangement": "alternate", "phyllo": 180,
             "droop": 0.4, "bend": 0.15, "fold": 0.15, "face_up": 1.0, "face_out": 0.6, "parent_from": 0.5},
    "leaf_colors": [(0.19, 0.30, 0.09), (0.17, 0.27, 0.08), (0.23, 0.34, 0.11)],
})

MAPLE = merge(BASE, {
    "species": "Acer platanoides / rubrum (Norway maple, red maple)",
    "genera": ["Acer", "Fagus", "Nyssa", "Cercidiphyllum", "Ostrya", "Carpinus", ""],
    "bark": "tree_bark_03", "bark_tint": [0.9, 0.9, 0.9],
    "shell": 2.0, "interior_cull": 0.7,
    "leaf": {"shape": "palmate", "length": 0.14, "width": 0.95, "petiole": 0.4, "petiole_angle": 60,
             "tip_cluster": 2, "tip_angle": 35, "per_node": 2, "arrangement": "opposite", "droop": 0.2,
             "bend": 0.12, "fold": 0.1, "face_up": 1.0, "face_out": 0.7, "parent_from": 0.5},
    "leaf_colors": [(0.20, 0.32, 0.09), (0.17, 0.28, 0.08), (0.24, 0.36, 0.11)],
})

LINDEN = merge(BASE, {
    "species": "Tilia cordata / americana (littleleaf, American linden)",
    "genera": ["Tilia", "Liquidambar", "Carpinus"],
    "bark": "bark_willow", "bark_tint": [0.85, 0.85, 0.85],
    "leaf": {"shape": "cordate", "length": 0.09, "width": 0.95, "petiole": 0.35, "petiole_angle": 60,
             "tip_cluster": 2, "tip_angle": 30, "per_node": 1, "phyllo": 180, "droop": 0.45, "bend": 0.12,
             "fold": 0.08, "face_up": 1.0, "face_out": 0.6, "parent_from": 0.5},
    "leaf_colors": [(0.20, 0.33, 0.09), (0.18, 0.29, 0.08), (0.25, 0.37, 0.11)],
})

ORNAMENTAL = merge(BASE, {
    "species": "Prunus / Malus / Pyrus / Cornus (cherry, crabapple, Callery pear, dogwood)",
    "genera": ["Prunus", "Malus", "Pyrus", "Cornus", "Amelanchier", "Cercis", "Syringa", "Crataegus",
               "Hamamelis", "Magnolia", "Stewartia", "Parrotia", "Ilex", "Eucommia"],
    "bark": "sakura_bark",
    "flare": 0.2, "buttress": 0.06, "shell": 1.5, "tip_radius": 0.003,
    "leaf": {"shape": "ovate", "length": 0.09, "width": 0.8, "petiole": 0.2, "petiole_angle": 55,
             "tip_cluster": 3, "tip_angle": 30, "per_node": 1, "droop": 0.3, "bend": 0.15, "fold": 0.15,
             "face_up": 1.0, "face_out": 0.6, "parent_from": 0.5},
    "leaf_colors": [(0.20, 0.31, 0.09), (0.18, 0.27, 0.08), (0.24, 0.35, 0.11)],
    "leaf_roughness": 0.45,
})

GINKGO = merge(BASE, {
    "species": "Ginkgo biloba",
    "genera": ["Ginkgo", "Metasequoia"],
    "bark": "bark_brown_01", "bark_tint": [0.85, 0.83, 0.8],
    "lumpiness": 0.25, "shell": 1.4, "interior_cull": 0.6,
    "leaf": {"shape": "fan", "length": 0.075, "width": 1.0, "petiole": 0.5, "petiole_angle": 50,
             "tip_cluster": 5, "tip_angle": 45, "per_node": 4, "droop": 0.2, "bend": 0.05, "fold": 0.05,
             "face_up": 1.0, "face_out": 0.5, "parent_from": 0.4},
    "leaf_colors": [(0.36, 0.48, 0.15), (0.32, 0.44, 0.13), (0.40, 0.52, 0.17)],
})


# ---------------------------------------------------------------------------- variants
def V(base, **kw):
    return merge(base, kw)


def variants():
    return {
        # northern red oak, mature: broad rounded crown on stout spreading limbs (decurrent)
        "oak_a": V(OAK, height=17.0, crown_base=3.4, crown_radius=8.0, first_branch=3.0,
                   envelope=[(0, 0.55), (0.2, 0.9), (0.45, 1.0), (0.7, 0.9), (0.88, 0.62), (1, 0.15)],
                   trunk_radius=0.33, trunk_frac=0.55, fork=3, fork_angle=28, fork_len=0.8, fork_radius=0.7,
                   min_leaf_z=3.0, leaf_target=52000, bark_tint=[0.72, 0.7, 0.68],
                   levels=[{}, {"count": 8, "angle": (62, 45), "radius_ratio": 0.6}]),
        # pin oak: central leader, pyramidal, drooping lower / horizontal middle / ascending upper limbs
        "oak_b": V(OAK, height=16.0, crown_base=2.8, crown_radius=5.6, first_branch=2.6,
                   envelope=[(0, 0.85), (0.15, 1.0), (0.4, 0.88), (0.7, 0.55), (0.9, 0.25), (1, 0.05)],
                   trunk_radius=0.26, trunk_frac=0.95, fork=0, min_leaf_z=2.5, leaf_target=42000,
                   leaf={"length": 0.14, "width": 0.75},
                   leaf_colors=[(0.17, 0.29, 0.08), (0.15, 0.25, 0.07), (0.21, 0.33, 0.10)],
                   levels=[{}, {"count": 26, "angle": (100, 45), "tropism": 0.0, "droop": 0.15,
                                "radius_ratio": 0.42, "length": 1.05, "top_shrink": 0.1},
                           {"per_m": 4.0, "tropism": 0.0, "angle": (60, 45)}]),
        # young street oak (~9 m)
        "oak_c": V(OAK, height=9.0, crown_base=2.3, crown_radius=3.6, first_branch=2.0, seed=3,
                   envelope=[(0, 0.6), (0.25, 0.95), (0.55, 1.0), (0.8, 0.75), (1, 0.15)],
                   trunk_radius=0.13, trunk_frac=0.8, fork=0, min_leaf_z=2.0, leaf_target=24000,
                   levels=[{}, {"count": 14, "angle": (65, 40), "radius_ratio": 0.5}, {"per_m": 4.0},
                           {"length": (0.25, 0.6)}]),
        # ---- honey locust: short trunk, few ascending-spreading limbs, open flat-topped airy crown
        "honeylocust_a": V(HONEYLOCUST, height=14.0, crown_base=3.0, crown_radius=7.0, first_branch=2.6,
                           envelope=[(0, 0.55), (0.25, 0.92), (0.55, 1.0), (0.8, 0.85), (1, 0.3)],
                           trunk_radius=0.24, trunk_frac=0.4, fork=3, fork_angle=34, fork_len=0.75,
                           fork_radius=0.68, min_leaf_z=3.0, leaf_target=24000,
                           levels=[{}, {"count": 5, "angle": (58, 42), "radius_ratio": 0.6}]),
        "honeylocust_b": V(HONEYLOCUST, height=8.0, crown_base=2.3, crown_radius=3.6, first_branch=2.0, seed=5,
                           envelope=[(0, 0.55), (0.3, 0.95), (0.6, 1.0), (0.85, 0.8), (1, 0.3)],
                           trunk_radius=0.1, trunk_frac=0.5, fork=2, fork_angle=30, fork_len=0.8,
                           min_leaf_z=2.2, leaf_target=12000,
                           levels=[{}, {"count": 6, "angle": (55, 40)}]),
        # ---- London plane: straight trunk, big spreading limbs, broad rounded crown, mottled bark
        "plane_a": V(PLANE, height=20.0, crown_base=4.2, crown_radius=9.0, first_branch=3.6,
                     envelope=[(0, 0.6), (0.2, 0.92), (0.5, 1.0), (0.75, 0.88), (0.92, 0.55), (1, 0.12)],
                     trunk_radius=0.42, trunk_frac=0.6, fork=3, fork_angle=24, fork_len=0.8, fork_radius=0.68,
                     min_leaf_z=3.6, leaf_target=32000,
                     levels=[{}, {"count": 9, "angle": (66, 42), "radius_ratio": 0.58}]),
        "plane_b": V(PLANE, height=12.0, crown_base=3.0, crown_radius=4.8, first_branch=2.6, seed=2,
                     envelope=[(0, 0.65), (0.25, 0.95), (0.5, 1.0), (0.8, 0.75), (1, 0.12)],
                     trunk_radius=0.2, trunk_frac=0.8, fork=0, min_leaf_z=2.6, leaf_target=19000,
                     levels=[{}, {"count": 15, "angle": (65, 40), "radius_ratio": 0.5}]),
        # ---- birch: river birch clump (tan peeling bark) and a single-stem white birch
        "birch_a": V(BIRCH, height=11.0, crown_base=2.4, crown_radius=4.6, first_branch=2.2, stems=3, stem_lean=9, stem_offset=0.05,
                     envelope=[(0, 0.6), (0.3, 1.0), (0.65, 0.9), (0.9, 0.5), (1, 0.1)],
                     trunk_radius=0.11, trunk_frac=0.85, bark="birch_river", min_leaf_z=2.3, leaf_target=42000,
                     buttress=0.0, flare=0.1,
                     levels=[{}, {"count": 11, "angle": (60, 35), "radius_ratio": 0.5}]),
        "birch_b": V(BIRCH, height=12.0, crown_base=2.6, crown_radius=3.6, first_branch=2.4,
                     envelope=[(0, 0.7), (0.3, 1.0), (0.6, 0.9), (0.85, 0.55), (1, 0.08)],
                     trunk_radius=0.15, trunk_frac=0.92, min_leaf_z=2.5, leaf_target=40000,
                     levels=[{}, {"count": 22, "angle": (62, 35), "radius_ratio": 0.42}]),
        # ---- American elm: low fork into ascending leaders that arch out into a vase / umbrella
        "elm_a": V(ELM, height=20.0, crown_base=5.0, crown_radius=10.0, first_branch=3.6,
                   envelope=[(0, 0.35), (0.25, 0.65), (0.55, 0.92), (0.8, 1.0), (0.95, 0.7), (1, 0.3)],
                   trunk_radius=0.4, trunk_frac=0.22, fork=5, fork_angle=28, fork_len=0.95, fork_radius=0.58, lumpiness=0.08,
                   fork_tropism=0.0, min_leaf_z=4.0, leaf_target=85000,
                   levels=[{}, {"count": 2, "angle": (40, 30), "droop": 0.1}, {"per_m": 4.2, "angle": (55, 45), "range": (0.3, 1.0), "droop": 0.25, "tropism": 0.03, "roll_bias": 25},
                           {"droop": 0.7, "tropism": -0.1, "length": (0.35, 0.9)}]),
        # Zelkova / young elm: smaller, tighter vase
        "elm_b": V(ELM, height=12.0, crown_base=3.0, crown_radius=5.5, first_branch=2.4, seed=1,
                   envelope=[(0, 0.4), (0.3, 0.75), (0.6, 0.97), (0.82, 1.0), (0.95, 0.65), (1, 0.25)],
                   trunk_radius=0.2, trunk_frac=0.22, fork=5, fork_angle=30, fork_tropism=0.0, lumpiness=0.08, fork_len=0.85, fork_radius=0.55,
                   min_leaf_z=2.6, leaf_target=50000,
                   levels=[{}, {"count": 0, "droop": 0.08}, {"per_m": 4.5, "angle": (55, 45), "range": (0.25, 1.0), "droop": 0.25, "tropism": 0.02, "roll_bias": 25},
                           {"droop": 0.5, "tropism": -0.05, "length": (0.3, 0.7)}]),
        # ---- maple: Norway maple dense rounded, red maple upright oval
        "maple_a": V(MAPLE, height=13.0, crown_base=2.8, crown_radius=6.5, first_branch=2.5,
                     envelope=[(0, 0.7), (0.3, 1.0), (0.6, 0.97), (0.85, 0.7), (1, 0.15)],
                     trunk_radius=0.27, trunk_frac=0.7, fork=2, fork_angle=25, fork_len=0.75,
                     min_leaf_z=2.6, leaf_target=34000,
                     levels=[{}, {"count": 10, "angle": (62, 40), "radius_ratio": 0.55}, {"per_m": 4.0}]),
        "maple_b": V(MAPLE, height=13.0, crown_base=2.6, crown_radius=4.3, first_branch=2.4, seed=4,
                     envelope=[(0, 0.6), (0.25, 0.95), (0.5, 1.0), (0.8, 0.75), (1, 0.12)],
                     trunk_radius=0.22, trunk_frac=0.88, min_leaf_z=2.5, leaf_target=32000,
                     leaf={"length": 0.11},
                     leaf_colors=[(0.22, 0.34, 0.10), (0.19, 0.30, 0.09), (0.27, 0.38, 0.12), (0.36, 0.22, 0.12)],
                     leaf_color_weights=[1, 1, 1, 0.12],
                     levels=[{}, {"count": 16, "angle": (48, 30), "radius_ratio": 0.45}, {"per_m": 4.0}]),
        # ---- linden: central leader, dense pyramidal-oval crown, branch tips droop
        "linden_a": V(LINDEN, height=14.0, crown_base=2.6, crown_radius=5.0, first_branch=2.4,
                      envelope=[(0, 0.85), (0.2, 1.0), (0.5, 0.85), (0.8, 0.5), (1, 0.05)],
                      trunk_radius=0.25, trunk_frac=0.92, min_leaf_z=2.5, leaf_target=46000,
                      levels=[{}, {"count": 24, "angle": (85, 45), "droop": 0.1, "radius_ratio": 0.42},
                              {"per_m": 4.0}, {"droop": 0.4}]),
        "linden_b": V(LINDEN, height=8.0, crown_base=2.0, crown_radius=3.0, first_branch=1.9, seed=6,
                      envelope=[(0, 0.8), (0.25, 1.0), (0.55, 0.85), (0.8, 0.5), (1, 0.05)],
                      trunk_radius=0.11, trunk_frac=0.92, min_leaf_z=2.0, leaf_target=24000,
                      levels=[{}, {"count": 16, "angle": (80, 45), "radius_ratio": 0.42}, {"per_m": 4.0}]),
        # ---- small ornamentals: spreading cherry / crabapple, upright Callery pear
        "ornamental_a": V(ORNAMENTAL, height=7.0, crown_base=1.9, crown_radius=4.0, first_branch=1.6,
                          envelope=[(0, 0.55), (0.3, 0.95), (0.6, 1.0), (0.85, 0.75), (1, 0.2)],
                          trunk_radius=0.13, trunk_frac=0.3, fork=4, fork_angle=40, fork_len=0.8,
                          fork_radius=0.6, min_leaf_z=1.8, leaf_target=30000,
                          levels=[{}, {"count": 1}, {"per_m": 4.0}, {"length": (0.3, 0.7), "angle": (60, 45)}]),
        "ornamental_b": V(ORNAMENTAL, height=10.0, crown_base=2.2, crown_radius=3.3, first_branch=1.9, seed=7,
                          envelope=[(0, 0.6), (0.25, 0.9), (0.5, 1.0), (0.8, 0.8), (1, 0.15)],
                          trunk_radius=0.15, trunk_frac=0.35, fork=5, fork_angle=18, fork_len=0.85,
                          fork_radius=0.55, min_leaf_z=2.0, leaf_target=38000,
                          leaf={"length": 0.08, "width": 0.9},
                          leaf_colors=[(0.18, 0.30, 0.08), (0.16, 0.27, 0.07), (0.22, 0.34, 0.10)],
                          levels=[{}, {"count": 2}, {"per_m": 4.5, "angle": (40, 30)}, {"length": (0.3, 0.6), "angle": (55, 45)}]),
        # ---- ginkgo: sparse, irregular, upright; fan leaves clustered on short spurs
        "ginkgo_a": V(GINKGO, height=12.0, crown_base=2.6, crown_radius=4.0, first_branch=2.4,
                      envelope=[(0, 0.75), (0.25, 1.0), (0.55, 0.85), (0.85, 0.5), (1, 0.12)],
                      trunk_radius=0.2, trunk_frac=0.92, min_leaf_z=2.5, leaf_target=40000,
                      levels=[{}, {"count": 12, "angle": (60, 40), "radius_ratio": 0.4, "tropism": 0.08},
                              {"per_m": 2.0, "wobble": 0.08}, {"per_m": 5.0, "length": (0.12, 0.3),
                                                                "angle": (70, 60)}]),
    }


# genus -> variant names (weights equal). Built from the play-area inventory; conifers have no model.
GENUS_MAP = {
    "Quercus": ["oak_a", "oak_b", "oak_c"],
    "Gleditsia": ["honeylocust_a", "honeylocust_b"],
    "Styphnoloblum": ["honeylocust_a"], "Gymnocladus": ["honeylocust_a"], "Fraxinus": ["honeylocust_a"],
    "Koelreuteria": ["honeylocust_b"], "Cladrastis": ["honeylocust_b"],
    "Planatus": ["plane_a", "plane_b"], "Platanus": ["plane_a", "plane_b"],
    "Liriodendron": ["plane_b"], "Aesculus": ["plane_b"],
    "Betula": ["birch_a", "birch_b"], "Populus": ["birch_b"], "Salix": ["birch_a"],
    "Ulmus": ["elm_a", "elm_b"], "Zelkova": ["elm_b"], "Celtis": ["elm_b"],
    "Acer": ["maple_a", "maple_b"], "Fagus": ["maple_a"], "Nyssa": ["maple_b"], "Cercidiphyllum": ["maple_b"],
    "Ostrya": ["maple_b"],
    "Tilia": ["linden_a", "linden_b"], "Liquidambar": ["linden_a"], "Carpinus": ["linden_b"],
    "Prunus": ["ornamental_a"], "Malus": ["ornamental_a"], "Cornus": ["ornamental_a"],
    "Amelanchier": ["ornamental_a"], "Cercis": ["ornamental_a"], "Syringa": ["ornamental_a"],
    "Crataegus": ["ornamental_a"], "Hamamelis": ["ornamental_a"], "Magnolia": ["ornamental_a"],
    "Stewartia": ["ornamental_a"], "Parrotia": ["ornamental_a"], "Eucommia": ["ornamental_b"],
    "Pyrus": ["ornamental_b"], "Ilex": ["ornamental_b"],
    "Ginkgo": ["ginkgo_a"], "Metasequoia": ["ginkgo_a"],
    "": ["maple_a", "oak_c", "linden_b"],
}
# genera with no fitting model (conifers): ~40 instances in mit_core
UNMAPPED_GENERA = ["Pinus", "Picea", "Taxus", "Juniperus", "Thuja", "Tsuga"]
