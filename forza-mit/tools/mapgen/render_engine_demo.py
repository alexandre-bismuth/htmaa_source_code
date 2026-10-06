"""Offline audition of the STi sound: renders a ~40 s drive through the same mixer as the game.

Usage:  uv run make_engine_audio.py && uv run render_engine_demo.py
Output: data/processed/common/audio/demo/
          sti_demo.wav            idle, blips, launch and a pull through 1st-3rd with shifts, the rev
                                  limiter, lift-off to overrun with pops, braking, 3000 rpm cruise, idle
          sti_demo_low.wav        just the idle and the low-rev blips
          sti_demo_unlocked.wav   the same drive with the loops' crank lock deliberately broken
                                  (what it would sound like if UE restarted silent loops)
          *.png                   spectrogram, rpm/load/voice-gain traces, loop checks

Mixer: class Mixer is a line-by-line port of UStiEngineAudio::TickComponent
(CambridgeRacer/Source/CambridgeRacer/Impreza/StiEngineAudio.cpp): same constants, same order of
operations, same 60 Hz-ish tick. Voices are emulated like UE's mixer sources: they all start at
sample 0 in BeginPlay, play at the commanded pitch (clamped to 0.4..2.0, linear-interpolating
resampler) and their volume/pitch ramp linearly across each tick.
Car: a small longitudinal model with the game's torque curve, gearbox, boost model
(AImprezaSTi::UpdateEngine) and Chaos-style gear changes (0.25 s in neutral; the engine flares
with the throttle held, which the mixer must hide).
"""
import math

import matplotlib
import numpy as np
from scipy.io import wavfile

from make_engine_audio import FS, OUT, RPMS

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

DEMO = OUT / "demo"
TICK = 1.0 / 60.0

# ---------------------------------------------------------------- port of StiEngineAudio.cpp
NUM_POP_WAVES = 5
NUM_POP_VOICES = 2
# UE clamps every pitch to [GlobalMinPitchScale, GlobalMaxPitchScale] (Project Settings > Audio,
# default 0.4..2.0). The integrator sets 0.08..12 in DefaultEngine.ini so no loop is ever clamped;
# the demo uses that, render(..., pitch_range=(0.4, 2.0)) shows the stock setting (relock at work).
PITCH_RANGE = (0.08, 12.0)
XFADE_START, XFADE_END = 0.2, 0.8
XFADE_SHAPE = 1.5        # cos/sin^1.5: between equal-power (incoherent) and linear (coherent)
LOAD_CURVE = 0.75
RELOCK_GAIN = 0.15
LAUNCH_RPM = 4000.0
LIMITER_RPM = 7900.0
LIMITER_HZ = 14.0
SHIFT_RPM_FALL = 4000.0
POP_VOLUME = 0.40
WHISTLE_VOLUME = 0.0093   # whistle + blow-off -4.2 dB (round 3: "25 % quieter")
BLOWOFF_VOLUME = 0.124
MASTER_VOLUME = 2.0


def finterp_to(cur, target, dt, speed):
    """FMath::FInterpTo"""
    if speed <= 0:
        return target
    dist = target - cur
    if dist * dist < 1e-8:
        return target
    return cur + dist * min(max(dt * speed, 0.0), 1.0)


def wrap_cycles(x):
    return x - round(x)


class Voice:
    """A UAudioComponent playing a USoundWave (looping or one-shot)."""

    def __init__(self, wave, loop, pitch_range):
        self.wave, self.loop = wave, loop
        self.pitch_range = pitch_range
        self.pos = 0.0
        self.playing = False
        self.vol = self.vol_prev = 0.0
        self.pitch = self.pitch_prev = 1.0

    def set_sound(self, wave):
        self.wave = wave

    def play(self):
        self.pos, self.playing = 0.0, True

    def render(self, n):
        vol = np.linspace(self.vol_prev, self.vol, n, endpoint=False)
        pitch = np.clip(np.linspace(self.pitch_prev, self.pitch, n, endpoint=False), *self.pitch_range)
        self.vol_prev, self.pitch_prev = self.vol, self.pitch
        if not self.playing:
            return np.zeros(n)
        w = self.wave
        pos = self.pos + np.concatenate(([0.0], np.cumsum(pitch[:-1])))
        self.pos = pos[-1] + pitch[-1]
        if self.loop:
            pos %= len(w)
            self.pos %= len(w)
            i = pos.astype(int)
            fr = pos - i
            y = w[i] * (1 - fr) + w[(i + 1) % len(w)] * fr
        else:
            ok = pos < len(w) - 1
            i = np.minimum(pos.astype(int), len(w) - 2)
            fr = pos - i
            y = np.where(ok, w[i] * (1 - fr) + w[i + 1] * fr, 0.0)
            if self.pos >= len(w) - 1:
                self.playing = False
        return y * vol


