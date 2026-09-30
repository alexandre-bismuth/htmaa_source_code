# Host tests for a MicroPython port, run with the MicroPython unix port:
#   cd embedded_programming/micropython/tests && micropython run_tests.py qpad_casino_naive [out_dir]
# Checks the rules (shared vectors + hand-written cases), game flows, touch logic, every benchmark
# section, and bit-exact parity of the scripted playthrough with the C++ reference.
import sys
import os
import json

PORT = sys.argv[1]
OUT = sys.argv[2] if len(sys.argv) > 2 else "/tmp/qpad_" + PORT
TESTS = os.getcwd()
ROOT = TESTS + "/../.."
PORT_DIR = PORT if PORT.startswith("/") else TESTS + "/../" + PORT
sys.path.insert(0, TESTS + "/stubs")
sys.path.insert(0, PORT_DIR)
os.chdir(PORT_DIR)
try:
    os.mkdir(OUT)
except OSError:
    pass

import cards
import ssd1306
import bench
from machine import I2C
from touch import Touch, UP, DOWN, LEFT, RIGHT, OK, BACK
from casino import Casino, MENU, ROULETTE, BLACKJACK, POKER

NAIVE = hasattr(cards, "Card")
checks = 0
failures = 0


def check(cond, what):
    global checks, failures
    checks += 1
    if not cond:
        failures += 1
        print("FAIL:", what)


# ---------- Adapters: the naive port uses Card objects, the optimized one card numbers ----------
def hand_of(indices):
    return [cards.Card(i) for i in indices] if NAIVE else bytearray(indices)


def bj_total(indices):
    return cards.bj_total(hand_of(indices)) if NAIVE else cards.bj_total(hand_of(indices), len(indices))


def best(indices):
    return cards.best_hand(hand_of(indices)) if NAIVE else cards.best_hand(hand_of(indices), len(indices))


def eval5(indices):
    return cards.eval_cards(hand_of(indices)) if NAIVE else cards.eval_cards(hand_of(indices), len(indices))


def top7(deck):
    return [c.index for c in deck.cards[:7]] if NAIVE else list(deck.cards[:7])


def text(msg):
    return msg if isinstance(msg, str) else msg.decode()


def card(s):
    return "23456789TJQKA".index(s[0]) + 13 * "HDCS".index(s[1])


def hand(*names):
    return best([card(n) for n in names])


# ---------- 1. Rules against the JS reference vectors ----------
with open(ROOT + "/cpp_arduino_ide/qpad_casino/tests/vectors.json") as f:
    vectors = json.load(f)
cards.rng.state = vectors["seed"]
deck = cards.Deck()
for row in vectors["rows"]:
    deck.shuffle()
    check(top7(deck) == row["cards"], "shuffle order %s" % row["cards"])
    check(bj_total(row["cards"][:3]) == row["bj3"], "bj_total %s" % row["cards"])
    check(eval5(row["cards"][:5]) == row["eval5"], "eval5 %s" % row["cards"])
    check(best(row["cards"]) == row["best7"], "best7 %s" % row["cards"])

# ---------- 2. Hand-written rule cases (same as tests/logic_test.cpp) ----------
names = [
    (("AS", "KS", "QS", "JS", "TS", "2H", "3D"), "ROYAL"), (("9S", "KS", "QS", "JS", "TS"), "STR FLUSH"),
    (("9S", "9H", "9D", "9C", "TS"), "QUADS"), (("9S", "9H", "9D", "4C", "4S"), "FULL HOUSE"),
    (("2S", "7S", "9S", "JS", "KS"), "FLUSH"), (("AS", "2H", "3D", "4C", "5S"), "STRAIGHT"),
    (("9S", "9H", "9D", "4C", "5S"), "TRIPS"), (("9S", "9H", "4D", "4C", "5S"), "TWO PAIR"),
    (("9S", "9H", "4D", "3C", "5S"), "PAIR"), (("9S", "JH", "4D", "3C", "5S"), "HIGH CARD"),
]
for cs, name in names:
    check(cards.hand_name(hand(*cs)) == name, "hand name " + name)
