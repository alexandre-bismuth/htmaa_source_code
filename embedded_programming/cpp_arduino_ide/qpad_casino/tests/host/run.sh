#!/bin/sh
# Runs the sketch on this computer (stubbed hardware): prints the benchmark's parity lines and
# saves every Nth frame of the scripted playthrough as PNG.   Usage: ./run.sh [out_dir] [every_n]
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
SKETCH="$HERE/../.."
GFX="$HOME/Documents/Arduino/libraries/Adafruit_GFX_Library"
OUT=${1:-/tmp/qpad_host}
mkdir -p "$OUT"
{
  echo '#include <Arduino.h>'
  sed 's/#define BENCHMARK 0/#define BENCHMARK 1/' "$SKETCH/qpad_casino.ino"
  for f in bench blackjack input menu poker roulette ui; do cat "$SKETCH/$f.ino"; done
  echo '#include "host_main.cpp"'
} > "$OUT/sketch.cpp"
c++ -std=c++17 -O2 -DARDUINO=10819 -I"$HERE/stubs" -I"$HERE" -I"$SKETCH" -I"$GFX" \
  "$OUT/sketch.cpp" "$GFX/Adafruit_GFX.cpp" -lz -o "$OUT/qpad_host" 2>&1 | grep -v "warning:" | grep -E "error" || true
"$OUT/qpad_host" "$OUT" "${2:-48}"
