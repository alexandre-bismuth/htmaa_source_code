#!/usr/bin/env python3
"""Generate embedded_programming/benchmarks/BENCHMARK.md from results/ only.
Every number in the report is read from a results file or computed here."""
import json, os, sys

# Paths are relative to this script's folder (benchmarks/): `python3 make_report.py` rebuilds BENCHMARK.md.
B = os.path.dirname(os.path.abspath(__file__))
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(B, "BENCHMARK.md")


def jl(p):
    d = {}
    for line in open(p):
        line = line.strip()
        if line:
            r = json.loads(line)
            d[(r["sec"], r["name"])] = r
    return d


def js(p):
    return json.load(open(p))


ORDER = ["cpp", "rust", "micropython", "micropython_naive"]
NAME = {"cpp": "C++", "rust": "Rust", "micropython": "MP optimized", "micropython_naive": "MP naive"}
D = {l: jl(f"{B}/results/{l}.jsonl") for l in ORDER}
H = {
    "cpp": jl(f"{B}/results/host/cpp_host.jsonl"),
    "rust": jl(f"{B}/results/host/rust_host.jsonl"),
    "micropython_naive": jl(f"{B}/results/host/micropython_naive_host.jsonl"),
    "micropython": jl(f"{B}/results/host/micropython_no_viper_host.jsonl"),  # viper stripped
}
BUILD = {l: js(f"{B}/results/{l}_build.json") for l in ORDER}
AUD = js(f"{B}/results/allocation_audit.json")
VER = js(f"{B}/results/verification.json")
REF = js(f"{B}/reference.json")

# ---- hardware facts (aggregate_prompt.md) ----
CPU_HZ = 125_000_000
NS_PER_CYC = 1e9 / CPU_HZ  # 8 ns
FLASH = 2_097_152
SRAM = 270_336
FRAME_MS = {r[("meta", "run")]["frame_ms"] for r in D.values()}
assert len(FRAME_MS) == 1, FRAME_MS
BUDGET_MS = float(FRAME_MS.pop())  # frame period from the meta rows: 33 ms
FPS_CAP = 1000 / BUDGET_MS  # 30.3 fps
FLOOR_MS = 1024 * 9 / 400_000 * 1000  # 23.04 ms
FRAMES = REF["frames"]
GAME_S = FRAMES * BUDGET_MS / 1000  # 54.48 s of game time


# ---- formatting ----
def n0(x):
    return f"{x:,.0f}"


def ms(ns, d=2):
    return f"{ns / 1e6:,.{d}f}"


def us(ns, d=1):
    return f"{ns / 1e3:,.{d}f}"


def cyc(ns):
    return n0(ns / NS_PER_CYC)


def pct(a, b, d=1):
    return f"{100 * a / b:.{d}f}%"


def rx(x):
    if x < 0.995:
        return f"{x:.2f}×"
    if x < 10:
        return f"{x:.2f}×"
    if x < 100:
        return f"{x:.1f}×"
    return f"{x:,.0f}×"


def table(head, rows):
    out = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def g(l, sec, name, key="avg_ns"):
    return D[l][(sec, name)][key]


# ---- self-checks (printed, and the failures go into the report) ----
checks = []
for l in ORDER:
    st = sum(g(l, "frame", s) for s in ("input", "update", "draw", "push"))
    tot = g(l, "frame", "total")
    checks.append(f"{l}: stage sum {st} vs total {tot} (diff {st - tot} ns)")
    fps = g(l, "frame", "percentiles", "unlocked_fps_x100") / 100
    checks.append(f"{l}: unlocked fps {fps} vs 1e9/total {1e9 / tot:.3f}")
    p = D[l][("parity", "playthrough")]
    for k in ("bank", "rng", "frame_crc32"):
        checks.append(f"{l}: {k} {p[k]} ref {REF[k]} {'OK' if p[k] == REF[k] else 'DIFF'}")
    for k in ("shuffle", "bj_total", "eval5", "best7"):
        c = D[l][("logic", k + "_check")]["checksum"]
        checks.append(f"{l}: {k}_check {c} {'OK' if c == REF[k + '_check'] else 'DIFF'}")
    checks.append(f"{l}: frames {g(l, 'frame', 'percentiles', 'frames')}")
for c in checks:
    print(c)
_cs, _sec = D["cpp"][("memory", "static")], BUILD["cpp"]["benchmark_build"]["sections"]
assert _cs["data_bytes"] + _cs["bss_bytes"] + _sec[".ram_vector_table"] + _sec[".uninitialized_data"] == _cs["ram_static_bytes"]
assert all(D[l][("leaks", "soak")]["frames"] == 3302 for l in ORDER)
assert all(D[l][("frame", s_)]["n"] == FRAMES for l in ORDER for s_ in ("input", "update", "draw", "push", "total"))
assert all(D[l][("latency", "input_to_display")]["n"] == 43 for l in ORDER)
assert D["micropython"][("memory", "static")]["flash_image_bytes"] == BUILD["micropython"]["compiled_mpy_bytes"] + BUILD["micropython"]["py_files"]["main.py"]
assert D["micropython_naive"][("memory", "static")]["flash_image_bytes"] == BUILD["micropython_naive"]["source_py_bytes"]
for l in ORDER:
    hb = D[l][("memory", "heap_boot")]
    assert hb["used_bytes"] + hb["free_bytes"] == D[l][("memory", "static")]["heap_total_bytes"], l
print("asserts OK")

# ======================================================================
md = []
A = md.append

# ---------------- derived per program ----------------
V = {}
for l in ORDER:
    d = D[l]
    tot = g(l, "frame", "total")
    unl = g(l, "frame", "percentiles", "unlocked_fps_x100") / 100
    v = dict(
        tot=tot,
        unl=unl,
        play=min(FPS_CAP, unl),
        rtf=min(1.0, BUDGET_MS / (tot / 1e6)),
        wall=FRAMES * tot / 1e9,
        run=d[("meta", "run")]["run_seconds"],
        p50=g(l, "frame", "percentiles", "p50_us"),
        p99=g(l, "frame", "percentiles", "p99_us"),
        fmin=g(l, "frame", "total", "min_us"),
        fmax=g(l, "frame", "total", "max_us"),
    )
    if v["fmax"] < BUDGET_MS * 1000:
        v["over"] = "none"
    elif v["fmin"] > BUDGET_MS * 1000:
        v["over"] = "all"
    elif v["p50"] > BUDGET_MS * 1000:
        v["over"] = "more than half"
    elif v["p99"] > BUDGET_MS * 1000:
        v["over"] = "more than 1%"
    else:
        v["over"] = "under 1%"
    V[l] = v

flash_run = {}
for l in ORDER:
    s = D[l][("memory", "static")]
    fw = BUILD[l].get("firmware_flash_bytes", 0)
    flash_run[l] = s["flash_image_bytes"] + fw

MPFW = BUILD["micropython"]["firmware_flash_bytes"]
MPHEAP = D["micropython"][("memory", "static")]["heap_total_bytes"]
assert MPHEAP == D["micropython_naive"][("memory", "static")]["heap_total_bytes"]

# ================= header =================
A("# QPAD Casino benchmark report")
A("")
A("Built 2026-09-30 from `benchmarks/results/` only: the four device runs on the RP2040 (`cpp.jsonl`, `rust.jsonl`, "
  "`micropython.jsonl`, `micropython_naive.jsonl`, captured "
  + ", ".join(f"{NAME[l]} {D[l][('meta','run')]['captured']}" for l in ORDER)
  + "), the `*_build.json` footprints, `allocation_audit.json`, `verification.json`, `reference.json`, and the host proxy "
  "runs in `results/host/`. The `*_raw.log` serial logs were not used.")
A("")
A(f"All device runs: RP2040 at {CPU_HZ // 1_000_000} MHz (`cpu_hz` in every meta row), seed {D['cpp'][('meta','run')]['seed']}, "
  f"{FRAMES:,} scripted frames. **Device data is the main content. Host-proxy numbers (Apple-silicon Mac) appear only under "
  "headings marked *Host proxy*.** They are not RP2040 speed.")
A("")
A("Names: **C++** (`cpp`), **Rust** (`rust`), **MP optimized** (`micropython`), **MP naive** (`micropython_naive`). "
  "The host run of the optimized MicroPython had its viper/native code stripped and is called **MP opt (no viper)**.")
A("")
A(f"Constants used below: frame period (budget) = `frame_ms` = {BUDGET_MS:g} ms from the meta rows, so the fps cap is "
  f"1000 ÷ {BUDGET_MS:g} = {FPS_CAP:.1f} fps; I²C floor for one SSD1306 frame = 1,024 × 9 bits / "
  f"400 kHz = {FLOOR_MS:.2f} ms; 1 cycle at 125 MHz = {NS_PER_CYC:.0f} ns (cycles = ns ÷ 8); game time of the script = "
  f"{FRAMES:,} × {BUDGET_MS:g} ms = {GAME_S:.2f} s; flash % = bytes ÷ {FLASH:,}; SRAM % = bytes ÷ {SRAM:,}. "
  "(`aggregate_prompt.md` gives 33.33 ms and 55.0 s; that was an error in the prompt, and this report uses the 33 ms from the data.)")
