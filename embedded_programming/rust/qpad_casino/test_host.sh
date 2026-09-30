#!/bin/sh
# Runs the game library's tests on this computer (rules, flows, touch logic, frame parity with C++).
cd "$(dirname "$0")" && cargo test --lib --target "$(rustc -vV | sed -n 's/host: //p')" "$@"
