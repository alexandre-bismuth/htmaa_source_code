# QPAD Casino, optimized MicroPython version: Roulette, Blackjack and Ultimate Texas Hold'em.
# Needs the ssd1306 driver on the board (mpremote mip install ssd1306); copy the .mpy files made by build.sh.
BENCHMARK = False      # True = boot into the deterministic benchmark (results over USB serial)

import micropython
import os
import time
import machine
from machine import Pin, I2C
import ssd1306
from cards import rng
from ui import Led, LED_RED, LED_OFF, draw_splash
from touch import Touch
from casino import Casino, FRAME_MS

machine.freq(125_000_000)
try:
    display = ssd1306.SSD1306_I2C(128, 64, I2C(1, sda=Pin(6), scl=Pin(7), freq=400_000))
except OSError:
    print("OLED init failed: check the solder joints / I2C address 0x3C")
    led = Led()
    while True:
        led.flash(LED_RED, 0)
        time.sleep_ms(150)
        led.flash(LED_OFF, 0)
        time.sleep_ms(150)

import gfx
gfx.init(display)
draw_splash(0, 6)
display.show()
boot_frame_ms = time.ticks_ms()
touch = Touch()
casino = Casino(display, touch)                   # builds the sprites
rng.state = int.from_bytes(os.urandom(4), "little") | 1


def show_progress(done, total):
    draw_splash(done, total)
    display.show()


touch.calibrate(show_progress)

if BENCHMARK:
    import bench
    bench.run(casino, boot_frame_ms)


@micropython.native
def play():
    while True:
        start = time.ticks_ms()
        casino.clock = start
        casino.update(touch.read_buttons(start))
        casino.draw()
        display.show()
        used = time.ticks_diff(time.ticks_ms(), start)
        if used < FRAME_MS:
            time.sleep_ms(FRAME_MS - used)


play()
