# Adafruit_GFX-identical drawing on the SSD1306 buffer: framebuf's C routines where their pixels match,
# viper where they don't, glyphs blitted at C speed, and sprites for anything drawn over and over.
import micropython
import framebuf
from array import array
from font import FONT

BLACK, WHITE = 0, 1
fb = None                     # the display (a FrameBuffer) and its 1 KB buffer, set by init()
_buf = bytearray(1024)
_pts = array("i", [0] * 16)   # scratch for up to 8 circle points
_glyphs = [None] * 128       # size-1 glyphs (5x8 FrameBuffers), built on first use
_glyphs2 = {}                 # size-2 glyphs, built on first use
_black = framebuf.FrameBuffer(bytearray(1), 2, 1, framebuf.MONO_HLSB)
_black.pixel(0, 0, 1)         # palette for black drawing: source 0 -> 1 (= transparent key), source 1 -> 0
_black.pixel(1, 0, 0)


def init(display):
    global fb, _buf
    fb = display
    _buf = display.buffer


def clear():
    fb.fill(0)


def fill_rect(x, y, w, h, c):
    fb.fill_rect(x, y, w, h, c)


def hline(x, y, w, c):
    fb.hline(x, y, w, c)


def vline(x, y, h, c):
    fb.vline(x, y, h, c)


def rect(x, y, w, h, c):
    fb.rect(x, y, w, h, c)


@micropython.viper
def pixel(x: int, y: int, c: int):
    if 0 <= x < 128 and 0 <= y < 64:
        b = ptr8(_buf)
        i = x + (y >> 3) * 128
        if c:
            b[i] = int(b[i]) | (1 << (y & 7))
        else:
            b[i] = int(b[i]) & (255 ^ (1 << (y & 7)))


@micropython.viper
def _plot(n: int, c: int):
    """Plots the first n points stored in _pts."""
    b = ptr8(_buf)
    p = ptr32(_pts)
    k = 0
    while k < n:
        x = int(p[2 * k])
        y = int(p[2 * k + 1])
        if 0 <= x < 128 and 0 <= y < 64:
            i = x + (y >> 3) * 128
            if c:
                b[i] = int(b[i]) | (1 << (y & 7))
            else:
                b[i] = int(b[i]) & (255 ^ (1 << (y & 7)))
        k += 1


@micropython.viper
def line(x0: int, y0: int, x1: int, y1: int, c: int):
    """Adafruit's drawLine (framebuf.line picks different pixels on some slopes)."""
    b = ptr8(_buf)
    if x0 == x1 or y0 == y1:
        if x0 > x1:
            x0, x1 = x1, x0
        if y0 > y1:
            y0, y1 = y1, y0
        if x0 == x1:
            fb.vline(x0, y0, y1 - y0 + 1, c)
        else:
            fb.hline(x0, y0, x1 - x0 + 1, c)
        return
    steep = 0
    ady = y1 - y0 if y1 > y0 else y0 - y1
    adx = x1 - x0 if x1 > x0 else x0 - x1
    if ady > adx:
        steep = 1
        x0, y0 = y0, x0
        x1, y1 = y1, x1
    if x0 > x1:
        x0, x1 = x1, x0
        y0, y1 = y1, y0
    dx = x1 - x0
    dy = y1 - y0 if y1 > y0 else y0 - y1
    err = dx >> 1
    ystep = 1 if y0 < y1 else -1
    while x0 <= x1:
        x = y0 if steep else x0
        y = x0 if steep else y0
        if 0 <= x < 128 and 0 <= y < 64:
            i = x + (y >> 3) * 128
            if c:
                b[i] = int(b[i]) | (1 << (y & 7))
            else:
                b[i] = int(b[i]) & (255 ^ (1 << (y & 7)))
        err -= dy
        if err < 0:
            y0 += ystep
            err += dx
        x0 += 1


@micropython.viper
def circle(x0: int, y0: int, r: int, c: int):
    p = ptr32(_pts)
    p[0] = x0
    p[1] = y0 + r
    p[2] = x0
    p[3] = y0 - r
    p[4] = x0 + r
    p[5] = y0
    p[6] = x0 - r
    p[7] = y0
    _plot(4, c)
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
        p[0] = x0 + x
        p[1] = y0 + y
        p[2] = x0 - x
        p[3] = y0 + y
        p[4] = x0 + x
        p[5] = y0 - y
        p[6] = x0 - x
        p[7] = y0 - y
        p[8] = x0 + y
        p[9] = y0 + x
        p[10] = x0 - y
        p[11] = y0 + x
        p[12] = x0 + y
        p[13] = y0 - x
        p[14] = x0 - y
        p[15] = y0 - x
        _plot(8, c)


@micropython.viper
def circle_helper(x0: int, y0: int, r: int, corner: int, c: int):
    p = ptr32(_pts)
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
        n = 0
        if corner & 4:
            p[0] = x0 + x
            p[1] = y0 + y
            p[2] = x0 + y
            p[3] = y0 + x
            n = 2
        if corner & 2:
            p[2 * n] = x0 + x
            p[2 * n + 1] = y0 - y
            p[2 * n + 2] = x0 + y
            p[2 * n + 3] = y0 - x
            n += 2
        if corner & 8:
            p[2 * n] = x0 - y
            p[2 * n + 1] = y0 + x
            p[2 * n + 2] = x0 - x
            p[2 * n + 3] = y0 + y
            n += 2
        if corner & 1:
            p[2 * n] = x0 - y
            p[2 * n + 1] = y0 - x
            p[2 * n + 2] = x0 - x
            p[2 * n + 3] = y0 - y
            n += 2
        _plot(n, c)


