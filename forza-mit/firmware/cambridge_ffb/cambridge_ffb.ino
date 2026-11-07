// OUTPUT board firmware: the CambridgeRacer force-feedback base (protocol: docs/wheel_protocol.md).
// Board: XIAO RP2040 #2 + DRV8251A H-bridge (week_9/steering/output_board), a 775 motor at 9 V (USB-C PD trigger),
// a capstan (~23:1) onto the steering rod. Arduino IDE, Earle Philhower RP2040 core. It never sends W lines: the input
// board (firmware/cambridge_wheel) reads the steering, pedals and paddles; this one only listens to the same encoder.
//
// game -> board  "F <permille>"  -1000..1000 of the motor's maximum torque, + turns the rim clockwise (~once per frame)
//                "?"             -> "I cambridge-ffb 1"
// board -> game  "H <flags> <mA>" heartbeat, 10 per second: the game finds and watches this board by it.
//                flags: 1 driving (fresh F lines), 2 Z seen (soft stops armed), 4 current guard backing off,
//                8 overspeed brake. mA: the motor current averaged over ~1 s.
// bench (serial monitor, line ending "New line"):
//                "S"             -> one status line (see statusLine)
//                "T <permille>"  hold that motor command for 3 s, without GAIN (the step 8 torque / stall tests);
//                                any F line ends it. The current guard and the overspeed brake still apply.
//
// Safety, in order:
// - no F line for 100 ms: limp (the bridge coasts, VREF low cuts the drive). The game sends F 0 when it pauses or closes.
// - the RP2040 watchdog resets the board if this loop ever stops: the pins float, the DRV8251A's pull-downs coast it.
// - rim faster than 580 deg/s: brake (at most 0.5 s at a time, then coast until it slows).
// - motor current averaged over ~1 s kept under 1.5 A (peaks may reach the 2.1 A hardware limit, ITRIP): the guard
//   holds a long stall at ~1.3 A.
// - soft end stops: a spring past +-165 deg from centre (the printed hard stop is at +-170), once Z has been seen.
// - GAIN scales everything the game asks for. Start at 20 %; raise it once the bench checks pass.
//
// PWM decay: SLOW decay (drive / brake). Forward = IN1 high and IN2 PWM: IN2 low drives, IN2 high brakes (both low-side
// FETs on), so the motor current keeps flowing through the off phase and the motor sees duty x 9 V on average: at a
// standstill its current, and so the torque, is proportional to the duty. Fast decay (drive / coast) pushes the current
// back into the supply every off phase; at 20 kHz, far shorter than the motor's L/R, it barely conducts below ~50 %
// duty: a dead zone, then a jump. The price of slow decay: during the brake phases the motor's back-EMF brakes it, so
// whenever a command is applied the rim is damped by the motor itself (always stable; it is why DAMPING starts low).
// Zero command is not brake but COAST (IN1 = IN2 = 0): the rim is free when the game sends F 0 or goes quiet.

#include <Arduino.h>
#include <hardware/gpio.h>

// ---- pins: the output board ------------------------------------------------------------------------------------
const int PIN_VREF = D0;                  // DRV8251A VREF: HIGH (3.3 V) = ITRIP ~2.1 A, LOW cuts the drive
const int PIN_IN1 = D1, PIN_IN2 = D2;     // 00 coast, 10 forward (OUT1 high), 01 reverse, 11 brake
const int PIN_IPROPI = A3;                // 1.575 V per amp (1 kohm to GND)
const int PIN_ENC_A = D10, PIN_ENC_B = D9, PIN_ENC_Z = D8;   // tap of the MT6701 (powered by the input board) via 1 kohm

// ---- constants to check / tune on the bench ---------------------------------------------------------------------
const float GAIN = 0.20f;                 // master gain on the game's force (and this firmware's damping and stops)
const int MOTOR_SIGN = -1;                // motor + (IN1 driven, OUT1 high) turns the rim LEFT and F + is clockwise, so -1.
                                          // Flip it if "T 300" turns the rim counter-clockwise.
const int ENC_SIGN = 1;                   // +1: clockwise raises the count (A leading B, the same decoding as the input
                                          // board). Flip it if the S line's "deg" falls while you turn the rim right.
const long Z_OFFSET_COUNTS = 0;           // straight ahead = where Z fires + this many counts. To measure it: power up
                                          // with the wheel straight (lug up), turn slowly until "z 1", send S, copy "zfix".