check(hand("AS", "2H", "3D", "4C", "5S") < hand("2S", "3H", "4D", "5C", "6S"), "wheel is the lowest straight")
check(hand("TS", "JH", "QD", "KC", "AS") > hand("9S", "TH", "JD", "QC", "KS"), "higher straight")
check(hand("2S", "7S", "9S", "JS", "KS") > hand("TS", "JH", "QD", "KC", "AS"), "flush beats straight")
check(hand("2S", "2H", "2D", "3C", "3S") > hand("AS", "7S", "9S", "JS", "KS"), "full house beats flush")
check(hand("KS", "KH", "4D", "4C", "5S") > hand("QS", "QH", "JD", "JC", "AS"), "higher top pair")
check(hand("KS", "KH", "4D", "4C", "6S") > hand("KD", "KC", "4H", "4S", "5S"), "kicker")
check(hand("AS", "AH", "9D", "3C", "2S") == hand("AD", "AC", "9H", "3S", "2D"), "exact tie")
check(hand("AS", "KS", "2H", "2D", "7C", "7H", "9S") == hand("AS", "7C", "7H", "2H", "2D"), "best 5 of 7")

for cs, total in ((("AS", "6H"), 17), (("AS", "6H", "TD"), 17), (("AS", "AH"), 12), (("AS", "AH", "9D"), 21),
                  (("TS", "TH", "5D"), 25), (("KS", "QH"), 20)):
    check(bj_total([card(c) for c in cs]) == total, "bj total %s" % (cs,))

for args, ret, msg in (((10, 21, 2, 21, 2), 10, "PUSH"), ((10, 21, 2, 20, 3), 25, "BLACKJACK!"),
                       ((5, 21, 2, 18, 2), 12, "BLACKJACK!"), ((10, 21, 3, 21, 2), 0, "DEALER BLACKJACK"),
                       ((10, 22, 3, 17, 2), 0, "BUST"), ((20, 18, 2, 23, 3), 40, "DEALER BUSTS"),
                       ((10, 20, 2, 19, 2), 20, "YOU WIN"), ((10, 18, 2, 19, 2), 0, "DEALER WINS"),
                       ((10, 19, 3, 19, 2), 10, "PUSH")):
    check(cards.bj_settle(*args) == (ret, msg), "bj_settle %s" % (args,))

pair, high = hand("9S", "9H", "4D", "3C", "5S"), hand("9S", "JH", "4D", "3C", "5S")
flush, straight = hand("2S", "7S", "9S", "JS", "KS"), hand("AS", "2H", "3D", "4C", "5S")
royal, two_pair = hand("AS", "KS", "QS", "JS", "TS"), hand("9S", "9H", "4D", "4C", "5S")
low = hand("2S", "4H", "6D", "8C", "9S")
for args, ret, msg in (((10, 0, two_pair, pair, True), 0, "FOLDED"), ((10, 40, two_pair, pair, False), 110, "YOU WIN"),
                       ((10, 40, flush, pair, False), 125, "YOU WIN"),
                       ((10, 40, straight, high, False), 110, "DEALER NO PAIR"),
                       ((10, 40, royal, pair, False), 5110, "YOU WIN"), ((10, 40, pair, two_pair, False), 0, "DEALER WINS"),
                       ((10, 40, low, high, False), 10, "DEALER WINS"), ((10, 40, pair, pair, False), 60, "PUSH")):
    check(cards.uth_settle(*args) == (ret, msg), "uth_settle %s" % (args[:2],))

reds = (1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36)
for n in range(37):
    check(cards.is_red(n) == (n in reds), "is_red %d" % n)
for b in range(9):
    check(not cards.bet_wins(b, 0), "zero loses outside bet %d" % b)
check(cards.bet_wins(9, 0) and cards.bet_pays(9) == 35, "straight zero")
check(cards.bet_wins(6, 12) and not cards.bet_wins(6, 13) and cards.bet_wins(7, 13) and cards.bet_wins(8, 36), "dozens")
check(cards.bet_wins(3, 35) and cards.bet_wins(2, 36) and cards.bet_wins(4, 18) and cards.bet_wins(5, 19), "even money")
check(sorted(cards.WHEEL) == list(range(37)), "wheel has every pocket once")