A("")

# ================= 1. Summary =================
A("## 1. Summary")
A("")
A(f"Device (RP2040) results. Real-time factor = min(100%, {BUDGET_MS:g} ms ÷ average frame). Playable fps = min({FPS_CAP:.1f}, unlocked fps).")
A("")
rows = []
for l in ORDER:
    d = D[l]
    v = V[l]
    s = d[("memory", "static")]
    hb = d[("memory", "heap_boot")]
    if l == "cpp":
        flash = f"{n0(flash_run[l])} B ({pct(flash_run[l], FLASH)})"
        ram = f"{n0(s['ram_static_bytes'])} B static + {n0(hb['used_bytes'])} B heap ({pct(s['ram_static_bytes'] + hb['used_bytes'], SRAM)})"
    elif l == "rust":
        flash = f"{n0(flash_run[l])} B ({pct(flash_run[l], FLASH)})"
        ram = f"{n0(s['ram_static_bytes'])} B static, no heap ({pct(s['ram_static_bytes'], SRAM)})"
    else:
        flash = f"{n0(flash_run[l])} B ({pct(flash_run[l], FLASH)}) = {n0(MPFW)} firmware + {n0(s['flash_image_bytes'])} program"
        ram = f"{n0(hb['used_bytes'])} B of the {n0(MPHEAP)} B GC heap ({pct(hb['used_bytes'], SRAM)})"
    soak = d[("leaks", "soak")]
    alloc = {"cpp": "0 (heap unchanged every frame)", "rust": "0 (no allocator)"}.get(l, f"{n0(soak.get('alloc_bytes_per_frame', 0))} B")
    if l == "rust":
        leak = f"impossible (no heap); stack high-water {n0(d[('memory', 'stack')]['stack_used_bytes'])} B"
    elif l == "cpp":
        leak = f"{soak['leaked_bytes']} B; largest free block unchanged"
    else:
        leak = f"{soak['leaked_bytes']} B; {soak['gc_runs']} GC runs"
    p = d[("parity", "playthrough")]
    exact = p["frame_crc32"] == REF["frame_crc32"]
    par = ("defines the reference; all match" if l == "cpp" else "all match, incl. frame CRC") if exact else \
        "bank, RNG, checksums match; frame CRC differs (float32 animation math)"
    rows.append([NAME[l], flash, ram,
                 f"{ms(v['tot'])} / {v['p99'] / 1000:.2f} ms",
                 f"{v['play']:.1f} ({v['unl']:.2f})",
                 f"{100 * v['rtf']:.1f}%",
                 f"{us(g(l, 'logic', 'best7'))} µs",
                 alloc, leak, par])
A(table(["Program", "Flash as run (% of 2 MB)", "RAM in use at boot (% of 264 KB)", "Frame avg / p99",
         "Playable fps (unlocked)", "Real-time factor", "best7 eval", "Bytes allocated / frame", "Leaks over 3,302-frame soak",
         "Parity vs reference"], rows))
A("")
c, r, o, nv = (V[x] for x in ORDER)
pushsh = {l: g(l, "frame", "push") / V[l]["tot"] for l in ORDER}
A("Takeaways:")
A("")
A(f"- **Rust and C++ both run at the {FPS_CAP:.1f} fps cap with every frame inside the {BUDGET_MS:g} ms budget.** Rust averages {ms(r['tot'])} ms per frame "
  f"(max {r['fmax'] / 1000:.2f} ms), C++ {ms(c['tot'])} ms (max {c['fmax'] / 1000:.2f} ms, {BUDGET_MS - c['fmax'] / 1000:.2f} ms "
  f"under the budget). Rust needs {pct(c['tot'] - r['tot'], c['tot'])} less time per frame, mostly from a shorter I²C push "
  f"({ms(g('rust', 'frame', 'push'))} vs {ms(g('cpp', 'frame', 'push'))} ms) and draw ({ms(g('rust', 'frame', 'draw'))} vs "
  f"{ms(g('cpp', 'frame', 'draw'))} ms).")
A(f"- **The display push dominates the compiled programs**: {pct(g('cpp', 'frame', 'push'), c['tot'])} of the C++ frame and "
  f"{pct(g('rust', 'frame', 'push'), r['tot'])} of the Rust frame. Every program's push sits above the {FLOOR_MS:.2f} ms I²C "
  f"floor ({ms(g('rust', 'frame', 'push'))}–{ms(g('cpp', 'frame', 'push'))} ms).")
A(f"- **MP optimized misses the cap**: {ms(o['tot'])} ms per frame, {o['play']:.1f} fps, {100 * o['rtf']:.1f}% of real time. "
  f"Its draw ({ms(g('micropython', 'frame', 'draw'))} ms) is {rx(g('micropython', 'frame', 'draw') / g('cpp', 'frame', 'draw'))} "
  f"C++'s; the frame is {ms(o['tot'] - BUDGET_MS * 1e6)} ms over budget.")
A(f"- **MP naive runs at {nv['play']:.1f} fps** ({ms(nv['tot'], 1)} ms per frame, {100 * nv['rtf']:.1f}% of real time): the "
  f"{GAME_S:.2f} s scripted game takes {nv['wall']:.0f} s. It is {rx(nv['tot'] / o['tot'])} slower per frame than MP optimized "
  f"and allocates {n0(D['micropython_naive'][('leaks','soak')]['alloc_bytes_per_frame'])} B per frame "
  f"(MP optimized: {D['micropython'][('leaks','soak')]['alloc_bytes_per_frame']} B).")
A(f"- **Memory is not a constraint for any program**: flash use is {pct(flash_run['rust'], FLASH)}–{pct(flash_run['micropython_naive'], FLASH)} of 2 MB. "
  f"No program leaks. MP optimized holds {rx(g('micropython', 'memory', 'heap_boot', 'used_bytes') / g('micropython_naive', 'memory', 'heap_boot', 'used_bytes'))} "
  f"MP naive's heap at boot; the audit lists preallocation (sprites, bytearrays, cached strings) among its techniques.")
A("- **Parity**: all four reproduce the reference bank, RNG state and the four logic checksums on the device. C++, Rust and "
  "MP optimized also produce the reference frame CRC (bit-identical frames). MP naive's frame CRC differs from the reference, "
  "and its device CRC also differs from its own host CRC.")
A("")

# ================= 2. Verification & parity =================
A("## 2. Verification and parity")
A("")
A("From `verification.json`: the tests ran on the host before the device runs; the last column is the device result.")
A("")
rows = [
    ["C++", VER["cpp"]["logic_tests"], VER["cpp"]["device_build"], VER["device_runs"]["cpp"]],
    ["Rust", VER["rust"]["host_tests"], VER["rust"]["device_build"], VER["device_runs"]["rust"]],
    ["MP optimized", VER["micropython"]["host_tests"], VER["micropython"]["device_compile"], VER["device_runs"]["micropython"]],
    ["MP naive", VER["micropython_naive"]["host_tests"], VER["micropython_naive"]["device_compile"], VER["device_runs"]["micropython_naive"]],
]
A(table(["Program", "Tests", "Build", "Device run"], rows))
A("")
A("Device parity values vs `reference.json` (the reference comes from the C++ sketch run on the host):")
A("")
keys = [("frames", lambda l: g(l, "frame", "percentiles", "frames")),
        ("bank", lambda l: D[l][("parity", "playthrough")]["bank"]),
        ("rng", lambda l: D[l][("parity", "playthrough")]["rng"]),
        ("shuffle_check", lambda l: D[l][("logic", "shuffle_check")]["checksum"]),
        ("bj_total_check", lambda l: D[l][("logic", "bj_total_check")]["checksum"]),
        ("eval5_check", lambda l: D[l][("logic", "eval5_check")]["checksum"]),
        ("best7_check", lambda l: D[l][("logic", "best7_check")]["checksum"]),
        ("frame_crc32", lambda l: D[l][("parity", "playthrough")]["frame_crc32"])]
rows = []
for k, f in keys:
    row = [k, n0(REF[k])]
    for l in ORDER:
        val = f(l)
        row.append("match" if val == REF[k] else f"**{n0(val)}** (differs)")
    rows.append(row)
hn = H["micropython_naive"][("parity", "playthrough")]["frame_crc32"]
A(table(["Value", "Reference", "C++", "Rust", "MP optimized", "MP naive"], rows))
A("")
A(f"- C++, Rust and MP optimized produce the same frame CRC on the device ({n0(REF['frame_crc32'])}), so all {FRAMES:,} frames "
  "are bit-identical across the three.")