class Mixer:
    """Port of UStiEngineAudio (BeginPlay + TickComponent)."""

    def __init__(self, waves, rng, master=MASTER_VOLUME, break_lock=False, pitch_range=PITCH_RANGE):
        self.rng = rng
        self.min_pitch, self.max_pitch = pitch_range
        self.master = master
        self.rpms = list(RPMS)
        self.on = [Voice(waves[f"engine_on_{r}"], True, pitch_range) for r in self.rpms]
        self.off = [Voice(waves[f"engine_off_{r}"], True, pitch_range) for r in self.rpms]
        self.smooth_rpm, self.smooth_load, self.prev_throttle = IDLE_RPM, 1.0, 0.0
        self.shift_rpm = self.limiter_clock = self.crackle = 0.0
        self.last_drive_gear, self.next_pop = 0, 0
        self.was_shifting = self.was_cut = False
        self.last_blowoff = self.last_pop = -10.0
        self.voice_pitch, self.phase_err = [], []
        for i, r in enumerate(self.rpms):
            p = min(max(self.smooth_rpm / r, self.min_pitch), self.max_pitch)
            self.voice_pitch.append(p)
            self.phase_err.append(0.0)
            for v in (self.on[i], self.off[i]):
                v.vol = v.vol_prev = 0.0
                v.pitch = v.pitch_prev = p
                v.play()
                if break_lock:            # what a restart-on-realisation would do: random crank phase
                    v.pos = rng.uniform(0, len(v.wave))
            if break_lock:
                self.off[i].pos = self.on[i].pos
        self.lock_rpm = self.smooth_rpm
        self.pop_waves = [waves[f"pop_{i}"] for i in range(1, NUM_POP_WAVES + 1)]
        self.pops = [Voice(self.pop_waves[0], False, pitch_range) for _ in range(NUM_POP_VOICES)]
        self.whistle = Voice(waves["turbo_whistle"], True, pitch_range)
        self.whistle.play()
        self.blowoff = Voice(waves["blowoff"], False, pitch_range)
        self.engine_voices = self.on + self.off
        self.voices = self.on + self.off + self.pops + [self.whistle, self.blowoff]
        self.log = []

    def fire_pop(self, volume, now):
        a = self.pops[self.next_pop % len(self.pops)]
        self.next_pop += 1
        a.set_sound(self.pop_waves[self.rng.integers(0, len(self.pop_waves))])
        a.vol = a.vol_prev = self.master * POP_VOLUME * volume * self.rng.uniform(0.55, 1.0)
        a.pitch = a.pitch_prev = self.rng.uniform(0.85, 1.15)
        a.play()
        self.last_pop = now

    def tick(self, dt, now, rpm_engine, throttle, boost, gear, target_gear):
        rpms = self.rpms
        # crank lock: integrate each loop's phase error over the last tick
        for i in range(len(rpms)):
            self.phase_err[i] = wrap_cycles(self.phase_err[i] + (self.voice_pitch[i] * rpms[i] - self.lock_rpm) / 120.0 * dt)

        rpm = rpm_engine
        if gear in (1, -1) and rpm < LAUNCH_RPM and throttle > 0.05:
            rpm = rpm + (LAUNCH_RPM - rpm) * throttle
        shifting = gear == 0 and target_gear != 0
        if shifting and not self.was_shifting and target_gear > self.last_drive_gear and self.last_drive_gear >= 1:
            if boost > 0.45 and now - self.last_blowoff > 0.5:
                self.last_blowoff = now
                b = self.blowoff
                b.vol = b.vol_prev = self.master * BLOWOFF_VOLUME * boost
                b.pitch = b.pitch_prev = self.rng.uniform(0.92, 1.08)
                b.play()
            self.crackle = max(self.crackle, 0.35)
        self.shift_rpm = max(self.shift_rpm - SHIFT_RPM_FALL * dt, float(rpms[0])) if shifting else rpm
        if shifting:
            rpm = min(rpm, self.shift_rpm)
        self.was_shifting = shifting
        if gear != 0:
            self.last_drive_gear = gear
        limiter = rpm >= LIMITER_RPM and throttle > 0.5
        self.limiter_clock = self.limiter_clock + dt if limiter else 0.0
        cut = limiter and (self.limiter_clock * LIMITER_HZ) % 1.0 < 0.5
        if cut:
            rpm -= 250.0
            if not self.was_cut and self.rng.random() < 0.25 and now - self.last_pop > 0.07:
                self.fire_pop(0.7, now)
        self.was_cut = cut
        rpm = min(max(rpm, rpms[0] * 0.9), 8000.0)
        self.smooth_rpm = finterp_to(self.smooth_rpm, rpm, dt, 25.0)

        idle_on = 1.0 - min(max((self.smooth_rpm - 1100.0) / 600.0, 0.0), 1.0)
        target_load = idle_on if (shifting or cut) else max(throttle, idle_on)
        self.smooth_load = finterp_to(self.smooth_load, target_load, dt, 60.0 if (shifting or limiter) else 12.0)

        lo = 0
        while lo + 1 < len(rpms) - 1 and rpms[lo + 1] <= self.smooth_rpm:
            lo += 1
        t = min(max((self.smooth_rpm - rpms[lo]) / float(rpms[lo + 1] - rpms[lo]), 0.0), 1.0)
        u = min(max((t - XFADE_START) / (XFADE_END - XFADE_START), 0.0), 1.0)
        on_gain = self.smooth_load ** LOAD_CURVE
        off_gain = (1.0 - self.smooth_load) ** LOAD_CURVE
        weights = []
        for i in range(len(rpms)):
            w = math.cos(u * math.pi / 2) ** XFADE_SHAPE if i == lo else (math.sin(u * math.pi / 2) ** XFADE_SHAPE if i == lo + 1 else 0.0)
            p = self.smooth_rpm / rpms[i]
            if w <= 0.0:
                p *= 1.0 - RELOCK_GAIN * self.phase_err[i]
            p = min(max(p, self.min_pitch), self.max_pitch)
            self.voice_pitch[i] = p
            self.on[i].vol = self.master * w * on_gain
            self.off[i].vol = self.master * w * off_gain
            self.on[i].pitch = self.off[i].pitch = p
            weights.append(w)
        self.lock_rpm = self.smooth_rpm

        if self.prev_throttle > 0.5 and throttle < 0.2 and self.smooth_rpm > 3000.0:
            self.crackle = 1.0
        self.crackle *= math.exp(-dt / 0.8)
        if self.smooth_load < 0.2 and self.smooth_rpm > 2400.0:
            rpm_factor = min(max((self.smooth_rpm - 2400.0) / 3000.0, 0.2), 1.0)
            rate = (0.3 + 6.0 * self.crackle) * rpm_factor
            if self.rng.random() < rate * dt and now - self.last_pop > 0.07:
                self.fire_pop(0.5 + 0.5 * rpm_factor, now)

        self.whistle.vol = self.master * WHISTLE_VOLUME * boost * boost * (0.3 + 0.7 * throttle)
        self.whistle.pitch = 0.75 + 0.45 * boost + 0.1 * self.smooth_rpm / 8000.0
        if self.prev_throttle > 0.6 and throttle < 0.2 and boost > 0.45 and now - self.last_blowoff > 0.8:
            self.last_blowoff = now
            b = self.blowoff
            b.vol = b.vol_prev = self.master * BLOWOFF_VOLUME * boost
            b.pitch = b.pitch_prev = self.rng.uniform(0.92, 1.08)
            b.play()
        self.prev_throttle = throttle
        self.log.append((now, rpm_engine, self.smooth_rpm, throttle, self.smooth_load, boost, gear, weights,
                         [self.phase_err[i] for i in range(len(rpms))]))

    def render(self, n):
        engine = sum(v.render(n) for v in self.engine_voices)
        return engine + sum(v.render(n) for v in self.voices[len(self.engine_voices):]), engine


