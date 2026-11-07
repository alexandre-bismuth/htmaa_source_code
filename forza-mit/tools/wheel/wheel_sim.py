#!/usr/bin/env python3
"""Pretend to be the home-built wheel (docs/wheel_protocol.md) on pseudo-terminals.

    python3 tools/wheel/wheel_sim.py [--script drive|idle|torture|menu] [--seconds 60] [--link PATH] [--unplug-at S]
                                     [--ffb | --ffb-only] [--ffb-link PATH] [--unplug-ffb-at S]

Prints the pty paths; start the game with -WheelPort=<input pty> (and -WheelFFBPort=<ffb pty>; add -WheelLog for a 1 Hz
status line in the log).

Default: ONE pty playing a single-board wheel (the old reference firmware): it streams
"W <steer_centideg> <throttle> <brake> <buttons> <handbrake>" at 500 Hz from a scripted drive and takes the force
feedback ("F <permille>") itself, so the whole input path (serial thread, calibration, paddles, FFB) is testable
without the hardware.
--ffb       TWO ptys, like the real rig: the input board (W lines; it ignores F) and the force-feedback board (answers
            "?" with "I cambridge-ffb-sim 1", sends the "H <flags> <mA>" heartbeat at 10 Hz, takes the F lines; it goes
            limp after 100 ms without F, like the firmware). The game must send F only to the force-feedback board.
--ffb-only  only the force-feedback board (the input board unplugged): the game runs on the keyboard and keeps sending
            F 0, so the board stays out of limp.
At the end (or Ctrl-C) a summary says how many F lines each pty got: in two-pty mode the input pty should get none
(at most the F 0 sent when the game closes), and the last F the force-feedback board got should be F 0 (game closed).

Script "drive": pedal (and handbrake) calibration sweep, launch in 1st, paddle upshifts at 2.5 / 5 / 7.5 s,
a slalom (+-90 deg of rim), brake to a stop with a downshift.
Script "menu": the launch menu and the settings by the paddles only (the wheel has no start button: both paddles
tapped together are its start, held 1 s are back / close; start the game with -LaunchMenu in a test run): from 8 s
after the game connects (the menu is up by then) right paddle, both tapped (Timed Race list), right paddle, both held
(back), right paddle, both tapped (Options: the settings), right paddle, both held (close), left paddle twice, both
tapped: the log must end with "launch: open world".
Script "torture": the same drive, with damaged input mixed in (noise bytes, short / long / out-of-range /
non-numeric lines, lines split across writes), on both ptys. The game must drop all of it: its -WheelLog status should
read the same pedal percentages as with "drive" (e.g. T 87% while the script holds 0.85 throttle).

--link PATH        also make PATH a symlink to the input pty, and start the game with -WheelPort=PATH
--ffb-link PATH    the same for the force-feedback pty (-WheelFFBPort=PATH)
--unplug-at S      at S seconds: close the input pty ("unplug"), and after 2 s open a new one ("replug") and point the
                   --link symlink at it: the game must reconnect by itself
--unplug-ffb-at S  the same for the force-feedback pty (the input keeps streaming meanwhile)
"""
import argparse
import math
import os
import random
import select
import signal
import sys
import termios
import time
import tty

RATE = 500


def drive(t):
    """(steer_deg, throttle 0..1, brake 0..1, buttons) at time t."""
    if t < 1.0:                      # calibration: both pedals through their full travel
        s = math.sin(math.pi * t)
        return 0.0, s, s, 0
    t -= 1.0
    buttons = 0
    for shift_t in (2.5, 5.0, 7.5):
        if shift_t <= t < shift_t + 0.06:
            buttons |= 1             # upshift paddle
    if 12.0 <= t < 12.06 or 13.0 <= t < 13.06:
        buttons |= 2                 # downshift paddle
    if t < 10.0:
        steer = 0.0 if t < 3.0 else 90.0 * math.sin(2 * math.pi * (t - 3.0) / 3.0)
        return steer, 0.85, 0.0, buttons
    if t < 14.0:
        return 0.0, 0.0, 0.7, buttons
    return 0.0, 0.0, 0.0, buttons


# (t, buttons, seconds held): 1 right (upshift) paddle, 2 left (downshift) paddle, 3 both
MENU_PRESSES = [(8.0, 1, 0.25), (9.5, 3, 0.25), (11.0, 1, 0.25), (12.5, 3, 1.0), (14.5, 1, 0.25), (16.0, 3, 0.25),
                (17.5, 1, 0.25), (19.0, 3, 1.0), (21.0, 2, 0.25), (22.5, 2, 0.25), (24.0, 3, 0.25)]


