// Blackjack: fresh deck every hand, dealer stands on 17, blackjack pays 3:2.

enum BjPhase : uint8_t { BJ_BET, BJ_CHECK, BJ_PLAY };
const char* const BJ_OPTS[] = {"HIT", "STAND", "DOUBLE"};

Round bj;
BjPhase bjPhase;
Hand bjPlayer, bjDealer;
long bjBet, bjStake;           // bjBet doubles on DOUBLE; bjStake = total chips put in
int bjSel;

void bjReset() { bj = Round(); bjEnter(); bjBet = bjStake = 0; }
void bjEnter() { bjPhase = BJ_BET; bjPlayer.n = bjDealer.n = 0; bj.banner = false; }

int bjOptions() { return bjPlayer.n == 2 && bank >= bjBet ? 3 : 2; }

int handTotal(const Hand& h) {
  uint8_t c[12];
  return bjTotal(c, allCards(h, c));
}

void bjDeal() {
  uint32_t t = now();
  bjBet = bjStake = CHIPS[bj.betIdx];
  bank -= bjBet;
  deck.shuffle();
  bjPlayer.n = bjDealer.n = 0;
  bjPlayer.add(deck.draw(), t, t);
  bjDealer.add(deck.draw(), t + 250, t + 250);
  bjPlayer.add(deck.draw(), t + 500, t + 500);
  bjDealer.add(deck.draw(), t + 750, 0);                  // hole card
  bj.busyUntil = t + 750 + SLIDE_MS;
  bjPhase = BJ_CHECK;
  bjSel = 0;
}

// Reveals the hole card, lets the dealer draw to 17 and settles the hand.
void bjFinish(uint32_t t) {
  bjDealer.s[1].showAt = t;
  t += 450;
  int p = handTotal(bjPlayer);
  bool natural = p == 21 && bjPlayer.n == 2;
  if (p <= 21 && !natural)
    while (handTotal(bjDealer) < 17) { bjDealer.add(deck.draw(), t, t); t += 550; }
  const char* msg;
  long ret = bjSettle(bjBet, p, bjPlayer.n, handTotal(bjDealer), bjDealer.n, &msg);
  showResult(bj, msg, ret, ret - bjStake, t);
  bjPhase = BJ_BET;
}

void bjUpdate(uint8_t ev) {
  uint32_t t = now();
  payWhenShown(bj);
  if (t < bj.busyUntil) return;

  if (bjPhase == BJ_BET) {
    if (ev) bj.banner = false;
    betInput(bj, ev, 1);
    if (has(ev, BACK)) { screen = MENU; return; }
    if (has(ev, OK) && canBet(bj, 1)) bjDeal();
    return;
  }
  if (bjPhase == BJ_CHECK) {                              // naturals end the hand at once
    if (handTotal(bjPlayer) == 21 || handTotal(bjDealer) == 21) bjFinish(t);
    else bjPhase = BJ_PLAY;
    return;
  }
  if (has(ev, LEFT) && bjSel > 0) bjSel--;
  if (has(ev, RIGHT) && bjSel < bjOptions() - 1) bjSel++;
  if (!has(ev, OK)) return;
  if (bjSel == 1) { bjFinish(t); return; }                // STAND
  if (bjSel == 2) { bank -= bjBet; bjStake += bjBet; bjBet *= 2; }
  bjPlayer.add(deck.draw(), t, t);                        // HIT or DOUBLE
  bj.busyUntil = t + SLIDE_MS;
  if (bjSel == 2 || handTotal(bjPlayer) >= 21) bjFinish(t + SLIDE_MS + 200);
  bjSel = min(bjSel, bjOptions() - 1);
}

void drawTotal(const Hand& h, int y) {
  uint8_t c[12];
  int n = upCards(h, c);
  if (!n) return;
  char b[12];
  sprintf(b, "%d", bjTotal(c, n));
  printRight(127, y, b, 2);
}

void bjDraw() {
  drawHeader("BLACKJACK");
  if (!bjPlayer.n) {
    printCenter(20, "BLACKJACK PAYS 3 TO 2");
    printCenter(32, "DEALER STANDS ON 17");
  }
  drawHand(bjDealer, 12);
  drawHand(bjPlayer, 34);
  drawTotal(bjDealer, 13);
  drawTotal(bjPlayer, 35);
  if (bjPhase == BJ_PLAY) drawBar(BJ_OPTS, bjOptions(), bjSel);
  else if (bjPhase == BJ_BET) drawBetBar("BET", CHIPS[bj.betIdx], "DEAL");
  if (bannerVisible(bj)) drawBanner(16, bj.msg, bj.net);
}