# ---------------------------------------------------------------- the car (port of the game's numbers)
TORQUE = np.array([(0, 110), (1000, 130), (2000, 190), (2500, 250), (3000, 320), (3500, 360), (4000, 373), (4500, 370),
                   (5000, 360), (5500, 345), (6000, 327), (6400, 307), (7000, 280), (7500, 258), (8000, 235)], float)
GEARS = [3.636, 2.375, 1.761, 1.346, 1.062, 0.842]
FINAL, WHEEL_R, MASS = 3.9, 0.317, 1545.0
GEAR_CHANGE_TIME, MAX_RPM, IDLE_RPM, CHANGE_UP = 0.25, 8000.0, 925.0, 7400.0


def torque(rpm):
    return float(np.interp(rpm, TORQUE[:, 0], TORQUE[:, 1]))


class Car:
    def __init__(self):
        self.rpm, self.v, self.boost = IDLE_RPM, 0.0, 0.0
        self.gear = self.target_gear = 0
        self.change_left = 0.0

    def set_gear(self, g, immediate=False):
        self.target_gear = g
        if g != self.gear:
            if immediate:
                self.gear = g
            else:
                self.gear, self.change_left = 0, GEAR_CHANGE_TIME

    def step(self, dt, throttle, brake, auto_up, auto_top=3):
        if self.gear != self.target_gear:
            self.change_left -= dt
            if self.change_left <= 0:
                self.gear = self.target_gear
        # boost (AImprezaSTi::UpdateEngine)
        eng_rpm = self.rpm
        if self.gear == 1 and self.rpm < LAUNCH_RPM and throttle > 0.05:
            eng_rpm = self.rpm + (LAUNCH_RPM - self.rpm) * throttle
        tau = np.interp(eng_rpm, [2000, 4500], [1.1, 0.35]) if throttle > self.boost else 0.15
        self.boost += (throttle - self.boost) * (1 - math.exp(-dt / tau))
        tq = torque(eng_rpm) * (0.55 + 0.45 * self.boost) * throttle
        if self.gear == 0:      # free revving (neutral or mid-shift): part throttle is plenty unloaded
            tq = torque(eng_rpm) * 0.7 * min(1.0, 1.6 * throttle)
            friction = 15.0 + 0.004 * self.rpm
            idle_hold = max(0.0, (IDLE_RPM - self.rpm) * 0.5)
            self.rpm += (tq - friction + idle_hold) / 0.09 * 60 / (2 * math.pi) * dt
            self.rpm = min(max(self.rpm, IDLE_RPM * 0.98), MAX_RPM)
            drive = 0.0
        else:
            ratio = GEARS[self.gear - 1] * FINAL
            if self.rpm >= MAX_RPM - 1:
                tq = min(tq, 0.0)
            drive = tq * ratio * 0.88 / WHEEL_R - (0.02 * self.rpm * 4 / WHEEL_R if throttle < 0.05 else 0.0)
        resist = 0.4 * self.v ** 2 + 230.0 + brake * 9000.0
        m_eff = MASS * (1.04 + (0.0025 * (GEARS[self.gear - 1] * FINAL) ** 2 if self.gear > 0 else 0))
        self.v = max(0.0, self.v + (drive - resist * (1 if self.v > 0 else 0)) / m_eff * dt)
        if self.gear > 0:
            self.rpm = min(max(self.v / WHEEL_R * GEARS[self.gear - 1] * FINAL * 60 / (2 * math.pi), IDLE_RPM), MAX_RPM)
            if auto_up and self.rpm >= CHANGE_UP and self.gear < auto_top and self.target_gear == self.gear:
                self.set_gear(self.gear + 1)


