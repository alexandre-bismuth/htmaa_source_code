//! Pure game rules (same as rules.h in the C++ version).

/// xorshift32 random numbers, identical in every port so a seed replays the same game.
#[derive(Clone, Copy)]
pub struct Rng {
    pub state: u32,
}

impl Rng {
    pub fn next_u32(&mut self) -> u32 {
        let mut x = self.state;
        x ^= x << 13;
        x ^= x >> 17;
        x ^= x << 5;
        self.state = x;
        x
    }

    pub fn below(&mut self, n: u32) -> u32 {
        self.next_u32() % n
    }
}

/// Cards are 0..51: rank = card % 13 (0 = '2' .. 12 = 'A'), suit = card / 13.
pub struct Deck {
    pub cards: [u8; 52],
    pub pos: usize,
}

impl Default for Deck {
    fn default() -> Self {
        Self::new()
    }
}

impl Deck {
    pub const fn new() -> Self {
        Deck { cards: [0; 52], pos: 0 }
    }

    pub fn shuffle(&mut self, rng: &mut Rng) {
        for (i, c) in self.cards.iter_mut().enumerate() {
            *c = i as u8;
        }
        for i in (1..52).rev() {
            let j = rng.below(i as u32 + 1) as usize;
            self.cards.swap(i, j);
        }
        self.pos = 0;
    }

    pub fn draw(&mut self) -> u8 {
        self.pos += 1;
        self.cards[self.pos - 1]
    }
}

// ---------- Blackjack ----------
pub fn bj_total(cards: &[u8]) -> i32 {
    let mut sum = 0;
    let mut aces = 0;
    for &c in cards {
        let r = (c % 13) as i32;
        sum += if r < 8 { r + 2 } else if r < 12 { 10 } else { 11 };
        aces += (r == 12) as i32;
    }
    while sum > 21 && aces > 0 {
        sum -= 10;
        aces -= 1;
    }
    sum
}

/// Chips returned to the player (stake included) for a finished hand, and the result message.
pub fn bj_settle(bet: i32, p: i32, p_n: usize, d: i32, d_n: usize) -> (i32, &'static str) {
    let (p_bj, d_bj) = (p == 21 && p_n == 2, d == 21 && d_n == 2);
    if p_bj && d_bj {
        (bet, "PUSH")
    } else if p_bj {
        (bet + bet * 3 / 2, "BLACKJACK!")
    } else if d_bj {
        (0, "DEALER BLACKJACK")
    } else if p > 21 {
        (0, "BUST")
    } else if d > 21 {
        (2 * bet, "DEALER BUSTS")
    } else if p > d {
        (2 * bet, "YOU WIN")
    } else if p < d {
        (0, "DEALER WINS")
    } else {
        (bet, "PUSH")
    }
}

// ---------- Poker hands ----------
/// Score of up to 5 cards: category << 20 | tie-break ranks. Higher is better.
pub fn eval_cards(c: &[u8]) -> u32 {
    let mut cnt = [0u8; 13];
    for &card in c {
        cnt[(card % 13) as usize] += 1;
    }
    let mut g = [0u8; 5]; // ranks grouped by count, then by rank
    let mut ng = 0;
    for k in (1..=4).rev() {
        for r in (0..13).rev() {
            if cnt[r] == k {
                g[ng] = r as u8;
                ng += 1;
            }
        }
    }
    let flush = c.len() == 5 && c.iter().all(|&x| x / 13 == c[0] / 13);
    let mut high = -1i32; // straight's top card (3 = the 5 of the wheel A-2-3-4-5)
    if ng == 5 {
        if g[0] - g[4] == 4 {
            high = g[0] as i32;
        } else if g[0] == 12 && g[1] == 3 {
            high = 3;
        }
    }
    let top = cnt[g[0] as usize];
    let second = if ng > 1 { cnt[g[1] as usize] } else { 0 };
    let cat: u32 = match () {
        _ if high >= 0 && flush => 8,
        _ if top == 4 => 7,
        _ if top == 3 && second >= 2 => 6,
        _ if flush => 5,
        _ if high >= 0 => 4,
        _ if top == 3 => 3,
        _ if top == 2 && second == 2 => 2,
        _ if top == 2 => 1,
        _ => 0,
    };
    let mut score = cat << 20;
    if high >= 0 {
        score |= (high as u32) << 16;
    } else {
        for (i, &r) in g[..ng].iter().enumerate() {
            score |= (r as u32) << (16 - 4 * i);
        }
    }
    score
}

