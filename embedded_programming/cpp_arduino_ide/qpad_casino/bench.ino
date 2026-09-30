// Deterministic benchmark (set BENCHMARK 1 in qpad_casino.ino): fixed seed, simulated 30 fps clock,
// scripted input. Results stream as "BENCH {json}" lines; embedded_programming/benchmarks/capture.py saves them.
// The script, seeds and measured items are identical in every language port.
#if BENCHMARK
#include <malloc.h>

extern "C" char __StackBottom, __StackTop, __end__, __data_start__, __data_end__, __bss_start__, __flash_binary_end;
static uint32_t* const STACK_BOTTOM = (uint32_t*)&__StackBottom;
static uint32_t* const STACK_TOP = (uint32_t*)&__StackTop;

struct Bench {
  static constexpr uint32_t SEED = 0xC0FFEE, HAND_SEED = 12345;
  static constexpr int N_HANDS = 250, REPS = 40, MAX_FRAMES = 2048;
  static constexpr uint32_t PAINT = 0xA5A5A5A5;

  struct Step { uint16_t wait; Btn btn; };        // wait = frames since the previous step
  static constexpr Step SCRIPT[] = {
    {20, RIGHT}, {12, RIGHT}, {12, RIGHT}, {12, OK},          // carousel once around, enter roulette
    {10, RIGHT}, {4, UP}, {4, UP}, {6, OK},                   // 50 on BLACK, spin
    {160, LEFT}, {4, LEFT}, {4, LEFT}, {6, OK},               // straight No.35, spin
    {160, BACK}, {12, RIGHT}, {12, OK},                       // -> blackjack
    {10, OK}, {45, OK}, {20, RIGHT}, {4, OK},                 // deal, hit, stand
    {110, OK}, {45, RIGHT}, {4, RIGHT}, {4, OK},              // deal, double
    {110, OK}, {45, RIGHT}, {4, OK},                          // deal, stand
    {110, BACK}, {12, RIGHT}, {12, OK},                       // -> hold'em
    {10, OK}, {45, OK}, {25, OK}, {25, RIGHT}, {4, OK},       // deal, check, check, bet 1x
    {120, OK}, {45, RIGHT}, {4, RIGHT}, {4, OK},              // deal, bet 4x
    {120, OK}, {45, OK}, {25, OK}, {25, OK},                  // deal, check, check, fold
    {120, BACK},
  };
  static constexpr int N_STEPS = sizeof(SCRIPT) / sizeof(SCRIPT[0]), TAIL_FRAMES = 60;

  struct Stat {
    uint32_t n = 0, lo = 0xFFFFFFFF, hi = 0;
    uint64_t sum = 0;
    void add(uint32_t v) { n++; sum += v; lo = min(lo, v); hi = max(hi, v); }
    uint32_t avgNs() const { return n ? sum * 1000 / n : 0; }
  };

  static void line(const char* sec, const char* name, const char* fmt, ...) {
    char kv[256];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(kv, sizeof kv, fmt, ap);
    va_end(ap);
    Serial.printf("BENCH {\"sec\":\"%s\",\"name\":\"%s\",%s}\n", sec, name, kv);
  }
  static void stat(const char* sec, const char* name, const Stat& s) {
    line(sec, name, "\"n\":%lu,\"avg_ns\":%lu,\"min_us\":%lu,\"max_us\":%lu", s.n, s.avgNs(), s.lo, s.hi);
  }
  // Average of a tight loop, for operations shorter than the 1 us timer.
  template <class F> static void batch(const char* sec, const char* name, uint32_t n, F f) {
    uint32_t t0 = micros();
    for (uint32_t i = 0; i < n; i++) f(i);
    uint32_t us = micros() - t0;
    line(sec, name, "\"n\":%lu,\"avg_ns\":%lu", n, (uint32_t)((uint64_t)us * 1000 / n));
  }
  static void progress(const char* what) {
    display.clearDisplay();
    printCenter(10, "BENCHMARK", 2);
    printCenter(34, what);
    display.display();
  }
  static uint32_t crc32(uint32_t crc, const uint8_t* p, size_t n) {   // zlib-compatible, chainable
    crc = ~crc;
    while (n--) {
      crc ^= *p++;
      for (int k = 0; k < 8; k++) crc = crc >> 1 ^ (0xEDB88320 & -(crc & 1));
    }
    return ~crc;
  }

