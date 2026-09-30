//! Deterministic benchmark (set BENCHMARK = true in main.rs): fixed seed, simulated 30 fps clock, scripted input.
//! Results stream as "BENCH {json}" lines; embedded_programming/benchmarks/capture.py saves them.
//! The script, seeds and measured items are identical in every language port.

use core::fmt::Write;
use core::hint::black_box;
use heapless::String;

use crate::board;
use crate::Hw;
use casino::casino::{Casino, FRAME_MS};
use casino::gfx::{Gfx, WHITE};
use casino::rules::{best_hand, bj_total, eval_cards, Deck, Rng};
use casino::script::{crc32, hands, run_script, N_HANDS, REPS, SEED};
use casino::ui::{draw_card, draw_card_back};

const MAX_FRAMES: usize = 2048;
const PAINT: u32 = 0xA5A5_A5A5;

extern "C" {
    static __erodata: u32;
    static __sdata: u32;
    static __edata: u32;
    static __sbss: u32;
    static __ebss: u32;
    static _stack_start: u32;
}

fn addr(sym: &u32) -> u32 {
    sym as *const u32 as u32
}

#[derive(Clone, Copy)]
struct Stat {
    n: u32,
    lo: u32,
    hi: u32,
    sum: u64,
}

impl Stat {
    const fn new() -> Self {
        Stat { n: 0, lo: u32::MAX, hi: 0, sum: 0 }
    }
    fn add(&mut self, v: u32) {
        self.n += 1;
        self.sum += v as u64;
        self.lo = self.lo.min(v);
        self.hi = self.hi.max(v);
    }
    fn avg_ns(&self) -> u64 {
        if self.n == 0 { 0 } else { self.sum * 1000 / self.n as u64 }
    }
}

fn line(sec: &str, name: &str, kv: core::fmt::Arguments) {
    let mut s: String<320> = String::new();
    let _ = write!(s, "BENCH {{\"sec\":\"{}\",\"name\":\"{}\",{}}}\r\n", sec, name, kv);
    board::usb_write(s.as_bytes(), true);
}

fn stat(sec: &str, name: &str, s: &Stat) {
    line(sec, name, format_args!("\"n\":{},\"avg_ns\":{},\"min_us\":{},\"max_us\":{}", s.n, s.avg_ns(), s.lo, s.hi));
}

/// Average of a tight loop, for operations shorter than the 1 us timer.
fn batch(hw: &Hw<impl embedded_hal::i2c::I2c>, sec: &str, name: &str, n: u32, mut work: impl FnMut(u32)) {
    let start = board::micros(&hw.timer);
    for i in 0..n {
        work(i);
    }
    let us = board::micros(&hw.timer).wrapping_sub(start) as u64;
    line(sec, name, format_args!("\"n\":{},\"avg_ns\":{}", n, us * 1000 / n as u64));
}

fn progress<I: embedded_hal::i2c::I2c>(hw: &mut Hw<I>, gfx: &mut Gfx, what: &str) {
    gfx.clear();
    gfx.text_center(10, b"BENCHMARK", 2, WHITE, 64);
    gfx.text_center(34, what.as_bytes(), 1, WHITE, 64);
    hw.push(gfx);
}

fn stack_bottom() -> *mut u32 {
    // flip-link puts the stack below .data (from the start of RAM); otherwise it grows down toward .bss.
    unsafe {
        if addr(&_stack_start) <= addr(&__sdata) { 0x2000_0000 as *mut u32 } else { addr(&__ebss) as *mut u32 }
    }
}

fn paint_stack() {
    let here = cortex_m::register::msp::read() - 256;
    let mut p = stack_bottom();
    while (p as u32) < here {
        unsafe { p.write_volatile(PAINT) };
        p = p.wrapping_add(1);
    }
}

fn stack_used() -> u32 {
    let mut p = stack_bottom();
    let top = unsafe { addr(&_stack_start) };
    while (p as u32) < top && unsafe { p.read_volatile() } == PAINT {
        p = p.wrapping_add(1);
    }
    top - p as u32
}