const long ENC_COUNTS_PER_REV = 4096;     // MT6701 at 1024 PPR, 4x decoding, on the rod (1:1 with the rim)
const float FFB_TAU_MS = 3.0f;            // smoothing of the game's F (it comes once per frame, 50-120 Hz)
const float VEL_TAU_MS = 8.0f;            // smoothing of the rim speed (one count per ms is 88 deg/s)
const float DAMPING = 0.0004f;            // torque (fraction of max) per deg/s of rim speed: 0.08 at 200 deg/s
const unsigned long FFB_TIMEOUT_MS = 100; // no F for this long: limp
const float SOFT_STOP_DEG = 165.0f;
const float SOFT_STOP_PER_DEG = 0.2f;     // spring past the soft stop: full torque 5 deg in, at the hard stop
const float SOFT_STOP_DAMPING = 0.003f;   // extra damping between the soft and the hard stop, per deg/s (no bounce)
const float OVERSPEED_DPS = 580.0f;       // brake above this rim speed ...
const float OVERSPEED_RELEASE_DPS = 480.0f;   // ... until it is back under this
const unsigned long BRAKE_MAX_MS = 500;   // one overspeed brake lasts at most this (IPROPI can't see the brake current)
const float VOLTS_PER_AMP = 1.575f;       // IPROPI into 1 kohm
const float AVG_TAU_S = 1.0f;             // the current guard: the motor current averaged over about a second ...
const float GUARD_FROM_AMPS = 1.3f;       // ... above this backs the command off (GUARD_DOWN per second per amp over),
const float GUARD_DOWN = 40.0f;           // so that even a sudden stall at the 2.1 A limit peaks under 1.5 A (1.45-1.48 A
const float GUARD_UP = 0.2f;              // simulated for a 0.5-2 ohm motor); regained at GUARD_UP per second under it
const uint32_t PWM_HZ = 20000;            // above hearing
const int PWM_RANGE = 1000;
const float MIN_DUTY = 0.003f;            // a smaller command coasts
const unsigned long LOOP_US = 1000;       // 1 kHz control loop
const unsigned long HEARTBEAT_MS = 100;
const unsigned long BENCH_HOLD_MS = 3000;

const float DEG_PER_COUNT = 360.0f / ENC_COUNTS_PER_REV;

// ---- encoder (interrupts; the same table and A / B roles as the input board) ---------------------------------------
volatile long encCount = 0;
volatile uint8_t encPrev = 0;
volatile long zCount = 0;                 // encCount when Z last rose
volatile bool zSeen = false;

uint8_t encState() {
  const uint32_t in = gpio_get_all();     // A and B in the same instant
  return (((in >> PIN_ENC_A) & 1u) << 1) | ((in >> PIN_ENC_B) & 1u);
}

void encISR() {
  static const int8_t table[16] = {0, -1, 1, 0, 1, 0, 0, -1, -1, 0, 0, 1, 0, 1, -1, 0};
  const uint8_t cur = encState();
  encCount += table[(encPrev << 2) | cur];
  encPrev = cur;
}

void zISR() {
  // Z is one count wide (~150 us at 580 deg/s): latched here, never polled. Every pass re-references the centre.
  zCount = encCount;
  zSeen = true;
}

// ---- bridge ----------------------------------------------------------------------------------------------------
enum Bridge : uint8_t { COAST, DRIVE, BRAKE };
Bridge bridge = COAST;
int pwmPin = -1;          // DRIVE: the input that PWMs (low = drive phase, high = brake phase)
float duty = 0.0f;

void setCoast() {
  analogWrite(PIN_IN1, 0);
  analogWrite(PIN_IN2, 0);
  bridge = COAST; pwmPin = -1; duty = 0.0f;
}

void setBrake() {
  analogWrite(PIN_IN1, PWM_RANGE);
  analogWrite(PIN_IN2, PWM_RANGE);
  bridge = BRAKE; pwmPin = -1; duty = 0.0f;
}

// t: -1..1 of the motor's maximum, + = clockwise on the rim. Slow decay: one input held high, the other PWMs.
void setTorque(float t) {
  const float m = constrain(t, -1.0f, 1.0f) * MOTOR_SIGN;    // + = motor + (IN1 driven, OUT1 high)
  const float d = fabsf(m);
  if (d < MIN_DUTY) { setCoast(); return; }
  const int brakeLevel = (int)lroundf((1.0f - d) * PWM_RANGE);   // the PWM'd input is high (brake) this long
  if (m > 0) { analogWrite(PIN_IN1, PWM_RANGE); analogWrite(PIN_IN2, brakeLevel); pwmPin = PIN_IN2; }
  else       { analogWrite(PIN_IN2, PWM_RANGE); analogWrite(PIN_IN1, brakeLevel); pwmPin = PIN_IN1; }
  bridge = DRIVE; duty = d;
}

