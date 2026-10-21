#!/usr/bin/env bash
# Capture the mouse's USB traffic while we send probe frames, then parse it.
# Validates tools/parse_capture.py on a real capture - the same workflow
# works for a capture of the vendor driver.
set -u
cd "$(dirname "$0")/.."
OUT=${1:-/tmp/opencode/usbmon.txt}
LOG=/tmp/opencode/capture_run.log
UNIT=ajazz-usbmon-cap

echo "== starting usbmon capture -> $OUT"
systemd-run --user --collect --unit=$UNIT \
  pkexec bash -c "cat /sys/kernel/debug/usb/devices > $OUT" >/dev/null 2>&1
sleep 3
ls -la "$OUT" || echo "(no capture file yet)"

echo "== sending probe frames (raw USB)"
systemd-run --user --wait --collect --unit=ajazz-cap-probe --pipe \
  pkexec python3 tools/usb_probe5.py 0x6d25 \
  > "$LOG" 2>&1
sleep 2

echo "== stopping capture"
systemctl --user stop $UNIT.service 2>/dev/null
sleep 1
echo "capture size: $(stat -c%s "$OUT" 2>/dev/null || echo 0) bytes"
echo "== parsing"
python3 tools/parse_capture.py "$OUT" | head -40