fn touch<I: embedded_hal::i2c::I2c>(hw: &mut Hw<I>, gfx: &mut Gfx) {
    progress(hw, gfx, "touch");
    for pad in 0..6 {
        let n = 200;
        let (mut sum, mut sq, mut lo, mut hi) = (0i64, 0i64, i32::MAX, 0);
        let start = board::micros(&hw.timer);
        for _ in 0..n {
            let v = board::measure_once(&hw.timer, pad);
            sum += v as i64;
            sq += (v as i64) * (v as i64);
            lo = lo.min(v);
            hi = hi.max(v);
        }
        let us = board::micros(&hw.timer).wrapping_sub(start) as u64;
        let var = (sq * n - sum * sum) as f32 / (n * n) as f32;
        let sd = if var > 0.0 { sqrt(var) } else { 0.0 };
        line(
            "touch",
            board::PAD_NAMES[pad],
            format_args!(
                "\"n\":{},\"avg_ns\":{},\"count_min\":{},\"count_max\":{},\"count_mean_x100\":{},\"count_sd_x100\":{}",
                n, us * 1000 / n as u64, lo, hi, sum * 100 / n, (sd * 100.0) as u32
            ),
        );
    }
    let mut s = Stat::new();
    for _ in 0..100 {
        let start = board::micros(&hw.timer);
        black_box(board::measure_all(&hw.timer));
        s.add(board::micros(&hw.timer).wrapping_sub(start));
    }
    stat("touch", "scan6", &s);
}

/// Newton's method (no libm): only used to report the touch-count spread.
fn sqrt(v: f32) -> f32 {
    let mut x = v.max(1.0);
    for _ in 0..20 {
        x = 0.5 * (x + v / x);
    }
    x
}

fn gfx_bench<I: embedded_hal::i2c::I2c>(hw: &mut Hw<I>, gfx: &mut Gfx) {
    progress(hw, gfx, "graphics");
    let n = 300;
    batch(hw, "gfx", "clear", n, |_| black_box(&mut *gfx).clear());
    batch(hw, "gfx", "fill_screen", n, |_| black_box(&mut *gfx).fill_rect(0, 0, 128, 64, WHITE));
    batch(hw, "gfx", "line", n, |_| black_box(&mut *gfx).line(0, 0, 127, 63, WHITE));
    batch(hw, "gfx", "circle_r16", n, |_| black_box(&mut *gfx).circle(64, 32, 16, WHITE));
    batch(hw, "gfx", "fill_circle_r16", n, |_| black_box(&mut *gfx).fill_circle(64, 32, 16, WHITE));
    batch(hw, "gfx", "fill_round_rect", n, |_| black_box(&mut *gfx).fill_round_rect(10, 10, 40, 30, 4, WHITE));
    batch(hw, "gfx", "fill_triangle", n, |_| black_box(&mut *gfx).fill_triangle(0, 0, 127, 20, 40, 63, WHITE));
    batch(hw, "gfx", "text_21_s1", n, |_| black_box(&mut *gfx).text(0, 0, b"ABCDEFGHIJKLMNOPQRSTU", 1, WHITE));
    batch(hw, "gfx", "text_10_s2", n, |_| black_box(&mut *gfx).text(0, 0, b"ABCDEFGHIJ", 2, WHITE));
    batch(hw, "gfx", "card", n, |i| draw_card(black_box(&mut *gfx), 40, 20, (i % 52) as u8));
    batch(hw, "gfx", "card_back", n, |_| draw_card_back(black_box(&mut *gfx), 40, 20));
}

fn push<I: embedded_hal::i2c::I2c>(hw: &mut Hw<I>, gfx: &mut Gfx) {
    progress(hw, gfx, "display push");
    let mut s = Stat::new();
    for _ in 0..100 {
        let start = board::micros(&hw.timer);
        hw.push(gfx);
        s.add(board::micros(&hw.timer).wrapping_sub(start));
    }
    stat("display", "push", &s);
    line("display", "theory", format_args!("\"i2c_hz\":400000,\"payload_bytes\":1024,\"min_us\":23040"));
}

