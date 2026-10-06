#!/bin/sh
# Import the procedural STi car (tools/mapgen/make_sti.py) into /Game/Cambridge/Car.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
. "$HERE/ue_common.sh"
for phase in import post; do
  ue_py "$HERE/import_car.py $phase" || exit 1
done
