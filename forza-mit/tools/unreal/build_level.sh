#!/bin/sh
# Rebuild the playable World Partition level for a region (headless). Usage: tools/unreal/build_level.sh mit_core
#   1. build_level.py build      plain level from the meshes / props (see build_level.py)
#   2. WorldPartitionConvertCommandlet, in place: one file per actor under Content/__ExternalActors__
#   3. build_level.py streaming  World Partition grid (cell size / loading range)
# The old map (and its external actors) must be deleted BEFORE the editor starts: once the asset
# registry has indexed it, new_level_from_template refuses to overwrite it.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
REGION="${1:-mit_core}"
PROJ_DIR="$HERE/../../CambridgeRacer"
UE="${UE_ROOT:-$HOME/UE_5.8}/Engine/Binaries/Mac/UnrealEditor-Cmd"
MAP="/Game/Cambridge/Maps/$REGION"
LOG="$HERE/../../data/processed/$REGION/meshes/build_level.log"
rm -f "$PROJ_DIR/Content/Cambridge/Maps/$REGION.umap"
rm -f "$PROJ_DIR/Content/Cambridge/Maps/$REGION.ini"   # converter-generated; regenerated each build
rm -rf "$PROJ_DIR/Content/__ExternalActors__/Cambridge/Maps/$REGION" "$PROJ_DIR/Content/__ExternalObjects__/Cambridge/Maps/$REGION"

. "$HERE/ue_common.sh"
py() { ue_py "$HERE/build_level.py $1 $REGION" "" "$LOG" || exit 1; }

: > "$LOG"
echo "== build"; py build
echo "== convert to World Partition"
"$UE" "$PROJ_DIR/CambridgeRacer.uproject" -run=WorldPartitionConvertCommandlet "$MAP" -AllowCommandletRendering -unattended -nosplash -stdout \
  | tee -a "$LOG" | grep -E "LogWorldPartitionConvertCommandlet: (Error|Warning|Display)|Commandlet->Main return" || true
grep -q "LogWorldPartitionConvertCommandlet: Display: Conversion took" "$LOG" || { echo "FAILED: World Partition conversion (log: $LOG)" >&2; exit 1; }
echo "== streaming settings"; py streaming
echo "external actors: $(find "$PROJ_DIR/Content/__ExternalActors__/Cambridge/Maps/$REGION" -name '*.uasset' 2>/dev/null | wc -l)"
cat "$HERE/../../data/processed/$REGION/meshes/ue_level_report.json" | head -30