  static void resetGame() {
    bank = 1000;
    screen = MENU;
    rngState = SEED;
    clockMs = 1000;
    menuReset(); rouReset(); bjReset(); uthReset();
    flashLed(LED_OFF);
  }
  // Plays SCRIPT (plus a short tail); frame(ev) does one frame's work.
  template <class F> static uint32_t runScript(F frame) {
    uint32_t frames = 0, nextAt = SCRIPT[0].wait;
    int step = 0, tail = 0;
    while (step < N_STEPS || tail++ < TAIL_FRAMES) {
      uint8_t ev = 0;
      if (step < N_STEPS && frames == nextAt) {
        ev = 1 << SCRIPT[step++].btn;
        if (step < N_STEPS) nextAt = frames + SCRIPT[step].wait;
      }
      frame(ev);
      frames++;
    }
    return frames;
  }

  static void paintStack() {
    uint32_t* p = STACK_BOTTOM;
    uint32_t* sp = min((uint32_t*)__builtin_frame_address(0) - 64, STACK_TOP);
    while (p < sp) *p++ = PAINT;
  }
  static uint32_t stackUsed() {
    uint32_t* p = STACK_BOTTOM;
    while (p < STACK_TOP && *p == PAINT) p++;
    return (uint8_t*)STACK_TOP - (uint8_t*)p;
  }
  static uint32_t largestBlock() {                 // biggest malloc that still succeeds
    uint32_t lo = 0, hi = rp2040.getFreeHeap();
    while (lo < hi) {
      uint32_t mid = (lo + hi + 1) / 2;
      void* p = malloc(mid);
      if (p) { free(p); lo = mid; } else hi = mid - 1;
    }
    return lo;
  }

  static void boot(uint32_t readyMs) {
    line("boot", "timing", "\"first_frame_ms\":%lu,\"ready_ms\":%lu", bootFrameMs, readyMs);
  }

  static void memoryStatic() {
    line("memory", "static",
         "\"flash_image_bytes\":%lu,\"flash_total_bytes\":2097152,\"data_bytes\":%lu,\"bss_bytes\":%lu,"
         "\"ram_static_bytes\":%lu,\"ram_total_bytes\":270336,\"heap_total_bytes\":%d,\"stack_bytes\":%lu",
         (uint32_t)(uintptr_t)&__flash_binary_end - 0x10000000, (uint32_t)(uintptr_t)&__data_end__ - (uint32_t)(uintptr_t)&__data_start__,
         (uint32_t)(uintptr_t)&__bss_end__ - (uint32_t)(uintptr_t)&__bss_start__, (uint32_t)(uintptr_t)&__end__ - 0x20000000,
         rp2040.getTotalHeap(), (uint32_t)(uintptr_t)&__StackTop - (uint32_t)(uintptr_t)&__StackBottom);
    struct mallinfo m = mallinfo();
    line("memory", "heap_boot", "\"used_bytes\":%d,\"free_bytes\":%d,\"arena_bytes\":%d",
         m.uordblks, rp2040.getFreeHeap(), m.arena);
  }

  static void touch() {
    progress("touch");
    for (int b = 0; b < N_BTNS; b++) {
      const int n = 200;
      int64_t sum = 0, sq = 0;
      int lo = 1 << 30, hi = 0;
      uint32_t t0 = micros();
      for (int i = 0; i < n; i++) {
        int v = measureOnce(BTN_PIN[b]);
        sum += v; sq += (int64_t)v * v;
        lo = min(lo, v); hi = max(hi, v);
      }
      uint32_t us = micros() - t0;
      float var = (float)(sq * n - sum * sum) / ((float)n * n);
      line("touch", BTN_PAD[b], "\"n\":%d,\"avg_ns\":%lu,\"count_min\":%d,\"count_max\":%d,\"count_mean_x100\":%ld,\"count_sd_x100\":%lu",
           n, (uint32_t)((uint64_t)us * 1000 / n), lo, hi, (long)(sum * 100 / n), (uint32_t)(sqrtf(var) * 100));
    }
    Stat s;
    for (int i = 0; i < 100; i++) {
      uint32_t t0 = micros();
      scanPads();
      s.add(micros() - t0);
    }
    stat("touch", "scan6", s);
  }

