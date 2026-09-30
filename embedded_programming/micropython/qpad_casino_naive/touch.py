# Capacitive pads -> button events. Each pad is discharged, released with its pull-up,
# and machine.time_pulse_us measures how long it stays low (a finger makes it longer).
import time
from machine import Pin, time_pulse_us

UP, DOWN, LEFT, RIGHT, OK, BACK = 0, 1, 2, 3, 4, 5
PAD_GPIO = [26, 2, 27, 1, 4, 3]                    # D0 D8 D1 D7 D9 D10
PAD_NAMES = ["Q5", "Q2", "Q3", "Q4", "Q1", "Q0"]
TIMEOUT_US = 200
SAMPLES = 8
REPEAT_DELAY = 400                                 # hold-to-repeat on the 4 left pads (ms)
REPEAT_RATE = 110


class Touch:
    def __init__(self):
        self.pins = [Pin(gpio, Pin.OUT, value=0) for gpio in PAD_GPIO]
        self.baseline = [0] * 6
        self.threshold = [0] * 6
        self.stuck = [False] * 6
        self.down = [False] * 6
        self.was_down = [False] * 6
        self.down_at = [0] * 6
        self.repeat_at = [0] * 6

    def measure_once(self, pad):
        pin = self.pins[pad]
        pin.init(Pin.OUT, value=0)                 # empty the pad
        time.sleep_us(25)
        pin.init(Pin.IN, Pin.PULL_UP)              # charge through the pull-up
        t = time_pulse_us(pin, 0, TIMEOUT_US)
        pin.init(Pin.OUT, value=0)
        if t == -2:                                # already high: charged before we started timing
            return 0
        if t == -1:                                # never went high: short to ground
            return TIMEOUT_US
        return t

    def measure(self, pad):
        return sum(self.measure_once(pad) for _ in range(SAMPLES)) / SAMPLES

    def calibrate(self, on_progress):
        time.sleep_ms(800)                         # let hands leave the board
        for pad in range(6):
            self.baseline[pad] = sum(self.measure(pad) for _ in range(32)) / 32
            self.threshold[pad] = self.baseline[pad] + max(2, self.baseline[pad])
            self.stuck[pad] = self.baseline[pad] >= TIMEOUT_US - 1
            if self.stuck[pad]:
                print(f"{PAD_NAMES[pad]} stuck at max: possible short to GND / solder bridge")
            on_progress(pad + 1, 6)

    def scan(self):
        """Hysteresis: press above threshold, release below the midpoint to baseline."""
        for pad in range(6):
            value = self.measure(pad)
            release = (self.baseline[pad] + self.threshold[pad]) / 2
            limit = release if self.down[pad] else self.threshold[pad]
            self.down[pad] = not self.stuck[pad] and value > limit

    def read_buttons(self, now):
        """Bitmask of new presses, with auto-repeat on the navigation pads."""
        self.scan()
        events = 0
        for pad in range(6):
            if self.down[pad] and not self.was_down[pad]:
                events |= 1 << pad
                self.down_at[pad] = now
                self.repeat_at[pad] = now
            elif (self.down[pad] and pad <= RIGHT and now - self.down_at[pad] > REPEAT_DELAY
                  and now - self.repeat_at[pad] > REPEAT_RATE):
                events |= 1 << pad
                self.repeat_at[pad] = now
            self.was_down[pad] = self.down[pad]
        return events


def pressed(events, button):
    return events >> button & 1 == 1
