#!/usr/bin/env python3
"""Compares two frames.bin dumps of the scripted playthrough (1024 bytes per frame, SSD1306 layout).

    python3 compare_frames.py reference/frames.bin port/frames.bin [diff.png]

Prints how many frames are identical, the ranges that differ and by how many pixels, and optionally
writes a PNG with up to 12 differing frames: reference | port | differing pixels.
"""
import struct, sys, zlib


def frames(path):
    data = open(path, "rb").read()
    return [data[i:i + 1024] for i in range(0, len(data), 1024)]


def pixel(fb, x, y):
    return fb[x + (y // 8) * 128] >> (y & 7) & 1


def png(path, rows, scale=2):
    pad, w1, h1 = 4, 128 * scale, 64 * scale
    width, height = 3 * (w1 + pad) + pad, len(rows) * (h1 + pad) + pad
    img = bytearray([40, 44, 60] * (width * height))
    for r, (a, b) in enumerate(rows):
        for col, fb in enumerate((a, b, None)):
            ox, oy = pad + col * (w1 + pad), pad + r * (h1 + pad)
            for y in range(64):
                for x in range(128):
                    if fb is None:
                        on = pixel(a, x, y) != pixel(b, x, y)
                        color = (255, 80, 80) if on else (10, 10, 14)
                    else:
                        color = (225, 240, 255) if pixel(fb, x, y) else (10, 10, 14)
                    for dy in range(scale):
                        i = ((oy + y * scale + dy) * width + ox + x * scale) * 3
                        img[i:i + 3 * scale] = bytes(color) * scale
    raw = b"".join(b"\0" + bytes(img[y * width * 3:(y + 1) * width * 3]) for y in range(height))

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def main():
    ref, port = frames(sys.argv[1]), frames(sys.argv[2])
    if len(ref) != len(port):
        print(f"frame count differs: {len(ref)} vs {len(port)}")
    diffs = []
    for i, (a, b) in enumerate(zip(ref, port)):
        if a != b:
            diffs.append((i, sum(bin(x ^ y).count("1") for x, y in zip(a, b))))
    print(f"{len(ref) - len(diffs)}/{len(ref)} frames identical")
    ranges, start = [], None
    for k, (i, n) in enumerate(diffs):
        if start is None:
            start, worst = i, n
        worst = max(worst, n)
        if k + 1 == len(diffs) or diffs[k + 1][0] != i + 1:
            ranges.append((start, i, worst))
            start = None
    for a, b, worst in ranges:
        print(f"  frames {a}-{b}: up to {worst} pixels differ")
    if len(sys.argv) > 3 and diffs:
        picks = [diffs[int(k * (len(diffs) - 1) / 11)][0] for k in range(min(12, len(diffs)))]
        png(sys.argv[3], [(ref[i], port[i]) for i in sorted(set(picks))])
        print(f"wrote {sys.argv[3]}")


if __name__ == "__main__":
    main()
