//! Host tests: rules against the shared JS vectors, hand-written cases, game flows, touch logic, and bit-exact
//! parity of the benchmark playthrough with the C++ reference (benchmarks/reference.json).
extern crate std;

use crate::casino::{Casino, Screen, FRAME_MS};
use crate::gfx::Gfx;
use crate::input::Pads;
use crate::rules::*;
use crate::script::{crc32, hands, run_script, N_HANDS, REPS, SEED};
use crate::test_vectors::{SEED as VEC_SEED, VECTORS};
use crate::ui::{BACK, DOWN, LEFT, OK, RIGHT, UP};
use std::string::String;
use std::vec::Vec;

fn card(s: &str) -> u8 {
    let b = s.as_bytes();
    let rank = b"23456789TJQKA".iter().position(|&c| c == b[0]).unwrap();
    let suit = b"HDCS".iter().position(|&c| c == b[1]).unwrap();
    (rank + 13 * suit) as u8
}

fn hand(names: &[&str]) -> u32 {
    let cards: Vec<u8> = names.iter().map(|n| card(n)).collect();
    best_hand(&cards)
}

#[test]
fn rules_match_js_reference_vectors() {
    let mut rng = Rng { state: VEC_SEED };
    let mut deck = Deck::new();
    for (cards, bj3, eval5, best7) in VECTORS.iter() {
        deck.shuffle(&mut rng);
        assert_eq!(&deck.cards[..7], cards);
        assert_eq!(bj_total(&cards[..3]), *bj3);
        assert_eq!(eval_cards(&cards[..5]), *eval5);
        assert_eq!(best_hand(cards), *best7);
    }
}

#[test]
fn hand_names_and_ordering() {
    let names = [
        (&["AS", "KS", "QS", "JS", "TS", "2H", "3D"][..], "ROYAL"),
        (&["9S", "KS", "QS", "JS", "TS"][..], "STR FLUSH"),
        (&["9S", "9H", "9D", "9C", "TS"][..], "QUADS"),
        (&["9S", "9H", "9D", "4C", "4S"][..], "FULL HOUSE"),
        (&["2S", "7S", "9S", "JS", "KS"][..], "FLUSH"),
        (&["AS", "2H", "3D", "4C", "5S"][..], "STRAIGHT"),
        (&["9S", "9H", "9D", "4C", "5S"][..], "TRIPS"),
        (&["9S", "9H", "4D", "4C", "5S"][..], "TWO PAIR"),
        (&["9S", "9H", "4D", "3C", "5S"][..], "PAIR"),
        (&["9S", "JH", "4D", "3C", "5S"][..], "HIGH CARD"),
    ];
    for (cards, name) in names {
        assert_eq!(hand_name(hand(cards)), name);
    }
    assert!(hand(&["AS", "2H", "3D", "4C", "5S"]) < hand(&["2S", "3H", "4D", "5C", "6S"]), "wheel is lowest");
    assert!(hand(&["TS", "JH", "QD", "KC", "AS"]) > hand(&["9S", "TH", "JD", "QC", "KS"]));
    assert!(hand(&["2S", "7S", "9S", "JS", "KS"]) > hand(&["TS", "JH", "QD", "KC", "AS"]), "flush > straight");
    assert!(hand(&["2S", "2H", "2D", "3C", "3S"]) > hand(&["AS", "7S", "9S", "JS", "KS"]), "full house > flush");
    assert!(hand(&["KS", "KH", "4D", "4C", "5S"]) > hand(&["QS", "QH", "JD", "JC", "AS"]));
    assert!(hand(&["KS", "KH", "4D", "4C", "6S"]) > hand(&["KD", "KC", "4H", "4S", "5S"]), "kicker");
    assert_eq!(hand(&["AS", "AH", "9D", "3C", "2S"]), hand(&["AD", "AC", "9H", "3S", "2D"]));
    assert_eq!(hand(&["AS", "KS", "2H", "2D", "7C", "7H", "9S"]), hand(&["AS", "7C", "7H", "2H", "2D"]));
}

