# Main menu: a carousel of the three games with animated icons.
import math
from gfx import BLACK, WHITE
from touch import UP, DOWN, LEFT, RIGHT, OK, pressed
from ui import ease_out

GAMES = ["ROULETTE", "BLACKJACK", "ULTIMATE HOLD'EM"]
SLIDE_MS = 220


class Menu:
    def __init__(self, casino):
        self.casino = casino
        self.reset()

    def reset(self):
        self.selected = 0
        self.previous = 0
        self.direction = 1
        self.slide_at = 0

    def update(self, events):
        step = 0
        if pressed(events, RIGHT) or pressed(events, DOWN):
            step = 1
        elif pressed(events, LEFT) or pressed(events, UP):
            step = -1
        if step:
            self.previous = self.selected
            self.selected = (self.selected + step) % 3
            self.direction = step
            self.slide_at = self.casino.now()
        if pressed(events, OK):
            self.casino.open_game(self.selected)

    def point(self, cx, cy, radius, degrees):
        a = math.radians(degrees)
        return cx + round(radius * math.cos(a)), cy + round(radius * math.sin(a))

    def draw_wheel(self, g, cx, cy):
        t = self.casino.now()
        turn = t / 5                                # degrees
        g.circle(cx, cy, 16, WHITE)
        g.circle(cx, cy, 11, WHITE)
        for k in range(18):
            x0, y0 = self.point(cx, cy, 11, turn + k * 20)
            x1, y1 = self.point(cx, cy, 16, turn + k * 20)
            g.line(x0, y0, x1, y1, WHITE)
        for k in range(4):
            x1, y1 = self.point(cx, cy, 11, turn + k * 90)
            g.line(cx, cy, x1, y1, WHITE)
        g.fill_circle(cx, cy, 3, WHITE)
        bx, by = self.point(cx, cy, 14, -t * 5 / 12)   # ball runs the other way
        g.fill_circle(bx, by, 1, WHITE)

    def draw_big_card(self, g, x, y, rank, suit):
        g.fill_round_rect(x - 1, y - 1, 24, 32, 3, BLACK)
        g.fill_round_rect(x, y, 22, 30, 3, WHITE)
        g.char(x + 3, y + 3, rank, BLACK, 2)
        g.char(x + 9, y + 14, suit, BLACK, 2)

    def draw_cards(self, g, cx, cy):
        lift = round(2 * math.sin(math.radians(self.casino.now() / 8)))
        self.draw_big_card(g, cx - 21, cy - 15, "A", "\x06")
        self.draw_big_card(g, cx - 1, cy - 13 + lift, "K", "\x03")

    def draw_chip(self, g, cx, cy):
        turn = self.casino.now() * 5 / 33
        g.fill_circle(cx, cy, 16, WHITE)
        g.fill_circle(cx, cy, 11, BLACK)
        g.circle(cx, cy, 9, WHITE)
        for k in range(6):
            x, y = self.point(cx, cy, 14, turn + k * 60)
            g.fill_circle(x, y, 2, BLACK)
        g.char(cx - 5, cy - 7, "\x06", WHITE, 2)

    def draw_item(self, g, i, dx):
        [self.draw_wheel, self.draw_cards, self.draw_chip][i](g, 64 + dx, 30)
        g.text_center(49, GAMES[i], 1, WHITE, 64 + dx)

    def draw(self, g):
        g.text(0, 0, "QPAD CASINO")
        g.text_right(127, 0, f"${self.casino.bank}")
        k = min(self.casino.now() - self.slide_at, SLIDE_MS)
        offset = round(self.direction * 128 * (1 - ease_out(k, SLIDE_MS)))
        self.draw_item(g, self.selected, offset)
        if k < SLIDE_MS:
            self.draw_item(g, self.previous, offset - self.direction * 128)
        g.fill_rect(0, 10, 9, 38, BLACK)
        g.fill_rect(119, 10, 9, 38, BLACK)
        g.text(1, 27, "\x11")
        g.text(122, 27, "\x10")
        for i in range(3):
            if i == self.selected:
                g.fill_circle(56 + i * 8, 60, 2, WHITE)
            else:
                g.circle(56 + i * 8, 60, 2, WHITE)
