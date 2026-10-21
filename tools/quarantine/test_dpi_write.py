#!/usr/bin/env python3
"""Decisive test of the host->mouse write path using the mouse's own frames.

Idea: the mouse pushes a DPI frame whenever its DPI stage changes.  If we
write that exact frame back to the mouse, a working write path should make
the mouse re-push its DPI state.  If that works, writing a *modified* value
should make the mouse push the new value -> we have DPI control.

Phases:
  1. wait for the mouse's own DPI frame (press the DPI button!)
  2. write it back verbatim, watch for a re-push
  3. write the same frame with a different DPI value, watch for a re-push
  4. restore the original value

Usage: python3 tools/test_dpi_write.py [node]
"""
import fcntl
import os
import select
import sys
import time

NODE = sys.argv[1] if len(sys.argv) > 1 else "/dev/hidraw5"
SIZE = 63
TEST_DPI = 2000


def ioc(direction, typ, nr, size):
    return (direction << 30) | ((size & 0xFFFF) << 16) | ((typ & 0xFF) << 8) | (nr & 0xFF)


SOUTPUT = lambda n: ioc(3, ord("H"), 0x0B, n)

fd = os.open(NODE, os.O_RDWR)
os.set_blocking(fd, False)


def write_body(body):
    buf = bytearray([6]) + bytearray(body).ljust(SIZE - 1, b"\x00")
    fcntl.ioctl(fd, SOUTPUT(len(buf)), buf, True)


def drain(seconds):
    out, end = [], time.time() + seconds
    while time.time() < end:
        r, _, _ = select.select([fd], [], [], 0.03)
        if not r:
            continue
        try:
            d = os.read(fd, 128)
        except (BlockingIOError, OSError):
            continue
        if d:
            out.append(d)
    return out


def is_dpi(frame):
    return len(frame) > 7 and frame[1] == 0xFA and frame[5] == 0x02


def describe(frame):
    if len(frame) > 7 and frame[1] == 0xFA:
        tag = frame[5]
        if tag == 0x02:
            return f"DPI stage={frame[6]} value={frame[7] | (frame[8] << 8) if len(frame) > 8 else 0}"
        return f"push tag={tag:#04x} {frame[6:9].hex(' ')}"
    return "REPLY " + frame[:8].hex(" ")


print(f"== DPI write test on {NODE} ==")
print("\n[1] waiting 30 s for the mouse's own DPI frame - PRESS THE DPI BUTTON NOW")
frame = None
end = time.time() + 30
while time.time() < end:
    for f in drain(0.5):
        print("   rx:", describe(f))
        if is_dpi(f) and frame is None:
            frame = f
    if frame:
        break

if not frame:
    print("!! no DPI frame seen - aborting (nothing was written)")
    raise SystemExit(1)

body = frame[1:]                      # the device body (kernel stripped the id)
stage = body[5]
orig = body[6] | (body[7] << 8)
print(f"\ncaptured DPI frame: {frame[:10].hex(' ')}  stage={stage} value={orig}")

print("\n[2] writing that frame back verbatim")
write_body(body)
got = drain(3.0)
for f in got:
    print("   rx:", describe(f))
if any(is_dpi(f) for f in got):
    print("   >>> the mouse re-pushed its DPI state: the write path works!")

print(f"\n[3] writing stage={stage} value={TEST_DPI}")
mod = bytearray(body)
mod[6] = TEST_DPI & 0xFF
mod[7] = (TEST_DPI >> 8) & 0xFF
write_body(bytes(mod))
got = drain(3.0)
changed = False
for f in got:
    print("   rx:", describe(f))
    if is_dpi(f):
        v = f[7] | (f[8] << 8)
        if v == TEST_DPI:
            changed = True
            print(f"   >>> the mouse reports the new DPI {v}!")
if not changed:
    print("   (no confirmation)")

print(f"\n[4] restoring value={orig}")
restore = bytearray(body)
write_body(bytes(restore))
for f in drain(2.0):
    print("   rx:", describe(f))

os.close(fd)