#[test]
fn blackjack_totals_and_payouts() {
    let total = |names: &[&str]| bj_total(&names.iter().map(|n| card(n)).collect::<Vec<_>>());
    assert_eq!(total(&["AS", "6H"]), 17);
    assert_eq!(total(&["AS", "6H", "TD"]), 17);
    assert_eq!(total(&["AS", "AH"]), 12);
    assert_eq!(total(&["AS", "AH", "9D"]), 21);
    assert_eq!(total(&["TS", "TH", "5D"]), 25);
    assert_eq!(total(&["KS", "QH"]), 20);
    assert_eq!(bj_settle(10, 21, 2, 21, 2), (10, "PUSH"));
    assert_eq!(bj_settle(10, 21, 2, 20, 3), (25, "BLACKJACK!"));
    assert_eq!(bj_settle(5, 21, 2, 18, 2), (12, "BLACKJACK!"));
    assert_eq!(bj_settle(10, 21, 3, 21, 2), (0, "DEALER BLACKJACK"));
    assert_eq!(bj_settle(10, 22, 3, 17, 2), (0, "BUST"));
    assert_eq!(bj_settle(20, 18, 2, 23, 3), (40, "DEALER BUSTS"));
    assert_eq!(bj_settle(10, 20, 2, 19, 2), (20, "YOU WIN"));
    assert_eq!(bj_settle(10, 18, 2, 19, 2), (0, "DEALER WINS"));
    assert_eq!(bj_settle(10, 19, 3, 19, 2), (10, "PUSH"));
}

#[test]
fn holdem_payouts() {
    let pair = hand(&["9S", "9H", "4D", "3C", "5S"]);
    let high = hand(&["9S", "JH", "4D", "3C", "5S"]);
    let flush = hand(&["2S", "7S", "9S", "JS", "KS"]);
    let straight = hand(&["AS", "2H", "3D", "4C", "5S"]);
    let royal = hand(&["AS", "KS", "QS", "JS", "TS"]);
    let two_pair = hand(&["9S", "9H", "4D", "4C", "5S"]);
    let low = hand(&["2S", "4H", "6D", "8C", "9S"]);
    assert_eq!(uth_settle(10, 0, two_pair, pair, true), (0, "FOLDED"));
    assert_eq!(uth_settle(10, 40, two_pair, pair, false), (110, "YOU WIN"));
    assert_eq!(uth_settle(10, 40, flush, pair, false), (125, "YOU WIN"));
    assert_eq!(uth_settle(10, 40, straight, high, false), (110, "DEALER NO PAIR"));
    assert_eq!(uth_settle(10, 40, royal, pair, false), (5110, "YOU WIN"));
    assert_eq!(uth_settle(10, 40, pair, two_pair, false), (0, "DEALER WINS"));
    assert_eq!(uth_settle(10, 40, low, high, false), (10, "DEALER WINS"));
    assert_eq!(uth_settle(10, 40, pair, pair, false), (60, "PUSH"));
}

#[test]
fn roulette_rules() {
    let reds = [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36];
    for n in 0..37 {
        assert_eq!(is_red(n), reds.contains(&n), "{}", n);
    }
    for b in 0..9 {
        assert!(!bet_wins(b, 0), "zero loses outside bet {}", b);
    }
    assert!(bet_wins(9, 0) && bet_pays(9) == 35);
    assert!(bet_wins(6, 12) && !bet_wins(6, 13) && bet_wins(7, 13) && bet_wins(8, 36));
    assert!(bet_wins(3, 35) && bet_wins(2, 36) && bet_wins(4, 18) && bet_wins(5, 19));
    let mut sorted = WHEEL;
    sorted.sort();
    assert!(sorted.iter().enumerate().all(|(i, &n)| i == n as usize), "every pocket once");
    for (i, &n) in WHEEL.iter().enumerate() {
        assert_eq!(wheel_index(n as i32), i as i32);
    }
}

// ---------- Game flows ----------
struct Sim {
    casino: Casino,
    gfx: Gfx,
}

impl Sim {
    fn new(seed: u32) -> Self {
        let mut casino = Casino::new();
        casino.reset(seed, 1000);
        Sim { casino, gfx: Gfx::default() }
    }
    fn step(&mut self, ev: u8, frames: u32) {
        let mut ev = ev;
        for _ in 0..frames.max(1) {
            self.casino.table.clock += FRAME_MS;
            self.casino.update(ev);
            self.casino.draw(&mut self.gfx);
            ev = 0;
        }
    }
    fn press(&mut self, button: u8, wait: u32) {
        self.step(1 << button, 1);
        if wait > 0 {
            self.step(0, wait);
        }
    }
}

