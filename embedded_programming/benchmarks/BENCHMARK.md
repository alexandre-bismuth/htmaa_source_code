# QPAD Casino benchmark report

Built 2026-09-30 from `benchmarks/results/` only: the four device runs on the RP2040 (`cpp.jsonl`, `rust.jsonl`, `micropython.jsonl`, `micropython_naive.jsonl`, captured C++ 2026-09-29 22:50:29, Rust 2026-09-30 00:22:23, MP optimized 2026-09-29 23:37:30, MP naive 2026-09-30 00:20:31), the `*_build.json` footprints, `allocation_audit.json`, `verification.json`, `reference.json`, and the host proxy runs in `results/host/`. The `*_raw.log` serial logs were not used.

All device runs: RP2040 at 125 MHz (`cpu_hz` in every meta row), seed 12648430, 1,651 scripted frames. **Device data is the main content. Host-proxy numbers (Apple-silicon Mac) appear only under headings marked *Host proxy*.** They are not RP2040 speed.

Names: **C++** (`cpp`), **Rust** (`rust`), **MP optimized** (`micropython`), **MP naive** (`micropython_naive`). The host run of the optimized MicroPython had its viper/native code stripped and is called **MP opt (no viper)**.

Constants used below: frame period (budget) = `frame_ms` = 33 ms from the meta rows, so the fps cap is 1000 ÷ 33 = 30.3 fps; I²C floor for one SSD1306 frame = 1,024 × 9 bits / 400 kHz = 23.04 ms; 1 cycle at 125 MHz = 8 ns (cycles = ns ÷ 8); game time of the script = 1,651 × 33 ms = 54.48 s; flash % = bytes ÷ 2,097,152; SRAM % = bytes ÷ 270,336. (`aggregate_prompt.md` gives 33.33 ms and 55.0 s; that was an error in the prompt, and this report uses the 33 ms from the data.)

## 1. Summary

Device (RP2040) results. Real-time factor = min(100%, 33 ms ÷ average frame). Playable fps = min(30.3, unlocked fps).

| Program | Flash as run (% of 2 MB) | RAM in use at boot (% of 264 KB) | Frame avg / p99 | Playable fps (unlocked) | Real-time factor | best7 eval | Bytes allocated / frame | Leaks over 3,302-frame soak | Parity vs reference |
|---|---|---|---|---|---|---|---|---|---|
| C++ | 118,232 B (5.6%) | 20,936 B static + 1,728 B heap (8.4%) | 31.38 / 32.91 ms | 30.3 (31.86) | 100.0% | 211.6 µs | 0 (heap unchanged every frame) | 0 B; largest free block unchanged | defines the reference; all match |
| Rust | 91,676 B (4.4%) | 9,532 B static, no heap (3.5%) | 27.24 / 28.08 ms | 30.3 (36.70) | 100.0% | 183.0 µs | 0 (no allocator) | impossible (no heap); stack high-water 9,700 B | all match, incl. frame CRC |
| MP optimized | 384,688 B (18.3%) = 338,688 firmware + 46,000 program | 106,752 B of the 233,728 B GC heap (39.5%) | 39.39 / 47.61 ms | 25.4 (25.38) | 83.8% | 1,416.9 µs | 2 B | 0 B; 0 GC runs | all match, incl. frame CRC |
| MP naive | 397,839 B (19.0%) = 338,688 firmware + 59,151 program | 54,560 B of the 233,728 B GC heap (20.2%) | 381.12 / 766.87 ms | 2.6 (2.62) | 8.7% | 42,025.8 µs | 10,351 B | 0 B; 320 GC runs | bank, RNG, checksums match; frame CRC differs (float32 animation math) |

Takeaways:

- **Rust and C++ both run at the 30.3 fps cap with every frame inside the 33 ms budget.** Rust averages 27.24 ms per frame (max 28.14 ms), C++ 31.38 ms (max 32.92 ms, 0.08 ms under the budget). Rust needs 13.2% less time per frame, mostly from a shorter I²C push (25.16 vs 27.80 ms) and draw (0.82 vs 2.09 ms).
- **The display push dominates the compiled programs**: 88.6% of the C++ frame and 92.4% of the Rust frame. Every program's push sits above the 23.04 ms I²C floor (25.16–27.80 ms).
- **MP optimized misses the cap**: 39.39 ms per frame, 25.4 fps, 83.8% of real time. Its draw (11.95 ms) is 5.71× C++'s; the frame is 6.39 ms over budget.
- **MP naive runs at 2.6 fps** (381.1 ms per frame, 8.7% of real time): the 54.48 s scripted game takes 629 s. It is 9.67× slower per frame than MP optimized and allocates 10,351 B per frame (MP optimized: 2 B).
- **Memory is not a constraint for any program**: flash use is 4.4%–19.0% of 2 MB. No program leaks. MP optimized holds 1.96× MP naive's heap at boot; the audit lists preallocation (sprites, bytearrays, cached strings) among its techniques.
- **Parity**: all four reproduce the reference bank, RNG state and the four logic checksums on the device. C++, Rust and MP optimized also produce the reference frame CRC (bit-identical frames). MP naive's frame CRC differs from the reference, and its device CRC also differs from its own host CRC.

