// car_inputs board (HTMAA week 5) - Wokwi simulation of the KiCad PCB.
//
// The real board carries a Seeed XIAO RP2040. Wokwi has no XIAO RP2040, so the simulation uses the
// XIAO ESP32-C3: same footprint and same D0..D10 pin names, so the wiring below matches the PCB 1:1
// and this sketch builds unchanged for the XIAO RP2040.

#include <Arduino.h>

#ifndef IRAM_ATTR
#define IRAM_ATTR
#endif

const int PIN_THROTTLE = A0, PIN_BRAKE = A1, PIN_HANDBRAKE = A2;
const int PIN_UPSHIFT = D3, PIN_DOWNSHIFT = D4;
const int PIN_ENC_A = D6, PIN_ENC_B = D5;

volatile long encCount = 0;
void IRAM_ATTR encISR() {
  // full quadrature decoding on both channels
  static uint8_t prev = 0;
  uint8_t cur = (digitalRead(PIN_ENC_A) << 1) | digitalRead(PIN_ENC_B);
  static const int8_t table[16] = {0, -1, 1, 0, 1, 0, 0, -1, -1, 0, 0, 1, 0, 1, -1, 0};
  encCount += table[(prev << 2) | cur];
  prev = cur;
}

int percent(int raw) { return (long)raw * 100 / 4095; }

void setup() {
  Serial.begin(115200);
  // external 4.99k pull-ups on the board (R7..R10), so plain INPUT
  pinMode(PIN_UPSHIFT, INPUT);
  pinMode(PIN_DOWNSHIFT, INPUT);
  pinMode(PIN_ENC_A, INPUT);
  pinMode(PIN_ENC_B, INPUT);
  attachInterrupt(digitalPinToInterrupt(PIN_ENC_A), encISR, CHANGE);
  attachInterrupt(digitalPinToInterrupt(PIN_ENC_B), encISR, CHANGE);
  analogReadResolution(12);   // 0..4095
  Serial.println("car_inputs ready");
}

void loop() {
  static char last[96] = "";
  noInterrupts(); long count = encCount; interrupts();
  char out[96];
  snprintf(out, sizeof(out), "steer %+4ld | throttle %3d%% | brake %3d%% | handbrake %3d%% | up %d | down %d",
           count / 4, percent(analogRead(PIN_THROTTLE)), percent(analogRead(PIN_BRAKE)),
           percent(analogRead(PIN_HANDBRAKE)), digitalRead(PIN_UPSHIFT) == LOW, digitalRead(PIN_DOWNSHIFT) == LOW);
  if (strcmp(out, last) != 0) {   // print only on change
    Serial.println(out);
    strcpy(last, out);
  }
  delay(20);
}
