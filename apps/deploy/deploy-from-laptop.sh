#!/usr/bin/env bash
# Deploy WITHOUT a container registry or GitHub secrets: build linux/amd64 images on this machine, ship them over SSH,
# upload the config and the private data, then start the stack with the same deploy.sh the CI/CD workflow uses.
#
#   apps/deploy/deploy-from-laptop.sh <key.pem> <user@host> [stage ...]
#   stages (default: all, in this order):
#     bootstrap  compose plugin, folders and a swap file on the server (non-destructive; see bootstrap-server.sh)
#     images     build backend + frontend for linux/amd64 and pull Traefik
#     ship       docker save | ssh docker load (no registry)
#     data       upload the private data (sync-data.sh; LIGHT=1 skips the building footprints, default)
#     up         upload config, start/refresh the stack, wait for health, add the nginx site
#
# Environment: GHCR_OWNER (default st127314), IMAGE_TAG (default manual-<git sha>), LIGHT (default 1),
#              SWAP_GB (default 1), SSH_EXTRA (e.g. "-o UserKnownHostsFile=... -o StrictHostKeyChecking=yes").
set -euo pipefail
KEY="${1:?usage: deploy-from-laptop.sh <key.pem> <user@host> [stage ...]}"
HOST="${2:?usage: deploy-from-laptop.sh <key.pem> <user@host> [stage ...]}"
shift 2
STAGES=("$@"); [ ${#STAGES[@]} -eq 0 ] && STAGES=(bootstrap images ship data up)
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OWNER="${GHCR_OWNER:-st127314}"
TAG="${IMAGE_TAG:-manual-$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M)}"
LIGHT="${LIGHT:-1}"
SSH="ssh -i $KEY -o IdentitiesOnly=yes ${SSH_EXTRA:-}"
SCP="scp -i $KEY -o IdentitiesOnly=yes ${SSH_EXTRA:-}"
BACKEND="ghcr.io/$OWNER/landslide-backend:$TAG"
FRONTEND="ghcr.io/$OWNER/landslide-frontend:$TAG"
echo "Deploying $TAG to $HOST (stages: ${STAGES[*]})"

for stage in "${STAGES[@]}"; do
  echo "=== $stage"
  case "$stage" in
    bootstrap)
      $SSH "$HOST" "SWAP_GB=${SWAP_GB:-1} bash -s -- --with-swap" < "$ROOT/apps/deploy/bootstrap-server.sh" ;;
    images)
      docker buildx build --platform linux/amd64 --load -t "$BACKEND" "$ROOT/apps/backend"
      docker buildx build --platform linux/amd64 --load --build-arg NEXT_PUBLIC_API_URL= -t "$FRONTEND" "$ROOT/apps/frontend"
      docker pull --platform linux/amd64 traefik:v3.1 ;;
    ship)
      docker save "$BACKEND" "$FRONTEND" traefik:v3.1 | gzip | $SSH "$HOST" 'gunzip | sudo docker load' ;;
    data)
      SKIP_BUILDINGS="$LIGHT" SSH_EXTRA="${SSH_EXTRA:-}" "$ROOT/apps/deploy/sync-data.sh" "$KEY" "$HOST" ;;
    up)
      $SSH "$HOST" 'mkdir -p /opt/landslide/traefik /opt/landslide/nginx'
      $SCP "$ROOT/apps/deploy/docker-compose.yml" "$ROOT/apps/deploy/deploy.sh" "$ROOT/apps/deploy/enable-https.sh" \
           "$ROOT/apps/deploy/install-nginx-site.sh" "$HOST:/opt/landslide/"
      $SCP "$ROOT/apps/deploy/traefik/landslide.yml" "$HOST:/opt/landslide/traefik/"
      $SCP "$ROOT/apps/deploy/nginx/landslide-host.conf.template" "$HOST:/opt/landslide/nginx/"
      # first deploy only: conservative memory limits for a small shared server (never overwritten afterwards)
      $SSH "$HOST" '[ -f /opt/landslide/.env.local ] || printf "DOMAIN=landslide.spadace.com\nTRAEFIK_PORT=8088\nBACKEND_MEM_LIMIT='"${BACKEND_MEM_LIMIT:-450m}"'\nFRONTEND_MEM_LIMIT='"${FRONTEND_MEM_LIMIT:-220m}"'\n" > /opt/landslide/.env.local'
      $SSH "$HOST" "chmod +x /opt/landslide/*.sh && SKIP_PULL=1 IMAGE_TAG='$TAG' GHCR_OWNER='$OWNER' /opt/landslide/deploy.sh"
      $SSH "$HOST" "cd /opt/landslide && ./install-nginx-site.sh" ;;
    *) echo "unknown stage: $stage" >&2; exit 1 ;;
  esac
done
echo "Done. Test on the server: curl -H 'Host: landslide.spadace.com' http://127.0.0.1:8088/api/health"
