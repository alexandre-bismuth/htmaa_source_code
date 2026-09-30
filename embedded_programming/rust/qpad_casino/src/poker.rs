//! Ultimate Texas Hold'em: Ante + equal Blind; bet 3x/4x pre-flop, 2x on the flop, 1x or fold on the river.

use crate::gfx::{Gfx, WHITE};
use crate::rules::{best_hand, hand_name, uth_settle};
use crate::ui::{add, banner, bar, bet_bar, cards, draw_slot, fmt, header, pressed, Hand, Round, Table, BACK, LEFT, OK,
                RIGHT, SLIDE_MS};

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Phase {
    Bet,
    Pre,
    Flop,
    River,
}

impl Phase {
    fn options(self) -> &'static [&'static [u8]] {
        match self {
            Phase::Bet => &[],
            Phase::Pre => &[b"CHECK", b"BET 3x", b"BET 4x"],
            Phase::Flop => &[b"CHECK", b"BET 2x"],
            Phase::River => &[b"FOLD", b"BET 1x"],
        }
    }

    /// Play bet (in antes) for each option; 0 = check or fold.
    fn mult(self, option: usize) -> i32 {
        match (self, option) {
            (Phase::Pre, 1) => 3,
            (Phase::Pre, 2) => 4,
            (Phase::Flop, 1) => 2,
            (Phase::River, 1) => 1,
            _ => 0,
        }
    }
}

pub struct Holdem {
    pub round: Round,
    pub phase: Phase,
    pub player: Hand,
    pub dealer: Hand,
    pub board: Hand,
    ante: i32,
    play: i32,
    stake: i32,
    selected: usize,
}

impl Holdem {
    pub fn new() -> Self {
        Holdem {
            round: Round::new(), phase: Phase::Bet, player: Hand::new(), dealer: Hand::new(), board: Hand::new(),
            ante: 0, play: 0, stake: 0, selected: 0,
        }
    }

    pub fn enter(&mut self) {
        self.phase = Phase::Bet;
        self.player.clear();
        self.dealer.clear();
        self.board.clear();
        self.round.banner = false;
    }

    fn deal(&mut self, t: &mut Table) {
        let now = t.clock;
        self.ante = self.round.bet();
        self.play = 0;
        self.stake = 2 * self.ante;
        t.bank -= self.stake;
        t.deck.shuffle(&mut t.rng);
        self.player.clear();
        self.dealer.clear();
        self.board.clear();
        add(&mut self.player, t.deck.draw(), now, now);
        add(&mut self.player, t.deck.draw(), now + 300, now + 300);
        add(&mut self.dealer, t.deck.draw(), now + 150, 0);
        add(&mut self.dealer, t.deck.draw(), now + 450, 0);
        for i in 0..5 {
            add(&mut self.board, t.deck.draw(), now + 650 + i * 90, 0);
        }
        self.round.busy_until = now + 650 + 4 * 90 + SLIDE_MS;
        self.phase = Phase::Pre;
        self.selected = 0;
    }

    /// Turns board cards [from, to) face up one after another; returns when the last one lands.
    fn flip(&mut self, from: usize, to: usize, mut at: u32) -> u32 {
        for s in &mut self.board[from..to] {
            if s.show_at == 0 {
                s.show_at = at;
                at += 180;
            }
        }
        at
    }

    fn score(&self, hole: &Hand) -> u32 {
        let mut c = [0u8; 7];
        cards(hole, None, &mut c[..2]);
        cards(&self.board, None, &mut c[2..]);
        best_hand(&c)
    }

    fn showdown(&mut self, mut at: u32, folded: bool) {
        at = self.flip(0, 5, at) + 250;
        self.dealer[0].show_at = at;
        self.dealer[1].show_at = at + 180;
        at += 180 + 500;
        let (ret, msg) = uth_settle(self.ante, self.play, self.score(&self.player), self.score(&self.dealer), folded);
        self.round.show_result(msg, ret, ret - self.stake, at);
        self.phase = Phase::Bet;
    }

