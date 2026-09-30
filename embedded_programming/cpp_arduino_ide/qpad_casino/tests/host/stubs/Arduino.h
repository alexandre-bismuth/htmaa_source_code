// Minimal Arduino stand-in so the sketch runs on a computer (host tests only).
#pragma once
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <cstdlib>
#include <cstdarg>
#include <cmath>
#include <algorithm>
#include "Print.h"
using std::min;
using std::max;
typedef uint8_t byte;
#define OUTPUT 1
#define INPUT 0
#define LOW 0
#define HIGH 1
#define __not_in_flash_func(f) f
#define radians(d) ((d) * M_PI / 180.0)
class __FlashStringHelper;
struct String {
  const char* c_str() const { return ""; }
  unsigned length() const { return 0; }
};
extern "C" char __bss_end__;
static const uint8_t D0 = 26, D1 = 27, D7 = 1, D8 = 2, D9 = 4, D10 = 3;
uint32_t millis();
uint32_t micros();
inline void delay(uint32_t) {}
inline void delayMicroseconds(uint32_t) {}
inline void pinMode(int, int) {}
inline void digitalWrite(int, int) {}
inline void noInterrupts() {}
inline void interrupts() {}
struct HostSerial {
  void begin(long) {}
  explicit operator bool() const { return true; }
  void println(const char* s) { puts(s); }
  int printf(const char* f, ...) { va_list a; va_start(a, f); int n = vprintf(f, a); va_end(a); return n; }
};
extern HostSerial Serial;
struct HostRP2040 {
  uint32_t hwrand32() { return 0x12345678; }
  int getFreeHeap() { return 200000; }
  int getTotalHeap() { return 250000; }
  int f_cpu() { return 125000000; }
};
extern HostRP2040 rp2040;