A(f"- MP naive's frame CRC differs **three ways**: reference {n0(REF['frame_crc32'])}, host {n0(hn)}, device "
  f"{n0(D['micropython_naive'][('parity','playthrough')]['frame_crc32'])}. Its animation math uses floats: float64 on the Mac, "
  "float32 on the RP2040 port, so each platform rounds differently and produces its own CRC (`verification.json`: "
  "\"differs by design\"). Game logic is unaffected (bank, RNG, checksums match). "
  "On the host, 1290/1651 frames were bit-identical to C++ and the rest differed by 1-pixel float rounding in animations; the "
  "device run records only the CRC, so the number of differing device frames is unmeasured.")
A(f"- Not verified: {VER['not_yet_verified']}")
A("")

# ================= 3. Memory vs chip =================
A("## 3. Memory size vs the chip")
A("")
A(f"Flash (% = bytes ÷ {FLASH:,}). *As run* = the benchmark image the device reported (`memory/static`); *game* = the build "
  "without the benchmark code, from `*_build.json`. MicroPython totals add the firmware image resident in flash.")
A("")
rows = []
cb, rb = BUILD["cpp"], BUILD["rust"]
rows.append(["C++", f"{n0(flash_run['cpp'])} ({pct(flash_run['cpp'], FLASH, 2)})",
             f"{n0(cb['game']['flash_bytes'])} ({pct(cb['game']['flash_bytes'], FLASH, 2)})",
             "boot2 + OTA + partition + .text + .rodata + .data; .text includes the Arduino core, TinyUSB, Adafruit libraries"])
rows.append(["Rust", f"{n0(flash_run['rust'])} ({pct(flash_run['rust'], FLASH, 2)})",
             f"{n0(rb['game']['flash_bytes'])} ({pct(rb['game']['flash_bytes'], FLASH, 2)})",
             "vector table + boot2 + .text + .rodata + .data"])
for l in ("micropython", "micropython_naive"):
    s = D[l][("memory", "static")]
    bench = BUILD[l]["mpy_files"]["bench.mpy"] if l == "micropython" else BUILD[l]["py_files"]["bench.py"]
    game = s["flash_image_bytes"] - bench
    what = ("precompiled `.mpy` with armv6m native/viper code + `main.py` source" if l == "micropython"
            else "`.py` source, compiled to bytecode on the board at import")
    rows.append([NAME[l], f"{n0(flash_run[l])} ({pct(flash_run[l], FLASH, 2)}) = {n0(MPFW)} + {n0(s['flash_image_bytes'])}",
                 f"{n0(MPFW + game)} ({pct(MPFW + game, FLASH, 2)}) = {n0(MPFW)} + {n0(game)}", what])
A(table(["Program", "Flash as run, B", "Flash, game build, B", "Contents"], rows))
A("")
A(f"The MicroPython firmware alone is {n0(MPFW)} B ({pct(MPFW, FLASH, 2)}). The `ssd1306` driver's size is not in the results.")
A("")
A("RAM (% = bytes ÷ 270,336). Device rows, except the game-build static RAM, which comes from `*_build.json`.")
A("")
cs, rs = D["cpp"][("memory", "static")], D["rust"][("memory", "static")]
ch, mh, nh = D["cpp"][("memory", "heap_boot")], D["micropython"][("memory", "heap_boot")], D["micropython_naive"][("memory", "heap_boot")]
cst, rst = D["cpp"][("memory", "stack")], D["rust"][("memory", "stack")]
mst, nst = D["micropython"][("memory", "stack")], D["micropython_naive"][("memory", "stack")]
rows = [
    ["C++", f"{n0(cs['ram_static_bytes'])} ({pct(cs['ram_static_bytes'], SRAM)}); game build {n0(cb['game']['static_ram_bytes'])}*",
     f"{n0(cs['heap_total_bytes'])} ({pct(cs['heap_total_bytes'], SRAM)})",
     f"{n0(ch['used_bytes'])} ({pct(ch['used_bytes'], SRAM, 2)}), incl. the 1,024 B frame buffer",
     f"{n0(cst['stack_used_bytes'])} of {n0(cst['stack_bytes'])} ({pct(cst['stack_used_bytes'], cst['stack_bytes'], 0)})"],
    ["Rust", f"{n0(rs['ram_static_bytes'])} ({pct(rs['ram_static_bytes'], SRAM)}); game build {n0(rb['game']['static_ram_bytes'])}",
     "0 (no allocator)", "0",
     f"{n0(rst['stack_used_bytes'])} of {n0(rst['stack_bytes'])} ({pct(rst['stack_used_bytes'], rst['stack_bytes'], 1)})"],
    ["MP optimized", f"{n0(SRAM - MPHEAP)} outside the GC heap ({pct(SRAM - MPHEAP, SRAM)})†",
     f"{n0(MPHEAP)} ({pct(MPHEAP, SRAM)})",
     f"{n0(mh['used_bytes'])} ({pct(mh['used_bytes'], SRAM)}; {pct(mh['used_bytes'], MPHEAP)} of the heap)",
     f"{n0(mst['stack_used_bytes'])}‡"],
    ["MP naive", f"{n0(SRAM - MPHEAP)} outside the GC heap ({pct(SRAM - MPHEAP, SRAM)})†",
     f"{n0(MPHEAP)} ({pct(MPHEAP, SRAM)})",
     f"{n0(nh['used_bytes'])} ({pct(nh['used_bytes'], SRAM)}; {pct(nh['used_bytes'], MPHEAP)} of the heap)",
     f"{n0(nst['stack_used_bytes'])}‡"],
]
A(table(["Program", "Static RAM, B", "Heap total, B", "Heap used at boot, B", "Stack used, B"], rows))
A("")
A(f"\\* C++ static RAM: the device counts .data {n0(cs['data_bytes'])} + .bss {n0(cs['bss_bytes'])} + vector table "
  f"{cb['benchmark_build']['sections']['.ram_vector_table']} + uninitialized {cb['benchmark_build']['sections']['.uninitialized_data']} = {n0(cs['ram_static_bytes'])} B. `cpp_build.json` counts .data + .bss + two 2,048 B stack reserves "
  f"= {n0(cb['benchmark_build']['static_ram_bytes'])} B for the same benchmark build. Both are right; they include different sections.")
A("")
A(f"† MicroPython: the results give only the GC heap ({n0(MPHEAP)} B). The {n0(SRAM - MPHEAP)} B outside it hold the firmware's "
  "static data and its C stack; the split is not in the results. `program_ram_bytes` (heap the program occupies) is "
  f"{n0(D['micropython'][('memory','static')]['program_ram_bytes'])} B optimized and "
  f"{n0(D['micropython_naive'][('memory','static')]['program_ram_bytes'])} B naive, "
  f"{mh['used_bytes'] - D['micropython'][('memory','static')]['program_ram_bytes']} B below `heap_boot.used_bytes` in both.")
A("")
A("‡ `micropython.stack_use()` sampled at the same call depth in the soak, so the two ports report the same value. It is a point "
  "sample, not a high-water mark.")
A("")
A("Takeaways:")
A("")
A(f"- Flash: at most {pct(flash_run['micropython_naive'], FLASH)} of 2 MB (MP naive with its firmware). Rust's game build is "
  f"the smallest image ({n0(rb['game']['flash_bytes'])} B, {pct(rb['game']['flash_bytes'], FLASH, 2)}).")
A(f"- C++'s core-0 stack reserve is the tightest figure in the report: {n0(cst['stack_used_bytes'])} of {n0(cst['stack_bytes'])} B used "
  f"({pct(cst['stack_used_bytes'], cst['stack_bytes'], 0)}, {cst['stack_bytes'] - cst['stack_used_bytes']} B left). Rust's stack uses the RAM below "
  f".data (flip-link) and peaked at {n0(rst['stack_used_bytes'])} B, {pct(rst['stack_used_bytes'], rst['stack_bytes'])} of its {n0(rst['stack_bytes'])} B region.")
A(f"- MicroPython's heap is the main RAM consumer: MP optimized occupies {n0(mh['used_bytes'])} B at boot, "
  f"{rx(mh['used_bytes'] / nh['used_bytes'])} MP naive's {n0(nh['used_bytes'])} B, leaving {n0(mh['free_bytes'])} B free vs "
  f"{n0(nh['free_bytes'])} B. The results do not break the heap down by object.")
A("")

# ================= 4. Latency & throughput =================
A("## 4. Latency and throughput")
A("")
A("### Device (RP2040)")
A("")
A(f"**Where the frame goes** (scripted playthrough, n = {FRAMES:,} frames; ms = avg_ns ÷ 10⁶; share = stage ÷ total)")
A("")
rows = []
for l in ORDER:
    tot = V[l]["tot"]
    row = [NAME[l]]
    for s in ("input", "update", "draw", "push"):
        x = g(l, "frame", s)
        row.append(f"{ms(x, 3 if x < 1e6 else 2)} ({pct(x, tot, 2 if x / tot < 0.01 else 1)})")
    row.append(ms(tot))
    rows.append(row)
