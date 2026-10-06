# Shared by the headless Unreal wrappers (sourced, POSIX sh). Not executable on its own.
UE_CMD="${UE_ROOT:-$HOME/UE_5.8}/Engine/Binaries/Mac/UnrealEditor-Cmd"
UPROJECT="$(cd "$(dirname "$0")/../../CambridgeRacer" && pwd)/CambridgeRacer.uproject"

# ue_py "<script.py> [args]" [extra grep -E pattern to show] [log file to append to]
# Runs a Python script in a headless editor, prints the interesting lines, and FAILS (status 1) unless
# the commandlet reports success: UnrealEditor-Cmd's own exit code can't be used (it is 1 whenever
# anything logs an error, and the old "| grep ... || true" pipelines swallowed real failures).
ue_py() {
  _log="${3:-$(mktemp -t ue_py)}"
  "$UE_CMD" "$UPROJECT" -run=pythonscript -script="$1" -nullrhi -unattended -nosplash -stdout >>"$_log" 2>&1
  grep -E "LogPython.*(Error|Warning)|Python script executed|Traceback${2:+|$2}" "$_log" | grep -v DeprecationWarning
  if ! grep -q "Python script executed successfully" "$_log"; then
    echo "FAILED: $1 (full log: $_log)" >&2
    return 1
  fi
}
