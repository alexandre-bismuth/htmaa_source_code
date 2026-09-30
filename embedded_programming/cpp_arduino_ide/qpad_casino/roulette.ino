// Roulette: European single-zero wheel, one bet per spin.

const char* const OUTSIDE[] = {"RED", "BLACK", "EVEN", "ODD", "1-18", "19-36", "1ST 12", "2ND 12", "3RD 12"};
const uint32_t SPIN_MS = 4200;

Round rou;
int rouBet;                    // 0..8 outside bets, 9.. straight numbers
int rouFrom, rouTo;            // wheel positions (pockets) of the current spin
uint32_t rouSpinAt;

void rouReset() { rou = Round(); rouBet = rouFrom = rouTo = 0; rouSpinAt = 0; }
void rouEnter() { rou.banner = false; }

void betName(char* b, int bet) {
  if (bet < 9) strcpy(b, OUTSIDE[bet]);
  else sprintf(b, "No.%d", bet - 9);
}

void rouUpdate(uint8_t ev) {
  uint32_t t = now();
  payWhenShown(rou);
  if (t < rou.busyUntil) return;
  rouFrom = rouTo = rouTo % 37;
  if (ev) rou.banner = false;
  if (has(ev, LEFT)) rouBet = (rouBet + N_BETS - 1) % N_BETS;
  if (has(ev, RIGHT)) rouBet = (rouBet + 1) % N_BETS;
  betInput(rou, ev, 1);
  if (has(ev, BACK)) { screen = MENU; return; }
  if (!has(ev, OK) || !canBet(rou, 1)) return;

  long stake = CHIPS[rou.betIdx];
  int n = rngBelow(37);
  bank -= stake;
  rouTo = rouFrom + 2 * 37 + (wheelIndex(n) - rouFrom + 37) % 37;   // two full turns, then land on n
  rouSpinAt = t;
  long payout = betWins(rouBet, n) ? stake * (betPays(rouBet) + 1) : 0;
  char msg[20];
  sprintf(msg, "%d %s", n, n == 0 ? "GREEN" : isRed(n) ? "RED" : "BLACK");
  showResult(rou, msg, payout, payout - stake, t + SPIN_MS + 250);
}

// Red pockets are filled, black ones outlined, zero double-framed.
void drawPocket(int x, int y, int n) {
  char b[12];
  sprintf(b, "%d", n);
  int tx = x + (13 - textW(b)) / 2;
  if (isRed(n)) {
    display.fillRoundRect(x, y, 13, 13, 2, WHITE);
    printAt(tx, y + 3, b, 1, BLACK);
  } else {
    display.drawRoundRect(x, y, 13, 13, 2, WHITE);
    if (n == 0) display.drawRect(x + 2, y + 2, 9, 9, WHITE);
    printAt(tx, y + 3, b);
  }
}

void rouDraw() {
  char b[16];
  int e = easeOut(now() - rouSpinAt, SPIN_MS);
  int pix = rouFrom * 16 + ((rouTo - rouFrom) * 16 * e >> 10);    // strip position in pixels
  drawHeader("ROULETTE");
  for (int k = -5; k <= 5; k++) drawPocket(57 + k * 16 - pix % 16, 12, WHEEL[(pix / 16 + k + 37) % 37]);
  display.drawRect(55, 10, 17, 17, WHITE);
  display.fillTriangle(60, 27, 66, 27, 63, 30, WHITE);
  printAt(0, 34, "\x11");
  printAt(123, 34, "\x10");
  betName(b, rouBet);
  printCenter(32, b, 2);
  sprintf(b, "PAYS %d TO 1", betPays(rouBet));
  printCenter(47, b);
  drawBetBar("BET", CHIPS[rou.betIdx], "SPIN");
  if (bannerVisible(rou)) drawBanner(28, rou.msg, rou.net);
}
