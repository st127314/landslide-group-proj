// MapLibre 6 loads its worker from a URL next to its own module, which the Next.js bundle does not emit, so the
// worker is copied into public/ and ImpactMap points maplibregl.setWorkerUrl at it.
import { copyFileSync, mkdirSync } from "node:fs";

mkdirSync("public", { recursive: true });
copyFileSync("node_modules/maplibre-gl/dist/maplibre-gl-worker.mjs", "public/maplibre-gl-worker.mjs");
