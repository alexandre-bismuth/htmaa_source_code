"""Synthesised sound for the STi: EJ207 2.0 L turbo flat-four with unequal-length headers
(the Subaru "boxer rumble"), turbo spool, blow-off valve, overrun pops, tyre squeal.

Usage:  uv run make_engine_audio.py
Output: data/processed/common/audio/*.wav   (16-bit mono 44.1 kHz; loops are seamless)
        (stale engine_*.wav / pop_*.wav from older runs are deleted first: import_car.py imports
        every wav in that folder)

Engine loops engine_on_<rpm> (full load) and engine_off_<rpm> (overrun) at RPMS, a geometric
grid (ratio ~1.25) so the game never pitch-shifts a loop by more than ~12 % while it is audible.
Physical model, per loop (everything circular over exactly N engine cycles -> seamless):
- Firing order 1-3-2-4, one firing every 180 deg of crank. Cylinders 1/3 are the right bank, 2/4
  the left, so each bank fires twice in a row then rests for a revolution.
- Each firing is an exhaust blowdown pulse whose shape is fixed in CRANK ANGLE (fast rise, ~40 deg
  decay, then the displacement plateau of the exhaust stroke): fat and deep at idle (~10 ms),
  short and sharp at redline (~1 ms).
- Unequal-length headers: the left bank's pulses travel ~0.9 ms further, arrive weaker and more
  smeared (darker) than the right bank's. Per revolution the bank pattern R R L L gives strong
  half- and first-order content: the "wub-wub". Cycle-to-cycle combustion variation (amplitude,
  timing, a rare lazy cycle at idle) and slow idle hunting keep it alive without stumbling
  (round 3 playtest: the lumpier idle sounded "cranky").
- Exhaust: turbine (smooths the pulses), two quarter-wave pipe sections (downpipe ~1.2 m, cat-back
  ~2.6 m: resonances at ~45/135/225 Hz and ~100/300 Hz), saturation that grows with rpm x load
  (the "angry" part), then a big muffler (Helmholtz low-pass with a ~140 Hz boom plus a
  straight-through bypass that opens with rpm x load).
- On load only: pulse-gated tailpipe rasp, a metallic heat-shield ring and intake roar, all
  growing steeply with rpm (nothing at idle: no steady noise bed -> no "vacuum").
- Overrun: weak, irregular pulses (lean, partly misfiring), darker muffler. The pops themselves
  are one-shots (pop_1..pop_5) fired at random by the game so they never repeat with the loop.

The game (UStiEngineAudio) crossfades neighbouring rpm loops, pitches them by rpm / loop_rpm and
keeps them crank-locked; tools/mapgen/render_engine_demo.py renders an offline demo with the same
mixer.
"""
from fractions import Fraction
from pathlib import Path

import numpy as np
from scipy.io import wavfile

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/processed/common/audio"
FS = 44100
RPMS = [800, 1000, 1250, 1550, 1950, 2450, 3050, 3800, 4750, 5950, 7400]
REDLINE = 8000.0
PEAK = 0.89                                   # shared peak of the engine-loop family
# TONE scales the fixed resonances (muffler boom, pipes, bank/turbine low-passes, airbox): round 3 of
# playtesting asked for less low than 1.0 (round 2 had asked for deeper); the user picked 1.18 over 1.10.
TONE = float(__import__("os").environ.get("STI_TONE", "1.18"))

# firing order 1-3-2-4: (cylinder, bank, crank angle of exhaust-valve opening)
FIRING = ((1, 0, 0.0), (3, 0, 180.0), (2, 1, 360.0), (4, 1, 540.0))
CYL_GAIN = {1: 1.0, 3: 0.85, 2: 0.78, 4: 0.62}
BANK_DELAY_S = (0.0, 0.0012)                  # long (left) headers: extra travel time
BANK_DELAY_DEG = (0.0, 8.0)                   # ... and slightly later effective arrival
BANK_WIDTH = (1.0, 1.5)                       # ... smeared pulses
BANK_LP = (3000.0, 1150.0)                    # ... darker (x TONE)
C_HOT = 470.0                                 # m/s, speed of sound in the exhaust
PIPES = ((2.6, 0.55), (1.2, 0.35))            # quarter-wave sections: (length m / TONE, reflection)


# ---------------------------------------------------------------- frequency-domain helpers
def lp1(f, fc):
    return 1.0 / (1.0 + 1j * f / fc)


