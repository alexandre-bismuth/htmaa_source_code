# Embedded programming: QPAD-XIAO

Firmware for the QPAD-XIAO board: a Seeed XIAO RP2040 with six capacitive touch pads and a 128×64 SSD1306 OLED.
The main project is **QPAD Casino** (Roulette, Blackjack and Ultimate Texas Hold'em), written four times so the
languages can be compared: C++, naive MicroPython, optimized MicroPython and Rust. All four play the same game
pixel for pixel.

## Folders

| Folder | What it is |
|---|---|
| `cpp_arduino_ide/qpad_test/` | Soldering test: shows every pad's reading on the OLED |
| `cpp_arduino_ide/qpad_casino/` | Casino in C++ (Arduino IDE) |
| `micropython/qpad_casino_naive/` | Casino in MicroPython, written the straightforward way |
| `micropython/qpad_casino/` | Casino in MicroPython, optimized (viper, sprites, PIO touch, no per-frame allocation) |
| `rust/qpad_casino/` | Casino in Rust (`no_std`, no heap) |
| `benchmarks/` | Benchmark capture tools, results and the report (`BENCHMARK.md`) |

## The board

| Part | Connection |
|---|---|
| OLED (SSD1306, I²C address 0x3C) | SDA = D4 (GPIO 6), SCL = D5 (GPIO 7) |
| Touch pads | Q5 = D0 (UP), Q2 = D8 (DOWN), Q3 = D1 (LEFT), Q4 = D7 (RIGHT), Q1 = D9 (OK), Q0 = D10 (BACK) |
| RGB LED (active low) | red GPIO 17, green GPIO 16, blue GPIO 25 |

Keep your hands off the pads while the board starts: they calibrate at boot.

## C++ (`cpp_arduino_ide/`)
1. Arduino IDE with the "Raspberry Pi Pico/RP2040" core (Earle Philhower) and the **Adafruit SSD1306** library.
2. Open `qpad_casino/qpad_casino.ino`. Choose Tools → Board **Seeed XIAO RP2040**, CPU Speed **125 MHz**,
   Optimize **-O2**.
3. Upload. When the board runs the C++ firmware, the IDE puts it into BOOTSEL by itself; coming from Rust, use
   BOOTSEL first.

Tests on the computer, from `cpp_arduino_ide/qpad_casino/tests/`: `clang++ -std=c++17 -O2 logic_test.cpp -o /tmp/t && /tmp/t`
(rules), and `host/run.sh` (runs the sketch against stubbed hardware and saves frames as PNG).

## MicroPython (`micropython/`)
```sh
cd micropython
./flash_firmware.sh         # once, and after any Rust/C++ flash: installs MicroPython v1.29.0
./upload.sh optimized       # or: ./upload.sh naive   then resets the board so main.py starts the game
```
- `upload.sh` first deletes both versions' modules from the board, because they share module names. It copies
  `lib/ssd1306.py` (the micropython-lib driver) to `:lib/`. For `optimized` it builds the ARMv6-M `.mpy` files with
  `qpad_casino/build.sh` and uploads those plus `main.py`.
- Keep the firmware at **v1.29.0**: the `.mpy` files (mpy v6.3) come from mpy-cross 1.29.0, and another minor version
  rejects their native/viper code.
- While MicroPython runs, `flash_firmware.sh` enters BOOTSEL by itself (`mpremote bootloader`).
- REPL: `mpremote` (Ctrl-C stops the game, Ctrl-D soft-resets).

Tests on the computer (`brew install micropython`):
```sh
cd micropython/tests
micropython -X heapsize=1M run_tests.py qpad_casino_naive
python3 prepare_host.py ../qpad_casino /tmp/qpad_opt && micropython -X heapsize=1M run_tests.py /tmp/qpad_opt
```
The macOS MicroPython can't run viper code, so `prepare_host.py` makes a plain-Python copy of the optimized version.

## Rust (`rust/qpad_casino/`)
```sh
cd rust/qpad_casino
./test_host.sh              # game-logic tests on the computer
# put the board in BOOTSEL
cargo run --release         # builds, flashes with picotool, starts the game
```
- Fallback: `picotool uf2 convert target/thumbv6m-none-eabi/release/qpad-casino -t elf qpad-casino.uf2 --family rp2040`,
  then drag `qpad-casino.uf2` onto `RPI-RP2`. The VS Code task *Export UF2* does the same.
- The Rust firmware can't enter BOOTSEL by itself, so flashing anything after it needs the BOOT button.

## Switching between programs
- To C++: upload from the Arduino IDE.
- To MicroPython: BOOTSEL if coming from Rust, then `./flash_firmware.sh`. The board's files survive a Rust or C++
  flash, so the last uploaded `main.py` runs again. Use `upload.sh` to pick the version.
- To Rust: BOOTSEL, then `cargo run --release`.

## Benchmarks
Each program has a `BENCHMARK` switch in its main file that turns the board into a deterministic benchmark. Capture a run
with `python3 benchmarks/capture.py --lang <cpp|micropython_naive|micropython|rust>`. See `benchmarks/README.md` for the
steps and `benchmarks/BENCHMARK.md` for the results.
