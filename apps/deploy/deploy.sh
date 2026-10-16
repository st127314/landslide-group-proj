#!/usr/bin/env bash
# Runs ON THE SERVER (called by the GitHub Actions deploy job). Renders the Traefik routes, pulls the images for
# IMAGE_TAG, restarts the stack, waits for the containers to be healthy and rolls back to the previous tag if not.
set -euo pipefail
cd /opt/landslide

: "${IMAGE_TAG:?IMAGE_TAG is required}"
: "${GHCR_OWNER:?GHCR_OWNER is required}"

# Settings that survive deploys live in .env.local (domain, Traefik port, memory limits); deploy.sh only owns .env.
[ -f .env.local ] || printf 'DOMAIN=landslide.spadace.com\nTRAEFIK_PORT=8088\n' > .env.local
set -a; . ./.env.local; set +a
DOMAIN="${DOMAIN:-landslide.spadace.com}"

mkdir -p traefik/dynamic project/data project/models project/results
sed "s/__DOMAIN__/$DOMAIN/g" traefik/landslide.yml > traefik/dynamic/landslide.yml.new && mv traefik/dynamic/landslide.yml.new traefik/dynamic/landslide.yml

previous=""
[ -f .env ] && previous=$(grep -E '^IMAGE_TAG=' .env | cut -d= -f2 || true)
{ cat .env.local; printf 'GHCR_OWNER=%s\nIMAGE_TAG=%s\nPREVIOUS_IMAGE_TAG=%s\n' "$GHCR_OWNER" "$IMAGE_TAG" "$previous"; } > .env

# SKIP_PULL=1: the images were loaded onto the server directly (deploy-from-laptop.sh), no registry involved
[ "${SKIP_PULL:-0}" = "1" ] || docker compose pull backend frontend
docker compose up -d --remove-orphans

healthy() {
  for _ in $(seq 1 40); do
    states=$(docker compose ps --format '{{.Service}}={{.Health}}' | sort | tr '\n' ' ')
    case "$states" in
      *backend=healthy*frontend=healthy*traefik=healthy*) return 0 ;;
    esac
    sleep 4
  done
  return 1
}

if healthy; then
  echo "Deployed $IMAGE_TAG"
  docker image prune -f >/dev/null
else
  echo "New release $IMAGE_TAG is unhealthy" >&2
  docker compose ps >&2 || true
  docker compose logs --tail=60 backend frontend traefik >&2 || true
  if [ -n "$previous" ] && [ "$previous" != "$IMAGE_TAG" ]; then
    echo "Rolling back to $previous" >&2
    { cat .env.local; printf 'GHCR_OWNER=%s\nIMAGE_TAG=%s\nPREVIOUS_IMAGE_TAG=\n' "$GHCR_OWNER" "$previous"; } > .env
    docker compose up -d --remove-orphans
  fi
  exit 1
fi
