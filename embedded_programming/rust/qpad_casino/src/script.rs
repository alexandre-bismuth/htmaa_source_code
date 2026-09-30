//! The deterministic benchmark's input script and helpers (identical in every language port).

use crate::rules::{Deck, Rng};
use crate::ui::{BACK, LEFT, OK, RIGHT, UP};

pub const SEED: u32 = 0xC0FFEE;
pub const HAND_SEED: u32 = 12345;
pub const N_HANDS: usize = 250;
pub const REPS: usize = 40;
pub const TAIL_FRAMES: u32 = 60;

/// (frames since the previous step, button)
pub const SCRIPT: &[(u32, u8)] = &[
    (20, RIGHT), (12, RIGHT), (12, RIGHT), (12, OK),            // carousel once around, enter roulette
    (10, RIGHT), (4, UP), (4, UP), (6, OK),                     // 50 on BLACK, spin
    (160, LEFT), (4, LEFT), (4, LEFT), (6, OK),                 // straight No.35, spin
    (160, BACK), (12, RIGHT), (12, OK),                         // -> blackjack
    (10, OK), (45, OK), (20, RIGHT), (4, OK),                   // deal, hit, stand
    (110, OK), (45, RIGHT), (4, RIGHT), (4, OK),                // deal, double
    (110, OK), (45, RIGHT), (4, OK),                            // deal, stand
    (110, BACK), (12, RIGHT), (12, OK),                         // -> hold'em
    (10, OK), (45, OK), (25, OK), (25, RIGHT), (4, OK),         // deal, check, check, bet 1x
    (120, OK), (45, RIGHT), (4, RIGHT), (4, OK),                // deal, bet 4x
    (120, OK), (45, OK), (25, OK), (25, OK),                    // deal, check, check, fold
    (120, BACK),
];

/// Plays SCRIPT plus a short tail; `frame(events)` does one frame's work. Returns the frame count.
pub fn run_script(mut frame: impl FnMut(u8)) -> u32 {
    let (mut frames, mut step, mut tail) = (0u32, 0usize, 0u32);
    let mut next_at = SCRIPT[0].0;
    while step < SCRIPT.len() || tail < TAIL_FRAMES {
        if step >= SCRIPT.len() {
            tail += 1;
        }
        let mut ev = 0;
        if step < SCRIPT.len() && frames == next_at {
            ev = 1 << SCRIPT[step].1;
            step += 1;
            if step < SCRIPT.len() {
                next_at = frames + SCRIPT[step].0;
            }
        }
        frame(ev);
        frames += 1;
    }
    frames
}

/// The seeded hands every port evaluates in the logic benchmark.
pub fn hands() -> [[u8; 7]; N_HANDS] {
    let mut rng = Rng { state: HAND_SEED };
    let mut deck = Deck::new();
    let mut out = [[0u8; 7]; N_HANDS];
    for h in out.iter_mut() {
        deck.shuffle(&mut rng);
        h.copy_from_slice(&deck.cards[..7]);
    }
    out
}

/// zlib-compatible CRC-32, chainable: crc32(crc32(0, a), b) == crc32(0, a ++ b).
pub fn crc32(crc: u32, data: &[u8]) -> u32 {
    let mut c = !crc;
    for &b in data {
        c ^= b as u32;
        for _ in 0..8 {
            c = c >> 1 ^ (0xEDB8_8320 & (c & 1).wrapping_neg());
        }
    }
    !c
}