def menu(t):
    """Launch menu / settings navigation with the wheel's buttons (MENU_PRESSES); the rim and pedals rest."""
    if t < 1.0:
        s = math.sin(math.pi * t)
        return 0.0, s, s, 0
    buttons = 0
    for at, b, held in MENU_PRESSES:
        if at <= t < at + held:
            buttons |= b
    return 0.0, 0.0, 0.0, buttons


GARBAGE = [
    b"\x00\xff\xfe garbage \x80\x81\n",
    b"W 1 2 3\n",                          # too few fields
    b"W 1 2 3 4 5 6\n",                    # too many
    b"W 99999999999 0 0 0\n",              # steer out of range
    b"W 0 70000 70000 0\n",                # pedals out of range (would wreck the calibration)
    b"W 0 -5 0 0\n",                       # negative pedal
    b"W 10 abc 0 0\n",                     # not a number
    b"W 10 4095x 0 0\n",                   # trailing junk in a field
    b"W 0 0 0 300\n",                      # buttons out of range
    b"X" * 300 + b" 0 4095 4095 0\n",      # overlong line
    b"WW 0 0 0 0\n",
    b"\r\r\n\n",                           # empty lines
]
FFB_GARBAGE = [
    b"\x00\xff garbage\n",
    b"H 1\n",                              # too few fields
    b"H 1 2 3\n",                          # too many
    b"H 999 0\n",                          # flags out of range
    b"H 3 -4\n",                           # negative current
    b"H x 10\n",
    b"W 0 4095 4095 0\n",                  # the force-feedback board never sends samples: must not drive the car
    b"X" * 300 + b"\n",
]


