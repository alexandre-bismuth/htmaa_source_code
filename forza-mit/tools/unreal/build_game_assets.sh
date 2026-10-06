#!/bin/sh
# Gameplay assets (gate / start-box / curtain materials, racing line, race UI sounds). Usage: tools/unreal/build_game_assets.sh
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
. "$HERE/ue_common.sh"
ue_py "$HERE/build_game_assets.py" "IMC_Vehicle_Default|imported "