def lp2(f, fc, q=0.707):
    s = 1j * f / fc
    return 1.0 / (1.0 + s / q + s * s)


def hp2(f, fc, q=0.707):
    s = 1j * f / fc
    return s * s / (1.0 + s / q + s * s)


def peak(f, f0, q, gain):
    """Resonant band-pass (complex, unit peak) scaled by gain, to add to 1."""
    s = 1j * f / f0
    return gain * (s / q) / (1.0 + s / q + s * s)


def pipe(f, length, refl):
    """Quarter-wave pipe section: the open end reflects with -refl, loss grows with frequency."""
    tau = 2.0 * length / TONE / C_HOT
    g = refl / np.sqrt(1.0 + (f / 500.0) ** 2)
    return (1.0 + refl) / (1.0 + g * np.exp(-2j * np.pi * f * tau))


def muffler(f, bypass, f_bypass):
    fb = 140.0 * TONE
    helmholtz = 1.0 / (1.0 - (f / fb) ** 2 + 1j * f / (fb * 1.4))
    return helmholtz + bypass * lp2(f, f_bypass)


def filt(x, h):
    return np.fft.irfft(np.fft.rfft(x) * h, len(x))


def band_noise(rng, n, h):
    return filt(rng.normal(size=n), h)


def rms(x):
    return float(np.sqrt(np.mean(x * x)) + 1e-12)


def k_loudness(x):
    """Approximate BS.1770 loudness (K-weighting, dB) of a loop."""
    f = np.fft.rfftfreq(len(x), 1.0 / FS)
    k = np.abs(hp2(f, 38.0, 0.5)) * np.sqrt(1.0 + 0.585 * (f / 1500.0) ** 2 / (1.0 + (f / 1500.0) ** 2))
    return 10 * np.log10(np.mean(filt(x, k) ** 2) + 1e-20)


# ---------------------------------------------------------------- engine
def loop_length(rpm):
    """An exact whole number of samples AND of engine cycles, so a loop played at rpm / loop_rpm
    keeps the same crank phase as every other loop forever (no rounding drift between loops)."""
    per_cycle = Fraction(120 * FS, rpm)       # samples per 720-degree engine cycle
    q = per_cycle.denominator                 # cycles must come in multiples of q
    loop_s = 4.0 if rpm <= 1250 else 3.0      # longer idle loops: the lumps repeat less often
    n_cycles = q * max(1, round(loop_s / (q * 120.0 / rpm)))
    n = n_cycles * per_cycle
    assert n.denominator == 1
    return int(n), n_cycles


def pulse_shape(psi, width, rpm):
    """Exhaust-port pressure vs crank angle after the pulse arrives (deg): blowdown + displacement.
    Rise and decay are crank angles, floored in time (the valve and the gas can't do it faster
    than ~0.25 ms / ~0.9 ms) so redline pulses are sharp but not a sample-step buzz."""
    deg_per_ms = 6.0 * rpm / 1000.0
    a, d = max(2.5 * width, 0.25 * deg_per_ms), max(28.0 * width, 0.9 * deg_per_ms)
    p = np.where(psi >= 0, (1.0 - np.exp(-np.maximum(psi, 0) / a)) ** 2 * np.exp(-np.maximum(psi, 0) / d), 0.0)
    p /= 0.75                                  # ~unit peak
    disp = 0.06 * np.sin(np.pi * np.clip(psi / 240.0, 0.0, 1.0)) ** 2
    return p + disp


