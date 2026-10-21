#!/usr/bin/env python3
"""Log every input report from both AJAZZ mouse interfaces, with report ids.

Usage: python3 tools/watch_inputs.py [seconds]
"""
import os
import select
import sys
import time

NODES = ["/dev/hidraw4", "/dev/hidraw5"]
duration = float(sys.argv[1]) if len(sys.argv) > 1 else 30.0

fds = {}
for n in NODES:
    try:
        fd = os.open(n, os.O_RDONLY | os.O_NONBLOCK)
        fds[fd] = n
    except OSError as exc:
        print(n, "open failed:", exc)

start = time.time()
while time.time() - start < duration:
    ready, _, _ = select.select(list(fds), [], [], 0.3)
    for fd in ready:
        try:
            data = os.read(fd, 128)
        except (BlockingIOError, OSError):
            continue
        if data:
            print(f"[{time.time()-start:6.2f}] {fds[fd]} id={data[0]:#04x} len={len(data)} {data[:16].hex(' ')}", flush=True)
os.close  # noqa
for fd in fds:
    os.close(fd)
