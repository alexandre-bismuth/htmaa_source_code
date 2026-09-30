// Frame-buffer-only SSD1306: same buffer layout and drawPixel as the Adafruit driver.
#pragma once
#include <Adafruit_GFX.h>
#include <Wire.h>
#define SSD1306_BLACK 0
#define SSD1306_WHITE 1
#define SSD1306_INVERSE 2
#define BLACK SSD1306_BLACK
#define WHITE SSD1306_WHITE
#define SSD1306_SWITCHCAPVCC 0x02
class Adafruit_SSD1306 : public Adafruit_GFX {
 public:
  Adafruit_SSD1306(uint8_t w, uint8_t h, TwoWire*, int8_t) : Adafruit_GFX(w, h) {}
  bool begin(uint8_t, uint8_t) { return true; }
  void clearDisplay() { memset(buffer, 0, sizeof buffer); }
  void display();                                   // provided by the host harness
  uint8_t* getBuffer() { return buffer; }
  void drawPixel(int16_t x, int16_t y, uint16_t c) override {
    if (x < 0 || y < 0 || x >= 128 || y >= 64) return;
    uint8_t& b = buffer[x + (y / 8) * 128];
    if (c == SSD1306_WHITE) b |= 1 << (y & 7);
    else if (c == SSD1306_BLACK) b &= ~(1 << (y & 7));
    else b ^= 1 << (y & 7);
  }
  void drawFastHLine(int16_t x, int16_t y, int16_t w, uint16_t c) override {   // clipped like the real driver
    if (y < 0 || y >= 64) return;
    if (x < 0) { w += x; x = 0; }
    if (x + w > 128) w = 128 - x;
    for (int i = 0; i < w; i++) drawPixel(x + i, y, c);
  }
  void drawFastVLine(int16_t x, int16_t y, int16_t h, uint16_t c) override {
    if (x < 0 || x >= 128) return;
    if (y < 0) { h += y; y = 0; }
    if (y + h > 64) h = 64 - y;
    for (int i = 0; i < h; i++) drawPixel(x, y + i, c);
  }
  uint8_t buffer[1024];
};