## 2. Verification and parity

From `verification.json`: the tests ran on the host before the device runs; the last column is the device result.

| Program | Tests | Build | Device run |
|---|---|---|---|
| C++ | 2127/2127 checks (tests/logic_test.cpp, incl. 500 vectors from the JS reference evaluator) | arduino-cli compile, 125 MHz, -O2, --warnings all: 0 warnings (game and benchmark builds) | complete; bank, RNG, all four checksums and the frame CRC over 1651 frames match reference.json |
| Rust | 13/13 cargo tests (rules vs the same 500 vectors, flows, touch logic, logic checksums, playthrough) | cargo build --release for thumbv6m-none-eabi: 0 warnings, 0 clippy warnings; touch loop placed in RAM (0x2003FAD0) | complete; bank, RNG, checksums and the frame CRC match reference.json |
| MP optimized | 2310/2310 checks at -X heapsize=1M (viper/native decorators stripped for the arm64 unix port, which has no native emitter) | all modules incl. viper code compile with mpy-cross -march=armv6m (44,348 bytes of .mpy) | complete; bank, RNG, checksums and the frame CRC match reference.json (bit-identical to C++ on the device) |
| MP naive | 2309/2309 checks on the MicroPython 1.29 unix port at -X heapsize=1M (tests/run_tests.py) | all modules compile with mpy-cross -march=armv6m | complete (a first capture was lost to a killed capture process during its soak; rerun in full); bank, RNG and checksums match; frame CRC differs by design (float animation math, float32 on the device) |

Device parity values vs `reference.json` (the reference comes from the C++ sketch run on the host):

| Value | Reference | C++ | Rust | MP optimized | MP naive |
|---|---|---|---|---|---|
| frames | 1,651 | match | match | match | match |
| bank | 790 | match | match | match | match |
| rng | 2,158,988,489 | match | match | match | match |
| shuffle_check | 52,393 | match | match | match | match |
| bj_total_check | 197,600 | match | match | match | match |
| eval5_check | 53,502,792 | match | match | match | match |
| best7_check | 1,224,999,960 | match | match | match | match |
| frame_crc32 | 908,070,050 | match | match | match | **810,939,409** (differs) |

- C++, Rust and MP optimized produce the same frame CRC on the device (908,070,050), so all 1,651 frames are bit-identical across the three.
- MP naive's frame CRC differs **three ways**: reference 908,070,050, host 491,742,382, device 810,939,409. Its animation math uses floats: float64 on the Mac, float32 on the RP2040 port, so each platform rounds differently and produces its own CRC (`verification.json`: "differs by design"). Game logic is unaffected (bank, RNG, checksums match). On the host, 1290/1651 frames were bit-identical to C++ and the rest differed by 1-pixel float rounding in animations; the device run records only the CRC, so the number of differing device frames is unmeasured.
- Not verified: Touch on real pads was only measured untouched (idle counts); no one pressed pads during the benchmark runs.

## 3. Memory size vs the chip

Flash (% = bytes ÷ 2,097,152). *As run* = the benchmark image the device reported (`memory/static`); *game* = the build without the benchmark code, from `*_build.json`. MicroPython totals add the firmware image resident in flash.

| Program | Flash as run, B | Flash, game build, B | Contents |
|---|---|---|---|
| C++ | 118,232 (5.64%) | 106,604 (5.08%) | boot2 + OTA + partition + .text + .rodata + .data; .text includes the Arduino core, TinyUSB, Adafruit libraries |
| Rust | 91,676 (4.37%) | 61,836 (2.95%) | vector table + boot2 + .text + .rodata + .data |
| MP optimized | 384,688 (18.34%) = 338,688 + 46,000 | 378,252 (18.04%) = 338,688 + 39,564 | precompiled `.mpy` with armv6m native/viper code + `main.py` source |
| MP naive | 397,839 (18.97%) = 338,688 + 59,151 | 384,860 (18.35%) = 338,688 + 46,172 | `.py` source, compiled to bytecode on the board at import |

The MicroPython firmware alone is 338,688 B (16.15%). The `ssd1306` driver's size is not in the results.

RAM (% = bytes ÷ 270,336). Device rows, except the game-build static RAM, which comes from `*_build.json`.

| Program | Static RAM, B | Heap total, B | Heap used at boot, B | Stack used, B |
|---|---|---|---|---|
| C++ | 20,936 (7.7%); game build 14,864* | 241,240 (89.2%) | 1,728 (0.64%), incl. the 1,024 B frame buffer | 1,600 of 2,048 (78%) |
| Rust | 9,532 (3.5%); game build 1,324 | 0 (no allocator) | 0 | 9,700 of 252,608 (3.8%) |
| MP optimized | 36,608 outside the GC heap (13.5%)† | 233,728 (86.5%) | 106,752 (39.5%; 45.7% of the heap) | 1,404‡ |
| MP naive | 36,608 outside the GC heap (13.5%)† | 233,728 (86.5%) | 54,560 (20.2%; 23.3% of the heap) | 1,404‡ |

