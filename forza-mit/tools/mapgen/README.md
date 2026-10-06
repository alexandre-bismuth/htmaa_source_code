# mapgen — Cambridge GIS -> Unreal world pipeline

    ./fetch.sh               # download raw layers (data/raw, gitignored)
    uv run clip.py mit_core  # clip + reproject -> data/processed/mit_core/*.geojson + preview.png

World frame is fixed in `config.json` (origin, axes, units). Never move the origin once
meshes are imported; expanding the map = adding a region and rerunning.

Data notes:
- Source is WGS84 lon/lat GeoJSON. Elevations/heights are **US survey feet** (NAVD88).
- `BASEMAP_Roads` = large pavement MultiPolygons with holes (blocks are holes), not per-street.
- `BASEMAP_Curbs` = LineStrings.
