#!/bin/sh
# Download raw Cambridge GIS layers (public domain, ODC PDDL 1.0) into data/raw/cambridge_gis.
# Files already present are kept (reproducible rebuilds); REFRESH=1 ./fetch.sh re-downloads the GIS layers.
set -e
DEST="$(cd "$(dirname "$0")/../.." && pwd)/data/raw/cambridge_gis"
R=https://raw.githubusercontent.com/cambridgegis/cambridgegis_data/main
mkdir -p "$DEST"
for p in Basemap/Roads/BASEMAP_Roads Basemap/Curbs/BASEMAP_Curbs Basemap/Sidewalks/BASEMAP_Sidewalks \
         Basemap/Buildings/BASEMAP_Buildings Basemap/Bridges/BASEMAP_Bridges Basemap/Driveways/BASEMAP_Driveways \
         Basemap/Walls/BASEMAP_Walls Basemap/Plazas/BASEMAP_Plazas Basemap/Vegetation/BASEMAP_Vegetation \
         Trans/Street_Centerlines/TRANS_Centerlines Trans/Intersections/TRANS_Intersections \
         Hydro/Water_Bodies/HYDRO_WaterBodies Basemap/Parking_Lots/BASEMAP_ParkingLots \
         Basemap/Public_Footpaths/BASEMAP_PublicFootpaths Basemap/Private_Walkways/BASEMAP_PrivateWalkways \
         Basemap/Other_Impervious_Surfaces/BASEMAP_ImperviousOther Basemap/Rooftop_Mechanicals/BASEMAP_RooftopMechanicals \
         Environmental/Trees/ENVIRONMENTAL_StreetTrees Infra/Street_Lights/INFRA_StreetLights \
         Boundary/City_Boundary/BOUNDARY_CityBoundary; do
  [ -z "$REFRESH" ] && [ -f "$DEST/$(basename $p).geojson" ] && continue
  curl -sfL "$R/$p.geojson" -o "$DEST/$(basename $p).geojson" && echo "ok   $p" || echo "FAIL $p"
done

# City Assessing FY2026 parcels + property database (exterior wall type -> facade style, build_meshes.py)
for f in ASSESSING_ParcelsFY2026.geojson ASSESSING_PropertyDatabase_FY2026.csv; do
  [ -f "$DEST/$f" ] || { curl -sfL "$R/Assessing/FY2026/FY2026_Parcels/$f" -o "$DEST/$f" && echo "ok   $f" || echo "FAIL $f"; }
done

# Street furniture placement (tools/mapgen/props.py place_furniture)
for p in Infra/Hydrants/INFRA_Hydrants Infra/Park_Benches/INFRA_ParkBenches DPW/Litter_Barrels/DPW_LitterBarrels \
         Recreation/Bike_Racks/RECREATION_BikeRacks Trans/Bus_Shelters/TRANS_BusShelters Traffic/Traffic_Signals/TRAFFIC_Signals \
         Traffic/Metered_Parking_Spaces/TRAFFIC_MeteredParkingSpaces Infra/Street_Lights_Not_City_Owned/INFRA_StreetLightsNotCityOwned \
         Infra/Utility_Poles/INFRA_UtilityPoles Basemap/Fences/BASEMAP_Fences Traffic/Pavement_Markings/TRAFFIC_PavementMarkings; do
  [ -f "$DEST/$(basename $p).geojson" ] || { curl -sfL "$R/$p.geojson" -o "$DEST/$(basename $p).geojson" && echo "ok   $p" || echo "FAIL $p"; }
done

# City 3D building models (OBJ, 2023 update), one zip per 5000 ft tile: the union of every region's
# camb3d_tiles in config.json (geo.all_tiles)
HERE="$(cd "$(dirname "$0")" && pwd)"
D3="$(cd "$(dirname "$0")/../.." && pwd)/data/raw/camb3d"
mkdir -p "$D3"
TILES=$(cd "$HERE" && python3 -c "import json;c=json.load(open('config.json'));print(' '.join(sorted(set(c['camb3d_tiles']).union(*[r.get('camb3d_tiles',[]) for r in c['regions'].values()]))))")
for t in $TILES; do
  [ -d "$D3/$t" ] || { curl -sfL "https://cambmagisdata.blob.core.windows.net/camb3d/Camb3D_${t}_2023_Bulding_Models_OBJ.zip" -o "$D3/$t.zip" && unzip -oq "$D3/$t.zip" -d "$D3/$t" && echo "ok   3D $t"; }
done
