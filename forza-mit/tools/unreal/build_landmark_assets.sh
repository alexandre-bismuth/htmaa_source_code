#!/bin/sh
# Landmark sign material (M_LandmarkSign). Usage: tools/unreal/build_landmark_assets.sh
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
. "$HERE/ue_common.sh"
ue_py "$HERE/build_landmark_assets.py" "M_LandmarkSign|saved "
