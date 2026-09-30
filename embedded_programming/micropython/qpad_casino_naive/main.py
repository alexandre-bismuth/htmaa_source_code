# QPAD Casino, naive MicroPython version: Roulette, Blackjack and Ultimate Texas Hold'em.
# Needs the ssd1306 driver on the board: mpremote mip install ssd1306
BENCHMARK = False      # True = boot into the deterministic benchmark (results over USB serial)

import os
import time
import machine
from machine import Pin, I2C
import ssd1306
from cards import rng
from touch import Touch
from ui import Led, draw_splash
from casino import Casino, FRAME_MS

machine.freq(125_000_000)
try:
    display = ssd1306.SSD1306_I2C(128, 64, I2C(1, sda=Pin(6), scl=Pin(7), freq=400_000))
except OSError:
    print("OLED init failed: check the solder joints / I2C address 0x3C")
    red = Led()
    while True:
        red.flash("red", 0)
        time.sleep_ms(150)
        red.flash(None, 0)
        time.sleep_ms(150)

touch = Touch()
casino = Casino(display, touch)
rng.state = int.from_bytes(os.urandom(4), "little") | 1


def show_progress(done, total):
    draw_splash(casino.gfx, done, total)
    display.show()


show_progress(0, 6)
boot_frame_ms = time.ticks_ms()
touch.calibrate(show_progress)

if BENCHMARK:
    import bench
    bench.run(casino, boot_frame_ms)

while True:
    start = time.ticks_ms()
    casino.clock = start
    casino.update(touch.read_buttons(casino.clock))
    casino.draw()
    display.show()
    used = time.ticks_diff(time.ticks_ms(), start)
    if used < FRAME_MS:
        time.sleep_ms(FRAME_MS - used)
