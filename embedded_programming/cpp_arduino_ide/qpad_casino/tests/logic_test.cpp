// Host unit tests for rules.h (no board needed):
//   clang++ -std=c++17 -Wall -O2 logic_test.cpp -o /tmp/logic_test && /tmp/logic_test
#include <cstdio>
#include <cstring>
#include "../rules.h"
#include "vectors.h"

static int failures = 0, checks = 0;
#define CHECK(cond) do { checks++; if (!(cond)) { failures++; printf("FAIL line %d: %s\n", __LINE__, #cond); } } while (0)

// "AS" -> ace of spades. Suits: H D C S = 0 1 2 3.
static uint8_t card(const char* s) {
  return strchr("23456789TJQKA", s[0]) - "23456789TJQKA" + 13 * (strchr("HDCS", s[1]) - "HDCS");
}
static uint32_t hand(const char* a, const char* b, const char* c, const char* d, const char* e,
                     const char* f = nullptr, const char* g = nullptr) {
  uint8_t h[7] = {card(a), card(b), card(c), card(d), card(e)};
  int n = 5;
  if (f) h[n++] = card(f);
  if (g) h[n++] = card(g);
  return bestHand(h, n);
}
static int total(const char* a, const char* b, const char* c = nullptr) {
  uint8_t h[3] = {card(a), card(b)};
  int n = 2;
  if (c) h[n++] = card(c);
  return bjTotal(h, n);
}

