# Widgets, cards, LED and the round/banner/bet logic shared by the games.
# Text is bytes and formatted strings are cached, so a normal frame allocates nothing.
import micropython
from machine import Pin
import gfx
from gfx import BLACK, WHITE, Sprite
from touch import UP, DOWN

CW, CH = 11, 17                                    # card size in pixels
SLIDE_MS, FLIP_MS = 160, 90
CHIPS = (5, 10, 25, 50, 100, 250, 500, 1000)
NUMBERS = tuple(str(n).encode() for n in range(100))
RANKS = b"23456789TJQKA"
CARDS = []                                         # 52 face sprites, built by build_sprites()
BACK = None


@micropython.viper
def ease_out(k: int, total: int) -> int:
    """Cubic ease-out, 0..1024."""
    if k >= total:
        return 1024
    r = 1024 - k * 1024 // total
    return 1024 - ((r * r * r) >> 20)


_money = {}


def money(v):
    s = _money.get(v)
    if s is None:
        s = (("+%d" if v > 0 else "%d") % v).encode()
        _money[v] = s
    return s


# ---------- Widgets ----------
_bank_text = [b"", -1]


def bank_text(bank):
    if _bank_text[1] != bank:
        _bank_text[0] = ("$%d" % bank).encode()
        _bank_text[1] = bank
    return _bank_text[0]


def header(title, bank):
    gfx.text(0, 0, title)
    gfx.text_right(127, 0, bank_text(bank))


def bar(items, n, selected):
    """Equal slots along the bottom; the selected one is inverted (= what OK does)."""
    for i in range(n):
        x0 = i * 128 // n
        x1 = (i + 1) * 128 // n
        cx = (x0 + x1) // 2
        if i == selected:
            gfx.fill_round_rect(x0, 55, x1 - x0, 9, 2, WHITE)
            gfx.text_center(56, items[i], 1, BLACK, cx)
        else:
            gfx.text_center(56, items[i], 1, WHITE, cx)


_bet_lines = {}


def bet_bar(label, amount, action):
    lines = _bet_lines.get(label)
    if lines is None:
        lines = _bet_lines[label] = {}
    s = lines.get(amount)
    if s is None:
        s = lines[amount] = b"\x12 " + label + b" " + NUMBERS[amount] if amount < 100 else (
            b"\x12 " + label + b" " + str(amount).encode())
    gfx.text(0, 56, s)
    w = gfx.text_width(action) + 8
    gfx.fill_round_rect(128 - w, 55, w, 9, 2, WHITE)
    gfx.text_right(123, 56, action, 1, BLACK)


def banner(y, line1, net):
    gfx.fill_rect(10, y, 108, 32, BLACK)
    gfx.rect(10, y, 108, 32, WHITE)
    gfx.rect(12, y + 2, 104, 28, WHITE)
    gfx.text_center(y + 5, line1)
    gfx.text_center(y + 14, money(net), 2)


