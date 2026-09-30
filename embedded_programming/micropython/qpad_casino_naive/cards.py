# Game rules: cards, hands, payouts and roulette (same rules as rules.h in the C++ version).


class Rng:
    """xorshift32 random numbers (identical in every port, so a seed replays the same game)."""

    def __init__(self, seed=0x2545F491):
        self.state = seed

    def next(self):
        x = self.state
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= x >> 17
        x ^= (x << 5) & 0xFFFFFFFF
        self.state = x
        return x

    def below(self, n):
        return self.next() % n


rng = Rng()

RANKS = "23456789TJQKA"


class Card:
    def __init__(self, index):
        self.index = index          # 0..51
        self.rank = index % 13      # 0 = '2' .. 12 = 'A'
        self.suit = index // 13     # hearts, diamonds, clubs, spades


class Deck:
    def __init__(self):
        self.cards = []

    def shuffle(self):
        self.cards = [Card(i) for i in range(52)]
        for i in range(51, 0, -1):
            j = rng.below(i + 1)
            self.cards[i], self.cards[j] = self.cards[j], self.cards[i]

    def draw(self):
        return self.cards.pop(0)


# ---------- Blackjack ----------
def bj_total(cards):
    total = 0
    aces = 0
    for card in cards:
        if card.rank < 8:
            total += card.rank + 2
        elif card.rank < 12:
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
HAND_NAMES = ["HIGH CARD", "PAIR", "TWO PAIR", "TRIPS", "STRAIGHT", "FLUSH", "FULL HOUSE", "QUADS", "STR FLUSH"]


def eval_cards(cards):
    """Score of up to 5 cards: category << 20 | tie-break ranks. Higher is better."""
    counts = {}
    for card in cards:
        counts[card.rank] = counts.get(card.rank, 0) + 1
    groups = sorted(counts, key=lambda r: (counts[r], r), reverse=True)
    flush = len(cards) == 5 and len(set(card.suit for card in cards)) == 1
    high = -1                                   # straight's top card (3 = the 5 of the wheel A-2-3-4-5)
    if len(groups) == 5:
        if groups[0] - groups[4] == 4:
            high = groups[0]
        elif groups[0] == 12 and groups[1] == 3:
            high = 3
    top = counts[groups[0]]
    second = counts[groups[1]] if len(groups) > 1 else 0
    if high >= 0 and flush:
        category = 8
    elif top == 4:
        category = 7
    elif top == 3 and second >= 2:
        category = 6
    elif flush:
        category = 5
    elif high >= 0:
        category = 4
    elif top == 3:
        category = 3
    elif top == 2 and second == 2:
        category = 2
    elif top == 2:
        category = 1
    else:
        category = 0
    score = category << 20
    if high >= 0:
        score |= high << 16
    else:
        for i, rank in enumerate(groups):
            score |= rank << (16 - 4 * i)
    return score


def best_hand(cards):
    """Best 5-card score out of up to 7 cards."""
    if len(cards) <= 5:
        return eval_cards(cards)
    best = 0
    for mask in range(1 << len(cards)):
        pick = [card for i, card in enumerate(cards) if mask >> i & 1]
        if len(pick) == 5:
            best = max(best, eval_cards(pick))
    return best


def is_royal(score):
    return score >> 20 == 8 and (score >> 16) & 15 == 12


def hand_name(score):
    return "ROYAL" if is_royal(score) else HAND_NAMES[score >> 20]


BLIND_X2 = [0, 0, 0, 0, 2, 3, 6, 20, 100, 1000]     # Blind pays x/2: straight 1:1 .. royal 500:1


def uth_settle(ante, play, p, d, folded):
    """Ultimate Texas Hold'em: chips returned (stake included) and the result message."""
    dealer_opens = d >> 20 >= 1                    # dealer needs a pair
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
WHEEL = [0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10,
         5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26]
OUTSIDE_BETS = ["RED", "BLACK", "EVEN", "ODD", "1-18", "19-36", "1ST 12", "2ND 12", "3RD 12"]
N_BETS = 9 + 37                                    # outside bets, then straight numbers 0..36


def is_red(n):
    if n == 0:
        return False
    if n <= 10 or 19 <= n <= 28:
        return n % 2 == 1
    return n % 2 == 0


def bet_pays(bet):
    if bet < 6:
        return 1
    if bet < 9:
        return 2
    return 35


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
    return OUTSIDE_BETS[bet] if bet < 9 else f"No.{bet - 9}"