\* C++ static RAM: the device counts .data 5,160 + .bss 15,552 + vector table 192 + uninitialized 32 = 20,936 B. `cpp_build.json` counts .data + .bss + two 2,048 B stack reserves = 24,808 B for the same benchmark build. Both are right; they include different sections.

† MicroPython: the results give only the GC heap (233,728 B). The 36,608 B outside it hold the firmware's static data and its C stack; the split is not in the results. `program_ram_bytes` (heap the program occupies) is 106,192 B optimized and 54,000 B naive, 560 B below `heap_boot.used_bytes` in both.

‡ `micropython.stack_use()` sampled at the same call depth in the soak, so the two ports report the same value. It is a point sample, not a high-water mark.

Takeaways:

- Flash: at most 19.0% of 2 MB (MP naive with its firmware). Rust's game build is the smallest image (61,836 B, 2.95%).
- C++'s core-0 stack reserve is the tightest figure in the report: 1,600 of 2,048 B used (78%, 448 B left). Rust's stack uses the RAM below .data (flip-link) and peaked at 9,700 B, 3.8% of its 252,608 B region.
- MicroPython's heap is the main RAM consumer: MP optimized occupies 106,752 B at boot, 1.96× MP naive's 54,560 B, leaving 126,976 B free vs 179,168 B. The results do not break the heap down by object.

## 4. Latency and throughput

### Device (RP2040)

**Where the frame goes** (scripted playthrough, n = 1,651 frames; ms = avg_ns ÷ 10⁶; share = stage ÷ total)

| Program | input (touch scan), ms | update, ms | draw, ms | push (I²C), ms | total, ms |
|---|---|---|---|---|---|
| C++ | 1.48 (4.7%) | 0.007 (0.02%) | 2.09 (6.7%) | 27.80 (88.6%) | 31.38 |
| Rust | 1.26 (4.6%) | 0.008 (0.03%) | 0.815 (3.0%) | 25.16 (92.4%) | 27.24 |
| MP optimized | 1.20 (3.0%) | 0.253 (0.64%) | 11.95 (30.3%) | 25.99 (66.0%) | 39.39 |
| MP naive | 18.63 (4.9%) | 0.423 (0.11%) | 336.09 (88.2%) | 25.98 (6.8%) | 381.12 |

**Speed beyond frame rate** (unlocked fps = 10⁹ ÷ avg frame ns; playable fps = min(30.3, unlocked); real-time factor = min(100%, 33 ms ÷ avg frame); scripted game wall time = 1,651 × avg frame, against 54.48 s of game time; `run_seconds` = whole benchmark, from the meta row)

| Program | Unlocked fps | Playable fps | Real-time factor | Scripted game, wall time | run_seconds |
|---|---|---|---|---|---|
| C++ | 31.86 | 30.3 | 100.0% | 51.8 s (0.95× game time) | 66.2 s |
| Rust | 36.70 | 30.3 | 100.0% | 45.0 s (0.83× game time) | 53.5 s |
| MP optimized | 25.38 | 25.4 | 83.8% | 65.0 s (1.19× game time) | 153.7 s (2.6 min) |
| MP naive | 2.62 | 2.6 | 8.7% | 629.2 s (11.55× game time) | 2,552.9 s (42.5 min) |

In benchmark mode the frames run back to back and the game clock advances one frame step per frame, so a program slower than 33 ms plays the same game in slow motion. C++ and Rust would be held to 54.48 s by the frame lock; MP optimized plays it 1.19× slower than real time and MP naive 11.55× slower.

**Frame-time distribution and input-to-display latency** (µs → ms; budget 33 ms; latency n = 43 input events)

| Program | min | p50 | avg | p99 | max | Frames over budget | Input→display avg (min–max), ms |
|---|---|---|---|---|---|---|---|
| C++ | 29.82 | 31.45 | 31.38 | 32.91 | 32.92 | none | 31.02 (29.82–32.23) |
| Rust | 26.60 | 27.13 | 27.24 | 28.08 | 28.14 | none | 27.12 (26.61–28.04) |
| MP optimized | 30.95 | 38.87 | 39.39 | 47.61 | 56.79 | more than half | 38.13 (31.63–56.79) |
| MP naive | 98.16 | 328.59 | 381.12 | 766.87 | 769.18 | all | 261.16 (98.16–497.24) |

- Input-to-display latency is about one frame: average latency ÷ average frame = 0.99 (C++), 1.00 (Rust), 0.97 (MP optimized), 0.69 (MP naive). MP naive's input frames are lighter than its average frame (261.2 vs 381.1 ms).
- C++'s slowest frame (32.92 ms) is 0.08 ms under the budget; Rust's (28.14 ms) is 4.86 ms under.

**Push against the I²C floor and the budget** (floor 23.04 ms; budget left = 33 − push; margin = budget − total frame)

