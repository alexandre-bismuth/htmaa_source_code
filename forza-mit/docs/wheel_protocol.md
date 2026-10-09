# Wheel / pedals / paddles ↔ game protocol (v1)

> **Reminder for the electronics build:** the game only sends a force-feedback value about
> 50–60 times a second (once per frame). The firmware must turn that into a **smooth force**
> before it reaches the motor:
> - interpolate or low-pass between `F` updates (a 2–5 ms filter, or linear interpolation over one frame);
> - run the motor current/PWM loop and its damping (from the encoder velocity) at ≥1 kHz;
> - never step the PWM straight to each new `F` value, or the rim will buzz and step at 50–60 Hz.
>
> `firmware/cambridge_wheel/cambridge_wheel.ino` shows a starting point (`FFB_TAU_MS`, `DAMPING`).

The game talks to the home-built controls over **USB CDC serial** (the microcontroller shows up as
`/dev/cu.usbmodem*` on macOS). It's plain ASCII, one message per line (`\n`), so you can debug it
with any serial monitor. Game side: `CambridgeRacer/Source/CambridgeRacer/CambridgeWheelSubsystem.*`.
For a reference firmware, see `firmware/cambridge_wheel/cambridge_wheel.ino`.

## Device → game: input samples (~500 Hz, at least 100 Hz)

```
W <steer_centideg> <throttle_raw> <brake_raw> <buttons>
W -1234 2048 0 1
```

| field | meaning |
|---|---|
| `steer_centideg` | rim angle in 1/100 degree, signed, **+ = clockwise (right)**. Any zero works: the player sets the centre in the menu (Esc, then *Centre wheel*). |
| `throttle_raw`, `brake_raw` | raw pedal readings, integers (e.g. 12-bit ADC: 0..4095), **increasing as the pedal is pressed** (invert in firmware if needed). The game learns each pedal's min/max travel by itself: press both pedals fully once after first plugging in. It keeps a 3 % dead zone at both ends. |
| `buttons` | bit 0 = **upshift** paddle, bit 1 = **downshift** paddle, bit 2 = start/confirm (optional: this wheel has none; both paddles pressed together do the same everywhere). Send the current state; the game detects presses. Debounce in firmware (~5 ms). |

Reply to `?` (sent by the game when it opens the port) with an info line:

```
I cambridge-wheel 1
```

## Game → device: force feedback

```
F <torque_permille>
F -350
```

- `-1000..1000` = fraction of the motor's maximum torque, **+ = turns the rim clockwise**.
- The game already applies its *force feedback strength* setting.
- Sent once per rendered frame (50-120 Hz, capped at 250 Hz). The firmware should:
  - **low-pass / interpolate** the command (e.g. 2-5 ms time constant);
  - add its own **damping** (from the encoder velocity, at the full loop rate), which keeps the rim stable;
  - **drop to 0 torque if no `F` line arrives for 100 ms** (game closed, paused, or crashed). Safety first: this motor can hurt wrists.
- The game sends `F 0` when it closes the port.

What the torque contains:
- Self-aligning torque from the front slip angle. It goes **light when the front tyres pass their peak**, which is how you feel understeer.
- Weight at parking speed.
- Kicks from one-sided kerb strikes.
- A little damping.

## Game behaviour with the wheel connected

- The wheel overrides keyboard and gamepad steering, throttle and brake. Everything else still works (Esc menu, camera, assists keys).
- Steering is linear over half the *Wheel rotation* setting (default 540° lock-to-lock, so ±270° = full lock of the road wheels). It's 1:1 at all speeds (the keyboard's speed-sensitive steering is undone).
- Two independent pedals: left-foot braking works. The **brake never engages reverse**; reverse = downshift past neutral (1 → N → R).
- A paddle press switches the gearbox to manual (G toggles back to auto). Reverse is refused above 8 km/h.
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
- **Port detection:** the game scans `/dev` for `cu.usbmodem*` / `ttyACM*` and sends `?`. A port that sends no valid
  `W` sample within 3 s is skipped (so another USB-serial board isn't mistaken for the wheel). `-WheelPort=<path>`
  overrides detection for one run and is never saved; a saved port that no longer exists (or is a pty) is ignored.
- If no sample arrives for 0.5 s, the wheel is considered unplugged; the game waits 1 s, then reconnects automatically.
- **Parsing is strict:** a `W` line must have exactly 4 in-range integer fields; anything else (partial or garbage
  lines) is dropped and counted in the `-WheelLog` status.
- **Pedal calibration** is tracked per session (the game learns each pedal's travel as you press it), starting from the
  saved values only if they are valid (min < max). The saved calibration is written only by the menu's
  *Recalibrate pedals* flow (press both pedals fully, then close the menu). Test runs (`-WheelPort`, shot tours,
  drive tests) never save anything.

## Testing without hardware

```
python3 tools/wheel/wheel_sim.py            # prints e.g. /dev/ttys007
<game> -WheelPort=/dev/ttys007 -WheelLog    # -WheelLog: 1 Hz status lines in the log
```

The simulator plays a scripted drive (pedal sweep, launch, paddle shifts, slalom, braking) and prints the
force feedback it receives. `--script torture` adds garbage and partial lines, `--unplug-at <s>` simulates an unplug /
replug, and `--link <path>` keeps a stable symlink to the pty (re-pointed on replug).
