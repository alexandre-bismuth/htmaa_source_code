#!/bin/sh
# Visible fullscreen check with the player's own settings (windowed fullscreen, their preset): a short automatic shot
# tour, then the game quits. Opens a real window: tell whoever is at the machine first. Run under the Unreal lock:
#   tools/unreal/ue_locked.sh <log> tools/unreal/fullscreen_test.sh <shots.json> <outdir>
# Screenshots + summary.json (GPU ms, viewport) land in <outdir>. On the 5K Studio Display fullscreen renders 2560x1440
# (bAllowHighDPIInGameMode is off); 2026-10-06 with High: 27-33 ms GPU.
R="$(cd "$(dirname "$0")/../.." && pwd)"; P=$R/CambridgeRacer
SHOTS=$1; OUT=$2
case "$SHOTS" in /*) ;; *) SHOTS="$PWD/$SHOTS" ;; esac
GUS=$P/Saved/Config/MacEditor/GameUserSettings.ini
GI=$P/Saved/Config/MacEditor/Game.ini
mkdir -p "$OUT"
[ -f "$GUS" ] && cp "$GUS" "$OUT/GameUserSettings.player.ini"   # restored afterwards (a test must not change them)
[ -f "$GI" ] && cp "$GI" "$OUT/Game.player.ini"                  # the player's best times
rm -rf $P/Saved/Screenshots/ShotTour
perl -e 'alarm shift; exec @ARGV' 1800 "${UE_ROOT:-$HOME/UE_5.8}/Engine/Binaries/Mac/UnrealEditor" "$P/CambridgeRacer.uproject" /Game/Cambridge/Maps/mit_core \
  -game -nosound -unattended -nosplash -stdout -ShotTour="$SHOTS" -ShotTourUI -ShotTourProfile \
  -TimeTrialAuto=none -TimeTrialAutoDelay=99999 2>&1 | grep -E "LogShotTour: Display: (shot|world ready|SHOTTOUR)|Fatal|Ensure|Error: |flip check|reset: back" | sed 's/^\[[^]]*\]\[[^]]*\]//'
pkill -f "CrashReportClient.*CambridgeRacer" 2>/dev/null
[ -f "$OUT/GameUserSettings.player.ini" ] && cp "$OUT/GameUserSettings.player.ini" "$GUS"
if [ -f "$OUT/Game.player.ini" ]; then cp "$OUT/Game.player.ini" "$GI"; else rm -f "$GI"; fi
cp -R $P/Saved/Screenshots/ShotTour/. "$OUT/"; cp ~/Library/Logs/CambridgeRacer/CambridgeRacer.log "$OUT/game.log" 2>/dev/null
true
