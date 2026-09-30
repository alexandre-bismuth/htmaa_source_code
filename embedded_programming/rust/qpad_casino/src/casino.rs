//! The casino: the shared table and the screen currently shown.

use crate::blackjack::Blackjack;
use crate::gfx::Gfx;
use crate::menu::Menu;
use crate::poker::Holdem;
use crate::roulette::Roulette;
use crate::ui::{Led, Table};

pub const FRAME_MS: u32 = 33; // 30 fps

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Screen {
    Menu,
    Roulette,
    Blackjack,
    Holdem,
}

pub struct Casino {
    pub table: Table,
    pub screen: Screen,
    pub menu: Menu,
    pub roulette: Roulette,
    pub blackjack: Blackjack,
    pub holdem: Holdem,
}

impl Casino {
    pub fn new() -> Self {
        Casino {
            table: Table::new(),
            screen: Screen::Menu,
            menu: Menu::new(),
            roulette: Roulette::new(),
            blackjack: Blackjack::new(),
            holdem: Holdem::new(),
        }
    }

    pub fn reset(&mut self, seed: u32, clock: u32) {
        *self = Casino::new();
        self.table.rng.state = seed;
        self.table.clock = clock;
        self.table.flash(Led::Off);
    }

    pub fn update(&mut self, ev: u8) {
        let t = &mut self.table;
        t.led_update();
        let back = match self.screen {
            Screen::Menu => {
                if let Some(game) = self.menu.update(t, ev) {
                    self.screen = [Screen::Roulette, Screen::Blackjack, Screen::Holdem][game];
                    match self.screen {
                        Screen::Roulette => self.roulette.enter(),
                        Screen::Blackjack => self.blackjack.enter(),
                        _ => self.holdem.enter(),
                    }
                }
                false
            }
            Screen::Roulette => self.roulette.update(t, ev),
            Screen::Blackjack => self.blackjack.update(t, ev),
            Screen::Holdem => self.holdem.update(t, ev),
        };
        if back {
            self.screen = Screen::Menu;
        }
    }

    pub fn draw(&self, g: &mut Gfx) {
        g.clear();
        match self.screen {
            Screen::Menu => self.menu.draw(g, &self.table),
            Screen::Roulette => self.roulette.draw(g, &self.table),
            Screen::Blackjack => self.blackjack.draw(g, &self.table),
            Screen::Holdem => self.holdem.draw(g, &self.table),
        }
    }
}

impl Default for Casino {
    fn default() -> Self {
        Self::new()
    }
}
