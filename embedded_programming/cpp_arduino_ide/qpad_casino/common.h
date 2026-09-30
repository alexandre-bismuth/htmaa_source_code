// Shared types, constants and cross-tab prototypes.
#pragma once
#include <Arduino.h>
#include <Adafruit_SSD1306.h>
#include "rules.h"

enum Btn : uint8_t { UP, DOWN, LEFT, RIGHT, OK, BACK, N_BTNS };
enum Screen : uint8_t { MENU, ROULETTE, BLACKJACK, POKER };
enum Led : uint8_t { LED_OFF, LED_GREEN, LED_RED, LED_BLUE };

inline bool has(uint8_t ev, Btn b) { return ev >> b & 1; }

const uint8_t BTN_PIN[N_BTNS] = {D0, D8, D1, D7, D9, D10};         // UP DOWN LEFT RIGHT OK BACK
const char* const BTN_PAD[N_BTNS] = {"Q5", "Q2", "Q3", "Q4", "Q1", "Q0"};

const uint32_t FRAME_MS = 33;                     // 30 fps
const long CHIPS[] = {5, 10, 25, 50, 100, 250, 500, 1000};
const int N_CHIPS = 8;
const int CW = 11, CH = 17;                       // card size in pixels
const uint32_t SLIDE_MS = 160, FLIP_MS = 90;

// A card on the table: slides in at dealAt, face up from showAt (0 = face down).
struct Slot { uint8_t card; uint32_t dealAt, showAt; };
struct Hand {
  Slot s[12];
  uint8_t n = 0;
  void add(uint8_t card, uint32_t dealAt, uint32_t showAt) { s[n++] = {card, dealAt, showAt}; }
};

// Bet size, result banner and pending payout of one game.
struct Round {
  uint8_t betIdx = 1;
  uint32_t busyUntil = 0, resultAt = 0;
  bool banner = false;
  long payout = -1, net = 0;                      // payout -1 = nothing pending
  char msg[20] = "";
};

extern Adafruit_SSD1306 display;
extern long bank;
extern Screen screen;
extern Deck deck;
extern uint32_t clockMs, bootFrameMs;
uint32_t now();

// input
void drawSplash(int progress, int total);
void calibrate();
int measureOnce(int pin);
void scanPads();
uint8_t readButtons();

// ui
int textW(const char* s, int size = 1);
void printAt(int x, int y, const char* s, int size = 1, uint16_t c = WHITE);
void printCenter(int y, const char* s, int size = 1, uint16_t c = WHITE, int cx = 64);
void printRight(int x, int y, const char* s, int size = 1, uint16_t c = WHITE);
void drawHeader(const char* title);
void drawBar(const char* const* items, int n, int sel);
void drawBetBar(const char* label, long amount, const char* action);
void drawBanner(int y, const char* line1, long net);
int easeOut(uint32_t k, uint32_t total);
int icos(int r, int a);
int isin(int r, int a);
void drawCard(int x, int y, uint8_t card);
void drawCardBack(int x, int y);
bool isUp(const Slot& s);
void drawSlot(int x, int y, const Slot& s);
void drawHand(const Hand& h, int y, int maxW = 100);
int allCards(const Hand& h, uint8_t* out);
int upCards(const Hand& h, uint8_t* out);
void setLed(Led c);
void flashLed(Led c);
void ledUpdate();
void showResult(Round& g, const char* msg, long payout, long net, uint32_t at);
bool bannerVisible(const Round& g);
void payWhenShown(Round& g);
void betInput(Round& g, uint8_t ev, int mult);
bool canBet(Round& g, int mult);

// screens
void menuReset();   void menuUpdate(uint8_t ev);  void menuDraw();
void rouReset();    void rouEnter();  void rouUpdate(uint8_t ev);  void rouDraw();
void bjReset();     void bjEnter();   void bjUpdate(uint8_t ev);   void bjDraw();
void uthReset();    void uthEnter();  void uthUpdate(uint8_t ev);  void uthDraw();
void update(uint8_t ev);
void draw();
void runBenchmark();
