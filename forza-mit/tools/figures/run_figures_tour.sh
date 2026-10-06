#!/bin/sh
# docs/figures capture: ONE shot-tour launch with a fixed timestep (clips), deterministic audio (wav in sync
# with the frames, nothing played on the speakers) and, by default, no window (-RenderOffscreen).
# usage: tools/figures/run_figures_tour.sh <outdir> <shots.json> [extra engine args]
#   FIG_RES=2560x1440 (default)   FIG_WINDOW=1 to render in a window instead of offscreen
# Waits for / takes the shared Unreal lock. The race autopilot (-TimeTrialAuto) only drives events that a
# shot starts (cr.TT.Start); its best times are not kept (Game.ini restored afterwards).
OUT=$1; SHOTS=$2; shift 2
case "$SHOTS" in /*) ;; *) SHOTS="$PWD/$SHOTS" ;; esac
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
LOCK="${UNREAL_LOCK:-$REPO/CambridgeRacer/Saved/unreal.lock}"   # shared one-Unreal-at-a-time lock
PROJ_DIR=$REPO/CambridgeRacer
RES="${FIG_RES:-2560x1440}"
OFFSCREEN=-RenderOffscreen; [ "${FIG_WINDOW:-0}" = "1" ] && OFFSCREEN=
mkdir -p "$OUT"
until ! pgrep -f 'UnrealEdito[r]' >/dev/null && ! pgrep -f 'UnrealBuildToo[l]' >/dev/null && mkdir "$LOCK" 2>/dev/null; do sleep 15; done
caffeinate -u -t 3
CFG=$PROJ_DIR/Saved/Config/MacEditor
[ -f "$CFG/GameUserSettings.ini" ] && mv "$CFG/GameUserSettings.ini" "$CFG/GameUserSettings.ini.player"
[ -f "$CFG/Game.ini" ] && cp "$CFG/Game.ini" "$OUT/Game.ini.before"
rm -rf "$PROJ_DIR/Saved/Screenshots/ShotTour"
rm -f "$PROJ_DIR"/Saved/BouncedWavFiles/chase_*.wav
caffeinate -dimu perl -e 'alarm shift; exec @ARGV' 5400 "$HOME/UE_5.8/Engine/Binaries/Mac/UnrealEditor" "$PROJ_DIR/CambridgeRacer.uproject" /Game/Cambridge/Maps/mit_core \
  -game -windowed $OFFSCREEN -ResX="${RES%x*}" -ResY="${RES#*x}" -unattended -nosplash -stdout \
  -UseFixedTimeStep -FPS=60 -DeterministicAudio -ShotTourRecordAudio \
  -TimeTrialAuto=kendall_dash -TimeTrialAutoDelay=1000000 \
  -ShotTour="$SHOTS" "$@" > "$OUT/tour_stdout.log" 2>&1
echo "engine exit $?"
pkill -f "CrashReportClient.*CambridgeRacer" 2>/dev/null
# restore the player's settings and best times
[ -f "$CFG/GameUserSettings.ini.player" ] && mv -f "$CFG/GameUserSettings.ini.player" "$CFG/GameUserSettings.ini"
if [ -f "$OUT/Game.ini.before" ]; then cp -f "$OUT/Game.ini.before" "$CFG/Game.ini"; else rm -f "$CFG/Game.ini"; fi
cp -R "$PROJ_DIR/Saved/Screenshots/ShotTour/." "$OUT/" 2>/dev/null
cp "$PROJ_DIR"/Saved/BouncedWavFiles/chase_*.wav "$OUT/" 2>/dev/null
cp ~/Library/Logs/CambridgeRacer/CambridgeRacer.log "$OUT/game.log" 2>/dev/null
rmdir "$LOCK"
echo done
grep -h "LogShotTour" "$OUT/game.log" | sed 's/^\[[^]]*\]\[[^]]*\]//' | tail -40
grep -h "Failed to compile Material" "$OUT/game.log" | tail -3
