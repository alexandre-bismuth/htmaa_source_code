#!/bin/sh
# Copies a QPAD Casino MicroPython build to the XIAO over USB-C, then resets it so main.py starts the game.
#   ./upload.sh optimized        (precompiles with qpad_casino/build.sh, copies build/*.mpy + main.py)
#   ./upload.sh naive            (copies qpad_casino_naive/*.py as source)
#   ./upload.sh <project> --no-reset
# Both projects use the same module names, so every project .py/.mpy in the board's root is removed
# first; otherwise a stale file from the other version could be imported. lib/ssd1306.py is kept.
# The board must already run MicroPython v1.29.0 (./flash_firmware.sh), because the .mpy format must match.
set -e
cd "$(dirname "$0")"
case "$1" in
  optimized) SRC=qpad_casino ;;
  naive)     SRC=qpad_casino_naive ;;
  *) echo "usage: $0 optimized|naive [--no-reset]"; exit 2 ;;
esac
command -v mpremote >/dev/null || { echo "mpremote missing: uv tool install mpremote"; exit 1; }
PORT=$(mpremote connect list | awk '/MicroPython/ {print $1; exit}')
[ -n "$PORT" ] || { echo "No MicroPython board on USB (running Rust/C++?): run ./flash_firmware.sh first"; exit 1; }

MODULES=$(ls qpad_casino/*.py qpad_casino_naive/*.py | sed 's|.*/||; s/\.py$//' | sort -u | tr '\n' ' ')
CLEAN="import os
for m in '$MODULES'.split():
    for ext in ('.py', '.mpy'):
        try:
            os.remove(m + ext)
        except OSError:
            pass
try:
    os.mkdir('lib')
except OSError:
    pass"

if [ "$SRC" = qpad_casino ]; then
  ./qpad_casino/build.sh
  FILES="qpad_casino/build/*.mpy qpad_casino/main.py"
else
  FILES="qpad_casino_naive/*.py"
fi

# shellcheck disable=SC2086
mpremote connect "$PORT" exec "$CLEAN" + cp lib/ssd1306.py :lib/ssd1306.py + cp $FILES : + ls :
[ "$2" = "--no-reset" ] || mpremote connect "$PORT" reset
