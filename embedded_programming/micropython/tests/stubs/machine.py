# Host stand-in for the RP2040 machine module (tests only).
class Pin:
    IN, OUT, PULL_UP = 0, 1, 1

    def __init__(self, gpio, mode=None, pull=None, value=None):
        self.gpio = gpio
        self._value = value or 0

    def init(self, mode=None, pull=None, value=None):
        pass

    def value(self, v=None):
        if v is None:
            return self._value
        self._value = v


class I2C:
    def __init__(self, *args, **kwargs):
        pass


def time_pulse_us(pin, level, timeout):
    return -2                      # pads charge instantly: never touched


def freq(hz=None):
    return 125_000_000
