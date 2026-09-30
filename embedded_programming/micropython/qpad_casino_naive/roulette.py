# Roulette: European single-zero wheel, one bet per spin.
from gfx import BLACK, WHITE
from touch import LEFT, RIGHT, OK, BACK, pressed
from cards import rng, WHEEL, N_BETS, is_red, bet_pays, bet_wins, bet_name
from ui import CHIPS, Round, ease_out, header, bet_bar, banner

SPIN_MS = 4200


class Roulette:
    def __init__(self, casino):
        self.casino = casino
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
        t = casino.now()
        r.pay_when_shown(casino)
        if t < r.busy_until:
            return
        self.spin_to %= 37
        self.spin_from = self.spin_to
        if events:
            r.banner = False
        if pressed(events, LEFT):
            self.bet = (self.bet - 1) % N_BETS
        if pressed(events, RIGHT):
            self.bet = (self.bet + 1) % N_BETS
        r.bet_input(casino, events, 1)
        if pressed(events, BACK):
            casino.open_menu()
            return
        if not pressed(events, OK) or not r.can_bet(casino, 1):
            return
        stake = CHIPS[r.bet_idx]
        n = rng.below(37)
        casino.bank -= stake
        self.spin_to = self.spin_from + 2 * 37 + (WHEEL.index(n) - self.spin_from) % 37   # two turns, then n
        self.spin_at = t
        payout = stake * (bet_pays(self.bet) + 1) if bet_wins(self.bet, n) else 0
        color = "GREEN" if n == 0 else "RED" if is_red(n) else "BLACK"
        r.show_result(f"{n} {color}", payout, payout - stake, t + SPIN_MS + 250)

    def draw_pocket(self, g, x, y, n):
        """Red pockets are filled, black ones outlined, zero double-framed."""
        label = str(n)
        tx = x + (13 - g.text_width(label)) // 2
        if is_red(n):
            g.fill_round_rect(x, y, 13, 13, 2, WHITE)
            g.text(tx, y + 3, label, 1, BLACK)
        else:
            g.round_rect(x, y, 13, 13, 2, WHITE)
            if n == 0:
                g.rect(x + 2, y + 2, 9, 9, WHITE)
            g.text(tx, y + 3, label)

    def draw(self, g):
        casino, r = self.casino, self.round
        e = ease_out(casino.now() - self.spin_at, SPIN_MS)
        pix = round(self.spin_from * 16 + (self.spin_to - self.spin_from) * 16 * e)   # strip position in pixels
        header(g, "ROULETTE", casino.bank)
        for k in range(-5, 6):
            self.draw_pocket(g, 57 + k * 16 - pix % 16, 12, WHEEL[(pix // 16 + k) % 37])
        g.rect(55, 10, 17, 17, WHITE)
        g.fill_triangle(60, 27, 66, 27, 63, 30, WHITE)
        g.text(0, 34, "\x11")
        g.text(123, 34, "\x10")
        g.text_center(32, bet_name(self.bet), 2)
        g.text_center(47, f"PAYS {bet_pays(self.bet)} TO 1")
        bet_bar(g, "BET", CHIPS[r.bet_idx], "SPIN")
        if r.banner_visible(casino.now()):
            banner(g, 28, r.msg, r.net)
