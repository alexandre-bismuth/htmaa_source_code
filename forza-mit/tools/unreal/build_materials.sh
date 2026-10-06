#!/bin/sh
# Textures + materials for a region (headless). Usage: tools/unreal/build_materials.sh mit_core
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
. "$HERE/ue_common.sh"
for phase in import build; do
  ue_py "$HERE/build_materials.py $phase ${1:-mit_core}" || exit 1
done
cat "$HERE/../../data/processed/${1:-mit_core}/meshes/ue_materials_report.json"
