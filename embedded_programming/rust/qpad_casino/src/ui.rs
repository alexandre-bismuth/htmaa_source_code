//! Shared table state, widgets, cards and the round/banner/bet logic used by all games.

use crate::gfx::{text_width, Gfx, BLACK, WHITE};
use crate::rules::{Deck, Rng};
use core::fmt::Write;
use heapless::String;

pub const UP: u8 = 0;
pub const DOWN: u8 = 1;
pub const LEFT: u8 = 2;
pub const RIGHT: u8 = 3;
pub const OK: u8 = 4;
pub const BACK: u8 = 5;

pub const CHIPS: [i32; 8] = [5, 10, 25, 50, 100, 250, 500, 1000];
pub const CW: i32 = 11; // card size in pixels
pub const CH: i32 = 17;
pub const SLIDE_MS: u32 = 160;
pub const FLIP_MS: u32 = 90;

pub fn pressed(ev: u8, button: u8) -> bool {
    ev >> button & 1 == 1
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Led {
    Off,
    Green,
    Red,
    Blue,
}

/// What every game shares: the bank, the game clock, the deck and the LED.
pub struct Table {
    pub bank: i32,
    pub clock: u32, // game time in ms (the benchmark simulates it)
    pub rng: Rng,
    pub deck: Deck,
    pub led: Led,
    led_until: u32,
}

impl Default for Table {
    fn default() -> Self {
        Self::new()
    }
}

impl Table {
    pub const fn new() -> Self {
        Table { bank: 1000, clock: 0, rng: Rng { state: 0x2545F491 }, deck: Deck::new(), led: Led::Off, led_until: 0 }
    }

    pub fn flash(&mut self, led: Led) {
        self.led = led;
        self.led_until = self.clock + 900;
    }

    pub fn led_update(&mut self) {
        if self.led != Led::Off && self.clock > self.led_until {
            self.flash(Led::Off);
        }
    }
}

// ---------- Text ----------
pub type Text = String<24>;

pub fn fmt(args: core::fmt::Arguments) -> Text {
    let mut s = Text::new();
    let _ = s.write_fmt(args);
    s
}

pub fn money(v: i32) -> Text {
    if v > 0 {
        fmt(format_args!("+{}", v))
    } else {
        fmt(format_args!("{}", v))
    }
}

// ---------- Widgets ----------
pub fn header(g: &mut Gfx, title: &[u8], bank: i32) {
    g.text(0, 0, title, 1, WHITE);
    g.text_right(127, 0, fmt(format_args!("${}", bank)).as_bytes(), 1, WHITE);
}

/// Equal slots along the bottom; the selected one is inverted (= what OK does).
pub fn bar(g: &mut Gfx, items: &[&[u8]], sel: usize) {
    let n = items.len() as i32;
    for (i, item) in items.iter().enumerate() {
        let (x0, x1) = (i as i32 * 128 / n, (i as i32 + 1) * 128 / n);
        if i == sel {
            g.fill_round_rect(x0, 55, x1 - x0, 9, 2, WHITE);
            g.text_center(56, item, 1, BLACK, (x0 + x1) / 2);
        } else {
            g.text_center(56, item, 1, WHITE, (x0 + x1) / 2);
        }
    }
}

pub fn bet_bar(g: &mut Gfx, label: &str, amount: i32, action: &[u8]) {
    g.text(0, 56, fmt(format_args!("\x12 {} {}", label, amount)).as_bytes(), 1, WHITE);
    let w = text_width(action, 1) + 8;
    g.fill_round_rect(128 - w, 55, w, 9, 2, WHITE);
    g.text_right(123, 56, action, 1, BLACK);
}

pub fn banner(g: &mut Gfx, y: i32, line1: &[u8], net: i32) {
    g.fill_rect(10, y, 108, 32, BLACK);
    g.rect(10, y, 108, 32, WHITE);
    g.rect(12, y + 2, 104, 28, WHITE);
    g.text_center(y + 5, line1, 1, WHITE, 64);
    g.text_center(y + 14, money(net).as_bytes(), 2, WHITE, 64);
}

pub fn splash(g: &mut Gfx, progress: i32, total: i32) {
    g.clear();
    g.text_center(4, b"\x06 \x03 \x05 \x04", 1, WHITE, 64);
    g.text_center(15, b"CASINO", 2, WHITE, 64);
    g.text_center(35, b"DON'T TOUCH THE PADS", 1, WHITE, 64);
    g.rect(24, 48, 80, 6, WHITE);
    g.fill_rect(26, 50, 76 * progress / total, 2, WHITE);
}

/// Cubic ease-out, 0..1024 (integer: the M0+ has no FPU).
pub fn ease_out(k: u32, total: u32) -> i32 {
    if k >= total {
        return 1024;
    }
    let r = 1024 - k * 1024 / total;
    1024 - ((r * r * r) >> 20) as i32
}

// ---------- Cards ----------
/// A card on the table: slides in at deal_at, face up from show_at (0 = face down).
#[derive(Clone, Copy, Default)]
pub struct Slot {
    pub card: u8,
    pub deal_at: u32,
    pub show_at: u32,
}

impl Slot {
    pub fn is_up(&self, now: u32) -> bool {
        self.show_at != 0 && now >= self.show_at
    }
}

pub type Hand = heapless::Vec<Slot, 12>;

pub fn add(hand: &mut Hand, card: u8, deal_at: u32, show_at: u32) {
    let _ = hand.push(Slot { card, deal_at, show_at });
}

/// The hand's cards (all, or only those face up) copied into `out`; returns how many.
pub fn cards(hand: &Hand, now: Option<u32>, out: &mut [u8]) -> usize {
    let mut n = 0;
    for s in hand.iter().filter(|s| now.is_none_or(|t| s.is_up(t))) {
        out[n] = s.card;
        n += 1;
    }
    n
}

pub fn draw_card(g: &mut Gfx, x: i32, y: i32, card: u8) {
    g.fill_round_rect(x - 1, y - 1, CW + 2, CH + 2, 2, BLACK);
    g.fill_round_rect(x, y, CW, CH, 2, WHITE);
    let r = card % 13;
    if r == 8 {
        // "10" squeezed into one card width
        g.char(x, y + 1, b'1', BLACK, 1);
        g.char(x + 5, y + 1, b'0', BLACK, 1);
    } else {
        g.char(x + 3, y + 1, b"23456789TJQKA"[r as usize], BLACK, 1);
    }
    g.char(x + 3, y + 9, 3 + card / 13, BLACK, 1); // CP437 3..6 = hearts diamonds clubs spades
}

pub fn draw_card_back(g: &mut Gfx, x: i32, y: i32) {
    g.fill_round_rect(x - 1, y - 1, CW + 2, CH + 2, 2, BLACK);
    g.round_rect(x, y, CW, CH, 2, WHITE);
    for j in 2..CH - 2 {
        for i in 2..CW - 2 {
            if (i + j) % 4 == 0 || (i - j + 40) % 4 == 0 {
                g.pixel(x + i, y + j, WHITE);
            }
        }
    }
}

/// Slides in from the shoe (top right), flips edge-on when turned face up.
pub fn draw_slot(g: &mut Gfx, mut x: i32, mut y: i32, s: &Slot, now: u32) {
    if now < s.deal_at {
        return;
    }
    let k = now - s.deal_at;
    if k < SLIDE_MS {
        let e = ease_out(k, SLIDE_MS);
        x = 120 + (((x - 120) * e) >> 10);
        y = -CH + (((y + CH) * e) >> 10);
    }
    if s.show_at > s.deal_at && now >= s.show_at && now - s.show_at < FLIP_MS {
        g.fill_rect(x + 4, y, 3, CH, WHITE);
    } else if s.is_up(now) {
        draw_card(g, x, y, s.card);
    } else {
        draw_card_back(g, x, y);
    }
}

pub fn draw_hand(g: &mut Gfx, hand: &Hand, y: i32, now: u32) {
    let n = hand.len() as i32;
    let step = if n > 1 { (CW + 2).min((100 - CW) / (n - 1)) } else { 0 };
    for (i, s) in hand.iter().enumerate() {
        draw_slot(g, i as i32 * step, y, s, now);
    }
}

// ---------- Rounds: result banner, payout, bets ----------
pub struct Round {
    pub bet_idx: usize,
    pub busy_until: u32,
    pub result_at: u32,
    pub banner: bool,
    pub payout: i32, // -1 = nothing pending
    pub net: i32,
    pub msg: Text,
}

impl Round {
    pub fn new() -> Self {
        Round { bet_idx: 1, busy_until: 0, result_at: 0, banner: false, payout: -1, net: 0, msg: Text::new() }
    }

    pub fn show_result(&mut self, msg: &str, payout: i32, net: i32, at: u32) {
        self.msg = fmt(format_args!("{}", msg));
        self.payout = payout;
        self.net = net;
        self.result_at = at;
        self.busy_until = at + 400;
        self.banner = true;
    }

    pub fn banner_visible(&self, now: u32) -> bool {
        self.banner && now >= self.result_at && now < self.result_at + 2500
    }

    /// Pays out when the banner appears, so the bank doesn't change before the reveal.
    pub fn pay_when_shown(&mut self, t: &mut Table) {
        if self.payout < 0 || t.clock < self.result_at {
            return;
        }
        t.bank += self.payout;
        self.payout = -1;
        t.flash(match self.net {
            n if n > 0 => Led::Green,
            n if n < 0 => Led::Red,
            _ => Led::Blue,
        });
    }

    /// mult = chips reserved per unit of bet (Hold'em needs ante + blind + 4x play).
    pub fn bet_input(&mut self, t: &Table, ev: u8, mult: i32) {
        if pressed(ev, UP) && self.bet_idx < CHIPS.len() - 1 && CHIPS[self.bet_idx + 1] * mult <= t.bank {
            self.bet_idx += 1;
        }
        if pressed(ev, DOWN) && self.bet_idx > 0 {
            self.bet_idx -= 1;
        }
        while self.bet_idx > 0 && CHIPS[self.bet_idx] * mult > t.bank {
            self.bet_idx -= 1;
        }
    }

    pub fn can_bet(&mut self, t: &mut Table, mult: i32) -> bool {
        if t.bank >= CHIPS[0] * mult {
            return true;
        }
        t.bank += 1000;
        self.show_result("HOUSE LOAN", -1, 1000, t.clock);
        t.flash(Led::Blue);
        false
    }

    pub fn bet(&self) -> i32 {
        CHIPS[self.bet_idx]
    }
}

impl Default for Round {
    fn default() -> Self {
        Self::new()
    }
}
