#!/bin/sh
# End a running -game autopilot session (it never exits after "stay"). Kept in a file so the caller's command line
# doesn't contain the editor name (which the lock's pgrep would match).
pkill -f "Binaries/Mac/UnrealEdit""or .*TimeTrialAuto"
