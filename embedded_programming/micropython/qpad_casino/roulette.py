# Roulette: European single-zero wheel, one bet per spin.
import micropython
import gfx
from gfx import BLACK, WHITE, Sprite
from touch import LEFT, RIGHT, OK, BACK
from cards import rng, WHEEL, N_BETS, BET_NAMES, is_red, bet_pays, bet_wins
from ui import CHIPS, NUMBERS, Round, ease_out, header, bet_bar, banner

SPIN_MS = 4200
NAMES = tuple(name.encode() for name in BET_NAMES)
PAYS = {1: b"PAYS 1 TO 1", 2: b"PAYS 2 TO 1", 35: b"PAYS 35 TO 1"}


def paint_pocket(n):
    """Red pockets are filled, black ones outlined, zero double-framed."""
    label = NUMBERS[n]
    tx = (13 - gfx.text_width(label)) // 2
    if is_red(n):
        gfx.fill_round_rect(0, 0, 13, 13, 2, WHITE)
        gfx.text(tx, 3, label, 1, BLACK)
    else:
        gfx.round_rect(0, 0, 13, 13, 2, WHITE)
        if n == 0:
            gfx.rect(2, 2, 9, 9, WHITE)
        gfx.text(tx, 3, label)


class Roulette:
    def __init__(self, casino):
        self.casino = casino
        self.pockets = [Sprite(13, 13, lambda: paint_pocket(n)) for n in range(37)]
        self.reset()

    def reset(self):
        self.round = Round()
        self.bet = 0               # 0..8 outside bets, 9.. straight numbers
        self.spin_from = 0         # wheel positions (pockets) of the current spin
        self.spin_to = 0
        self.spin_at = 0

    def enter(self):
        self.round.banner = False

    def update(self, events):
        casino, r = self.casino, self.round
        t = casino.clock
        r.pay_when_shown(casino)
        if t < r.busy_until:
            return
        self.spin_to %= 37
        self.spin_from = self.spin_to
        if events:
            r.banner = False
        if events >> LEFT & 1:
            self.bet = (self.bet - 1) % N_BETS
        if events >> RIGHT & 1:
            self.bet = (self.bet + 1) % N_BETS
        r.bet_input(casino, events, 1)
        if events >> BACK & 1:
            casino.open_menu()
            return
        if not events >> OK & 1 or not r.can_bet(casino, 1):
            return
        stake = CHIPS[r.bet_idx]
        n = rng.below(37)
        casino.bank -= stake
        self.spin_to = self.spin_from + 2 * 37 + (WHEEL.index(n) - self.spin_from) % 37   # two turns, then n
        self.spin_at = t
        payout = stake * (bet_pays(self.bet) + 1) if bet_wins(self.bet, n) else 0
        color = "GREEN" if n == 0 else "RED" if is_red(n) else "BLACK"
        r.show_result("%d %s" % (n, color), payout, payout - stake, t + SPIN_MS + 250)

    @micropython.native
    def draw(self):
        casino, r = self.casino, self.round
        e = ease_out(casino.clock - self.spin_at, SPIN_MS)
        pix = self.spin_from * 16 + ((self.spin_to - self.spin_from) * 16 * e >> 10)   # strip position in pixels
        header(b"ROULETTE", casino.bank)
        base, frac = pix // 16, pix % 16
        for k in range(-5, 6):
            self.pockets[WHEEL[(base + k) % 37]].draw(57 + k * 16 - frac, 12)
        gfx.rect(55, 10, 17, 17, WHITE)
        gfx.fill_triangle(60, 27, 66, 27, 63, 30, WHITE)
        gfx.text(0, 34, b"\x11")
        gfx.text(123, 34, b"\x10")
        gfx.text_center(32, NAMES[self.bet], 2)
        gfx.text_center(47, PAYS[bet_pays(self.bet)])
        bet_bar(b"BET", CHIPS[r.bet_idx], b"SPIN")
        if r.banner_visible(casino.clock):
            banner(28, r.msg, r.net)