#[test]
fn menu_navigation() {
    let mut s = Sim::new(1);
    s.press(RIGHT, 10);
    assert_eq!(s.casino.menu.selected, 1);
    s.press(LEFT, 10);
    s.press(UP, 10);
    assert_eq!(s.casino.menu.selected, 2, "wraps around");
    s.press(DOWN, 10);
    s.press(OK, 5);
    assert_eq!(s.casino.screen, Screen::Roulette);
    s.press(BACK, 5);
    assert_eq!(s.casino.screen, Screen::Menu);
}

#[test]
fn house_loan_and_ante_cap() {
    let mut s = Sim::new(1);
    s.casino.table.bank = 0;
    s.press(RIGHT, 10);
    s.press(OK, 5);
    s.press(OK, 5);
    assert_eq!(s.casino.table.bank, 1000);
    assert_eq!(s.casino.blackjack.round.msg.as_str(), "HOUSE LOAN");
    assert_eq!(s.casino.blackjack.phase, crate::blackjack::Phase::Bet, "a loan doesn't deal");

    let mut s = Sim::new(1);
    s.casino.table.bank = 100;
    s.press(RIGHT, 10);
    s.press(RIGHT, 10);
    s.press(OK, 5);
    for _ in 0..5 {
        s.press(UP, 2);
    }
    assert_eq!(s.casino.holdem.round.bet_idx, 1, "ante capped at 10 with a bank of 100");
}

#[test]
fn roulette_straight_win_pays_35_to_1() {
    for seed in 1..40 {
        let mut s = Sim::new(seed);
        let n = Rng { state: seed }.below(37) as i32;
        s.press(OK, 5); // the menu starts on roulette
        s.casino.roulette.bet = 9 + n;
        let bank0 = s.casino.table.bank;
        s.press(OK, 200);
        assert_eq!(s.casino.table.bank, bank0 + 10 * 35, "seed {}", seed);
        assert_eq!(s.casino.roulette.spin_to % 37, wheel_index(n), "strip stops on the winning pocket");
    }
}

#[test]
fn blackjack_bank_matches_banner() {
    for seed in 1..60 {
        let mut s = Sim::new(seed);
        s.press(RIGHT, 10);
        s.press(OK, 5);
        let bank0 = s.casino.table.bank;
        s.press(OK, 40); // deal
        if s.casino.blackjack.phase == crate::blackjack::Phase::Play {
            s.press(RIGHT, 2);
            s.press(RIGHT, 2); // DOUBLE when allowed, else STAND
            s.press(OK, 0);
        }
        s.step(0, 200);
        let r = &s.casino.blackjack.round;
        assert_eq!(r.payout, -1, "payout applied (seed {})", seed);
        assert_eq!(s.casino.table.bank - bank0, r.net, "seed {}", seed);
        assert!([-20, -10, 0, 10, 15, 20].contains(&r.net), "result {} (seed {})", r.net, seed);
    }
}

#[test]
fn holdem_fold_and_back_ignored_mid_hand() {
    let mut s = Sim::new(3);
    s.press(RIGHT, 10);
    s.press(RIGHT, 10);
    s.press(OK, 5);
    s.press(OK, 50);
    s.press(BACK, 2);
    assert_eq!(s.casino.screen, Screen::Holdem, "BACK ignored during a hand");
    s.press(OK, 30);
    s.press(OK, 30);
    let bank0 = s.casino.table.bank;
    s.press(OK, 0); // FOLD is selected on the river
    s.step(0, 200);
    let r = &s.casino.holdem.round;
    assert_eq!((r.msg.as_str(), s.casino.table.bank, r.net), ("FOLDED", bank0, -20));
}

