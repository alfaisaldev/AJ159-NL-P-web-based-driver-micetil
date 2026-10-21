<p align="center">
  <img src="assets/logo-horizontal.png" alt="Micetil" width="520">
</p>

# Micetil — AJAZZ AJ159 NL P control panel

A small local web panel for the **AJAZZ AJ159 NL P** mouse (USB VID `0x7768`,
NearLink generation). It shows the real battery level and it controls the
mouse's **DPI stages**, the **active DPI stage** and the **report rate** —
every write is made with the vendor's own frame and read back before the
panel claims it worked.

No framework, no build step, no external Python packages: standard library
only, and one static HTML page.

```
http://127.0.0.1:8778
```

![The panel](docs/panel.png)

---

## What it does

| | |
|---|---|
| **Battery** | the percentage the mouse reports, plus charging state and the source node |
| **DPI stages** | read the six stored stages, change any of them in 50 DPI steps |
| **Active stage** | pick which of the six stages the mouse is using right now |
| **Report rate** | 125 / 250 / 500 / 1000 Hz, read back from the mouse |

The panel prefers the mouse's own wired USB interface (it knows about
charging) and falls back to the NearLink receiver. It re-scans every five
seconds, so plugging the mouse in or unplugging it needs no restart.

## Install

```bash
git clone <your-repo> micetil
cd micetil
./install.sh
```

`install.sh` does three things:

1. **udev rule** (`/etc/udev/rules.d/99-ajazz-mouse.rules`) — lets your user
   read the mouse's and the receiver's hidraw nodes without root:
   ```
   SUBSYSTEM=="hidraw", ATTRS{idVendor}=="7768", MODE="0660", GROUP="plugdev", TAG+="uaccess"
   ```
2. **systemd user service** `ajazz-panel.service` — the panel starts with
   your session and restarts if it dies.
3. **Desktop launcher** — “Micetil” in the app menu.

Manual start (no service):

```bash
python3 server.py --port 8778
```

## How it talks to the mouse

The mouse exposes a vendor HID collection (usage pages `0xFFB1` / `0xFFB2` /
`0xFFB3`) on report id **6**. Frames are one tag/value entry behind a
five-byte header:

```
offset 0 : report id     0x06
offset 1 : class         command / notification class
offset 2 : entry length  L      (1 tag byte + L-1 value bytes)
offset 3 : reserved      0x00
offset 4 : reserved      0x00
offset 5 : type          property / sub-command
offset 6 : value (L-1 bytes)
```

The panel writes to the node with `HIDIOCSOUTPUT` and reads the answers from
the same node's input stream — no root, no usbfs, no unbinding `usbhid`.

### Reading

A read is `06 <class>`; the mouse answers with the same shape:

```
host -> mouse   06 05 01 00 00 00
mouse -> host   06 05 24 00 00 01 | 00 25 6d 12 10 01 01 64 …
```

The class-`0x05` block is 35 bytes and holds almost everything the panel
shows:

| byte | meaning |
|------|---------|
| 7 | battery percent |
| 10 | number of DPI stages (6) |
| 11 | **active** DPI stage, zero based |
| 12…23 | six u16 LE DPI stages, stored as `dpi / 50 − 1` |
| 24 | report-rate index (0…3 → 125/250/500/1000 Hz) |

The mouse also pushes unsolicited status frames on class `0xFA`, where type
`0x03` is the battery:

```
06 fa 03 00 00 03 64 01
                  |  |  +-- charging flag (1 = on USB power)
                  |  +----- percentage = 0x64 = 100 %
                  +-------- tag 0x03 = battery level
```

### Writing

Two write shapes are used, both taken from the vendor application's own
traffic:

```
DPI, one frame per stage
host -> mouse   06 13 05 00 00 01 | 06 <stage> <dpi lo> <dpi hi> 00

report rate
host -> mouse   06 13 02 00 00 02 | <value> 00
```

The DPI value is the **raw DPI** as u16 LE, not the `dpi / 50 − 1` form the
read block uses — writing the read form makes the device clamp to its
50 DPI minimum.

**The active stage is chosen by ordering, not by a command.** The device
activates whichever stage frame it receives last, so the panel rewrites the
whole table with the chosen stage sent last. Measured on hardware: with the
table unchanged, writing stages 0…5 with stage 3 last moved the active stage
from 1 to 3, and writing with stage 1 last moved it back.

### Safety model

* Only the five read frames the vendor driver itself sends are allowed
  without an explicit write grant (`ajazz_protocol.READ_ONLY`).
