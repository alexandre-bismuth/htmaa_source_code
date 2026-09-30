//! Pad readings -> button events: hysteresis, press edges and hold-to-repeat (the timing itself is in main.rs).

use crate::ui::RIGHT;

pub const T_MAX: i32 = 3000; // loop-count ceiling of one reading
pub const SAMPLES: i32 = 8;
const REPEAT_DELAY: u32 = 400; // hold-to-repeat on the 4 left pads
const REPEAT_RATE: u32 = 110;

pub struct Pads {
    pub baseline: [i32; 6],
    pub threshold: [i32; 6],
    pub stuck: [bool; 6],
    pub down: [bool; 6],
    was_down: [bool; 6],
    down_at: [u32; 6],
    repeat_at: [u32; 6],
}

#[allow(clippy::needless_range_loop)] // pads are addressed by index across several arrays
impl Pads {
    pub const fn new() -> Self {
        Pads {
            baseline: [0; 6],
            threshold: [0; 6],
            stuck: [false; 6],
            down: [false; 6],
            was_down: [false; 6],
            down_at: [0; 6],
            repeat_at: [0; 6],
        }
    }

    pub fn calibrate(&mut self, pad: usize, baseline: i32) {
        self.baseline[pad] = baseline;
        self.threshold[pad] = baseline + baseline.max(10);
        self.stuck[pad] = baseline >= T_MAX - 1;
    }

    /// Hysteresis: press above threshold, release below the midpoint to baseline.
    pub fn update(&mut self, values: &[i32; 6]) {
        for pad in 0..6 {
            let off = (self.baseline[pad] + self.threshold[pad]) / 2;
            let limit = if self.down[pad] { off } else { self.threshold[pad] };
            self.down[pad] = !self.stuck[pad] && values[pad] > limit;
        }
    }

    /// Bitmask of new presses, with auto-repeat on the navigation pads.
    pub fn events(&mut self, now: u32) -> u8 {
        let mut ev = 0;
        for pad in 0..6 {
            if self.down[pad] && !self.was_down[pad] {
                ev |= 1 << pad;
                self.down_at[pad] = now;
                self.repeat_at[pad] = now;
            } else if self.down[pad]
                && pad <= RIGHT as usize
                && now - self.down_at[pad] > REPEAT_DELAY
                && now - self.repeat_at[pad] > REPEAT_RATE
            {
                ev |= 1 << pad;
                self.repeat_at[pad] = now;
            }
            self.was_down[pad] = self.down[pad];
        }
        ev
    }
}

impl Default for Pads {
    fn default() -> Self {
        Self::new()
    }
}
