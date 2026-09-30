//! Main menu: a carousel of the three games with animated icons (integer trig).

use crate::gfx::{Gfx, BLACK, WHITE};
use crate::ui::{ease_out, fmt, pressed, Table, DOWN, LEFT, OK, RIGHT, UP};

const GAMES: [&[u8]; 3] = [b"ROULETTE", b"BLACKJACK", b"ULTIMATE HOLD'EM"];
const SLIDE_MS: u32 = 220;
/// sin(k * 5 deg) * 1024
const SIN72: [i32; 72] = [
    0, 89, 178, 265, 350, 433, 512, 587, 658, 724, 784, 839, 887, 928, 962, 989, 1008, 1020, 1024, 1020, 1008, 989,
    962, 928, 887, 839, 784, 724, 658, 587, 512, 433, 350, 265, 178, 89, 0, -89, -178, -265, -350, -433, -512, -587,
    -658, -724, -784, -839, -887, -928, -962, -989, -1008, -1020, -1024, -1020, -1008, -989, -962, -928, -887, -839,
    -784, -724, -658, -587, -512, -433, -350, -265, -178, -89,
];

/// Point on a circle of radius r at angle a (5 degree steps).
fn icos(r: i32, a: i32) -> i32 {
    (r * SIN72[((a + 18) % 72) as usize] + 512) >> 10
}
fn isin(r: i32, a: i32) -> i32 {
    (r * SIN72[(a % 72) as usize] + 512) >> 10
}

pub struct Menu {
    pub selected: usize,
    previous: usize,
    direction: i32,
    slide_at: u32,
}

impl Default for Menu {
    fn default() -> Self {
        Self::new()
    }
}

impl Menu {
    pub const fn new() -> Self {
        Menu { selected: 0, previous: 0, direction: 1, slide_at: 0 }
    }

    /// Returns the game to open, if OK was pressed.
    pub fn update(&mut self, t: &Table, ev: u8) -> Option<usize> {
        let step = if pressed(ev, RIGHT) || pressed(ev, DOWN) {
            1
        } else if pressed(ev, LEFT) || pressed(ev, UP) {
            -1
        } else {
            0
        };
        if step != 0 {
            self.previous = self.selected;
            self.selected = (self.selected as i32 + step + 3) as usize % 3;
            self.direction = step;
            self.slide_at = t.clock;
        }
        pressed(ev, OK).then_some(self.selected)
    }

    fn draw_wheel(g: &mut Gfx, cx: i32, cy: i32, t: u32) {
        let a0 = (t / 25 % 72) as i32; // wheel turns 5 deg every 25 ms
        g.circle(cx, cy, 16, WHITE);
        g.circle(cx, cy, 11, WHITE);
        for k in 0..18 {
            let a = a0 + k * 4;
            g.line(cx + icos(11, a), cy + isin(11, a), cx + icos(16, a), cy + isin(16, a), WHITE);
        }
        for k in 0..4 {
            let a = a0 + k * 18;
            g.line(cx, cy, cx + icos(11, a), cy + isin(11, a), WHITE);
        }
        g.fill_circle(cx, cy, 3, WHITE);
        let b = 71 - (t / 12 % 72) as i32; // ball runs the other way
        g.fill_circle(cx + icos(14, b), cy + isin(14, b), 1, WHITE);
    }

    fn draw_big_card(g: &mut Gfx, x: i32, y: i32, rank: u8, suit: u8) {
        g.fill_round_rect(x - 1, y - 1, 24, 32, 3, BLACK);
        g.fill_round_rect(x, y, 22, 30, 3, WHITE);
        g.char(x + 3, y + 3, rank, BLACK, 2);
        g.char(x + 9, y + 14, suit, BLACK, 2);
    }

    fn draw_cards(g: &mut Gfx, cx: i32, cy: i32, t: u32) {
        let lift = isin(2, (t / 40 % 72) as i32);
        Self::draw_big_card(g, cx - 21, cy - 15, b'A', 6);
        Self::draw_big_card(g, cx - 1, cy - 13 + lift, b'K', 3);
    }

    fn draw_chip(g: &mut Gfx, cx: i32, cy: i32, t: u32) {
        let a0 = (t / 33 % 72) as i32;
        g.fill_circle(cx, cy, 16, WHITE);
        g.fill_circle(cx, cy, 11, BLACK);
        g.circle(cx, cy, 9, WHITE);
        for k in 0..6 {
            let a = a0 + k * 12;
            g.fill_circle(cx + icos(14, a), cy + isin(14, a), 2, BLACK);
        }
        g.char(cx - 5, cy - 7, 6, WHITE, 2);
    }

    fn draw_item(g: &mut Gfx, i: usize, dx: i32, t: u32) {
        match i {
            0 => Self::draw_wheel(g, 64 + dx, 30, t),
            1 => Self::draw_cards(g, 64 + dx, 30, t),
            _ => Self::draw_chip(g, 64 + dx, 30, t),
        }
        g.text_center(49, GAMES[i], 1, WHITE, 64 + dx);
    }

    pub fn draw(&self, g: &mut Gfx, t: &Table) {
        g.text(0, 0, b"QPAD CASINO", 1, WHITE);
        g.text_right(127, 0, fmt(format_args!("${}", t.bank)).as_bytes(), 1, WHITE);
        let k = (t.clock - self.slide_at).min(SLIDE_MS);
        let offset = (self.direction * 128 * (1024 - ease_out(k, SLIDE_MS))) >> 10;
        Self::draw_item(g, self.selected, offset, t.clock);
        if k < SLIDE_MS {
            Self::draw_item(g, self.previous, offset - self.direction * 128, t.clock);
        }
        g.fill_rect(0, 10, 9, 38, BLACK);
        g.fill_rect(119, 10, 9, 38, BLACK);
        g.text(1, 27, b"\x11", 1, WHITE);
        g.text(122, 27, b"\x10", 1, WHITE);
        for i in 0..3 {
            if i == self.selected {
                g.fill_circle(56 + i as i32 * 8, 60, 2, WHITE);
            } else {
                g.circle(56 + i as i32 * 8, 60, 2, WHITE);
            }
        }
    }
}
