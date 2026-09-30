//! Adafruit_GFX drawing algorithms on the SSD1306 frame buffer (128x64, 8 rows per byte), pixel-identical
//! to the C++ build. Fast lines use byte masks like Adafruit_SSD1306's drawFastHLine/VLine.

use crate::font::FONT;

pub const W: i32 = 128;
pub const H: i32 = 64;
pub const BLACK: u8 = 0;
pub const WHITE: u8 = 1;

pub struct Gfx {
    pub buf: [u8; 1024],
}

impl Default for Gfx {
    fn default() -> Self {
        Gfx { buf: [0; 1024] }
    }
}

impl Gfx {
    pub fn clear(&mut self) {
        self.buf.fill(0);
    }

    #[inline]
    pub fn pixel(&mut self, x: i32, y: i32, c: u8) {
        if (0..W).contains(&x) && (0..H).contains(&y) {
            let b = &mut self.buf[(x + (y >> 3) * W) as usize];
            if c == WHITE {
                *b |= 1 << (y & 7);
            } else {
                *b &= !(1 << (y & 7));
            }
        }
    }

    pub fn hline(&mut self, mut x: i32, y: i32, mut w: i32, c: u8) {
        if !(0..H).contains(&y) {
            return;
        }
        if x < 0 {
            w += x;
            x = 0;
        }
        w = w.min(W - x);
        if w <= 0 {
            return;
        }
        let bit = 1u8 << (y & 7);
        let row = (y >> 3) * W;
        for b in &mut self.buf[(row + x) as usize..(row + x + w) as usize] {
            if c == WHITE {
                *b |= bit;
            } else {
                *b &= !bit;
            }
        }
    }

    pub fn vline(&mut self, x: i32, mut y: i32, mut h: i32, c: u8) {
        if !(0..W).contains(&x) {
            return;
        }
        if y < 0 {
            h += y;
            y = 0;
        }
        h = h.min(H - y);
        while h > 0 {
            // bits y..y+h within this 8-row page
            let shift = y & 7;
            let n = (8 - shift).min(h);
            let mask = ((0xFFu16 >> (8 - n)) << shift) as u8;
            let b = &mut self.buf[(x + (y >> 3) * W) as usize];
            if c == WHITE {
                *b |= mask;
            } else {
                *b &= !mask;
            }
            y += n;
            h -= n;
        }
    }

    pub fn fill_rect(&mut self, x: i32, y: i32, w: i32, h: i32, c: u8) {
        for i in x..x + w {
            self.vline(i, y, h, c);
        }
    }

    pub fn rect(&mut self, x: i32, y: i32, w: i32, h: i32, c: u8) {
        self.hline(x, y, w, c);
        self.hline(x, y + h - 1, w, c);
        self.vline(x, y, h, c);
        self.vline(x + w - 1, y, h, c);
    }

    pub fn line(&mut self, mut x0: i32, mut y0: i32, mut x1: i32, mut y1: i32, c: u8) {
        if x0 == x1 {
            self.vline(x0, y0.min(y1), (y1 - y0).abs() + 1, c);
            return;
        }
        if y0 == y1 {
            self.hline(x0.min(x1), y0, (x1 - x0).abs() + 1, c);
            return;
        }
        let steep = (y1 - y0).abs() > (x1 - x0).abs();
        if steep {
            core::mem::swap(&mut x0, &mut y0);
            core::mem::swap(&mut x1, &mut y1);
        }
        if x0 > x1 {
            core::mem::swap(&mut x0, &mut x1);
            core::mem::swap(&mut y0, &mut y1);
        }
        let dx = x1 - x0;
        let dy = (y1 - y0).abs();
        let mut err = dx / 2;
        let ystep = if y0 < y1 { 1 } else { -1 };
        while x0 <= x1 {
            if steep {
                self.pixel(y0, x0, c);
            } else {
                self.pixel(x0, y0, c);
            }
            err -= dy;
            if err < 0 {
                y0 += ystep;
                err += dx;
            }
            x0 += 1;
        }
    }

    pub fn circle(&mut self, x0: i32, y0: i32, r: i32, c: u8) {
        let (mut f, mut ddf_x, mut ddf_y, mut x, mut y) = (1 - r, 1, -2 * r, 0, r);
        self.pixel(x0, y0 + r, c);
        self.pixel(x0, y0 - r, c);
        self.pixel(x0 + r, y0, c);
        self.pixel(x0 - r, y0, c);
        while x < y {
            if f >= 0 {
                y -= 1;
                ddf_y += 2;
                f += ddf_y;
            }
            x += 1;
            ddf_x += 2;
            f += ddf_x;
            for (px, py) in [(x, y), (-x, y), (x, -y), (-x, -y), (y, x), (-y, x), (y, -x), (-y, -x)] {
                self.pixel(x0 + px, y0 + py, c);
            }
        }
    }

    pub fn circle_helper(&mut self, x0: i32, y0: i32, r: i32, corner: u8, c: u8) {
        let (mut f, mut ddf_x, mut ddf_y, mut x, mut y) = (1 - r, 1, -2 * r, 0, r);
        while x < y {
            if f >= 0 {
                y -= 1;
                ddf_y += 2;
                f += ddf_y;
            }
            x += 1;
            ddf_x += 2;
            f += ddf_x;
            if corner & 4 != 0 {
                self.pixel(x0 + x, y0 + y, c);
                self.pixel(x0 + y, y0 + x, c);
            }
            if corner & 2 != 0 {
                self.pixel(x0 + x, y0 - y, c);
                self.pixel(x0 + y, y0 - x, c);
            }
            if corner & 8 != 0 {
                self.pixel(x0 - y, y0 + x, c);
                self.pixel(x0 - x, y0 + y, c);
            }
            if corner & 1 != 0 {
                self.pixel(x0 - y, y0 - x, c);
                self.pixel(x0 - x, y0 - y, c);
            }
        }
    }

