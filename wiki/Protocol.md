# Protocol

Everything on this page was **measured on real hardware**, not inferred.
The full log with the dead ends and the corrections is in
[`docs/CUSTOMIZATION.md`](https://github.com/alfaisaldev/AJ159-NL-P-web-based-driver-micetil/blob/main/docs/CUSTOMIZATION.md).

## Transport

The mouse exposes a *vendor* HID collection next to the normal mouse
interface: usage pages `0xFFB1` / `0xFFB2` / `0xFFB3`, with **report id 6**
carrying 63-byte frames.

* write: `HIDIOCSOUTPUT` on the hidraw node of that collection
* read: the same node's input stream

No root, no `usbfs`, no unbinding `usbhid`. The frame layout was confirmed
against the vendor driver, which sends the very same thing as a USB class
control transfer (`SET_REPORT`, `wValue=0x0206`, `wIndex=1`, `wLength=64`).

## Frame layout

```
offset 0 : report id     0x06
offset 1 : class         command / notification class
offset 2 : entry length  L      (1 tag byte + L-1 value bytes)
offset 3 : reserved      0x00
offset 4 : reserved      0x00
offset 5 : type          property / sub-command
offset 6 : value (L-1 bytes)
```

A read is `06 <class>` and nothing else.

```
host -> mouse   06 05 01 00 00 00
mouse -> host   06 05 24 00 00 01 | 00 25 6d 12 10 01 01 64 …
```

## Status pushes (class 0xFA)

The mouse pushes status on its own — roughly every 30 s over NearLink,
every 10 s over USB, and only while it is awake.

| type | meaning | value |
|------|---------|-------|
| `0x01` | link state | 1 byte, flips when the mouse switches between NearLink and Bluetooth |
| `0x02` | DPI | 3 bytes: stage index + u16 LE stage value |
| `0x03` | **battery** | 2 bytes: percentage, then a charging flag |
| `0x06` | mode | 1 byte |

```
06 fa 03 00 00 03 64 01
                  |  |  +-- charging flag (1 = on USB power)
                  |  +----- percentage = 0x64 = 100 %
                  +-------- tag 0x03 = battery level
```

## The info block (class 0x05)

35 bytes, and the most useful thing the mouse will tell you:

| byte | meaning |
|------|---------|
| 7 | battery percent |
| 10 | number of DPI stages (6) |
| 11 | **active** DPI stage, zero based |
| 12…23 | six u16 LE DPI stages, stored as `dpi / 50 − 1` |
| 24 | report-rate index (0…3 → 125 / 250 / 500 / 1000 Hz) |

```
DPI stages read back:  07 00 0f 00 17 00 1f 00 2f 00 3f 00
                       400 800 1200 1600 2400 3200   (value = dpi/50 - 1)
```

## Writing

Two shapes, both taken from the vendor driver's own traffic:

```
DPI, one frame per stage
host -> mouse   06 13 05 00 00 01 | 06 <stage> <dpi lo> <dpi hi> 00

report rate
host -> mouse   06 13 02 00 00 02 | <value> 00
```

### ⚠ The two DPI encodings are different

```
read block  (class 0x05, offset 12)   dpi/50 - 1     400 -> 7
write frame (class 0x13, type 0x01)   raw dpi        400 -> 90 01
```

Mixing them up was measured: it wrote 7…63 dpi, the device clamped to its
50 dpi minimum, and all six stages read back as 0 (= 50 dpi). The write path
always uses the raw form.

### ⚠ There is no "select stage" command

The vendor application never sends one. The device **activates whichever
stage frame it received last**.

Measured, with the table values held constant so nothing else could move:

| write order | byte 11 | table |
|---|---|---|
| before | 1 | 400 800 1200 1600 2400 3200 |
| all six, stage **3** last | **3** | unchanged |
| all six, stage **1** last | **1** | unchanged |

So "use stage 4" is the ordinary verified DPI write with the table
re-ordered — the chosen stage sent last:

```python
dpi_frames_for_stage(table, stage)   # the others, then `stage`
```

The same fact explains a bug that existed for a while in the panel: editing
any DPI stage wrote the stages 0…5 in order, so **every DPI edit silently
moved the mouse to stage 6 (3200 DPI)**.

### Report rate, measured from the mouse's own input

The mouse's interrupt-IN stream says what each value does — median gaps
between reports while the vendor app held each value in force:

| value | median gap | rate |
|---|---|---|
| 0 | 8.00 ms | 125 Hz |
| 1 | 4.00 ms | 250 Hz |
| 2 | 2.00 ms | 500 Hz |
| 3 | 1.00 ms | 1000 Hz |

The window before and after the change both sat at 1.00 ms, so the change
is the setting and not the load.

Reading it back: `06 13 01 00 00 <id>` is only answered for `id = 0x09`.
The value is in the **info block instead — byte 24** (verified live: write
2 → byte 24 = 2, write 0 → byte 24 = 0).

## Verification and rollback

Every write is read back through an independent path, and a mismatch
triggers a restore of the previous value.

The receiver relays writes with a delay: a read straight after a write can
return the *previous* block, so verification **polls for up to ~3 s** rather
than sampling once. This is why the panel can be slow to answer a write —
it is waiting for the device, not for the network.

## Quarantined classes

`0x12` (records) and `0x31` (LED/profile, multi-chunk) are the only
classes that take bulk payloads, and a **short write to either clears stored
state**. The mouse's button map was lost that way twice; only the vendor's
"Restore Factory Settings" restored it.

`ajazz_protocol.py` refuses both, unconditionally:

```python
QUARANTINED_CLASSES = frozenset({0x12, 0x31})
```

## Still unknown

* **the button map** — no `06 12 … 11` write and no restore frame were ever
  captured. Until one is, the button map is not editable from Linux.
* the settings that live in the record and profile classes, for the same
  reason.
