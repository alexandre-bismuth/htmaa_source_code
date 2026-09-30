# Game rules on card numbers 0..51 (rank = card % 13, suit = card // 13); hot paths compiled with viper.
import micropython
from array import array

_cnt = bytearray(13)      # scratch buffers: no allocation while evaluating hands
_grp = bytearray(5)
_pick = bytearray(5)


class Rng:
    """xorshift32 random numbers (identical in every port, so a seed replays the same game)."""

    def __init__(self, seed=0x2545F491):
        self.s = array("I", [seed])

    @property
    def state(self):
        return self.s[0]

    @state.setter
    def state(self, value):
        self.s[0] = value

    def below(self, n):
        return _below(self.s, n)


@micropython.viper
def _below(s: ptr32, n: int) -> int:
    x = uint(s[0])
    x = (x ^ (x << 13)) & uint(0xFFFFFFFF)
    x ^= x >> 17
    x = (x ^ (x << 5)) & uint(0xFFFFFFFF)
    s[0] = x
    hi = int(x >> 16)                        # x % n without unsigned division
    lo = int(x & uint(0xFFFF))
    return ((hi % n) * (65536 % n) + lo) % n


rng = Rng()


@micropython.viper
def _shuffle(c: ptr8, s: ptr32):
    for i in range(52):
        c[i] = i
    x = uint(s[0])
    i = 51
    while i > 0:
        x = (x ^ (x << 13)) & uint(0xFFFFFFFF)
        x ^= x >> 17
        x = (x ^ (x << 5)) & uint(0xFFFFFFFF)
        n = i + 1
        j = ((int(x >> 16) % n) * (65536 % n) + int(x & uint(0xFFFF))) % n
        t = c[i]
        c[i] = c[j]
        c[j] = t
        i -= 1
    s[0] = x


class Deck:
    def __init__(self):
        self.cards = bytearray(52)
        self.pos = 0

    def shuffle(self):
        _shuffle(self.cards, rng.s)
        self.pos = 0

    def draw(self):
        self.pos += 1
        return self.cards[self.pos - 1]


# ---------- Blackjack ----------
@micropython.viper
def bj_total(c: ptr8, n: int) -> int:
    total = 0
    aces = 0
    for i in range(n):
        r = int(c[i]) % 13
        if r < 8:
            total += r + 2
        elif r < 12:
            total += 10
        else:
            total += 11
            aces += 1
    while total > 21 and aces > 0:
        total -= 10
        aces -= 1
    return total


def bj_settle(bet, p, p_count, d, d_count):
    """Chips returned to the player (stake included) and the result message."""
    p_bj = p == 21 and p_count == 2
    d_bj = d == 21 and d_count == 2
    if p_bj and d_bj:
        return bet, "PUSH"
    if p_bj:
        return bet + bet * 3 // 2, "BLACKJACK!"
    if d_bj:
        return 0, "DEALER BLACKJACK"
    if p > 21:
        return 0, "BUST"
    if d > 21:
        return 2 * bet, "DEALER BUSTS"
    if p > d:
        return 2 * bet, "YOU WIN"
    if p < d:
        return 0, "DEALER WINS"
    return bet, "PUSH"


# ---------- Poker hands ----------
HAND_NAMES = ("HIGH CARD", "PAIR", "TWO PAIR", "TRIPS", "STRAIGHT", "FLUSH", "FULL HOUSE", "QUADS", "STR FLUSH")


