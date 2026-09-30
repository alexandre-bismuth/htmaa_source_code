// Drawing helpers, cards, LED and the round/banner/bet logic shared by the games.

const uint8_t LED_R = 17, LED_G = 16, LED_B = 25;                 // active LOW
const char RANKS[] = "23456789TJQKA";
// sin(k * 5 deg) * 1024: integer trig for the menu icons (no FPU on the M0+)
const int16_t SIN72[72] = {
  0, 89, 178, 265, 350, 433, 512, 587, 658, 724, 784, 839, 887, 928, 962, 989, 1008, 1020,
  1024, 1020, 1008, 989, 962, 928, 887, 839, 784, 724, 658, 587, 512, 433, 350, 265, 178, 89,
  0, -89, -178, -265, -350, -433, -512, -587, -658, -724, -784, -839, -887, -928, -962, -989, -1008, -1020,
  -1024, -1020, -1008, -989, -962, -928, -887, -839, -784, -724, -658, -587, -512, -433, -350, -265, -178, -89};

Led ledColor = LED_OFF;
uint32_t ledUntil = 0;

// ---------- Text ----------
int textW(const char* s, int size) { return strlen(s) * 6 * size - size; }

void printAt(int x, int y, const char* s, int size, uint16_t c) {
  display.setTextSize(size);
  display.setTextColor(c);
  display.setCursor(x, y);
  display.print(s);
}
void printCenter(int y, const char* s, int size, uint16_t c, int cx) { printAt(cx - textW(s, size) / 2, y, s, size, c); }
void printRight(int x, int y, const char* s, int size, uint16_t c) { printAt(x - textW(s, size) + 1, y, s, size, c); }

void fmtMoney(char* b, long v) { sprintf(b, v > 0 ? "+%ld" : "%ld", v); }

// ---------- Widgets ----------
void drawHeader(const char* title) {
  char b[16];
  printAt(0, 0, title);
  sprintf(b, "$%ld", bank);
  printRight(127, 0, b);
}

// Equal slots along the bottom; the selected one is inverted (= what OK does).
void drawBar(const char* const* items, int n, int sel) {
  for (int i = 0; i < n; i++) {
    int x0 = i * 128 / n, x1 = (i + 1) * 128 / n, cx = (x0 + x1) / 2;
    if (i == sel) {
      display.fillRoundRect(x0, 55, x1 - x0, 9, 2, WHITE);
      printCenter(56, items[i], 1, BLACK, cx);
    } else {
      printCenter(56, items[i], 1, WHITE, cx);
    }
  }
}

void drawBetBar(const char* label, long amount, const char* action) {
  char b[24];
  sprintf(b, "\x12 %s %ld", label, amount);
  printAt(0, 56, b);
  int w = textW(action) + 8;
  display.fillRoundRect(128 - w, 55, w, 9, 2, WHITE);
  printRight(123, 56, action, 1, BLACK);
}

void drawBanner(int y, const char* line1, long net) {
  char b[16];
  fmtMoney(b, net);
  display.fillRect(10, y, 108, 32, BLACK);
  display.drawRect(10, y, 108, 32, WHITE);
  display.drawRect(12, y + 2, 104, 28, WHITE);
  printCenter(y + 5, line1);
  printCenter(y + 14, b, 2);
}

// ---------- Integer animation math ----------
int easeOut(uint32_t k, uint32_t total) {       // cubic ease-out, 0..1024
  if (k >= total) return 1024;
  uint32_t r = 1024 - k * 1024 / total;
  return 1024 - (r * r * r >> 20);
}
int icos(int r, int a) { return (r * SIN72[(a + 18) % 72] + 512) >> 10; }   // a in 5 deg steps
int isin(int r, int a) { return (r * SIN72[a % 72] + 512) >> 10; }

// ---------- Cards ----------
void drawCard(int x, int y, uint8_t card) {
  display.fillRoundRect(x - 1, y - 1, CW + 2, CH + 2, 2, BLACK);
  display.fillRoundRect(x, y, CW, CH, 2, WHITE);
  int r = card % 13;
  if (r == 8) {                                                     // "10" squeezed into one card width
    display.drawChar(x, y + 1, '1', BLACK, BLACK, 1);
    display.drawChar(x + 5, y + 1, '0', BLACK, BLACK, 1);
  } else {
    display.drawChar(x + 3, y + 1, RANKS[r], BLACK, BLACK, 1);
  }
  display.drawChar(x + 3, y + 9, 3 + card / 13, BLACK, BLACK, 1);  // CP437 3..6 = hearts diamonds clubs spades
}

