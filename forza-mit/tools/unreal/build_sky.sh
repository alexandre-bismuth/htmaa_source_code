#!/bin/sh
# Sky dome assets (headless): tools/unreal/build_sky.sh, after tools/mapgen/fetch_sky.py and tools/blender/make_sky.py.
# Then tools/unreal/build_level.sh places the dome (and aims the sun at the photo's sun).
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
. "$HERE/ue_common.sh"
LOG="$HERE/../../data/processed/common/sky/build_sky.log"
: > "$LOG"
ue_py "$HERE/build_sky.py import" "" "$LOG" || exit 1
ue_py "$HERE/build_sky.py build" "" "$LOG" || exit 1
