# Micetil

A local control panel for the **AJAZZ AJ159 NL P** mouse (USB vendor id
`0x7768`, NearLink generation), written on Linux against the vendor's own
HID protocol.

It shows the mouse's real battery level and controls its **DPI stages**,
the **active DPI stage** and the **report rate** — with no driver, no Wine,
no root and no network access.

```
http://127.0.0.1:8778
```

* **Repository:** <https://github.com/alfaisaldev/AJ159-NL-P-web-based-driver-micetil>
* **Install:** [[Installation]]
* **How it talks to the mouse:** [[Protocol]]
* **When something looks wrong:** [[Troubleshooting]]
* **Working on it:** [[Development]]
* **The device, the nodes, the two USB ids:** [[Hardware-notes]]

## What it does

| | |
|---|---|
| **Battery** | the percentage the mouse reports, charging state, and which node answered |
| **DPI stages** | read the six stored stages, change any of them in 50 DPI steps |
| **Active stage** | choose which of the six stages the mouse is using right now |
| **Report rate** | 125 / 250 / 500 / 1000 Hz, read back from the mouse |

The panel prefers the mouse's own wired USB interface (it knows about
charging) and falls back to the NearLink receiver, re-scanning every five
seconds — plugging the mouse in or unplugging it needs no restart.

## The interface

A desktop-style window: a device column with the battery on the left, cards
for the pointer stages, the polling rate and the device on the right. The
title bar has a **system / light / dark** theme switch, remembered across
restarts.

```
http://127.0.0.1:8778/?theme=dark
http://127.0.0.1:8778/?theme=light
```

## One thing to know up front

Every write is **verified by the device**: the panel writes a value, reads it
back through an independent path, and if the mouse did not store it, the
previous value is written again and the panel says so. The UI never shows a
value the mouse did not confirm.

Classes `0x12` (records) and `0x31` (LED/profile) are **quarantined** — a
short write to either clears stored state, and the mouse's button map was
lost that way twice. Micetil never sends them.

## The short story

The mouse ships with a Windows driver that does all of this, and nothing on
Linux. The protocol was decoded from a capture of that driver, the write
frames were taken from the driver's own traffic, and every claim was checked
against the hardware. The full account is in the repository's
[README](https://github.com/alfaisaldev/AJ159-NL-P-web-based-driver-micetil#how-this-was-made--the-short-story)
and in `docs/CUSTOMIZATION.md`.