def engine_loop(rpm, on):
    n, cycles = loop_length(rpm)
    T = n / FS
    x = rpm / REDLINE                          # 0.1 .. 0.93
    rng = np.random.default_rng(rpm)           # same draws for the on and off loop -> crank-coherent
    t = np.arange(n) / FS
    f = np.fft.rfftfreq(n, 1.0 / FS)

    # crank angle vs time, with slow idle hunting (integer periods per loop -> seamless)
    theta = 720.0 * cycles * t / T
    hunt = max(0.0, 1.0 - (rpm - 800) / 700.0) * 0.005
    for m_hz, share in ((0.55, 0.6), (1.3, 0.4)):
        m = max(1, round(m_hz * T))
        theta += hunt * share * 720.0 * cycles / (2 * np.pi * m) * np.sin(2 * np.pi * m * t / T)
    omega = np.gradient(theta, t) / 6.0        # local rpm

    # per-cycle variation (shared by on/off: same z, different spread)
    z_amp = rng.normal(size=(cycles, 4))
    z_cyc = rng.normal(size=cycles)
    z_time = rng.normal(size=(cycles, 4))
    u_lazy = rng.random(size=(cycles, 4))
    idle = max(0.0, 1.0 - (rpm - 800) / 2500.0)
    if on:
        sd_amp, sd_deg, sd_cyc = 0.05 + 0.05 * idle, 0.4 + 0.4 * idle, 0.02 + 0.04 * idle
        p_lazy, lazy_gain, level = 0.015 * idle, 0.75, 1.0
    else:
        sd_amp, sd_deg, sd_cyc = 0.20, 1.4, 0.09
        p_lazy, lazy_gain, level = 0.06, 0.35, 0.30 if rpm > 1100 else 0.6

    banks = [np.zeros(n), np.zeros(n)]
    env = np.zeros(n)
    for c in range(cycles):
        for k, (cyl, bank, deg) in enumerate(FIRING):
            th = c * 720.0 + deg + BANK_DELAY_DEG[bank] + z_time[c, k] * sd_deg
            ta = np.interp(th, theta, t, period=None) if th < theta[-1] else T + np.interp(th - 720.0 * cycles, theta, t)
            ta += BANK_DELAY_S[bank]
            r_loc = float(np.interp(ta % T, t, omega))
            amp = level * CYL_GAIN[cyl] * max(0.05, 1.0 + z_amp[c, k] * sd_amp + z_cyc[c] * sd_cyc)
            if u_lazy[c, k] < p_lazy:
                amp *= lazy_gain
            span = int(330.0 / (6.0 * r_loc) * FS) + 2
            i0 = int(np.floor(ta * FS))
            idx = np.arange(i0, i0 + span)
            psi = (idx / FS - ta) * 6.0 * r_loc
            banks[bank][idx % n] += amp * pulse_shape(psi, BANK_WIDTH[bank], rpm)
            env[idx % n] += amp * np.exp(-np.maximum(psi, 0) / 25.0) * (psi >= 0)

    # turbulent texture on the gas pulses (multiplicative: silence stays silent)
    tex_depth = (0.25 + 0.35 * x) if on else 0.5
    tex_bw = (300.0 + 1500.0 * x) if on else (400.0 + 600.0 * x)
    coll = np.zeros(n)
    for b in (0, 1):
        tex = band_noise(rng, n, lp2(f, tex_bw))
        tex /= rms(tex)
        sig = banks[b] * (1.0 + tex_depth * np.clip(tex, -2.5, 2.5))
        coll += filt(sig, lp1(f, BANK_LP[b] * TONE))

    # turbine + pipes (AC from here on)
    coll = filt(coll, lp1(f, (2000.0 if on else 2500.0) * TONE) * hp2(f, 20.0))
    piped = filt(coll, pipe(f, *PIPES[0]) * pipe(f, *PIPES[1]))
    # saturation (exhaust gas / shell non-linearity): drive grows with rpm x load -> angry
    piped /= np.percentile(np.abs(piped), 99.5) + 1e-9
    drive = (1.0 + 3.2 * x ** 1.2) if on else (1.0 + 0.8 * x)
    bias = 0.25 if on else 0.1
    sat = (np.tanh(drive * (piped + bias)) - np.tanh(drive * bias)) / drive
    # muffler: big Helmholtz boom + straight-through bypass that opens with rpm x load
    if on:
        byp, f_byp = 0.45 + 0.30 * x ** 1.3, 1000.0 + 1800.0 * x ** 1.2
    else:
        byp, f_byp = 0.30, 900.0 + 1200.0 * x
    out = filt(sat, muffler(f, byp, f_byp) * hp2(f, 24.0))
    base = rms(out)

    def layer(sig, db):
        return sig / rms(sig) * base * 10 ** (db / 20.0)

    if on:
        # tailpipe rasp: band noise gated by the pulses (raspy, never a hiss bed)
        gate = env / (env.max() + 1e-9)
        gate = filt(gate, lp1(f, 900.0)).clip(0.0) ** 2
        rasp = band_noise(rng, n, hp2(f, 900.0) * lp2(f, 4500.0)) * gate
        out += layer(rasp, -40.0 + 25.0 * x ** 1.1)
        # metallic heat-shield / pipe-shell ring, excited by the pulses
        metal = filt(np.diff(np.r_[coll[-1], coll]), peak(f, 2350.0, 12.0, 1.0) + peak(f, 3650.0, 14.0, 0.6))
        out += layer(metal, -26.0 - 30.0 * (1.0 - x) ** 2)
        # intake roar: suction pulses (exhaust timing + 360 deg) through the airbox / hood scoop,
        # plus a little gated turbulence
        intake = np.roll(-(banks[0] + banks[1]), int(round(360.0 / (6.0 * rpm) * FS)))
        intake = filt(intake, (peak(f, 260.0 * TONE, 2.0, 1.0) + peak(f, 720.0 * TONE, 3.0, 0.7)) * lp1(f, 1500.0))
        roar = band_noise(rng, n, hp2(f, 500.0) * lp2(f, 2500.0)) * np.roll(gate, int(round(360.0 / (6.0 * rpm) * FS)))
        intake = intake / rms(intake) + 0.35 * roar / rms(roar)
        out += layer(intake, -34.0 + 21.0 * x ** 1.3)
    return out