int main() {
  // Cross-check against the JS evaluator: same RNG, same shuffle, same scores.
  rngState = VEC_SEED;
  Deck deck;
  for (const Vec& v : VECTORS) {
    deck.shuffle();
    CHECK(memcmp(deck.c, v.cards, 7) == 0);
    CHECK(bjTotal(v.cards, 3) == v.bj3);
    CHECK(evalCards(v.cards, 5) == v.eval5);
    CHECK(bestHand(v.cards, 7) == v.best7);
  }

  // Categories and names
  CHECK(!strcmp(handName(hand("AS", "KS", "QS", "JS", "TS", "2H", "3D")), "ROYAL"));
  CHECK(!strcmp(handName(hand("9S", "KS", "QS", "JS", "TS")), "STR FLUSH"));
  CHECK(!strcmp(handName(hand("9S", "9H", "9D", "9C", "TS")), "QUADS"));
  CHECK(!strcmp(handName(hand("9S", "9H", "9D", "4C", "4S")), "FULL HOUSE"));
  CHECK(!strcmp(handName(hand("2S", "7S", "9S", "JS", "KS")), "FLUSH"));
  CHECK(!strcmp(handName(hand("AS", "2H", "3D", "4C", "5S")), "STRAIGHT"));
  CHECK(!strcmp(handName(hand("9S", "9H", "9D", "4C", "5S")), "TRIPS"));
  CHECK(!strcmp(handName(hand("9S", "9H", "4D", "4C", "5S")), "TWO PAIR"));
  CHECK(!strcmp(handName(hand("9S", "9H", "4D", "3C", "5S")), "PAIR"));
  CHECK(!strcmp(handName(hand("9S", "JH", "4D", "3C", "5S")), "HIGH CARD"));

  // Ordering and tie-breaks
  CHECK(hand("AS", "2H", "3D", "4C", "5S") < hand("2S", "3H", "4D", "5C", "6S"));   // wheel is the lowest straight
  CHECK(hand("TS", "JH", "QD", "KC", "AS") > hand("9S", "TH", "JD", "QC", "KS"));
  CHECK(hand("2S", "7S", "9S", "JS", "KS") > hand("TS", "JH", "QD", "KC", "AS"));   // flush beats straight
  CHECK(hand("2S", "2H", "2D", "3C", "3S") > hand("AS", "7S", "9S", "JS", "KS"));   // full house beats flush
  CHECK(hand("KS", "KH", "4D", "4C", "5S") > hand("QS", "QH", "JD", "JC", "AS"));   // higher top pair
  CHECK(hand("KS", "KH", "4D", "4C", "6S") > hand("KD", "KC", "4H", "4S", "5S"));   // kicker
  CHECK(hand("AS", "AH", "9D", "3C", "2S") == hand("AD", "AC", "9H", "3S", "2D"));  // exact tie
  CHECK(hand("AS", "KS", "2H", "2D", "7C", "7H", "9S") == hand("AS", "7C", "7H", "2H", "2D"));   // best 5 of 7

  // Blackjack totals (soft aces)
  CHECK(total("AS", "6H") == 17);
  CHECK(total("AS", "6H", "TD") == 17);
  CHECK(total("AS", "AH") == 12);
  CHECK(total("AS", "AH", "9D") == 21);
  CHECK(total("TS", "TH", "5D") == 25);
  CHECK(total("KS", "QH") == 20);

  // Blackjack payouts (returned chips, stake included)
  const char* msg;
  CHECK(bjSettle(10, 21, 2, 21, 2, &msg) == 10 && !strcmp(msg, "PUSH"));
  CHECK(bjSettle(10, 21, 2, 20, 3, &msg) == 25 && !strcmp(msg, "BLACKJACK!"));
  CHECK(bjSettle(5, 21, 2, 18, 2, &msg) == 12);                                    // 3:2 rounds down
  CHECK(bjSettle(10, 21, 3, 21, 2, &msg) == 0 && !strcmp(msg, "DEALER BLACKJACK"));
  CHECK(bjSettle(10, 22, 3, 17, 2, &msg) == 0 && !strcmp(msg, "BUST"));
  CHECK(bjSettle(20, 18, 2, 23, 3, &msg) == 40 && !strcmp(msg, "DEALER BUSTS"));
  CHECK(bjSettle(10, 20, 2, 19, 2, &msg) == 20 && !strcmp(msg, "YOU WIN"));
  CHECK(bjSettle(10, 18, 2, 19, 2, &msg) == 0 && !strcmp(msg, "DEALER WINS"));
  CHECK(bjSettle(10, 19, 3, 19, 2, &msg) == 10 && !strcmp(msg, "PUSH"));

  // Ultimate Texas Hold'em payouts: ante 10 (+ blind 10), play 40
  uint32_t pair = hand("9S", "9H", "4D", "3C", "5S"), high = hand("9S", "JH", "4D", "3C", "5S");
  uint32_t flush = hand("2S", "7S", "9S", "JS", "KS"), straight = hand("AS", "2H", "3D", "4C", "5S");
  uint32_t royal = hand("AS", "KS", "QS", "JS", "TS"), twoPair = hand("9S", "9H", "4D", "4C", "5S");
  CHECK(uthSettle(10, 0, twoPair, pair, true, &msg) == 0 && !strcmp(msg, "FOLDED"));
  CHECK(uthSettle(10, 40, twoPair, pair, false, &msg) == 80 + 20 + 10 && !strcmp(msg, "YOU WIN"));   // blind pushes
  CHECK(uthSettle(10, 40, flush, pair, false, &msg) == 80 + 20 + 10 + 15);                          // blind 3:2
  CHECK(uthSettle(10, 40, straight, high, false, &msg) == 80 + 10 + 10 + 10 && !strcmp(msg, "DEALER NO PAIR"));
  CHECK(uthSettle(10, 40, royal, pair, false, &msg) == 80 + 20 + 10 + 5000);                        // 500:1
  CHECK(uthSettle(10, 40, pair, twoPair, false, &msg) == 0 && !strcmp(msg, "DEALER WINS"));
  CHECK(uthSettle(10, 40, hand("2S", "4H", "6D", "8C", "9S"), high, false, &msg) == 10);            // ante pushes
  CHECK(uthSettle(10, 40, pair, pair, false, &msg) == 60 && !strcmp(msg, "PUSH"));

  // Roulette
  const int REDS[] = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36};
  for (int n = 0, i = 0; n <= 36; n++) {
    bool red = i < 18 && REDS[i] == n;
    if (red) i++;
    CHECK(isRed(n) == red);
  }
  for (int b = 0; b < 9; b++) CHECK(!betWins(b, 0));          // zero loses every outside bet
  CHECK(betWins(9, 0) && betPays(9) == 35);
  CHECK(betWins(6, 12) && !betWins(6, 13) && betWins(7, 13) && betWins(8, 36));
  CHECK(betWins(3, 35) && betWins(2, 36) && betWins(4, 18) && betWins(5, 19));
  for (int i = 0; i < 37; i++) CHECK(wheelIndex(WHEEL[i]) == i);

  printf("%d/%d checks passed\n", checks - failures, checks);
  return failures != 0;
}