    pub fn fill_circle_helper(&mut self, x0: i32, y0: i32, r: i32, corners: u8, delta: i32, c: u8) {
        let (mut f, mut ddf_x, mut ddf_y, mut x, mut y) = (1 - r, 1, -2 * r, 0, r);
        let (mut px, mut py) = (x, y);
        let delta = delta + 1;
        while x < y {
            if f >= 0 {
                y -= 1;
                ddf_y += 2;
                f += ddf_y;
            }
            x += 1;
            ddf_x += 2;
            f += ddf_x;
            if x < y + 1 {
                if corners & 1 != 0 {
                    self.vline(x0 + x, y0 - y, 2 * y + delta, c);
                }
                if corners & 2 != 0 {
                    self.vline(x0 - x, y0 - y, 2 * y + delta, c);
                }
            }
            if y != py {
                if corners & 1 != 0 {
                    self.vline(x0 + py, y0 - px, 2 * px + delta, c);
                }
                if corners & 2 != 0 {
                    self.vline(x0 - py, y0 - px, 2 * px + delta, c);
                }
                py = y;
            }
            px = x;
        }
    }

    pub fn fill_circle(&mut self, x0: i32, y0: i32, r: i32, c: u8) {
        self.vline(x0, y0 - r, 2 * r + 1, c);
        self.fill_circle_helper(x0, y0, r, 3, 0, c);
    }

    pub fn round_rect(&mut self, x: i32, y: i32, w: i32, h: i32, r: i32, c: u8) {
        let r = r.min(w.min(h) / 2);
        self.hline(x + r, y, w - 2 * r, c);
        self.hline(x + r, y + h - 1, w - 2 * r, c);
        self.vline(x, y + r, h - 2 * r, c);
        self.vline(x + w - 1, y + r, h - 2 * r, c);
        self.circle_helper(x + r, y + r, r, 1, c);
        self.circle_helper(x + w - r - 1, y + r, r, 2, c);
        self.circle_helper(x + w - r - 1, y + h - r - 1, r, 4, c);
        self.circle_helper(x + r, y + h - r - 1, r, 8, c);
    }

    pub fn fill_round_rect(&mut self, x: i32, y: i32, w: i32, h: i32, r: i32, c: u8) {
        let r = r.min(w.min(h) / 2);
        self.fill_rect(x + r, y, w - 2 * r, h, c);
        self.fill_circle_helper(x + w - r - 1, y + r, r, 1, h - 2 * r - 1, c);
        self.fill_circle_helper(x + r, y + r, r, 2, h - 2 * r - 1, c);
    }

    /// Adafruit's scanline triangle (integer division truncates toward zero, as in C).
    #[allow(clippy::too_many_arguments)] // same signature as Adafruit_GFX::fillTriangle
    pub fn fill_triangle(&mut self, mut x0: i32, mut y0: i32, mut x1: i32, mut y1: i32, mut x2: i32, mut y2: i32, c: u8) {
        if y0 > y1 {
            core::mem::swap(&mut y0, &mut y1);
            core::mem::swap(&mut x0, &mut x1);
        }
        if y1 > y2 {
            core::mem::swap(&mut y2, &mut y1);
            core::mem::swap(&mut x2, &mut x1);
        }
        if y0 > y1 {
            core::mem::swap(&mut y0, &mut y1);
            core::mem::swap(&mut x0, &mut x1);
        }
        if y0 == y2 {
            let a = x0.min(x1).min(x2);
            self.hline(a, y0, x0.max(x1).max(x2) - a + 1, c);
            return;
        }
        let last = if y1 == y2 { y1 } else { y1 - 1 };
        let mut y = y0;
        while y <= last {
            let a = x0 + (x1 - x0) * (y - y0) / (y1 - y0);
            let b = x0 + (x2 - x0) * (y - y0) / (y2 - y0);
            self.hline(a.min(b), y, (b - a).abs() + 1, c);
            y += 1;
        }
        while y <= y2 {
            let a = x1 + (x2 - x1) * (y - y1) / (y2 - y1);
            let b = x0 + (x2 - x0) * (y - y0) / (y2 - y0);
            self.hline(a.min(b), y, (b - a).abs() + 1, c);
            y += 1;
        }
    }

    // ---------- Text: Adafruit classic font, transparent background ----------
    pub fn char(&mut self, x: i32, y: i32, code: u8, c: u8, size: i32) {
        if x >= W || y >= H || x + 6 * size - 1 < 0 || y + 8 * size - 1 < 0 {
            return;
        }
        for i in 0..5 {
            let column = FONT[code as usize * 5 + i as usize];
            for j in 0..8 {
                if column >> j & 1 == 1 {
                    if size == 1 {
                        self.pixel(x + i, y + j, c);
                    } else {
                        self.fill_rect(x + i * size, y + j * size, size, size, c);
                    }
                }
            }
        }
    }

    pub fn text(&mut self, mut x: i32, y: i32, s: &[u8], size: i32, c: u8) {
        for &code in s {
            self.char(x, y, code, c, size);
            x += 6 * size;
        }
    }

    pub fn text_center(&mut self, y: i32, s: &[u8], size: i32, c: u8, cx: i32) {
        self.text(cx - text_width(s, size) / 2, y, s, size, c);
    }

    pub fn text_right(&mut self, x: i32, y: i32, s: &[u8], size: i32, c: u8) {
        self.text(x - text_width(s, size) + 1, y, s, size, c);
    }
}

pub fn text_width(s: &[u8], size: i32) -> i32 {
    s.len() as i32 * 6 * size - size
}