@micropython.viper
def eval_cards(c: ptr8, n: int) -> int:
    """Score of up to 5 cards: category << 20 | tie-break ranks. Higher is better."""
    cnt = ptr8(_cnt)
    g = ptr8(_grp)
    for r in range(13):
        cnt[r] = 0
    for i in range(n):
        r = int(c[i]) % 13
        cnt[r] = int(cnt[r]) + 1
    ng = 0
    k = 4
    while k >= 1:                            # ranks grouped by count, then by rank
        r = 12
        while r >= 0:
            if int(cnt[r]) == k:
                g[ng] = r
                ng += 1
            r -= 1
        k -= 1
    flush = 0
    if n == 5:
        flush = 1
        suit = int(c[0]) // 13
        for i in range(1, 5):
            if int(c[i]) // 13 != suit:
                flush = 0
    high = -1                                # straight's top card (3 = the 5 of the wheel A-2-3-4-5)
    if ng == 5:
        if int(g[0]) - int(g[4]) == 4:
            high = int(g[0])
        elif int(g[0]) == 12 and int(g[1]) == 3:
            high = 3
    top = int(cnt[int(g[0])])
    second = 0
    if ng > 1:
        second = int(cnt[int(g[1])])
    if high >= 0 and flush:
        cat = 8
    elif top == 4:
        cat = 7
    elif top == 3 and second >= 2:
        cat = 6
    elif flush:
        cat = 5
    elif high >= 0:
        cat = 4
    elif top == 3:
        cat = 3
    elif top == 2 and second == 2:
        cat = 2
    elif top == 2:
        cat = 1
    else:
        cat = 0
    score = cat << 20
    if high >= 0:
        score |= high << 16
    else:
        for i in range(ng):
            score |= int(g[i]) << (16 - 4 * i)
    return score


@micropython.viper
def best_hand(c: ptr8, n: int) -> int:
    """Best 5-card score out of up to 7 cards."""
    if n <= 5:
        return int(eval_cards(c, n))
    p = ptr8(_pick)
    best = 0
    m = 0
    end = 1 << n
    while m < end:
        bits = 0
        b = m
        while b:
            bits += b & 1
            b >>= 1
        if bits == 5:
            j = 0
            for i in range(n):
                if (m >> i) & 1:
                    p[j] = c[i]
                    j += 1
            s = int(eval_cards(_pick, 5))
            if s > best:
                best = s
        m += 1
    return best


def is_royal(score):
    return score >> 20 == 8 and (score >> 16) & 15 == 12


def hand_name(score):
    return "ROYAL" if is_royal(score) else HAND_NAMES[score >> 20]


BLIND_X2 = (0, 0, 0, 0, 2, 3, 6, 20, 100, 1000)     # Blind pays x/2: straight 1:1 .. royal 500:1


def uth_settle(ante, play, p, d, folded):
    """Ultimate Texas Hold'em: chips returned (stake included) and the result message."""
    dealer_opens = d >> 20 >= 1
    if folded:
        return 0, "FOLDED"
    if p > d:
        category = 9 if is_royal(p) else p >> 20
        ret = 2 * play + (2 * ante if dealer_opens else ante) + ante + ante * BLIND_X2[category] // 2
        return ret, "YOU WIN" if dealer_opens else "DEALER NO PAIR"
    if p < d:
        return (0 if dealer_opens else ante), "DEALER WINS"
    return 2 * ante + play, "PUSH"


# ---------- Roulette (European, single zero) ----------
WHEEL = (0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10,
         5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26)
N_BETS = 9 + 37
BET_NAMES = ("RED", "BLACK", "EVEN", "ODD", "1-18", "19-36", "1ST 12", "2ND 12", "3RD 12") + tuple(
    "No." + str(n) for n in range(37))


def is_red(n):
    if n == 0:
        return False
    if n <= 10 or 19 <= n <= 28:
        return n % 2 == 1
    return n % 2 == 0


def bet_pays(bet):
    return 1 if bet < 6 else 2 if bet < 9 else 35


def bet_wins(bet, n):
    if bet == 0:
        return is_red(n)
    if bet == 1:
        return n > 0 and not is_red(n)
    if bet == 2:
        return n > 0 and n % 2 == 0
    if bet == 3:
        return n % 2 == 1
    if bet == 4:
        return 1 <= n <= 18
    if bet == 5:
        return n >= 19
    if bet < 9:
        return n > 0 and (n - 1) // 12 == bet - 6
    return n == bet - 9


def bet_name(bet):
    return BET_NAMES[bet]
