"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import * as maplibregl from "maplibre-gl";
import type { Map as MapLibreMap } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { api } from "@/lib/api";

// OpenStreetMap standard tiles: no API key, attribution required. Fine for a low-traffic project site under the
// OSM tile usage policy; a heavily used deployment should move to a commercial or self-hosted tile service.
const BASE_STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: {
    osm: {
      type: "raster",
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      maxzoom: 19,
      attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    },
  },
  layers: [{ id: "osm", type: "raster", source: "osm" }],
};

// Served from public/ (copied there by scripts/copy-maplibre-worker.mjs): the bundle does not ship the worker.
maplibregl.setWorkerUrl("/maplibre-gl-worker.mjs");

const STUDY_AREA_CENTER: [number, number] = [100.0, 8.2];
const STUDY_AREA_ZOOM = 6.3;

// The report's five susceptibility classes (calibrated score bins and Figure 1 colours); the PNG layer is rendered
// with the same table in scripts/make_susceptibility_png.py.
const SUSCEPTIBILITY_CLASSES: Array<{ label: string; range: string; color: string }> = [
  { label: "Very low", range: "< 0.2", color: "#cde2fb" },
  { label: "Low", range: "0.2–0.4", color: "#86b6ef" },
  { label: "Moderate", range: "0.4–0.6", color: "#2a78d6" },
  { label: "High", range: "0.6–0.8", color: "#1c5cab" },
  { label: "Very high", range: "≥ 0.8", color: "#104281" },
];
const CLASS_EDGES = [0.2, 0.4, 0.6, 0.8];

const FACILITY_CATEGORY_COLORS: Record<string, string> = {
  hospital: "#dc2626",
  clinic: "#dc2626",
  doctors: "#dc2626",
  dentist: "#dc2626",
  pharmacy: "#f97316",
  nursing_home: "#f97316",
  veterinary: "#f97316",
  school: "#2563eb",
  college: "#2563eb",
  university: "#2563eb",
  kindergarten: "#2563eb",
  fire_station: "#b91c1c",
  police: "#1d4ed8",
  townhall: "#7c3aed",
  community_centre: "#7c3aed",
  courthouse: "#7c3aed",
  embassy: "#7c3aed",
  post_office: "#7c3aed",
  railway_station: "#059669",
  railway_halt: "#059669",
  bus_station: "#059669",
  airport: "#059669",
  airfield: "#059669",
  ferry_terminal: "#059669",
};
const DEFAULT_FACILITY_COLOR = "#78716c"; // places of worship + anything else

interface Layers {
  boundary: boolean;
  susceptibilityGrid: boolean;
  susceptibility: boolean;
  facilities: boolean;
  buildings: boolean;
}