fn logic<I: embedded_hal::i2c::I2c>(hw: &mut Hw<I>, gfx: &mut Gfx) {
    progress(hw, gfx, "game logic");
    let hs = hands();
    let mut rng = Rng { state: SEED };
    let mut deck = Deck::new();
    let mut sum = 0u32;
    batch(hw, "logic", "shuffle", 2000, |_| {
        deck.shuffle(&mut rng);
        sum = sum.wrapping_add(deck.cards[0] as u32);
    });
    line("logic", "shuffle_check", format_args!("\"checksum\":{}", sum));
    let n = (N_HANDS * REPS) as u32;
    let mut sum = 0u32;
    batch(hw, "logic", "bj_total", n, |i| {
        sum = sum.wrapping_add(bj_total(black_box(&hs[i as usize % N_HANDS][..3])) as u32)
    });
    line("logic", "bj_total_check", format_args!("\"checksum\":{}", sum));
    let mut sum = 0u32;
    batch(hw, "logic", "eval5", n, |i| sum = sum.wrapping_add(eval_cards(black_box(&hs[i as usize % N_HANDS][..5]))));
    line("logic", "eval5_check", format_args!("\"checksum\":{}", sum));
    let mut sum = 0u32;
    batch(hw, "logic", "best7", n, |i| sum = sum.wrapping_add(best_hand(black_box(&hs[i as usize % N_HANDS]))));
    line("logic", "best7_check", format_args!("\"checksum\":{}", sum));
}

/// Full game on the simulated clock, with the real touch scan and display push every frame.
fn playthrough<I: embedded_hal::i2c::I2c>(hw: &mut Hw<I>, casino: &mut Casino, gfx: &mut Gfx) {
    progress(hw, gfx, "playthrough");
    static mut TOTALS: [u32; MAX_FRAMES] = [0; MAX_FRAMES];
    // SAFETY: only this function touches TOTALS, and it never runs concurrently.
    let totals = unsafe { &mut *core::ptr::addr_of_mut!(TOTALS) };
    const SCREENS: [&str; 4] = ["menu", "roulette", "blackjack", "holdem"];
    let (mut input, mut update, mut draw, mut pushes, mut total, mut latency) =
        (Stat::new(), Stat::new(), Stat::new(), Stat::new(), Stat::new(), Stat::new());
    let mut by_screen = [Stat::new(); 4];
    let (mut crc, mut n) = (0u32, 0usize);
    casino.reset(SEED, 1000);
    let frames = run_script(|ev| {
        casino.table.clock += FRAME_MS;
        let t0 = board::micros(&hw.timer);
        black_box(board::measure_all(&hw.timer));
        let t1 = board::micros(&hw.timer);
        casino.update(ev);
        let t2 = board::micros(&hw.timer);
        casino.draw(gfx);
        let t3 = board::micros(&hw.timer);
        hw.push(gfx);
        let t4 = board::micros(&hw.timer);
        crc = crc32(crc, &gfx.buf);
        input.add(t1 - t0);
        update.add(t2 - t1);
        draw.add(t3 - t2);
        pushes.add(t4 - t3);
        total.add(t4 - t0);
        by_screen[casino.screen as usize].add(t3 - t2);
        if ev != 0 {
            latency.add(t4 - t0);
        }
        if n < MAX_FRAMES {
            totals[n] = t4 - t0;
            n += 1;
        }
    });
    totals[..n].sort_unstable();
    stat("frame", "input", &input);
    stat("frame", "update", &update);
    stat("frame", "draw", &draw);
    stat("frame", "push", &pushes);
    stat("frame", "total", &total);
    for (i, s) in by_screen.iter().enumerate() {
        if s.n > 0 {
            stat("draw_screen", SCREENS[i], s);
        }
    }
    line(
        "frame",
        "percentiles",
        format_args!(
            "\"p50_us\":{},\"p99_us\":{},\"unlocked_fps_x100\":{},\"frames\":{}",
            totals[n / 2], totals[n * 99 / 100], 100_000_000u64 * total.n as u64 / total.sum, frames
        ),
    );
    stat("latency", "input_to_display", &latency);
    line(
        "parity",
        "playthrough",
        format_args!("\"bank\":{},\"rng\":{},\"frame_crc32\":{}", casino.table.bank, casino.table.rng.state, crc),
    );
}

