#!/usr/bin/env bash
# Install and start the 6-hourly GFS refresh timer on the server (run once, with sudo).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
sudo install -m 644 "$here/landslide-gfs-refresh.service" /etc/systemd/system/
sudo install -m 644 "$here/landslide-gfs-refresh.timer" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now landslide-gfs-refresh.timer
systemctl list-timers landslide-gfs-refresh.timer