#[test]
fn touch_edges_hysteresis_repeat() {
    let mut p = Pads::new();
    for pad in 0..6 {
        p.calibrate(pad, 10);
    }
    let mut v = [0i32; 6];
    let read = |p: &mut Pads, v: &[i32; 6], now| {
        p.update(v);
        p.events(now)
    };
    assert_eq!(read(&mut p, &v, 0), 0);
    v[UP as usize] = 30;
    assert_eq!(read(&mut p, &v, 0), 1 << UP, "press edge");
    assert_eq!(read(&mut p, &v, 100), 0, "no repeat before 400 ms");
    v[UP as usize] = 16;
    assert_eq!(read(&mut p, &v, 200), 0);
    assert!(p.down[UP as usize], "hysteresis holds above the midpoint");
    assert_eq!(read(&mut p, &v, 450), 1 << UP, "auto-repeat after 400 ms");
    assert_eq!(read(&mut p, &v, 500), 0, "repeat rate 110 ms");
    assert_eq!(read(&mut p, &v, 570), 1 << UP);
    v[UP as usize] = 14;
    assert_eq!(read(&mut p, &v, 600), 0);
    assert!(!p.down[UP as usize], "release below the midpoint");
    v[OK as usize] = 30;
    assert_eq!(read(&mut p, &v, 700), 1 << OK);
    assert_eq!(read(&mut p, &v, 1500), 0, "OK never repeats");
    v[OK as usize] = 0;
    p.calibrate(LEFT as usize, 5000);
    v[LEFT as usize] = 9999;
    assert_eq!(read(&mut p, &v, 1600), 0, "stuck pad ignored");
}

// ---------- Parity with the C++ reference ----------
fn reference(key: &str) -> u64 {
    let text = std::fs::read_to_string(concat!(env!("CARGO_MANIFEST_DIR"), "/../../benchmarks/reference.json")).unwrap();
    let at = text.find(&std::format!("\"{}\":", key)).unwrap() + key.len() + 3;
    let digits: String = text[at..].trim_start().chars().take_while(|c| c.is_ascii_digit()).collect();
    digits.parse().unwrap()
}

#[test]
fn logic_checksums_match_cpp() {
    let hs = hands();
    let mut rng = Rng { state: SEED };
    let mut deck = Deck::new();
    let mut sum = 0u32;
    for _ in 0..2000 {
        deck.shuffle(&mut rng);
        sum = sum.wrapping_add(deck.cards[0] as u32);
    }
    assert_eq!(sum as u64, reference("shuffle_check"));
    let (mut bj, mut e5, mut b7) = (0u32, 0u32, 0u32);
    for i in 0..N_HANDS * REPS {
        let h = &hs[i % N_HANDS];
        bj = bj.wrapping_add(bj_total(&h[..3]) as u32);
        e5 = e5.wrapping_add(eval_cards(&h[..5]));
        b7 = b7.wrapping_add(best_hand(h));
    }
    assert_eq!(bj as u64, reference("bj_total_check"));
    assert_eq!(e5 as u64, reference("eval5_check"));
    assert_eq!(b7 as u64, reference("best7_check"));
}

#[test]
fn playthrough_is_bit_identical_to_cpp() {
    let mut casino = Casino::new();
    let mut gfx = Gfx::default();
    casino.reset(SEED, 1000);
    let mut crc = 0u32;
    let mut frames_bin = Vec::new();
    let frames = run_script(|ev| {
        casino.table.clock += FRAME_MS;
        casino.update(ev);
        casino.draw(&mut gfx);
        crc = crc32(crc, &gfx.buf);
        frames_bin.extend_from_slice(&gfx.buf);
    });
    if let Ok(dir) = std::env::var("QPAD_FRAMES_DIR") {
        std::fs::write(std::format!("{}/frames.bin", dir), &frames_bin).unwrap();
    }
    assert_eq!(frames as u64, reference("frames"));
    assert_eq!(casino.table.bank as u64, reference("bank"));
    assert_eq!(casino.table.rng.state as u64, reference("rng"));
    assert_eq!(crc as u64, reference("frame_crc32"), "every frame bit-identical to C++");
}

