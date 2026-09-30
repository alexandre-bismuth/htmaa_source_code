// QPAD Casino: Roulette, Blackjack and Ultimate Texas Hold'em on the QPAD-XIAO.
// Board: "Seeed XIAO RP2040" (Tools: CPU Speed 125 MHz, Optimize -O2)
// Libraries: Adafruit SSD1306 (+ dependencies)

#define BENCHMARK 0   // 1 = boot into the deterministic benchmark (results stream over USB serial)

#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include "hardware/gpio.h"
#include "common.h"

Adafruit_SSD1306 display(128, 64, &Wire, -1);   // I2C at 400 kHz while drawing
long bank = 1000;
Screen screen = MENU;
Deck deck;
uint32_t clockMs = 0;                           // game time; the benchmark drives it with a simulated clock
uint32_t bootFrameMs = 0;

uint32_t now() { return clockMs; }

void setup() {
  setLed(LED_OFF);
  Serial.begin(115200);
  Wire.begin();
  if (!display.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
    Serial.println("OLED init failed: check the solder joints / I2C address 0x3C");
    for (;;) { setLed(LED_RED); delay(150); setLed(LED_OFF); delay(150); }
  }
  display.setTextWrap(false);
  display.cp437(true);
  rngState = rp2040.hwrand32() | 1;
  drawSplash(0, N_BTNS);
  bootFrameMs = millis();
  calibrate();
#if BENCHMARK
  runBenchmark();
#endif
}

void loop() {
  uint32_t start = millis();
  clockMs = start;
  update(readButtons());
  draw();
  display.display();
  uint32_t used = millis() - start;
  if (used < FRAME_MS) delay(FRAME_MS - used);
}

void update(uint8_t ev) {
  ledUpdate();
  switch (screen) {
    case MENU:      menuUpdate(ev); break;
    case ROULETTE:  rouUpdate(ev);  break;
    case BLACKJACK: bjUpdate(ev);   break;
    case POKER:     uthUpdate(ev);  break;
  }
}

void draw() {
  display.clearDisplay();
  switch (screen) {
    case MENU:      menuDraw(); break;
    case ROULETTE:  rouDraw();  break;
    case BLACKJACK: bjDraw();   break;
    case POKER:     uthDraw();  break;
  }
}