export default function ImpactMap() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const [layers, setLayers] = useState<Layers>({
    boundary: true,
    susceptibilityGrid: true,
    susceptibility: false,
    facilities: true,
    buildings: true,
  });
  const [buildingsTruncated, setBuildingsTruncated] = useState(false);
  const [buildingsCount, setBuildingsCount] = useState(0);
  const [selected, setSelected] = useState<Record<string, unknown> | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const refreshBuildings = useCallback(async () => {
    const map = mapRef.current;
    if (!map || !map.getSource("buildings")) return;
    const bounds = map.getBounds();
    try {
      const data = await api.buildings(
        [bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()],
        5000
      );
      (map.getSource("buildings") as maplibregl.GeoJSONSource).setData(
        data as unknown as GeoJSON.FeatureCollection
      );
      setBuildingsTruncated(data.truncated);
      setBuildingsCount(data.features.length);
    } catch {
      // Viewport too large / API unreachable -- leave the last good data in place.
    }
  }, []);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: BASE_STYLE,
      center: STUDY_AREA_CENTER,
      zoom: STUDY_AREA_ZOOM,
    });
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl(), "top-right");

    map.on("load", async () => {
      try {
        // The training/test samples (~2.7 MB) are off by default, so they are fetched only when switched on.
        const [boundary, facilities, raster] = await Promise.all([
          api.boundary(),
          api.facilities(),
          // Optional: the rest of the map still works if the PNG has not been generated or synced yet.
          api.susceptibilityRaster().catch(() => null),
        ]);

        map.addSource("boundary", { type: "geojson", data: boundary as unknown as GeoJSON.FeatureCollection });
        map.addLayer({
          id: "boundary-line",
          type: "line",
          source: "boundary",
          paint: { "line-color": "#18181b", "line-width": 1.5 },
        });

        // The 250 m map is one pre-coloured PNG (scripts/make_susceptibility_png.py), drawn under the boundary.
        if (raster) {
          map.addSource("susceptibility-raster", {
            type: "image",
            url: api.susceptibilityRasterUrl(),
            coordinates: raster.coordinates as [
              [number, number], [number, number], [number, number], [number, number],
            ],
          });
          map.addLayer(
            {
              id: "susceptibility-raster",
              type: "raster",
              source: "susceptibility-raster",
              paint: { "raster-opacity": 0.75, "raster-resampling": "nearest", "raster-fade-duration": 0 },
            },
            "boundary-line"
          );
        }

        map.addSource("susceptibility", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
        map.addLayer({
          id: "susceptibility-points",
          type: "circle",
          source: "susceptibility",
          layout: { visibility: "none" },
          paint: {
            "circle-radius": 3.5,
            "circle-color": [
              "case",
              ["==", ["get", "heldout_score"], null],
              "#a1a1aa", // no held-out score (embargoed row) -- shown but greyed out
              // Same bins as the map; "step" puts a score exactly on an edge in the upper class, which only differs
              // from the report's (a, b] bins for scores of exactly 0.2/0.4/0.6/0.8.
              [
                "step",
                ["coalesce", ["get", "heldout_score"], 0],
                SUSCEPTIBILITY_CLASSES[0].color,
                ...CLASS_EDGES.flatMap((edge, i) => [edge, SUSCEPTIBILITY_CLASSES[i + 1].color]),
              ],
            ],
            "circle-opacity": 0.75,
            "circle-stroke-width": 0,
          },
        });

        map.addSource("buildings", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
        map.addLayer(
          {
            id: "buildings-fill",
            type: "fill",
            source: "buildings",
            paint: { "fill-color": "#9333ea", "fill-opacity": 0.45 },
          },
          "susceptibility-points"
        );

        map.addSource("facilities", {
          type: "geojson",
          data: facilities as unknown as GeoJSON.FeatureCollection,
        });
        const colorExpr = [
          "match",
          ["get", "fclass"],
          ...Object.entries(FACILITY_CATEGORY_COLORS).flat(),
          DEFAULT_FACILITY_COLOR,
        ] as unknown as maplibregl.ExpressionSpecification;
        map.addLayer({
          id: "facilities-points",
          type: "circle",
          source: "facilities",
          paint: {
            "circle-radius": 4.5,
            "circle-color": colorExpr,
            "circle-stroke-width": 1,
            "circle-stroke-color": "#ffffff",
          },
        });

        // A raster has no features to click, so a click that misses every vector layer asks the API for the
        // score of the nearest grid cell.
        const vectorLayers = ["susceptibility-points", "facilities-points", "buildings-fill"];
        map.on("click", async (e) => {
          if (!map.getLayer("susceptibility-raster")) return;
          if (map.getLayoutProperty("susceptibility-raster", "visibility") === "none") return;
          if (map.queryRenderedFeatures(e.point, { layers: vectorLayers }).length) return;
          try {
            const cell = await api.susceptibilityAt(+e.lngLat.lng.toFixed(5), +e.lngLat.lat.toFixed(5));
            setSelected({ layer: "Susceptibility map (250m grid)", ...cell });
          } catch {
            // Outside the study area.
          }
        });
        map.on("click", "susceptibility-points", (e) => {
          const f = e.features?.[0];
          if (f) setSelected({ layer: "Susceptibility sample", ...f.properties });
        });
        map.on("click", "facilities-points", (e) => {
          const f = e.features?.[0];
          if (f) setSelected({ layer: "Facility", ...f.properties });
        });
        map.on("click", "buildings-fill", (e) => {
          const f = e.features?.[0];
          if (f) setSelected({ layer: "Building", ...f.properties });
        });
        for (const id of vectorLayers) {
          map.on("mouseenter", id, () => (map.getCanvas().style.cursor = "pointer"));
          map.on("mouseleave", id, () => (map.getCanvas().style.cursor = ""));
        }

        map.on("moveend", refreshBuildings);
        refreshBuildings();
      } catch (e) {
        setLoadError(e instanceof Error ? e.message : String(e));
      }
    });

    return () => {
      map.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const samplesLoaded = useRef(false);
  useEffect(() => {
    const map = mapRef.current;
    if (!layers.susceptibility || samplesLoaded.current || !map?.getSource("susceptibility")) return;
    samplesLoaded.current = true;
    api
      .susceptibility()
      .then((data) =>
        (map.getSource("susceptibility") as maplibregl.GeoJSONSource).setData(
          data as unknown as GeoJSON.FeatureCollection
        )
      )
      .catch((e) => {
        samplesLoaded.current = false;
        setLoadError(e instanceof Error ? e.message : String(e));
      });
  }, [layers.susceptibility]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const visibility = (on: boolean) => (on ? "visible" : "none");
    if (map.getLayer("boundary-line")) map.setLayoutProperty("boundary-line", "visibility", visibility(layers.boundary));
    if (map.getLayer("susceptibility-raster"))
      map.setLayoutProperty("susceptibility-raster", "visibility", visibility(layers.susceptibilityGrid));
    if (map.getLayer("susceptibility-points"))
      map.setLayoutProperty("susceptibility-points", "visibility", visibility(layers.susceptibility));
    if (map.getLayer("facilities-points"))
      map.setLayoutProperty("facilities-points", "visibility", visibility(layers.facilities));
    if (map.getLayer("buildings-fill")) map.setLayoutProperty("buildings-fill", "visibility", visibility(layers.buildings));
  }, [layers]);

  return (
    <div className="relative h-full w-full">
      <div ref={containerRef} className="h-full w-full" />

      <div className="absolute left-3 top-3 w-64 rounded-lg border border-zinc-200 bg-white/95 p-3 text-sm shadow-lg backdrop-blur dark:border-zinc-800 dark:bg-zinc-900/95">
        <h3 className="mb-2 font-semibold">Layers</h3>
        {(
          [
            ["boundary", "Study area boundary"],
            ["susceptibilityGrid", "Susceptibility map (250m grid)"],
            ["susceptibility", "Susceptibility samples (training/test points)"],
            ["facilities", "Critical facilities"],
            ["buildings", "Buildings (viewport-limited)"],
          ] as const
        ).map(([key, label]) => (
          <label key={key} className="flex items-center gap-2 py-0.5">
            <input
              type="checkbox"
              checked={layers[key]}
              onChange={(e) => setLayers((prev) => ({ ...prev, [key]: e.target.checked }))}
            />
            {label}
          </label>
        ))}
        {layers.susceptibilityGrid && (
          <div className="mt-2 text-xs text-zinc-500">
            <p className="mb-1 font-medium text-zinc-600 dark:text-zinc-300">Susceptibility class (calibrated score)</p>
            {SUSCEPTIBILITY_CLASSES.map((c) => (
              <div key={c.label} className="flex items-center gap-2 py-px">
                <span className="inline-block h-3 w-4 rounded-sm" style={{ background: c.color }} />
                <span className="w-16">{c.label}</span>
                <span className="text-zinc-400">{c.range}</span>
              </div>
            ))}
            <p className="mt-1">Click the map for the score of a 250 m cell.</p>
          </div>
        )}
        {layers.buildings && (
          <p className="mt-1 text-xs text-zinc-500">
            Showing {buildingsCount.toLocaleString()} buildings in view
            {buildingsTruncated ? " (capped — zoom in for all)" : ""}.
          </p>
        )}
        <p className="mt-2 border-t border-zinc-200 pt-2 text-xs text-zinc-500 dark:border-zinc-800">
          Susceptibility map is 250m-resolution and relative (not calibrated to real-world
          prevalence). Forecast rainfall and live impact per tambon are on the Early Warning
          page.
        </p>
      </div>

      {loadError && (
        <div className="absolute left-3 bottom-3 rounded-lg border border-red-200 bg-red-50 p-3 text-xs text-red-700 shadow-lg dark:border-red-900 dark:bg-red-950 dark:text-red-300">
          Failed to load map data: {loadError}
        </div>
      )}

      {selected && (
        <div className="absolute right-3 bottom-3 max-h-64 w-80 overflow-auto rounded-lg border border-zinc-200 bg-white/95 p-3 text-xs shadow-lg backdrop-blur dark:border-zinc-800 dark:bg-zinc-900/95">
          <div className="mb-1 flex items-center justify-between">
            <span className="font-semibold">{String(selected.layer)}</span>
            <button className="text-zinc-400 hover:text-zinc-700" onClick={() => setSelected(null)}>
              ✕
            </button>
          </div>
          <pre className="whitespace-pre-wrap font-mono">
            {JSON.stringify(
              Object.fromEntries(Object.entries(selected).filter(([k]) => k !== "layer")),
              null,
              2
            )}
          </pre>
        </div>
      )}
    </div>
  );
}
