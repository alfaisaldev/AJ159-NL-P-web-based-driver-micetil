#!/usr/bin/env python3
"""Monitor interrupt-IN reports on both AJAZZ hidraw nodes."""
import os, select, sys, time

nodes = sys.argv[1:] or ["/dev/hidraw2", "/dev/hidraw3"]
fds = {}
for n in nodes:
    try:
        fd = os.open(n, os.O_RDONLY | os.O_NONBLOCK)
        fds[fd] = n
    except OSError as e:
        print(n, "open failed:", e)

end = time.time() + 30
counts = {}
while time.time() < end:
    r, _, _ = select.select(list(fds), [], [], 0.2)
    for fd in r:
        try:
            data = os.read(fd, 64)
        except (BlockingIOError, OSError):
            continue
        if data:
            key = (fds[fd], data.hex())
            counts[key] = counts.get(key, 0) + 1
            print(f"{fds[fd]}  {data.hex(' ')}")
if not counts:
    print("no input reports received in 30s")
else:
    print("\n-- summary --")
    for (node, hexs), n in counts.items():
        print(f"  {node} x{n}: {hexs}")
