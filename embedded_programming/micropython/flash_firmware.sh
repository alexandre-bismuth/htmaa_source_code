#!/bin/sh
# Flashes MicroPython v1.29.0 (matches the local mpy-cross, .mpy v6.3) onto the XIAO RP2040 over USB-C.
# If the board already runs MicroPython it is rebooted into BOOTSEL automatically; otherwise
# (Rust/C++ firmware) hold BOOT, tap RESET, release BOOT first. Files on the board's filesystem are kept.
#   ./flash_firmware.sh
set -e
cd "$(dirname "$0")"
UF2=firmware/SEEED_XIAO_RP2040-20260824-v1.29.0.uf2
URL=https://micropython.org/resources/firmware/SEEED_XIAO_RP2040-20260824-v1.29.0.uf2
[ -f "$UF2" ] || { mkdir -p firmware && curl -fL -o "$UF2" "$URL"; }

if ! picotool info >/dev/null 2>&1; then
  PORT=$(mpremote connect list 2>/dev/null | awk '/MicroPython/ {print $1; exit}')
  if [ -n "$PORT" ]; then
    mpremote connect "$PORT" bootloader || true
    sleep 3
  fi
fi
picotool info >/dev/null 2>&1 || { echo "No XIAO in BOOTSEL: hold BOOT, tap RESET, release BOOT, then rerun."; exit 1; }
picotool load -v -x "$UF2"
