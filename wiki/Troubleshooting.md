# Troubleshooting

## The panel says "no AJAZZ mouse or receiver found"

The device is not visible to the panel.

```bash
lsusb | grep -i 7768
ls -l /dev/hidraw*
```

* **Nothing in `lsusb`** — the mouse or the receiver is not plugged in, or
  the USB port is not delivering power. Try the other port.
* **The device is there, but no hidraw node** — the `usbhid` driver has not
  bound the interface, or the node is owned by root and unreadable.
  Re-apply the rule:
  ```bash
  sudo udevadm control --reload-rules && sudo udevadm trigger
  ```
* **Permission denied on `/dev/hidraw*`** — the node should be
  `root plugdev 660` and your user must be in the `plugdev` group:
  ```bash
  groups | grep plugdev      # not there?  sudo usermod -aG plugdev $USER
  ```
  Log out and back in for the group change to take effect. On a
  distribution without `plugdev`, see [[Installation]].

## The battery is stuck at `--`

The mouse only relays status while it is **awake and paired**. Switch it on
and check the pairing.

The panel keeps the last reading, so a restart still shows a real number
with its age ("Level since 2 h"). If the number is old, the mouse has not
been talking for a while — the panel polls the info block every 15 s, so a
stale value means the device stopped answering entirely.

```bash
python3 tools/track_status.py 120     # log the decoded status frames
```

## "Is the percentage right?"

It comes straight from the mouse, over the wireless link (or over USB when
it is on the cable). The panel never guesses: it shows the last value the
device reported.

The charging flag flips to `1` exactly when the mouse sits on the USB
cable:

```
receiver (wireless):  06 fa 03 00 00 03 64 00   100 %, not charging
mouse (USB cable):    06 fa 03 00 00 03 64 01   100 %, charging
```

If the panel disagrees with the mouse's own LED, run
`python3 tools/track_status.py 120` and compare — that logs every decoded
frame with a timestamp.

## A write was rejected

The panel says so in the status line and **restores the previous value**.
The message contains what the device read back, and that is the interesting
part.

Common causes:

* **The mouse was asleep** — it did not answer the read-back. Wake it and
  try again.
* **The receiver relayed the write late** — the panel polls for ~3 s; if
  the device answers even later, the read-back times out.
* **The value was rejected** — the DPI range is 50…26000, in steps of 50.

## The report rate does not stick

Check the read-back row in the Polling card. If the panel shows a value it
wrote but the mouse reads a different one, the write was refused.

`/api/rate` reports where the number came from:

```json
{"ok":true,"hz":1000,"readable":true,"note":"read back from the info block, byte 24"}
```

`"readable": false` means the mouse did not answer the read, and the panel
is showing the last value it wrote.

## The stage does not change

The active stage is byte 11 of the info block. Check it:

```bash
curl -s http://127.0.0.1:8778/api/dpi
```

```json
{"ok":true,"dpi":[400,800,1200,1600,2400,3200],"stages":6,"active":1,"activeDpi":800}
```

If `active` did not move, the write did not land — the mouse has to be
awake and in range.

## The panel is slow to answer a write

Expected. Verification waits for the device (up to ~3 s) and the receiver
relays writes with a delay. It is not a network round trip.

## The service is not running

```bash
systemctl --user status ajazz-panel
journalctl --user -u ajazz-panel -n 50
```

The service file points at the path you cloned to — if you moved the
repository, reinstall it (or edit `ExecStart` and `WorkingDirectory` in
`~/.config/systemd/user/ajazz-panel.service`, then
`systemctl --user daemon-reload`).

## The theme keeps resetting

The choice is stored in `localStorage['micetil-theme']` — per browser, per
origin. A private window or a cleared profile forgets it. `?theme=dark` and
`?theme=light` force a theme for one visit.

## Everything else

Read the service log first; it is usually enough:

```bash
journalctl --user -u ajazz-panel -f
```