# ---------- 3. Game flows on the stubbed board ----------
frame_file = [None]                                # playthrough frames stream to disk (keeps the heap small)
shown = [0]


def on_show(buf):
    shown[0] += 1
    if frame_file[0]:
        frame_file[0].write(buf)


ssd1306.on_show.append(on_show)
display = ssd1306.SSD1306_I2C(128, 64, I2C(1))
touch = Touch()
casino = Casino(display, touch)


def step(events=0, n=1):
    for _ in range(n):
        casino.clock += 33
        casino.update(events)
        casino.draw()
        events = 0


def press(button, wait=0):
    step(1 << button)
    step(0, wait)


def settle_frames():
    step(0, 200)


casino.reset(1, 1000)
press(RIGHT, 10)
check(casino.menu.selected == 1, "menu RIGHT selects blackjack")
press(LEFT, 10)
press(UP, 10)
check(casino.menu.selected == 2, "menu wraps around")
press(DOWN, 10)
press(OK, 5)
check(casino.screen == ROULETTE, "OK opens roulette")
press(BACK, 5)
check(casino.screen == MENU, "BACK returns to the menu")

# House loan when broke
casino.reset(1, 1000)
casino.bank = 0
press(RIGHT, 10)
press(OK, 5)
press(OK, 5)
bj = casino.games[1]
check(casino.bank == 1000 and text(bj.round.msg) == "HOUSE LOAN", "house loan when broke")
check(bj.phase == "bet" or bj.phase == 0, "loan does not deal a hand")

# Hold'em ante is capped at bank / 6
casino.reset(1, 1000)
casino.bank = 100
press(RIGHT, 10)
press(RIGHT, 10)
press(OK, 5)
uth = casino.games[2]
for _ in range(5):
    press(UP, 2)
check(uth.round.bet_idx == 1, "hold'em ante capped at 10 with a bank of 100")

# Roulette straight-number win pays 35:1 and lands the strip on the number
for seed in range(1, 500):
    casino.reset(seed, 1000)
    peek = cards.rng.state
    n = cards.rng.below(37)
    cards.rng.state = peek
    press(OK, 5)                                   # open roulette (menu starts on it)
    rou = casino.games[0]
    rou.bet = 9 + n
    bank0 = casino.bank
    press(OK, 0)
    settle_frames()
    check(casino.bank == bank0 + 10 * 35, "straight win pays 35:1 (seed %d)" % seed)
    check(rou.spin_to % 37 == cards.WHEEL.index(n), "strip stops on the winning pocket")
    break

# Blackjack: every hand keeps the bank consistent with the stake and the payout
for seed in range(1, 60):
    casino.reset(seed, 1000)
    press(RIGHT, 10)
    press(OK, 5)
    bj = casino.games[1]
    bank0 = casino.bank
    press(OK, 40)                                  # deal
    if bj.phase in ("play", 2):
        press(RIGHT, 2)
        press(RIGHT, 2)                            # DOUBLE when allowed, else STAND
        press(OK, 0)
    settle_frames()
    check(bj.round.payout == -1, "payout applied (seed %d)" % seed)
    check(casino.bank - bank0 == bj.round.net, "bank change equals the banner (seed %d)" % seed)
    check(bj.round.net in (-20, -10, 0, 10, 15, 20), "possible blackjack result %d (seed %d)" % (bj.round.net, seed))

# Hold'em: fold costs exactly ante + blind; BACK is ignored mid-hand
casino.reset(3, 1000)
press(RIGHT, 10)
press(RIGHT, 10)
press(OK, 5)
uth = casino.games[2]
press(OK, 50)
press(BACK, 2)
check(casino.screen == POKER, "BACK ignored during a hand")
press(OK, 30)
press(OK, 30)
bank0 = casino.bank
press(OK, 0)                                       # FOLD is selected on the river
settle_frames()
check(text(uth.round.msg) == "FOLDED" and casino.bank == bank0 and uth.round.net == -20, "fold loses ante + blind")