* Classes `0x12` and `0x31` are **quarantined**: a short write to either
  clears stored state — the mouse's button map was lost twice that way, and
  only the vendor's “Restore Factory Settings” brought it back. The panel
  refuses to send them.
* Every write is **verified**: the value is read back and, if it does not
  match, the previous table is written again. The panel only reports success
  when the mouse itself confirms it.
* The receiver relays writes slowly, so a read straight after a write can
  return the previous block; the panel polls for up to ~3 s before deciding.

## API

| endpoint | returns |
|----------|---------|
| `GET /api/battery` | `{"percent":100,"ok":true,"detail":"battery reported","node":"/dev/hidraw4","device":"7768:6425","source":"NearLink receiver","charging":false,"chargeState":0,"raw":"06 fa 03 00 00 03 64 00 …","updatedAt":1792610122347,"age":5,"since":1792604206987,"rateHz":1000,"dpi":null,"dpiStage":null,"link":null,"mode":null}` |
| `GET /api/dpi` | `{"ok":true,"dpi":[400,800,1200,1600,2400,3200],"stages":6,"active":1,"activeDpi":800}` |
| `GET /api/stage` | same as `/api/dpi` |
| `POST /api/stage` | body `{"stage":0…5}` → switches the active stage, verified |
| `POST /api/dpi` | body `{"stage":0…5,"dpi":50…26000}` → writes one stage, verified |
| `GET /api/rate` | `{"ok":true,"hz":1000,"options":[125,250,500,1000],"readable":true,"note":"read back from the info block, byte 24"}` |
| `POST /api/rate` | body `{"hz":125|250|500|1000}` → sets the report rate, verified |
| `GET /api/health` | `{"ok":true,"uptime":1234}` |

A failed write answers with `{"ok":false,"error":"…"}` and the current
values, so the UI can show the real state instead of an optimistic guess.

## The interface

A desktop-style window: a device column with the battery, and cards for the
pointer stages, the polling rate and the device itself. The theme control in
the title bar switches between **system / light / dark** and is remembered
in `localStorage`. To force a theme from the URL:

```
http://127.0.0.1:8778/?theme=dark
http://127.0.0.1:8778/?theme=light
```

## Files

```
server.py                stdlib HTTP server: the UI, the JSON API
battery.py               device access: finds the vendor hidraw node, listens
                         for the status frames, parses the TLV entries,
                         writes and verifies DPI / stage / rate
ajazz_protocol.py        the wire format, the read-only whitelist, the
                         quarantined classes, the frame builders
static/index.html        the whole UI (single file, no framework)
static/fonts/            Inter Variable — the closest open SF Pro substitute
assets/                  brand assets, cropped from the identity board
install.sh               one-time setup (udev rule, systemd service, launcher)
docs/CUSTOMIZATION.md    the protocol notes: every frame, measured
docs/panel.png           screenshot of the panel
tools/                   the reverse-engineering tools that produced the
                         protocol, and the ones that check it
```

## Development

```bash
python3 tools/crop_brand.py     # re-cut the brand assets from the board
python3 tools/read_blocks.py    # read the mouse's config blocks (read-only)
python3 tools/dpi_roundtrip.py  # round-trip the DPI table and verify it
python3 tools/parse_capture.py ajaaz.pcapng   # decode a USB capture
```

`ajaaz.pcapng` is the capture of the vendor application that the protocol
was decoded from. It is **not** in this repository — it is kept local, because
a capture carries the recording machine's details (OS build, CPU model).
`docs/CUSTOMIZATION.md` keeps the decoded notes without it.

## Troubleshooting

* **“dongle not found”** — the receiver is not plugged in, or the udev rule
  has not been applied: `sudo udevadm control --reload-rules && sudo udevadm trigger`.
* **Permission denied** — check `ls -l /dev/hidraw*`; the node should be
  `root plugdev 660` and your user must be in the `plugdev` group.
* **Battery stuck at `--`** — the mouse must be switched on and paired to
  the dongle; it only relays status while it is awake.
* **Is the percentage right?** — it comes straight from the mouse. If the
  panel ever disagrees with the mouse's own LED, run
  `python3 tools/track_status.py 120` and compare.
* Service logs: `journalctl --user -u ajazz-panel -f`

## Notes

* The older AJ-series mice (`0x3151:…`) use a different, 64-byte
  feature-report protocol; this panel targets the NearLink generation
  (`0x7768:6425` / `0x7768:6d25`) only.
* The mouse's **button map** is not touched. The frames that rewrite it were
  never captured, and guessing at them is not worth losing the button map.
