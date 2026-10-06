#!/bin/sh
# Run the headless drive test.
#   tools/unreal/drive_test.sh mit_core                 settle check on the city map
#   tools/unreal/drive_test.sh DriveTest accel [args]   accel | brake | skidpad on the test track
# Extra args are passed through, e.g. -DriveTestTC=sport -DriveTestSpeed=60 -DriveTestSeconds=60
HERE="$(cd "$(dirname "$0")" && pwd)"
PROJ_DIR="$HERE/../../CambridgeRacer"
MAP="${1:-DriveTest}"; MODE="${2:-accel}"; shift $(( $# < 2 ? $# : 2 ))   # never leak the map name into the engine args
# 5-minute hard timeout: a crash leaves the unattended crash reporter spinning forever
perl -e 'alarm shift; exec @ARGV' "${DRIVETEST_TIMEOUT:-300}" "${UE_ROOT:-$HOME/UE_5.8}/Engine/Binaries/Mac/UnrealEditor" "$PROJ_DIR/CambridgeRacer.uproject" "/Game/Cambridge/Maps/$MAP" \
  -game -nullrhi -nosound -unattended -nosplash -stdout -benchmark -fps=60 \
  -DriveTest -DriveTestMode="$MODE" "$@" 2>&1 | grep -E "DRIVETEST_RESULT|Fatal|Ensure|Error: " | sed 's/.*DRIVETEST_RESULT/DRIVETEST_RESULT/'
pkill -f "CrashReportClient.*CambridgeRacer" 2>/dev/null; true
