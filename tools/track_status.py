#!/usr/bin/env python3
"""Log every vendor status packet with a timestamp (state-change tests)."""
import os, select, sys, time

fd = os.open("/dev/hidraw3", os.O_RDONLY | os.O_NONBLOCK)
duration = float(sys.argv[1]) if len(sys.argv) > 1 else 180.0
start = time.time()
while time.time() - start < duration:
    r, _, _ = select.select([fd], [], [], 0.2)
    if r:
        try:
            d = os.read(fd, 64)
        except OSError:
            d = b""
        if d:
            print(f"[{time.time()-start:7.2f}] len={len(d)} {d[:16].hex(' ')}", flush=True)
print("done", flush=True)
os.close(fd)