  static void gfx() {
    progress("graphics");
    const int n = 300;
    batch("gfx", "clear", n, [](uint32_t) { display.clearDisplay(); });
    batch("gfx", "fill_screen", n, [](uint32_t) { display.fillRect(0, 0, 128, 64, WHITE); });
    batch("gfx", "line", n, [](uint32_t) { display.drawLine(0, 0, 127, 63, WHITE); });
    batch("gfx", "circle_r16", n, [](uint32_t) { display.drawCircle(64, 32, 16, WHITE); });
    batch("gfx", "fill_circle_r16", n, [](uint32_t) { display.fillCircle(64, 32, 16, WHITE); });
    batch("gfx", "fill_round_rect", n, [](uint32_t) { display.fillRoundRect(10, 10, 40, 30, 4, WHITE); });
    batch("gfx", "fill_triangle", n, [](uint32_t) { display.fillTriangle(0, 0, 127, 20, 40, 63, WHITE); });
    batch("gfx", "text_21_s1", n, [](uint32_t) { printAt(0, 0, "ABCDEFGHIJKLMNOPQRSTU"); });
    batch("gfx", "text_10_s2", n, [](uint32_t) { printAt(0, 0, "ABCDEFGHIJ", 2); });
    batch("gfx", "card", n, [](uint32_t i) { drawCard(40, 20, i % 52); });
    batch("gfx", "card_back", n, [](uint32_t) { drawCardBack(40, 20); });
  }

  static void push() {
    progress("display push");
    Stat s;
    for (int i = 0; i < 100; i++) {
      uint32_t t0 = micros();
      display.display();
      s.add(micros() - t0);
    }
    stat("display", "push", s);
    line("display", "theory", "\"i2c_hz\":400000,\"payload_bytes\":1024,\"min_us\":23040");
  }

  static void logic() {
    progress("game logic");
    static uint8_t hands[N_HANDS][7];
    rngState = HAND_SEED;
    for (int h = 0; h < N_HANDS; h++) {
      deck.shuffle();
      memcpy(hands[h], deck.c, 7);
    }
    uint32_t sum = 0;
    rngState = SEED;
    batch("logic", "shuffle", 2000, [&](uint32_t) { deck.shuffle(); sum += deck.c[0]; });
    line("logic", "shuffle_check", "\"checksum\":%lu", sum);
    sum = 0;
    batch("logic", "bj_total", N_HANDS * REPS, [&](uint32_t i) { sum += bjTotal(hands[i % N_HANDS], 3); });
    line("logic", "bj_total_check", "\"checksum\":%lu", sum);
    sum = 0;
    batch("logic", "eval5", N_HANDS * REPS, [&](uint32_t i) { sum += evalCards(hands[i % N_HANDS], 5); });
    line("logic", "eval5_check", "\"checksum\":%lu", sum);
    sum = 0;
    batch("logic", "best7", N_HANDS * REPS, [&](uint32_t i) { sum += bestHand(hands[i % N_HANDS], 7); });
    line("logic", "best7_check", "\"checksum\":%lu", sum);
  }

