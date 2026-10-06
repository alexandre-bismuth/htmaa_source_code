#!/bin/sh
# Restore the Unreal Content/ folder on a fresh clone (Content/ is not in git).
# 1) template assets from the engine's Vehicle template, 2) then rebuild generated content:
#    tools/mapgen: fetch.sh, clip.py, build_meshes.py ; tools/unreal: import_region.sh, build_level.sh
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
UE="${UE_ROOT:-$HOME/UE_5.8}"
C="$HERE/../../CambridgeRacer/Content"
mkdir -p "$C/Vehicles" "$C/Input"
cp -R "$UE/Templates/TP_VehicleAdv/Content/" "$C/"
cp -R "$UE/Templates/TemplateResources/Standard/Vehicles/Content/" "$C/Vehicles/"
cp -R "$UE/Templates/TemplateResources/High/Input/Content/" "$C/Input/"
echo "template content restored into $C"
