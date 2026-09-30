//! Blackjack: fresh deck every hand, dealer stands on 17, blackjack pays 3:2.

use crate::gfx::{Gfx, WHITE};
use crate::rules::{bj_settle, bj_total};
use crate::ui::{add, banner, bar, bet_bar, cards, draw_hand, fmt, header, pressed, Hand, Round, Table, BACK, LEFT, OK,
                RIGHT, SLIDE_MS};

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Phase {
    Bet,
    Check,
    Play,
}

const OPTIONS: [&[u8]; 3] = [b"HIT", b"STAND", b"DOUBLE"];

pub struct Blackjack {
    pub round: Round,
    pub phase: Phase,
    pub player: Hand,
    pub dealer: Hand,
    bet: i32,   // doubles on DOUBLE
    stake: i32, // total chips put in this hand
    selected: usize,
}

fn total(hand: &Hand) -> i32 {
    let mut c = [0u8; 12];
    let n = cards(hand, None, &mut c);
    bj_total(&c[..n])
}

impl Blackjack {
    pub fn new() -> Self {
        Blackjack { round: Round::new(), phase: Phase::Bet, player: Hand::new(), dealer: Hand::new(), bet: 0, stake: 0, selected: 0 }
    }

    pub fn enter(&mut self) {
        self.phase = Phase::Bet;
        self.player.clear();
        self.dealer.clear();
        self.round.banner = false;
    }

    fn options(&self, t: &Table) -> usize {
        if self.player.len() == 2 && t.bank >= self.bet { 3 } else { 2 }
    }

    fn deal(&mut self, t: &mut Table) {
        let now = t.clock;
        self.bet = self.round.bet();
        self.stake = self.bet;
        t.bank -= self.bet;
        t.deck.shuffle(&mut t.rng);
        self.player.clear();
        self.dealer.clear();
        add(&mut self.player, t.deck.draw(), now, now);
        add(&mut self.dealer, t.deck.draw(), now + 250, now + 250);
        add(&mut self.player, t.deck.draw(), now + 500, now + 500);
        add(&mut self.dealer, t.deck.draw(), now + 750, 0); // hole card
        self.round.busy_until = now + 750 + SLIDE_MS;
        self.phase = Phase::Check;
        self.selected = 0;
    }

    /// Reveals the hole card, lets the dealer draw to 17 and settles the hand.
    fn finish(&mut self, t: &mut Table, mut at: u32) {
        self.dealer[1].show_at = at;
        at += 450;
        let p = total(&self.player);
        let natural = p == 21 && self.player.len() == 2;
        if p <= 21 && !natural {
            while total(&self.dealer) < 17 {
                add(&mut self.dealer, t.deck.draw(), at, at);
                at += 550;
            }
        }
        let (ret, msg) = bj_settle(self.bet, p, self.player.len(), total(&self.dealer), self.dealer.len());
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
        match self.phase {
            Phase::Bet => {
                if ev != 0 {
                    self.round.banner = false;
                }
                self.round.bet_input(t, ev, 1);
                if pressed(ev, BACK) {
                    return true;
                }
                if pressed(ev, OK) && self.round.can_bet(t, 1) {
                    self.deal(t);
                }
            }
            Phase::Check => {
                // naturals end the hand at once
                if total(&self.player) == 21 || total(&self.dealer) == 21 {
                    self.finish(t, now);
                } else {
                    self.phase = Phase::Play;
                }
            }
            Phase::Play => {
                if pressed(ev, LEFT) && self.selected > 0 {
                    self.selected -= 1;
                }
                if pressed(ev, RIGHT) && self.selected < self.options(t) - 1 {
                    self.selected += 1;
                }
                if !pressed(ev, OK) {
                    return false;
                }
                if self.selected == 1 {
                    self.finish(t, now); // STAND
                    return false;
                }
                if self.selected == 2 {
                    // DOUBLE
                    t.bank -= self.bet;
                    self.stake += self.bet;
                    self.bet *= 2;
                }
                add(&mut self.player, t.deck.draw(), now, now); // HIT or DOUBLE
                self.round.busy_until = now + SLIDE_MS;
                if self.selected == 2 || total(&self.player) >= 21 {
                    self.finish(t, now + SLIDE_MS + 200);
                }
                self.selected = self.selected.min(self.options(t) - 1);
            }
        }
        false
    }

    fn draw_total(g: &mut Gfx, hand: &Hand, y: i32, now: u32) {
        let mut c = [0u8; 12];
        let n = cards(hand, Some(now), &mut c);
        if n > 0 {
            g.text_right(127, y, fmt(format_args!("{}", bj_total(&c[..n]))).as_bytes(), 2, WHITE);
        }
    }

    pub fn draw(&self, g: &mut Gfx, t: &Table) {
        let now = t.clock;
        header(g, b"BLACKJACK", t.bank);
        if self.player.is_empty() {
            g.text_center(20, b"BLACKJACK PAYS 3 TO 2", 1, WHITE, 64);
            g.text_center(32, b"DEALER STANDS ON 17", 1, WHITE, 64);
        }
        draw_hand(g, &self.dealer, 12, now);
        draw_hand(g, &self.player, 34, now);
        Self::draw_total(g, &self.dealer, 13, now);
        Self::draw_total(g, &self.player, 35, now);
        match self.phase {
            Phase::Play => bar(g, &OPTIONS[..self.options(t)], self.selected),
            Phase::Bet => bet_bar(g, "BET", self.round.bet(), b"DEAL"),
            Phase::Check => {}
        }
        if self.round.banner_visible(now) {
            banner(g, 16, self.round.msg.as_bytes(), self.round.net);
        }
    }
}

impl Default for Blackjack {
    fn default() -> Self {
        Self::new()
    }
}
