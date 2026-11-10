# CI/CD and deployment (Traefik)

```
git push (main) ─► GitHub Actions
                    1. test      backend API tests (synthetic data) + data/model tests + frontend lint/build
                                 + deploy-config checks (shell syntax, docker compose config)
                    2. build     Docker images  ghcr.io/<owner>/landslide-backend|frontend|forecast:<sha>
                    3. deploy    SSH to the AWS server -> docker compose pull/up -> health check -> auto-rollback
                                 (skipped until the repository variable DEPLOY_ENABLED = true)
```

Pull requests run step 1 only. Nothing in the repo contains data or credentials: the pipeline data is private and is
uploaded separately (`sync-data.sh`); the SSH key lives only in GitHub secrets.

## How traffic flows on the server

```
internet ─► host nginx (80/443, already serves the other app; adds TLS for landslide.spadace.com via certbot)
              └─► Traefik  127.0.0.1:8088  (routes by Host + path, rate limit, gzip, headers)
                    ├─ /api/*  ─► backend  (FastAPI, read-only)
                    └─ /*      ─► frontend (Next.js)
```

* Traefik listens **only on `127.0.0.1:${TRAEFIK_PORT}`** (default 8088). It never needs ports 80/443, so it runs next to
  the other app without touching it. Routes are in `traefik/landslide.yml` (file provider, hot-reloaded); there are no
  Docker labels, so Traefik never gets the Docker socket (root-equivalent on a shared host).
* Let's Encrypt cannot validate through a non-standard port, so **HTTPS is terminated by the host nginx + certbot**
  (`install-nginx-site.sh`, `enable-https.sh`). Traefik stays plain HTTP behind it.
* A different subdomain later = add `|| Host(`new.example.com`)` to the two rules in `traefik/landslide.yml`, plus an
  nginx `server_name`/certificate for it.
* *Alternative:* if you later want Traefik to own 80/443 (and do its own certificates), the other app has to move behind
  Traefik too (or nginx be retired). That is a bigger change to the live server and is not done here.

## What the server looks like

Ubuntu 26.04, 2 vCPU, **908 MB RAM, 1 GB swap (added by `bootstrap-server.sh --with-swap`), ~3 GB disk free**; Docker with
the compose plugin; the host nginx also serves another app on `127.0.0.1:8050`. This stack only adds one nginx file and
three containers.

**Memory decides what is deployed.** The API reads its data lazily, so the deployment (live forecast, impact overlay,
what-if scenario, susceptibility map, tambons, facilities) needs about 150 MB of backend RAM. Buildings are served as
vector tiles from `buildings.pmtiles` (20 MB on disk, nothing in memory); the 140 MB GeoJSON, which needs roughly
1.5 GB as Python objects, is not uploaded (`SKIP_BUILDINGS=1`), so only the bounding-box endpoint
`/api/impact/buildings` answers 404. Set `BACKEND_MEM_LIMIT=450m` and `FRONTEND_MEM_LIMIT=220m` in
`/opt/landslide/.env.local` on a small server (the compose defaults are 3g and 300m; `deploy-from-laptop.sh` writes
these two lines): the limits keep an out-of-memory kill inside the container instead of taking the other app down.

## Scheduled forecast refresh

`apps/forecast/Dockerfile` builds a third image that runs `run_live_gfs_forecast.py` and then
`refresh_impact_overlay.py` (pandas only, a few seconds, 300 MB limit). It is the compose service `forecast`, in the
profile `jobs`, so `docker compose up` never starts it. Run **once from your laptop**:

```bash
apps/deploy/install-forecast-cron.sh credentials/github_deploy_key ubuntu@<server-ip>
```

It copies the Earth Engine service-account key to `/opt/landslide/secrets/gee_key.json` (mode 600, mounted read-only
into the job) and installs the cron entry `20 */3 * * * docker compose --profile jobs run --rm forecast`. The API
re-reads the forecast and overlay on every request, so no restart is needed. Log: `/opt/landslide/forecast.log`.

## Files

