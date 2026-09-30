// Host harness (appended to the concatenated sketch by run.sh): runs the benchmark's logic
// checksums and scripted playthrough on this computer and saves frames as PNG contact sheets.
#include <chrono>
#include <string>
#include <vector>
#include <zlib.h>

HostSerial Serial;
HostRP2040 rp2040;
TwoWire Wire;
extern "C" { char __StackBottom, __StackTop, __end__, __data_start__, __data_end__, __bss_start__, __bss_end__, __flash_binary_end; }

static const auto T0 = std::chrono::steady_clock::now();
uint32_t micros() {
  return std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now() - T0).count();
}
uint32_t millis() { return micros() / 1000; }

static std::vector<std::vector<uint8_t>> frames;
static bool capture = false;
void Adafruit_SSD1306::display() {
  if (capture) frames.emplace_back(buffer, buffer + 1024);
}

static void chunk(FILE* f, const char* type, const std::vector<uint8_t>& data) {
  uint8_t len[4] = {uint8_t(data.size() >> 24), uint8_t(data.size() >> 16), uint8_t(data.size() >> 8), uint8_t(data.size())};
  fwrite(len, 1, 4, f);
  std::vector<uint8_t> td(type, type + 4);
  td.insert(td.end(), data.begin(), data.end());
  fwrite(td.data(), 1, td.size(), f);
  uLong c = crc32(0, td.data(), td.size());
  uint8_t cb[4] = {uint8_t(c >> 24), uint8_t(c >> 16), uint8_t(c >> 8), uint8_t(c)};
  fwrite(cb, 1, 4, f);
}

// Grid of frames, each pixel drawn as an S x S dot, frame number burned in the gap is omitted for simplicity.
static void sheet(const std::string& path, const std::vector<int>& idx, int cols, int S) {
  int rows = (idx.size() + cols - 1) / cols, pad = 6;
  int w = cols * (128 * S + pad) + pad, h = rows * (64 * S + pad) + pad;
  std::vector<uint8_t> raw((w * 3 + 1) * h, 0);
  for (int y = 0; y < h; y++)
    for (int x = 0; x < w; x++) { uint8_t* p = &raw[y * (w * 3 + 1) + 1 + x * 3]; p[0] = 60; p[1] = 70; p[2] = 90; }
  for (size_t i = 0; i < idx.size(); i++) {
    const std::vector<uint8_t>& fb = frames[idx[i]];
    int ox = pad + (i % cols) * (128 * S + pad), oy = pad + (i / cols) * (64 * S + pad);
    for (int y = 0; y < 64 * S; y++)
      for (int x = 0; x < 128 * S; x++) {
        int px = x / S, py = y / S;
        bool on = fb[px + (py / 8) * 128] >> (py & 7) & 1, gap = x % S == S - 1 || y % S == S - 1;
        uint8_t* p = &raw[(oy + y) * (w * 3 + 1) + 1 + (ox + x) * 3];
        uint8_t v = on ? (gap ? 150 : 235) : 8;
        p[0] = v; p[1] = on ? v : 8; p[2] = on ? 255 : 12;
      }
  }
  std::vector<uint8_t> z(compressBound(raw.size()));
  uLongf zn = z.size();
  compress2(z.data(), &zn, raw.data(), raw.size(), 6);
  z.resize(zn);
  std::vector<uint8_t> ihdr = {uint8_t(w >> 24), uint8_t(w >> 16), uint8_t(w >> 8), uint8_t(w),
                               uint8_t(h >> 24), uint8_t(h >> 16), uint8_t(h >> 8), uint8_t(h), 8, 2, 0, 0, 0};
  FILE* f = fopen(path.c_str(), "wb");
  const uint8_t sig[8] = {137, 80, 78, 71, 13, 10, 26, 10};
  fwrite(sig, 1, 8, f);
  chunk(f, "IHDR", ihdr);
  chunk(f, "IDAT", z);
  chunk(f, "IEND", {});
  fclose(f);
}

int main(int argc, char** argv) {
  std::string out = argc > 1 ? argv[1] : ".";
  int every = argc > 2 ? atoi(argv[2]) : 48;
  display.setTextWrap(false);
  display.cp437(true);
  calibrate();
  Bench::logic();
  Bench::gfx();
  capture = true;
  Bench::playthrough();
  capture = false;
  FILE* raw = fopen((out + "/frames.bin").c_str(), "wb");      // every frame, 1024 bytes each (SSD1306 layout)
  for (auto& f : frames) fwrite(f.data(), 1, 1024, raw);
  fclose(raw);
  std::vector<int> idx;
  for (size_t i = every; i < frames.size(); i += every) idx.push_back(i);
  for (size_t s = 0; s * 8 < idx.size(); s++) {
    std::vector<int> part(idx.begin() + s * 8, idx.begin() + std::min(idx.size(), s * 8 + 8));
    sheet(out + "/frames_" + std::to_string(s) + ".png", part, 2, 3);
  }
  printf("captured %zu frames, wrote %zu sheets to %s\n", frames.size(), (idx.size() + 7) / 8, out.c_str());
}