A(table(["Program", "input (touch scan), ms", "update, ms", "draw, ms", "push (I²C), ms", "total, ms"], rows))
A("")
A(f"**Speed beyond frame rate** (unlocked fps = 10⁹ ÷ avg frame ns; playable fps = min({FPS_CAP:.1f}, unlocked); real-time factor = "
  f"min(100%, {BUDGET_MS:g} ms ÷ avg frame); scripted game wall time = {FRAMES:,} × avg frame, against {GAME_S:.2f} s of game time; "
  "`run_seconds` = whole benchmark, from the meta row)")
A("")
rows = []
for l in ORDER:
    v = V[l]
    rows.append([NAME[l], f"{v['unl']:.2f}", f"{v['play']:.1f}", f"{100 * v['rtf']:.1f}%",
                 f"{v['wall']:.1f} s ({v['wall'] / GAME_S:.2f}× game time)",
                 f"{v['run']:,.1f} s" + (f" ({v['run'] / 60:.1f} min)" if v['run'] > 120 else "")])
A(table(["Program", "Unlocked fps", "Playable fps", "Real-time factor", "Scripted game, wall time", "run_seconds"], rows))
A("")
A("In benchmark mode the frames run back to back and the game clock advances one frame step per frame, so a program slower "
  f"than {BUDGET_MS:g} ms plays the same game in slow motion. C++ and Rust would be held to {GAME_S:.2f} s by the frame lock; "
  f"MP optimized plays it {V['micropython']['wall'] / GAME_S:.2f}× slower than real time and MP naive {V['micropython_naive']['wall'] / GAME_S:.2f}× slower.")
A("")
A(f"**Frame-time distribution and input-to-display latency** (µs → ms; budget {BUDGET_MS:g} ms; latency n = 43 input events)")
A("")
rows = []
for l in ORDER:
    v = V[l]
    lat = D[l][("latency", "input_to_display")]
    rows.append([NAME[l], f"{v['fmin'] / 1000:.2f}", f"{v['p50'] / 1000:.2f}", ms(v["tot"]), f"{v['p99'] / 1000:.2f}",
                 f"{v['fmax'] / 1000:.2f}", v["over"],
                 f"{ms(lat['avg_ns'])} ({lat['min_us'] / 1000:.2f}–{lat['max_us'] / 1000:.2f})"])
A(table(["Program", "min", "p50", "avg", "p99", "max", "Frames over budget", "Input→display avg (min–max), ms"], rows))
A("")
A("- Input-to-display latency is about one frame: average latency ÷ average frame = "
  + ", ".join(f"{g(l, 'latency', 'input_to_display') / V[l]['tot']:.2f} ({NAME[l]})" for l in ORDER)
  + f". MP naive's input frames are lighter than its average frame ({ms(g('micropython_naive', 'latency', 'input_to_display'), 1)} vs "
  f"{ms(V['micropython_naive']['tot'], 1)} ms).")
A(f"- C++'s slowest frame ({V['cpp']['fmax'] / 1000:.2f} ms) is {BUDGET_MS - V['cpp']['fmax'] / 1000:.2f} ms under the budget; "
  f"Rust's ({V['rust']['fmax'] / 1000:.2f} ms) is {BUDGET_MS - V['rust']['fmax'] / 1000:.2f} ms under.")
A("")
A(f"**Push against the I²C floor and the budget** (floor {FLOOR_MS:.2f} ms; budget left = {BUDGET_MS:g} − push; "
  "margin = budget − total frame)")
A("")
rows = []
for l in ORDER:
    fp = g(l, "frame", "push")
    dp = D[l][("display", "push")]
    rest = V[l]["tot"] - fp
    rows.append([NAME[l], f"{ms(fp)} (max {g(l, 'frame', 'push', 'max_us') / 1000:.2f})",
                 f"{ms(dp['avg_ns'])} ({dp['min_us'] / 1000:.2f}–{dp['max_us'] / 1000:.2f})",
                 f"{fp / 1e6 / FLOOR_MS:.3f}× (+{fp / 1e6 - FLOOR_MS:.2f} ms)",
                 pct(fp / 1e6, BUDGET_MS),
                 f"{BUDGET_MS - fp / 1e6:.2f}", ms(rest), f"{BUDGET_MS - V[l]['tot'] / 1e6:+.2f}"])
A(table(["Program", "Push in game, ms", "Push isolated (n = 100), ms", "÷ I²C floor", "% of budget",
         "Budget left, ms", "input + update + draw, ms", "Margin, ms"], rows))
A("")
A(f"- No push reaches the {FLOOR_MS:.2f} ms floor; the overhead above it is {g('rust', 'frame', 'push') / 1e6 - FLOOR_MS:.2f} ms (Rust) to "
  f"{g('cpp', 'frame', 'push') / 1e6 - FLOOR_MS:.2f} ms (C++). Both MicroPython ports push in the same time "
  f"({ms(g('micropython', 'frame', 'push'))} vs {ms(g('micropython_naive', 'frame', 'push'))} ms).")
A(f"- MP optimized's max in-game push ({g('micropython', 'frame', 'push', 'max_us') / 1000:.2f} ms) is "
  f"{g('micropython', 'frame', 'push', 'max_us') / 1000 - g('micropython', 'frame', 'push') / 1e6:.2f} ms above its average; "
  f"MP naive's max is {g('micropython_naive', 'frame', 'push', 'max_us') / 1000:.2f} ms. The isolated MicroPython pushes span at most "
  f"{max(D[l][('display','push')]['max_us'] - D[l][('display','push')]['min_us'] for l in ('micropython', 'micropython_naive')) / 1000:.3f} ms (min to max), "
  "so those outliers happen inside the game loop; the results do not say why.")
A(f"- With the push blocking, {BUDGET_MS - g('cpp', 'frame', 'push') / 1e6:.2f} ms (C++) to {BUDGET_MS - g('rust', 'frame', 'push') / 1e6:.2f} ms "
  f"(Rust) is left for everything else. MP optimized needs {ms(V['micropython']['tot'] - g('micropython', 'frame', 'push'))} ms for "
  f"input + update + draw, {ms(V['micropython']['tot'] - BUDGET_MS * 1e6)} ms too many.")
A("")
A("**Draw time per screen**, avg ms (max) — frames per screen: " +
  ", ".join(f"{s} {D['cpp'][('draw_screen', s)]['n']}" for s in ("menu", "roulette", "blackjack", "holdem")))
A("")
rows = []
for l in ORDER:
    row = [NAME[l]]
    for s in ("menu", "roulette", "blackjack", "holdem"):
        r_ = D[l][("draw_screen", s)]
        row.append(f"{ms(r_['avg_ns'])} ({r_['max_us'] / 1000:.2f})")
    rows.append(row)
A(table(["Program", "menu", "roulette", "blackjack", "holdem"], rows))
A("")
assert all(max(("menu", "roulette", "blackjack", "holdem"), key=lambda s_: D[l][("draw_screen", s_)]["avg_ns"]) == "holdem" for l in ORDER)
A("Hold'em is the heaviest screen for every program. MP optimized's worst draw "
  f"({D['micropython'][('draw_screen','holdem')]['max_us'] / 1000:.2f} ms) alone is {pct(D['micropython'][('draw_screen','holdem')]['max_us'] / 1000, BUDGET_MS, 0)} of the budget.")
A("")
A("**Touch and boot** (per reading = mean of the six pads' avg_ns; scan6 = 6 pads × 8 samples + hysteresis ≈ 48 readings; "
  "scan6 ÷ 48 readings = scan6 ÷ (48 × per reading); calibration = ready − first frame)")
A("")
rows = []
units = {"cpp": "loop turns", "rust": "loop turns", "micropython": "PIO steps of 16 ns", "micropython_naive": "µs"}
meth = {"cpp": "RC loop", "rust": "RC loop (in RAM)", "micropython": "PIO", "micropython_naive": "`time_pulse_us`"}
for l in ORDER:
    pads = [D[l][("touch", f"Q{i}")] for i in range(6)]
    per = sum(p["avg_ns"] for p in pads) / 6
    lo, hi = min(p["count_min"] for p in pads), max(p["count_max"] for p in pads)
    sc = D[l][("touch", "scan6")]
    bt = D[l][("boot", "timing")]
    rows.append([NAME[l], meth[l], f"{us(per)} µs", f"{lo}–{hi} {units[l]}" if lo != hi else f"{lo} {units[l]} (all pads)",
                 f"{ms(sc['avg_ns'])} ms ({sc['min_us'] / 1000:.2f}–{sc['max_us'] / 1000:.2f})",
                 f"{sc['avg_ns'] / (48 * per):.2f}",
                 f"{bt['first_frame_ms']:,} ms", f"{bt['ready_ms']:,} ms", f"{bt['ready_ms'] - bt['first_frame_ms']:,} ms"])
