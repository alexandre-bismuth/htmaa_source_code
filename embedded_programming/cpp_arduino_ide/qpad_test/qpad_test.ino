// QPAD-XIAO soldering test of the six capacitive touch pads and SSD1306 OLED.
// Board: "Seeed XIAO RP2040"
// Libraries: Adafruit SSD1306 (+ dependencies)

// ---------- Imports ----------
#include <Wire.h>               // Driver that lets the processor talk to peripherals
#include <Adafruit_GFX.h>       // Library to create shapes on the screen
#include <Adafruit_SSD1306.h>   // Driver for the OLED mini-processor handling the screen
#include "hardware/gpio.h"      // Library for RP2040 I/O functions

// ---------- OLED ----------
#define SCREEN_W 128            // Screen dimensions
#define SCREEN_H 64
#define OLED_ADDR 0x3C          // Screen's ID (define by the manufacturer) 
Adafruit_SSD1306 display(SCREEN_W, SCREEN_H, &Wire, -1);

// ---------- Touch pads ----------  
const int N_PADS = 6;
// Map XIAO pin labels -> QPAD numbering (using the board's visible mapping)
const int padPins[N_PADS] = {D10, D9, D8, D1, D7, D0}; 
const char* padNames[N_PADS] = {"Q0", "Q1", "Q2", "Q3", "Q4", "Q5"};

// Timeout (loop count) for physical errors like shorts. Defined as a value well
// above (but within the same order of magnitude) as the maximum empirical reading.
const int T_MAX = 3000;       

// Number of readings that are averaged in a single update,
// tuned by looking at the empirical jitter and responsiveness.
const int SAMPLES = 8;        

// Array declarations
int baseline[N_PADS];         // Initial reading from calibration
int threshold[N_PADS];        // Reading above which we consider touched
int value[N_PADS];            // Current reading
bool touched[N_PADS];         // Currently touched?
bool confirmed[N_PADS];       // Pad touched and worked?
bool stuck[N_PADS];           // Reading pinned at max value? -> likely short

// ---------- LED ----------
// Pin I/O index on the RP2040 (manufacturer-defined)
const int LED_R = 17, LED_G = 16, LED_B = 25;
// LOW mode = low voltage -> pin goes to ground -> circuit is flowing -> light
// HIGH mode = high voltage -> no voltage difference -> no current -> no light

int measureOnce(int pin) {
  pinMode(pin, OUTPUT);         // Empty any leftover charge
  digitalWrite(pin, LOW);
  gpio_pull_up(pin);            // Connect resistor to 3.3V: slow-charge pad to time it properly
  delayMicroseconds(25);

  noInterrupts();               // Charge the pad capacitor
  gpio_set_dir(pin, GPIO_IN);
  int t = 0;                    // Time it to measure pressure
  while (!gpio_get(pin) && t < T_MAX) t++; 
  interrupts();

  pinMode(pin, OUTPUT);         // Discharge the pad again
  digitalWrite(pin, LOW);
  return t;
}

int measure(int pin) {          // Average measurement over samples
  long sum = 0;                 
  for (int s = 0; s < SAMPLES; s++) sum += measureOnce(pin);
  return sum / SAMPLES;
}

void calibrate() {
  display.clearDisplay();      // Warn the user we are about to
  display.setTextSize(1);      // calibrate the system
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(0, 20);    // Pixel position on the OLED screen
  display.println("Calibrating...");
  display.println("Don't touch the pads");
  display.display();
  delay(1000);

  // For each pad, make 32 measurements to set the "0" reading
  for (int i = 0; i < N_PADS; i++) {
    long sum = 0;
    for (int k = 0; k < 32; k++) sum += measure(padPins[i]);
    baseline[i] = sum / 32;
    threshold[i] = baseline[i] + max(10, baseline[i]);                 // Set threshold at 2x to account for jitter 
    stuck[i] = baseline[i] >= T_MAX - 1;          // Is the baseline stuck at the ceiling? likely short
    confirmed[i] = false;

  // Warn the user of possible shorts
  if (stuck[i]) Serial.printf("%s <-- STUCK: possible short\n", padNames[i]);
  }
}

void drawUI() {                         // Redraw the screen every loop
  display.clearDisplay();
  const int bw = 40, bh = 22;
  for (int i = 0; i < N_PADS; i++) {    // Draw each pad as rectangles with an offset
    int x = 2 + (i % 3) * 42;           // Pixel coords with offset
    int y = (i / 3) * 24;

    if (touched[i]) display.fillRect(x, y, bw, bh, SSD1306_WHITE);
    else            display.drawRect(x, y, bw, bh, SSD1306_WHITE);

    display.setTextColor(touched[i] ? SSD1306_BLACK : SSD1306_WHITE);
    display.setCursor(x + 3, y + 3);
    display.print(padNames[i]);
    display.setCursor(x + 3, y + 12);
    if (stuck[i]) display.print("ERR");
    else          display.print(value[i]);

    if (confirmed[i]) {                 // Add a circular  marker for the confirmed pads
      display.fillCircle(x + bw - 6, y + 6, 3, touched[i] ? SSD1306_BLACK : SSD1306_WHITE);
    }
  }

  int ok = 0;
  for (int i = 0; i < N_PADS; i++) if (confirmed[i]) ok++;

  display.setTextColor(SSD1306_WHITE); // User interface to show how many pads are confirmed working
  display.setCursor(2, 54);
  if (ok == N_PADS) display.print("ALL 6 PADS OK!");
  else {
    display.print("Touch each pad: ");
    display.print(ok);
    display.print("/6");
  }
  display.display();
}

void setup() {
  // Turn of LEDs
  pinMode(LED_R, OUTPUT); pinMode(LED_G, OUTPUT); pinMode(LED_B, OUTPUT);
  digitalWrite(LED_R, HIGH); digitalWrite(LED_G, HIGH); digitalWrite(LED_B, HIGH);

  // Setup USB
  Serial.begin(115200); // Standard baud (11.5 kb/s)
  while (!Serial && millis() < 2000) {}  // wait for OLED (2s timeout)

  Wire.begin();                                                           // Init I/O 
  if (!display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR)) {                  // Init OLED
    Serial.println("OLED init FAILED -> check solder joints / address");
    while (true) {                                                        // OLED failure: blink red
      digitalWrite(LED_R, LOW);  delay(150);
      digitalWrite(LED_R, HIGH); delay(150);
    }
  }
  Serial.println("OLED OK");
  calibrate();
}

void loop() {
  bool any = false;
  for (int i = 0; i < N_PADS; i++) {                       // Read each pad
    value[i] = measure(padPins[i]);
    touched[i] = !stuck[i] && value[i] > threshold[i];
    if (touched[i]) { confirmed[i] = true; any = true; }
  }

  digitalWrite(LED_G, any ? LOW : HIGH);                  // Pad touched: blink green
  drawUI();                                               // Draw the squares with current measurements
}