// IPROPI follows the bridge current while it drives; in the brake phases of slow decay the current circulates through
// the low-side FETs, which IPROPI may not report. So A3 is read inside a drive phase (the PWM'd input low before and
// after the conversion), waiting at most ~one PWM period. Returns -1 if no drive phase was long enough (tiny duty).
float a3Volts = 0.0f, peakA3Volts = 0.0f;
float readMotorAmps() {
  if (bridge != DRIVE) return bridge == COAST ? 0.0f : -1.0f;
  const unsigned long t0 = micros();
  do {
    if (!gpio_get(pwmPin)) {
      const int raw = analogRead(PIN_IPROPI);
      if (!gpio_get(pwmPin)) {
        a3Volts = raw * 3.3f / 4095.0f;
        peakA3Volts = max(peakA3Volts, a3Volts);
        return a3Volts / VOLTS_PER_AMP;
      }
    }
  } while (micros() - t0 < 60);
  return -1.0f;
}

// ---- state -----------------------------------------------------------------------------------------------------
bool gotF = false;
unsigned long lastFfbMs = 0;
float target = 0.0f, torque = 0.0f;       // the game's command (-1..1, + clockwise), raw and smoothed
long benchPermille = 0;
unsigned long benchStartMs = 0;
bool bench = false;
long lastPos = 0;
float rimDps = 0.0f;                      // + = clockwise
float out = 0.0f;                         // what went to the bridge (-1..1)
float amps = 0.0f, avgAmps = 0.0f, guard = 1.0f;
bool overspeed = false;
unsigned long overspeedSinceMs = 0;
bool limp = true;
unsigned long lastLoopUs = 0, lastBeatMs = 0;
char line[48];
int lineLen = 0;
bool lineOverlong = false;

// strict "<letter> <integer>" (no junk): a damaged line must not command torque or refresh the watchdog
bool parseInt(const char* s, long lo, long hi, long& v) {
  while (*s == ' ' || *s == '\t') ++s;
  char* end = nullptr;
  v = strtol(s, &end, 10);
  if (end == s) return false;
  while (*end == ' ' || *end == '\t') ++end;
  return *end == 0 && v >= lo && v <= hi;
}

void writeLine(const char* s, int len) {
  if (Serial.availableForWrite() >= len) Serial.write(s, len);   // never block (nobody reading)
}

void statusLine() {
  noInterrupts(); long raw = encCount; long zRaw = zCount; bool z = zSeen; interrupts();
  const long pos = ENC_SIGN * raw;
  const float deg = pos * DEG_PER_COUNT;                                       // since power-up
  const float ang = (pos - (ENC_SIGN * zRaw + Z_OFFSET_COUNTS)) * DEG_PER_COUNT;   // from centre (needs Z)
  const char* mode = limp ? "limp" : overspeed ? "overspeed" : bench ? "bench" : "game";
  const char* br = bridge == DRIVE ? "drive" : bridge == BRAKE ? "brake" : "coast";
  char angText[16] = "none";             // (no centre before Z)
  if (z) snprintf(angText, sizeof(angText), "%.1f", ang);
  char s[256];
  int n = snprintf(s, sizeof(s),
    "S deg %.1f ang %s z %d count %ld zcount %ld zfix %ld dps %.0f game %.3f out %.3f %s duty %.2f amps %.2f avg %.2f a3 %.3fV peak %.3fV guard %.2f gain %.2f %s\n",
    deg, angText, z ? 1 : 0, pos, ENC_SIGN * zRaw, -ENC_SIGN * zRaw, rimDps, torque, out, br, duty,
    max(amps, 0.0f), avgAmps, a3Volts, peakA3Volts, guard, GAIN, mode);
  writeLine(s, min(n, (int)sizeof(s) - 1));
  peakA3Volts = 0.0f;
}

void handleLine(const char* s) {
  long v;
  if (s[0] == 'F' && (s[1] == ' ' || s[1] == '\t') && parseInt(s + 1, -1000, 1000, v)) {
    target = v / 1000.0f;
    lastFfbMs = millis();
    gotF = true;
    bench = false;
  } else if (s[0] == 'T' && (s[1] == ' ' || s[1] == '\t') && parseInt(s + 1, -1000, 1000, v)) {
    benchPermille = v;
    benchStartMs = millis();
    bench = v != 0;
  } else if (strcmp(s, "?") == 0) {
    writeLine("I cambridge-ffb 1\n", 18);
  } else if (strcmp(s, "S") == 0) {
    statusLine();
  }
}

