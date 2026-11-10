# Dashboard (Next.js)

The web front end of the landslide impact application. See `../README.md` for the pages and the API it calls, and
`../deploy/README.md` for how it is built and deployed.

```bash
npm install
npm run dev          # http://localhost:3000
npm run lint
npm run build        # production build (standalone output, used by the Dockerfile)
```

- `NEXT_PUBLIC_API_URL` — API base URL used by the browser (default `http://localhost:8000`; `""` in production, where
  the API is served from the same origin under `/api/`).
- `INTERNAL_API_URL` — API base URL used by server components inside the container (`http://backend:8000`).
- `scripts/copy-maplibre-worker.mjs` runs before `dev` and `build` and copies the MapLibre worker into `public/`.