/// Leak check: the script twice from the same seed. There is no allocator in this build, so the heap
/// numbers are 0 by construction; frame times and stack depth are still measured.
fn soak<I: embedded_hal::i2c::I2c>(hw: &mut Hw<I>, casino: &mut Casino, gfx: &mut Gfx) {
    progress(hw, gfx, "memory soak");
    let mut frame = Stat::new();
    let mut frames = 0;
    for _ in 0..2 {
        casino.reset(SEED, 1000);
        frames += run_script(|ev| {
            let start = board::micros(&hw.timer);
            casino.table.clock += FRAME_MS;
            casino.update(ev);
            casino.draw(gfx);
            frame.add(board::micros(&hw.timer).wrapping_sub(start));
        });
    }
    line(
        "leaks",
        "soak",
        format_args!(
            "\"frames\":{},\"heap_used_before\":0,\"heap_used_after\":0,\"leaked_bytes\":0,\"frames_with_heap_change\":0,\
             \"max_heap_delta\":0,\"allocator\":\"none\",\"frame_avg_ns\":{},\"frame_max_us\":{}",
            frames, frame.avg_ns(), frame.hi
        ),
    );
    line("leaks", "fragmentation", format_args!("\"free_bytes\":0,\"largest_block_before\":0,\"largest_block_after\":0"));
}

fn memory_static() {
    unsafe {
        let data = addr(&__edata) - addr(&__sdata);
        let bss = addr(&__ebss) - addr(&__sbss);
        let stack = addr(&_stack_start) - stack_bottom() as u32;
        line(
            "memory",
            "static",
            format_args!(
                "\"flash_image_bytes\":{},\"flash_total_bytes\":2097152,\"data_bytes\":{},\"bss_bytes\":{},\
                 \"ram_static_bytes\":{},\"ram_total_bytes\":270336,\"heap_total_bytes\":0,\"stack_bytes\":{}",
                addr(&__erodata) - 0x1000_0000 + data, data, bss, data + bss, stack
            ),
        );
    }
    line("memory", "heap_boot", format_args!("\"used_bytes\":0,\"free_bytes\":0,\"arena_bytes\":0"));
}

pub fn run<I: embedded_hal::i2c::I2c>(hw: &mut Hw<I>, casino: &mut Casino, gfx: &mut Gfx, boot_frame_ms: u32) -> ! {
    let ready_ms = board::millis(&hw.timer);
    progress(hw, gfx, "run capture.py");
    while !board::host_listening() {}
    board::delay_us(&hw.timer, 500_000);
    paint_stack();
    let mut s: String<128> = String::new();
    let _ = write!(s, "BENCH_BEGIN {{\"lang\":\"rust\",\"cpu_hz\":{},\"frame_ms\":{},\"seed\":{}}}\r\n", hw.cpu_hz, FRAME_MS, SEED);
    board::usb_write(s.as_bytes(), true);
    line("boot", "timing", format_args!("\"first_frame_ms\":{},\"ready_ms\":{}", boot_frame_ms, ready_ms));
    memory_static();
    touch(hw, gfx);
    gfx_bench(hw, gfx);
    push(hw, gfx);
    logic(hw, gfx);
    playthrough(hw, casino, gfx);
    soak(hw, casino, gfx);
    let stack = unsafe { addr(&_stack_start) } - stack_bottom() as u32;
    line("memory", "stack", format_args!("\"stack_used_bytes\":{},\"stack_bytes\":{}", stack_used(), stack));
    board::usb_write(b"BENCH_END\r\n", true);
    progress(hw, gfx, "done");
    loop {
        cortex_m::asm::wfi();
    }
}
