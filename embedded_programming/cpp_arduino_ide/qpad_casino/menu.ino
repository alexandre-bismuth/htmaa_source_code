// Main menu: a carousel of the three games with animated icons.

const char* const GAMES[] = {"ROULETTE", "BLACKJACK", "ULTIMATE HOLD'EM"};
const uint32_t MENU_SLIDE_MS = 220;

struct {
  uint8_t sel, prev;
  int8_t dir;
  uint32_t slideAt;
} menu;

void menuReset() { menu = {0, 0, 1, 0}; }

void menuUpdate(uint8_t ev) {
  int step = has(ev, RIGHT) || has(ev, DOWN) ? 1 : has(ev, LEFT) || has(ev, UP) ? -1 : 0;
  if (step) {
    menu.prev = menu.sel;
    menu.sel = (menu.sel + step + 3) % 3;
    menu.dir = step;
    menu.slideAt = now();
  }
  if (!has(ev, OK)) return;
  if (menu.sel == 0) { screen = ROULETTE;  rouEnter(); }
  if (menu.sel == 1) { screen = BLACKJACK; bjEnter(); }
  if (menu.sel == 2) { screen = POKER;     uthEnter(); }
}

void drawWheelIcon(int cx, int cy) {
  uint32_t t = now();
  int a0 = t / 25 % 72;                                   // wheel turns 5 deg every 25 ms
  display.drawCircle(cx, cy, 16, WHITE);
  display.drawCircle(cx, cy, 11, WHITE);
  for (int k = 0; k < 18; k++) {
    int a = a0 + k * 4;
    display.drawLine(cx + icos(11, a), cy + isin(11, a), cx + icos(16, a), cy + isin(16, a), WHITE);
  }
  for (int k = 0; k < 4; k++) {
    int a = a0 + k * 18;
    display.drawLine(cx, cy, cx + icos(11, a), cy + isin(11, a), WHITE);
  }
  display.fillCircle(cx, cy, 3, WHITE);
  int b = 71 - t / 12 % 72;                               // ball runs the other way
  display.fillCircle(cx + icos(14, b), cy + isin(14, b), 1, WHITE);
}

void drawBigCard(int x, int y, char rank, uint8_t suit) {
  display.fillRoundRect(x - 1, y - 1, 24, 32, 3, BLACK);
  display.fillRoundRect(x, y, 22, 30, 3, WHITE);
  display.drawChar(x + 3, y + 3, rank, BLACK, BLACK, 2);
  display.drawChar(x + 9, y + 14, suit, BLACK, BLACK, 2);
}

void drawCardsIcon(int cx, int cy) {
  int lift = isin(2, now() / 40 % 72);
  drawBigCard(cx - 21, cy - 15, 'A', 6);
  drawBigCard(cx - 1, cy - 13 + lift, 'K', 3);
}

void drawChipIcon(int cx, int cy) {
  int a0 = now() / 33 % 72;
  display.fillCircle(cx, cy, 16, WHITE);
  display.fillCircle(cx, cy, 11, BLACK);
  display.drawCircle(cx, cy, 9, WHITE);
  for (int k = 0; k < 6; k++) {
    int a = a0 + k * 12;
    display.fillCircle(cx + icos(14, a), cy + isin(14, a), 2, BLACK);
  }
  display.drawChar(cx - 5, cy - 7, 6, WHITE, WHITE, 2);
}

void drawMenuItem(int i, int dx) {
  if (i == 0) drawWheelIcon(64 + dx, 30);
  if (i == 1) drawCardsIcon(64 + dx, 30);
  if (i == 2) drawChipIcon(64 + dx, 30);
  printCenter(49, GAMES[i], 1, WHITE, 64 + dx);
}

void menuDraw() {
  char b[16];
  printAt(0, 0, "QPAD CASINO");
  sprintf(b, "$%ld", bank);
  printRight(127, 0, b);
  uint32_t k = min(now() - menu.slideAt, MENU_SLIDE_MS);
  int off = menu.dir * 128 * (1024 - easeOut(k, MENU_SLIDE_MS)) >> 10;
  drawMenuItem(menu.sel, off);
  if (k < MENU_SLIDE_MS) drawMenuItem(menu.prev, off - menu.dir * 128);
  display.fillRect(0, 10, 9, 38, BLACK);
  display.fillRect(119, 10, 9, 38, BLACK);
  printAt(1, 27, "\x11");
  printAt(122, 27, "\x10");
  for (int i = 0; i < 3; i++) {
    if (i == menu.sel) display.fillCircle(56 + i * 8, 60, 2, WHITE);
    else display.drawCircle(56 + i * 8, 60, 2, WHITE);
  }
}