    /// Returns true to go back to the menu.
    pub fn update(&mut self, t: &mut Table, ev: u8) -> bool {
        let now = t.clock;
        self.round.pay_when_shown(t);
        if now < self.round.busy_until {
            return false;
        }
        if self.phase == Phase::Bet {
            if ev != 0 {
                self.round.banner = false;
            }
            self.round.bet_input(t, ev, 6);
            if pressed(ev, BACK) {
                return true;
            }
            if pressed(ev, OK) && self.round.can_bet(t, 6) {
                self.deal(t);
            }
            return false;
        }
        if pressed(ev, LEFT) && self.selected > 0 {
            self.selected -= 1;
        }
        if pressed(ev, RIGHT) && self.selected < self.phase.options().len() - 1 {
            self.selected += 1;
        }
        if !pressed(ev, OK) {
            return false;
        }
        let mult = self.phase.mult(self.selected);
        if mult > 0 {
            self.play = self.ante * mult;
            t.bank -= self.play;
            self.stake += self.play;
            self.showdown(now, false);
        } else if self.phase == Phase::River {
            self.showdown(now, true); // fold
        } else if self.phase == Phase::Pre {
            self.round.busy_until = self.flip(0, 3, now);
            self.phase = Phase::Flop;
            self.selected = 0;
        } else {
            self.round.busy_until = self.flip(3, 5, now);
            self.phase = Phase::River;
            self.selected = 0;
        }
        false
    }

    /// Name of the best hand among a hole pair's face-up cards plus the face-up board.
    fn live_hand_name(&self, hole: &Hand, now: u32) -> Option<&'static str> {
        let mut c = [0u8; 7];
        let n = cards(hole, Some(now), &mut c);
        if n < 2 {
            return None;
        }
        let n = n + cards(&self.board, Some(now), &mut c[n..]);
        Some(hand_name(best_hand(&c[..n])))
    }

    pub fn draw(&self, g: &mut Gfx, t: &Table) {
        let now = t.clock;
        header(g, b"HOLD'EM", t.bank);
        if self.player.is_empty() {
            g.text_center(18, b"DEALER NEEDS A PAIR", 1, WHITE, 64);
            g.text_center(30, b"BLIND PAYS STRAIGHT+", 1, WHITE, 64);
        }
        for (i, s) in self.board.iter().enumerate() {
            draw_slot(g, 32 + i as i32 * 13, 9, s, now);
        }
        for (i, s) in self.player.iter().enumerate() {
            draw_slot(g, i as i32 * 13, 28, s, now);
        }
        for (i, s) in self.dealer.iter().enumerate() {
            draw_slot(g, 104 + i as i32 * 13, 28, s, now);
        }
        if !self.player.is_empty() {
            g.text_center(29, fmt(format_args!("A{} B{}", self.ante, self.ante)).as_bytes(), 1, WHITE, 64);
            let play = if self.play > 0 { fmt(format_args!("PLAY {}", self.play)) } else { fmt(format_args!("PLAY -")) };
            g.text_center(38, play.as_bytes(), 1, WHITE, 64);
            if let Some(name) = self.live_hand_name(&self.player, now) {
                g.text(0, 46, name.as_bytes(), 1, WHITE);
            }
            if let Some(name) = self.live_hand_name(&self.dealer, now) {
                g.text_right(127, 46, name.as_bytes(), 1, WHITE);
            }
        }
        if self.phase == Phase::Bet {
            bet_bar(g, "ANTE", self.round.bet(), b"DEAL");
        } else {
            bar(g, self.phase.options(), self.selected);
        }
        if self.round.banner_visible(now) {
            banner(g, 14, self.round.msg.as_bytes(), self.round.net);
        }
    }
}

impl Default for Holdem {
    fn default() -> Self {
        Self::new()
    }
}
