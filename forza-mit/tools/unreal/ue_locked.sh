#!/bin/sh
# Run one Unreal command under the shared lock (AGENT_RULES). Usage: ue_locked.sh <logfile> <command...>
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
L="${UNREAL_LOCK:-$REPO/CambridgeRacer/Saved/unreal.lock}"
LOG=$1; shift
until ! pgrep -f 'UnrealEdito[r]' >/dev/null && ! pgrep -f 'UnrealBuildToo[l]' >/dev/null && mkdir $L 2>/dev/null; do sleep 15; done
trap 'rmdir $L 2>/dev/null' EXIT INT TERM
cd "$REPO"
s=$(date +%s)
"$@" > "$LOG" 2>&1
rc=$?
echo "EXIT $rc after $(( $(date +%s) - s )) s: $*" | tee -a "$LOG"
exit $rc
