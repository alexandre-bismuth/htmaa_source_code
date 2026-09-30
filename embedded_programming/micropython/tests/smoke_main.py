# Runs a port's real main.py on the host with stubbed hardware:
#   micropython smoke_main.py <port>          -> 120 frames of the normal game loop
#   echo g | micropython smoke_main.py <port> bench   -> the full benchmark boot path
import sys
import os

PORT = sys.argv[1]
BENCH = len(sys.argv) > 2
sys.path.insert(0, os.getcwd() + "/stubs")
PORT_DIR = PORT if PORT.startswith("/") else os.getcwd() + "/../" + PORT
sys.path.insert(0, PORT_DIR)
os.chdir(PORT_DIR)
import ssd1306

shown = [0]


def hook(buf):
    shown[0] += 1
    if not BENCH and shown[0] > 120:
        raise SystemExit


ssd1306.on_show.append(hook)
if BENCH:
    import bench
    original = bench.progress

    def progress(casino, what):
        original(casino, what)
        if what == "done":
            raise SystemExit

    bench.progress = progress

source = open("main.py").read()
if BENCH:
    source = source.replace("BENCHMARK = False", "BENCHMARK = True")
try:
    exec(source, {"__name__": "__main__"})
except SystemExit:
    print("SMOKE OK: %d frames shown" % shown[0])