/// Host-proxy benchmark (Mac, not the RP2040): `cargo test --release --lib -- --ignored --nocapture host_proxy`.
#[test]
#[ignore]
fn host_proxy_benchmark() {
    use std::time::Instant;
    fn batch(name: &str, n: u32, mut work: impl FnMut(u32)) {
        let start = Instant::now();
        for i in 0..n {
            work(i);
        }
        std::println!("BENCH {{\"sec\":\"{}\",\"name\":\"{}\",\"n\":{},\"avg_ns\":{}}}",
            if name.starts_with("logic_") { "logic" } else { "gfx" }, name.trim_start_matches("logic_"), n,
            start.elapsed().as_nanos() as u64 / n as u64);
    }
    let mut g = Gfx::default();
    let n = 300;
    batch("clear", n, |_| std::hint::black_box(&mut g).clear());
    batch("fill_screen", n, |_| std::hint::black_box(&mut g).fill_rect(0, 0, 128, 64, 1));
    batch("line", n, |_| std::hint::black_box(&mut g).line(0, 0, 127, 63, 1));
    batch("circle_r16", n, |_| std::hint::black_box(&mut g).circle(64, 32, 16, 1));
    batch("fill_circle_r16", n, |_| std::hint::black_box(&mut g).fill_circle(64, 32, 16, 1));
    batch("fill_round_rect", n, |_| std::hint::black_box(&mut g).fill_round_rect(10, 10, 40, 30, 4, 1));
    batch("fill_triangle", n, |_| std::hint::black_box(&mut g).fill_triangle(0, 0, 127, 20, 40, 63, 1));
    batch("text_21_s1", n, |_| std::hint::black_box(&mut g).text(0, 0, b"ABCDEFGHIJKLMNOPQRSTU", 1, 1));
    batch("text_10_s2", n, |_| std::hint::black_box(&mut g).text(0, 0, b"ABCDEFGHIJ", 2, 1));
    batch("card", n, |i| crate::ui::draw_card(std::hint::black_box(&mut g), 40, 20, (i % 52) as u8));
    batch("card_back", n, |_| crate::ui::draw_card_back(std::hint::black_box(&mut g), 40, 20));
    let hs = hands();
    let check = |name: &str, sum: u32| std::println!("BENCH {{\"sec\":\"logic\",\"name\":\"{}_check\",\"checksum\":{}}}", name, sum);
    let (mut rng, mut deck, mut sum) = (Rng { state: SEED }, Deck::new(), 0u32);
    batch("logic_shuffle", 2000, |_| { deck.shuffle(&mut rng); sum = sum.wrapping_add(deck.cards[0] as u32); });
    check("shuffle", sum);
    let n = (N_HANDS * REPS) as u32;
    sum = 0;
    batch("logic_bj_total", n, |i| sum = sum.wrapping_add(bj_total(std::hint::black_box(&hs[i as usize % N_HANDS][..3])) as u32));
    check("bj_total", sum);
    sum = 0;
    batch("logic_eval5", n, |i| sum = sum.wrapping_add(eval_cards(std::hint::black_box(&hs[i as usize % N_HANDS][..5]))));
    check("eval5", sum);
    sum = 0;
    batch("logic_best7", n, |i| sum = sum.wrapping_add(best_hand(std::hint::black_box(&hs[i as usize % N_HANDS]))));
    check("best7", sum);
    let mut casino = Casino::new();
    casino.reset(SEED, 1000);
    let (mut update_ns, mut draw_ns, mut crc) = (0u128, 0u128, 0u32);
    let frames = run_script(|ev| {
        casino.table.clock += FRAME_MS;
        let t0 = Instant::now();
        casino.update(ev);
        let t1 = Instant::now();
        casino.draw(&mut g);
        update_ns += (t1 - t0).as_nanos();
        draw_ns += t1.elapsed().as_nanos();
        crc = crc32(crc, &g.buf);
    });
    std::println!("BENCH {{\"sec\":\"frame\",\"name\":\"update\",\"n\":{},\"avg_ns\":{}}}", frames, update_ns / frames as u128);
    std::println!("BENCH {{\"sec\":\"frame\",\"name\":\"draw\",\"n\":{},\"avg_ns\":{}}}", frames, draw_ns / frames as u128);
    std::println!("BENCH {{\"sec\":\"parity\",\"name\":\"playthrough\",\"bank\":{},\"rng\":{},\"frame_crc32\":{}}}",
        casino.table.bank, casino.table.rng.state, crc);
}