| Program | Push in game, ms | Push isolated (n = 100), ms | ÷ I²C floor | % of budget | Budget left, ms | input + update + draw, ms | Margin, ms |
|---|---|---|---|---|---|---|---|
| C++ | 27.80 (max 27.84) | 27.77 (27.75–27.79) | 1.207× (+4.76 ms) | 84.2% | 5.20 | 3.58 | +1.62 |
| Rust | 25.16 (max 25.18) | 25.16 (25.16–25.17) | 1.092× (+2.12 ms) | 76.3% | 7.84 | 2.08 | +5.76 |
| MP optimized | 25.99 (max 45.59) | 25.81 (25.80–25.82) | 1.128× (+2.95 ms) | 78.8% | 7.01 | 13.40 | -6.39 |
| MP naive | 25.98 (max 34.23) | 25.80 (25.80–25.82) | 1.127× (+2.94 ms) | 78.7% | 7.02 | 355.14 | -348.12 |

- No push reaches the 23.04 ms floor; the overhead above it is 2.12 ms (Rust) to 4.76 ms (C++). Both MicroPython ports push in the same time (25.99 vs 25.98 ms).
- MP optimized's max in-game push (45.59 ms) is 19.60 ms above its average; MP naive's max is 34.23 ms. The isolated MicroPython pushes span at most 0.026 ms (min to max), so those outliers happen inside the game loop; the results do not say why.
- With the push blocking, 5.20 ms (C++) to 7.84 ms (Rust) is left for everything else. MP optimized needs 13.40 ms for input + update + draw, 6.39 ms too many.

**Draw time per screen**, avg ms (max) — frames per screen: menu 165, roulette 358, blackjack 511, holdem 617

| Program | menu | roulette | blackjack | holdem |
|---|---|---|---|---|
| C++ | 1.28 (1.59) | 2.29 (2.84) | 1.63 (2.18) | 2.58 (3.62) |
| Rust | 0.43 (0.78) | 0.67 (1.08) | 0.66 (1.01) | 1.13 (1.69) |
| MP optimized | 8.67 (12.00) | 11.56 (14.90) | 9.52 (12.20) | 15.06 (20.27) |
| MP naive | 202.96 (328.20) | 225.60 (468.33) | 316.76 (509.53) | 451.80 (724.17) |

Hold'em is the heaviest screen for every program. MP optimized's worst draw (20.27 ms) alone is 61% of the budget.

