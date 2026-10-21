# Installation

## Requirements

* Linux with `hidraw`, `udev` and `systemd` (a user session is enough).
* Python **3.9 or newer** — the panel uses the standard library only, there
  is nothing to `pip install`.
* The mouse (`7768:6d25`) or its NearLink receiver (`7768:6425`).

## Automatic

```bash
git clone https://github.com/alfaisaldev/AJ159-NL-P-web-based-driver-micetil.git
cd AJ159-NL-P-web-based-driver-micetil
./install.sh
```

`install.sh` does three things, and it is the only step that needs `sudo`:

**1. A udev rule** — `/etc/udev/rules.d/99-ajazz-mouse.rules`:

```
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="7768", MODE="0660", GROUP="plugdev", TAG+="uaccess"
```

This lets your user read the mouse's and the receiver's hidraw nodes
without running anything as root. It applies to the devices that are
plugged in now, and to any that appear later.

**2. A systemd user service** — `~/.config/systemd/user/ajazz-panel.service`:

```ini
[Service]
ExecStart=/usr/bin/python3 /path/to/server.py --host 127.0.0.1 --port 8778
Restart=always
RestartSec=3
WorkingDirectory=/path/to
```

The panel starts with your session and restarts if it crashes.

**3. A desktop launcher** — "Micetil" in the app menu, pointing at
`http://127.0.0.1:8778`.

## Manual

No install, no service, no root:

```bash
cd ~/Desktop/Micetil
python3 server.py --port 8778
```

```
AJAZZ panel  ->  http://127.0.0.1:8778
```

Useful flags: `--host` (default `127.0.0.1`) and `--port` (default `8778`).
Keep the host on the loopback — the panel has no authentication.

## Check that it works

```bash
curl -s http://127.0.0.1:8778/api/health
curl -s http://127.0.0.1:8778/api/battery
```

The first answers immediately. The second answers with a real reading, or
with `"no AJAZZ mouse or receiver found"` if the mouse is asleep, out of
range, or not plugged in.

## Stopping and removing it

```bash
systemctl --user stop ajazz-panel            # stop it now
systemctl --user disable --now ajazz-panel   # stop it and keep it stopped
```

To remove everything the installer created:

```bash
systemctl --user disable --now ajazz-panel
rm ~/.config/systemd/user/ajazz-panel.service
rm ~/.local/share/applications/ajazz-panel.desktop
systemctl --user daemon-reload
sudo rm /etc/udev/rules.d/99-ajazz-mouse.rules
sudo udevadm control --reload-rules
```

Stopping the panel does not affect the mouse: it only stops the panel from
listening for pushes and from polling the info block every 15 seconds.

## Other distributions

The udev rule assumes the `plugdev` group, which exists on Debian, Ubuntu
and Arch. On a distribution without it (Fedora, openSUSE), either create the
group and add yourself to it, or use the seat-based access instead:

```
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="7768", MODE="0660", TAG+="uaccess"
```

`uaccess` grants access to whoever is logged in at the seat, which is what
the panel needs anyway.

## Logs

```bash
journalctl --user -u ajazz-panel -f
```

The panel's own state and the battery history live in
`~/.cache/ajazz-panel/` (`last.json`, `battery.log`, `rate.json`).
