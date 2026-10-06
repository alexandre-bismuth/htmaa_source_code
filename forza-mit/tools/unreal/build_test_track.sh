#!/bin/sh
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
PROJ_DIR="$HERE/../../CambridgeRacer"
rm -f "$PROJ_DIR/Content/Cambridge/Maps/DriveTest.umap"
. "$HERE/ue_common.sh"
ue_py "$HERE/build_test_track.py"