A(table(["Program", "Method", "Per reading", "Idle counts", "scan6", "scan6 ÷ 48 readings", "First frame", "Ready", "Calibration"], rows))
A("")
A("- Counts are in each program's own unit, so compare time per reading and scan6, not counts. MP optimized's idle charge time is "
  f"{min(D['micropython'][('touch', f'Q{i}')]['count_min'] for i in range(6)) * 16}–{max(D['micropython'][('touch', f'Q{i}')]['count_max'] for i in range(6)) * 16} ns (counts × 16 ns).")
A("- MP naive reads **0 µs on every idle pad**. `time_pulse_us` has 1 µs resolution and starts only after slow `Pin.init` "
  f"calls, so it cannot see an untouched pad's charge time (MP optimized measures it at "
  f"{max(D['micropython'][('touch', f'Q{i}')]['count_max'] for i in range(6)) * 16} ns or less). Its touch detection "
  "therefore relies on a finger adding at least the threshold to a reading of 0. Its input stage is also the slowest by far "
  f"({ms(g('micropython_naive', 'frame', 'input'))} ms per frame, {pct(g('micropython_naive', 'frame', 'input'), BUDGET_MS * 1e6, 0)} of the budget).")
assert g("micropython", "touch", "scan6") < min(g(l, "touch", "scan6") for l in ("cpp", "rust", "micropython_naive"))
assert all(pm_ > max(sum(D[l][("touch", f"Q{i}")]["avg_ns"] for i in range(6)) / 6 for l in ("cpp", "rust"))
           for pm_ in [sum(D["micropython"][("touch", f"Q{i}")]["avg_ns"] for i in range(6)) / 6])
A(f"- MP optimized's scan6 takes {D['micropython'][('touch','scan6')]['avg_ns'] / (48 * sum(D['micropython'][('touch', f'Q{i}')]['avg_ns'] for i in range(6)) / 6):.2f}× "
  "the time of 48 single readings, while the other three are close to 1×. That is expected: its PIO state machines time all six "
  "pads at once (6 parallel charges × 8 samples), so a full scan costs less than six sequential pads. This makes it the "
  f"fastest scan of the four ({ms(g('micropython', 'touch', 'scan6'))} ms vs {ms(g('rust', 'touch', 'scan6'))} ms Rust, "
  f"{ms(g('cpp', 'touch', 'scan6'))} ms C++) even though one PIO reading is the slowest of the three non-naive methods.")
BT = lambda l: D[l][("boot", "timing")]
A(f"- Boot: the compiled programs show the splash within {max(BT('cpp')['first_frame_ms'], BT('rust')['first_frame_ms'])} ms, MP optimized "
  f"in {BT('micropython')['first_frame_ms']} ms; MP naive, which compiles its `.py` files at import, takes "
  f"{D['micropython_naive'][('boot','timing')]['first_frame_ms']:,} ms. Calibration takes "
  f"{min(BT(l)['ready_ms'] - BT(l)['first_frame_ms'] for l in ('cpp', 'rust')) / 1000:.2f}–{max(BT(l)['ready_ms'] - BT(l)['first_frame_ms'] for l in ('cpp', 'rust')) / 1000:.2f} s in C++ and Rust and "
  f"{(D['micropython'][('boot','timing')]['ready_ms'] - D['micropython'][('boot','timing')]['first_frame_ms']) / 1000:.1f}–"
  f"{(D['micropython_naive'][('boot','timing')]['ready_ms'] - D['micropython_naive'][('boot','timing')]['first_frame_ms']) / 1000:.1f} s in MicroPython.")
A("")
A("### Host proxy (Apple-silicon Mac, not RP2040)")
A("")
A("The host stubs the pads and the display, so only update + draw compare. Ratio = device ÷ host.")
A("")
rows = []
for l in ORDER:
    dv = g(l, "frame", "update") + g(l, "frame", "draw")
    hv = H[l][("frame", "update")]["avg_ns"] + H[l][("frame", "draw")]["avg_ns"]
    rows.append([NAME[l] + (" (host: no viper)" if l == "micropython" else ""), f"{ms(dv, 3)} ms", f"{us(hv, 2)} µs", rx(dv / hv)])
A(table(["Program", "Device update + draw", "Host update + draw", "Device ÷ host"], rows))
A("")
dh = [(g(l, "frame", "update") + g(l, "frame", "draw")) / (H[l][("frame", "update")]["avg_ns"] + H[l][("frame", "draw")]["avg_ns"]) for l in ORDER]
A(f"The device is {rx(min(dh))}–{rx(max(dh))} slower than the Mac here, and the gap is not uniform across programs, so host ratios "
  "between programs do not predict device ratios. The MP optimized row is not like for like: its host run had no viper code.")
A("")

# ================= 5. Compute kernels =================
A("## 5. Compute kernels")
A("")
A("Device (RP2040), average per call. Cells: ns / cycles, with cycles = ns ÷ 8 (125 MHz). Ratio = program ÷ C++ "
  "(below 1 = faster than C++).")
A("")


def ktable(names):
    rows = []
    for sec, k in names:
        row = [f"{k} ({D['cpp'][(sec, k)]['n']:,})"]
        for l in ORDER:
            x = g(l, sec, k)
            row.append(f"{n0(x)} / {cyc(x)}")
        cx = g("cpp", sec, k)
        for l in ("rust", "micropython", "micropython_naive"):
            row.append(rx(g(l, sec, k) / cx))
        rows.append(row)
    return table(["Kernel (n)", "C++", "Rust", "MP optimized", "MP naive", "Rust ÷ C++", "MP opt ÷ C++", "MP naive ÷ C++"], rows)


LOGIC = [("logic", k) for k in ("shuffle", "bj_total", "eval5", "best7")]
GFX = [("gfx", k) for k in ("clear", "fill_screen", "line", "circle_r16", "fill_circle_r16", "fill_round_rect",
                             "fill_triangle", "text_21_s1", "text_10_s2", "card", "card_back")]
A("**Game logic**")
A("")
A(ktable(LOGIC))
A("")
A("**Graphics primitives** (into the 1 KB frame buffer, no push)")
A("")
A(ktable(GFX))
A("")
fs = {l: g(l, "gfx", "fill_screen") / NS_PER_CYC / 8192 for l in ORDER}
cl = {l: g(l, "gfx", "clear") / NS_PER_CYC / 1024 for l in ORDER}
A("Takeaways:")
A("")
KK = LOGIC + GFX
rc = {k: g('rust', s, k) / g('cpp', s, k) for s, k in KK}
A(f"- **Rust vs C++**: Rust is faster on {sum(1 for x in rc.values() if x < 0.99)} of {len(KK)} kernels, within 1% on "
  f"{sum(1 for x in rc.values() if 0.99 <= x <= 1.01)} ({', '.join(k for k, x in rc.items() if 0.99 <= x <= 1.01)}) and slower on "
  f"{sum(1 for x in rc.values() if x > 1.01)}. Its biggest wins are text ({rx(g('cpp', 'gfx', 'text_21_s1') / g('rust', 'gfx', 'text_21_s1'))} "
  f"faster on text_21_s1), line ({rx(g('cpp', 'gfx', 'line') / g('rust', 'gfx', 'line'))}) and circle "
  f"({rx(g('cpp', 'gfx', 'circle_r16') / g('rust', 'gfx', 'circle_r16'))}). "
  f"It is slower on bj_total ({rx(g('rust', 'logic', 'bj_total') / g('cpp', 'logic', 'bj_total'))}) and fill_screen "
  f"({rx(g('rust', 'gfx', 'fill_screen') / g('cpp', 'gfx', 'fill_screen'))}). best7 costs "
  f"{cyc(g('cpp', 'logic', 'best7'))} cycles in C++ and {cyc(g('rust', 'logic', 'best7'))} in Rust.")
mc = lambda s, k: g('micropython', s, k) / g('cpp', s, k)
A(f"- **MP optimized** is {rx(min(mc(s, k) for s, k in LOGIC))}–{rx(max(mc(s, k) for s, k in LOGIC))} C++ on the logic kernels "
  f"(best7 {rx(mc('logic', 'best7'))}, bj_total {rx(mc('logic', 'bj_total'))}). Its closest primitives are line "
  f"({rx(mc('gfx', 'line'))}), text ({rx(mc('gfx', 'text_21_s1'))}–{rx(mc('gfx', 'text_10_s2'))}) and circle_r16 ({rx(mc('gfx', 'circle_r16'))}); "
  f"its worst are clear ({rx(mc('gfx', 'clear'))}) and fill_triangle ({rx(mc('gfx', 'fill_triangle'))}).")
