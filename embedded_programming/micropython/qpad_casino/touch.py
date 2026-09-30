# Capacitive pads -> button events. Six PIO state machines time all pads at once: each drives its pad low,
# releases it to the pull-up and counts down every 2 cycles (16 ns) until the pad reads high.
import micropython
import rp2
from machine import Pin, freq

UP, DOWN, LEFT, RIGHT, OK, BACK = 0, 1, 2, 3, 4, 5
PAD_GPIO = (26, 2, 27, 1, 4, 3)                    # D0 D8 D1 D7 D9 D10
PAD_NAMES = ("Q5", "Q2", "Q3", "Q4", "Q1", "Q0")
T_MAX = 30000                                      # timeout in counts (~480 us)
SAMPLES = 8
REPEAT_DELAY = 400                                 # hold-to-repeat on the 4 left pads (ms)
REPEAT_RATE = 110


@rp2.asm_pio(set_init=rp2.PIO.OUT_LOW)
def rc_timer():
    pull(block)                                    # wait for Python to send the timeout
    mov(x, osr)
    set(pindirs, 1)                                # drive the pad low...
    set(y, 31)
    label("discharge")
    jmp(y_dec, "discharge")[31]                    # ...for ~8 us
    set(pindirs, 0)                                # release: the pull-up charges the pad
    label("wait")
    jmp(pin, "done")
    jmp(x_dec, "wait")
    label("done")
    mov(isr, x)                                    # counts left; the charge time is T_MAX - x
    push(block)


class Touch:
    def __init__(self):
        self.sms = []
        for i, gpio in enumerate(PAD_GPIO):
            pin = Pin(gpio, Pin.IN, Pin.PULL_UP)
            sm = rp2.StateMachine(i, rc_timer, freq=freq(), set_base=pin, jmp_pin=pin)
            sm.active(1)
            self.sms.append(sm)
        self.values = [0] * 6
        self.baseline = [0] * 6
        self.threshold = [0] * 6
        self.stuck = [False] * 6
        self.down = [False] * 6
        self.was_down = [False] * 6
        self.down_at = [0] * 6
        self.repeat_at = [0] * 6

    def measure_once(self, pad):
        sm = self.sms[pad]
        sm.put(T_MAX)
        return T_MAX - sm.get()

    def measure(self, pad):
        total = 0
        for _ in range(SAMPLES):
            total += self.measure_once(pad)
        return total // SAMPLES

    @micropython.native
    def measure_all(self):
        """Average of SAMPLES rounds, all six pads charging at the same time."""
        sms, v = self.sms, self.values
        for pad in range(6):
            v[pad] = 0
        for _ in range(SAMPLES):
            for sm in sms:
                sm.put(T_MAX)
            for pad in range(6):
                v[pad] += T_MAX - sms[pad].get()
        for pad in range(6):
            v[pad] //= SAMPLES
        return v

    def calibrate(self, on_progress):
        import time
        time.sleep_ms(800)                         # let hands leave the board
        for pad in range(6):
            total = 0
            for _ in range(32):
                total += self.measure(pad)
            self.baseline[pad] = total // 32
            self.threshold[pad] = self.baseline[pad] + max(10, self.baseline[pad])
            self.stuck[pad] = self.baseline[pad] >= T_MAX - 1
            if self.stuck[pad]:
                print(PAD_NAMES[pad], "stuck at max: possible short to GND / solder bridge")
            on_progress(pad + 1, 6)

    @micropython.native
    def scan(self):
        """Hysteresis: press above threshold, release below the midpoint to baseline."""
        v = self.measure_all()
        for pad in range(6):
            limit = (self.baseline[pad] + self.threshold[pad]) // 2 if self.down[pad] else self.threshold[pad]
            self.down[pad] = not self.stuck[pad] and v[pad] > limit

    @micropython.native
    def read_buttons(self, now):
        """Bitmask of new presses, with auto-repeat on the navigation pads."""
        self.scan()
        events = 0
        for pad in range(6):
            if self.down[pad] and not self.was_down[pad]:
                events |= 1 << pad
                self.down_at[pad] = now
                self.repeat_at[pad] = now
            elif (self.down[pad] and pad <= 3 and now - self.down_at[pad] > REPEAT_DELAY
                  and now - self.repeat_at[pad] > REPEAT_RATE):
                events |= 1 << pad
                self.repeat_at[pad] = now
            self.was_down[pad] = self.down[pad]
        return events


def pressed(events, button):
    return events >> button & 1
