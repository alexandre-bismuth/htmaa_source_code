// Ultimate Texas Hold'em: Ante + equal Blind; bet 3x/4x pre-flop, 2x on the flop, 1x or fold on the river.

enum UthPhase : uint8_t { UTH_BET, UTH_PRE, UTH_FLOP, UTH_RIVER };
const char* const UTH_OPTS[4][3] = {{}, {"CHECK", "BET 3x", "BET 4x"}, {"CHECK", "BET 2x"}, {"FOLD", "BET 1x"}};
const uint8_t UTH_N_OPTS[4] = {0, 3, 2, 2};
const uint8_t UTH_MULT[4][3] = {{}, {0, 3, 4}, {0, 2}, {0, 1}};   // play bet per option (0 = check/fold)

Round uth;
UthPhase uthPhase;
Hand uthPlayer, uthDealer, uthBoard;
long uthAnte, uthPlay, uthStake;
int uthSel;

void uthReset() { uth = Round(); uthEnter(); uthAnte = uthPlay = uthStake = 0; }
void uthEnter() { uthPhase = UTH_BET; uthPlayer.n = uthDealer.n = uthBoard.n = 0; uth.banner = false; }

void uthDeal() {
  uint32_t t = now();
  uthAnte = CHIPS[uth.betIdx];
  uthPlay = 0;
  uthStake = 2 * uthAnte;
  bank -= uthStake;
  deck.shuffle();
  uthPlayer.n = uthDealer.n = uthBoard.n = 0;
  uthPlayer.add(deck.draw(), t, t);
  uthPlayer.add(deck.draw(), t + 300, t + 300);
  uthDealer.add(deck.draw(), t + 150, 0);
  uthDealer.add(deck.draw(), t + 450, 0);
  for (int i = 0; i < 5; i++) uthBoard.add(deck.draw(), t + 650 + i * 90, 0);
  uth.busyUntil = t + 650 + 4 * 90 + SLIDE_MS;
  uthPhase = UTH_PRE;
  uthSel = 0;
}

// Turns board cards [from, to) face up one after another; returns when the last one lands.
uint32_t uthFlip(int from, int to, uint32_t t) {
  for (int i = from; i < to; i++)
    if (!uthBoard.s[i].showAt) { uthBoard.s[i].showAt = t; t += 180; }
  return t;
}

uint32_t score7(const Hand& hole) {
  uint8_t c[7];
  allCards(hole, c);
  allCards(uthBoard, c + 2);
  return bestHand(c, 7);
}

void uthShowdown(uint32_t t, bool folded) {
  t = uthFlip(0, 5, t) + 250;
  uthDealer.s[0].showAt = t;
  uthDealer.s[1].showAt = t + 180;
  t += 180 + 500;
  const char* msg;
  long ret = uthSettle(uthAnte, uthPlay, score7(uthPlayer), score7(uthDealer), folded, &msg);
  showResult(uth, msg, ret, ret - uthStake, t);
  uthPhase = UTH_BET;
}

void uthUpdate(uint8_t ev) {
  uint32_t t = now();
  payWhenShown(uth);
  if (t < uth.busyUntil) return;

  if (uthPhase == UTH_BET) {
    if (ev) uth.banner = false;
    betInput(uth, ev, 6);
    if (has(ev, BACK)) { screen = MENU; return; }
    if (has(ev, OK) && canBet(uth, 6)) uthDeal();
    return;
  }
  if (has(ev, LEFT) && uthSel > 0) uthSel--;
  if (has(ev, RIGHT) && uthSel < UTH_N_OPTS[uthPhase] - 1) uthSel++;
  if (!has(ev, OK)) return;
  int mult = UTH_MULT[uthPhase][uthSel];
  if (mult) {
    uthPlay = uthAnte * mult;
    bank -= uthPlay;
    uthStake += uthPlay;
    uthShowdown(t, false);
  } else if (uthPhase == UTH_RIVER) {
    uthShowdown(t, true);                                 // fold
  } else {
    uth.busyUntil = uthFlip(uthPhase == UTH_PRE ? 0 : 3, uthPhase == UTH_PRE ? 3 : 5, t);
    uthPhase = uthPhase == UTH_PRE ? UTH_FLOP : UTH_RIVER;
    uthSel = 0;
  }
}

// Name of the best hand among the face-up cards of a hole pair plus the board.
const char* liveHandName(const Hand& hole) {
  uint8_t c[7];
  int n = upCards(hole, c);
  if (n < 2) return nullptr;
  n += upCards(uthBoard, c + n);
  return handName(bestHand(c, n));
}

void uthDraw() {
  char b[24];
  drawHeader("HOLD'EM");
  if (!uthPlayer.n) {
    printCenter(18, "DEALER NEEDS A PAIR");
    printCenter(30, "BLIND PAYS STRAIGHT+");
  }
  for (int i = 0; i < uthBoard.n; i++) drawSlot(32 + i * 13, 9, uthBoard.s[i]);
  for (int i = 0; i < uthPlayer.n; i++) drawSlot(i * 13, 28, uthPlayer.s[i]);
  for (int i = 0; i < uthDealer.n; i++) drawSlot(104 + i * 13, 28, uthDealer.s[i]);
  if (uthPlayer.n) {
    sprintf(b, "A%ld B%ld", uthAnte, uthAnte);
    printCenter(29, b);
    if (uthPlay) sprintf(b, "PLAY %ld", uthPlay);
    else strcpy(b, "PLAY -");
    printCenter(38, b);
    const char* mine = liveHandName(uthPlayer);
    const char* theirs = liveHandName(uthDealer);
    if (mine) printAt(0, 46, mine);
    if (theirs) printRight(127, 46, theirs);
  }
  if (uthPhase == UTH_BET) drawBetBar("ANTE", CHIPS[uth.betIdx], "DEAL");
  else drawBar(UTH_OPTS[uthPhase], UTH_N_OPTS[uthPhase], uthSel);
  if (bannerVisible(uth)) drawBanner(14, uth.msg, uth.net);
}
