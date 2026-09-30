# Widgets, cards, LED and the round/banner/bet logic shared by the games.
from machine import Pin
from gfx import BLACK, WHITE
from cards import RANKS
from touch import UP, DOWN

CW, CH = 11, 17                                    # card size in pixels
SLIDE_MS, FLIP_MS = 160, 90
CHIPS = [5, 10, 25, 50, 100, 250, 500, 1000]


def ease_out(k, total):
    """Cubic ease-out from 0.0 to 1.0."""
    if k >= total:
        return 1.0
    p = k / total
    return 1 - (1 - p) ** 3


def money(v):
    return f"+{v}" if v > 0 else f"{v}"


# ---------- Widgets ----------
def header(g, title, bank):
    g.text(0, 0, title)
    g.text_right(127, 0, f"${bank}")


def bar(g, items, selected):
    """Equal slots along the bottom; the selected one is inverted (= what OK does)."""
    n = len(items)
    for i, item in enumerate(items):
        x0 = i * 128 // n
        x1 = (i + 1) * 128 // n
        cx = (x0 + x1) // 2
        if i == selected:
            g.fill_round_rect(x0, 55, x1 - x0, 9, 2, WHITE)
            g.text_center(56, item, 1, BLACK, cx)
        else:
            g.text_center(56, item, 1, WHITE, cx)


def bet_bar(g, label, amount, action):
    g.text(0, 56, f"\x12 {label} {amount}")
    w = g.text_width(action) + 8
    g.fill_round_rect(128 - w, 55, w, 9, 2, WHITE)
    g.text_right(123, 56, action, 1, BLACK)


def banner(g, y, line1, net):
    g.fill_rect(10, y, 108, 32, BLACK)
    g.rect(10, y, 108, 32, WHITE)
    g.rect(12, y + 2, 104, 28, WHITE)
    g.text_center(y + 5, line1)
    g.text_center(y + 14, money(net), 2)


# ---------- Cards ----------
class Slot:
    """A card on the table: slides in at deal_at, face up from show_at (0 = face down)."""

    def __init__(self, card, deal_at, show_at):
        self.card = card
        self.deal_at = deal_at
        self.show_at = show_at

    def is_up(self, now):
        return self.show_at != 0 and now >= self.show_at


def draw_card(g, x, y, card):
    g.fill_round_rect(x - 1, y - 1, CW + 2, CH + 2, 2, BLACK)
    g.fill_round_rect(x, y, CW, CH, 2, WHITE)
    if card.rank == 8:                             # "10" squeezed into one card width
        g.char(x, y + 1, "1", BLACK)
        g.char(x + 5, y + 1, "0", BLACK)
    else:
        g.char(x + 3, y + 1, RANKS[card.rank], BLACK)
    g.char(x + 3, y + 9, chr(3 + card.suit), BLACK)


def draw_card_back(g, x, y):
    g.fill_round_rect(x - 1, y - 1, CW + 2, CH + 2, 2, BLACK)
    g.round_rect(x, y, CW, CH, 2, WHITE)
    for j in range(2, CH - 2):
        for i in range(2, CW - 2):
            if (i + j) % 4 == 0 or (i - j) % 4 == 0:
                g.pixel(x + i, y + j, WHITE)


def draw_slot(g, x, y, slot, now):
    """Slides in from the shoe (top right), flips edge-on when turned face up."""
    if now < slot.deal_at:
        return
    k = now - slot.deal_at
    if k < SLIDE_MS:
        e = ease_out(k, SLIDE_MS)
        x = round(120 + (x - 120) * e)
        y = round(-CH + (y + CH) * e)
    if slot.show_at > slot.deal_at and now >= slot.show_at and now - slot.show_at < FLIP_MS:
        g.fill_rect(x + 4, y, 3, CH, WHITE)
        return
    if slot.is_up(now):
        draw_card(g, x, y, slot.card)
    else:
        draw_card_back(g, x, y)


def draw_hand(g, hand, y, now, max_w=100):
    step = min(CW + 2, (max_w - CW) // (len(hand) - 1)) if len(hand) > 1 else 0
    for i, slot in enumerate(hand):
        draw_slot(g, i * step, y, slot, now)


def all_cards(hand):
    return [slot.card for slot in hand]


def up_cards(hand, now):
    return [slot.card for slot in hand if slot.is_up(now)]


# ---------- LED (active LOW) ----------
class Led:
    def __init__(self):
        self.pins = {"red": Pin(17, Pin.OUT, value=1), "green": Pin(16, Pin.OUT, value=1),
                     "blue": Pin(25, Pin.OUT, value=1)}
        self.color = None
        self.until = 0

    def flash(self, color, now):
        for name, pin in self.pins.items():
            pin.value(0 if name == color else 1)
        self.color = color
        self.until = now + 900

    def update(self, now):
        if self.color is not None and now > self.until:
            self.flash(None, now)


# ---------- Rounds: result banner, payout, bets ----------
class Round:
    def __init__(self):
        self.bet_idx = 1
        self.busy_until = 0
        self.result_at = 0
        self.banner = False
        self.payout = -1                           # -1 = nothing pending
        self.net = 0
        self.msg = ""

    def show_result(self, msg, payout, net, at):
        self.msg = msg
        self.payout = payout
        self.net = net
        self.result_at = at
        self.busy_until = at + 400
        self.banner = True

    def banner_visible(self, now):
        return self.banner and self.result_at <= now < self.result_at + 2500

    def pay_when_shown(self, casino):
        """Pays out when the banner appears, so the bank doesn't change before the reveal."""
        if self.payout < 0 or casino.now() < self.result_at:
            return
        casino.bank += self.payout
        self.payout = -1
        casino.led.flash("green" if self.net > 0 else "red" if self.net < 0 else "blue", casino.now())

    def bet_input(self, casino, events, mult):
        """mult = chips reserved per unit of bet (Hold'em needs ante + blind + 4x play)."""
        if events >> UP & 1 and self.bet_idx < len(CHIPS) - 1 and CHIPS[self.bet_idx + 1] * mult <= casino.bank:
            self.bet_idx += 1
        if events >> DOWN & 1 and self.bet_idx > 0:
            self.bet_idx -= 1
        while self.bet_idx > 0 and CHIPS[self.bet_idx] * mult > casino.bank:
            self.bet_idx -= 1

    def can_bet(self, casino, mult):
        if casino.bank >= CHIPS[0] * mult:
            return True
        casino.bank += 1000
        self.show_result("HOUSE LOAN", -1, 1000, casino.now())
        casino.led.flash("blue", casino.now())
        return False


def draw_splash(g, progress, total):
    g.clear()
    g.text_center(4, "\x06 \x03 \x05 \x04")
    g.text_center(15, "CASINO", 2)
    g.text_center(35, "DON'T TOUCH THE PADS")
    g.rect(24, 48, 80, 6, WHITE)
    g.fill_rect(26, 50, 76 * progress // total, 2, WHITE)