def drive():
    """The whole demo drive at TICK. Returns per-tick driver/car states."""
    car = Car()
    out = []
    t = 0.0

    def tick(throttle, brake=0.0, auto=False):
        nonlocal t
        car.step(TICK, throttle, brake, auto)
        out.append((t, car.rpm, throttle, car.boost, car.gear, car.target_gear, car.v))
        t += TICK

    def hold(seconds, throttle=0.0, brake=0.0, auto=False, stop=None):
        end = t + seconds
        while t < end - 1e-9:
            tick(throttle(t) if callable(throttle) else throttle, brake, auto)
            if stop and stop():
                break

    hold(4.0)                                                               # idle
    for dur, amt, rest in ((0.17, 0.75, 1.0), (0.23, 1.0, 1.4), (0.33, 1.0, 2.0)):   # blips
        hold(dur, amt)
        hold(rest)
    hold(0.8)
    car.set_gear(1, immediate=True)                                         # launch, pull 1st-3rd
    hold(30.0, 1.0, auto=True, stop=lambda: car.gear == 3 and car.rpm >= MAX_RPM - 1)
    hold(0.9, 1.0)                                                          # on the limiter in 3rd
    hold(2.8, 0.0)                                                          # lift: overrun + pops
    hold(10.0, 0.0, brake=0.7, stop=lambda: car.rpm <= 3050)              # brake down to 3000
    hold(1.5, lambda _: 0.30)                                               # cruise 3000 in 3rd
    hold(1.6, lambda _: 0.55)                                               # gentle roll-on
    hold(2.5, lambda _: 0.25)                                               # cruise
    hold(10.0, 0.0, brake=0.6, stop=lambda: car.rpm <= 1500)              # slow down
    car.set_gear(0, immediate=True)                                         # clutch in -> idle
    car.target_gear = 0
    hold(5.0, 0.0, brake=0.5)
    return out


