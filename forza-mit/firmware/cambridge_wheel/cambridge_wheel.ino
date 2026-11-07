// INPUT board firmware for the CambridgeRacer wheel (protocol: docs/wheel_protocol.md): steering, pedals, handbrake and
// paddles -> "W" lines at 500 Hz. The force feedback is the OUTPUT board's job (firmware/cambridge_ffb): this board
// never drives a motor and ignores "F" lines.
// Board: car_inputs v6, Seeed XIAO RP2040 (Arduino IDE, Earle Philhower RP2040 core).
//   steering : MT6701 magnetic encoder in ABZ mode, 1:1 on the steering rod: 1024 PPR = 4096 counts per turn with 4x
//              decoding. A and B on J1 (4.99k pull-ups on the board); Z is not wired here (only the output board has it)
//   pedals   : two analog sensors, 0..3.3 V (J2 throttle, J3 brake)
//   handbrake: a potentiometer like the pedals (J4; PIN_HANDBRAKE = -1 without one)
//   paddles  : two buttons to GND (J5, J6; 4.99k pull-ups on the board)
// Straight ahead is wherever the rim sits at power-up (no Z pulse on this board). The game can recentre on top of
// that (Esc > Centre wheel).
// TODO (with the paddles, on the cast rim): both paddles held 2 s with the wheel straight = recentre (encCount = 0).

#include <Arduino.h>
#include <hardware/gpio.h>

// ---- pins: the car_inputs board ------------------------------------------------------------------------------------
const int PIN_ENC_A = D6, PIN_ENC_B = D5;                          // J1 (GPIO0, GPIO7). Swap them if right turns read negative
const int PIN_THROTTLE = A0, PIN_BRAKE = A1, PIN_HANDBRAKE = A2;   // J2, J3, J4
const int PIN_UPSHIFT = D3, PIN_DOWNSHIFT = D4;                    // J5, J6 (no start button)

// ---- calibration constants -----------------------------------------------------------------------------------------
const long ENC_COUNTS_PER_REV = 4096;   // MT6701 at 1024 PPR, 4x decoding
const long STEER_GEAR = 1;              // rod turns per rim turn: the sensor is on the steering rod itself
const unsigned long SAMPLE_US = 2000;   // 500 Hz input reports

volatile long encCount = 0;             // + = clockwise (A leading B: the MT6701 turning clockwise)
volatile uint8_t encPrev = 0;

uint8_t encState() {
  const uint32_t in = gpio_get_all();   // A and B read in the same instant
  return (((in >> PIN_ENC_A) & 1u) << 1) | ((in >> PIN_ENC_B) & 1u);
}

void encISR() {
  // full quadrature decoding on both edges of A and B
  static const int8_t table[16] = {0, -1, 1, 0, 1, 0, 0, -1, -1, 0, 0, 1, 0, 1, -1, 0};
  const uint8_t cur = encState();
  encCount += table[(encPrev << 2) | cur];
  encPrev = cur;
}

// rim angle in centidegrees: counts x 36000 / 4096 (8.79 centideg per count), rounded
long steerCentideg(long count) {
  const int64_t num = (int64_t)count * 36000;
  const int64_t den = (int64_t)ENC_COUNTS_PER_REV * STEER_GEAR;
  return (long)((num + (num >= 0 ? den / 2 : -den / 2)) / den);
}

unsigned long lastSampleUs = 0;
char line[48];
int lineLen = 0;
bool lineOverlong = false;

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

void handleLine(const char* s) {
  if (strcmp(s, "?") == 0) {
    Serial.println("I cambridge-wheel 1");
  }
  // anything else, the game's "F <torque>" lines included, is ignored: the output board does the force feedback
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_ENC_A, INPUT);            // the MT6701 drives A / B push-pull; the board has the pull-ups
  pinMode(PIN_ENC_B, INPUT);
  pinMode(PIN_UPSHIFT, INPUT_PULLUP);
  pinMode(PIN_DOWNSHIFT, INPUT_PULLUP);
  analogReadResolution(12);             // 0..4095
  delay(50);                            // the MT6701 holds its ABZ outputs for 16 ms after power-up
  encPrev = encState();
  attachInterrupt(digitalPinToInterrupt(PIN_ENC_A), encISR, CHANGE);
  attachInterrupt(digitalPinToInterrupt(PIN_ENC_B), encISR, CHANGE);
}

void loop() {
  // 1. lines from the game ("?"; F lines are dropped)
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (lineLen && !lineOverlong) { line[lineLen] = 0; handleLine(line); }
      lineLen = 0;
      lineOverlong = false;
    } else if (lineLen < (int)sizeof(line) - 1) {
      line[lineLen++] = c;
    } else {
      lineOverlong = true;              // dropped whole, never parsed truncated
    }
  }

  // 2. input report at 500 Hz
  unsigned long nowUs = micros();
  if (nowUs - lastSampleUs >= SAMPLE_US) {
    lastSampleUs = nowUs;
    noInterrupts(); long count = encCount; interrupts();
    long steer = steerCentideg(count);
    static uint8_t buttons = 0;
    buttons = debounced(PIN_UPSHIFT, 1, buttons) | debounced(PIN_DOWNSHIFT, 2, buttons);
    char out[48];
    int len = PIN_HANDBRAKE < 0
      ? snprintf(out, sizeof(out), "W %ld %d %d %u\n", steer, analogRead(PIN_THROTTLE), analogRead(PIN_BRAKE), buttons)
      : snprintf(out, sizeof(out), "W %ld %d %d %u %d\n", steer, analogRead(PIN_THROTTLE), analogRead(PIN_BRAKE), buttons,
                 analogRead(PIN_HANDBRAKE));
    // never block here (game closed, host not reading): drop the sample instead
    if (Serial.availableForWrite() >= len) Serial.write(out, len);
  }
}