/// Best 5-card score out of up to 7 cards.
pub fn best_hand(c: &[u8]) -> u32 {
    if c.len() <= 5 {
        return eval_cards(c);
    }
    let mut best = 0;
    let mut pick = [0u8; 5];
    for m in 0u32..1 << c.len() {
        if m.count_ones() != 5 {
            continue;
        }
        let mut k = 0;
        for (i, &card) in c.iter().enumerate() {
            if m >> i & 1 == 1 {
                pick[k] = card;
                k += 1;
            }
        }
        best = best.max(eval_cards(&pick));
    }
    best
}

pub fn is_royal(s: u32) -> bool {
    s >> 20 == 8 && (s >> 16 & 15) == 12
}

pub fn hand_name(s: u32) -> &'static str {
    const NAMES: [&str; 9] =
        ["HIGH CARD", "PAIR", "TWO PAIR", "TRIPS", "STRAIGHT", "FLUSH", "FULL HOUSE", "QUADS", "STR FLUSH"];
    if is_royal(s) {
        "ROYAL"
    } else {
        NAMES[(s >> 20) as usize]
    }
}

/// Ultimate Texas Hold'em: chips returned (stake included). The Blind pays on a straight or better.
pub fn uth_settle(ante: i32, play: i32, p: u32, d: u32, folded: bool) -> (i32, &'static str) {
    const BLIND_X2: [i32; 10] = [0, 0, 0, 0, 2, 3, 6, 20, 100, 1000]; // pays x/2: 1 (straight) .. 500 (royal)
    let open = d >> 20 >= 1; // dealer needs a pair
    if folded {
        (0, "FOLDED")
    } else if p > d {
        let cat = if is_royal(p) { 9 } else { (p >> 20) as usize };
        let ret = 2 * play + if open { 2 * ante } else { ante } + ante + ante * BLIND_X2[cat] / 2;
        (ret, if open { "YOU WIN" } else { "DEALER NO PAIR" })
    } else if p < d {
        (if open { 0 } else { ante }, "DEALER WINS")
    } else {
        (2 * ante + play, "PUSH")
    }
}

// ---------- Roulette (European, single zero) ----------
pub const WHEEL: [u8; 37] = [
    0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10, 5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18,
    29, 7, 28, 12, 35, 3, 26,
];
pub const N_BETS: i32 = 9 + 37; // 9 outside bets, then straight numbers 0..36

pub fn is_red(n: i32) -> bool {
    n != 0 && if n <= 10 || (19..=28).contains(&n) { n % 2 == 1 } else { n % 2 == 0 }
}

pub fn wheel_index(n: i32) -> i32 {
    WHEEL.iter().position(|&w| w as i32 == n).unwrap_or(0) as i32
}

pub fn bet_pays(b: i32) -> i32 {
    if b < 6 {
        1
    } else if b < 9 {
        2
    } else {
        35
    }
}

pub fn bet_wins(b: i32, n: i32) -> bool {
    match b {
        0 => is_red(n),
        1 => n > 0 && !is_red(n),
        2 => n > 0 && n % 2 == 0,
        3 => n % 2 == 1,
        4 => (1..=18).contains(&n),
        5 => n >= 19,
        6..=8 => n > 0 && (n - 1) / 12 == b - 6,
        _ => n == b - 9,
    }
}
