# Deterministic benchmark (set BENCHMARK = True in main.py): fixed seed, simulated 30 fps clock,
# scripted input. Results stream as "BENCH {json}" lines; embedded_programming/benchmarks/capture.py saves them.
# The script, seeds and measured items are identical in every language port.
import array
import binascii
import gc
import json
import machine
import micropython
import os
import sys
import time
from cards import rng, Card, bj_total, eval_cards, best_hand
from casino import FRAME_MS
from gfx import WHITE
from touch import UP, DOWN, LEFT, RIGHT, OK, BACK, PAD_NAMES
from ui import draw_card, draw_card_back

SEED = 0xC0FFEE
HAND_SEED = 12345
N_HANDS = 250
REPS = 40
TAIL_FRAMES = 60
TOTAL_FRAMES = 1651                                  # frames in one run of SCRIPT
TIMES = array.array("I", bytes(4 * (TOTAL_FRAMES + 8)))   # per-frame times, preallocated once
SCREENS = ["menu", "roulette", "blackjack", "holdem"]
SCRIPT = [                                          # (frames since the previous step, button)
    (20, RIGHT), (12, RIGHT), (12, RIGHT), (12, OK),          # carousel once around, enter roulette
    (10, RIGHT), (4, UP), (4, UP), (6, OK),                   # 50 on BLACK, spin
    (160, LEFT), (4, LEFT), (4, LEFT), (6, OK),               # straight No.35, spin
    (160, BACK), (12, RIGHT), (12, OK),                       # -> blackjack
    (10, OK), (45, OK), (20, RIGHT), (4, OK),                 # deal, hit, stand
    (110, OK), (45, RIGHT), (4, RIGHT), (4, OK),              # deal, double
    (110, OK), (45, RIGHT), (4, OK),                          # deal, stand
    (110, BACK), (12, RIGHT), (12, OK),                       # -> hold'em
    (10, OK), (45, OK), (25, OK), (25, RIGHT), (4, OK),       # deal, check, check, bet 1x
    (120, OK), (45, RIGHT), (4, RIGHT), (4, OK),              # deal, bet 4x
    (120, OK), (45, OK), (25, OK), (25, OK),                  # deal, check, check, fold
    (120, BACK),
]


def line(sec, name, **values):
    row = {"sec": sec, "name": name}
    row.update(values)
    print("BENCH " + json.dumps(row))