void control(float dt) {
  const unsigned long now = millis();
  noInterrupts(); long raw = encCount; long zRaw = zCount; bool z = zSeen; interrupts();
  const long pos = ENC_SIGN * raw;
  const float rawDps = (pos - lastPos) * DEG_PER_COUNT / dt;
  lastPos = pos;
  rimDps += dt * 1000.0f / (VEL_TAU_MS + dt * 1000.0f) * (rawDps - rimDps);

  bench = bench && now - benchStartMs < BENCH_HOLD_MS;
  const bool fresh = gotF && now - lastFfbMs <= FFB_TIMEOUT_MS;
  limp = !fresh && !bench;
  if (limp) {
    // game gone (closed, crashed, unplugged) or never there: coast, drive cut, start over from zero
    setCoast();
    digitalWrite(PIN_VREF, LOW);
    target = torque = out = 0.0f;
    overspeed = false;
  } else {
    digitalWrite(PIN_VREF, HIGH);
    torque += dt * 1000.0f / (FFB_TAU_MS + dt * 1000.0f) * (target - torque);
    float cmd;
    if (bench) {
      cmd = benchPermille / 1000.0f;                       // the bench command, as is
    } else {
      cmd = torque - DAMPING * rimDps;
      if (z) {
        const float ang = (pos - (ENC_SIGN * zRaw + Z_OFFSET_COUNTS)) * DEG_PER_COUNT;
        const float past = fabsf(ang) - SOFT_STOP_DEG;
        if (past > 0.0f) {
          cmd -= (ang > 0.0f ? 1.0f : -1.0f) * SOFT_STOP_PER_DEG * past + SOFT_STOP_DAMPING * rimDps;
        }
      }
      cmd = constrain(cmd, -1.0f, 1.0f) * GAIN;
    }
    out = constrain(cmd, -1.0f, 1.0f) * guard;

    if (!overspeed && fabsf(rimDps) > OVERSPEED_DPS) { overspeed = true; overspeedSinceMs = now; }
    else if (overspeed && fabsf(rimDps) < OVERSPEED_RELEASE_DPS) { overspeed = false; }
    if (overspeed) {
      now - overspeedSinceMs < BRAKE_MAX_MS ? setBrake() : setCoast();
    } else {
      setTorque(out);
    }
  }

  // current guard (unmeasurable samples count as the last good one)
  const float a = readMotorAmps();
  if (a >= 0.0f) amps = a;
  else if (bridge != DRIVE) amps = 0.0f;
  avgAmps += dt / AVG_TAU_S * (amps - avgAmps);
  if (avgAmps > GUARD_FROM_AMPS) guard = max(0.0f, guard - GUARD_DOWN * (avgAmps - GUARD_FROM_AMPS) * dt);
  else guard = min(1.0f, guard + GUARD_UP * dt);
}

void setup() {
  // the bridge coasts and the drive is cut before anything else
  pinMode(PIN_VREF, OUTPUT);
  digitalWrite(PIN_VREF, LOW);
  analogWriteFreq(PWM_HZ);                // (before the first analogWrite: these reset the core's PWM setup)
  analogWriteRange(PWM_RANGE);
  setCoast();
  analogReadResolution(12);
  Serial.begin(115200);
  pinMode(PIN_ENC_A, INPUT);              // plain inputs: the sensor is powered (and driven) by the input board
  pinMode(PIN_ENC_B, INPUT);
  pinMode(PIN_ENC_Z, INPUT);
  delay(50);                              // the MT6701 holds its ABZ outputs for 16 ms after power-up
  encPrev = encState();
  attachInterrupt(digitalPinToInterrupt(PIN_ENC_A), encISR, CHANGE);
  attachInterrupt(digitalPinToInterrupt(PIN_ENC_B), encISR, CHANGE);
  attachInterrupt(digitalPinToInterrupt(PIN_ENC_Z), zISR, RISING);
  lastLoopUs = micros();
  rp2040.wdt_begin(200);                  // the loop stops for 0.2 s: reset (the bridge coasts)
}

void loop() {
  // 1. lines from the game (or the serial monitor)
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (lineLen && !lineOverlong) { line[lineLen] = 0; handleLine(line); }
      lineLen = 0;
      lineOverlong = false;
    } else if (lineLen < (int)sizeof(line) - 1) {
      line[lineLen++] = c;
    } else {
      lineOverlong = true;
    }
  }

  // 2. force, damping, stops and guards at a fixed 1 kHz
  const unsigned long nowUs = micros();
  if (nowUs - lastLoopUs >= LOOP_US) {
    const float dt = min((nowUs - lastLoopUs) * 1e-6f, 0.01f);
    lastLoopUs = nowUs;
    control(dt);
    rp2040.wdt_reset();
  }

  // 3. heartbeat
  if (millis() - lastBeatMs >= HEARTBEAT_MS) {
    lastBeatMs = millis();
    const int flags = (limp ? 0 : 1) | (zSeen ? 2 : 0) | (guard < 0.99f ? 4 : 0) | (overspeed ? 8 : 0);
    char s[32];
    const int n = snprintf(s, sizeof(s), "H %d %ld\n", flags, lroundf(avgAmps * 1000.0f));
    writeLine(s, n);
  }
}
