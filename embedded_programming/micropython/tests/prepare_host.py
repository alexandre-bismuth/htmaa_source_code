#!/usr/bin/env python3
"""Copies a port to a host-runnable folder: drops @micropython.native/viper decorators (the macOS unix
port can't emit ARM code) and imports plain-Python stand-ins for ptr8/ptr16/ptr32/uint.
    python3 prepare_host.py ../qpad_casino /tmp/qpad_casino_host"""
import os, re, shutil, sys

src, dst = sys.argv[1], sys.argv[2]
shutil.rmtree(dst, ignore_errors=True)
os.makedirs(dst)
for name in os.listdir(src):
    if not name.endswith(".py"):
        continue
    code = open(os.path.join(src, name)).read()
    code = re.sub(r"^(\s*)@micropython\.(native|viper)\s*$", r"\1", code, flags=re.M)
    if "micropython.viper" in open(os.path.join(src, name)).read():
        code = "from viper_shim import ptr8, ptr16, ptr32, uint\n" + code
    open(os.path.join(dst, name), "w").write(code)
