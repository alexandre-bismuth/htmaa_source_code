#!/usr/bin/env python3
"""Pretend to be the home-built wheel (docs/wheel_protocol.md) on a pseudo-terminal.

    python3 tools/wheel/wheel_sim.py [--script drive|idle|torture] [--seconds 60] [--link PATH] [--unplug-at S]

Prints the pty path; start the game with -WheelPort=<that path> (add -WheelLog for a 1 Hz status
line in the log). The simulator streams "W <steer_centideg> <throttle> <brake> <buttons>" at 500 Hz
from a scripted drive and prints the force feedback ("F <permille>") the game sends back, so the whole
input path (serial thread, calibration, paddles, FFB) is testable without the hardware.

Script "drive": pedal calibration sweep, launch in 1st, paddle upshifts at 2.5 / 5 / 7.5 s,
a slalom (+-90 deg of rim), brake to a stop with a downshift.
Script "torture": the same drive, with damaged input mixed in (noise bytes, short / long / out-of-range /
non-numeric lines, lines split across writes). The game must drop all of it: its -WheelLog status should
read the same pedal percentages as with "drive" (e.g. T 87% while the script holds 0.85 throttle).

--link PATH      also make PATH a symlink to the pty, and start the game with -WheelPort=PATH
--unplug-at S    at S seconds: close the pty ("unplug"), and after 2 s open a new one ("replug") and
                 point the --link symlink at it: the game must reconnect by itself
"""
import argparse
import math
import os
import random
import select
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


GARBAGE = [
    b"\x00\xff\xfe garbage \x80\x81\n",
    b"W 1 2 3\n",                          # too few fields
    b"W 1 2 3 4 5\n",                      # too many
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


def open_pty(link):
    master, slave = os.openpty()
    tty.setraw(slave)
    attrs = termios.tcgetattr(slave)
    termios.tcsetattr(slave, termios.TCSANOW, attrs)
    path = os.ttyname(slave)
    if link:
        tmp = link + ".tmp"
        if os.path.lexists(tmp):
            os.remove(tmp)
        os.symlink(path, tmp)
        os.replace(tmp, link)          # atomic: the game never sees a missing link
    os.set_blocking(master, False)
    return master, slave, path


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--script", default="drive", choices=["drive", "idle", "torture"])
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--link", default="")
    ap.add_argument("--unplug-at", type=float, default=-1.0)
    args = ap.parse_args()

    master, slave, path = open_pty(args.link)
    port = args.link or path
    print(f"wheel_sim: {path}  (start the game with -WheelPort={port})", flush=True)
    rng = random.Random(1)
    unplugged = False

    t0 = None          # the script starts when the game first talks to us
    buf = b""
    last_print, torque, n_ffb = 0.0, 0, 0
    start = time.time()
    while time.time() - start < args.seconds + (0 if t0 is None else 0):
        now = time.time()
        r, _, _ = select.select([master], [], [], 1.0 / RATE)
        if r:
            try:
                buf += os.read(master, 4096)
            except OSError:
                pass
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip().decode(errors="replace")
                if line == "?":
                    os.write(master, b"I cambridge-wheel-sim 1\n")
                    t0 = t0 or now
                elif line.startswith("F "):
                    torque, n_ffb = int(line[2:]), n_ffb + 1
                    t0 = t0 or now
        if t0 is None:
            continue
        t = now - t0
        if 0 <= args.unplug_at <= t and not unplugged:
            unplugged = True
            print(f"t={t:5.1f}s  UNPLUG {path}", flush=True)
            os.close(master)
            os.close(slave)
            time.sleep(2.0)
            master, slave, path = open_pty(args.link)
            buf = b""
            print(f"t={time.time() - t0:5.1f}s  REPLUG {path} (link {args.link or '-'})", flush=True)
            continue
        steer, thr, brk, buttons = drive(t) if args.script in ("drive", "torture") else (0.0, 0.0, 0.0, 0)
        msg = f"W {int(round(steer * 100))} {int(thr * 4095)} {int(brk * 4095)} {buttons}\n".encode()
        try:
            if args.script == "torture" and rng.random() < 0.05:
                os.write(master, rng.choice(GARBAGE))
            if args.script == "torture" and rng.random() < 0.05:
                cut = rng.randrange(1, len(msg) - 1)      # one sample split across two writes
                os.write(master, msg[:cut])
                time.sleep(0.003)
                os.write(master, msg[cut:])
            else:
                os.write(master, msg)
        except (BlockingIOError, OSError):
            pass             # nobody reading: drop the sample, like a real device would
        if now - last_print > 0.5:
            last_print = now
            print(f"t={t:5.1f}s  steer {steer:6.1f}  thr {thr:.2f}  brk {brk:.2f}  btn {buttons}  <- F {torque:5d} ({n_ffb} msgs)", flush=True)
        if t > args.seconds:
            break


if __name__ == "__main__":
    sys.exit(main())