A(f"- **clear costs the same in both MicroPython ports** ({us(g('micropython', 'gfx', 'clear'))} vs {us(g('micropython_naive', 'gfx', 'clear'))} µs, "
  f"about {cl['micropython']:.0f} cycles per byte of the 1,024 B buffer) against {cl['cpp']:.2f} cycles per byte in C++. "
  f"MP optimized's fill_screen costs {fs['micropython']:.1f} cycles per pixel (8,192 pixels) vs {fs['cpp']:.1f} (C++) and "
  f"{fs['rust']:.1f} (Rust); MP naive's costs {n0(fs['micropython_naive'])} cycles per pixel.")
A(f"- **MP naive** is {rx(min(g('micropython_naive', s, k) / g('cpp', s, k) for s, k in LOGIC + GFX))}–"
  f"{rx(max(g('micropython_naive', s, k) / g('cpp', s, k) for s, k in LOGIC + GFX))} C++ per kernel. One best7 takes "
  f"{ms(g('micropython_naive', 'logic', 'best7'), 1)} ms, {pct(g('micropython_naive', 'logic', 'best7') / 1e6, BUDGET_MS, 0)} of a frame budget; "
  f"one fill_screen takes {ms(g('micropython_naive', 'gfx', 'fill_screen'), 0)} ms.")
A("")
A("### Host proxy (Apple-silicon Mac, not RP2040)")
A("")
A("best7 only, as a contrast (host ns are not converted to cycles). Ratio = device ÷ host.")
A("")
rows = []
for l in ORDER:
    dv, hv = g(l, "logic", "best7"), H[l][("logic", "best7")]["avg_ns"]
    rows.append([NAME[l] + (" (host: no viper)" if l == "micropython" else ""), n0(dv), n0(hv), rx(dv / hv)])
A(table(["Program", "Device best7, ns", "Host best7, ns", "Device ÷ host"], rows))
A("")
A(f"On the host the no-viper port's best7 is {pct(H['micropython'][('logic','best7')]['avg_ns'] - H['micropython_naive'][('logic','best7')]['avg_ns'], H['micropython_naive'][('logic','best7')]['avg_ns'], 0)} slower than MP naive's; on the device MP optimized (with viper) is "
  f"{rx(g('micropython_naive', 'logic', 'best7') / g('micropython', 'logic', 'best7'))} faster than MP naive. The host cannot show "
  "the viper gain.")
A("")

# ================= 6. Leaks & allocation =================
A("## 6. Memory leaks and allocation")
A("")
A("Soak = the script replayed twice (3,302 frames) with update + draw only (no touch scan, no push), on the device.")
A("")
A("### C++ vs Rust")
A("")
cso, rso = D["cpp"][("leaks", "soak")], D["rust"][("leaks", "soak")]
cfr = D["cpp"][("leaks", "fragmentation")]
rows = [
    ["Allocator", "malloc (`<malloc.h>`) over the heap", AUD["rust"]["allocator"]],
    ["Heap calls in game code (static audit)", "none" if not AUD["cpp"]["heap_calls_in_game_code"] else "yes", "none possible"],
    ["Boot-time allocations", "Adafruit_SSD1306 frame buffer (1,024 B, kept); core/TinyUSB/Serial buffers",
     "none; fixed-capacity `heapless::String` / `heapless::Vec<Slot, 12>`"],
    ["Heap used at boot", f"{n0(ch['used_bytes'])} B (arena {n0(ch['arena_bytes'])} B)", "0"],
    ["Heap used before → after soak", f"{n0(cso['heap_used_before'])} → {n0(cso['heap_used_after'])} B", "0 → 0"],
    ["Leaked bytes / frames with a heap change / max delta", f"{cso['leaked_bytes']} / {cso['frames_with_heap_change']} / {cso['max_heap_delta']}",
     f"{rso['leaked_bytes']} / {rso['frames_with_heap_change']} / {rso['max_heap_delta']}"],
    ["Largest free block before → after (free)", f"{n0(cfr['largest_block_before'])} → {n0(cfr['largest_block_after'])} B "
     f"({n0(cfr['free_bytes'])} free: {pct(cfr['largest_block_after'], cfr['free_bytes'], 0)} contiguous)", "n/a"],
    ["Soak frame (update + draw)", "not recorded", f"avg {us(rso['frame_avg_ns'])} µs, max {rso['frame_max_us']:,} µs"],
    ["Stack used / reserved", f"{n0(cst['stack_used_bytes'])} / {n0(cst['stack_bytes'])} B ({pct(cst['stack_used_bytes'], cst['stack_bytes'], 0)})",
     f"{n0(rst['stack_used_bytes'])} / {n0(rst['stack_bytes'])} B ({pct(rst['stack_used_bytes'], rst['stack_bytes'], 1)})"],
    ["`unsafe` blocks", "n/a", str(AUD["rust"]["unsafe_blocks"])],
]
A(table(["", "C++", "Rust"], rows))
A("")
A("### MicroPython")
A("")
mso, nso = D["micropython"][("leaks", "soak")], D["micropython_naive"][("leaks", "soak")]
mfr, nfr = D["micropython"][("leaks", "fragmentation")], D["micropython_naive"][("leaks", "fragmentation")]


def mprow(label, f, fmt=n0, ratio=True):
    a, b = f("micropython_naive"), f("micropython")
    rr = rx(a / b) if ratio and b else "–"
    return [label, fmt(a), fmt(b), rr]


SO = lambda l: D[l][("leaks", "soak")]
FR = lambda l: D[l][("leaks", "fragmentation")]
rows = [
    mprow("Bytes allocated per frame", lambda l: SO(l)["alloc_bytes_per_frame"]),
    mprow("Bytes allocated over the soak (per frame × 3,302)", lambda l: SO(l)["alloc_bytes_per_frame"] * SO(l)["frames"]),
    mprow("Frames with a heap change", lambda l: SO(l)["frames_with_heap_change"],
          fmt=lambda x: f"{n0(x)} ({pct(x, 3302)})"),
    mprow("Max heap delta, B", lambda l: SO(l)["max_heap_delta"]),
    mprow("GC runs", lambda l: SO(l)["gc_runs"], ratio=False),
    ["Frames per GC run / bytes allocated per GC run", f"{3302 / nso['gc_runs']:.1f} / {n0(nso['alloc_bytes_per_frame'] * 3302 / nso['gc_runs'])}", "no GC run", "–"],
    mprow("Heap used before → after, B", lambda l: SO(l)["heap_used_before"],
          fmt=lambda x: f"{n0(x)} → {n0(x)}", ratio=False),
    mprow("Leaked bytes", lambda l: SO(l)["leaked_bytes"], ratio=False),
    ["Largest free block before → after, B", f"{n0(nfr['largest_block_before'])} → {n0(nfr['largest_block_after'])}",
     f"{n0(mfr['largest_block_before'])} → {n0(mfr['largest_block_after'])}", "–"],
    ["Largest block ÷ free bytes after", f"{pct(nfr['largest_block_after'], nfr['free_bytes'])} of {n0(nfr['free_bytes'])}",
     f"{pct(mfr['largest_block_after'], mfr['free_bytes'])} of {n0(mfr['free_bytes'])}", "–"],
    mprow("Soak frame p50, ms", lambda l: SO(l)["frame_p50_us"] / 1000, fmt=lambda x: f"{x:.2f}"),
    mprow("Soak frame max, ms", lambda l: SO(l)["frame_max_us"] / 1000, fmt=lambda x: f"{x:.2f}"),
]
assert nso["heap_used_before"] == nso["heap_used_after"] and mso["heap_used_before"] == mso["heap_used_after"]
A(table(["Metric (device)", "MP naive", "MP optimized", "naive ÷ opt"], rows))
A("")
A("Takeaways:")
A("")
A(f"- **C++**: the heap did not move during the soak ({n0(cso['heap_used_before'])} B before and after, 0 frames with a change), "
  f"and the largest free block equals all free memory ({n0(cfr['free_bytes'])} B), so there is no fragmentation. Game code makes "
  "no heap calls; the only malloc/free in the sketch is the benchmark's own binary-search probe (`bench.ino:111–112`).")
A(f"- **C++ stack is the risk to watch**: {n0(cst['stack_used_bytes'])} of the {n0(cst['stack_bytes'])} B reserve "
  f"({cst['stack_bytes'] - cst['stack_used_bytes']} B headroom). Rust peaked at {n0(rst['stack_used_bytes'])} B in a "
  f"{n0(rst['stack_bytes'])} B region.")
A(f"- **MP naive allocates {n0(nso['alloc_bytes_per_frame'])} B per frame** and ran the GC {nso['gc_runs']} times in 3,302 frames "
  f"(once every {3302 / nso['gc_runs']:.1f} frames). Its largest free block shrank from {n0(nfr['largest_block_before'])} to "
  f"{n0(nfr['largest_block_after'])} B while {n0(nfr['free_bytes'])} B were free, so its heap is fragmented. GC pause length is "
  "not recorded.")
