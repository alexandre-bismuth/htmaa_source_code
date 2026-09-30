# Task: write `embedded_programming/benchmarks/BENCHMARK.md`

You are a performance analyst. Build the report **only** from the files in `embedded_programming/benchmarks/results/`
and the hardware facts below. Do not read the source code. Do not invent numbers: every figure in the report must come
from a results file or from a calculation you show (e.g. cycles = µs × 125). Where data is missing, say so plainly.

## The four programs
The same game (QPAD Casino: roulette, blackjack, Ultimate Texas Hold'em on a 128×64 SSD1306 OLED, 6 capacitive pads)
written four times: `cpp` (Arduino C++), `micropython_naive` (straightforward MicroPython), `micropython` (optimized
MicroPython: viper/native, sprites, no per-frame allocation, PIO touch), `rust` (no_std, no allocator). A deterministic
benchmark (fixed seed, simulated 30 fps clock, scripted input) runs identically in all four.

## Data sources (read all of them)
- `results/<lang>.jsonl`: **device** results captured from the RP2040 (may be missing: then the device tables are "pending").
- `results/host/<lang>_host.jsonl`: **host proxy** runs on an Apple-silicon Mac. Clearly label them as such. They show
  relative interpreter/allocation behaviour, not RP2040 speed. `micropython_no_viper_host` ran the optimized MicroPython
  with its viper/native code stripped (the macOS unix port cannot emit ARM code), so its compute numbers understate the
  device and must not be read as the optimized port's speed. The host MicroPython runs use 64-bit objects (heap sizes ≈2×).
- `results/<lang>_build.json`: flash/RAM footprint of each build (exact, from the linkers / mpy-cross / the firmware UF2).
- `results/allocation_audit.json`: static audit of heap use per program.
- `results/verification.json` and `reference.json`: test results and the parity reference.

## How to read specific rows
- `touch/<pad>`: one single reading (`avg_ns` per reading; counts are the raw charge-time units of that program:
  loop turns for C++/Rust, µs for naive MicroPython (`time_pulse_us`), 16 ns PIO steps for optimized MicroPython).
  `touch/scan6` is a full scan: 6 pads × 8 samples + hysteresis (so ≈ 48 readings, not 6).
- `frame/*` and `draw_screen/*` come from the scripted playthrough with the real touch scan and display push.
  `leaks/soak` replays the script twice with update + draw only (no touch scan, no push), so its frame times are lower.
- `boot/timing` is ms since reset on the device; on the host it is wall-clock time and meaningless: skip it.
  `first_frame_ms` (splash shown) is expected to come before `ready_ms` (pads calibrated).
- Host runs use stubbed hardware: pad counts are 0 and the display push does nothing, so skip host touch/push rows.
  `memory/static` on the host counts the files in the folder the host run used; the `*_build.json` files are authoritative.
- `host_min_heap_game_bench` in the MicroPython build files: the smallest heap (64-bit unix port) in which the whole
  benchmark still completes. The device heap is reported by the device run (`memory/heap_boot`).
- C++ and Rust `stack_used_bytes` come only from device runs.

## Speed beyond frame rate (include for every program with device data)
- Playable fps = min(30.3, unlocked_fps): the game loop waits out a 33 ms frame (30.3 fps), so slower frames lower the frame rate.
- Real-time factor = 33 ms / average frame time (capped at 100%): in benchmark mode the game clock advances 33 ms
  per frame, so a slower program plays the same game in slow motion. Also give the wall time of the scripted game
  (frames × average frame time) against its 54.48 s of game time (1,651 × 33 ms), and `run_seconds` (whole
  benchmark) from the meta row when present.
- Input-to-display latency, and where the frame time goes (input / update / draw / push shares).

## Hardware facts (for the "against the chip" sections)
RP2040: dual Cortex-M0+ (one core used), run at 125 MHz here (133 MHz nominal, 200 MHz validated by SDK 2.x);
no FPU (float is software); single-cycle SIO GPIO; hardware 32-bit divider; 264 KB SRAM (4×64 KB striped + 2×4 KB);
2 MB external QSPI flash executed in place through a 16 KB XIP cache; 8 PIO state machines; I²C up to 1 MHz (Fm+).
SSD1306: 128×64, 1 KB GDDRAM, I²C at 400 kHz → a full frame needs ≥ 1024 × 9 bits / 400 kHz ≈ 23.0 ms.
Frame budget: 33 ms (the loop period; 30.3 fps). One cycle at 125 MHz = 8 ns.

## Required sections
1. **Summary**: one table, one row per program: flash footprint, static RAM / heap use, frame time (device if available,
   else "pending"), best7 evaluation time, bytes allocated per frame, leaks, parity status.
2. **Verification & parity**: what was tested and what matched (from verification.json / parity rows).
3. **Memory size vs the chip**: flash and RAM per program as bytes and % of 2 MB / 264 KB; for MicroPython include the
   firmware (resident in flash) plus program bytecode/native code, and the heap the program occupies.
4. **Latency & throughput**: per-stage frame times (input/update/draw/push), p50/p99, unlocked fps, input-to-display
   latency; compare the push time with the 23 ms I²C floor and the 33.3 ms budget. Device data first; host proxy separate.
5. **Compute kernels**: shuffle, bj_total, eval5, best7 and graphics primitives, in ns and in 125 MHz cycles.
6. **Memory leaks & allocation**: C++ vs Rust (malloc audit, heap delta over the soak, fragmentation, stack high-water)
   and MicroPython (allocation per frame, GC runs, leaked bytes). Explain what "leak-free" means for each model.
7. **Cost of naive MicroPython**: naive ÷ optimized for every metric available, and which optimizations explain which
   gains (viper/native, blit font, sprites, no per-frame allocation, PIO touch, .mpy precompilation).
8. **Caveats**: host vs device, different touch-sensing methods (C++/Rust RC loop, naive time_pulse_us, optimized PIO),
   what is still unmeasured.
9. **How to complete the device runs** (short; point to `benchmarks/README.md`).

Style: concise, tables first, plain language, no marketing tone.
