// Pure game rules: no Arduino dependencies, so tests/logic_test.cpp can run them on a computer.
#pragma once
#include <stdint.h>

// ---------- RNG: xorshift32 (identical in every port, so a seed replays the same game) ----------
inline uint32_t rngState = 0x2545F491;
inline uint32_t rng() {
  uint32_t x = rngState;
  x ^= x << 13;
  x ^= x >> 17;
  x ^= x << 5;
  return rngState = x;
}
inline uint32_t rngBelow(uint32_t n) { return rng() % n; }

// ---------- Cards: 0..51, rank = card % 13 (0 = '2' .. 12 = 'A'), suit = card / 13 ----------
struct Deck {
  uint8_t c[52];
  uint8_t pos;
  void shuffle() {
    for (int i = 0; i < 52; i++) c[i] = i;
    for (int i = 51; i > 0; i--) {
      int j = rngBelow(i + 1);
      uint8_t t = c[i]; c[i] = c[j]; c[j] = t;
    }
    pos = 0;
  }
  uint8_t draw() { return c[pos++]; }
};

// ---------- Blackjack ----------
inline int bjTotal(const uint8_t* c, int n) {
  int sum = 0, aces = 0;
  for (int i = 0; i < n; i++) {
    int r = c[i] % 13;
    sum += r < 8 ? r + 2 : r < 12 ? 10 : 11;
    if (r == 12) aces++;
  }
  while (sum > 21 && aces) { sum -= 10; aces--; }
  return sum;
}

// Chips returned to the player (stake included) for a finished hand.
inline long bjSettle(long bet, int p, int pN, int d, int dN, const char** msg) {
  bool pBJ = p == 21 && pN == 2, dBJ = d == 21 && dN == 2;
  if (pBJ && dBJ) { *msg = "PUSH";             return bet; }
  if (pBJ)        { *msg = "BLACKJACK!";       return bet + bet * 3 / 2; }
  if (dBJ)        { *msg = "DEALER BLACKJACK"; return 0; }
  if (p > 21)     { *msg = "BUST";             return 0; }
  if (d > 21)     { *msg = "DEALER BUSTS";     return 2 * bet; }
  if (p > d)      { *msg = "YOU WIN";          return 2 * bet; }
  if (p < d)      { *msg = "DEALER WINS";      return 0; }
  *msg = "PUSH";
  return bet;
}

// ---------- Poker hands ----------
// Score of up to 5 cards: category << 20 | tie-break ranks. Higher is better.
inline uint32_t evalCards(const uint8_t* c, int n) {
  uint8_t cnt[13] = {0};
  for (int i = 0; i < n; i++) cnt[c[i] % 13]++;
  uint8_t g[5];                                   // ranks grouped by count, then by rank
  int ng = 0;
  for (int k = 4; k >= 1; k--)
    for (int r = 12; r >= 0; r--)
      if (cnt[r] == k) g[ng++] = r;
  bool flush = n == 5;
  for (int i = 1; i < n && flush; i++) flush = c[i] / 13 == c[0] / 13;
  int high = -1;                                  // straight's top card (5 for the wheel A-2-3-4-5)
  if (ng == 5) {
    if (g[0] - g[4] == 4) high = g[0];
    else if (g[0] == 12 && g[1] == 3) high = 3;
  }
  uint32_t cat;
  if (high >= 0 && flush)                         cat = 8;
  else if (cnt[g[0]] == 4)                        cat = 7;
  else if (cnt[g[0]] == 3 && ng > 1 && cnt[g[1]] >= 2) cat = 6;
  else if (flush)                                 cat = 5;
  else if (high >= 0)                             cat = 4;
  else if (cnt[g[0]] == 3)                        cat = 3;
  else if (cnt[g[0]] == 2 && ng > 1 && cnt[g[1]] == 2) cat = 2;
  else if (cnt[g[0]] == 2)                        cat = 1;
  else                                            cat = 0;
  uint32_t score = cat << 20;
  if (high >= 0) score |= (uint32_t)high << 16;
  else for (int i = 0; i < ng; i++) score |= (uint32_t)g[i] << (16 - 4 * i);
  return score;
}

// Best 5-card score out of n <= 7 cards.
inline uint32_t bestHand(const uint8_t* c, int n) {
  if (n <= 5) return evalCards(c, n);
  uint32_t best = 0;
  uint8_t pick[5];
  for (int m = 0; m < (1 << n); m++) {
    if (__builtin_popcount(m) != 5) continue;
    int k = 0;
    for (int i = 0; i < n; i++)
      if (m >> i & 1) pick[k++] = c[i];
    uint32_t s = evalCards(pick, 5);
    if (s > best) best = s;
  }
  return best;
}

inline bool isRoyal(uint32_t s) { return s >> 20 == 8 && (s >> 16 & 15) == 12; }

inline const char* handName(uint32_t s) {
  static const char* const NAMES[] = {"HIGH CARD", "PAIR", "TWO PAIR", "TRIPS", "STRAIGHT",
                                      "FLUSH", "FULL HOUSE", "QUADS", "STR FLUSH"};
  return isRoyal(s) ? "ROYAL" : NAMES[s >> 20];
}

// Ultimate Texas Hold'em: chips returned (stake included). Blind pays on a straight or better.
inline long uthSettle(long ante, long play, uint32_t p, uint32_t d, bool folded, const char** msg) {
  static const uint16_t BLIND_X2[] = {0, 0, 0, 0, 2, 3, 6, 20, 100, 1000};   // pays x/2 : 1 (straight) .. 500 (royal)
  bool open = d >> 20 >= 1;                                                   // dealer needs a pair
  if (folded) { *msg = "FOLDED"; return 0; }
  if (p > d) {
    int cat = isRoyal(p) ? 9 : p >> 20;
    *msg = open ? "YOU WIN" : "DEALER NO PAIR";
    return 2 * play + (open ? 2 * ante : ante) + ante + ante * BLIND_X2[cat] / 2;
  }
  if (p < d) { *msg = "DEALER WINS"; return open ? 0 : ante; }
  *msg = "PUSH";
  return 2 * ante + play;
}

// ---------- Roulette (European, single zero) ----------
inline constexpr uint8_t WHEEL[37] = {0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10,
                                      5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26};
inline constexpr int N_BETS = 9 + 37;             // 9 outside bets, then straight numbers 0..36

inline bool isRed(int n) {
  if (n == 0) return false;
  return (n <= 10 || (n >= 19 && n <= 28)) ? n % 2 == 1 : n % 2 == 0;
}
inline int wheelIndex(int n) {
  for (int i = 0; i < 37; i++) if (WHEEL[i] == n) return i;
  return 0;
}
inline int betPays(int b) { return b < 6 ? 1 : b < 9 ? 2 : 35; }
inline bool betWins(int b, int n) {
  switch (b) {
    case 0: return isRed(n);
    case 1: return n > 0 && !isRed(n);
    case 2: return n > 0 && n % 2 == 0;
    case 3: return n % 2 == 1;
    case 4: return n >= 1 && n <= 18;
    case 5: return n >= 19;
    case 6: case 7: case 8: return n > 0 && (n - 1) / 12 == b - 6;
    default: return n == b - 9;
  }
}
