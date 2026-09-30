//! XIAO RP2040 hardware: pad timing, the SSD1306 over I2C, the RGB LED, USB serial and the microsecond clock.

use core::cell::RefCell;
use core::sync::atomic::{AtomicBool, Ordering};
use critical_section::Mutex;
use embedded_hal::i2c::I2c;
use seeeduino_xiao_rp2040::hal::{self, pac, pac::interrupt, usb::UsbBus};
use usb_device::{class_prelude::UsbBusAllocator, prelude::*};
use usbd_serial::SerialPort;

use casino::input::T_MAX;
use casino::ui::Led;

pub const PAD_GPIO: [u32; 6] = [26, 2, 27, 1, 4, 3]; // D0 D8 D1 D7 D9 D10 = UP DOWN LEFT RIGHT OK BACK
pub const PAD_NAMES: [&str; 6] = ["Q5", "Q2", "Q3", "Q4", "Q1", "Q0"];
const LED_R: u32 = 17; // active LOW
const LED_G: u32 = 16;
const LED_B: u32 = 25;
const OLED: u8 = 0x3C;

#[inline(always)]
fn sio() -> &'static pac::sio::RegisterBlock {
    // SAFETY: the pad and LED pins are only touched from the main thread through these registers.
    unsafe { &*pac::SIO::ptr() }
}

// ---------- Clock ----------
pub fn micros(timer: &hal::Timer) -> u32 {
    timer.get_counter().ticks() as u32
}

pub fn millis(timer: &hal::Timer) -> u32 {
    (timer.get_counter().ticks() / 1000) as u32
}

pub fn delay_us(timer: &hal::Timer, us: u32) {
    let start = micros(timer);
    while micros(timer).wrapping_sub(start) < us {}
}

// ---------- Pads (RC timing, same method as the C++ build) ----------
/// Counts loop turns until the released pad reads high. Runs from RAM so flash cache misses can't add jitter.
#[inline(never)]
#[link_section = ".data.charge_count"]
fn charge_count(mask: u32) -> i32 {
    let sio = sio();
    sio.gpio_oe_clr().write(|w| unsafe { w.bits(mask) }); // release: the pull-up charges the pad
    let mut t = 0;
    while sio.gpio_in().read().bits() & mask == 0 && t < T_MAX {
        t += 1;
    }
    t
}

pub fn measure_once(timer: &hal::Timer, pad: usize) -> i32 {
    let mask = 1 << PAD_GPIO[pad];
    let sio = sio();
    sio.gpio_out_clr().write(|w| unsafe { w.bits(mask) });
    sio.gpio_oe_set().write(|w| unsafe { w.bits(mask) }); // empty the pad
    delay_us(timer, 25);
    let count: fn(u32) -> i32 = core::hint::black_box(charge_count); // call through a pointer: flash -> RAM
    let t = cortex_m::interrupt::free(|_| count(mask));
    sio.gpio_oe_set().write(|w| unsafe { w.bits(mask) }); // discharge again
    t
}

pub fn measure(timer: &hal::Timer, pad: usize) -> i32 {
    (0..casino::input::SAMPLES).map(|_| measure_once(timer, pad)).sum::<i32>() / casino::input::SAMPLES
}

pub fn measure_all(timer: &hal::Timer) -> [i32; 6] {
    core::array::from_fn(|pad| measure(timer, pad))
}

// ---------- RGB LED ----------
pub fn set_led(led: Led) {
    let sio = sio();
    let on = match led {
        Led::Off => 0,
        Led::Green => 1 << LED_G,
        Led::Red => 1 << LED_R,
        Led::Blue => 1 << LED_B,
    };
    let all = 1 << LED_R | 1 << LED_G | 1 << LED_B;
    sio.gpio_out_set().write(|w| unsafe { w.bits(all & !on) });
    sio.gpio_out_clr().write(|w| unsafe { w.bits(on) });
}

