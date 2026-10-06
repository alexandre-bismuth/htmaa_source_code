#!/bin/sh
# Import shared props (trees, lamps, poles) into the project (headless).
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
. "$HERE/ue_common.sh"
for phase in import post; do
  ue_py "$HERE/import_props.py $phase" || exit 1
done
