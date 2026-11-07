# Wheel / pedals / paddles / force feedback ↔ game protocol (v1)

The game talks to the home-built controls over **USB CDC serial** (each microcontroller shows up as
`/dev/cu.usbmodem*` on macOS). It's plain ASCII, one message per line (`\n`), so you can debug it
with any serial monitor. Game side: `CambridgeRacer/Source/CambridgeRacer/CambridgeWheelSubsystem.*`.

The rig has **two boards**, both Seeed XIAO RP2040 (Arduino IDE, Earle Philhower core):

| board | firmware | what it does |
|---|---|---|
| **input board** (car_inputs v6) | `firmware/cambridge_wheel/cambridge_wheel.ino` | steering (MT6701 encoder on the steering rod, A/B), pedals, handbrake, paddles → `W` lines. Never drives a motor; ignores `F`. |
| **force-feedback board** (output board) | `firmware/cambridge_ffb/cambridge_ffb.ino` | DRV8251A H-bridge + 775 motor through the capstan; listens to the same encoder (A/B/Z) → takes `F` lines. Never sends `W`. |

A single board doing both (the old reference firmware: `W` out, `F` in on one port) still works: see *Port detection*.

## Input board → game: input samples (~500 Hz, at least 100 Hz)

```
W <steer_centideg> <throttle_raw> <brake_raw> <buttons> [<handbrake_raw>]
W -1234 2048 0 1
W -1234 2048 0 1 3100
```

| field | meaning |
|---|---|
| `steer_centideg` | rim angle in 1/100 degree, signed, **+ = clockwise (right)**. The input board sends counts × 36000 / 4096 (MT6701 at 1024 PPR, 4× decoding, 1:1 on the rod); zero is where the rim sat at power-up. Any zero works: the player sets the centre in the menu (Esc, then *Centre wheel*). |
| `throttle_raw`, `brake_raw` | raw pedal readings, integers (e.g. 12-bit ADC: 0..4095), **increasing as the pedal is pressed** (invert in firmware if needed). The game learns each pedal's min/max travel by itself: press both pedals fully once after first plugging in. It keeps a 3 % dead zone at both ends. |
| `buttons` | bit 0 = **upshift** paddle, bit 1 = **downshift** paddle, bit 2 = start/confirm (optional: this wheel has none; both paddles pressed together do the same everywhere). Send the current state; the game detects presses. Debounce in firmware (~5 ms). |
| `handbrake_raw` | optional: the handbrake lever's raw reading (e.g. a potentiometer on the ADC), **increasing as it is pulled**, calibrated like the pedals (pull it fully once). Without a handbrake, send 4 fields. |

Reply to `?` (sent by the game when it opens the port) with an info line:

```
I cambridge-wheel 1
```

## Force-feedback board ↔ game

Game → board:

```
F <torque_permille>
F -350
```

- `-1000..1000` = fraction of the motor's maximum torque, **+ = turns the rim clockwise**.
- The game already applies its *force feedback strength* setting.
- Sent once per rendered frame (50-120 Hz, capped at 250 Hz), whenever the board is connected: the car's torque while
  the wheel drives it, **`F 0` while the game is paused, in a menu, or driven by the keyboard**, and `F 0` when the
  game closes.
- The game only sends ~50-60 values a second. The firmware turns that into a smooth force: a 3 ms low-pass on the
  command, a 1 kHz loop with damping from the encoder velocity, 20 kHz PWM. It **goes limp (coasts) if no `F` line
  arrives for 100 ms** (game closed, crashed, unplugged). Safety first: this motor can hurt wrists.
- A line that isn't exactly `F` and one integer in range is ignored (it doesn't refresh the 100 ms timeout either).

Board → game:

```
I cambridge-ffb 1            the reply to "?": this is how the game recognises the force-feedback board
H <flags> <milliamps>        heartbeat, 10 per second, from power-up
H 3 480
```

| `H` field | meaning |
|---|---|
| `flags` | bit 0 = driving (fresh `F` lines; 0 = limp), bit 1 = the Z pulse has been seen (centre known, soft end stops armed), bit 2 = the current guard is backing the force off, bit 3 = overspeed brake |
| `milliamps` | motor current averaged over ~1 s |

The heartbeat is kept out of the `W` format on purpose: the game tells the boards apart by what they send. It shows
"FFB" in the menu's *Wheel* row (or "FFB, turn to find the centre" until Z has been seen) and logs flag changes.