# ---------- 4. Touch: edges, hysteresis, auto-repeat ----------
t = Touch()
values = [0] * 6
t.measure = lambda pad: values[pad]
t.measure_all = lambda: values
t.baseline = [10] * 6
t.threshold = [20] * 6
check(t.read_buttons(0) == 0, "idle pads give no events")
values[UP] = 30
check(t.read_buttons(0) == 1 << UP, "press edge")
check(t.read_buttons(100) == 0, "no repeat before 400 ms")
values[UP] = 16
check(t.read_buttons(200) == 0 and t.down[UP], "hysteresis keeps the pad down above the midpoint")
check(t.read_buttons(450) == 1 << UP, "auto-repeat after 400 ms")
check(t.read_buttons(500) == 0, "repeat rate 110 ms")
check(t.read_buttons(570) == 1 << UP, "second repeat")
values[UP] = 14
check(t.read_buttons(600) == 0 and not t.down[UP], "release below the midpoint")
values[OK] = 30
check(t.read_buttons(700) == 1 << OK, "OK press")
check(t.read_buttons(1500) == 0, "OK never repeats")
values[OK] = 0
t.stuck[LEFT] = True
values[LEFT] = 99
check(t.read_buttons(1600) == 0, "stuck pad is ignored")

# ---------- 5. Benchmark sections: parity with the C++ reference ----------
with open(ROOT + "/benchmarks/reference.json") as f:
    ref = json.load(f)
rows = []
bench.line = lambda sec, name, **values: rows.append((sec, name, values))


def result(sec, name):
    for s, n, v in rows:
        if s == sec and n == name:
            return v
    return None


bench.logic_bench(casino)
for name in ("shuffle", "bj_total", "eval5", "best7"):
    check(result("logic", name + "_check")["checksum"] == ref[name + "_check"], name + " checksum matches C++")
frame_file[0] = open(OUT + "/frames_raw.bin", "wb")
bench.playthrough(casino)
frame_file[0].close()
frame_file[0] = None
parity = result("parity", "playthrough")
check(result("frame", "percentiles")["frames"] == ref["frames"], "same number of frames as C++")
check(parity["bank"] == ref["bank"], "final bank matches C++ (%d)" % parity["bank"])
check(parity["rng"] == ref["rng"], "RNG state matches C++")
crc_match = parity["frame_crc32"] == ref["frame_crc32"]
if NAIVE:
    print("frame CRC vs C++:", "identical" if crc_match else "differs (floats in the naive port, expected)")
else:
    check(crc_match, "every frame is bit-identical to C++")
with open(OUT + "/frames_raw.bin", "rb") as src, open(OUT + "/frames.bin", "wb") as dst:
    src.read(1024)                                 # the first frame is the progress screen
    while True:
        chunk = src.read(1024)
        if not chunk:
            break
        dst.write(chunk)
os.remove(OUT + "/frames_raw.bin")

bench.touch_bench(casino)
bench.gfx_bench(casino)
bench.push_bench(casino)
stack = bench.soak(casino)
for sec, name in (("touch", "Q5"), ("touch", "scan6"), ("gfx", "card"), ("gfx", "fill_triangle"), ("display", "push"),
                  ("frame", "total"), ("draw_screen", "holdem"), ("latency", "input_to_display"),
                  ("leaks", "soak"), ("leaks", "fragmentation")):
    check(result(sec, name) is not None, "benchmark emits %s/%s" % (sec, name))
check(stack > 0, "stack use measured")
bench.memory_static()
check(result("memory", "static")["flash_image_bytes"] > 0, "program size measured")
with open(OUT + "/bench_rows.json", "w") as f:
    json.dump([{"sec": s, "name": n, "values": v} for s, n, v in rows], f)

print("%s: %d/%d checks passed (frames written to %s)" % (PORT, checks - failures, checks, OUT))
sys.exit(1 if failures else 0)
