# Host stand-in for the micropython-lib SSD1306 driver: same MONO_VLSB buffer, show() calls hooks.
import framebuf

on_show = []


class SSD1306_I2C(framebuf.FrameBuffer):
    def __init__(self, width, height, i2c, addr=0x3C, external_vcc=False):
        self.buffer = bytearray(width * height // 8)
        super().__init__(self.buffer, width, height, framebuf.MONO_VLSB)

    def show(self):
        for hook in on_show:
            hook(self.buffer)
