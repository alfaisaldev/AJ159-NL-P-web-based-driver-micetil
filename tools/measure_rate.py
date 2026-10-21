#!/usr/bin/env python3
"""Measure the mouse's actual USB polling rate.

The mouse sends one interrupt-IN report per poll, so the inter-arrival time
of the report stream is the polling rate. This is the ground truth for the
"Report Rate" setting - no driver needed.

Usage: python3 tools/measure_rate.py [seconds] [node]
"""
import os
import select
import sys
import time
from collections import deque

duration = float(sys.argv[1]) if len(sys.argv) > 1 else 2.0
node = sys.argv[2] if len(sys.argv) > 2 else "/dev/hidraw4"

fd = os.open(node, os.O_RDONLY | os.O_NONBLOCK)
stamps = deque()
end = time.time() + duration
while time.time() < end:
    r, _, _ = select.select([fd], [], [], 0.05)
    if r:
        try:
            os.read(fd, 64)
        except OSError:
            continue
        stamps.append(time.perf_counter())

os.close(fd)

if len(stamps) < 10:
    print(f"{node}: only {len(stamps)} reports in {duration}s - mouse idle or asleep")
    raise SystemExit

# interval statistics over the middle 80% (skip start/stop transients)
stamps = list(stamps)
gaps = sorted(b - a for a, b in zip(stamps, stamps[1:]))
n = len(gaps)
core = gaps[int(n * 0.1) : int(n * 0.9)]
avg = sum(core) / len(core)
median = core[len(core) // 2]

print(f"{node}: {len(stamps)} reports in {duration:.1f}s")
print(f"  fastest (p5)  {core[max(0, len(core) // 20)] * 1e6:8.1f} us  ->  {1 / core[max(0, len(core) // 20)]:8.1f} Hz   <- the polling rate")
print(f"  median        {median * 1e6:8.1f} us  ->  {1 / median:8.1f} Hz")
print(f"  mean          {avg * 1e6:8.1f} us  ->  {1 / avg:8.1f} Hz  (lower: the mouse idles between moves)")
print(f"  min {core[0] * 1e6:.0f} us   max {core[-1] * 1e6:.0f} us")
