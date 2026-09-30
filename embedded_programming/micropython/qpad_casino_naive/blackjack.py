# Blackjack: fresh deck every hand, dealer stands on 17, blackjack pays 3:2.
from touch import LEFT, RIGHT, OK, BACK, pressed
from cards import bj_total, bj_settle
from ui import (CHIPS, SLIDE_MS, Round, Slot, header, bar, bet_bar, banner, draw_hand,
                all_cards, up_cards)

BET, CHECK, PLAY = "bet", "check", "play"
OPTIONS = ["HIT", "STAND", "DOUBLE"]


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
        return OPTIONS if len(self.player) == 2 and self.casino.bank >= self.bet else OPTIONS[:2]

    def deal(self):
        casino = self.casino
        t = casino.now()
        self.bet = self.stake = CHIPS[self.round.bet_idx]
        casino.bank -= self.bet
        casino.deck.shuffle()
        self.player = [Slot(casino.deck.draw(), t, t)]
        self.dealer = [Slot(casino.deck.draw(), t + 250, t + 250)]
        self.player.append(Slot(casino.deck.draw(), t + 500, t + 500))
        self.dealer.append(Slot(casino.deck.draw(), t + 750, 0))      # hole card
        self.round.busy_until = t + 750 + SLIDE_MS
        self.phase = CHECK
        self.selected = 0

    def finish(self, t):
        """Reveals the hole card, lets the dealer draw to 17 and settles the hand."""
        self.dealer[1].show_at = t
        t += 450
        p = bj_total(all_cards(self.player))
        natural = p == 21 and len(self.player) == 2
        if p <= 21 and not natural:
            while bj_total(all_cards(self.dealer)) < 17:
                self.dealer.append(Slot(self.casino.deck.draw(), t, t))
                t += 550
        ret, msg = bj_settle(self.bet, p, len(self.player), bj_total(all_cards(self.dealer)), len(self.dealer))
        self.round.show_result(msg, ret, ret - self.stake, t)
        self.phase = BET

    def update(self, events):
        casino, r = self.casino, self.round
        t = casino.now()
        r.pay_when_shown(casino)
        if t < r.busy_until:
            return
        if self.phase == BET:
            if events:
                r.banner = False
            r.bet_input(casino, events, 1)
            if pressed(events, BACK):
                casino.open_menu()
                return
            if pressed(events, OK) and r.can_bet(casino, 1):
                self.deal()
            return
        if self.phase == CHECK:                    # naturals end the hand at once
            if bj_total(all_cards(self.player)) == 21 or bj_total(all_cards(self.dealer)) == 21:
                self.finish(t)
            else:
                self.phase = PLAY
            return
        if pressed(events, LEFT) and self.selected > 0:
            self.selected -= 1
        if pressed(events, RIGHT) and self.selected < len(self.options()) - 1:
            self.selected += 1
        if not pressed(events, OK):
            return
        choice = self.options()[self.selected]
        if choice == "STAND":
            self.finish(t)
            return
        if choice == "DOUBLE":
            casino.bank -= self.bet
            self.stake += self.bet
            self.bet *= 2
        self.player.append(Slot(casino.deck.draw(), t, t))
        r.busy_until = t + SLIDE_MS
        if choice == "DOUBLE" or bj_total(all_cards(self.player)) >= 21:
            self.finish(t + SLIDE_MS + 200)
        self.selected = min(self.selected, len(self.options()) - 1)

    def draw_total(self, g, hand, y):
        cards = up_cards(hand, self.casino.now())
        if cards:
            g.text_right(127, y, str(bj_total(cards)), 2)

    def draw(self, g):
        casino, r = self.casino, self.round
        now = casino.now()
        header(g, "BLACKJACK", casino.bank)
        if not self.player:
            g.text_center(20, "BLACKJACK PAYS 3 TO 2")
            g.text_center(32, "DEALER STANDS ON 17")
        draw_hand(g, self.dealer, 12, now)
        draw_hand(g, self.player, 34, now)
        self.draw_total(g, self.dealer, 13)
        self.draw_total(g, self.player, 35)
        if self.phase == PLAY:
            bar(g, self.options(), self.selected)
        elif self.phase == BET:
            bet_bar(g, "BET", CHIPS[r.bet_idx], "DEAL")
        if r.banner_visible(now):
            banner(g, 16, r.msg, r.net)
