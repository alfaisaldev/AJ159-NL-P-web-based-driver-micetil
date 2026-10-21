#!/usr/bin/env bash
# One-time setup for the AJAZZ mouse panel:
#   1. udev rule  -> lets your user read the mouse's hidraw node
#   2. systemd user service -> the panel starts with your session
#   3. desktop launcher -> open the panel from the app menu
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UDEV_RULE=/etc/udev/rules.d/99-ajazz-mouse.rules
SERVICE_DIR="$HOME/.config/systemd/user"
SERVICE_FILE="$SERVICE_DIR/ajazz-panel.service"
APP_DIR="$HOME/.local/share/applications"
APP_FILE="$APP_DIR/ajazz-panel.desktop"
PORT="${PORT:-8778}"
RULE_TEXT='SUBSYSTEM=="hidraw", ATTRS{idVendor}=="7768", MODE="0660", GROUP="plugdev", TAG+="uaccess"'

need_sudo=0
if [ ! -f "$UDEV_RULE" ] || ! grep -q '7768' "$UDEV_RULE"; then
  need_sudo=1
fi

if [ "$need_sudo" = "1" ]; then
  echo "==> installing udev rule for AJAZZ 7768:6425 (hidraw)"
  sudo tee "$UDEV_RULE" >/dev/null <<EOF
# Allow the desktop user to read the AJAZZ AJ159 NL P mouse hidraw nodes.
$RULE_TEXT
EOF
  sudo udevadm control --reload-rules
  sudo udevadm trigger --subsystem-match=hidraw
  echo "    rule installed: $UDEV_RULE"
else
  echo "==> udev rule already in place: $UDEV_RULE"
fi

echo "==> applying to the currently plugged-in mouse"
for d in /dev/hidraw*; do
  if [ -r "/sys/class/hidraw/$(basename "$d")/device/uevent" ] && \
     grep -q 'HID_ID=0003:00007768:' "/sys/class/hidraw/$(basename "$d")/device/uevent"; then
    if [ "$(stat -c '%a %G' "$d")" != "660 plugdev" ]; then
      sudo chgrp plugdev "$d" && sudo chmod 660 "$d"
    fi
    echo "    ok $d ($(stat -c '%a %U:%G' "$d"))"
  fi
done

echo "==> installing systemd user service"
mkdir -p "$SERVICE_DIR"
cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=AJAZZ mouse battery panel
After=graphical-session.target

[Service]
ExecStart=$(command -v python3) $HERE/server.py --host 127.0.0.1 --port $PORT
Restart=always
RestartSec=3
WorkingDirectory=$HERE

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now ajazz-panel.service
echo "    service: systemctl --user status ajazz-panel"

echo "==> installing launcher"
mkdir -p "$APP_DIR"
cat > "$APP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=Micetil
Comment=Micetil - AJAZZ AJ159 NL P control panel
Exec=xdg-open http://127.0.0.1:$PORT
Icon=$HERE/assets/emblem.png
Terminal=false
Categories=Utility;
EOF
update-desktop-database "$APP_DIR" 2>/dev/null || true

echo
echo "Done. Open http://127.0.0.1:$PORT  (or launch 'AJAZZ Mouse Panel')."
