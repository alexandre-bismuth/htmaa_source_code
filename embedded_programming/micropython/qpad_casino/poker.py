# Ultimate Texas Hold'em: Ante + equal Blind; bet 3x/4x pre-flop, 2x on the flop, 1x or fold on the river.
import micropython
import gfx
from touch import LEFT, RIGHT, OK, BACK
from cards import best_hand, hand_name, uth_settle
from ui import CHIPS, SLIDE_MS, Round, Slot, header, bar, bet_bar, banner, draw_slot, all_cards, up_cards

BET, PRE, FLOP, RIVER = 0, 1, 2, 3
OPTIONS = ((), (b"CHECK", b"BET 3x", b"BET 4x"), (b"CHECK", b"BET 2x"), (b"FOLD", b"BET 1x"))
MULT = ((), (0, 3, 4), (0, 2), (0, 1))            # play bet per option (0 = check / fold)
NAMES = {}                                         # hand name -> bytes, filled on first use
_cards = bytearray(7)


def name_bytes(score):
    name = hand_name(score)
    b = NAMES.get(name)
    if b is None:
        b = NAMES[name] = name.encode()
    return b


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
        self.bets_text = b""
        self.play_text = b""
        self.round.banner = False

    def deal(self):
        casino = self.casino
        t = casino.clock
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
        self.bets_text = ("A%d B%d" % (self.ante, self.ante)).encode()
        self.play_text = b"PLAY -"

    def flip(self, first, last, t):
        """Turns board cards [first, last) face up one after another; returns when the last one lands."""
        for i in range(first, last):
            if self.board[i].show_at == 0:
                self.board[i].show_at = t
                t += 180
        return t

    def score(self, hole):
        all_cards(hole, _cards)
        all_cards(self.board, _cards, 2)
        return best_hand(_cards, 7)

    def showdown(self, t, folded):
        t = self.flip(0, 5, t) + 250
        self.dealer[0].show_at = t
        self.dealer[1].show_at = t + 180
        t += 180 + 500
        ret, msg = uth_settle(self.ante, self.play, self.score(self.player), self.score(self.dealer), folded)
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
            r.bet_input(casino, events, 6)
            if events >> BACK & 1:
                casino.open_menu()
                return
            if events >> OK & 1 and r.can_bet(casino, 6):
                self.deal()
            return
        n = len(OPTIONS[self.phase])
        if events >> LEFT & 1 and self.selected > 0:
            self.selected -= 1
        if events >> RIGHT & 1 and self.selected < n - 1:
            self.selected += 1
        if not events >> OK & 1:
            return
        mult = MULT[self.phase][self.selected]
        if mult:
            self.play = self.ante * mult
            self.play_text = ("PLAY %d" % self.play).encode()
            casino.bank -= self.play
            self.stake += self.play
            self.showdown(t, False)
        elif self.phase == RIVER:
            self.showdown(t, True)                 # fold
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
        n = up_cards(hole, now, _cards)
        if n < 2:
            return None
        n += up_cards(self.board, now, _cards, n)
        return name_bytes(best_hand(_cards, n))

    @micropython.native
    def draw(self):
        casino, r = self.casino, self.round
        now = casino.clock
        header(b"HOLD'EM", casino.bank)
        if not self.player:
            gfx.text_center(18, b"DEALER NEEDS A PAIR")
            gfx.text_center(30, b"BLIND PAYS STRAIGHT+")
        for i in range(len(self.board)):
            draw_slot(32 + i * 13, 9, self.board[i], now)
        for i in range(len(self.player)):
            draw_slot(i * 13, 28, self.player[i], now)
        for i in range(len(self.dealer)):
            draw_slot(104 + i * 13, 28, self.dealer[i], now)
        if self.player:
            gfx.text_center(29, self.bets_text)
            gfx.text_center(38, self.play_text)
            mine = self.live_hand_name(self.player, now)
            theirs = self.live_hand_name(self.dealer, now)
            if mine:
                gfx.text(0, 46, mine)
            if theirs:
                gfx.text_right(127, 46, theirs)
        if self.phase == BET:
            bet_bar(b"ANTE", CHIPS[r.bet_idx], b"DEAL")
        else:
            bar(OPTIONS[self.phase], len(OPTIONS[self.phase]), self.selected)
        if r.banner_visible(now):
            banner(14, r.msg, r.net)