  // Full game on the simulated clock, with the real touch scan and display push every frame.
  static void playthrough() {
    progress("playthrough");
    static uint32_t totals[MAX_FRAMES];
    static const char* const SCREENS[] = {"menu", "roulette", "blackjack", "holdem"};
    Stat in, upd, drw, psh, tot, lat, byScreen[4];
    uint32_t crc = 0, n = 0;
    resetGame();
    uint32_t frames = runScript([&](uint8_t ev) {
      clockMs += FRAME_MS;
      uint32_t t0 = micros();
      scanPads();
      uint32_t t1 = micros();
      update(ev);
      uint32_t t2 = micros();
      draw();
      uint32_t t3 = micros();
      display.display();
      uint32_t t4 = micros();
      crc = crc32(crc, display.getBuffer(), 1024);
      in.add(t1 - t0); upd.add(t2 - t1); drw.add(t3 - t2); psh.add(t4 - t3); tot.add(t4 - t0);
      byScreen[screen].add(t3 - t2);
      if (ev) lat.add(t4 - t0);
      if (n < MAX_FRAMES) totals[n++] = t4 - t0;
    });
    qsort(totals, n, sizeof totals[0], [](const void* a, const void* b) {
      uint32_t x = *(const uint32_t*)a, y = *(const uint32_t*)b;
      return (x > y) - (x < y);
    });
    stat("frame", "input", in);
    stat("frame", "update", upd);
    stat("frame", "draw", drw);
    stat("frame", "push", psh);
    stat("frame", "total", tot);
    for (int i = 0; i < 4; i++) if (byScreen[i].n) stat("draw_screen", SCREENS[i], byScreen[i]);
    line("frame", "percentiles", "\"p50_us\":%lu,\"p99_us\":%lu,\"unlocked_fps_x100\":%lu,\"frames\":%lu",
         totals[n / 2], totals[n * 99 / 100], (uint32_t)(100000000ULL * tot.n / tot.sum), frames);
    stat("latency", "input_to_display", lat);
    line("parity", "playthrough", "\"bank\":%ld,\"rng\":%lu,\"frame_crc32\":%lu", bank, rngState, crc);
  }

  // Leak check: play the script twice from the same seed; a leak-free program ends both runs with the
  // same heap. Heap changes are watched on every frame of both runs.
  static void soak() {
    progress("memory soak");
    uint32_t before = largestBlock(), changed = 0, frames = 0;
    int used[2], last = 0, maxDelta = 0;
    for (int rep = 0; rep < 2; rep++) {
      resetGame();
      last = mallinfo().uordblks;
      frames += runScript([&](uint8_t ev) {
        clockMs += FRAME_MS;
        update(ev);
        draw();
        int now = mallinfo().uordblks;
        if (now != last) changed++;
        maxDelta = max(maxDelta, abs(now - last));
        last = now;
      });
      used[rep] = mallinfo().uordblks;
    }
    line("leaks", "soak", "\"frames\":%lu,\"heap_used_before\":%d,\"heap_used_after\":%d,\"leaked_bytes\":%d,"
         "\"frames_with_heap_change\":%lu,\"max_heap_delta\":%d", frames, used[0], used[1], used[1] - used[0], changed,
         maxDelta);
    line("leaks", "fragmentation", "\"free_bytes\":%d,\"largest_block_before\":%lu,\"largest_block_after\":%lu",
         rp2040.getFreeHeap(), before, largestBlock());
  }

  static void run() {
    uint32_t readyMs = millis();                  // splash shown, pads calibrated
    progress("run capture.py");
    while (!Serial) delay(10);
    delay(500);
    paintStack();
    Serial.printf("BENCH_BEGIN {\"lang\":\"cpp\",\"cpu_hz\":%d,\"frame_ms\":%lu,\"seed\":%lu}\n",
                  rp2040.f_cpu(), FRAME_MS, SEED);
    boot(readyMs);
    memoryStatic();
    touch();
    gfx();
    push();
    logic();
    playthrough();
    soak();
    line("memory", "stack", "\"stack_used_bytes\":%lu,\"stack_bytes\":%lu", stackUsed(),
         (uint32_t)(uintptr_t)&__StackTop - (uint32_t)(uintptr_t)&__StackBottom);
    Serial.println("BENCH_END");
    progress("done");
    for (;;) delay(1000);
  }
};

void runBenchmark() { Bench::run(); }
#endif
