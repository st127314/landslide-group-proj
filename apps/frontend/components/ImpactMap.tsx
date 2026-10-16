"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import * as maplibregl from "maplibre-gl";
import type { Map as MapLibreMap } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { api } from "@/lib/api";

// Public, no-API-key basemap style maintained by the MapLibre project --
// fine for this scaffold; swap for your own style/tile source in production.
const BASE_STYLE = "https://demotiles.maplibre.org/style.json";

const STUDY_AREA_CENTER: [number, number] = [100.0, 8.2];
const STUDY_AREA_ZOOM = 6.3;

const SCORE_COLOR_STOPS: Array<[number, string]> = [
  [0, "#2563eb"], // low susceptibility
  [0.4, "#eab308"],
  [0.6, "#f97316"],
  [0.8, "#dc2626"],
  [1, "#7f1d1d"], // very high
];

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
  const [gridTruncated, setGridTruncated] = useState(false);
  const [gridCount, setGridCount] = useState(0);
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

  const refreshSusceptibilityGrid = useCallback(async () => {
    const map = mapRef.current;
    if (!map || !map.getSource("susceptibility-grid")) return;
    const bounds = map.getBounds();
    try {
      const data = await api.susceptibilityGrid(
        [bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()],
        8000
      );
      (map.getSource("susceptibility-grid") as maplibregl.GeoJSONSource).setData(
        data as unknown as GeoJSON.FeatureCollection
      );
      setGridTruncated(data.truncated);
      setGridCount(data.features.length);
    } catch {
      // Viewport too large / API unreachable (e.g. map not built yet) -- leave last good data.
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
        const [boundary, susceptibility, facilities] = await Promise.all([
          api.boundary(),
          api.susceptibility(),
          api.facilities(),
        ]);

        map.addSource("boundary", { type: "geojson", data: boundary as unknown as GeoJSON.FeatureCollection });
        map.addLayer({
          id: "boundary-line",
          type: "line",
          source: "boundary",
          paint: { "line-color": "#18181b", "line-width": 1.5 },
        });

        map.addSource("susceptibility-grid", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
        map.addLayer(
          {
            id: "susceptibility-grid-points",
            type: "circle",
            source: "susceptibility-grid",
            paint: {
              "circle-radius": 5,
              "circle-blur": 0.6,
              "circle-color": [
                "interpolate", ["linear"], ["get", "calibrated_probability"],
                ...SCORE_COLOR_STOPS.flat(),
              ],
              "circle-opacity": 0.55,
            },
          },
          "boundary-line"
        );

        map.addSource("susceptibility", {
          type: "geojson",
          data: susceptibility as unknown as GeoJSON.FeatureCollection,
        });
        map.addLayer({
          id: "susceptibility-points",
          type: "circle",
          source: "susceptibility",
          paint: {
            "circle-radius": 3.5,
            "circle-color": [
              "case",
              ["==", ["get", "heldout_score"], null],
              "#a1a1aa", // no held-out score (embargoed row) -- shown but greyed out
              [
                "interpolate",
                ["linear"],
                ["coalesce", ["get", "heldout_score"], 0],
                ...SCORE_COLOR_STOPS.flat(),
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

        map.on("click", "susceptibility-grid-points", (e) => {
          const f = e.features?.[0];
          if (f) setSelected({ layer: "Susceptibility map (250m grid)", ...f.properties });
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
        for (const id of ["susceptibility-grid-points", "susceptibility-points", "facilities-points", "buildings-fill"]) {
          map.on("mouseenter", id, () => (map.getCanvas().style.cursor = "pointer"));
          map.on("mouseleave", id, () => (map.getCanvas().style.cursor = ""));
        }

        map.on("moveend", refreshBuildings);
        map.on("moveend", refreshSusceptibilityGrid);
        refreshBuildings();
        refreshSusceptibilityGrid();
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

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const visibility = (on: boolean) => (on ? "visible" : "none");
    if (map.getLayer("boundary-line")) map.setLayoutProperty("boundary-line", "visibility", visibility(layers.boundary));
    if (map.getLayer("susceptibility-grid-points"))
      map.setLayoutProperty("susceptibility-grid-points", "visibility", visibility(layers.susceptibilityGrid));
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
          <p className="mt-2 text-xs text-zinc-500">
            Showing {gridCount.toLocaleString()} of ~1.14M grid points in view
            {gridTruncated ? " (capped — zoom in for all)" : ""}.
          </p>
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