def stat(sec, name, times):
    line(sec, name, n=len(times), avg_ns=sum(times) * 1000 // len(times), min_us=min(times), max_us=max(times))


def batch(sec, name, n, work):
    """Average of a tight loop, for operations shorter than the 1 us timer."""
    start = time.ticks_us()
    for i in range(n):
        work(i)
    line(sec, name, n=n, avg_ns=time.ticks_diff(time.ticks_us(), start) * 1000 // n)


def progress(casino, what):
    g = casino.gfx
    g.clear()
    g.text_center(10, "BENCHMARK", 2)
    g.text_center(34, what)
    casino.display.show()


def kth_smallest(a, n, k):
    """k-th smallest of a[:n] by in-place quickselect (reorders a, allocates nothing)."""
    lo, hi = 0, n - 1
    while lo < hi:
        pivot = a[(lo + hi) // 2]
        i, j = lo, hi
        while i <= j:
            while a[i] < pivot:
                i += 1
            while a[j] > pivot:
                j -= 1
            if i <= j:
                a[i], a[j] = a[j], a[i]
                i += 1
                j -= 1
        if k <= j:
            hi = j
        elif k >= i:
            lo = i
        else:
            break
    return a[k]


def run_script(frame):
    """Plays SCRIPT (plus a short tail); frame(events) does one frame's work."""
    frames = 0
    step = 0
    next_at = SCRIPT[0][0]
    tail = 0
    while step < len(SCRIPT) or tail < TAIL_FRAMES:
        if step >= len(SCRIPT):
            tail += 1
        events = 0
        if step < len(SCRIPT) and frames == next_at:
            events = 1 << SCRIPT[step][1]
            step += 1
            if step < len(SCRIPT):
                next_at = frames + SCRIPT[step][0]
        frame(events)
        frames += 1
    return frames


def largest_block():
    """Biggest bytearray that can still be allocated."""
    gc.collect()
    lo, hi = 0, gc.mem_free()
    while lo < hi:
        mid = (lo + hi + 1) // 2
        try:
            block = bytearray(mid)
            del block
            lo = mid
        except MemoryError:
            hi = mid - 1
    gc.collect()
    return lo


def memory_static():
    files = sum(os.stat(f)[6] for f in os.listdir() if f.endswith(".py") or f.endswith(".mpy"))
    gc.collect()
    line("memory", "static", flash_image_bytes=files, flash_total_bytes=2097152, ram_total_bytes=270336,
         heap_total_bytes=gc.mem_free() + gc.mem_alloc(), program_ram_bytes=gc.mem_alloc())
    line("memory", "heap_boot", used_bytes=gc.mem_alloc(), free_bytes=gc.mem_free())


def touch_bench(casino):
    progress(casino, "touch")
    touch = casino.touch
    for pad in range(6):
        values = []
        start = time.ticks_us()
        for _ in range(200):
            values.append(touch.measure_once(pad))
        us = time.ticks_diff(time.ticks_us(), start)
        mean = sum(values) / len(values)
        sd = (sum((v - mean) ** 2 for v in values) / len(values)) ** 0.5
        line("touch", PAD_NAMES[pad], n=200, avg_ns=us * 1000 // 200, count_min=min(values),
             count_max=max(values), count_mean_x100=int(mean * 100), count_sd_x100=int(sd * 100))
    times = []
    for _ in range(100):
        start = time.ticks_us()
        touch.scan()
        times.append(time.ticks_diff(time.ticks_us(), start))
    stat("touch", "scan6", times)


def gfx_bench(casino):
    progress(casino, "graphics")
    g = casino.gfx
    cards = [Card(i) for i in range(52)]
    n = 300
    batch("gfx", "clear", n, lambda i: g.clear())
    batch("gfx", "fill_screen", n, lambda i: g.fill_rect(0, 0, 128, 64, WHITE))
    batch("gfx", "line", n, lambda i: g.line(0, 0, 127, 63, WHITE))
    batch("gfx", "circle_r16", n, lambda i: g.circle(64, 32, 16, WHITE))
    batch("gfx", "fill_circle_r16", n, lambda i: g.fill_circle(64, 32, 16, WHITE))
    batch("gfx", "fill_round_rect", n, lambda i: g.fill_round_rect(10, 10, 40, 30, 4, WHITE))
    batch("gfx", "fill_triangle", n, lambda i: g.fill_triangle(0, 0, 127, 20, 40, 63, WHITE))
    batch("gfx", "text_21_s1", n, lambda i: g.text(0, 0, "ABCDEFGHIJKLMNOPQRSTU"))
    batch("gfx", "text_10_s2", n, lambda i: g.text(0, 0, "ABCDEFGHIJ", 2))
    batch("gfx", "card", n, lambda i: draw_card(g, 40, 20, cards[i % 52]))
    batch("gfx", "card_back", n, lambda i: draw_card_back(g, 40, 20))


def push_bench(casino):
    progress(casino, "display push")
    times = []
    for _ in range(100):
        start = time.ticks_us()
        casino.display.show()
        times.append(time.ticks_diff(time.ticks_us(), start))
    stat("display", "push", times)
    line("display", "theory", i2c_hz=400000, payload_bytes=1024, min_us=23040)


def logic_bench(casino):
    progress(casino, "game logic")
    deck = casino.deck
    table = [Card(i) for i in range(52)]
    rng.state = HAND_SEED
    hands = []
    for _ in range(N_HANDS):
        deck.shuffle()
        hands.append([table[card.index] for card in deck.cards[:7]])
    total = [0]

    def shuffle(i):
        deck.shuffle()
        total[0] += deck.cards[0].index

    rng.state = SEED
    batch("logic", "shuffle", 2000, shuffle)
    line("logic", "shuffle_check", checksum=total[0] & 0xFFFFFFFF)
    for name, work in (("bj_total", lambda h: bj_total(h[:3])), ("eval5", lambda h: eval_cards(h[:5])),
                       ("best7", best_hand)):
        total[0] = 0

        def run(i):
            total[0] += work(hands[i % N_HANDS])

        batch("logic", name, N_HANDS * REPS, run)
        line("logic", name + "_check", checksum=total[0] & 0xFFFFFFFF)


class Stat:
    """Running count / sum / min / max, so measuring allocates nothing per frame."""

    def __init__(self):
        self.n = self.total = self.hi = 0
        self.lo = 1 << 29

    def add(self, v):
        self.n += 1
        self.total += v
        if v < self.lo:
            self.lo = v
        if v > self.hi:
            self.hi = v

    def emit(self, sec, name):
        line(sec, name, n=self.n, avg_ns=self.total * 1000 // self.n, min_us=self.lo, max_us=self.hi)


def playthrough(casino):
    """Full game on the simulated clock, with the real touch scan and display push every frame."""
    progress(casino, "playthrough")
    parts = {"input": Stat(), "update": Stat(), "draw": Stat(), "push": Stat(), "total": Stat()}
    by_screen = [Stat(), Stat(), Stat(), Stat()]
    latency = Stat()
    totals = TIMES
    crc = [0, 0]                                                   # running CRC, frames stored
    casino.reset(SEED, 1000)

    def frame(events):
        casino.clock += FRAME_MS
        t0 = time.ticks_us()
        casino.touch.scan()
        t1 = time.ticks_us()
        casino.update(events)
        t2 = time.ticks_us()
        casino.draw()
        t3 = time.ticks_us()
        casino.display.show()
        t4 = time.ticks_us()
        crc[0] = binascii.crc32(casino.display.buffer, crc[0])
        total = time.ticks_diff(t4, t0)
        parts["input"].add(time.ticks_diff(t1, t0))
        parts["update"].add(time.ticks_diff(t2, t1))
        parts["draw"].add(time.ticks_diff(t3, t2))
        parts["push"].add(time.ticks_diff(t4, t3))
        parts["total"].add(total)
        by_screen[casino.screen].add(time.ticks_diff(t3, t2))
        if events:
            latency.add(total)
        if crc[1] < len(totals):
            totals[crc[1]] = total
            crc[1] += 1

    frames = run_script(frame)
    for name in ("input", "update", "draw", "push", "total"):
        parts[name].emit("frame", name)
    for i, s in enumerate(by_screen):
        if s.n:
            s.emit("draw_screen", SCREENS[i])
    n = crc[1]
    p50, p99 = kth_smallest(totals, n, n // 2), kth_smallest(totals, n, n * 99 // 100)
    line("frame", "percentiles", p50_us=p50, p99_us=p99,
         unlocked_fps_x100=100000000 * n // parts["total"].total, frames=frames)
    latency.emit("latency", "input_to_display")
    line("parity", "playthrough", bank=casino.bank, rng=rng.state, frame_crc32=crc[0] & 0xFFFFFFFF)


def soak(casino):
    """Leak check: play the script twice from the same seed; a leak-free program ends both runs with the
    same heap. Per-frame allocation and collector runs are counted during both runs."""
    progress(casino, "memory soak")
    before_block = largest_block()
    times = TIMES                                  # frame times of the current run
    state = {"frame": 0, "last": 0, "changed": 0, "max_delta": 0, "allocated": 0, "gc_runs": 0, "stack": 0,
             "worst": 0, "run": 0}

    def frame(events):
        start = time.ticks_us()
        casino.clock += FRAME_MS
        casino.update(events)
        casino.draw()
        us = time.ticks_diff(time.ticks_us(), start)
        if state["run"] < len(times):
            times[state["run"]] = us
            state["run"] += 1
        state["worst"] = max(state["worst"], us)
        state["frame"] += 1
        state["stack"] = max(state["stack"], micropython.stack_use())
        used = gc.mem_alloc()
        delta = used - state["last"]
        if delta:
            state["changed"] += 1
        if delta < 0:
            state["gc_runs"] += 1              # the collector ran during this frame
        else:
            state["allocated"] += delta
            state["max_delta"] = max(state["max_delta"], delta)
        state["last"] = used

    used = []
    for _ in range(2):
        state["run"] = 0
        casino.reset(SEED, 1000)
        gc.collect()
        state["last"] = gc.mem_alloc()
        run_script(frame)
        gc.collect()
        used.append(gc.mem_alloc())
    frames = state["frame"]
    p50, worst = kth_smallest(times, state["run"], state["run"] // 2), state["worst"]   # p50 of the second run
    line("leaks", "soak", frames=frames, heap_used_before=used[0], heap_used_after=used[1],
         leaked_bytes=used[1] - used[0], frames_with_heap_change=state["changed"],
         max_heap_delta=state["max_delta"], alloc_bytes_per_frame=state["allocated"] // frames,
         gc_runs=state["gc_runs"], frame_p50_us=p50, frame_max_us=worst)
    line("leaks", "fragmentation", free_bytes=gc.mem_free(), largest_block_before=before_block,
         largest_block_after=largest_block())
    return state["stack"]


def run(casino, boot_frame_ms, wait_for_host=True):
    ready_ms = time.ticks_ms()
    progress(casino, "run capture.py")
    if wait_for_host:
        sys.stdin.read(1)                          # capture.py sends a byte once it is listening
    print('BENCH_BEGIN {"lang":"micropython_naive","cpu_hz":%d,"frame_ms":%d,"seed":%d}'
          % (machine.freq(), FRAME_MS, SEED))
    line("boot", "timing", first_frame_ms=boot_frame_ms, ready_ms=ready_ms)
    memory_static()
    touch_bench(casino)
    gfx_bench(casino)
    push_bench(casino)
    logic_bench(casino)
    playthrough(casino)
    stack = soak(casino)
    line("memory", "stack", stack_used_bytes=stack)
    print("BENCH_END")
    progress(casino, "done")
    while True:
        time.sleep(1)