@micropython.viper
def fill_circle_helper(x0: int, y0: int, r: int, corners: int, delta: int, c: int):
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
                fb.vline(x0 + x, y0 - y, 2 * y + delta, c)
            if corners & 2:
                fb.vline(x0 - x, y0 - y, 2 * y + delta, c)
        if y != py:
            if corners & 1:
                fb.vline(x0 + py, y0 - px, 2 * px + delta, c)
            if corners & 2:
                fb.vline(x0 - py, y0 - px, 2 * px + delta, c)
            py = y
        px = x


def fill_circle(x0, y0, r, c):
    fb.vline(x0, y0 - r, 2 * r + 1, c)
    fill_circle_helper(x0, y0, r, 3, 0, c)


def round_rect(x, y, w, h, r, c):
    r = min(r, min(w, h) // 2)
    fb.hline(x + r, y, w - 2 * r, c)
    fb.hline(x + r, y + h - 1, w - 2 * r, c)
    fb.vline(x, y + r, h - 2 * r, c)
    fb.vline(x + w - 1, y + r, h - 2 * r, c)
    circle_helper(x + r, y + r, r, 1, c)
    circle_helper(x + w - r - 1, y + r, r, 2, c)
    circle_helper(x + w - r - 1, y + h - r - 1, r, 4, c)
    circle_helper(x + r, y + h - r - 1, r, 8, c)


def fill_round_rect(x, y, w, h, r, c):
    r = min(r, min(w, h) // 2)
    fb.fill_rect(x + r, y, w - 2 * r, h, c)
    fill_circle_helper(x + w - r - 1, y + r, r, 1, h - 2 * r - 1, c)
    fill_circle_helper(x + r, y + r, r, 2, h - 2 * r - 1, c)


def _div(a, b):
    """C integer division (truncates toward zero), as Adafruit_GFX uses."""
    q = abs(a) // abs(b)
    return q if (a < 0) == (b < 0) else -q


def fill_triangle(x0, y0, x1, y1, x2, y2, c):
    if y0 > y1:
        x0, y0, x1, y1 = x1, y1, x0, y0
    if y1 > y2:
        x1, y1, x2, y2 = x2, y2, x1, y1
    if y0 > y1:
        x0, y0, x1, y1 = x1, y1, x0, y0
    if y0 == y2:
        a = min(x0, x1, x2)
        fb.hline(a, y0, max(x0, x1, x2) - a + 1, c)
        return
    last = y1 if y1 == y2 else y1 - 1
    y = y0
    while y <= last:
        a = x0 + _div((x1 - x0) * (y - y0), y1 - y0)
        b = x0 + _div((x2 - x0) * (y - y0), y2 - y0)
        fb.hline(min(a, b), y, abs(b - a) + 1, c)
        y += 1
    while y <= y2:
        a = x1 + _div((x2 - x1) * (y - y1), y2 - y1)
        b = x0 + _div((x2 - x0) * (y - y0), y2 - y0)
        fb.hline(min(a, b), y, abs(b - a) + 1, c)
        y += 1


# ---------- Text (transparent background); strings are bytes so iterating them allocates nothing ----------
def _glyph2(code):
    g = _glyphs2.get(code)
    if g is None:
        g = framebuf.FrameBuffer(bytearray(20), 10, 16, framebuf.MONO_VLSB)
        for i in range(5):
            column = FONT[code * 5 + i]
            for j in range(8):
                if column >> j & 1:
                    g.fill_rect(i * 2, j * 2, 2, 2, 1)
        _glyphs2[code] = g
    return g


def _glyph1(code):
    g = framebuf.FrameBuffer(bytearray(FONT[code * 5:code * 5 + 5]), 5, 8, framebuf.MONO_VLSB)
    _glyphs[code] = g
    return g


@micropython.native
def char(x, y, code, color, size=1):
    if size == 1:
        g = _glyphs[code]
        if g is None:
            g = _glyph1(code)
    else:
        g = _glyph2(code)
    if color:
        fb.blit(g, x, y, 0)
    else:
        fb.blit(g, x, y, 1, _black)


@micropython.native
def text(x, y, s, size=1, color=WHITE):
    step = 6 * size
    for code in s:
        char(x, y, code, color, size)
        x += step


def text_width(s, size=1):
    return len(s) * 6 * size - size


def text_center(y, s, size=1, color=WHITE, cx=64):
    text(cx - text_width(s, size) // 2, y, s, size, color)


def text_right(x, y, s, size=1, color=WHITE):
    text(x - text_width(s, size) + 1, y, s, size, color)


# ---------- Sprites: something drawn often, captured once as two blits ----------
@micropython.viper
def _split(a: ptr8, b: ptr8, n: int):
    """a = drawn on black, b = drawn on white -> a becomes the white pixels, b the touched-pixel mask."""
    for i in range(n):
        touched = 255 ^ (int(a[i]) ^ int(b[i]))
        a[i] = int(a[i]) & touched
        b[i] = touched


class Sprite:
    def __init__(self, w, h, paint):
        """paint() draws the thing with its bounding box at (0, 0)."""
        size = w * ((h + 7) // 8)
        white, mask = bytearray(size), bytearray(size)
        self.white = framebuf.FrameBuffer(white, w, h, framebuf.MONO_VLSB)
        self.mask = framebuf.FrameBuffer(mask, w, h, framebuf.MONO_VLSB)
        fb.fill(0)
        paint()
        self.white.blit(fb, 0, 0)
        fb.fill(1)
        paint()
        self.mask.blit(fb, 0, 0)
        _split(white, mask, size)
        fb.fill(0)

    @micropython.native
    def draw(self, x, y):
        fb.blit(self.mask, x, y, 1, _black)    # clear every pixel the original drawing touched
        fb.blit(self.white, x, y, 0)           # then set its white pixels
