# Blackjack: fresh deck every hand, dealer stands on 17, blackjack pays 3:2.
import micropython
import gfx
from touch import LEFT, RIGHT, OK, BACK
from cards import bj_total, bj_settle
from ui import CHIPS, NUMBERS, SLIDE_MS, Round, Slot, header, bar, bet_bar, banner, draw_hand, all_cards, up_cards

BET, CHECK, PLAY = 0, 1, 2
OPTIONS = (b"HIT", b"STAND", b"DOUBLE")
_cards = bytearray(12)


class Blackjack:
    def __init__(self, casino):
        self.casino = casino
        self.reset()

    def reset(self):
        self.round = Round()
        self.bet = 0               # doubles on DOUBLE
        self.stake = 0             # total chips put in this hand
        self.enter()

    def enter(self):
        self.phase = BET
        self.player = []
        self.dealer = []
        self.selected = 0
        self.round.banner = False

    def options(self):
        return 3 if len(self.player) == 2 and self.casino.bank >= self.bet else 2

    def total(self, hand):
        return bj_total(_cards, all_cards(hand, _cards))

    def deal(self):
        casino = self.casino
        t = casino.clock
        deck = casino.deck
        self.bet = self.stake = CHIPS[self.round.bet_idx]
        casino.bank -= self.bet
        deck.shuffle()
        self.player = [Slot(deck.draw(), t, t)]
        self.dealer = [Slot(deck.draw(), t + 250, t + 250)]
        self.player.append(Slot(deck.draw(), t + 500, t + 500))
        self.dealer.append(Slot(deck.draw(), t + 750, 0))      # hole card
        self.round.busy_until = t + 750 + SLIDE_MS
        self.phase = CHECK
        self.selected = 0

    def finish(self, t):
        """Reveals the hole card, lets the dealer draw to 17 and settles the hand."""
        self.dealer[1].show_at = t
        t += 450
        p = self.total(self.player)
        natural = p == 21 and len(self.player) == 2
        if p <= 21 and not natural:
            while self.total(self.dealer) < 17:
                self.dealer.append(Slot(self.casino.deck.draw(), t, t))
                t += 550
        ret, msg = bj_settle(self.bet, p, len(self.player), self.total(self.dealer), len(self.dealer))
        self.round.show_result(msg, ret, ret - self.stake, t)
        self.phase = BET

    def update(self, events):
        casino, r = self.casino, self.round
        t = casino.clock
        r.pay_when_shown(casino)
        if t < r.busy_until:
            return
        if self.phase == BET:
            if events:
                r.banner = False
            r.bet_input(casino, events, 1)
            if events >> BACK & 1:
                casino.open_menu()
                return
            if events >> OK & 1 and r.can_bet(casino, 1):
                self.deal()
            return
        if self.phase == CHECK:                    # naturals end the hand at once
            if self.total(self.player) == 21 or self.total(self.dealer) == 21:
                self.finish(t)
            else:
                self.phase = PLAY
            return
        if events >> LEFT & 1 and self.selected > 0:
            self.selected -= 1
        if events >> RIGHT & 1 and self.selected < self.options() - 1:
            self.selected += 1
        if not events >> OK & 1:
            return
        if self.selected == 1:                     # STAND
            self.finish(t)
            return
        if self.selected == 2:                     # DOUBLE
            casino.bank -= self.bet
            self.stake += self.bet
            self.bet *= 2
        self.player.append(Slot(casino.deck.draw(), t, t))
        r.busy_until = t + SLIDE_MS
        if self.selected == 2 or self.total(self.player) >= 21:
            self.finish(t + SLIDE_MS + 200)
        self.selected = min(self.selected, self.options() - 1)

    def draw_total(self, hand, y):
        n = up_cards(hand, self.casino.clock, _cards)
        if n:
            gfx.text_right(127, y, NUMBERS[bj_total(_cards, n)], 2)

    @micropython.native
    def draw(self):
        casino, r = self.casino, self.round
        now = casino.clock
        header(b"BLACKJACK", casino.bank)
        if not self.player:
            gfx.text_center(20, b"BLACKJACK PAYS 3 TO 2")
            gfx.text_center(32, b"DEALER STANDS ON 17")
        draw_hand(self.dealer, 12, now)
        draw_hand(self.player, 34, now)
        self.draw_total(self.dealer, 13)
        self.draw_total(self.player, 35)
        if self.phase == PLAY:
            bar(OPTIONS, self.options(), self.selected)
        elif self.phase == BET:
            bet_bar(b"BET", CHIPS[r.bet_idx], b"DEAL")
        if r.banner_visible(now):
            banner(16, r.msg, r.net)
