// Reference firmware for the CambridgeRacer wheel (protocol: docs/wheel_protocol.md).
// Arduino API; any board with native USB serial (RP2040, SAMD21/51, ESP32-S2/S3, Teensy).
// Hardware assumed (change the pins / sensors to match the build):
//   steering : quadrature encoder on the rim shaft (or motor shaft, see STEER_GEAR)
//   pedals   : two analog sensors (potentiometer / hall), 0..3.3 V
//   paddles  : two buttons to GND (internal pull-ups)
//   motor    : DC motor on an H-bridge with PWM + DIR inputs (e.g. BTS7960: RPWM/LPWM)

#include <Arduino.h>

// ---- pins --------------------------------------------------------------------------------------
const int PIN_ENC_A = 2, PIN_ENC_B = 3;
const int PIN_THROTTLE = A0, PIN_BRAKE = A1;
const int PIN_UPSHIFT = 6, PIN_DOWNSHIFT = 7, PIN_START = 8;
const int PIN_MOTOR_RPWM = 9, PIN_MOTOR_LPWM = 10;   // one PWM per direction (BTS7960 style)

// ---- calibration constants ---------------------------------------------------------------------
const float ENC_COUNTS_PER_REV = 2400.0f;   // encoder counts per revolution of its shaft (4x decoding)
const float STEER_GEAR = 1.0f;              // shaft turns per rim turn (e.g. 5.0 if on the motor through 5:1)
const float MAX_PWM = 255.0f;               // analogWrite range (set analogWriteResolution for more)
// REMINDER: the game updates the torque only ~50-60 times a second (once per frame). Smooth it here
// (this low-pass, or interpolate across frames) and run the motor loop + damping at >= 1 kHz, so the
// rim gets a continuous force instead of 50-60 Hz steps.
const float FFB_TAU_MS = 3.0f;              // smoothing of the game's torque command
// Firmware-side rim damping, in torque (fraction of max) per centidegree/s of rim speed. 1e-5 gives 0.36 of
// max torque at one rim turn per second. Start low and raise it until the rim stops oscillating: too much
// makes the rim feel locked (0.0008, the old value, saturated the motor at 10 deg/s).
const float DAMPING = 0.00001f;
const float VEL_TAU_MS = 5.0f;              // low-pass of the rim speed (one encoder count is 15 centideg)
const unsigned long FFB_TIMEOUT_MS = 100;   // no "F" for this long -> motor off (safety)
const unsigned long SAMPLE_US = 2000;       // 500 Hz input reports
const unsigned long MOTOR_US = 1000;        // 1 kHz force / damping loop

volatile long encCount = 0;
void encISR() {
  // full quadrature decoding on both channels
  static uint8_t prev = 0;
  uint8_t cur = (digitalRead(PIN_ENC_A) << 1) | digitalRead(PIN_ENC_B);
  static const int8_t table[16] = {0, -1, 1, 0, 1, 0, 0, -1, -1, 0, 0, 1, 0, 1, -1, 0};
  encCount += table[(prev << 2) | cur];
  prev = cur;
}

float targetTorque = 0.0f, torque = 0.0f;   // -1..1, + = clockwise
float steerRate = 0.0f;                     // filtered rim speed, centideg/s
unsigned long lastFfbMs = 0, lastSampleUs = 0, lastLoopUs = 0;
long lastSteer = 0;
char line[48];
int lineLen = 0;

uint8_t debounced(int pin, uint8_t bit, uint8_t prevState) {
  static unsigned long changedAt[3] = {0, 0, 0};
  bool pressed = digitalRead(pin) == LOW;
  bool was = prevState & bit;
  if (pressed != was && millis() - changedAt[bit >> 1] > 5) {
    changedAt[bit >> 1] = millis();
    return pressed ? bit : 0;
  }
  return was ? bit : 0;
}

void setMotor(float t) {
  t = constrain(t, -1.0f, 1.0f);
  int pwm = (int)(fabsf(t) * MAX_PWM);
  analogWrite(PIN_MOTOR_RPWM, t > 0 ? pwm : 0);   // swap the two pins if + turns the rim the wrong way
  analogWrite(PIN_MOTOR_LPWM, t < 0 ? pwm : 0);
}

void handleLine(const char* s) {
  if (s[0] == 'F' && s[1] == ' ') {
    targetTorque = constrain(atoi(s + 2), -1000, 1000) / 1000.0f;
    lastFfbMs = millis();
  } else if (s[0] == '?') {
    Serial.println("I cambridge-wheel 1");
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_ENC_A, INPUT_PULLUP);
  pinMode(PIN_ENC_B, INPUT_PULLUP);
  pinMode(PIN_UPSHIFT, INPUT_PULLUP);
  pinMode(PIN_DOWNSHIFT, INPUT_PULLUP);
  pinMode(PIN_START, INPUT_PULLUP);
  pinMode(PIN_MOTOR_RPWM, OUTPUT);
  pinMode(PIN_MOTOR_LPWM, OUTPUT);
  attachInterrupt(digitalPinToInterrupt(PIN_ENC_A), encISR, CHANGE);
  attachInterrupt(digitalPinToInterrupt(PIN_ENC_B), encISR, CHANGE);
  analogReadResolution(12);   // 0..4095 (remove on boards without it)
  setMotor(0);
}

void loop() {
  // 1. commands from the game
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (lineLen) { line[lineLen] = 0; handleLine(line); lineLen = 0; }
    } else if (lineLen < (int)sizeof(line) - 1) {
      line[lineLen++] = c;
    }
  }

  // 2. force feedback at a fixed 1 kHz: smooth the command, add damping, watchdog. (Not every loop():
  // a rim speed taken over a few microseconds is one encoder count / dt = huge spikes -> motor chatter.)
  unsigned long nowUs = micros();
  noInterrupts(); long count = encCount; interrupts();
  long steer = (long)(count * 36000.0f / (ENC_COUNTS_PER_REV * STEER_GEAR));   // centidegrees
  if (nowUs - lastLoopUs >= MOTOR_US) {
    float dt = (nowUs - lastLoopUs) * 1e-6f;
    lastLoopUs = nowUs;
    float rawRate = (steer - lastSteer) / dt;                                       // centideg/s
    lastSteer = steer;
    steerRate += dt * 1000.0f / (VEL_TAU_MS + dt * 1000.0f) * (rawRate - steerRate);
    if (millis() - lastFfbMs > FFB_TIMEOUT_MS) targetTorque = 0;                  // game gone -> limp
    float a = dt * 1000.0f / (FFB_TAU_MS + dt * 1000.0f);
    torque += a * (targetTorque - torque);
    setMotor(torque - DAMPING * steerRate);
  }

  // 3. input report at 500 Hz
  if (nowUs - lastSampleUs >= SAMPLE_US) {
    lastSampleUs = nowUs;
    static uint8_t buttons = 0;
    buttons = debounced(PIN_UPSHIFT, 1, buttons) | debounced(PIN_DOWNSHIFT, 2, buttons) | debounced(PIN_START, 4, buttons);
    char out[48];
    int len = snprintf(out, sizeof(out), "W %ld %d %d %u\n", steer, analogRead(PIN_THROTTLE), analogRead(PIN_BRAKE), buttons);
    // never block here (game closed, host not reading): a blocked loop would also stop the FFB watchdog
    // above and leave the motor at its last torque. Drop the sample instead.
    if (Serial.availableForWrite() >= len) Serial.write(out, len);
  }
}
