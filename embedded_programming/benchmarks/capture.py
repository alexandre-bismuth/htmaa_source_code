#!/usr/bin/env python3
"""Saves a QPAD Casino benchmark run from the XIAO's USB serial port to files.

    python3 capture.py --lang cpp            # or micropython_naive, micropython, rust

Flash the project with its BENCHMARK flag on, plug the board in, then run this.
Writes results/<lang>.jsonl (one JSON object per measurement) and results/<lang>_raw.log.
Standard library only (no pyserial): USB CDC ignores the baud rate.
"""
import argparse, fcntl, functools, glob, json, os, select, struct, sys, termios, time, tty

print = functools.partial(print, flush=True)

HERE = os.path.dirname(os.path.abspath(__file__))


def open_port(path):
    fd = os.open(path, os.O_RDWR | os.O_NOCTTY)
    tty.setraw(fd)
    try:                                              # raise DTR: the C++ build waits for it
        fcntl.ioctl(fd, termios.TIOCMBIS, struct.pack("I", termios.TIOCM_DTR))
    except (AttributeError, OSError):
        pass
    return fd


def save(path, meta, rows, begin, done):
    head = {"sec": "meta", "name": "run", **meta, "captured": time.strftime("%Y-%m-%d %H:%M:%S"),
            "run_seconds": round(time.time() - begin, 1), "complete": done}
    with open(path, "w") as f:
        f.write(json.dumps(head) + "\n")
        for r in rows:
            f.write(json.dumps(r) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", required=True, choices=["cpp", "micropython_naive", "micropython", "rust"])
    ap.add_argument("--port", help="default: the only /dev/cu.usbmodem* device")
    ap.add_argument("--timeout", type=float, default=3600, help="seconds to wait for BENCH_END")
    args = ap.parse_args()

    port = args.port
    if not port:
        ports = sorted(glob.glob("/dev/cu.usbmodem*"))
        if len(ports) != 1:
            sys.exit(f"Found {ports or 'no USB serial ports'}; pass --port")
        port = ports[0]
    out_dir = os.path.join(HERE, "results")
    os.makedirs(out_dir, exist_ok=True)
    raw_path = os.path.join(out_dir, f"{args.lang}_raw.log")
    json_path = os.path.join(out_dir, f"{args.lang}.jsonl")

    fd = open_port(port)
    os.write(fd, b"go\r\n")                           # MicroPython builds wait for any input
    print(f"Listening on {port} ... (reset the board if nothing happens)")
    buf, rows, meta, started = b"", [], None, False
    deadline = time.time() + args.timeout
    with open(raw_path, "w", buffering=1) as raw:                 # line-buffered: progress is visible live
        while time.time() < deadline:
            ready, _, _ = select.select([fd], [], [], 1.0)
            if not ready:
                continue
            buf += os.read(fd, 4096)
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                text = line.decode(errors="replace").strip()
                raw.write(text + "\n")
                if text.startswith("BENCH_BEGIN"):
                    meta, rows, started = json.loads(text.split(" ", 1)[1]), [], True
                    begin = time.time()
                    print(f"started: {meta}")
                elif text.startswith("BENCH ") and started:
                    try:
                        row = json.loads(text[6:])
                    except json.JSONDecodeError:
                        print(f"  skipped malformed line (kept in the raw log): {text[:80]}")
                        continue
                    rows.append(row)
                    save(json_path, meta, rows, begin, done=False)     # saved as it arrives: an interrupted run keeps its results
                    print(f"  {row['sec']:>12} {row['name']}")
                elif text == "BENCH_END" and started:
                    save(json_path, meta, rows, begin, done=True)
                    print(f"Saved {len(rows)} results to {json_path}")
                    return
                elif text:
                    print(f"  [board] {text}")
    sys.exit(f"Timed out; partial output is in {raw_path}")


if __name__ == "__main__":
    main()