void drawCardBack(int x, int y) {
  display.fillRoundRect(x - 1, y - 1, CW + 2, CH + 2, 2, BLACK);
  display.drawRoundRect(x, y, CW, CH, 2, WHITE);
  for (int j = 2; j < CH - 2; j++)
    for (int i = 2; i < CW - 2; i++)
      if ((i + j) % 4 == 0 || (i - j + 40) % 4 == 0) display.drawPixel(x + i, y + j, WHITE);
}

bool isUp(const Slot& s) { return s.showAt && now() >= s.showAt; }

// Slides in from the shoe (top right), flips edge-on when turned face up.
void drawSlot(int x, int y, const Slot& s) {
  uint32_t t = now();
  if (t < s.dealAt) return;
  uint32_t k = t - s.dealAt;
  if (k < SLIDE_MS) {
    int e = easeOut(k, SLIDE_MS);
    x = 120 + ((x - 120) * e >> 10);
    y = -CH + ((y + CH) * e >> 10);
  }
  if (s.showAt > s.dealAt && t >= s.showAt && t - s.showAt < FLIP_MS) {
    display.fillRect(x + 4, y, 3, CH, WHITE);
    return;
  }
  if (isUp(s)) drawCard(x, y, s.card);
  else drawCardBack(x, y);
}

void drawHand(const Hand& h, int y, int maxW) {
  int step = h.n > 1 ? min(CW + 2, (maxW - CW) / (h.n - 1)) : 0;
  for (int i = 0; i < h.n; i++) drawSlot(i * step, y, h.s[i]);
}

int allCards(const Hand& h, uint8_t* out) {
  for (int i = 0; i < h.n; i++) out[i] = h.s[i].card;
  return h.n;
}

int upCards(const Hand& h, uint8_t* out) {
  int n = 0;
  for (int i = 0; i < h.n; i++)
    if (isUp(h.s[i])) out[n++] = h.s[i].card;
  return n;
}

// ---------- LED ----------
void setLed(Led c) {
  pinMode(LED_R, OUTPUT); pinMode(LED_G, OUTPUT); pinMode(LED_B, OUTPUT);
  digitalWrite(LED_R, c == LED_RED ? LOW : HIGH);
  digitalWrite(LED_G, c == LED_GREEN ? LOW : HIGH);
  digitalWrite(LED_B, c == LED_BLUE ? LOW : HIGH);
}
void flashLed(Led c) { setLed(c); ledColor = c; ledUntil = now() + 900; }
void ledUpdate() {
  if (ledColor != LED_OFF && now() > ledUntil) flashLed(LED_OFF);
}

// ---------- Rounds: result banner, payout, bets ----------
void showResult(Round& g, const char* msg, long payout, long net, uint32_t at) {
  snprintf(g.msg, sizeof g.msg, "%s", msg);
  g.payout = payout;
  g.net = net;
  g.resultAt = at;
  g.busyUntil = at + 400;
  g.banner = true;
}

bool bannerVisible(const Round& g) {
  uint32_t t = now();
  return g.banner && t >= g.resultAt && t < g.resultAt + 2500;
}

// Pays out when the banner appears, so the bank doesn't change before the reveal.
void payWhenShown(Round& g) {
  if (g.payout < 0 || now() < g.resultAt) return;
  bank += g.payout;
  g.payout = -1;
  flashLed(g.net > 0 ? LED_GREEN : g.net < 0 ? LED_RED : LED_BLUE);
}

// mult = chips reserved per unit of bet (Hold'em needs ante + blind + 4x play).
void betInput(Round& g, uint8_t ev, int mult) {
  if (has(ev, UP) && g.betIdx < N_CHIPS - 1 && CHIPS[g.betIdx + 1] * mult <= bank) g.betIdx++;
  if (has(ev, DOWN) && g.betIdx > 0) g.betIdx--;
  while (g.betIdx > 0 && CHIPS[g.betIdx] * mult > bank) g.betIdx--;
}

bool canBet(Round& g, int mult) {
  if (bank >= CHIPS[0] * mult) return true;
  bank += 1000;
  showResult(g, "HOUSE LOAN", -1, 1000, now());
  flashLed(LED_BLUE);
  return false;
}