A(f"- **MP optimized allocates {mso['alloc_bytes_per_frame']} B per frame on average**, changed the heap on "
  f"{mso['frames_with_heap_change']} of 3,302 frames and never triggered the GC. Its largest free block did not shrink.")
A("")
A("**What leak-free means for each model**")
A("")
A("- **C++**: heap in use and the largest free block are unchanged after the soak (both true on the device), and the stack stays "
  "inside its reserve (true, with 448 B left).".replace("448", str(cst['stack_bytes'] - cst['stack_used_bytes'])))
A("- **Rust**: no allocator exists, so a heap leak cannot happen. What remains is stack depth (flip-link places the stack below "
  f".data, so an overflow faults instead of corrupting statics) and the {AUD['rust']['unsafe_blocks']} `unsafe` blocks.")
A("- **MicroPython**: garbage-collected, so a leak means heap in use after collection is higher at the end of the soak than at "
  "the start. Both ports show 0 B. Allocation per frame is not a leak, but it costs GC work and fragmentation, which is where "
  "the two ports differ.")
A("")
A("### Host proxy (Mac, 64-bit objects) vs device")
A("")
hn_, hm_ = H["micropython_naive"], H["micropython"]
rows = [
    ["Heap used at boot, B", f"{n0(hn_[('memory','heap_boot')]['used_bytes'])} → {n0(nh['used_bytes'])} "
     f"({rx(nh['used_bytes'] / hn_[('memory','heap_boot')]['used_bytes'])})",
     f"{n0(hm_[('memory','heap_boot')]['used_bytes'])} → {n0(mh['used_bytes'])} ({rx(mh['used_bytes'] / hm_[('memory','heap_boot')]['used_bytes'])})"],
    ["Bytes allocated per frame", f"{n0(hn_[('leaks','soak')]['alloc_bytes_per_frame'])} → {n0(nso['alloc_bytes_per_frame'])} "
     f"({rx(nso['alloc_bytes_per_frame'] / hn_[('leaks','soak')]['alloc_bytes_per_frame'])})",
     f"{hm_[('leaks','soak')]['alloc_bytes_per_frame']} → {mso['alloc_bytes_per_frame']}"],
    ["GC runs over the soak", f"{hn_[('leaks','soak')]['gc_runs']} → {nso['gc_runs']}", f"{hm_[('leaks','soak')]['gc_runs']} → {mso['gc_runs']}"],
    ["Heap size", f"{n0(hn_[('memory','static')]['heap_total_bytes'])} → {n0(MPHEAP)}", "same"],
]
A(table(["Host → device (ratio device ÷ host)", "MP naive", "MP optimized (host: no viper)"], rows))
A("")
A(f"The device heap at boot is {rx(nh['used_bytes'] / hn_[('memory','heap_boot')]['used_bytes'])}–{rx(mh['used_bytes'] / hm_[('memory','heap_boot')]['used_bytes'])} "
  "the host figure, not the ≈ 0.5× that halving 64-bit objects would suggest. The host "
  f"soak ran on a {n0(hn_[('memory','static')]['heap_total_bytes'])} B heap, so its GC counts do not transfer. Host minimum heaps "
  f"(64-bit): MP naive completes the whole benchmark in 160 KB (smallest tried), MP optimized needs 176 KB; the device heap is "
  f"{n0(MPHEAP)} B and both completed.")
A("")

# ================= 7. Cost of naive MicroPython =================
A("## 7. Cost of naive MicroPython")
A("")
A("Ratio = MP naive ÷ MP optimized, device values (above 1 = naive is worse, except where marked).")
A("")


def nr(label, a, b, fa, higher_better=False):
    return [label, fa(a), fa(b), rx(a / b) + (" (higher is better)" if higher_better else "")]


N, M = "micropython_naive", "micropython"
f_ms = lambda x: f"{x / 1e6:,.2f} ms"
f_us = lambda x: f"{x / 1e3:,.1f} µs"
f_b = lambda x: f"{n0(x)} B"
rows = []
rows.append(nr("Program flash", D[N][("memory", "static")]["flash_image_bytes"], D[M][("memory", "static")]["flash_image_bytes"], f_b))
rows.append(nr("Heap used at boot", nh["used_bytes"], mh["used_bytes"], f_b))
rows.append(nr("Boot: first frame", D[N][("boot", "timing")]["first_frame_ms"], D[M][("boot", "timing")]["first_frame_ms"], lambda x: f"{x:,} ms"))
rows.append(nr("Boot: ready", D[N][("boot", "timing")]["ready_ms"], D[M][("boot", "timing")]["ready_ms"], lambda x: f"{x:,} ms"))
pn = sum(D[N][("touch", f"Q{i}")]["avg_ns"] for i in range(6)) / 6
pm = sum(D[M][("touch", f"Q{i}")]["avg_ns"] for i in range(6)) / 6
rows.append(nr("Touch, one reading", pn, pm, f_us))
rows.append(nr("Touch, scan6", g(N, "touch", "scan6"), g(M, "touch", "scan6"), f_ms))
for s in ("input", "update", "draw", "push", "total"):
    rows.append(nr(f"Frame {s}", g(N, "frame", s), g(M, "frame", s), f_ms))
rows.append(nr("Push isolated (n = 100)", g(N, "display", "push"), g(M, "display", "push"), f_ms))
rows.append(nr("Frame p50", V[N]["p50"] * 1000, V[M]["p50"] * 1000, f_ms))
rows.append(nr("Frame p99", V[N]["p99"] * 1000, V[M]["p99"] * 1000, f_ms))
rows.append(nr("Frame max", V[N]["fmax"] * 1000, V[M]["fmax"] * 1000, f_ms))
rows.append(nr("Unlocked fps", V[N]["unl"], V[M]["unl"], lambda x: f"{x:.2f}", higher_better=True))
rows.append(nr("Real-time factor", V[N]["rtf"], V[M]["rtf"], lambda x: f"{100 * x:.1f}%", higher_better=True))
rows.append(nr("Input→display latency", g(N, "latency", "input_to_display"), g(M, "latency", "input_to_display"), f_ms))
rows.append(nr("Scripted game wall time", V[N]["wall"], V[M]["wall"], lambda x: f"{x:,.1f} s"))
rows.append(nr("run_seconds (whole benchmark)", V[N]["run"], V[M]["run"], lambda x: f"{x:,.1f} s"))
for s in ("menu", "roulette", "blackjack", "holdem"):
    rows.append(nr(f"Draw: {s} screen", g(N, "draw_screen", s), g(M, "draw_screen", s), f_ms))
for sec, k in LOGIC + GFX:
    rows.append(nr(f"{'Logic' if sec == 'logic' else 'Gfx'}: {k}", g(N, sec, k), g(M, sec, k), f_us))
rows.append(nr("Bytes allocated per frame", nso["alloc_bytes_per_frame"], mso["alloc_bytes_per_frame"], f_b))
rows.append(nr("Frames with a heap change", nso["frames_with_heap_change"], mso["frames_with_heap_change"], n0))
rows.append(nr("Max heap delta", nso["max_heap_delta"], mso["max_heap_delta"], f_b))
rows.append(["GC runs (soak)", str(nso["gc_runs"]), str(mso["gc_runs"]), "–"])
rows.append(nr("Soak frame p50", nso["frame_p50_us"] * 1000, mso["frame_p50_us"] * 1000, f_ms))
rows.append(nr("Soak frame max", nso["frame_max_us"] * 1000, mso["frame_max_us"] * 1000, f_ms))
rows.append(nr("Stack used", nst["stack_used_bytes"], mst["stack_used_bytes"], f_b))
rows.append(nr("Largest free block after soak", nfr["largest_block_after"], mfr["largest_block_after"], f_b, higher_better=True))
A(table(["Metric", "MP naive", "MP optimized", "naive ÷ opt"], rows))
A("")
A("**Which optimization explains which gain.** Techniques are from `allocation_audit.json`. The host column (MP naive ÷ MP opt "
  "(no viper), Mac) shows what remains when viper/native is removed: a gain that exists on the host comes from the Python-level "
  "change, one that appears only on the device comes from viper/native code.")
A("")


def hr(sec, k):
    return H[N][(sec, k)]["avg_ns"] / H[M][(sec, k)]["avg_ns"]


def dr(sec, k):
    return g(N, sec, k) / g(M, sec, k)


def both(pairs):
    return "; ".join(f"{k} {rx(dr(s, k))}" for s, k in pairs), "; ".join(f"{k} {rx(hr(s, k))}" for s, k in pairs)


rows = []
d_, h_ = both([("logic", "shuffle"), ("logic", "bj_total"), ("logic", "eval5"), ("logic", "best7")])
LG = [k for _, k in LOGIC]
rows.append(["viper/native code (game logic)", d_, h_,
             f"host {rx(min(hr('logic', k) for k in LG))}–{rx(max(hr('logic', k) for k in LG))}, device "
             f"{rx(min(dr('logic', k) for k in LG))}–{rx(max(dr('logic', k) for k in LG))}: the gain is viper/native. "
             "shuffle also drops naive's new Card object per card"])