def load_waves():
    waves = {}
    for p in OUT.glob("*.wav"):
        _, x = wavfile.read(p)
        waves[p.stem] = x.astype(np.float64) / 32767.0
    return waves


def render(waves, states, break_lock=False, seed=1, pitch_range=PITCH_RANGE):
    mixer = Mixer(waves, np.random.default_rng(seed), break_lock=break_lock, pitch_range=pitch_range)
    n_tick = int(round(TICK * FS))
    out, eng = [], []
    cycles = [round(len(v.wave) * r / (120.0 * FS)) for v, r in zip(mixer.on, RPMS)]
    mixer.crank_err = []
    for (t, rpm, th, boost, gear, target, _v) in states:
        mixer.tick(TICK, t, rpm, th, boost, gear, target)
        y, e = mixer.render(n_tick)
        out.append(y)
        eng.append(e)
        # true crank phase of each audible loop (from its playback position), relative to the loudest
        live = [i for i, w in enumerate(mixer.log[-1][7]) if w > 0]
        ph = {i: mixer.on[i].pos / len(mixer.on[i].wave) * cycles[i] for i in live}
        ref = max(live, key=lambda i: mixer.log[-1][7][i])
        mixer.crank_err.append(max(abs(wrap_cycles(ph[i] - ph[ref])) for i in live))
    mixer.engine_only = np.concatenate(eng)
    return np.concatenate(out), mixer


def analyse_loops(waves):
    """Seams and crank alignment of the loop family."""
    fig, axs = plt.subplots(2, 1, figsize=(12, 7))
    seams = []
    for name, w in sorted(waves.items()):
        if name.startswith("engine_"):
            d = np.abs(np.diff(w))
            seams.append((name, abs(w[0] - w[-1]) / (np.percentile(d, 99) + 1e-9)))
    axs[0].bar(range(len(seams)), [s for _, s in seams])
    axs[0].set_xticks(range(len(seams)), [n.replace("engine_", "") for n, _ in seams], rotation=90, fontsize=7)
    axs[0].set_title("loop seam jump / 99th-percentile sample step (<1 = seamless)")
    # crossfade coherence: for each pair of neighbouring loops (both pitched to the same rpm and
    # crank-locked) the power of each engine order at the crossfade midpoint relative to an
    # incoherent sum: +3 dB = fully coherent, 0 = random phase, very negative = cancellation
    orders = np.arange(1, 17) / 2
    rows = []
    for a, b in zip(RPMS[:-1], RPMS[1:]):
        c = []
        for r in (a, b):
            x = waves[f"engine_on_{r}"]
            n_cyc = round(len(x) * r / (120.0 * FS))
            X = np.fft.rfft(x)[[int(round(n_cyc * o * 2)) for o in orders]]
            c.append(X / np.sqrt(np.mean(np.abs(X) ** 2)))
        rows.append(10 * np.log10(np.abs(c[0] + c[1]) ** 2 / (np.abs(c[0]) ** 2 + np.abs(c[1]) ** 2) + 1e-9))
    im = axs[1].imshow(np.array(rows), aspect="auto", cmap="RdBu", vmin=-12, vmax=12)
    axs[1].set_xticks(range(len(orders)), [f"{o:g}" for o in orders])
    axs[1].set_yticks(range(len(rows)), [f"{a}-{b}" for a, b in zip(RPMS[:-1], RPMS[1:])], fontsize=7)
    axs[1].set_xlabel("engine order")
    axs[1].set_title("on-load crossfade coherence per order (dB vs incoherent sum; +3 = in phase)")
    fig.colorbar(im, ax=axs[1])
    fig.tight_layout()
    fig.savefig(DEMO / "loops_check.png", dpi=80)
    return max(s for _, s in seams)


