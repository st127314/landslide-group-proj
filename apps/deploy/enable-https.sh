#!/usr/bin/env bash
# Run ON THE SERVER once an A record  <domain> -> this server's public IP resolves and install-nginx-site.sh has run.
#   cd /opt/landslide && ./enable-https.sh landslide.spadace.com you@example.com
# Uses the host's existing certbot (it already manages the other app's certificate): gets a certificate for this
# name only, adds the HTTPS block to /etc/nginx/conf.d/landslide.conf and redirects HTTP -> HTTPS. Traefik stays
# plain HTTP on localhost behind nginx, so it never needs ports 80/443 or ACME of its own.
set -euo pipefail
DOMAIN="${1:?usage: enable-https.sh <domain> <email>}"
EMAIL="${2:?usage: enable-https.sh <domain> <email>}"
getent hosts "$DOMAIN" >/dev/null || { echo "$DOMAIN does not resolve yet; add the DNS A record first." >&2; exit 1; }
sudo certbot --nginx -d "$DOMAIN" --email "$EMAIL" --agree-tos --no-eff-email --non-interactive --redirect
sudo nginx -t && sudo systemctl reload nginx
echo "HTTPS enabled for https://$DOMAIN (renewal uses the host's existing certbot timer)."
