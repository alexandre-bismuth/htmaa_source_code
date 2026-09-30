// Capacitive pads -> button events (RC timing, same method as qpad_test).

const int T_MAX = 3000;                                            // loop-count ceiling
const int SAMPLES = 8;
const uint32_t REPEAT_DELAY = 400, REPEAT_RATE = 110;              // hold-to-repeat on the 4 left pads

int baseline[N_BTNS], threshold[N_BTNS], value[N_BTNS];
bool stuck[N_BTNS], down[N_BTNS];

// Runs from RAM so flash cache misses can't add jitter to the count.
int __not_in_flash_func(measureOnce)(int pin) {
  pinMode(pin, OUTPUT);             // empty the pad
  digitalWrite(pin, LOW);
  gpio_pull_up(pin);                // connect resistor to 3.3V: slow-charge pad to time it properly
  delayMicroseconds(25);
  noInterrupts();
  gpio_set_dir(pin, GPIO_IN);
  int t = 0;                        // a finger adds capacitance -> longer charge
  while (!gpio_get(pin) && t < T_MAX) t++;
  interrupts();
  pinMode(pin, OUTPUT);             // discharge again
  digitalWrite(pin, LOW);
  return t;
}

int measure(int pin) {
  long sum = 0;
  for (int s = 0; s < SAMPLES; s++) sum += measureOnce(pin);
  return sum / SAMPLES;
}

void drawSplash(int progress, int total) {
  display.clearDisplay();
  printCenter(4, "\x06 \x03 \x05 \x04");
  printCenter(15, "CASINO", 2);
  printCenter(35, "DON'T TOUCH THE PADS");
  display.drawRect(24, 48, 80, 6, WHITE);
  display.fillRect(26, 50, 76 * progress / total, 2, WHITE);
  display.display();
}

void calibrate() {
  delay(800);                       // let hands leave the board
  for (int b = 0; b < N_BTNS; b++) {
    long sum = 0;
    for (int k = 0; k < 32; k++) sum += measure(BTN_PIN[b]);
    baseline[b] = sum / 32;
    threshold[b] = baseline[b] + max(10, baseline[b]);
    stuck[b] = baseline[b] >= T_MAX - 1;
    if (stuck[b]) Serial.printf("%s stuck at max: possible short to GND / solder bridge\n", BTN_PAD[b]);
    drawSplash(b + 1, N_BTNS);
  }
}

// Hysteresis: press above threshold, release below the midpoint to baseline.
void scanPads() {
  for (int b = 0; b < N_BTNS; b++) {
    value[b] = measure(BTN_PIN[b]);
    int off = (baseline[b] + threshold[b]) / 2;
    down[b] = !stuck[b] && value[b] > (down[b] ? off : threshold[b]);
  }
}

// Bitmask of new presses, with auto-repeat on the navigation pads.
uint8_t readButtons() {
  static bool wasDown[N_BTNS];
  static uint32_t downAt[N_BTNS], repeatAt[N_BTNS];
  scanPads();
  uint32_t t = now();
  uint8_t ev = 0;
  for (int b = 0; b < N_BTNS; b++) {
    if (down[b] && !wasDown[b]) {
      ev |= 1 << b;
      downAt[b] = repeatAt[b] = t;
    } else if (down[b] && b <= RIGHT && t - downAt[b] > REPEAT_DELAY && t - repeatAt[b] > REPEAT_RATE) {
      ev |= 1 << b;
      repeatAt[b] = t;
    }
    wasDown[b] = down[b];
  }
  return ev;
}