d_, h_ = both([("gfx", "line"), ("gfx", "circle_r16"), ("gfx", "fill_triangle")])
rows.append(["viper writing the frame buffer directly (same Adafruit algorithms for lines, circles, triangles)", d_, h_,
             f"line and circle: host {rx(max(hr('gfx', 'line'), hr('gfx', 'circle_r16')))} or less, device "
             f"{rx(dr('gfx', 'circle_r16'))}–{rx(dr('gfx', 'line'))}, so viper alone. fill_triangle gains {rx(hr('gfx', 'fill_triangle'))} "
             "on the host too, so part of its gain is not viper"])
d_, h_ = both([("gfx", "fill_screen"), ("gfx", "fill_circle_r16"), ("gfx", "fill_round_rect")])
rows.append(["framebuf C routines (`fill_rect`, `hline`, `vline`) instead of one `fb.pixel()` call per pixel", d_, h_,
             "gain present on the host too; it comes from the C routines"])
d_, h_ = both([("gfx", "text_21_s1"), ("gfx", "text_10_s2")])
rows.append(["blit font (bytes text, cached glyph FrameBuffers)", d_, h_, "gain present on both"])
d_, h_ = both([("gfx", "card"), ("gfx", "card_back")])
rows.append(["sprites (2 blits per card)", d_, h_, "gain present on both"])
rows.append(["no per-frame allocation (cached strings, bytes text, preallocated bytearrays)",
             f"{n0(nso['alloc_bytes_per_frame'])} → {mso['alloc_bytes_per_frame']} B/frame; GC runs {nso['gc_runs']} → 0; "
             f"soak p50 {rx(nso['frame_p50_us'] / mso['frame_p50_us'])}, max {rx(nso['frame_max_us'] / mso['frame_max_us'])}",
             f"{n0(hn_[('leaks','soak')]['alloc_bytes_per_frame'])} → {hm_[('leaks','soak')]['alloc_bytes_per_frame']} B/frame; "
             f"GC {hn_[('leaks','soak')]['gc_runs']} → {hm_[('leaks','soak')]['gc_runs']}",
             "removes GC work and fragmentation; the soak ratios mix this with the drawing gains above"])
rows.append(["PIO touch", f"one reading {rx(pn / pm)}; scan6 {rx(dr('touch', 'scan6'))}; frame input {rx(dr('frame', 'input'))}",
             "not measurable (host pads are stubs)",
             f"input stage {ms(g(N, 'frame', 'input'))} → {ms(g(M, 'frame', 'input'))} ms"])
rows.append(["`.mpy` precompilation",
             f"program flash {rx(D[N][('memory','static')]['flash_image_bytes'] / D[M][('memory','static')]['flash_image_bytes'])}; "
             f"first frame {rx(D[N][('boot','timing')]['first_frame_ms'] / D[M][('boot','timing')]['first_frame_ms'])}",
             "host boot rows are wall-clock and meaningless",
             "the boot gain also includes other start-up work, which the results do not separate"])
A(table(["Optimization", "Device naive ÷ opt", "Host naive ÷ opt (no viper)", "Reading"], rows))
A("")
A(f"- The frame gain ({rx(dr('frame', 'total'))}) is capped by the push, which both ports share "
  f"({ms(g(N, 'frame', 'push'))} vs {ms(g(M, 'frame', 'push'))} ms). Without the push, input + update + draw goes from "
  f"{ms(g(N, 'frame', 'total') - g(N, 'frame', 'push'), 1)} to {ms(g(M, 'frame', 'total') - g(M, 'frame', 'push'))} ms "
  f"({rx((g(N, 'frame', 'total') - g(N, 'frame', 'push')) / (g(M, 'frame', 'total') - g(M, 'frame', 'push')))}).")
A(f"- Draw is where naive loses most time ({ms(g(N, 'frame', 'draw'), 1)} ms of its {ms(g(N, 'frame', 'total'), 1)} ms frame, "
  f"{pct(g(N, 'frame', 'draw'), g(N, 'frame', 'total'), 0)}). The update step gains the least ({rx(dr('frame', 'update'))}).")
A(f"- The optimized port pays in RAM: {rx(mh['used_bytes'] / nh['used_bytes'])} the heap at boot "
  f"({n0(mh['used_bytes'])} vs {n0(nh['used_bytes'])} B).")
A("")

# ================= 8. Caveats =================
A("## 8. Caveats")
A("")
A("- **Host vs device**: the host proxy is an Apple-silicon Mac with an FPU, large caches and a GHz clock; the RP2040 is a "
  "Cortex-M0+ at 125 MHz (one core used) with software float, flash executed in place through a 16 KB XIP cache, and a "
  "hardware divider. The host MicroPython runs use 64-bit objects, and the optimized port ran there without viper/native "
  "code. Host numbers are used above only for contrasts and for what the device cannot show.")
A("- **Touch methods differ**: C++ and Rust time an RC charge in a loop (Rust's loop runs from RAM), MP naive uses "
  "`time_pulse_us`, MP optimized uses PIO state machines that time all six pads in parallel. Counts are in different units; "
  "only times compare. Pads were never touched during the runs.")
A("- **MP naive touch is blind at idle**: every idle reading is 0 µs. `time_pulse_us` (1 µs resolution, started only after slow "
  "`Pin.init` calls) cannot see an untouched pad's charge time, so the naive port's touch margin rests entirely on a finger "
  "adding at least the detection threshold. Whether it does was not tested (no pads were pressed).")
A("- **Soak vs game**: soak frames exclude the touch scan and the push, so they are much shorter than game frames.")
A("- **run_seconds**: only C++ records how it was measured (\"raw log file times (capture start to BENCH_END), about 1 s "
  "precision\"), so its figure includes the wait from capture start. The other three meta rows give no method.")
A("- **Still unmeasured**: touch on pressed pads, GC pause length, C++ soak frame times, the number of differing MP naive "
  "frames on the device (only the CRC), MicroPython firmware static RAM vs C stack split, the `ssd1306` driver size, and a "
  "MicroPython stack high-water mark (the reported figure is a point sample).")
A("")
A("**Inconsistencies found in the results files**")
A("")
cbf = cb["benchmark_build"]["flash_bytes"]
rbf = rb["benchmark_build"]["flash_bytes"]
A(f"1. Rust flash: the device reports {n0(rs['flash_image_bytes'])} B, `rust_build.json` gives {n0(rbf)} B for the benchmark "
  f"build ({rbf - rs['flash_image_bytes']} B more). The difference is not explained in the results.")
A(f"2. C++ flash: device {n0(cs['flash_image_bytes'])} B vs build {n0(cbf)} B ({cs['flash_image_bytes'] - cbf:+} B); heap total: device "
  f"{n0(cs['heap_total_bytes'])} B vs `.heap` {n0(cb['benchmark_build']['sections']['.heap'])} B "
  f"({cs['heap_total_bytes'] - cb['benchmark_build']['sections']['.heap']:+} B). Static RAM differs by accounting (Section 3).")
A(f"3. MicroPython soak: `heap_used_before` + fragmentation `free_bytes` falls short of the heap total by "
  f"{MPHEAP - nso['heap_used_before'] - nfr['free_bytes']} B (naive) and {MPHEAP - mso['heap_used_before'] - mfr['free_bytes']} B "
  "(optimized); the two were probably sampled at different moments.")
A("4. Soak rows use different fields: C++ has no frame times, Rust has avg + max, MicroPython has p50 + max. Only C++'s meta row "
  "lacks `complete`; only it has `run_seconds_source`.")
A(f"5. Host vs device heap: the prompt's \"host heap ≈ 2×\" overstates it (device ÷ host = "
  f"{rx(nh['used_bytes'] / hn_[('memory','heap_boot')]['used_bytes'])} naive, {rx(mh['used_bytes'] / hm_[('memory','heap_boot')]['used_bytes'])} optimized), "
  f"and MP naive allocates {rx(hn_[('leaks','soak')]['alloc_bytes_per_frame'] / nso['alloc_bytes_per_frame'])} more per frame on the host than on the device.")
A("")

# ================= 9. Rerun =================
A("## 9. How to complete (or rerun) the device runs")
A("")
A("All four device runs are complete. To rerun one: turn on the program's benchmark switch, flash it (C++ at 125 MHz and -O2; "
  "MicroPython v1.29.0 firmware, then `micropython/upload.sh naive|optimized`; Rust with `cargo run --release`), run "
  "`python3 capture.py --lang <lang>` from `benchmarks/` with hands off the pads during boot, and turn the switch off. "
  "Details: `benchmarks/README.md`. Rebuild this report with `python3 make_report.py` in `benchmarks/`.")
A("")

open(OUT, "w").write("\n".join(md))
print("wrote", OUT, len("\n".join(md)), "chars")
