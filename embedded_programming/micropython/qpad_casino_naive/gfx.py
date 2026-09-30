# Adafruit_GFX drawing algorithms, translated line by line, drawing one pixel at a time.
from font import FONT

BLACK, WHITE, INVERSE = 0, 1, 2
WIDTH, HEIGHT = 128, 64


def div(a, b):
    """C-style integer division (truncates toward zero), as Adafruit_GFX does."""
    q = abs(a) // abs(b)
    return q if (a < 0) == (b < 0) else -q


class Gfx:
    def __init__(self, fb):
        self.fb = fb                     # the SSD1306 driver is a FrameBuffer

    def clear(self):
        self.fb.fill(0)

    def pixel(self, x, y, color):
        if 0 <= x < WIDTH and 0 <= y < HEIGHT:
            if color == INVERSE:
                color = 1 - self.fb.pixel(x, y)
            self.fb.pixel(x, y, color)

    def hline(self, x, y, w, color):
        for i in range(w):
            self.pixel(x + i, y, color)

    def vline(self, x, y, h, color):
        for i in range(h):
            self.pixel(x, y + i, color)

    def fill_rect(self, x, y, w, h, color):
        for i in range(x, x + w):
            self.vline(i, y, h, color)

    def rect(self, x, y, w, h, color):
        self.hline(x, y, w, color)
        self.hline(x, y + h - 1, w, color)
        self.vline(x, y, h, color)
        self.vline(x + w - 1, y, h, color)

    def line(self, x0, y0, x1, y1, color):
        if x0 == x1:
            self.vline(x0, min(y0, y1), abs(y1 - y0) + 1, color)
            return
        if y0 == y1:
            self.hline(min(x0, x1), y0, abs(x1 - x0) + 1, color)
            return
        steep = abs(y1 - y0) > abs(x1 - x0)
        if steep:
            x0, y0 = y0, x0
            x1, y1 = y1, x1
        if x0 > x1:
            x0, x1 = x1, x0
            y0, y1 = y1, y0
        dx = x1 - x0
        dy = abs(y1 - y0)
        err = dx // 2
        ystep = 1 if y0 < y1 else -1
        while x0 <= x1:
            if steep:
                self.pixel(y0, x0, color)
            else:
                self.pixel(x0, y0, color)
            err -= dy
            if err < 0:
                y0 += ystep
                err += dx
            x0 += 1

    def circle(self, x0, y0, r, color):
        f = 1 - r
        ddf_x = 1
        ddf_y = -2 * r
        x = 0
        y = r
        self.pixel(x0, y0 + r, color)
        self.pixel(x0, y0 - r, color)
        self.pixel(x0 + r, y0, color)
        self.pixel(x0 - r, y0, color)
        while x < y:
            if f >= 0:
                y -= 1
                ddf_y += 2
                f += ddf_y
            x += 1
            ddf_x += 2
            f += ddf_x
            for px, py in ((x0 + x, y0 + y), (x0 - x, y0 + y), (x0 + x, y0 - y), (x0 - x, y0 - y),
                           (x0 + y, y0 + x), (x0 - y, y0 + x), (x0 + y, y0 - x), (x0 - y, y0 - x)):
                self.pixel(px, py, color)

    def circle_helper(self, x0, y0, r, corner, color):
        f = 1 - r
        ddf_x = 1
        ddf_y = -2 * r
        x = 0
        y = r
        while x < y:
            if f >= 0:
                y -= 1
                ddf_y += 2
                f += ddf_y
            x += 1
            ddf_x += 2
            f += ddf_x
            if corner & 4:
                self.pixel(x0 + x, y0 + y, color)
                self.pixel(x0 + y, y0 + x, color)
            if corner & 2:
                self.pixel(x0 + x, y0 - y, color)
                self.pixel(x0 + y, y0 - x, color)
            if corner & 8:
                self.pixel(x0 - y, y0 + x, color)
                self.pixel(x0 - x, y0 + y, color)
            if corner & 1:
                self.pixel(x0 - y, y0 - x, color)
                self.pixel(x0 - x, y0 - y, color)

    def fill_circle_helper(self, x0, y0, r, corners, delta, color):
        f = 1 - r
        ddf_x = 1
        ddf_y = -2 * r
        x = 0
        y = r
        px = x
        py = y
        delta += 1
        while x < y:
            if f >= 0:
                y -= 1
                ddf_y += 2
                f += ddf_y
            x += 1
            ddf_x += 2
            f += ddf_x
            if x < y + 1:
                if corners & 1:
                    self.vline(x0 + x, y0 - y, 2 * y + delta, color)
                if corners & 2:
                    self.vline(x0 - x, y0 - y, 2 * y + delta, color)
            if y != py:
                if corners & 1:
                    self.vline(x0 + py, y0 - px, 2 * px + delta, color)
                if corners & 2:
                    self.vline(x0 - py, y0 - px, 2 * px + delta, color)
                py = y
            px = x

    def fill_circle(self, x0, y0, r, color):
        self.vline(x0, y0 - r, 2 * r + 1, color)
        self.fill_circle_helper(x0, y0, r, 3, 0, color)

    def round_rect(self, x, y, w, h, r, color):
        r = min(r, min(w, h) // 2)
        self.hline(x + r, y, w - 2 * r, color)
        self.hline(x + r, y + h - 1, w - 2 * r, color)
        self.vline(x, y + r, h - 2 * r, color)
        self.vline(x + w - 1, y + r, h - 2 * r, color)
        self.circle_helper(x + r, y + r, r, 1, color)
        self.circle_helper(x + w - r - 1, y + r, r, 2, color)
        self.circle_helper(x + w - r - 1, y + h - r - 1, r, 4, color)
        self.circle_helper(x + r, y + h - r - 1, r, 8, color)

    def fill_round_rect(self, x, y, w, h, r, color):
        r = min(r, min(w, h) // 2)
        self.fill_rect(x + r, y, w - 2 * r, h, color)
        self.fill_circle_helper(x + w - r - 1, y + r, r, 1, h - 2 * r - 1, color)
        self.fill_circle_helper(x + r, y + r, r, 2, h - 2 * r - 1, color)

    def fill_triangle(self, x0, y0, x1, y1, x2, y2, color):
        if y0 > y1:
            x0, y0, x1, y1 = x1, y1, x0, y0
        if y1 > y2:
            x1, y1, x2, y2 = x2, y2, x1, y1
        if y0 > y1:
            x0, y0, x1, y1 = x1, y1, x0, y0
        if y0 == y2:
            a = min(x0, x1, x2)
            b = max(x0, x1, x2)
            self.hline(a, y0, b - a + 1, color)
            return
        last = y1 if y1 == y2 else y1 - 1
        y = y0
        while y <= last:
            a = x0 + div((x1 - x0) * (y - y0), y1 - y0)
            b = x0 + div((x2 - x0) * (y - y0), y2 - y0)
            if a > b:
                a, b = b, a
            self.hline(a, y, b - a + 1, color)
            y += 1
        while y <= y2:
            a = x1 + div((x2 - x1) * (y - y1), y2 - y1)
            b = x0 + div((x2 - x0) * (y - y0), y2 - y0)
            if a > b:
                a, b = b, a
            self.hline(a, y, b - a + 1, color)
            y += 1

    # ---------- Text (transparent background) ----------
    def char(self, x, y, ch, color, size=1):
        if x >= WIDTH or y >= HEIGHT or x + 6 * size - 1 < 0 or y + 8 * size - 1 < 0:
            return
        code = ord(ch)
        for i in range(5):
            column = FONT[code * 5 + i]
            for j in range(8):
                if column >> j & 1:
                    if size == 1:
                        self.pixel(x + i, y + j, color)
                    else:
                        self.fill_rect(x + i * size, y + j * size, size, size, color)

    def text(self, x, y, s, size=1, color=WHITE):
        for ch in s:
            self.char(x, y, ch, color, size)
            x += 6 * size

    def text_width(self, s, size=1):
        return len(s) * 6 * size - size

    def text_center(self, y, s, size=1, color=WHITE, cx=64):
        self.text(cx - self.text_width(s, size) // 2, y, s, size, color)

    def text_right(self, x, y, s, size=1, color=WHITE):
        self.text(x - self.text_width(s, size) + 1, y, s, size, color)
