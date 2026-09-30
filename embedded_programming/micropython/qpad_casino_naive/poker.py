# Ultimate Texas Hold'em: Ante + equal Blind; bet 3x/4x pre-flop, 2x on the flop, 1x or fold on the river.
from touch import LEFT, RIGHT, OK, BACK, pressed
from cards import best_hand, hand_name, uth_settle
from ui import CHIPS, SLIDE_MS, Round, Slot, header, bar, bet_bar, banner, draw_slot, all_cards, up_cards

BET, PRE, FLOP, RIVER = "bet", "pre", "flop", "river"
OPTIONS = {PRE: ["CHECK", "BET 3x", "BET 4x"], FLOP: ["CHECK", "BET 2x"], RIVER: ["FOLD", "BET 1x"]}


class Holdem:
    def __init__(self, casino):
        self.casino = casino
        self.reset()

    def reset(self):
        self.round = Round()
        self.ante = 0
        self.play = 0
        self.stake = 0
        self.enter()

    def enter(self):
        self.phase = BET
        self.player = []
        self.dealer = []
        self.board = []
        self.selected = 0
        self.round.banner = False

    def deal(self):
        casino = self.casino
        t = casino.now()
        deck = casino.deck
        self.ante = CHIPS[self.round.bet_idx]
        self.play = 0
        self.stake = 2 * self.ante
        casino.bank -= self.stake
        deck.shuffle()
        self.player = [Slot(deck.draw(), t, t), Slot(deck.draw(), t + 300, t + 300)]
        self.dealer = [Slot(deck.draw(), t + 150, 0), Slot(deck.draw(), t + 450, 0)]
        self.board = [Slot(deck.draw(), t + 650 + i * 90, 0) for i in range(5)]
        self.round.busy_until = t + 650 + 4 * 90 + SLIDE_MS
        self.phase = PRE
        self.selected = 0

    def flip(self, first, last, t):
        """Turns board cards [first, last) face up one after another; returns when the last one lands."""
        for slot in self.board[first:last]:
            if slot.show_at == 0:
                slot.show_at = t
                t += 180
        return t

    def showdown(self, t, folded):
        t = self.flip(0, 5, t) + 250
        self.dealer[0].show_at = t
        self.dealer[1].show_at = t + 180
        t += 180 + 500
        board = all_cards(self.board)
        mine = best_hand(all_cards(self.player) + board)
        theirs = best_hand(all_cards(self.dealer) + board)
        ret, msg = uth_settle(self.ante, self.play, mine, theirs, folded)
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
            r.bet_input(casino, events, 6)
            if pressed(events, BACK):
                casino.open_menu()
                return
            if pressed(events, OK) and r.can_bet(casino, 6):
                self.deal()
            return
        options = OPTIONS[self.phase]
        if pressed(events, LEFT) and self.selected > 0:
            self.selected -= 1
        if pressed(events, RIGHT) and self.selected < len(options) - 1:
            self.selected += 1
        if not pressed(events, OK):
            return
        choice = options[self.selected]
        if choice.startswith("BET"):
            self.play = self.ante * int(choice[4])
            casino.bank -= self.play
            self.stake += self.play
            self.showdown(t, False)
        elif choice == "FOLD":
            self.showdown(t, True)
        elif self.phase == PRE:
            r.busy_until = self.flip(0, 3, t)
            self.phase = FLOP
            self.selected = 0
        else:
            r.busy_until = self.flip(3, 5, t)
            self.phase = RIVER
            self.selected = 0

    def live_hand_name(self, hole, now):
        """Best hand among the face-up hole cards plus the face-up board."""
        cards = up_cards(hole, now)
        if len(cards) < 2:
            return None
        return hand_name(best_hand(cards + up_cards(self.board, now)))

    def draw(self, g):
        casino, r = self.casino, self.round
        now = casino.now()
        header(g, "HOLD'EM", casino.bank)
        if not self.player:
            g.text_center(18, "DEALER NEEDS A PAIR")
            g.text_center(30, "BLIND PAYS STRAIGHT+")
        for i, slot in enumerate(self.board):
            draw_slot(g, 32 + i * 13, 9, slot, now)
        for i, slot in enumerate(self.player):
            draw_slot(g, i * 13, 28, slot, now)
        for i, slot in enumerate(self.dealer):
            draw_slot(g, 104 + i * 13, 28, slot, now)
        if self.player:
            g.text_center(29, f"A{self.ante} B{self.ante}")
            g.text_center(38, f"PLAY {self.play}" if self.play else "PLAY -")
            mine = self.live_hand_name(self.player, now)
            theirs = self.live_hand_name(self.dealer, now)
            if mine:
                g.text(0, 46, mine)
            if theirs:
                g.text_right(127, 46, theirs)
        if self.phase == BET:
            bet_bar(g, "ANTE", CHIPS[r.bet_idx], "DEAL")
        else:
            bar(g, OPTIONS[self.phase], self.selected)
        if r.banner_visible(now):
            banner(g, 14, r.msg, r.net)