# ---------------------------------------------------------------- loudness of the family
def target_loudness(rpm, on):
    """Deliberate loudness curve (relative dB): +12 dB from idle to redline on load; overrun quieter."""
    x = (rpm - 800.0) / (REDLINE - 800.0)
    db = 12.0 * x ** 0.8
    if not on:
        db -= 2.0 + 6.0 * min(1.0, x * 1.6)
    return db


# ---------------------------------------------------------------- one-shots and other loops
def exhaust_path(x, f, bypass=0.5, f_bypass=2200.0):
    return filt(x, pipe(f, *PIPES[0]) * pipe(f, *PIPES[1]) * muffler(f, bypass, f_bypass) * hp2(f, 35.0))


def pop(kind, seed):
    """Overrun afterfire: fuel lighting off in the hot exhaust -> muffled 'pop'/'brap'/crackle."""
    rng = np.random.default_rng(seed)
    n = int(FS * 0.30)
    f = np.fft.rfftfreq(n, 1.0 / FS)
    t = np.arange(n) / FS
    bangs = {
        "single": [(0.004, 1.0, 1.2)],
        "double": [(0.004, 1.0, 1.2), (0.049, 0.7, 1.0)],
        "crackle": [(0.004 + 0.022 * i + rng.uniform(0, 0.01), rng.uniform(0.25, 0.6), 0.6) for i in range(6)],
        "deep": [(0.004, 1.0, 3.0)],
        "brap": [(0.004, 0.8, 1.0), (0.031, 1.0, 1.2), (0.064, 0.6, 1.0)],
    }[kind]
    x = np.zeros(n)
    crack = np.zeros(n)
    for t0, a, decay_ms in bangs:
        d = np.clip(t - t0, 0, None)
        on = t >= t0
        x += a * on * (1 - np.exp(-d / 0.00015)) * np.exp(-d / (decay_ms * 0.001))
        crack += a * on * np.exp(-d / 0.003)
    body = exhaust_path(x, f, 0.25 if kind == "deep" else 0.55, 1400.0 if kind == "deep" else 2600.0)
    hf = band_noise(rng, n, hp2(f, 1800.0) * lp2(f, 6000.0)) * crack
    y = body / np.abs(body).max() + 0.25 * hf / (np.abs(hf).max() + 1e-9)
    y *= np.clip((0.30 - t) / 0.06, 0, 1)      # fade the tail
    return y


def whistle_loop():
    """Turbo spool: mostly air, not a tone (a pure-sine whine reads as an electric motor).
    Narrow resonant noise at the compressor's blade-pass (~1.6 kHz) and its double, a broad breath
    band underneath with a slow swell, and only a small sine core so it still whistles under boost.
    2 s, circular filtering + integer cycles of every sine / modulation -> seamless. The game pitches
    it with boost and keeps it quiet; it is RMS-matched to the old sine whistle (same in-game level)."""
    rng = np.random.default_rng(11)
    n = int(FS * 2.0)
    t = np.arange(n) / FS
    f = np.fft.rfftfreq(n, 1.0 / FS)
    f0 = 1600.0

    def reson(fc, q):
        w = f / fc
        return 1.0 / np.sqrt(1.0 + q * q * (w - 1.0 / np.maximum(w, 1e-6)) ** 2)

    def unit(x):
        return x / rms(x)

    blade = unit(band_noise(rng, n, reson(f0, 24.0) + 0.35 * reson(2 * f0, 20.0)))
    breath = unit(band_noise(rng, n, hp2(f, 600.0) * lp2(f, 5000.0) * (1.0 + 0.6 * reson(f0 * 0.9, 2.0))))
    swell = 1.0 + 0.15 * np.sin(2 * np.pi * 3.0 * t) + 0.08 * np.sin(2 * np.pi * 7.5 * t + 1.3)
    core = np.sqrt(2.0) * np.sin(2 * np.pi * f0 * t) * (1.0 + 0.05 * np.sin(2 * np.pi * 11.5 * t))
    return (blade + 0.45 * breath + 0.3 * core) * swell