**Touch and boot** (per reading = mean of the six pads' avg_ns; scan6 = 6 pads × 8 samples + hysteresis ≈ 48 readings; scan6 ÷ 48 readings = scan6 ÷ (48 × per reading); calibration = ready − first frame)

| Program | Method | Per reading | Idle counts | scan6 | scan6 ÷ 48 readings | First frame | Ready | Calibration |
|---|---|---|---|---|---|---|---|---|
| C++ | RC loop | 31.2 µs | 7–10 loop turns | 1.46 ms (1.46–1.51) | 0.98 | 36 ms | 1,055 ms | 1,019 ms |
| Rust | RC loop (in RAM) | 27.0 µs | 11–16 loop turns | 1.25 ms (1.25–1.28) | 0.96 | 26 ms | 1,019 ms | 993 ms |
| MP optimized | PIO | 43.0 µs | 25–35 PIO steps of 16 ns | 1.17 ms (1.16–1.28) | 0.57 | 391 ms | 2,065 ms | 1,674 ms |
| MP naive | `time_pulse_us` | 352.2 µs | 0 µs (all pads) | 18.20 ms (18.06–26.05) | 1.08 | 1,424 ms | 3,813 ms | 2,389 ms |

- Counts are in each program's own unit, so compare time per reading and scan6, not counts. MP optimized's idle charge time is 400–560 ns (counts × 16 ns).
- MP naive reads **0 µs on every idle pad**. `time_pulse_us` has 1 µs resolution and starts only after slow `Pin.init` calls, so it cannot see an untouched pad's charge time (MP optimized measures it at 560 ns or less). Its touch detection therefore relies on a finger adding at least the threshold to a reading of 0. Its input stage is also the slowest by far (18.63 ms per frame, 56% of the budget).
- MP optimized's scan6 takes 0.57× the time of 48 single readings, while the other three are close to 1×. That is expected: its PIO state machines time all six pads at once (6 parallel charges × 8 samples), so a full scan costs less than six sequential pads. This makes it the fastest scan of the four (1.17 ms vs 1.25 ms Rust, 1.46 ms C++) even though one PIO reading is the slowest of the three non-naive methods.
- Boot: the compiled programs show the splash within 36 ms, MP optimized in 391 ms; MP naive, which compiles its `.py` files at import, takes 1,424 ms. Calibration takes 0.99–1.02 s in C++ and Rust and 1.7–2.4 s in MicroPython.

### Host proxy (Apple-silicon Mac, not RP2040)

The host stubs the pads and the display, so only update + draw compare. Ratio = device ÷ host.

| Program | Device update + draw | Host update + draw | Device ÷ host |
|---|---|---|---|
| C++ | 2.100 ms | 9.26 µs | 227× |
| Rust | 0.823 ms | 2.40 µs | 343× |
| MP optimized (host: no viper) | 12.202 ms | 119.30 µs | 102× |
| MP naive | 336.509 ms | 761.22 µs | 442× |

The device is 102×–442× slower than the Mac here, and the gap is not uniform across programs, so host ratios between programs do not predict device ratios. The MP optimized row is not like for like: its host run had no viper code.

## 5. Compute kernels

Device (RP2040), average per call. Cells: ns / cycles, with cycles = ns ÷ 8 (125 MHz). Ratio = program ÷ C++ (below 1 = faster than C++).

**Game logic**

| Kernel (n) | C++ | Rust | MP optimized | MP naive | Rust ÷ C++ | MP opt ÷ C++ | MP naive ÷ C++ |
|---|---|---|---|---|---|---|---|
| shuffle (2,000) | 21,449 / 2,681 | 18,886 / 2,361 | 285,899 / 35,737 | 13,830,123 / 1,728,765 | 0.88× | 13.3× | 645× |
| bj_total (10,000) | 1,291 / 161 | 1,883 / 235 | 37,751 / 4,719 | 98,214 / 12,277 | 1.46× | 29.2× | 76.1× |
| eval5 (10,000) | 7,554 / 944 | 6,147 / 768 | 101,905 / 12,738 | 1,015,827 / 126,978 | 0.81× | 13.5× | 134× |
| best7 (10,000) | 211,648 / 26,456 | 183,003 / 22,875 | 1,416,892 / 177,112 | 42,025,815 / 5,253,227 | 0.86× | 6.69× | 199× |

**Graphics primitives** (into the 1 KB frame buffer, no push)

| Kernel (n) | C++ | Rust | MP optimized | MP naive | Rust ÷ C++ | MP opt ÷ C++ | MP naive ÷ C++ |
|---|---|---|---|---|---|---|---|
| clear (300) | 4,763 / 595 | 4,790 / 599 | 910,176 / 113,772 | 913,976 / 114,247 | 1.01× | 191× | 192× |
| fill_screen (300) | 231,260 / 28,908 | 372,343 / 46,543 | 931,063 / 116,383 | 500,305,803 / 62,538,225 | 1.61× | 4.03× | 2,163× |
| line (300) | 130,396 / 16,300 | 29,806 / 3,726 | 250,960 / 31,370 | 8,508,136 / 1,063,517 | 0.23× | 1.92× | 65.2× |
| circle_r16 (300) | 91,913 / 11,489 | 30,226 / 3,778 | 332,333 / 41,542 | 7,205,910 / 900,739 | 0.33× | 3.62× | 78.4× |
| fill_circle_r16 (300) | 61,333 / 7,667 | 56,990 / 7,124 | 1,260,496 / 157,562 | 63,768,920 / 7,971,115 | 0.93× | 20.6× | 1,040× |
| fill_round_rect (300) | 70,573 / 8,822 | 70,570 / 8,821 | 570,943 / 71,368 | 73,003,803 / 9,125,475 | 1.00× | 8.09× | 1,034× |
| fill_triangle (300) | 402,683 / 50,335 | 240,263 / 30,033 | 10,879,040 / 1,359,880 | 232,216,053 / 29,027,007 | 0.60× | 27.0× | 577× |
| text_21_s1 (300) | 505,383 / 63,173 | 52,366 / 6,546 | 1,607,960 / 200,995 | 28,928,276 / 3,616,034 | 0.10× | 3.18× | 57.2× |
| text_10_s2 (300) | 584,473 / 73,059 | 275,393 / 34,424 | 1,976,033 / 247,004 | 57,057,880 / 7,132,235 | 0.47× | 3.38× | 97.6× |
| card (300) | 101,653 / 12,707 | 52,260 / 6,532 | 696,480 / 87,060 | 30,338,626 / 3,792,328 | 0.51× | 6.85× | 298× |
| card_back (300) | 80,406 / 10,051 | 47,246 / 5,906 | 662,126 / 82,766 | 22,369,336 / 2,796,167 | 0.59× | 8.23× | 278× |

Takeaways:

- **Rust vs C++**: Rust is faster on 11 of 15 kernels, within 1% on 2 (clear, fill_round_rect) and slower on 2. Its biggest wins are text (9.65× faster on text_21_s1), line (4.37×) and circle (3.04×). It is slower on bj_total (1.46×) and fill_screen (1.61×). best7 costs 26,456 cycles in C++ and 22,875 in Rust.
- **MP optimized** is 6.69×–29.2× C++ on the logic kernels (best7 6.69×, bj_total 29.2×). Its closest primitives are line (1.92×), text (3.18×–3.38×) and circle_r16 (3.62×); its worst are clear (191×) and fill_triangle (27.0×).
- **clear costs the same in both MicroPython ports** (910.2 vs 914.0 µs, about 111 cycles per byte of the 1,024 B buffer) against 0.58 cycles per byte in C++. MP optimized's fill_screen costs 14.2 cycles per pixel (8,192 pixels) vs 3.5 (C++) and 5.7 (Rust); MP naive's costs 7,634 cycles per pixel.
- **MP naive** is 57.2×–2,163× C++ per kernel. One best7 takes 42.0 ms, 127% of a frame budget; one fill_screen takes 500 ms.

### Host proxy (Apple-silicon Mac, not RP2040)

best7 only, as a contrast (host ns are not converted to cycles). Ratio = device ÷ host.

| Program | Device best7, ns | Host best7, ns | Device ÷ host |
|---|---|---|---|
| C++ | 211,648 | 1,644 | 129× |
| Rust | 183,003 | 1,415 | 129× |
| MP optimized (host: no viper) | 1,416,892 | 158,680 | 8.93× |
| MP naive | 42,025,815 | 144,212 | 291× |

On the host the no-viper port's best7 is 10% slower than MP naive's; on the device MP optimized (with viper) is 29.7× faster than MP naive. The host cannot show the viper gain.

## 6. Memory leaks and allocation

Soak = the script replayed twice (3,302 frames) with update + draw only (no touch scan, no push), on the device.

### C++ vs Rust

|  | C++ | Rust |
|---|---|---|
| Allocator | malloc (`<malloc.h>`) over the heap | none: no #[global_allocator], no `alloc` crate |
| Heap calls in game code (static audit) | none | none possible |
| Boot-time allocations | Adafruit_SSD1306 frame buffer (1,024 B, kept); core/TinyUSB/Serial buffers | none; fixed-capacity `heapless::String` / `heapless::Vec<Slot, 12>` |
| Heap used at boot | 1,728 B (arena 3,640 B) | 0 |
| Heap used before → after soak | 1,728 → 1,728 B | 0 → 0 |
| Leaked bytes / frames with a heap change / max delta | 0 / 0 / 0 | 0 / 0 / 0 |
| Largest free block before → after (free) | 239,512 → 239,512 B (239,512 free: 100% contiguous) | n/a |
| Soak frame (update + draw) | not recorded | avg 783.4 µs, max 1,640 µs |
| Stack used / reserved | 1,600 / 2,048 B (78%) | 9,700 / 252,608 B (3.8%) |
| `unsafe` blocks | n/a | 15 |

### MicroPython

| Metric (device) | MP naive | MP optimized | naive ÷ opt |
|---|---|---|---|
| Bytes allocated per frame | 10,351 | 2 | 5,176× |
| Bytes allocated over the soak (per frame × 3,302) | 34,179,002 | 6,604 | 5,176× |
| Frames with a heap change | 3,302 (100.0%) | 38 (1.2%) | 86.9× |
| Max heap delta, B | 78,944 | 752 | 105× |
| GC runs | 320 | 0 | – |
| Frames per GC run / bytes allocated per GC run | 10.3 / 106,809 | no GC run | – |
| Heap used before → after, B | 57,792 → 57,792 | 110,800 → 110,800 | – |
| Leaked bytes | 0 | 0 | – |
| Largest free block before → after, B | 28,960 → 19,168 | 34,064 → 34,752 | – |
| Largest block ÷ free bytes after | 10.9% of 175,120 | 28.5% of 122,144 | – |
| Soak frame p50, ms | 286.89 | 10.88 | 26.4× |
| Soak frame max, ms | 727.55 | 18.77 | 38.8× |

Takeaways:

- **C++**: the heap did not move during the soak (1,728 B before and after, 0 frames with a change), and the largest free block equals all free memory (239,512 B), so there is no fragmentation. Game code makes no heap calls; the only malloc/free in the sketch is the benchmark's own binary-search probe (`bench.ino:111–112`).
- **C++ stack is the risk to watch**: 1,600 of the 2,048 B reserve (448 B headroom). Rust peaked at 9,700 B in a 252,608 B region.
- **MP naive allocates 10,351 B per frame** and ran the GC 320 times in 3,302 frames (once every 10.3 frames). Its largest free block shrank from 28,960 to 19,168 B while 175,120 B were free, so its heap is fragmented. GC pause length is not recorded.
- **MP optimized allocates 2 B per frame on average**, changed the heap on 38 of 3,302 frames and never triggered the GC. Its largest free block did not shrink.

**What leak-free means for each model**

- **C++**: heap in use and the largest free block are unchanged after the soak (both true on the device), and the stack stays inside its reserve (true, with 448 B left).
- **Rust**: no allocator exists, so a heap leak cannot happen. What remains is stack depth (flip-link places the stack below .data, so an overflow faults instead of corrupting statics) and the 15 `unsafe` blocks.
- **MicroPython**: garbage-collected, so a leak means heap in use after collection is higher at the end of the soak than at the start. Both ports show 0 B. Allocation per frame is not a leak, but it costs GC work and fragmentation, which is where the two ports differ.

### Host proxy (Mac, 64-bit objects) vs device

| Host → device (ratio device ÷ host) | MP naive | MP optimized (host: no viper) |
|---|---|---|
| Heap used at boot, B | 74,624 → 54,560 (0.73×) | 131,712 → 106,752 (0.81×) |
| Bytes allocated per frame | 33,664 → 10,351 (0.31×) | 5 → 2 |
| GC runs over the soak | 6 → 320 | 0 → 0 |
| Heap size | 16,582,784 → 233,728 | same |

The device heap at boot is 0.73×–0.81× the host figure, not the ≈ 0.5× that halving 64-bit objects would suggest. The host soak ran on a 16,582,784 B heap, so its GC counts do not transfer. Host minimum heaps (64-bit): MP naive completes the whole benchmark in 160 KB (smallest tried), MP optimized needs 176 KB; the device heap is 233,728 B and both completed.

## 7. Cost of naive MicroPython

Ratio = MP naive ÷ MP optimized, device values (above 1 = naive is worse, except where marked).

| Metric | MP naive | MP optimized | naive ÷ opt |
|---|---|---|---|
| Program flash | 59,151 B | 46,000 B | 1.29× |
| Heap used at boot | 54,560 B | 106,752 B | 0.51× |
| Boot: first frame | 1,424 ms | 391 ms | 3.64× |
| Boot: ready | 3,813 ms | 2,065 ms | 1.85× |
| Touch, one reading | 352.2 µs | 43.0 µs | 8.20× |
| Touch, scan6 | 18.20 ms | 1.17 ms | 15.6× |
| Frame input | 18.63 ms | 1.20 ms | 15.5× |
| Frame update | 0.42 ms | 0.25 ms | 1.67× |
| Frame draw | 336.09 ms | 11.95 ms | 28.1× |
| Frame push | 25.98 ms | 25.99 ms | 1.00× |
| Frame total | 381.12 ms | 39.39 ms | 9.67× |
| Push isolated (n = 100) | 25.80 ms | 25.81 ms | 1.00× |
| Frame p50 | 328.59 ms | 38.87 ms | 8.45× |
| Frame p99 | 766.87 ms | 47.61 ms | 16.1× |
| Frame max | 769.18 ms | 56.79 ms | 13.5× |
| Unlocked fps | 2.62 | 25.38 | 0.10× (higher is better) |
| Real-time factor | 8.7% | 83.8% | 0.10× (higher is better) |
| Input→display latency | 261.16 ms | 38.13 ms | 6.85× |
| Scripted game wall time | 629.2 s | 65.0 s | 9.67× |
| run_seconds (whole benchmark) | 2,552.9 s | 153.7 s | 16.6× |
| Draw: menu screen | 202.96 ms | 8.67 ms | 23.4× |
| Draw: roulette screen | 225.60 ms | 11.56 ms | 19.5× |
| Draw: blackjack screen | 316.76 ms | 9.52 ms | 33.3× |
| Draw: holdem screen | 451.80 ms | 15.06 ms | 30.0× |
| Logic: shuffle | 13,830.1 µs | 285.9 µs | 48.4× |
| Logic: bj_total | 98.2 µs | 37.8 µs | 2.60× |
| Logic: eval5 | 1,015.8 µs | 101.9 µs | 9.97× |
| Logic: best7 | 42,025.8 µs | 1,416.9 µs | 29.7× |
| Gfx: clear | 914.0 µs | 910.2 µs | 1.00× |
| Gfx: fill_screen | 500,305.8 µs | 931.1 µs | 537× |
| Gfx: line | 8,508.1 µs | 251.0 µs | 33.9× |
| Gfx: circle_r16 | 7,205.9 µs | 332.3 µs | 21.7× |
| Gfx: fill_circle_r16 | 63,768.9 µs | 1,260.5 µs | 50.6× |
| Gfx: fill_round_rect | 73,003.8 µs | 570.9 µs | 128× |
| Gfx: fill_triangle | 232,216.1 µs | 10,879.0 µs | 21.3× |
| Gfx: text_21_s1 | 28,928.3 µs | 1,608.0 µs | 18.0× |
| Gfx: text_10_s2 | 57,057.9 µs | 1,976.0 µs | 28.9× |
| Gfx: card | 30,338.6 µs | 696.5 µs | 43.6× |
| Gfx: card_back | 22,369.3 µs | 662.1 µs | 33.8× |
| Bytes allocated per frame | 10,351 B | 2 B | 5,176× |
| Frames with a heap change | 3,302 | 38 | 86.9× |
| Max heap delta | 78,944 B | 752 B | 105× |
| GC runs (soak) | 320 | 0 | – |
| Soak frame p50 | 286.89 ms | 10.88 ms | 26.4× |
| Soak frame max | 727.55 ms | 18.77 ms | 38.8× |
| Stack used | 1,404 B | 1,404 B | 1.00× |
| Largest free block after soak | 19,168 B | 34,752 B | 0.55× (higher is better) |

**Which optimization explains which gain.** Techniques are from `allocation_audit.json`. The host column (MP naive ÷ MP opt (no viper), Mac) shows what remains when viper/native is removed: a gain that exists on the host comes from the Python-level change, one that appears only on the device comes from viper/native code.

| Optimization | Device naive ÷ opt | Host naive ÷ opt (no viper) | Reading |
|---|---|---|---|
| viper/native code (game logic) | shuffle 48.4×; bj_total 2.60×; eval5 9.97×; best7 29.7× | shuffle 1.07×; bj_total 0.69×; eval5 0.43×; best7 0.91× | host 0.43×–1.07×, device 2.60×–48.4×: the gain is viper/native. shuffle also drops naive's new Card object per card |
| viper writing the frame buffer directly (same Adafruit algorithms for lines, circles, triangles) | line 33.9×; circle_r16 21.7×; fill_triangle 21.3× | line 0.38×; circle_r16 0.34×; fill_triangle 12.8× | line and circle: host 0.38× or less, device 21.7×–33.9×, so viper alone. fill_triangle gains 12.8× on the host too, so part of its gain is not viper |
| framebuf C routines (`fill_rect`, `hline`, `vline`) instead of one `fb.pixel()` call per pixel | fill_screen 537×; fill_circle_r16 50.6×; fill_round_rect 128× | fill_screen 157×; fill_circle_r16 64.6×; fill_round_rect 58.5× | gain present on the host too; it comes from the C routines |
| blit font (bytes text, cached glyph FrameBuffers) | text_21_s1 18.0×; text_10_s2 28.9× | text_21_s1 14.8×; text_10_s2 10.9× | gain present on both |
| sprites (2 blits per card) | card 43.6×; card_back 33.8× | card 63.9×; card_back 54.6× | gain present on both |
| no per-frame allocation (cached strings, bytes text, preallocated bytearrays) | 10,351 → 2 B/frame; GC runs 320 → 0; soak p50 26.4×, max 38.8× | 33,664 → 5 B/frame; GC 6 → 0 | removes GC work and fragmentation; the soak ratios mix this with the drawing gains above |
| PIO touch | one reading 8.20×; scan6 15.6×; frame input 15.5× | not measurable (host pads are stubs) | input stage 18.63 → 1.20 ms |
| `.mpy` precompilation | program flash 1.29×; first frame 3.64× | host boot rows are wall-clock and meaningless | the boot gain also includes other start-up work, which the results do not separate |

- The frame gain (9.67×) is capped by the push, which both ports share (25.98 vs 25.99 ms). Without the push, input + update + draw goes from 355.1 to 13.40 ms (26.5×).
- Draw is where naive loses most time (336.1 ms of its 381.1 ms frame, 88%). The update step gains the least (1.67×).
- The optimized port pays in RAM: 1.96× the heap at boot (106,752 vs 54,560 B).

## 8. Caveats

- **Host vs device**: the host proxy is an Apple-silicon Mac with an FPU, large caches and a GHz clock; the RP2040 is a Cortex-M0+ at 125 MHz (one core used) with software float, flash executed in place through a 16 KB XIP cache, and a hardware divider. The host MicroPython runs use 64-bit objects, and the optimized port ran there without viper/native code. Host numbers are used above only for contrasts and for what the device cannot show.
- **Touch methods differ**: C++ and Rust time an RC charge in a loop (Rust's loop runs from RAM), MP naive uses `time_pulse_us`, MP optimized uses PIO state machines that time all six pads in parallel. Counts are in different units; only times compare. Pads were never touched during the runs.
- **MP naive touch is blind at idle**: every idle reading is 0 µs. `time_pulse_us` (1 µs resolution, started only after slow `Pin.init` calls) cannot see an untouched pad's charge time, so the naive port's touch margin rests entirely on a finger adding at least the detection threshold. Whether it does was not tested (no pads were pressed).
- **Soak vs game**: soak frames exclude the touch scan and the push, so they are much shorter than game frames.
- **run_seconds**: only C++ records how it was measured ("raw log file times (capture start to BENCH_END), about 1 s precision"), so its figure includes the wait from capture start. The other three meta rows give no method.
- **Still unmeasured**: touch on pressed pads, GC pause length, C++ soak frame times, the number of differing MP naive frames on the device (only the CRC), MicroPython firmware static RAM vs C stack split, the `ssd1306` driver size, and a MicroPython stack high-water mark (the reported figure is a point sample).

**Inconsistencies found in the results files**

1. Rust flash: the device reports 91,676 B, `rust_build.json` gives 91,836 B for the benchmark build (160 B more). The difference is not explained in the results.
2. C++ flash: device 118,232 B vs build 118,228 B (+4 B); heap total: device 241,240 B vs `.heap` 241,208 B (+32 B). Static RAM differs by accounting (Section 3).
3. MicroPython soak: `heap_used_before` + fragmentation `free_bytes` falls short of the heap total by 816 B (naive) and 784 B (optimized); the two were probably sampled at different moments.
4. Soak rows use different fields: C++ has no frame times, Rust has avg + max, MicroPython has p50 + max. Only C++'s meta row lacks `complete`; only it has `run_seconds_source`.
5. Host vs device heap: the prompt's "host heap ≈ 2×" overstates it (device ÷ host = 0.73× naive, 0.81× optimized), and MP naive allocates 3.25× more per frame on the host than on the device.

## 9. How to complete (or rerun) the device runs

All four device runs are complete. To rerun one: turn on the program's benchmark switch, flash it (C++ at 125 MHz and -O2; MicroPython v1.29.0 firmware, then `micropython/upload.sh naive|optimized`; Rust with `cargo run --release`), run `python3 capture.py --lang <lang>` from `benchmarks/` with hands off the pads during boot, and turn the switch off. Details: `benchmarks/README.md`. Rebuild this report with `python3 make_report.py` in `benchmarks/`.