def draw_splash(progress, total):
    gfx.clear()
    gfx.text_center(4, b"\x06 \x03 \x05 \x04")
    gfx.text_center(15, b"CASINO", 2)
    gfx.text_center(35, b"DON'T TOUCH THE PADS")
    gfx.rect(24, 48, 80, 6, WHITE)
    gfx.fill_rect(26, 50, 76 * progress // total, 2, WHITE)


# ---------- Cards ----------
def paint_card(x, y, card):
    gfx.fill_round_rect(x - 1, y - 1, CW + 2, CH + 2, 2, BLACK)
    gfx.fill_round_rect(x, y, CW, CH, 2, WHITE)
    r = card % 13
    if r == 8:                                     # "10" squeezed into one card width
        gfx.char(x, y + 1, 0x31, BLACK)
        gfx.char(x + 5, y + 1, 0x30, BLACK)
    else:
        gfx.char(x + 3, y + 1, RANKS[r], BLACK)
    gfx.char(x + 3, y + 9, 3 + card // 13, BLACK)


def paint_card_back(x, y):
    gfx.fill_round_rect(x - 1, y - 1, CW + 2, CH + 2, 2, BLACK)
    gfx.round_rect(x, y, CW, CH, 2, WHITE)
    for j in range(2, CH - 2):
        for i in range(2, CW - 2):
            if (i + j) % 4 == 0 or (i - j) % 4 == 0:
                gfx.pixel(x + i, y + j, WHITE)


def build_sprites():
    global BACK
    for card in range(52):
        CARDS.append(Sprite(CW + 2, CH + 2, lambda: paint_card(1, 1, card)))
    BACK = Sprite(CW + 2, CH + 2, lambda: paint_card_back(1, 1))


class Slot:
    """A card on the table: slides in at deal_at, face up from show_at (0 = face down)."""

    def __init__(self, card, deal_at, show_at):
        self.card = card
        self.deal_at = deal_at
        self.show_at = show_at

    def is_up(self, now):
        return self.show_at != 0 and now >= self.show_at


@micropython.native
def draw_slot(x, y, slot, now):
    """Slides in from the shoe (top right), flips edge-on when turned face up."""
    if now < slot.deal_at:
        return
    k = now - slot.deal_at
    if k < SLIDE_MS:
        e = ease_out(k, SLIDE_MS)
        x = 120 + ((x - 120) * e >> 10)
        y = -CH + ((y + CH) * e >> 10)
    if slot.show_at > slot.deal_at and now >= slot.show_at and now - slot.show_at < FLIP_MS:
        gfx.fill_rect(x + 4, y, 3, CH, WHITE)
        return
    if slot.show_at != 0 and now >= slot.show_at:
        CARDS[slot.card].draw(x - 1, y - 1)
    else:
        BACK.draw(x - 1, y - 1)


def draw_hand(hand, y, now, max_w=100):
    n = len(hand)
    step = min(CW + 2, (max_w - CW) // (n - 1)) if n > 1 else 0
    for i in range(n):
        draw_slot(i * step, y, hand[i], now)


def all_cards(hand, out, start=0):
    """Copies the hand's cards into the bytearray out; returns how many."""
    for i in range(len(hand)):
        out[start + i] = hand[i].card
    return len(hand)


def up_cards(hand, now, out, start=0):
    n = 0
    for slot in hand:
        if slot.show_at != 0 and now >= slot.show_at:
            out[start + n] = slot.card
            n += 1
    return n


# ---------- LED (active LOW) ----------
LED_OFF, LED_GREEN, LED_RED, LED_BLUE = 0, 1, 2, 3


class Led:
    def __init__(self):
        self.red = Pin(17, Pin.OUT, value=1)
        self.green = Pin(16, Pin.OUT, value=1)
        self.blue = Pin(25, Pin.OUT, value=1)
        self.color = LED_OFF
        self.until = 0

    def flash(self, color, now):
        self.red.value(0 if color == LED_RED else 1)
        self.green.value(0 if color == LED_GREEN else 1)
        self.blue.value(0 if color == LED_BLUE else 1)
        self.color = color
        self.until = now + 900

    def update(self, now):
        if self.color != LED_OFF and now > self.until:
            self.flash(LED_OFF, now)


# ---------- Rounds: result banner, payout, bets ----------
class Round:
    def __init__(self):
        self.bet_idx = 1
        self.busy_until = 0
        self.result_at = 0
        self.banner = False
        self.payout = -1                           # -1 = nothing pending
        self.net = 0
        self.msg = b""

    def show_result(self, msg, payout, net, at):
        self.msg = msg.encode() if isinstance(msg, str) else msg
        self.payout = payout
        self.net = net
        self.result_at = at
        self.busy_until = at + 400
        self.banner = True

    def banner_visible(self, now):
        return self.banner and self.result_at <= now < self.result_at + 2500

    def pay_when_shown(self, casino):
        """Pays out when the banner appears, so the bank doesn't change before the reveal."""
        if self.payout < 0 or casino.clock < self.result_at:
            return
        casino.bank += self.payout
        self.payout = -1
        casino.led.flash(LED_GREEN if self.net > 0 else LED_RED if self.net < 0 else LED_BLUE, casino.clock)

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
        self.show_result(b"HOUSE LOAN", -1, 1000, casino.clock)
        casino.led.flash(LED_BLUE, casino.clock)
        return False