def plots(y, mixer, name):
    log = mixer.log
    tt = np.array([r[0] for r in log])
    fig, axs = plt.subplots(5, 1, figsize=(15, 16), sharex=True,
                            gridspec_kw={"height_ratios": [3, 1.2, 1.2, 1.2, 1.2]})
    axs[0].specgram(y + 1e-9, NFFT=4096, Fs=FS, noverlap=3584, cmap="magma", vmin=-130, vmax=-30, scale="dB")
    axs[0].set_yscale("symlog", linthresh=200)
    axs[0].set_ylim(20, 16000)
    axs[0].set_ylabel("Hz")
    axs[0].set_title(f"{name}: spectrogram")
    axs[1].plot(tt, [r[1] for r in log], lw=0.8, label="engine rpm (car)")
    axs[1].plot(tt, [r[2] for r in log], lw=0.8, label="SmoothRpm (heard)")
    for r in RPMS:
        axs[1].axhline(r, color="k", lw=0.3, alpha=0.3)
    axs[1].legend(fontsize=8)
    axs[2].plot(tt, [r[3] for r in log], lw=0.8, label="throttle")
    axs[2].plot(tt, [r[4] for r in log], lw=0.8, label="SmoothLoad")
    axs[2].plot(tt, [r[5] for r in log], lw=0.8, label="boost")
    axs[2].plot(tt, [r[6] / 6 for r in log], lw=0.8, label="gear/6")
    axs[2].legend(fontsize=8)
    W = np.array([r[7] for r in log])
    for i, r in enumerate(RPMS):
        axs[3].plot(tt, W[:, i], lw=0.8, label=str(r))
    axs[3].set_ylabel("loop weight")
    axs[3].legend(fontsize=6, ncol=6)
    win = int(0.05 * FS)
    env = np.sqrt(np.convolve(y ** 2, np.ones(win) / win, mode="same"))
    ty = np.arange(len(y)) / FS
    axs[4].plot(ty, 20 * np.log10(env + 1e-9), lw=0.6, label="50 ms RMS (dBFS)")
    axs[4].plot(ty, 20 * np.log10(np.abs(y) + 1e-9), lw=0.2, alpha=0.4, label="|sample|")
    axs[4].set_ylim(-60, 3)
    axs[4].legend(fontsize=8)
    axs[4].set_xlabel("s")
    fig.tight_layout()
    fig.savefig(DEMO / f"{name}.png", dpi=70)


def clicks(y):
    """Largest sample-to-sample jump relative to the local signal (a click detector)."""
    d = np.abs(np.diff(y))
    win = int(0.01 * FS)
    local = np.convolve(d, np.ones(win) / win, mode="same") + 1e-6
    r = d / local
    i = int(np.argmax(r))
    return float(r[i]), i / FS


def main():
    DEMO.mkdir(parents=True, exist_ok=True)
    waves = load_waves()
    states = drive()
    y, mixer = render(waves, states)
    y_unlocked, _ = render(waves, states, break_lock=True)
    _, stock = render(waves, states, pitch_range=(0.4, 2.0))
    peak = np.abs(y).max()
    gain = 10 ** (-1.0 / 20) / peak                     # demo normalised to -1 dBFS peak
    for name, sig in (("sti_demo", y), ("sti_demo_unlocked", y_unlocked)):
        wavfile.write(DEMO / f"{name}.wav", FS, (np.clip(sig * gain, -1, 1) * 32767).astype(np.int16))
    low_end = next(i for i, s in enumerate(states) if s[4] == 1)        # up to the launch
    wavfile.write(DEMO / "sti_demo_low.wav", FS, (np.clip(y[: low_end * int(round(TICK * FS))] * gain, -1, 1) * 32767).astype(np.int16))
    plots(y * gain, mixer, "sti_demo")
    seam = analyse_loops(waves)
    # crank lock while audible: phase error of every loop with weight > 0
    errs = mixer.crank_err
    c, ct = clicks(mixer.engine_only)
    print(f"demo {len(y) / FS:.1f} s; raw mix peak {20 * np.log10(peak):+.1f} dBFS at MasterVolume {MASTER_VOLUME} "
          f"(written at -1 dBFS, gain {20 * np.log10(gain):+.1f} dB)")
    print(f"worst loop seam {seam:.2f}; worst click ratio {c:.1f} at {ct:.2f} s; "
          f"max crank-phase mismatch between audible loops {max(errs):.3f} cycles "
          f"(stock 0.4..2.0 pitch clamp: max {max(stock.crank_err):.3f}, "
          f"95th pct {np.percentile(stock.crank_err, 95):.3f})")
    print(f"-> {DEMO}")


if __name__ == "__main__":
    main()
