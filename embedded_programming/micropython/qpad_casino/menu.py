# Main menu: a carousel of the three games with animated icons (integer trig, no floats).
import micropython
import gfx
from gfx import BLACK, WHITE, Sprite
from touch import UP, DOWN, LEFT, RIGHT, OK
from ui import ease_out, bank_text

GAMES = (b"ROULETTE", b"BLACKJACK", b"ULTIMATE HOLD'EM")
SLIDE_MS = 220
# sin(k * 5 deg) * 1024
SIN72 = (0, 89, 178, 265, 350, 433, 512, 587, 658, 724, 784, 839, 887, 928, 962, 989, 1008, 1020,
         1024, 1020, 1008, 989, 962, 928, 887, 839, 784, 724, 658, 587, 512, 433, 350, 265, 178, 89,
         0, -89, -178, -265, -350, -433, -512, -587, -658, -724, -784, -839, -887, -928, -962, -989, -1008, -1020,
         -1024, -1020, -1008, -989, -962, -928, -887, -839, -784, -724, -658, -587, -512, -433, -350, -265, -178, -89)


def icos(r, a):                                    # a in 5 degree steps
    return (r * SIN72[(a + 18) % 72] + 512) >> 10


def isin(r, a):
    return (r * SIN72[a % 72] + 512) >> 10


def paint_big_card(x, y, rank, suit):
    gfx.fill_round_rect(x - 1, y - 1, 24, 32, 3, BLACK)
    gfx.fill_round_rect(x, y, 22, 30, 3, WHITE)
    gfx.char(x + 3, y + 3, rank, BLACK, 2)
    gfx.char(x + 9, y + 14, suit, BLACK, 2)


class Menu:
    def __init__(self, casino):
        self.casino = casino
        self.ace = Sprite(24, 32, lambda: paint_big_card(1, 1, 0x41, 6))
        self.king = Sprite(24, 32, lambda: paint_big_card(1, 1, 0x4B, 3))
        self.reset()

    def reset(self):
        self.selected = 0
        self.previous = 0
        self.direction = 1
        self.slide_at = 0

    def update(self, events):
        step = 1 if events & (1 << RIGHT | 1 << DOWN) else -1 if events & (1 << LEFT | 1 << UP) else 0
        if step:
            self.previous = self.selected
            self.selected = (self.selected + step) % 3
            self.direction = step
            self.slide_at = self.casino.clock
        if events >> OK & 1:
            self.casino.open_game(self.selected)

    @micropython.native
    def draw_wheel(self, cx, cy):
        t = self.casino.clock
        a0 = t // 25 % 72                          # wheel turns 5 deg every 25 ms
        gfx.circle(cx, cy, 16, WHITE)
        gfx.circle(cx, cy, 11, WHITE)
        for k in range(18):
            a = a0 + k * 4
            gfx.line(cx + icos(11, a), cy + isin(11, a), cx + icos(16, a), cy + isin(16, a), WHITE)
        for k in range(4):
            a = a0 + k * 18
            gfx.line(cx, cy, cx + icos(11, a), cy + isin(11, a), WHITE)
        gfx.fill_circle(cx, cy, 3, WHITE)
        b = 71 - t // 12 % 72                      # ball runs the other way
        gfx.fill_circle(cx + icos(14, b), cy + isin(14, b), 1, WHITE)

    def draw_cards(self, cx, cy):
        lift = isin(2, self.casino.clock // 40 % 72)
        self.ace.draw(cx - 22, cy - 16)
        self.king.draw(cx - 2, cy - 14 + lift)

    @micropython.native
    def draw_chip(self, cx, cy):
        a0 = self.casino.clock // 33 % 72
        gfx.fill_circle(cx, cy, 16, WHITE)
        gfx.fill_circle(cx, cy, 11, BLACK)
        gfx.circle(cx, cy, 9, WHITE)
        for k in range(6):
            a = a0 + k * 12
            gfx.fill_circle(cx + icos(14, a), cy + isin(14, a), 2, BLACK)
        gfx.char(cx - 5, cy - 7, 6, WHITE, 2)

    def draw_item(self, i, dx):
        if i == 0:
            self.draw_wheel(64 + dx, 30)
        elif i == 1:
            self.draw_cards(64 + dx, 30)
        else:
            self.draw_chip(64 + dx, 30)
        gfx.text_center(49, GAMES[i], 1, WHITE, 64 + dx)

    def draw(self):
        gfx.text(0, 0, b"QPAD CASINO")
        gfx.text_right(127, 0, bank_text(self.casino.bank))
        k = min(self.casino.clock - self.slide_at, SLIDE_MS)
        offset = self.direction * 128 * (1024 - ease_out(k, SLIDE_MS)) >> 10
        self.draw_item(self.selected, offset)
        if k < SLIDE_MS:
            self.draw_item(self.previous, offset - self.direction * 128)
        gfx.fill_rect(0, 10, 9, 38, BLACK)
        gfx.fill_rect(119, 10, 9, 38, BLACK)
        gfx.text(1, 27, b"\x11")
        gfx.text(122, 27, b"\x10")
        for i in range(3):
            if i == self.selected:
                gfx.fill_circle(56 + i * 8, 60, 2, WHITE)
            else:
                gfx.circle(56 + i * 8, 60, 2, WHITE)
