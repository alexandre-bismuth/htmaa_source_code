#!/bin/sh
# Precompiles every module except main.py to ARMv6-M .mpy (native/viper code included) into build/,
# then, with --upload, copies them and main.py to the board.
#   ./build.sh [--upload]        (needs: pip install mpy-cross mpremote; mpremote mip install ssd1306)
set -e
cd "$(dirname "$0")"
MPY_CROSS="mpy-cross"
command -v mpy-cross >/dev/null || MPY_CROSS="uvx mpy-cross"
rm -rf build && mkdir build
for f in *.py; do
  [ "$f" = main.py ] || [ "$f" = bench.py ] && continue
  $MPY_CROSS -march=armv6m -o "build/${f%.py}.mpy" "$f"
done
$MPY_CROSS -march=armv6m -o build/bench.mpy bench.py
ls -l build | awk 'NR > 1 {s += $5} END {print "build/: " s " bytes of .mpy"}'
if [ "$1" = "--upload" ]; then
  mpremote cp build/*.mpy : + cp main.py :
fi
