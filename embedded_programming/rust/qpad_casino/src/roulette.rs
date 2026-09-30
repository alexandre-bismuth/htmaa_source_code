//! Roulette: European single-zero wheel, one bet per spin.

use crate::gfx::{text_width, Gfx, BLACK, WHITE};
use crate::rules::{bet_pays, bet_wins, is_red, wheel_index, N_BETS, WHEEL};
use crate::ui::{banner, bet_bar, ease_out, fmt, header, pressed, Round, Table, BACK, LEFT, OK, RIGHT};

const OUTSIDE: [&str; 9] = ["RED", "BLACK", "EVEN", "ODD", "1-18", "19-36", "1ST 12", "2ND 12", "3RD 12"];
const SPIN_MS: u32 = 4200;

pub struct Roulette {
    pub round: Round,
    pub bet: i32,       // 0..8 outside bets, 9.. straight numbers
    pub spin_from: i32, // wheel positions (pockets) of the current spin
    pub spin_to: i32,
    spin_at: u32,
}

impl Roulette {
    pub fn new() -> Self {
        Roulette { round: Round::new(), bet: 0, spin_from: 0, spin_to: 0, spin_at: 0 }
    }

    pub fn enter(&mut self) {
        self.round.banner = false;
    }

    /// Returns true to go back to the menu.
    pub fn update(&mut self, t: &mut Table, ev: u8) -> bool {
        let r = &mut self.round;
        r.pay_when_shown(t);
        if t.clock < r.busy_until {
            return false;
        }
        self.spin_to %= 37;
        self.spin_from = self.spin_to;
        if ev != 0 {
            r.banner = false;
        }
        if pressed(ev, LEFT) {
            self.bet = (self.bet + N_BETS - 1) % N_BETS;
        }
        if pressed(ev, RIGHT) {
            self.bet = (self.bet + 1) % N_BETS;
        }
        r.bet_input(t, ev, 1);
        if pressed(ev, BACK) {
            return true;
        }
        if !pressed(ev, OK) || !r.can_bet(t, 1) {
            return false;
        }
        let stake = r.bet();
        let n = t.rng.below(37) as i32;
        t.bank -= stake;
        self.spin_to = self.spin_from + 2 * 37 + (wheel_index(n) - self.spin_from + 37) % 37; // two turns, then n
        self.spin_at = t.clock;
        let payout = if bet_wins(self.bet, n) { stake * (bet_pays(self.bet) + 1) } else { 0 };
        let color = if n == 0 { "GREEN" } else if is_red(n) { "RED" } else { "BLACK" };
        r.show_result(&fmt(format_args!("{} {}", n, color)), payout, payout - stake, t.clock + SPIN_MS + 250);
        false
    }

    /// Red pockets are filled, black ones outlined, zero double-framed.
    fn draw_pocket(g: &mut Gfx, x: i32, y: i32, n: i32) {
        let label = fmt(format_args!("{}", n));
        let tx = x + (13 - text_width(label.as_bytes(), 1)) / 2;
        if is_red(n) {
            g.fill_round_rect(x, y, 13, 13, 2, WHITE);
            g.text(tx, y + 3, label.as_bytes(), 1, BLACK);
        } else {
            g.round_rect(x, y, 13, 13, 2, WHITE);
            if n == 0 {
                g.rect(x + 2, y + 2, 9, 9, WHITE);
            }
            g.text(tx, y + 3, label.as_bytes(), 1, WHITE);
        }
    }

    pub fn draw(&self, g: &mut Gfx, t: &Table) {
        let e = ease_out(t.clock - self.spin_at, SPIN_MS);
        let pix = self.spin_from * 16 + (((self.spin_to - self.spin_from) * 16 * e) >> 10); // strip position
        header(g, b"ROULETTE", t.bank);
        for k in -5..=5 {
            let n = WHEEL[((pix / 16 + k + 37) % 37) as usize] as i32;
            Self::draw_pocket(g, 57 + k * 16 - pix % 16, 12, n);
        }
        g.rect(55, 10, 17, 17, WHITE);
        g.fill_triangle(60, 27, 66, 27, 63, 30, WHITE);
        g.text(0, 34, b"\x11", 1, WHITE);
        g.text(123, 34, b"\x10", 1, WHITE);
        let name = if self.bet < 9 { fmt(format_args!("{}", OUTSIDE[self.bet as usize])) } else { fmt(format_args!("No.{}", self.bet - 9)) };
        g.text_center(32, name.as_bytes(), 2, WHITE, 64);
        g.text_center(47, fmt(format_args!("PAYS {} TO 1", bet_pays(self.bet))).as_bytes(), 1, WHITE, 64);
        bet_bar(g, "BET", self.round.bet(), b"SPIN");
        if self.round.banner_visible(t.clock) {
            banner(g, 28, self.round.msg.as_bytes(), self.round.net);
        }
    }
}

impl Default for Roulette {
    fn default() -> Self {
        Self::new()
    }
}
