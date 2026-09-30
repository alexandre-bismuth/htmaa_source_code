# QPAD Casino benchmarks

The same casino runs in four programs, each with a deterministic benchmark (fixed seed, simulated 30 fps clock,
scripted input). Results go to `results/`, and `BENCHMARK.md` is the report built from them.

| Program | Folder | Benchmark switch |
|---|---|---|
| C++ | `cpp_arduino_ide/qpad_casino` | `#define BENCHMARK 1` in `qpad_casino.ino` |
| MicroPython (naive) | `micropython/qpad_casino_naive` | `BENCHMARK = True` in `main.py` |
| MicroPython (optimized) | `micropython/qpad_casino` | `BENCHMARK = True` in `main.py` |
| Rust | `rust/qpad_casino` | `const BENCHMARK: bool = true;` in `src/main.rs` |

## Run one on the board
Plug in the XIAO, turn the switch on, flash, then from this folder run `python3 capture.py --lang <lang>`.
It waits for the board and saves `results/<lang>.jsonl`. Turn the switch off afterwards.
Flashing helpers for every program are described in `embedded_programming/README.md`; the steps below do the same by hand.

1. **C++** (`--lang cpp`): Arduino IDE, board "Seeed XIAO RP2040", Tools → CPU Speed **125 MHz**, Optimize **-O2**, Upload.
2. **MicroPython naive** (`--lang micropython_naive`): once, `micropython/flash_firmware.sh` (MicroPython v1.29.0,
   which the `.mpy` files need). Then set `BENCHMARK = True` in the naive `main.py` and run `micropython/upload.sh naive`.
3. **MicroPython optimized** (`--lang micropython`): set `BENCHMARK = True` in its `main.py`, then
   `micropython/upload.sh optimized` (builds the `.mpy` files, clears the other version's modules, uploads, resets).
4. **Rust** (`--lang rust`): hold BOOT, tap RESET, then `cargo run --release` in `rust/qpad_casino`.

A run takes about a minute (C++, Rust) to several minutes (naive MicroPython). Keep your hands off the pads while
the board boots: the pads calibrate then.

## Rebuild the report
Ask Claude to regenerate `BENCHMARK.md` with a fresh agent that follows `aggregate_prompt.md`.

## Other files
- `reference.json`: parity values from the C++ build (every port must reproduce bank, RNG, and for the exact ports
  the frame CRC).
- `compare_frames.py`: diff two frame dumps (`frames.bin`) and render the differing frames.
- `results/host/`: the same benchmark run on a Mac (proxy only), `results/*_build.json`: flash/RAM footprints,
  `results/allocation_audit.json`, `results/verification.json`.
