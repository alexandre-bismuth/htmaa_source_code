# Content sources: map expansion, Boston skyline, street furniture, trees

Research notes, 2026-10-04. Each URL below was checked with `curl -I`, an API call or a test
download (marked "verified") unless it is marked "not verified". Test downloads are in the session
scratchpad (`research/`), not in `data/`. Sizes are `Content-Length` values in bytes or MB as of
2026-10-04.

---

## 1. Map expansion (MIT to Harvard Square)

### 1.1 Cambridge 3D building tiles (CyberCity3D 2023 OBJ)

**URL pattern (from `tools/mapgen/fetch.sh`):**
`https://cambmagisdata.blob.core.windows.net/camb3d/Camb3D_{TILE}_2023_Bulding_Models_OBJ.zip`
("Bulding" is misspelled in the real file names.)

**Tile grid.** This is the CitySchema "Metro Boston 3D" scheme (https://www.cityschema.org/tile_scheme/index.htm):
- Tiles are 5000 ft squares in MA State Plane feet (EPSG:2249).
- Origin is X = 731,100, Y = 2,902,900 (lon -71.223391, lat 42.213379). This is the same offset `buildings3d.py` already subtracts.
- Column letter: `chr(ord('A') + floor((X - 731100) / 5000) - 1)`. That gives E = X **756,100 to 761,100**, F = 761,100 to 766,100, G = 766,100 to 771,100 and H = 771,100 to 776,100, matching the local catalogs.
- Row number: `floor((2,972,900 - Y) / 5000) + 1`, counted southward. Row 2 = Y 2,962,900 to 2,967,900; row 3 = Y 2,957,900 to 2,962,900; row 4 = Y 2,952,900 to 2,957,900.
- Approximate latitudes: row 2 is 42.3777 to 42.391; row 3 is 42.364 to 42.3777; row 4 is 42.3522 to 42.364.

Checked against the local catalogs, where each `catalog.csv` row has a `Tile` column:

| Tile | Local? | Zip size | Models | What it covers |
|---|---|---|---|---|
| E-3 | yes | 9.8 MB | 1,777 | **Harvard Square, Harvard Yard (south of about the Science Center), the river Houses, JFK St, Brattle St** |
| E-4 | yes | 1.5 MB | 378 | Memorial Dr west of the BU Bridge (Cambridge side only) |
| F-3 | yes | 16 MB | 4,097 | Central Sq, Mid-Cambridge, Mass Ave from Central to Harvard |
| F-4 | yes | 7.0 MB | 1,808 | Cambridgeport, MIT west |
| G-3 / G-4 / H-3 | yes | 7.6 / 2.1 / 1.3 MB | 2,049 / 355 / 263 | MIT, Kendall, East Cambridge |
| **E-2** | no | 14,870,950 B (14.9 MB) | 3,505 (test-downloaded) | Harvard Law, Cambridge Common north, Radcliffe, Divinity Ave, Oxford St museums, Porter Sq |
| **F-2** | no | 1,254,655 B (1.3 MB) | 303 (test-downloaded) | Kirkland St, Holden Green, Beckwith Circle (Cambridge is only a sliver of this tile) |
| D-3 | no | 4,719,093 B (4.7 MB) | 1,151 (test-downloaded) | West of Harvard: Mt Auburn Hospital, BB&N, Eliot Bridge, Brattle Circle |
| D-2 / D-1 / E-1 / C-2 / C-3 | no | 11.1 / 6.8 / 3.3 / 2.0 / 1.5 MB | not downloaded | West Cambridge, Fresh Pond, North Cambridge |
| D-4, E-5, F-1, F-5, G-2, G-5, H-2, H-4, I-3, I-4 | n/a | HTTP 404 | n/a | Outside Cambridge (these tiles exist only in the Boston dataset; see section 2) |

**Conclusion: Harvard Square itself is already on disk (E-3).** The only new tiles needed for a
Harvard-inclusive map are **E-2** (Yard north half, Law School, Common) and **F-2** (Kirkland St).
**D-3** is needed only if the map goes west toward Mt Auburn St and the Eliot Bridge.
**Next step:** add E-2 and F-2 to the `for t in ...` loop in `fetch.sh`.

**Catalog details:**
- Columns are the same in every tile: `Center_Lat`, `Center_Long`, `Ground_Elev_Ft`, `Height_Ft`, `Tile`.
- `buildings3d.catalog()` already reads several tiles.
- A few catalog rows carry a `Tile` tag that is inconsistent with their position. For example, E-3 has outliers out to lon -71.0809. This is harmless because the region polygon filter uses `Center_Lat/Long`.

### 1.2 GIS layers

- **All 19 layers in `config.json` are citywide.** `data/raw/cambridge_gis` already covers Harvard, so nothing needs re-fetching for the 2D data.
- **Harvard Yard has paths in the data:** 25 `BASEMAP_PrivateWalkways` and 33 `BASEMAP_PublicFootpaths` polygons.
- `TRANS_Centerlines` has every street around the Yard: Mass Ave, JFK, Brattle, Garden, Kirkland, Quincy, Prescott, Plympton, Holyoke, Dunster, Bow, Linden, Oxford, Divinity Ave and Cambridge St. Harvard's internal Yard paths are pedestrian ways, not centrelines.

The full repo listing, from the GitHub tree API (verified), has more layers that are useful later:
- `Basemap/Fences` (23k lines)
- `Basemap/Stairs`
- `Basemap/Porches`
- `Basemap/Decks`
- `Basemap/Rooftop_Solar_Panels`
- `Trans/Sidewalk_Centerlines` (10 MB)
- `Traffic/Pavement_Markings` (39,391,527 B: vector lane lines and crosswalks, an alternative to the ortho-derived `markings.py` mask)
- `Infra/Catchbasins`
- `Recreation/Open_Space`
- Furniture layers: see section 3.4.

### 1.3 Gaps and caveats

**Elevation.**
- `buildings3d.py` seats every building at z = 0, so the world is flat.
- The ground elevations in the 3D catalog (`Ground_Elev_Ft`, NAVD88) rise gently: median 2.4 m at MIT core, 3.9 m at Central Sq, 5.7 m at Harvard Sq, 6.5 m at Harvard Law and the Common.
- That is about 4 m of rise over about 3 km (under 0.2 % grade), so **the flat world still holds for every stage below**.
- If terrain is ever wanted, MassGIS LiDAR terrain is listed at https://www.mass.gov/info-details/massgis-data-lidar-terrain-data (page resolves; data not downloaded).
- Do not use `BASEMAP_Buildings.ELEV_GL` for ground height: it is a height above ground, not ground elevation.

**Tunnels and underpasses.**
- The Cambridge St underpass beneath Harvard Yard is in the E-3 catalog as "Cambridge Street Underpass", type Tunnel.
- Some centreline segments are flagged `ROADWAYS = N` (e.g. Cambridge St x3, Memorial Dr x12).
- A flat world cannot drive under the Yard. Either skip the underpass segments or treat them as closed.
- Memorial Dr also has underpasses at the River St and Western Ave bridges. This is from general knowledge; it is consistent with the `ROADWAYS = N` Memorial Dr segments, but verify on the ortho.

**Undocumented attributes.**
- The meanings of `Restriction` (T / F) and `ROADWAYS` (T / F / N) in `TRANS_Centerlines` are not documented in the repo.
- `ROADWAYS = T` correlates with divided roads: Mass Ave x69, O'Brien Hwy, Land Blvd.
- **Verify these against the ortho before relying on them.**

**Street signs.**
- The city data has no stop signs or street-name signs. `INFRA_OverheadSigns` has only 30 features.
- OSM has 147 `highway=stop` nodes in stage C (section 3.4).

**Tree data typos.**
- The tree inventory misspells the London plane genus as **`Planatus`** and *Styphnolobium* as `Styphnoloblum`.
- Match those spellings in any genus-to-mesh table.

**Clipping.**
- `clip.py` only supports a rectangular `bbox_lonlat` per region.
- A corridor or L-shape is therefore two adjacent regions, or `clip.py` needs polygon support.
- Overlapping regions would duplicate geometry: either rebuild as one larger region that supersedes `mit_core`, or clip new regions by `box - previous`.

**Rendering cost.** At 7 to 14 km², the always-loaded `ctx_` ring and per-tile building meshes will need HLODs (already noted as a TODO in memory). World Partition streaming (256 m cells, 768 m range) is already in place.

### 1.4 Staged extents

All numbers were computed from the local data: 3D catalog centres, `TRANS_Centerlines` length clipped to the box, `ENVIRONMENTAL_StreetTrees` with the same filter as `props.py` (`SiteType == Tree`, plus MIT/Other-owned campus trees; before thinning), and `INFRA_StreetLights`. The bbox is `[lon0, lat0, lon1, lat1]`, as in `config.json`.

| Stage | bbox / shape | Area | 3D buildings | Street centreline | Trees (raw) | Street lights | New tiles |
|---|---|---|---|---|---|---|---|
| now: `mit_core` | [-71.0965, 42.3555, -71.0840, 42.3640] | 0.97 km² | 342 | 8.4 km | 2,324 | 240 | none |
| **A: MIT + Central Sq** | [-71.1085, 42.3540, -71.0800, 42.3700] | 4.17 km² | 3,818 | 58.4 km | 8,470 | 1,542 | none (F-3/F-4/G-3/G-4 local) |
| **B: + Harvard Sq (L-shape)** | A plus a `harvard` box [-71.1240, 42.3560, -71.1085, 42.3785] | 7.36 km² | 7,213 | 96.5 km | 15,076 | n/a | E-2, F-2 |
| B': same as one rectangle | [-71.1240, 42.3540, -71.0800, 42.3785] | 9.86 km² | 9,972 | 122.4 km | 17,697 | 3,365 | E-2, F-2 |
| **C: full Harvard + MIT** | [-71.1290, 42.3530, -71.0790, 42.3830] | 13.72 km² | 11,778 | 142.9 km | 20,735 | 3,791 | E-2, F-2 |

What each stage covers:

- **A** covers the Mass Ave bridge, Memorial Dr to the BU Bridge, Central Sq, Cambridgeport, Kendall and the whole Mass Ave stretch MIT to Central. It needs no downloads; it is just a new region plus a pipeline rerun. Good for new events, e.g. a Central Sq loop or a Memorial Dr sprint to the BU Bridge.
- **B** adds Memorial Dr to JFK St, the river Houses, Harvard Sq, the Yard, the Science Center and the Common. It enables a Memorial Dr / Mass Ave loop: MIT to Harvard along the river and back via Central, about 6 km. The L-shape saves about 25 % over the rectangle B' by skipping Inman Sq and the Wellington-Harrington grid.
- **C** adds the Law School, Radcliffe Quad, Divinity Ave museums, Brattle St west and riverside Cambridgeport. It is roughly the "whole MIT + Harvard" goal minus North and West Cambridge.

Rough tree cost: about 1,500 to 2,400 inventory trees per km². Today `thin_trees()` keeps 851 of 2,324 in `mit_core` (about 37 %). At that ratio stage A is about 3.1k instances, stage B about 5.6k and stage C about 7.7k. That makes the tree mesh choice (section 4) a hard prerequisite for B and C.

---

## 2. Boston skyline backdrop

### 2.1 Recommended source: City of Boston Planning Department "3D Smart Model" tiled OBJ (verified)

**Same tile grid, same State Plane offset as the Cambridge data.**
- The Boston documentation PDF (`http://maps.bostonplans.org/3d/3D_Data_Documentation.pdf`, 15,990,008 B) gives the origin as X 731,100 / Y 2,902,900 MA State Plane feet.
- A test OBJ vertex from G-5 is `39295.9, 45254.9` = SP (770,396, 2,948,155), consistent with that offset.
- The Bos3d tile grid GeoJSON (cityschema GitHub) has D-13 centred at MASP_X 753,600, so the columns line up with Cambridge's.
- The older pbcGIS metadata page mentions 732,200 ft; that page is from 2020 and is stale.
- **Conclusion: `buildings3d.py`'s transform can be reused for Boston as is.**

**Where the URLs come from.** The download map on https://www.bostonplans.org/3d-data-maps/3d-smart-model/3d-data-download is an ArcGIS Experience (`d8f824291f294fddbb8d211047563c47`). Its web map `cc79d1bd7bdd448c8cb891d344d015d9` popups contain these URL templates (verified with HEAD requests):

```
https://maps.bostonplans.org/3d/Bos3d_BldgModels_20260624_OBJ/BOS_{C}_{R}_BldgModels_OBJ.zip    <- latest (also _20251204_)
https://maps.bostonplans.org/3d/Bos3d_Terrain_2011_OBJ/BOS_{C}_{R}_TerrainMesh_2011_OBJ.zip
https://maps.bostonplans.org/3d/Bos3d_Orthophoto_2023_JPG/BOS_{C}_{R}_Orthophoto_2023.zip
https://maps.bostonplans.org/3d/Bos3d_Groundplan_DXF/BOS_{C}_{R}_Groundplan_DXF.zip
https://maps.bostonplans.org/3d//Bos3d_CityModel_20251204_SKP/BOS_{C}_{R}_CityModel_SKP.zip  (SketchUp, 48 MB for G-5)
```

Tile grid: `https://maps.bostonplans.org/3d/Bos3d_CityWide_Data/Bos3d_TileGrid.zip` (3,828,416 B), or as GeoJSON from the cityschema GitHub repo: `cityschema/repository-catalog/Bos3d_CityWide_Data/Bos3d_TIleGrid/Bos3d_TileGrid.json` (106 tiles).

**Tiles for the view from Memorial Drive** (OBJ, 20260624 release, sizes verified):

| Tile | Covers | Zip size |
|---|---|---|
| **G-5** | Prudential, 200 Clarendon (Hancock), One Dalton, Back Bay south of Beacon St, Copley | 13,227,379 B |
| **G-4** | Back Bay riverfront (Beacon St / Bay State Rd), Esplanade, Boston side of the Mass Ave / Longfellow-west river | 6,720,848 B |
| **H-4** | Beacon Hill, State House, Millennium Tower, Government Center | 12,308,719 B |
| **I-4** | Financial District, Custom House, Post Office Sq, International Place | 7,408,775 B |
| F-5 | Kenmore, Fenway, Longwood | 10,529,630 B |
| H-3 | West End, Zakim Bridge, Charlestown (seen from Kendall / Longfellow) | 11,438,564 B |
| E-4 | BU (Boston side of the BU Bridge) | 8,693,640 B |
| optional: H-5, I-3, G-6 | South End, North End, Roxbury edge | 10.3 / 8.4 / 13.4 MB |

Core four tiles (G-4, G-5, H-4, I-4): **about 40 MB**. All seven: **about 70 MB**.

**Test download of G-5** (13 MB zip, 24 MB extracted, verified):
- Layout:
  - `catalog.csv`: 2,205 rows.
  - `ModelFinder.htm`.
  - `objz/<Model_ID>_OBJ.zip`: one nested zip per building, each holding `<id>.obj`, `materials.mtl` and a `<id>.json` metadata file.
- OBJs are FME-exported and Z-up. Their vertices are offset State Plane feet, with a `# COORDINATE_SYSTEM` header naming EPSG:2249.
- Catalog columns differ from Cambridge's: `Centr_Lat`, `Centr_Lon`, `Gnd_El_Ft`, `Height_Ft`, `Z_Max_Ft`, `Status`, `Model_LOD`, `StructType`, `Name`.
- `Status` values: Current 2,098, History 85, Approved Demo 9, Complete 7, Board Approved 5, Under Construction 1. **Filter to `Status in {Current, Complete}`**: History and Approved buildings are demolished or unbuilt.
- Model LOD: 1.5 (2,050 models), 1 (125), 3 (30). These are block masses with roof shapes, which is fine at 0.7 to 3 km.
- Whole tile: **331,645 triangles across 2,205 models**. 99 models are at least 30 m tall.
- Tallest heights: Hancock 240 m, Prudential 231 m, One Dalton 230 m, 40 Trinity 133 m.

**Licence.**
- The Analyze Boston record for the same model, "Boston 3D Buildings (Existing)" (https://data.boston.gov/dataset/boston-3d-buildings-existing, an ArcGIS SceneServer), is **ODC PDDL** (public domain).
- The OBJ download page shows no licence text. The documentation PDF calls the model "public information available for all to download".
- Treat it as public domain but credit "City of Boston Planning Department, 3D Smart Model" in the game credits.

### 2.2 OpenStreetMap (Overpass): tested, fallback only

Query, run against overpass-api.de on 2026-10-04: `way/relation["building"](42.345,-71.090,42.362,-71.050); out tags center;`. This box covers Back Bay, Beacon Hill and downtown. Results:

- 4,836 buildings. **424 have `height`, 1,406 have `building:levels`, and 1,533 (32 %) have either.**
- The towers are well covered:
  - 42 buildings are at least 100 m and 81 are at least 60 m.
  - Correct heights for 200 Clarendon (240.8 m), Prudential (228.6 m), One Dalton (226 m), Winthrop Center (210.5 m), South Station Tower (210 m), Millennium Tower (209 m), Federal Reserve (187 m) and others.
- **The Back Bay rowhouse fabric is not covered.** Only 417 of 1,388 buildings in the sub-box [-71.090..-71.070, 42.348..42.356] have height or levels. Everything else would need a default height.
- Licence: **ODbL**. Attribution ("© OpenStreetMap contributors") is required, and share-alike applies to any derived *database* (not to rendered output).
- Verdict: worse than the BPDA models on coverage and licence. It is useful only to cross-check heights or to cover Brookline / Somerville, which are outside the BPDA tiles.

### 2.3 Google Photorealistic 3D Tiles / Cesium: not recommended

Map Tiles API policies (https://developers.google.com/maps/documentation/tile/policies, fetched):
- "you must not pre-fetch, index, store, or cache any Content except under the limited conditions stated in the terms".
- "Offline uses" are prohibited.
- "Programmatically reading and recording measurements (heights...)" is prohibited as derivative use.
- All tile attributions must be shown on screen.

Practical consequences:
- Billing is per root tileset request; one session token allows up to three hours of tile requests (https://developers.google.com/maps/documentation/tile/usage-and-billing).
- It needs an API key, a billing account and a network connection at runtime.
- Baking it into a static backdrop mesh is explicitly forbidden.

Cesium for Unreal v2.28.0 (July 2026) lists UE 5.8 support (Cesium blog, not tested here). Even so, streaming photogrammetry tiles for a backdrop costs GPU memory and draw calls on the M4 Pro and makes the game network-dependent. **Not suitable.**

Cesium OSM Buildings (via Cesium ion) is the OSM data in section 2.2 with an ion token added. It brings no advantage over the BPDA models.

### 2.4 Recommended approach for a cheap backdrop

1. **Fetch.** Add a `fetch_boston.sh` step that downloads the G-4, G-5, H-4 and I-4 OBJ zips (later also F-5, H-3, E-4) into `data/raw/bos3d/` (not `camb3d/`, because tile names collide). Unzip, including the nested `objz/*.zip`.
2. **Load.** Generalise `buildings3d.load()` with a column map (`Centr_Lon`/`Centr_Lat`/`Gnd_El_Ft`/`Height_Ft`) and a `Status` filter. The coordinate transform is identical.
3. **Filter.**
   - Drop buildings under about 12 m beyond about 1.5 km from the Cambridge bank.
   - Keep everything on the riverfront (G-4, Beacon St), because those rowhouses are the first row seen across the river.
   - Estimated total is well under 1.5 M triangles for the core four tiles, since G-5 is 332k triangles in full.
4. **Mesh.**
   - Merge per tile and material class into a few `ctx_boston_*` meshes.
   - Nanite, no collision, always loaded, like the existing `ctx_` ring.
   - Reuse the procedural facade masters (`facade_brick_red` for Back Bay and Beacon Hill, `glass`/`metal` for towers taller than 60 m, `limestone` otherwise).
   - At 1 to 3 km, flat facade materials plus the existing fog and aerial perspective will read correctly.
5. **Ground (optional).** The Boston 2023 orthophoto per tile (`Bos3d_Orthophoto_2023_JPG`, about 20 MB per tile) or the existing MassGIS ortho fetch could texture a flat Boston ground plane and the Esplanade.
6. **Cost.** Expect a few draw calls and a fraction of a millisecond of GPU time. If profiling ever shows otherwise, bake the farthest tiles (I-4, H-3) into a skyline impostor card.

---

## 3. Street furniture

### 3.1 Poly Haven (CC0): verified via `api.polyhaven.com`

Poly Haven has 521 models in total. The relevant ones, with polycounts as listed by the API and the
glTF size at 1k textures (including textures):

| Asset | Polys | glTF 1k | Note |
|---|---|---|---|
| `fire_hydrant` | 86,316 | 5.5 MB | Heavy; needs decimation or Nanite. Check it looks US/Boston-style (Cambridge hydrants are mostly red/silver Mueller types). |
| `metal_trash_can` | 13,960 | 5.0 MB | Generic metal bin. |
| `painted_wooden_bench` | 630 | 2.0 MB | Very cheap. |
| `modular_street_seating` | 25,156 | 7.6 MB | Modern benches. |
| `street_lamp_01` / `_02` | 30,610 / 20,338 | 2.2 / 1.9 MB | Alternative to the generated lamp poles. |
| `concrete_road_barrier` / `_02` | 80,776 / 42,578 | 3.8 MB | Jersey barriers. |
| `utility_box_01` / `_02` | 4,404 / 6,268 | 2.0 MB | Signal and utility cabinets at intersections. |
| `modular_electricity_poles` | 200,610 | 12.4 MB | For `INFRA_UtilityPoles`. |
| `water_manhole_cover` | 6,301 | 2.3 MB | Pairs with `INFRA_Catchbasin`. |
| `modular_chainlink_fence` | 89,232 | n/a | For `BASEMAP_Fences`. |
| `wooden_picnic_table`, `planter_box_01..03` | 10k to 13k | n/a | Parks. |
| `shrub_01..04` | 17k to 282k | about 2 MB | Hedges and planting beds. |

Download URL pattern (verified): `https://dl.polyhaven.org/file/ph-assets/Models/gltf/1k/<id>/<id>_1k.gltf`. The API file list is at `https://api.polyhaven.com/files/<id>`.

**Poly Haven has no** traffic signal, pedestrian signal, street or regulatory sign, bollard, parking meter or pay station, bike rack, bus shelter, or bike-share dock.

### 3.2 Other free libraries

**Sketchfab** (API search, `downloadable=true`):
- **The CC0 filter returns almost nothing** for these terms: 0 results for hydrant, bench, traffic light, bus shelter, meter, bollard, trash can and bike rack.
- CC-BY results are plentiful. Downloading needs a free Sketchfab account (the user must log in). Credit each author.
- Picks below were verified via `api.sketchfab.com/v3/models/<uid>`, showing licence and face count:

| Item | Model | Author | Faces | Licence |
|---|---|---|---|---|
| Mixed pack (hydrant, signs, cones, etc.) | https://sketchfab.com/3d-models/street-asset-pack-f3eb47d02e2e4ab290e66752fa354b48 | vmatthew | 37,840 | CC-BY 4.0 |
| Hydrant (US) | https://sketchfab.com/3d-models/american-fire-hydrant-d021f42ea8c44afe9c90655beaa36d89 | Fayruso | 34,568 | CC-BY |
| Pedestrian signal (US Econolite) | https://sketchfab.com/3d-models/econolite-e8-neon-pedestrian-signals-b83dd241ddba42f69b0445fa91bab781 | Signalrenders | 11,802 | CC-BY |
| Parking meter | https://sketchfab.com/3d-models/parking-meter-cfaf0f457ca244e59c746ebdd6f3ad6c | Raffey | 12,345 | CC-BY |
| Bench | https://sketchfab.com/3d-models/classic-park-bench-low-poly-01a5b64427984632bb44242da3813bb1 | berkgedik | 4,796 | CC-BY |
| Trash can | https://sketchfab.com/3d-models/trash-can-f61aeec14ff441abb0f6add5485a2e90 | longtail | 3,920 | CC-BY |
| Bike rack | https://sketchfab.com/3d-models/bike-rack-bb71ca627c5c44aba68c610fbfa24cd2 | Sam54123 | 8,384 | CC-BY |
| Bus shelter | https://sketchfab.com/3d-models/bus-station-8c984e73fa274c49a444f9991444d542 | turtlesomber | 8,396 | CC-BY |
| Road signs | https://sketchfab.com/3d-models/road-signs-c39bf97110494b5db3de84165211f592 | FrodoUndead | 14,252 | CC-BY (check the sign style is US MUTCD) |
| Newspaper box | https://sketchfab.com/3d-models/newspaper-box-with-mat-e4dd34bb4e384dee82d80889fa3742b9 | neverfollow81 | 1,320 | CC-BY |
| USPS mailbox | https://sketchfab.com/3d-models/us-mailbox-3376b03ebf1d45ea99fbb6ff350489da | yrdoes | 1,854 | CC-BY |

The model titled "CC0 - Bicycle Stand 4" (plaggy) is actually licensed **CC-BY** according to the API, so it is not CC0.

**ambientCG** (CC0):
- The API now returns only Material, HDRI and Atlas types, with **no 3D models**.
- Useful for surfaces: `ManholeCover011`, `Road*`, `Asphalt*`, `AsphaltDamageSet001/002`, and the leaf atlases (section 4).

**Kenney** (https://kenney.nl/assets/city-kit-roads, `city-kit-suburban`) and **Quaternius** (https://quaternius.com/packs/ultimatenature.html):
- Both pages resolve and both are CC0.
- They are stylised low-poly and would clash with the realistic look. Use them only as placeholders.

**Smithsonian 3D:** nothing relevant (museum objects).

**Recommendation: generate simple items procedurally in Python**, as `props.py` already does for lamp poles.
- Items: bollards, parking-meter and pay-station posts, sign posts with MUTCD sign faces (STOP, ONE WAY, street-name blades in Cambridge's green), mast-arm traffic signals and pedestrian heads, bike racks (Cambridge uses inverted-U "staple" racks), and Bluebikes docks (kiosk plus a row of docks).
- Generated items are exact, very cheap, licence-free and US-correct.
- Use Poly Haven for the organic or detailed items: hydrant (decimated), trash can, benches, utility boxes, barriers and manholes.

### 3.3 Placement data (where furniture goes)

**Cambridge GIS**: `https://raw.githubusercontent.com/cambridgegis/cambridgegis_data/main/<path>.geojson`. Licence is ODC PDDL. All files were downloaded and parsed. Counts are given for `mit_core` and for stage C.

| Layer path | Features | mit_core | C | Geometry and useful fields |
|---|---|---|---|---|
| `Infra/Hydrants/INFRA_Hydrants` | 1,960 | 107 | 1,134 | Points with **`ROTATION`**. `ContractAuthority` includes "PRIVATE HARVARD", so Harvard's hydrants are covered. |
| `Infra/Park_Benches/INFRA_ParkBenches` | 3,017 | 286 | 1,905 | **LineStrings** (bench footprint), which give length and orientation. |
| `DPW/Litter_Barrels/DPW_LitterBarrels` | 990 | 23 | 711 | Points: `TYPE` (e.g. BB = BigBelly), `LOCATION`. |
| `Recreation/Bike_Racks/RECREATION_BikeRacks` | 2,892 | 232 | 2,298 | Points: `Racks`, `Capacity`, `Status`. |
| `Trans/Bus_Shelters/TRANS_BusShelters` | 68 | 8 | 45 | Footprint polygons with heights (`TOP_GL`). |
| `Traffic/Traffic_Signals/TRAFFIC_Signals` | 785 | 74 | 480 | Points, about 4 per intersection (630 named points across about 152 intersections, plus 155 unnamed). They look like per-pole or per-head locations. `Jurisdiction` is City / DCR (Memorial Dr) / MassDOT. |
| `Traffic/Metered_Parking_Spaces/TRAFFIC_MeteredParkingSpaces` | 3,320 | 254 | 2,731 | Space polygons: `SmartMeter`, `Rate`, `MaxTime`. Put a meter post at the curb end of each space, or pay stations every N spaces. |
| `Infra/Overhead_Signs/INFRA_OverheadSigns` | 30 | 2 | 8 | Lines (gantries). |
| `Infra/Utility_Poles/INFRA_UtilityPoles` | 2,457 | 55 | 1,121 | Points. |
| `Infra/Park_Lights/INFRA_ParkLights` | 858 | 0 | 519 | Points: `Description` (e.g. "Ornamental Tear Drop"). |
| `Infra/Street_Lights_Not_City_Owned/...` | 1,590 | 228 | 868 | Points. **MIT and Harvard private lights are missing from the current `INFRA_StreetLights`.** |
| `Trans/Subway_Headhouses/TRANS_SubwayHeadhouses` | 11 | 2 | 11 | Footprints with heights. The Harvard, Central and Kendall T entrances, including the Harvard Sq kiosk. |
| `Recreation/Bike_Facilities/RECREATION_BikeFacilities` | 671 | 36 | 414 | Bike-lane lines, for green paint and separated-lane posts. |
| `Basemap/Fences/BASEMAP_Fences` | 23,153 | 245 | 12,078 | Lines. |
| `Traffic/Pavement_Markings/TRAFFIC_PavementMarkings` | n/a | n/a | n/a | 39.4 MB (HEAD only). Vector markings. |
| also available | | | | `Infra/Catchbasins` (7.8 MB), `License/Taxi_Cab_Stands`, `Landmark/Memorial_Poles`, `Infra/Billboards`, `DPW/Pedestrian_Ramps` |

**Bluebikes (GBFS)**: `https://gbfs.bluebikes.com/gbfs/en/station_information.json` (verified, 361,588 B).
- 624 stations: **84 in stage C, 9 in `mit_core`**.
- Fields: `lat`, `lon`, `capacity` (number of docks), `name`, `has_kiosk`.
- Data licence: https://bluebikes.com/data-license-agreement (resolves). It is a free-use licence with attribution; read it before shipping.

**MBTA bus stops.**
- GTFS: `https://cdn.mbta.com/MBTA_GTFS.zip` (24,684,874 B, updated 2026-10-02, not downloaded). Take `stops.txt` with `location_type = 0` and filter by bbox.
- Or the V3 API, tested: `https://api-v3.mbta.com/stops?filter[route_type]=3&filter[latitude]=..&filter[longitude]=..&filter[radius]=..`. A 0.02° radius around Central Sq returned 203 stops, 177 of them in stage C, so there are **at least 177**. Records carry `on_street` and `wheelchair_boarding`. Use GTFS `stops.txt` for the full bbox. Without an API key the rate limit is low; that is fine for a one-off fetch.
- MBTA data is published for developers under the MassDOT developers' licence agreement (not verified). Attribute "MBTA".
- Put a bus-stop sign pole at each stop. The 45 shelters in stage C come from `TRANS_BusShelters`.

**OpenStreetMap** (Overpass, stage C bbox, tested) for comparison and gap-filling:

| Tag | Count |
|---|---|
| `highway=crossing` | 3,319 |
| `amenity=bicycle_parking` | 1,232 |
| `highway=street_lamp` | 1,129 |
| `amenity=bench` | 1,018 |
| `amenity=waste_basket` | 434 |
| `emergency=fire_hydrant` | 420 |
| `highway=traffic_signals` | 364 |
| `highway=bus_stop` | 225 |
| **`highway=stop`** | **147** |
| `barrier=bollard` | 139 |
| `amenity=post_box` | 99 |
| `amenity=bicycle_rental` | 73 |

**OSM is the only source here for stop signs, post boxes and bollards** (ODbL, with attribution). Elsewhere, prefer the city layers.

Street-name signs have no dataset. Generate them from `TRANS_Intersections` plus the centreline names: one blade pair per intersection corner.

---

## 4. Trees

Context:
- The current tree is the Poly Haven `jacaranda_tree`: 312,356 polys, masked leaf cards, 851 instances (after commit f3e40c1).
- It costs about 12 ms of GPU time (memory notes).
- Any replacement must be *cheaper* per instance, because stage B/C multiplies the count 6 to 10 times.

Inventory composition (citywide live trees = 31,183):

| Genus | Count | Main species |
|---|---|---|
| Acer | 4,521 | red maple 1,764; Norway maple 1,686; sugar maple 308 |
| Quercus | 3,594 | pin oak 1,507; northern red oak 1,125; swamp white oak 675 |
| Gleditsia | 2,850 | honeylocust |
| Ulmus | 1,762 | American elm 917 |
| Tilia | 1,511 | littleleaf linden 919; American linden 439 |
| Fraxinus | 1,412 | |
| Prunus | 1,272 | Japanese cherry 352 |
| Planatus [sic] | 1,264 | London plane 832; sycamore 332 |
| Pyrus | 963 | Callery pear |
| Zelkova | 790 | |
| Betula | 631 | river birch 460 |
| Ginkgo | 544 | |

Stage C order is similar: Acer, Quercus, Gleditsia, Ulmus, Tilia, Planatus, Prunus, Pyrus, Zelkova, Cornus.

### 4.1 Procedural Vegetation Editor: already installed, no login (verified locally)

The plugin is at `~/UE_5.8/Engine/Plugins/Experimental/ProceduralVegetationEditor`. It is "Experimental", disabled by default, and **lists `Mac` in `PlatformAllowList`**. It depends on Dataflow, GeometryScripting, PCG and DynamicWind. Its `Content/` folder (553 MB) ships these samples:

- `SampleAssets/Tree_Norway_Maple_01/Instances/NorwayMaple_01..04.json`. **This is Acer platanoides, the species with 1,686 trees in the inventory.**
- `Tree_European_Beech_01` (4 variants), `Tree_European_QuakingAspen_01` (4), `Tree_Common_Hazel_01` (5).
- `StarterContent/Presets`: `PVE_Preset_Leaf_Tree_01..04`, `Shrub_01`, `Sapling_01`, `Pine_01`, `Spruce_01/02`, `Tropical_01`.
- `StarterContent/DeciduousTree_01`: a full sample tree with bark and foliage materials.

How it works:
- The species JSONs are growth skeletons: global growth attributes plus branch points and primitives. They are not meshes.
- PVE turns them into **Nanite Foliage** assets. Those are skeletal meshes with Dynamic Wind skinning instead of world-position offset (WPO), with Nanite Assemblies for instanced twigs and Nanite Voxels for distance LOD (UE 5.7+ feature; see Tom Looman's "UE 5.7 Performance Highlights" and Epic's docs).

**Leaf type, honestly assessed.** The starter tree's foliage textures are `T_LeafTree_01_Foliage_CA` (colour plus alpha) on `SKM_Leaf_Twig_*` instances. **So leaves are still alpha-masked twig cards, not opaque leaf geometry.** The win over the jacaranda is that Nanite Voxels replace distant canopies, so masked overdraw only happens near the camera. It is not alpha-free. Measure with `-ShotTourProfile` before committing.

**Workflow caveat.** PVE is an in-editor node-graph GUI. Trees must be authored once, interactively, then saved as assets that `import_props` / `build_level` instance. It cannot run inside the headless mapgen pipeline. The plugin is Experimental, but this is a single-machine game, so shipping risk is acceptable.

### 4.2 Quixel Megaplants on Fab (free, needs the user's Epic login)

- Quixel's posts (https://quixel.com/news/quixel-on-fab-new-megascans-and-megaplants, 2026-04-08, and https://quixel.com/news/discover-the-latest-quixel-megascans-and-free-megaplants) say Megaplants are "free to use under the Fab Standard License".
- Each one is a PVE preset pack with scanned branch and leaf meshes and textures, plus Nanite Foliage support.
- New Megaplants "will be compatible with UE 5.8 and above only". Epic notes that Megaplants and PVE are Experimental and that they "do not recommend shipping projects with Experimental features".
- Fab listing pages return HTTP 403 to non-browser fetches, so polycounts could not be read. **Download requires the user to log in to Fab** (or use the in-editor Fab plugin).

Matches to the inventory:

| Cambridge genus | Megaplant | Fit |
|---|---|---|
| Quercus | **English Oak** (https://www.fab.com/listings/83642c38-7661-4df1-8629-0422e1898d26) | Good silhouette stand-in for red and pin oak |
| Acer | **Norway Maple Forest** (https://www.fab.com/listings/e789ad04-cf79-4973-adb0-85c794d77144), Norway Maple Saplings | Exact for Norway maple; OK for red maple |
| Ginkgo | **Ginkgo** (https://www.fab.com/listings/53f033c3-00ec-425b-b44e-65c04fdbd2b0, announced 2026-08-31) | Exact |
| Betula | **Silver Birch** | Close enough for river birch at street scale |
| Prunus | **Yoshino Cherry** | Exact for Japanese cherry |
| Ulmus / Zelkova (vase form) | **European Hornbeam**, European Beech | Approximate only |
| Gleditsia, Platanus, Tilia, Cornus, Pyrus | none found | Build from PVE presets with custom leaves (below) |

Other free Megaplants listed include Black Alder, Common Hazel, European Aspen, Goat Willow, Japanese Medlar, Elder, Norway Spruce, Japanese Cypress, Baltic Pine and Greasewood.

The older "Megascans Trees: Norway Maple" (non-PVE, 15 trees) was free on the UE Marketplace and Fab according to search results. Since 2025, Megascans in general follow Fab's paid model. **Not verified.**

### 4.3 Covering the unmatched genera

**ambientCG leaf atlases** (CC0, verified via API, type Atlas):
- `LeafSet001..030`. Tagged ones include `LeafSet016` (oak, spring), `LeafSet012` (oak, autumn) and `LeafSet027` (maple).
- They can re-skin PVE preset trees to read as honeylocust (fine pinnate leaves: use a small-leaf set and a sparse canopy), London plane, linden and elm.
- `Bark014`, plus Poly Haven bark textures, cover the bark. Plane-tree camouflage bark needs its own texture, which is the plane tree's most recognisable feature.

**Sketchfab** (verified via API):

| Genus | Model | Author | Faces | Licence |
|---|---|---|---|---|
| Zelkova | https://sketchfab.com/3d-models/cc0-japanese-zelkova-zelkova-serrata-024e8b42dd2a4657aec9d4c872337ab1 | ffishAsia-and-floraZia | 309,379 | **CC0** |
| Tilia | https://sketchfab.com/3d-models/linden-tree-c0c3aa73cc9945d2a36c01a0d8d6d4bb | intice184 | 46,236 | CC-BY |
| Tilia | https://sketchfab.com/3d-models/4-linden-trees-pack-medium-poly-b497c5f3f26344c29f27f53dc2ca74f4 | Sereib | 139,971 (4 trees) | CC-BY |
| Ulmus | https://sketchfab.com/3d-models/high-detail-elm-tree-collection-0fee36ee370244688c91ab430f87b039 | Jagobo | 342,480 | CC-BY |
| Gleditsia | https://sketchfab.com/3d-models/honey-locust-b42beff7506349f8901de2d148e30b0f | sananga | 57,329 | CC-BY (0 likes; quality unknown) |
| Ginkgo | https://sketchfab.com/3d-models/ginkgo-tree-springsummer-2aa9348064c243f8b1f67ba73707c45e | PuzzledPapaya | 24,756 | CC-BY |
| Quercus | https://sketchfab.com/3d-models/mighty-oak-trees-4f6ab5594a8a415aba3f958682b9ced5 | Jagobo | 344,224 | CC-BY |
| Quercus | https://sketchfab.com/3d-models/realistic-hd-northern-red-oak-37138-b7ed18f291c3445a8b805da379e3de4f | PlantCatalog | 202,617 | CC-BY |
| Acer | https://sketchfab.com/3d-models/maple-trees-9f51e08e56cd4e44b35fd02a3ad8d3a6 | Jagobo | 165,167 | CC-BY |
| Prunus | https://sketchfab.com/3d-models/cherry-blossom-trees-f69be55d2e4f4f73b568ebb185bd8496 | Jagobo | 156,838 | CC-BY |

- None of these were downloaded, because downloading needs a Sketchfab login.
- Assume masked leaf cards. Expect the same import fixes the jacaranda needed: a keyed alpha atlas and the project's own bark materials.
- The Sketchfab CC0 filter found nothing for honey locust, London plane, linden, elm, ginkgo, birch, dogwood, cherry or maple.

**Poly Haven trees** (CC0) are a dead end for these genera:
- `jacaranda_tree` (312k polys, in use).
- `island_tree_01..03` (1.8M to 4.8M polys).
- `tree_small_02` (4.65M).
- Fir and pine (2.3M to 17M).
- Southern-African Namaqualand species.
- No temperate street-tree species.

**SpeedTree:** no current free species library found. Search results only point to the 2014 UE4 samples. **Not verified; skip.**

---

## 5. Recommended plan

Order is by visual payoff per hour, given the existing pipeline. The effort figures are agent-hours of pipeline work plus the main session's UE builds.

| # | Task | Effort | Why this order |
|---|---|---|---|
| 1 | **Boston backdrop from BPDA OBJ tiles.** G-4, G-5, H-4 and I-4 first, then F-5, H-3 and E-4. Generalise `buildings3d.py` (column map, `Status` filter, nested zips). Merge into no-collision Nanite `ctx_boston_*` meshes with the existing facade masters. Add a credit line. | about 1 day | Biggest change in what you see from Memorial Dr. Same CRS and offset as Cambridge, so it is mostly plumbing. Render cost is negligible: about 0.3 to 1.5 M triangles, always loaded, a few draws. |
| 2 | **Stage A region** ([-71.1085, 42.3540, -71.0800, 42.3700]): superseding region or `box - mit_core` clip, then `fetch_ortho`, `build_meshes`, `props`, `import`, `build_level`. New events: a Central Sq loop and Memorial Dr to the BU Bridge. | half a day of compute plus about half a day of fixes | No downloads. It tests pipeline scale (4.3x the area, about 11x the buildings) before Harvard. Watch for `ctx_` ring HLOD and tree counts. |
| 3 | **Tree species via PVE.** Enable the plugin. Build 5 to 6 species: Norway maple (sample), plus Leaf_Tree presets re-leafed as honeylocust, oak, linden, plane, elm and zelkova, each with 2 to 3 size variants. Add a genus-to-mesh map in `props.py` using `Planatus`. Profile against the jacaranda. Optionally, the user logs in to Fab for English Oak, Ginkgo, Silver Birch and Yoshino Cherry. | 2 to 3 days (GUI-heavy, main session) | Variety plus a likely perf win from Nanite voxel LOD. **Must land before stage B**, which needs about 5.6k trees. |
| 4 | **Street furniture.** Placement from the Cambridge layers (hydrants, benches, litter barrels, bike racks, signals, meters, bus shelters, headhouses), Bluebikes GBFS, MBTA stops, and OSM stop signs and bollards. Procedural meshes for poles, signals, signs, bollards, meters, racks and Bluebikes docks. Poly Haven for hydrant (decimated), trash can, benches, utility boxes, barriers and manholes. ISM per tile, like the existing props. | 1.5 to 2 days | Big realism gain at street level for low GPU cost (small instanced meshes; cull at about 150 to 250 m). |
| 5 | **Stage B** (add the `harvard` box plus the E-2 and F-2 tiles, 16 MB). Memorial Dr / Mass Ave loop event. Handle the Cambridge St underpass. | about 1 day plus HLOD work | After 1 to 4 are in, this is mostly a rerun at 7.4 km². |
| 6 | Stage C, the D-3 west extension and Pavement_Markings vectors | later | Diminishing returns versus the hardware schedule. |

**Credits / licences to add to the game:**
- City of Cambridge GIS (PDDL).
- City of Boston Planning Department 3D Smart Model (PDDL per Analyze Boston).
- MassGIS.
- Poly Haven, ambientCG, Kenney, Quaternius (CC0; credit optional).
- Each CC-BY Sketchfab author used.
- © OpenStreetMap contributors (ODbL), if OSM points are used.
- Bluebikes data licence and MBTA, if their stops and stations are used.
- Fab Standard License items (Megaplants): check the licence's redistribution terms before shipping a build (not verified).
