"""Synthesise the small race UI sounds (countdown beeps, checkpoint chimes, callouts) with numpy.

    cd tools/ui && uv run make_ui_sounds.py

Writes 16-bit mono 44.1 kHz WAVs into data/processed/common/audio/ui/ (a sub-folder on purpose:
tools/unreal/import_car.py imports every *.wav directly in data/processed/common/audio as a car sound).
tools/unreal/build_game_assets.sh imports them into /Game/Cambridge/Game/Audio, where
UTimeTrialSubsystem loads them by name.

  ui_count        3-2-1 beep                       ui_go           GO! (octave chord)
  ui_checkpoint   checkpoint chime                 ui_checkpoint_ahead  brighter chime (ahead of best)
  ui_lap          new lap arpeggio                 ui_final_lap    final-lap fanfare
  ui_finish       finish chord                     ui_new_best     sparkle for a new best time
  ui_wrong_way    low double buzz                  ui_missed       falling two-note "missed checkpoint"
  ui_select       results-menu move tick           ui_confirm      results-menu confirm blip
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

SR = 44100
OUT = Path(__file__).resolve().parents[2] / "data/processed/common/audio/ui"


def t_axis(seconds: float) -> np.ndarray:
    return np.arange(int(SR * seconds)) / SR


def env(t: np.ndarray, attack: float, decay: float, hold: float = 0.0) -> np.ndarray:
    """Linear attack, optional hold, exponential decay (time constant `decay`)."""
    a = np.clip(t / max(attack, 1e-4), 0, 1)
    d = np.where(t < attack + hold, 1.0, np.exp(-(t - attack - hold) / decay))
    return a * d


def bell(freq: float, seconds: float, decay: float = 0.25, bright: float = 1.0) -> np.ndarray:
    """Soft glassy bell: a few inharmonic partials, the high ones decaying faster."""
    t = t_axis(seconds)
    out = np.zeros_like(t)
    for ratio, amp, dk in ((1.0, 1.0, 1.0), (2.0, 0.35 * bright, 0.6), (3.01, 0.18 * bright, 0.4), (4.17, 0.08 * bright, 0.25)):
        out += amp * np.sin(2 * np.pi * freq * ratio * t) * env(t, 0.003, decay * dk)
    return out


def tone(freq: float, seconds: float, attack=0.004, decay=0.08, hold=0.0, square=0.0) -> np.ndarray:
    """Sine with a touch of odd harmonics (square-ish when square -> 1): the arcade beep."""
    t = t_axis(seconds)
    x = np.sin(2 * np.pi * freq * t)
    for k in (3, 5, 7):
        x += square / k * np.sin(2 * np.pi * freq * k * t)
    return x * env(t, attack, decay, hold)


def place(parts: list[tuple[float, np.ndarray]], seconds: float) -> np.ndarray:
    out = np.zeros(int(SR * seconds))
    for at, x in parts:
        i = int(at * SR)
        n = min(len(x), len(out) - i)
        out[i:i + n] += x[:n]
    return out


def lowpass(x: np.ndarray, cutoff: float) -> np.ndarray:
    a = np.exp(-2 * np.pi * cutoff / SR)
    y = np.zeros_like(x)
    acc = 0.0
    for i, v in enumerate(x):
        acc = (1 - a) * v + a * acc
        y[i] = acc
    return y


def note(n: str) -> float:
    names = {"C": -9, "D": -7, "E": -5, "F": -4, "G": -2, "A": 0, "B": 2}
    semis = names[n[0]] + (1 if "#" in n else 0) + 12 * (int(n[-1]) - 4)
    return 440.0 * 2 ** (semis / 12)


def save(name: str, x: np.ndarray, peak: float = 0.5) -> None:
    fade = min(len(x), int(0.01 * SR))
    x = x.copy()
    x[-fade:] *= np.linspace(1, 0, fade)
    x = x / max(np.abs(x).max(), 1e-9) * peak
    OUT.mkdir(parents=True, exist_ok=True)
    with wave.open(str(OUT / f"{name}.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((x * 32767).astype("<i2").tobytes())
    print(f"  {name:22s} {len(x) / SR:4.2f} s")


def main() -> None:
    # countdown: short A5 arcade beep, then GO an octave up with the fifth, held a little
    save("ui_count", tone(note("A5"), 0.22, decay=0.06, hold=0.05, square=0.35), 0.45)
    save("ui_go", place([(0, tone(note("A6"), 0.7, decay=0.18, hold=0.12, square=0.3)),
                         (0, 0.6 * tone(note("E6"), 0.7, decay=0.18, hold=0.12, square=0.3))], 0.7), 0.5)
    # checkpoint: two-note glass chime (E6 -> B6); ahead of best: brighter, a third higher
    save("ui_checkpoint", place([(0, bell(note("E6"), 0.6, 0.18)), (0.07, bell(note("B6"), 0.6, 0.22))], 0.7), 0.42)
    save("ui_checkpoint_ahead", place([(0, bell(note("G6"), 0.6, 0.18, 1.3)), (0.06, bell(note("D7"), 0.7, 0.26, 1.3))], 0.8), 0.42)
    # lap: rising triad; final lap: fanfare with a held top note
    save("ui_lap", place([(0.0, bell(note("C6"), 0.5, 0.15)), (0.08, bell(note("E6"), 0.5, 0.15)),
                          (0.16, bell(note("G6"), 0.8, 0.3))], 1.0), 0.45)
    brass = lambda f, s, h: lowpass(tone(f, s, attack=0.012, decay=0.25, hold=h, square=0.8), 3500)
    save("ui_final_lap", place([(0.0, brass(note("G5"), 0.3, 0.05)), (0.12, brass(note("C6"), 0.3, 0.05)),
                                (0.24, brass(note("E6"), 0.3, 0.05)), (0.36, brass(note("G6"), 1.0, 0.35)),
                                (0.36, 0.5 * brass(note("C6"), 1.0, 0.35))], 1.4), 0.5)
    # finish: arpeggio into a held major chord; new best: high sparkle run
    chord = sum(bell(note(n), 1.6, 0.6) for n in ("C6", "E6", "G6", "C7"))
    save("ui_finish", place([(0.0, bell(note("G5"), 0.4, 0.12)), (0.09, bell(note("C6"), 0.4, 0.12)),
                             (0.18, bell(note("E6"), 0.4, 0.12)), (0.27, chord)], 1.9), 0.5)
    save("ui_new_best", place([(0.06 * i, bell(note(n), 0.7, 0.2, 1.4)) for i, n in
                               enumerate(("C7", "E7", "G7", "C8", "G7", "C8"))], 1.2), 0.38)
    # warnings: low filtered square double buzz; falling two-note for a missed checkpoint
    buzz = lambda: lowpass(tone(196.0, 0.16, attack=0.005, decay=0.2, hold=0.1, square=1.0), 1800)
    save("ui_wrong_way", place([(0.0, buzz()), (0.22, buzz())], 0.45), 0.45)
    save("ui_missed", place([(0.0, lowpass(tone(note("E5"), 0.25, decay=0.08, hold=0.06, square=0.7), 2500)),
                             (0.16, lowpass(tone(note("A4"), 0.4, decay=0.14, hold=0.08, square=0.7), 2500))], 0.6), 0.42)
    # results menu
    save("ui_select", tone(2200.0, 0.05, attack=0.001, decay=0.012), 0.25)
    save("ui_confirm", place([(0, tone(note("E6"), 0.12, decay=0.03)), (0.05, tone(note("A6"), 0.18, decay=0.05))], 0.25), 0.35)


if __name__ == "__main__":
    print(f"UI sounds -> {OUT}")
    main()