What the torque contains:
- Self-aligning torque from the front slip angle. It goes **light when the front tyres pass their peak**, which is how you feel understeer.
- Weight at parking speed.
- Kicks from one-sided kerb strikes.
- A little damping.

The firmware adds, on top (all scaled by its `GAIN`, which starts at 20 %):
- damping from the rim speed (`DAMPING`); the motor itself also damps whenever it is driven (slow-decay PWM);
- **soft end stops**: a spring past ±165° from the centre (the printed hard stop is at ±170°), once the Z pulse has
  been seen. Centre = where Z fires + `Z_OFFSET_COUNTS` (measured once, see the bench list);
- a **brake above 580°/s** rim speed (at most 0.5 s at a time);
- a **current guard**: peaks may reach the DRV8251A's 2.1 A limit, but the motor current averaged over ~1 s stays
  under 1.5 A (it starts backing off at 1.3 A);
- the RP2040 watchdog: if the firmware ever hangs, the board resets and the bridge coasts.

### Bench commands (Arduino serial monitor, line ending "New line")

| send | gets |
|---|---|
| `?` | `I cambridge-ffb 1` |
| `S` | one status line: `deg` (since power-up), `ang` (from the centre, `none` before Z), `z`, `count`, `zcount`, `zfix` (the `Z_OFFSET_COUNTS` to use if the board was powered up with the wheel straight), `dps`, the command, the bridge state and duty, `amps` (now), `avg` (1 s), `a3` and `peak` (A3 volts, peak since the last `S`), `guard`, `gain`, mode |
| `T <permille>` | hold that motor command for 3 s, without `GAIN` (torque and stall tests); the current guard and the overspeed brake still apply; any `F` line ends it |

### Bench bring-up (step 8 of the steering guide), in this order

1. **Signs first** (`GAIN` 20 %): turn the rim right by hand and send `S`: `deg` must rise (else flip `ENC_SIGN`).
   Send `T 300`: the rim must turn clockwise (else flip `MOTOR_SIGN`). A wrong sign makes the damping push instead of
   brake and the soft stops push into the hard stop.
2. **Centre**: power up with the wheel straight (lug up), turn slowly through the full lock until `S` shows `z 1`,
   copy `zfix` into `Z_OFFSET_COUNTS`, upload; `ang` then reads ~0 with the wheel straight. If `z` never turns 1 across
   the whole lock, the magnet's zero sits behind the hard stop (the ±170..180° gap): turn the magnet in its cap.
