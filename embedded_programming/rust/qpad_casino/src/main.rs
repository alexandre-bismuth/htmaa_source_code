//! QPAD Casino, Rust version: Roulette, Blackjack and Ultimate Texas Hold'em on the QPAD-XIAO.
//! Flash: hold BOOT, tap RESET, then `cargo run --release`.
#![no_std]
#![no_main]

const BENCHMARK: bool = false; // true = boot into the deterministic benchmark (results over USB serial)

mod bench;
mod board;

use casino::casino::{Casino, FRAME_MS};
use casino::gfx::Gfx;
use casino::input::Pads;
use casino::ui::{splash, Led};
use panic_halt as _;
use seeeduino_xiao_rp2040::entry;
use seeeduino_xiao_rp2040::hal::{self, fugit::RateExtU32, gpio::FunctionI2C, pac, Clock};

/// Everything the game loop and the benchmark need from the board.
pub struct Hw<I> {
    pub timer: hal::Timer,
    pub i2c: I,
    pub cpu_hz: u32,
    pub tx: [u8; 1025],
}

impl<I: embedded_hal::i2c::I2c> Hw<I> {
    pub fn push(&mut self, gfx: &Gfx) {
        board::oled_push(&mut self.i2c, &gfx.buf, &mut self.tx);
    }
}

#[entry]
fn main() -> ! {
    let mut pac = pac::Peripherals::take().unwrap();
    let mut watchdog = hal::Watchdog::new(pac.WATCHDOG);
    let clocks = hal::clocks::init_clocks_and_plls(
        seeeduino_xiao_rp2040::XOSC_CRYSTAL_FREQ,
        pac.XOSC,
        pac.CLOCKS,
        pac.PLL_SYS,
        pac.PLL_USB,
        &mut pac.RESETS,
        &mut watchdog,
    )
    .ok()
    .unwrap(); // 125 MHz
    let timer = hal::Timer::new(pac.TIMER, &mut pac.RESETS, &clocks);
    let sio = hal::Sio::new(pac.SIO);
    let pins = hal::gpio::Pins::new(pac.IO_BANK0, pac.PADS_BANK0, sio.gpio_bank0, &mut pac.RESETS);

    // Pads: SIO inputs with pull-ups (board.rs drives them directly); LED pins as outputs, off.
    let _pads = (
        pins.gpio26.into_pull_up_input(),
        pins.gpio2.into_pull_up_input(),
        pins.gpio27.into_pull_up_input(),
        pins.gpio1.into_pull_up_input(),
        pins.gpio4.into_pull_up_input(),
        pins.gpio3.into_pull_up_input(),
    );
    let _leds = (pins.gpio17.into_push_pull_output(), pins.gpio16.into_push_pull_output(), pins.gpio25.into_push_pull_output());
    board::set_led(Led::Off);

    board::usb_start(hal::usb::UsbBus::new(pac.USBCTRL_REGS, pac.USBCTRL_DPRAM, clocks.usb_clock, true, &mut pac.RESETS));

    let sda: hal::gpio::Pin<_, FunctionI2C, _> = pins.gpio6.reconfigure();
    let scl: hal::gpio::Pin<_, FunctionI2C, _> = pins.gpio7.reconfigure();
    let i2c = hal::I2C::i2c1(pac.I2C1, sda, scl, 400.kHz(), &mut pac.RESETS, &clocks.system_clock);
    let mut hw = Hw { timer, i2c, cpu_hz: clocks.system_clock.freq().to_Hz(), tx: [0; 1025] };

    if !board::oled_init(&mut hw.i2c) {
        loop {
            board::usb_write(b"OLED init failed: check the solder joints / I2C address 0x3C\r\n", false);
            board::set_led(Led::Red);
            board::delay_us(&hw.timer, 150_000);
            board::set_led(Led::Off);
            board::delay_us(&hw.timer, 150_000);
        }
    }

    let mut gfx = Gfx::default();
    splash(&mut gfx, 0, 6);
    hw.push(&gfx);
    let boot_frame_ms = board::millis(&hw.timer);

    let mut casino = Casino::new();
    let rosc = hal::rosc::RingOscillator::new(pac.ROSC).initialize();
    casino.table.rng.state = (0..32).fold(0u32, |s, _| s << 1 | rosc.get_random_bit() as u32) | 1;

    let mut pads = Pads::new();
    board::delay_us(&hw.timer, 800_000); // let hands leave the board
    for pad in 0..6 {
        let baseline = (0..32).map(|_| board::measure(&hw.timer, pad)).sum::<i32>() / 32;
        pads.calibrate(pad, baseline);
        if pads.stuck[pad] {
            board::usb_write(board::PAD_NAMES[pad].as_bytes(), false);
            board::usb_write(b" stuck at max: possible short to GND / solder bridge\r\n", false);
        }
        splash(&mut gfx, pad as i32 + 1, 6);
        hw.push(&gfx);
    }

    if BENCHMARK {
        bench::run(&mut hw, &mut casino, &mut gfx, boot_frame_ms);
    }

    let mut last_led = Led::Off;
    loop {
        let start = board::millis(&hw.timer);
        casino.table.clock = start;
        pads.update(&board::measure_all(&hw.timer));
        casino.update(pads.events(start));
        if casino.table.led != last_led {
            last_led = casino.table.led;
            board::set_led(last_led);
        }
        casino.draw(&mut gfx);
        hw.push(&gfx);
        while board::millis(&hw.timer).wrapping_sub(start) < FRAME_MS {}
    }
}