class Pty:
    """One simulated board on a pseudo-terminal (re-openable for unplug / replug tests)."""

    def __init__(self, name, link):
        self.name, self.link = name, link
        self.master = self.slave = None
        self.path, self.buf = "", b""
        self.replug_at = None               # unplugged until then
        self.f_lines = self.f_nonzero = 0
        self.torque, self.last_f, self.last_f_time = 0, None, None
        self.open()

    def open(self):
        self.master, self.slave = os.openpty()
        tty.setraw(self.slave)
        attrs = termios.tcgetattr(self.slave)
        termios.tcsetattr(self.slave, termios.TCSANOW, attrs)
        self.path = os.ttyname(self.slave)
        if self.link:
            tmp = self.link + ".tmp"
            if os.path.lexists(tmp):
                os.remove(tmp)
            os.symlink(self.path, tmp)
            os.replace(tmp, self.link)          # atomic: the game never sees a missing link
        os.set_blocking(self.master, False)
        self.buf = b""

    def close(self):
        os.close(self.master)
        os.close(self.slave)
        self.master = self.slave = None

    def lines(self):
        """Lines the game sent since the last call."""
        try:
            self.buf += os.read(self.master, 4096)
        except OSError:
            pass
        out = []
        while b"\n" in self.buf:
            line, self.buf = self.buf.split(b"\n", 1)
            out.append(line.strip().decode(errors="replace"))
        return out

    def got_f(self, line, now):
        self.f_lines += 1
        self.last_f, self.last_f_time = line, now
        try:
            self.torque = int(line[2:])
        except ValueError:
            self.torque = 0
        self.f_nonzero += self.torque != 0

    def write(self, data):
        try:
            os.write(self.master, data)
        except (BlockingIOError, OSError):
            pass             # nobody reading: drop it, like a real device would


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--script", default="drive", choices=["drive", "idle", "torture", "menu"])
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--link", default="")
    ap.add_argument("--unplug-at", type=float, default=-1.0)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--ffb", action="store_true", help="two ptys: the input board and the force-feedback board")
    mode.add_argument("--ffb-only", action="store_true", help="only the force-feedback board")
    ap.add_argument("--ffb-link", default="")
    ap.add_argument("--unplug-ffb-at", type=float, default=-1.0)
    args = ap.parse_args()

    def stop(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)            # (scripted runs: kill it to get the summary; a background job
    signal.signal(signal.SIGINT, stop)             # ignores SIGINT unless it is set back)

    inp = None if args.ffb_only else Pty("input", args.link)
    ffb = Pty("ffb", args.ffb_link) if (args.ffb or args.ffb_only) else None
    flags = []
    if inp:
        flags.append(f"-WheelPort={args.link or inp.path}")
        print(f"wheel_sim: input board {inp.path}" + ("" if ffb else "  (single-board wheel: it takes F too)"), flush=True)
    if ffb:
        flags.append(f"-WheelFFBPort={args.ffb_link or ffb.path}")
        print(f"wheel_sim: force-feedback board {ffb.path}", flush=True)
    print(f"wheel_sim: start the game with {' '.join(flags)}", flush=True)
    rng = random.Random(1)
    unplugged = {"input": False, "ffb": False}

    t0 = None          # the script starts when the game first talks to us
    last_print = last_beat = 0.0
    start = time.time()

    def unplug(dev, at):
        print(f"t={at:5.1f}s  UNPLUG {dev.name} {dev.path}", flush=True)
        dev.close()
        dev.replug_at = time.time() + 2.0   # (the other board keeps going meanwhile)

    try:
        while time.time() - start < args.seconds + 30.0:
            now = time.time()
            for d in (inp, ffb):
                if d and d.master is None and now >= d.replug_at:
                    d.open()
                    d.replug_at = None
                    print(f"t={now - t0:5.1f}s  REPLUG {d.name} {d.path} (link {d.link or '-'})", flush=True)
            live = [d for d in (inp, ffb) if d and d.master is not None]
            if live:
                select.select([d.master for d in live], [], [], 1.0 / RATE)
            else:
                time.sleep(1.0 / RATE)
            inp_live = inp if inp and inp.master is not None else None
            ffb_live = ffb if ffb and ffb.master is not None else None
            if inp_live:
                for line in inp.lines():
                    if line == "?":
                        inp.write(b"I cambridge-wheel-sim 1\n")
                        t0 = t0 or now
                    elif line.startswith("F "):
                        inp.got_f(line, now)          # (single-board: drives its motor; two-board: ignored)
                        t0 = t0 or now
            if ffb_live:
                for line in ffb.lines():
                    if line == "?":
                        ffb.write(b"I cambridge-ffb-sim 1\n")
                        t0 = t0 or now
                    elif line.startswith("F "):
                        ffb.got_f(line, now)
                        t0 = t0 or now
                if now - last_beat >= 0.1:      # (from power-up, like the firmware)
                    last_beat = now
                    driving = ffb.last_f_time is not None and now - ffb.last_f_time < 0.1
                    zseen = t0 is not None and now - t0 > 3.0          # (the rim swept through the centre)
                    if args.script == "torture" and rng.random() < 0.2:
                        ffb.write(rng.choice(FFB_GARBAGE))
                    ffb.write(f"H {(1 if driving else 0) | (2 if zseen else 0)} {abs(ffb.torque) * 2 if driving else 0}\n".encode())
            if t0 is None:
                continue
            t = now - t0
            if inp_live and 0 <= args.unplug_at <= t and not unplugged["input"]:
                unplugged["input"] = True
                unplug(inp, t)
                continue
            if ffb_live and 0 <= args.unplug_ffb_at <= t and not unplugged["ffb"]:
                unplugged["ffb"] = True
                unplug(ffb, t)
                continue
            steer, thr, brk, buttons = (drive(t) if args.script in ("drive", "torture")
                                        else menu(t) if args.script == "menu" else (0.0, 0.0, 0.0, 0))
            if inp_live:
                hb = math.sin(math.pi * t) if t < 1.0 and args.script != "idle" else 0.0   # (swept with the pedals)
                msg = f"W {int(round(steer * 100))} {int(thr * 4095)} {int(brk * 4095)} {buttons} {int(hb * 4095)}\n".encode()
                if args.script == "torture" and rng.random() < 0.05:
                    inp.write(rng.choice(GARBAGE))
                if args.script == "torture" and rng.random() < 0.05:
                    cut = rng.randrange(1, len(msg) - 1)      # one sample split across two writes
                    inp.write(msg[:cut])
                    time.sleep(0.003)
                    inp.write(msg[cut:])
                else:
                    inp.write(msg)
            if now - last_print > 0.5:
                last_print = now
                fb = ffb or inp
                print(f"t={t:5.1f}s  steer {steer:6.1f}  thr {thr:.2f}  brk {brk:.2f}  btn {buttons}  <- F {fb.torque:5d} "
                      f"({fb.f_lines} msgs" + (f", input pty {inp.f_lines}" if ffb and inp else "") + ")", flush=True)
            if t > args.seconds:
                break
    except KeyboardInterrupt:
        pass
    for d in (inp, ffb):
        if d:
            print(f"wheel_sim summary: {d.name} pty got {d.f_lines} F lines ({d.f_nonzero} non-zero), last {d.last_f!r}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
