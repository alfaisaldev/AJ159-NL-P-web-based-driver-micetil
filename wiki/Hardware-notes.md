# Hardware notes

## The two USB devices

Both are vendor id **`0x7768`**:

| USB id | what it is | hidraw | how it behaves |
|---|---|---|---|
| `7768:6425` | **NearLink receiver** (the dongle) | `/dev/hidraw*` | relays the mouse's status every ~30 s; the mouse is on battery |
| `7768:6d25` | **the mouse itself**, wired over USB | `/dev/hidraw*` | reports every ~10 s and knows whether it is charging |

The dongle only relays while the mouse is awake, in range and paired. The
wired interface answers immediately and reports the charging flag, so the
panel prefers it.

## Which node the panel picks

The panel scans every hidraw node of a `0x7768` device, keeps the ones that
expose the vendor collection (usage page `0xFFB2`, report id 6), and ranks
them:

1. the mouse over USB (`0x6d25`)
2. the NearLink receiver (`0x6425`)

It re-scans every **5 seconds**, so plugging the mouse in or unplugging it
needs no restart. The node it settled on is shown in the **Device** card
(`/dev/hidraw4`, `7768:6425` in the example below).

```
Source   NearLink receiver
Node     /dev/hidraw4
USB id   7768:6425
```

The hidraw numbers are not stable — they change when the device
re-enumerates. Never hard-code one.

## On battery and on the cable

The mouse reports the same battery percentage either way; what changes is
the **charging flag**, and it flips to `1` exactly when the mouse sits on
the USB cable:

```
receiver (wireless):  06 fa 03 00 00 03 64 00   100 %, not charging
mouse (USB cable):    06 fa 03 00 00 03 64 01   100 %, charging
```

The panel shows this as *"On Battery · Power Source: Battery"* or
*"Charging · Power Source: USB"*.

## The DPI stages

Six stages, stored as `dpi / 50 − 1` in the info block:

| stage | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|
| DPI | 400 | 800 | 1200 | 1600 | 2400 | 3200 |

The mouse uses exactly one of them at a time — byte 11 of the info block.
There is no "select stage" command; the device activates whichever stage
frame it received last. See [[Protocol]].

## The report rate

125 / 250 / 500 / 1000 Hz, stored as an index in byte 24 of the info block.
The value can also be measured from the mouse's own input stream — the
median gap between reports. See [[Protocol]].

## What the panel will not touch

* **The button map.** The frames that write it were never captured. A
  short write to class `0x12` clears it, and only the vendor's "Restore
  Factory Settings" brings it back.
* **The LED and profile blocks** (class `0x31`), for the same reason.
* **Any other HID device** on the machine. Only `0x7768` devices are ever
  opened.

## Other mice

The older AJ-series mice (`0x3151:…`) use a different, 64-byte
feature-report protocol. Micetil targets the NearLink generation only
(`0x7768:6425` / `0x7768:6d25`).

## If the device numbers do not match

The product id of the wired mouse is `0x6d25`; the receiver's is `0x6425`.
Both are listed in the vendor driver's own configuration table, which is
kept in the repository as `docs/vendor-config.xml`.
