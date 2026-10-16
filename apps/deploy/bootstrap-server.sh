#!/usr/bin/env bash
# One-time, NON-DESTRUCTIVE server preparation (Ubuntu). It never touches the existing web server or containers.
#   ssh -i ml.pem ubuntu@<ip> 'bash -s' < apps/deploy/bootstrap-server.sh            # compose plugin + folders
#   ssh -i ml.pem ubuntu@<ip> 'bash -s -- --with-swap' < apps/deploy/bootstrap-server.sh   # + swap file (size: SWAP_GB, default 1)
# The server may already run other apps (e.g. a example-app container behind the host nginx).
set -euo pipefail

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed; install it first (e.g. sudo apt-get install -y docker.io)." >&2
  exit 1
fi
if ! docker compose version >/dev/null 2>&1 && ! sudo docker compose version >/dev/null 2>&1; then
  sudo apt-get update -y
  sudo apt-get install -y docker-compose-v2 || sudo apt-get install -y docker-compose-plugin
fi
sudo docker compose version

sudo usermod -aG docker "$USER" || true
sudo mkdir -p /opt/landslide/traefik /opt/landslide/nginx /opt/landslide/project/{data,models,results}
sudo chown -R "$USER":"$USER" /opt/landslide

if [ "${1:-}" = "--with-swap" ] && ! swapon --show | grep -q .; then
  sudo fallocate -l "${SWAP_GB:-1}G" /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
  echo "Added ${SWAP_GB:-1} GB swap."
fi
free -m | awk '/^Mem:/{print "RAM MB:",$2," available:",$7}'; df -h / | awk 'NR==2{print "disk free:",$4}'
echo "Done. Log out/in once if you want to run docker without sudo."
