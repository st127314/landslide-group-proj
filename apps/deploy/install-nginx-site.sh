#!/usr/bin/env bash
# Run ON THE SERVER. Adds the landslide subdomain to the existing host nginx, forwarding to Traefik.
# It only ADDS one file under /etc/nginx/conf.d/, tests the whole config, and reloads only if the test passes;
# on failure it removes its own file again and leaves nginx exactly as it was.
set -euo pipefail
cd /opt/landslide
[ -f .env.local ] && { set -a; . ./.env.local; set +a; }
DOMAIN="${DOMAIN:-landslide.spadace.com}"; PORT="${TRAEFIK_PORT:-8088}"
DEST=/etc/nginx/conf.d/landslide.conf
if [ -f "$DEST" ] && grep -q ssl_certificate "$DEST"; then
  echo "$DEST already has TLS (certbot); leaving it untouched."; exit 0
fi
sed -e "s/__DOMAIN__/$DOMAIN/g" -e "s/__PORT__/$PORT/g" nginx/landslide-host.conf.template | sudo tee "$DEST" >/dev/null
if sudo nginx -t; then
  sudo systemctl reload nginx
  echo "nginx now forwards $DOMAIN to Traefik on 127.0.0.1:$PORT."
else
  echo "nginx config test FAILED; removing $DEST." >&2
  sudo rm -f "$DEST"
  exit 1
fi
