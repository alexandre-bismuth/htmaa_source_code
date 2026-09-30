//! QPAD Casino game library: rules, drawing and screens, free of any hardware so it runs on the computer too.
#![no_std]

pub mod blackjack;
pub mod casino;
pub mod font;
pub mod gfx;
pub mod input;
pub mod menu;
pub mod poker;
pub mod roulette;
pub mod rules;
pub mod script;
pub mod ui;

#[cfg(test)]
mod test_vectors;
#[cfg(test)]
mod tests;
