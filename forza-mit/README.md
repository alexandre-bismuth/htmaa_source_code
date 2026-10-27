# Forza @ MIT

A driving game set on the real MIT and Harvard campuses in Cambridge, MA, built in
Unreal Engine 5.8 for an HTMAA final project (repository: forza-MIT). Free roam plus solo time trials in a 2002 Subaru
Impreza WRX STi (GDB-B "bugeye"), later to be driven with a custom wheel, pedals and force feedback.

## Play
    ~/UE_5.8/Engine/Binaries/Mac/UnrealEditor ~/dev/forza-mit/CambridgeRacer/CambridgeRacer.uproject -game -FullScreen

The launch menu comes up while the engine starts (it is the loading screen, then the live menu while the map
keeps streaming behind it): **Launch Open World** (free roam from the HTMAA lectures, the Media Lab on Amherst St),
**Timed Race** (the 12 events) and **Options** (graphics, driving assists, wheel, controls). In game, Esc opens the
settings with a **Main menu** button. `-NoLaunchMenu` starts straight in the car; test runs (`-ShotTour`,
`-DriveTest`, `-TimeTrialAuto`) skip the menu and start on Mass Ave as before (`-LaunchMenu` forces it).

## Layout
- `CambridgeRacer/` — UE 5.8 C++ project (from the Vehicle template). Car: `Source/CambridgeRacer/Impreza/`.
  `Source/CambridgeUI/` is the UI kit and the launch menu (its own module: it is the engine's loading screen).
- `tools/mapgen/` — Python pipeline: Cambridge GIS data -> world-frame meshes.
- `tools/unreal/` — headless Unreal scripts: import meshes, build levels, drive tests.

## Rebuild everything (fresh clone)
Content/ and data/ are not in git; every step below is headless and rerunnable. Order matters
(each step reads the previous one's output). Run from the repo root:

    # prerequisites: UE 5.8 at ~/UE_5.8 (or UE_ROOT), Xcode, uv, Blender 5.2, python3, curl, unzip, perl,
    # rsvg-convert (brew install librsvg; tools/ui launch-menu art)
    BLENDER=/Applications/Blender.app/Contents/MacOS/Blender

    # 0. engine template content + the C++ module (the Unreal Python steps call UCambridgeWorldTools)
    tools/unreal/bootstrap_content.sh
    ~/UE_5.8/Engine/Build/BatchFiles/Mac/Build.sh CambridgeRacerEditor Mac Development \
        -Project=$PWD/CambridgeRacer/CambridgeRacer.uproject -WaitMutex   # (add -NoUBA if the PCH build fails)

    # 1. downloads (data/raw, cached) and generated data (data/processed)
    cd tools/mapgen
    ./fetch.sh && ./fetch_boston.sh                    # GIS layers, Cambridge + Boston 3D buildings
    uv run fetch_textures.py && uv run fetch_models.py # Poly Haven CC0 textures and models
    uv run fetch_sky.py                                # Poly Haven CC0 sky photo (HDRI) for the sky dome
    uv run clip.py mit_core && uv run clip.py mit_core --context
    uv run fetch_ortho.py mit_core && uv run fetch_ortho.py mit_core --context
    uv run make_ground_mask.py mit_core                # edge / surface / paving-direction masks for the ground shader (~1.5 min, 6.5 GB peak)
    uv run make_water_normal.py && uv run make_leaf_alpha.py && uv run make_paint_flakes.py
    uv run make_engine_audio.py
    uv run build_meshes.py mit_core
    cd ../..
    $BLENDER -b --factory-startup -P tools/blender/tree_textures.py # bark texture sets
    $BLENDER -b --factory-startup -P tools/blender/build_trees.py   # street tree variants + trees.json
    for m in fire_hydrant metal_trash_can painted_wooden_bench; do
      $BLENDER -b --factory-startup -P tools/blender/merge_model.py -- \
        data/raw/models/$m/$m.gltf data/processed/common/props/$m.glb; done
    $BLENDER -b --factory-startup -P tools/blender/build_sti.py     # the car
    $BLENDER -b --factory-startup -P tools/blender/make_sky.py      # sky dome texture + sun position (sky.json)
    $BLENDER -b --factory-startup -P tools/blender/parked_cars.py   # parked car body types + parked_cars.json
    (cd tools/mapgen && uv run props.py mit_core && uv run tracks.py mit_core \
        && uv run checks/parked_check.py mit_core && uv run ../minimap/make_map.py mit_core)

    # 2. Unreal import and level (one Unreal process at a time)
    tools/unreal/import_props.sh
    tools/unreal/import_region.sh mit_core
    tools/unreal/build_materials.sh mit_core
    tools/unreal/build_sky.sh                  # sky dome material (build_level places the dome and aims the sun)
    tools/unreal/build_level.sh mit_core
    tools/unreal/build_test_track.sh
    tools/unreal/import_car.sh
    (cd tools/ui && uv run make_ui_sounds.py && uv run make_landmark_signs.py)
    tools/unreal/build_game_assets.sh
    tools/unreal/build_landmark_assets.sh
    (cd tools/ui && uv run make_ui_assets.py && uv run make_launch_assets.py)   # UI: see tools/ui/README.md

Rendered check: `tools/unreal/shot_tour.sh mit_core [shots.json]` (screenshots and timings in
CambridgeRacer/Saved/Screenshots/ShotTour/).

## Test the car (headless)
    tools/unreal/drive_test.sh DriveTest accel|brake|skidpad
    tools/unreal/drive_test.sh mit_core settle

## Data
City of Cambridge GIS data (ODC PDDL 1.0, public domain), MassGIS imagery (public domain), City of Boston Planning
Department 3D Smart Model (Boston skyline backdrop, PDDL per Analyze Boston), Poly Haven and ambientCG textures, models
and the sky photo (CC0). Fonts are under the SIL Open Font License (CambridgeRacer/UI/Fonts). Sources and details:
docs/content_sources.md.