def blowoff():
    """Blow-off valve 'pshh' (0.45 s): a chuff as the valve snaps open, then a hiss whose
    brightness falls as the charge pressure drains (upper bands decay faster)."""
    rng = np.random.default_rng(7)
    n = int(FS * 0.45)
    t = np.arange(n) / FS
    f = np.fft.rfftfreq(n, 1.0 / FS)
    attack = 1 - np.exp(-t / 0.003)
    y = np.zeros(n)
    for lo, hi, tau, g in ((2800, 7500, 0.07, 1.0), (1800, 4200, 0.11, 0.8), (900, 2400, 0.15, 0.45)):
        y += g * band_noise(rng, n, hp2(f, lo) * lp2(f, hi)) * np.exp(-t / tau)
    chuff = band_noise(rng, n, hp2(f, 250) * lp2(f, 1200)) * np.exp(-t / 0.018)
    y = y / rms(y[: n // 4]) + 0.9 * chuff / rms(chuff[: n // 20])
    y *= attack * np.clip((0.45 - t) / 0.08, 0, 1)
    return y


def squeal_loop():
    """Tyre squeal: narrow noise bands around 1-2 kHz with a slowly wandering tone."""
    rng = np.random.default_rng(3)
    n = int(FS * 2.0)
    t = np.arange(n) / FS
    f = np.fft.rfftfreq(n, 1.0 / FS)

    def reson(f0, q):
        w = f / f0
        return 1.0 / np.sqrt(1.0 + q * q * (w - 1.0 / np.maximum(w, 1e-6)) ** 2)

    bands = sum(g * reson(f0, 12.0) for f0, g in ((900, 0.6), (1400, 1.0), (2100, 0.5)))
    noise = np.fft.irfft(np.fft.rfft(rng.normal(size=n)) * bands, n)
    tone = 0.3 * np.sin(2 * np.pi * 1400 * t + 3.0 * np.sin(2 * np.pi * 1.5 * t))
    return noise + tone


def write(name, x, peak_in, peak_out=PEAK):
    y = x / peak_in * peak_out
    y = np.where(np.abs(y) > 0.8, np.sign(y) * (0.8 + 0.2 * np.tanh((np.abs(y) - 0.8) / 0.2)), y)  # soft knee
    wavfile.write(OUT / f"{name}.wav", FS, (np.clip(y, -1, 1) * 32767).astype(np.int16))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for stale in list(OUT.glob("engine_*.wav")) + list(OUT.glob("pop_*.wav")):
        stale.unlink()
    loops = {}
    for r in RPMS:
        for on in (True, False):
            y = engine_loop(r, on)
            loops[(r, on)] = y * 10 ** ((target_loudness(r, on) - k_loudness(y)) / 20.0)
    peak_all = max(np.abs(v).max() for v in loops.values())
    for (r, on), y in loops.items():
        write(f"engine_{'on' if on else 'off'}_{r}", y, peak_all)
    pops = [pop(k, 100 + i) for i, k in enumerate(("single", "double", "crackle", "deep", "brap"))]
    for i, y in enumerate(pops):
        write(f"pop_{i + 1}", y, np.abs(y).max())
    for name, y in (("blowoff", blowoff()), ("tyre_squeal", squeal_loop())):
        write(name, y, np.abs(y).max())
    # whistle: same RMS as the old sine whistle (0.44 of full scale); the turbo level is set in the game
    w = whistle_loop()
    write("turbo_whistle", w, rms(w) * PEAK / 0.44)
    print(f"{len(loops)} engine loops at {RPMS} rpm + {len(pops)} pops, whistle, blow-off, squeal -> {OUT}")


if __name__ == "__main__":
    main()