// ---------- SSD1306 ----------
/// Same init sequence as Adafruit_SSD1306::begin() for a 128x64 panel with its internal charge pump.
pub fn oled_init(i2c: &mut impl I2c) -> bool {
    const INIT: [u8; 27] = [
        0x00, 0xAE, 0xD5, 0x80, 0xA8, 0x3F, 0xD3, 0x00, 0x40, 0x8D, 0x14, 0x20, 0x00, 0xA1, 0xC8, 0xDA, 0x12, 0x81,
        0xCF, 0xD9, 0xF1, 0xDB, 0x40, 0xA4, 0xA6, 0x2E, 0xAF,
    ];
    i2c.write(OLED, &INIT).is_ok()
}

/// Sends the 1 KB frame: address the whole panel, then one data transfer (0x40 + buffer).
pub fn oled_push(i2c: &mut impl I2c, frame: &[u8; 1024], tx: &mut [u8; 1025]) {
    let _ = i2c.write(OLED, &[0x00, 0x22, 0x00, 0x07, 0x21, 0x00, 0x7F]);
    tx[0] = 0x40;
    tx[1..].copy_from_slice(frame);
    let _ = i2c.write(OLED, tx);
}

// ---------- USB serial (polled from its interrupt) ----------
static USB_DEVICE: Mutex<RefCell<Option<UsbDevice<'static, UsbBus>>>> = Mutex::new(RefCell::new(None));
static USB_SERIAL: Mutex<RefCell<Option<SerialPort<'static, UsbBus>>>> = Mutex::new(RefCell::new(None));
static HOST_SENT: AtomicBool = AtomicBool::new(false);

pub fn usb_start(bus: UsbBus) {
    let bus: &'static UsbBusAllocator<UsbBus> =
        cortex_m::singleton!(: UsbBusAllocator<UsbBus> = UsbBusAllocator::new(bus)).unwrap();
    let serial = SerialPort::new(bus);
    let device = UsbDeviceBuilder::new(bus, UsbVidPid(0x2E8A, 0x000A))
        .strings(&[StringDescriptors::default().manufacturer("HTMAA").product("QPAD Casino").serial_number("RUST")])
        .unwrap()
        .device_class(usbd_serial::USB_CLASS_CDC)
        .build();
    critical_section::with(|cs| {
        USB_DEVICE.borrow(cs).replace(Some(device));
        USB_SERIAL.borrow(cs).replace(Some(serial));
    });
    // SAFETY: the handler only touches the two Mutex-guarded statics above.
    unsafe { pac::NVIC::unmask(pac::Interrupt::USBCTRL_IRQ) };
}

#[interrupt]
fn USBCTRL_IRQ() {
    critical_section::with(|cs| {
        let mut device = USB_DEVICE.borrow_ref_mut(cs);
        let mut serial = USB_SERIAL.borrow_ref_mut(cs);
        if let (Some(device), Some(serial)) = (device.as_mut(), serial.as_mut()) {
            if device.poll(&mut [serial]) {
                let mut buf = [0u8; 64];
                if matches!(serial.read(&mut buf), Ok(n) if n > 0) {
                    HOST_SENT.store(true, Ordering::Relaxed);
                }
            }
        }
    });
}

/// True once a host has the port open (DTR) or has sent a byte.
pub fn host_listening() -> bool {
    HOST_SENT.load(Ordering::Relaxed)
        || critical_section::with(|cs| USB_SERIAL.borrow_ref(cs).as_ref().is_some_and(|s| s.dtr()))
}

/// Writes to USB serial. `wait` blocks until everything is queued (only use it with a host listening).
pub fn usb_write(data: &[u8], wait: bool) {
    let mut sent = 0;
    while sent < data.len() {
        let n = critical_section::with(|cs| match USB_SERIAL.borrow_ref_mut(cs).as_mut() {
            Some(s) => s.write(&data[sent..]).unwrap_or(0),
            None => data.len() - sent,
        });
        sent += n;
        if !wait {
            break;
        }
    }
}
