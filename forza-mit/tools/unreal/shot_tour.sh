#!/bin/sh
# Rendered screenshot tour (real GPU). Usage: tools/unreal/shot_tour.sh [map] [shots.json] [extra args]
# Screenshots land in CambridgeRacer/Saved/Screenshots/ShotTour/. First run compiles shaders (slow).
# SHOTTOUR_RES=WxH sets the render size (default 1920x1080). Renders offscreen (-RenderOffscreen, no window,
# verified on Mac/Metal 2026-10-05) so tours don't disturb whoever is at the machine; SHOTTOUR_WINDOW=1 opens a
# real window instead (windowed size can't exceed the display).
# Perf gate (tools/unreal/perf/baseline_1080.json = 1280x720 offscreen x r.ScreenPercentage 150, mean of 2 runs,
# round 5; run-to-run noise is about +-1 ms per shot):
#   SHOTTOUR_RES=1280x720 tools/unreal/shot_tour.sh mit_core tools/unreal/shots_perf_1080.json -ShotTourProfile
# Harvard views (stage B): same setup, tools/unreal/shots_perf_harvard.json vs perf/baseline_harvard.json (2026-10-06).
# 5K study (fullscreen on the Studio Display is 2560x1440): SHOTTOUR_RES=2560x1440 ... tools/unreal/shots_5k.json
# (windowed offscreen sizes are clamped to the display's: 5120x2880 comes out 1920x1080). The real fullscreen check,
# with the player's settings and a visible window: tools/unreal/fullscreen_test.sh tools/unreal/shots_fullscreen.json <outdir>.
HERE="$(cd "$(dirname "$0")" && pwd)"
PROJ_DIR="$HERE/../../CambridgeRacer"
RES="${SHOTTOUR_RES:-1920x1080}"
MAP="${1:-mit_core}"; SHOTS="${2:-$HERE/shots_mit_core.json}"; shift $(( $# < 2 ? $# : 2 ))   # never leak the map name into the engine args
case "$SHOTS" in /*) ;; *) SHOTS="$PWD/$SHOTS" ;; esac            # the engine resolves relative paths elsewhere
OFFSCREEN=-RenderOffscreen; [ "${SHOTTOUR_WINDOW:-0}" = "1" ] && OFFSCREEN=
rm -rf "$PROJ_DIR/Saved/Screenshots/ShotTour"
GUS="$PROJ_DIR/Saved/Config/MacEditor/GameUserSettings.ini"   # measure with project defaults, not the player's
[ -f "$GUS" ] && mv "$GUS" "$GUS.player"                       # menu choices (restored afterwards)
perl -e 'alarm shift; exec @ARGV' "${SHOTTOUR_TIMEOUT:-5400}" "${UE_ROOT:-$HOME/UE_5.8}/Engine/Binaries/Mac/UnrealEditor" "$PROJ_DIR/CambridgeRacer.uproject" "/Game/Cambridge/Maps/$MAP" \
  -game -windowed $OFFSCREEN -ResX="${RES%x*}" -ResY="${RES#*x}" -nosound -unattended -nosplash -stdout -ShotTour="$SHOTS" "$@" 2>&1 \
  | grep -E "LogShotTour|Fatal|Ensure|Error: |LogShaderCompilers: (Error|Warning)|error:|\.hlsl" | sed 's/^\[[^]]*\]\[[^]]*\]//'
pkill -f "CrashReportClient.*CambridgeRacer" 2>/dev/null
[ -f "$GUS.player" ] && mv -f "$GUS.player" "$GUS"; true
