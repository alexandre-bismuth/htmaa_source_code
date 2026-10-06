#!/bin/sh
# Import a generated region into the Unreal project (headless). Usage: tools/unreal/import_region.sh mit_core
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
. "$HERE/ue_common.sh"
for phase in import post verify; do
  ue_py "$HERE/import_meshes.py $phase ${1:-mit_core}" || exit 1
done
cat "$HERE/../../data/processed/${1:-mit_core}/meshes/ue_import_report.json"
