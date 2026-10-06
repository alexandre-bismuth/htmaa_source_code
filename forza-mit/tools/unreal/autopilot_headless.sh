#!/bin/sh
# TEST HARNESS ONLY (the autopilot is not a game feature). Headless (-nullrhi, no window) autopilot over time-trial events. Run inside the Unreal lock (ue_locked.sh).
# Usage: autopilot_headless.sh <first event id> <after-steps> <timeout s> [extra engine args]
#   e.g. autopilot_headless.sh harvard_sq_loop next,next,next,next,next,stay 5400
#        autopilot_headless.sh mit_loop_rev stay 900 -TimeTrialAutoViaMarker   (the player's path: into the start box, Enter)
R="$(cd "$(dirname "$0")/../.." && pwd)"
GI=$R/CambridgeRacer/Saved/Config/MacEditor/Game.ini
EXTRA=$(shift 3 2>/dev/null && echo "$@")
[ -f "$GI" ] && cp "$GI" "$GI.stageb_keep"          # keep the player's best times; restored afterwards
perl -e 'alarm shift; exec @ARGV' "${3:-5400}" "$HOME/UE_5.8/Engine/Binaries/Mac/UnrealEditor" "$R/CambridgeRacer/CambridgeRacer.uproject" /Game/Cambridge/Maps/mit_core \
  -game -nullrhi -RenderOffscreen -nosound -unattended -nosplash -stdout -benchmark -fps=60 \
  -TimeTrialAuto="$1" -TimeTrialAutoDelay=5 -TimeTrialAutoAfter="$2" $EXTRA 2>&1 \
  | grep -E --line-buffered "LogTimeTrial|Fatal|Ensure|Error: |autopilot"
pkill -f "CrashReportClient.*CambridgeRacer" 2>/dev/null
if [ -f "$GI.stageb_keep" ]; then mv -f "$GI.stageb_keep" "$GI"; else rm -f "$GI"; fi
true