3. One turn of the rod = 4096 counts (`count`; the game's *Wheel* row moves 360°). Assembled, hard stop to hard stop
   (340°) is about 3870 counts.
4. No slip: lock to lock 10 times, back to the start, `count` (and the game's angle) come back to the same value.
5. Stall at full command (`T 1000`, rim held): A3 reads ~3.1-3.3 V (`a3` / `peak`, or a meter on A3) **for about the
   first second**; then the current guard backs off and it settles near 2 V (1.3 A). The `peak` in the next `S` keeps
   the full-current reading.
6. XIAO in reset (or unpowered): the wheel coasts freely (the DRV8251A's pull-downs; only the firmware ever brakes).
7. F timeout: with the game driving, close it (or pull its USB cable) mid-turn: the wheel goes limp within 0.1 s.
8. Torque: luggage scale on the bar 70 mm from the centre, `T 1000`: about 2.3 kgf (1.6 N·m), read within the first
   second (current guard).

In the game, set *Wheel rotation* to **330°** (the soft stops at ±165° are full lock).

## Game behaviour with the wheel connected

- The wheel overrides keyboard and gamepad steering, throttle and brake. Everything else still works (Esc menu, camera, assists keys).
- Steering is linear over half the *Wheel rotation* setting (default 540° lock-to-lock, so ±270° = full lock of the
  road wheels; 330° for the force-feedback base). It's 1:1 at all speeds (the keyboard's speed-sensitive steering is undone).
- Two independent pedals: left-foot braking works (the turbo builds no boost while the brake pedal is pressed).
- Handbrake lever: it brakes the rear wheels harder and harder over its whole travel (fully pulled = Space on the
  keyboard). Space / gamepad A still work beside it.
- The gearbox setting (automatic / manual) changes only in Settings > Driving Assists, never from the wheel.
- Automatic (as in Forza): the paddles don't shift. Holding the brake at a standstill engages reverse; the brake pedal then drives and the throttle brakes, and the throttle at a standstill goes back to first.
- Manual: the paddles shift, the **brake never engages reverse**; reverse = downshift past neutral (1 → N → R), refused above 8 km/h.
- No start button: **both paddles pressed together** are the start everywhere. In menus one paddle waits 0.12 s in
  case the other joins, so pressing both never moves the selection first. Every key hint switches to these controls
  while the wheel is connected:
  - launch menu: left / right paddle = up / down, both tapped = go, both held 0.8 s (or the rim turned left past
    50°) = back;
  - settings (Esc): left / right paddle = up / down, turning the rim past 50° changes a value, both tapped = next
    section, both held 0.8 s = close;
  - a start box: both paddles start the event;
  - in an event: both tapped = back on track, held 1 s = restart; leaving an event stays on the keyboard (hold
    Backspace);
  - the results: one paddle picks Retry / Next event / Free roam (no shifting there), both tapped press it.
  A start button on bit 2, if one is ever added, does what a tap of both paddles does.
- **Port detection:** the game scans `/dev` for `cu.usbmodem*` / `ttyACM*`, opens every candidate at once and sends
  `?` (again every second until the port is identified). A port that sends valid `W` samples is the **input board**;
  one that says `I cambridge-ffb` (or sends `H`) is the **force-feedback board**. A port that is neither within 3 s is
  skipped (so another USB-serial board isn't mistaken for the wheel; unplugged and plugged back in, it is asked
  again). A second board of the same kind is ignored. `-WheelPort=<path>` and `-WheelFFBPort=<path>` replace the scan
  for one run (either may be either board; never saved); a saved port that no longer exists (or is a pty) is ignored.
- **Where `F` goes:** to the force-feedback board. Without one (none seen this session), to the input board's port: a
  single board doing both (the old reference firmware) gets its force feedback, and the new input board ignores it.
  Once a force-feedback board has been seen, `F` never goes to the input board, even while the force-feedback board
  is unplugged.
- **Each board reconnects on its own** and the game works with either one missing: without the input board it runs on
  the keyboard / gamepad (the force-feedback board gets `F 0`); without the force-feedback board the wheel still steers.
  The input board counts as unplugged when no sample arrives for 0.5 s; the force-feedback board when no heartbeat
  arrives for 0.5 s (its port is closed and looked for again after 3 s). An unplugged port is retried every second.
- **Parsing is strict:** a `W` line must have 4 (or 5, with the handbrake) in-range integer fields, an `H` line 2;
  anything else (partial or garbage lines, a `W` from the force-feedback board) is dropped and counted in the
  `-WheelLog` status.
- **Pedal calibration** is tracked per session (the game learns each pedal's travel as you press it), starting from the
  saved values only if they are valid (min < max). The saved calibration is written only by the menu's
  *Recalibrate pedals* flow (press both pedals fully and pull the handbrake, then close the menu). Test runs (`-WheelPort`, shot tours,
  drive tests) never save anything.

## Testing without hardware

```
python3 tools/wheel/wheel_sim.py --ffb      # prints the two ptys and the flags, e.g.
<game> -WheelPort=/dev/ttys007 -WheelFFBPort=/dev/ttys008 -WheelLog     # -WheelLog: 1 Hz status lines in the log
```

The simulator plays a scripted drive (pedal sweep, launch, paddle shifts, slalom, braking) on the input pty and, with
`--ffb`, a force-feedback board on a second pty (`I` reply, `H` heartbeat, prints the `F` it receives). Without
`--ffb` it is a single-board wheel (one pty, `W` out and `F` in); `--ffb-only` is the force-feedback board alone. On
exit (or Ctrl-C) it prints how many `F` lines each pty got: with two boards the input pty must get none, and the last
`F` the force-feedback board got must be `F 0` (the game closed). `--script torture` adds garbage and partial lines on
both, `--unplug-at <s>` / `--unplug-ffb-at <s>` unplug and replug each board, and `--link` / `--ffb-link <path>` keep
stable symlinks to the ptys (re-pointed on replug). For a run that ends by itself (and so sends its closing `F 0`):
`<game> /Game/Cambridge/Maps/DriveTest -DriveTest -DriveTestMode=idle -DriveTestSeconds=40 -WheelPort=... -WheelFFBPort=...`.