```
docker-compose.yml  deploy.sh  enable-https.sh  install-nginx-site.sh   <- uploaded by the workflow on every deploy
install-forecast-cron.sh         run LOCALLY once: uploads the Earth Engine key and installs the 3-hourly forecast job
traefik/landslide.yml            routes/middlewares (rendered to traefik/dynamic/landslide.yml)
nginx/landslide-host.conf.template   host-nginx site block (rendered to /etc/nginx/conf.d/landslide.conf)
bootstrap-server.sh              one-time: compose plugin + folders (optional 1 GB swap); never touches nginx
sync-data.sh                     run LOCALLY: uploads the private data the API reads
```
On the server (`/opt/landslide`): `project/{data,models,results}` (private data, mounted read-only), `.env.local`
(your settings: `DOMAIN`, `TRAEFIK_PORT`, memory limits; never overwritten), `.env` (written by `deploy.sh`).

## One-time setup (when you are ready)

0. **No registry or GitHub secrets needed for a first deploy:** `apps/deploy/deploy-from-laptop.sh <key.pem> <user@host>`
   runs steps 2, 3 and 5 below from your laptop (amd64 images over SSH). Steps 4 and 6 are for the automatic pipeline.
1. **Size** — see the memory note above.
2. **Prepare the server** (adds the compose plugin and folders only; read the script first):
   `ssh -i ml.pem ubuntu@<server-ip> 'bash -s' < apps/deploy/bootstrap-server.sh`
3. **Upload the private data** (about 130 MB): `SKIP_BUILDINGS=1 apps/deploy/sync-data.sh ml.pem ubuntu@<server-ip>`
   (re-run, then `docker compose restart backend`, whenever the results change).
4. **GitHub secrets/variables** — must be set by an account with admin rights on the repo (`st127314`; the `gh` CLI on
   this machine is logged in as a different user and cannot):
   ```bash
   R=st127314/landslide-group-proj
   gh secret set EC2_HOST --body <server-ip> -R $R
   gh secret set EC2_USER --body ubuntu -R $R
   gh secret set EC2_SSH_KEY -R $R < ml.pem
   gh secret set EC2_KNOWN_HOSTS -R $R < credentials/ec2_known_hosts.txt   # pins the server host keys
   gh variable set DEPLOY_ENABLED --body true -R $R                                               # last: switches deploy on
   ```
   Safer than uploading `ml.pem`: create a deploy-only key (`ssh-keygen -t ed25519 -f deploy_key`), append
   `deploy_key.pub` to `~/.ssh/authorized_keys` on the server and store `deploy_key` as `EC2_SSH_KEY`.
5. **First deploy** — push to `main` (or run the workflow by hand). The server pulls the images with the job's
   short-lived token, so no registry password is stored on it.
6. **Expose the subdomain** — add the DNS **A record** `landslide.spadace.com → <server-ip>` (use an **Elastic IP**,
   otherwise the IP changes when the instance is stopped), then on the server:
   ```bash
   cd /opt/landslide && ./install-nginx-site.sh          # adds ONE file to /etc/nginx/conf.d, tests, reloads (undoes itself on failure)
   ./enable-https.sh landslide.spadace.com you@example.com   # certbot --nginx: certificate + HTTP->HTTPS redirect
   ```
   Until DNS exists you can test on the server with `curl -H 'Host: landslide.spadace.com' http://127.0.0.1:8088/api/health`.

## Operations (on the server, in `/opt/landslide`)
| Task | Command |
|---|---|
| Status / logs | `docker compose ps` · `docker compose logs -f backend` |
| Roll back by hand | `IMAGE_TAG=<older-sha> GHCR_OWNER=st127314 ./deploy.sh` |
| Restart after new data | `docker compose restart backend` |
| Refresh the forecast now | `docker compose --profile jobs run --rm forecast` |
| Free disk | `deploy.sh` keeps only the current and previous image tags; `docker image prune -f` removes dangling layers |

A failed health check after a deploy rolls back to the previous tag automatically (`deploy.sh`).

## Local check of the whole stack
Build the two images, then `docker compose up` with `GHCR_OWNER=me IMAGE_TAG=local DATA_ROOT=<folder with data/ models/ results/>
TRAEFIK_PORT=18088` and call `http://localhost:18088/` with `-H 'Host: landslide.spadace.com'`.
