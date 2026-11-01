"use client";

import { useEffect, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import type { Map as MapLibreMap } from "maplibre-gl";
import type { FeatureCollection } from "geojson";
import "maplibre-gl/dist/maplibre-gl.css";
import { Protocol } from "pmtiles";
import { ChevronDown, Layers as LayersIcon, List, MapPin, TriangleAlert, X } from "lucide-react";
import { api } from "@/lib/api";

// Served from public/ (copied there by scripts/copy-maplibre-worker.mjs): the bundle does not ship the worker.
maplibregl.setWorkerUrl("/maplibre-gl-worker.mjs");

// Buildings come as one PMTiles archive read with HTTP range requests (scripts/make_buildings_tiles.sh).
const pmtilesProtocol = new Protocol();
maplibregl.addProtocol("pmtiles", pmtilesProtocol.tile);
const BUILDINGS_MIN_ZOOM = 12;

const OSM_ATTRIBUTION = '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

// OpenStreetMap standard tiles: no API key, attribution required, fine for a low-traffic project site under the OSM
// tile usage policy. In the dark theme the same tiles are drawn with inverted brightness (see DARK_BASEMAP), so no
// second tile service is needed.
const BASE_STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: {
    osm: {
      type: "raster",
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      maxzoom: 19,
      attribution: OSM_ATTRIBUTION,
    },
  },
  layers: [{ id: "basemap", type: "raster", source: "osm" }],
};

// Swapping min/max brightness inverts the tiles; hue-rotate 180 puts water back to blue and land to grey.
const LIGHT_BASEMAP = { "raster-brightness-min": 0, "raster-brightness-max": 1, "raster-saturation": 0, "raster-hue-rotate": 0, "raster-contrast": 0 };
const DARK_BASEMAP = { "raster-brightness-min": 0.92, "raster-brightness-max": 0.08, "raster-saturation": -0.55, "raster-hue-rotate": 180, "raster-contrast": 0.1 };

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

// Facility groups, coloured away from the blue susceptibility ramp so the points stay readable on top of it.
const FACILITY_GROUPS: Array<{ label: string; color: string; classes: string[] }> = [
  { label: "Health", color: "#dc2626", classes: ["hospital", "clinic", "doctors", "dentist", "pharmacy", "nursing_home", "veterinary"] },
  { label: "Education", color: "#d97706", classes: ["school", "college", "university", "kindergarten"] },
  { label: "Emergency", color: "#db2777", classes: ["fire_station", "police"] },
  { label: "Civic", color: "#7c3aed", classes: ["townhall", "community_centre", "courthouse", "embassy", "post_office"] },
  { label: "Transport", color: "#059669", classes: ["railway_station", "railway_halt", "bus_station", "airport", "airfield", "ferry_terminal"] },
];
const OTHER_FACILITY = { label: "Other", color: "#78716c" };
const BUILDING_COLOR = "#9333ea";

interface Layers {
  boundary: boolean;
  susceptibilityGrid: boolean;
  susceptibility: boolean;
  facilities: boolean;
  buildings: boolean;
}

const LAYER_ROWS: Array<{ key: keyof Layers; label: string; hint?: string }> = [
  { key: "susceptibilityGrid", label: "Susceptibility map", hint: "250 m grid, calibrated score" },
  { key: "facilities", label: "Critical facilities", hint: "OSM, 3,895 points" },
  { key: "buildings", label: "Buildings", hint: "426,519 footprints, visible from town scale" },
  { key: "susceptibility", label: "Training / test samples", hint: "Held-out score per point" },
  { key: "boundary", label: "Province boundaries" },
];

const VECTOR_LAYERS = ["susceptibility-points", "facilities-points", "buildings-fill"];

interface Selection {
  title: string;
  rows: Array<[string, string]>;
}

const FIELD_LABELS: Record<string, string> = {
  calibrated_probability: "Calibrated score",
  susceptibility_class: "Class",
  heldout_score: "Held-out score",
  relative_score_class: "Score class",
  event_date: "Event date",
  landslide: "Label",
  split: "Split",
  fclass: "Type",
  name: "Name",
  osm_id: "OSM id",
  id: "Id",
  lon: "Longitude",
  lat: "Latitude",
};

function formatValue(key: string, value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (key === "landslide") return Number(value) === 1 ? "Landslide" : "Non-landslide";
  if (typeof value === "number") return Number.isInteger(value) ? value.toLocaleString() : value.toFixed(key === "lon" || key === "lat" ? 4 : 3);
  return String(value).replace(/_/g, " ");
}

function toRows(props: Record<string, unknown>): Array<[string, string]> {
  return Object.entries(props).map(([k, v]) => [FIELD_LABELS[k] ?? k.replace(/_/g, " "), formatValue(k, v)]);
}

function isDark() {
  return document.documentElement.classList.contains("dark");
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
  const [panelOpen, setPanelOpen] = useState(true);
  const [legendOpen, setLegendOpen] = useState(true);
  const [zoom, setZoom] = useState(STUDY_AREA_ZOOM);
  const [rasterAvailable, setRasterAvailable] = useState(true);
  const [selected, setSelected] = useState<Selection | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: BASE_STYLE,
      center: STUDY_AREA_CENTER,
      zoom: STUDY_AREA_ZOOM,
      attributionControl: { compact: true },
    });
    mapRef.current = map;
    map.on("zoomend", () => setZoom(map.getZoom()));
    map.addControl(new maplibregl.NavigationControl({ visualizePitch: false }), "top-right");
    map.addControl(new maplibregl.ScaleControl({ maxWidth: 120 }), "bottom-left");

    // Swap the basemap with the page theme.
    const syncBasemap = () => {
      if (!map.getLayer("basemap")) return;
      for (const [prop, value] of Object.entries(isDark() ? DARK_BASEMAP : LIGHT_BASEMAP)) {
        map.setPaintProperty("basemap", prop as "raster-saturation", value);
      }
    };
    const themeObserver = new MutationObserver(syncBasemap);
    themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });

    map.on("load", async () => {
      syncBasemap();
      try {
        const [boundary, facilities, raster] = await Promise.all([
          api.boundary(),
          api.facilities(),
          // Optional: the rest of the map still works if the PNG has not been generated or synced yet.
          api.susceptibilityRaster().catch(() => null),
        ]);

        map.addSource("boundary", { type: "geojson", data: boundary as unknown as FeatureCollection });
        map.addLayer({
          id: "boundary-line",
          type: "line",
          source: "boundary",
          paint: { "line-color": "#334155", "line-width": ["interpolate", ["linear"], ["zoom"], 6, 0.8, 10, 1.6], "line-opacity": 0.8 },
        });

        // The 250 m map is one pre-coloured PNG (scripts/make_susceptibility_png.py), drawn under the boundary.
        if (raster) {
          map.addSource("susceptibility-raster", {
            type: "image",
            url: api.susceptibilityRasterUrl(raster.version),
            coordinates: raster.coordinates as [
              [number, number], [number, number], [number, number], [number, number],
            ],
          });
          map.addLayer(
            {
              id: "susceptibility-raster",
              type: "raster",
              source: "susceptibility-raster",
              paint: { "raster-opacity": 0.8, "raster-resampling": "nearest", "raster-fade-duration": 0 },
            },
            "boundary-line"
          );
        } else {
          setRasterAvailable(false);
        }

        map.addSource("susceptibility", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
        map.addLayer({
          id: "susceptibility-points",
          type: "circle",
          source: "susceptibility",
          layout: { visibility: "none" },
          paint: {
            "circle-radius": ["interpolate", ["linear"], ["zoom"], 6, 2.5, 12, 6],
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
            "circle-stroke-width": 0.75,
            "circle-stroke-color": "#ffffff",
          },
        });

        // PMTiles needs an absolute URL; the API may be same-origin ("").
        map.addSource("buildings", {
          type: "vector",
          url: `pmtiles://${new URL(api.buildingsTilesUrl(), window.location.href).href}`,
        });
        map.addLayer(
          {
            id: "buildings-fill",
            type: "fill",
            source: "buildings",
            "source-layer": "buildings",
            minzoom: BUILDINGS_MIN_ZOOM,
            paint: { "fill-color": BUILDING_COLOR, "fill-opacity": 0.55, "fill-outline-color": BUILDING_COLOR },
          },
          "susceptibility-points"
        );

        map.addSource("facilities", {
          type: "geojson",
          data: facilities as unknown as FeatureCollection,
        });
        const colorExpr = [
          "match",
          ["get", "fclass"],
          ...FACILITY_GROUPS.flatMap((g) => [g.classes, g.color]),
          OTHER_FACILITY.color,
        ] as unknown as maplibregl.ExpressionSpecification;
        map.addLayer({
          id: "facilities-points",
          type: "circle",
          source: "facilities",
          paint: {
            "circle-radius": ["interpolate", ["linear"], ["zoom"], 6, 2.2, 10, 4.5, 14, 7],
            "circle-color": colorExpr,
            "circle-stroke-width": ["interpolate", ["linear"], ["zoom"], 6, 0.5, 12, 1.25],
            "circle-stroke-color": "#ffffff",
          },
        });

        map.on("click", "susceptibility-points", (e) => {
          const f = e.features?.[0];
          if (f) setSelected({ title: "Training / test sample", rows: toRows(f.properties) });
        });
        map.on("click", "facilities-points", (e) => {
          const f = e.features?.[0];
          if (f) setSelected({ title: "Critical facility", rows: toRows(f.properties) });
        });
        map.on("click", "buildings-fill", (e) => {
          const f = e.features?.[0];
          if (f) setSelected({ title: "Building", rows: toRows(f.properties) });
        });
        // A raster has no features to click, so a click that misses every vector layer asks the API for the
        // score of the nearest grid cell.
        map.on("click", async (e) => {
          if (!map.getLayer("susceptibility-raster")) return;
          if (map.getLayoutProperty("susceptibility-raster", "visibility") === "none") return;
          if (map.queryRenderedFeatures(e.point, { layers: VECTOR_LAYERS.filter((id) => map.getLayer(id)) }).length) return;
          try {
            const cell = await api.susceptibilityAt(+e.lngLat.lng.toFixed(5), +e.lngLat.lat.toFixed(5));
            setSelected({ title: "Susceptibility cell (250 m)", rows: toRows(cell) });
          } catch {
            setSelected(null); // outside the study area
          }
        });
        for (const id of VECTOR_LAYERS) {
          map.on("mouseenter", id, () => (map.getCanvas().style.cursor = "pointer"));
          map.on("mouseleave", id, () => (map.getCanvas().style.cursor = ""));
        }

      } catch (e) {
        setLoadError(e instanceof Error ? e.message : String(e));
      }
    });

    return () => {
      themeObserver.disconnect();
      map.remove();
      mapRef.current = null;
    };
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
          data as unknown as FeatureCollection
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
    const set = (id: string, on: boolean) => map.getLayer(id) && map.setLayoutProperty(id, "visibility", visibility(on));
    set("boundary-line", layers.boundary);
    set("susceptibility-raster", layers.susceptibilityGrid);
    set("susceptibility-points", layers.susceptibility);
    set("facilities-points", layers.facilities);
    set("buildings-fill", layers.buildings);
  }, [layers]);

  const legendEmpty = !layers.susceptibilityGrid && !layers.susceptibility && !layers.facilities && !layers.buildings;

  return (
    <div className="relative h-full w-full">
      <div ref={containerRef} className="h-full w-full" />

      {/* Layers */}
      <div className="map-panel absolute left-3 top-3 w-[min(17rem,calc(100%-1.5rem))]">
        <button
          type="button"
          onClick={() => setPanelOpen((o) => !o)}
          className="flex w-full items-center justify-between px-4 py-3"
          aria-expanded={panelOpen}
        >
          <span className="flex items-center gap-2 font-semibold"><LayersIcon className="h-4 w-4 text-accent" aria-hidden />Layers</span>
          <Chevron open={panelOpen} />
        </button>
        {panelOpen && (
          <div className="space-y-0.5 border-t border-line px-2 py-2">
            {LAYER_ROWS.map(({ key, label, hint }) => (
              <label
                key={key}
                className="flex cursor-pointer items-start gap-3 rounded-lg px-2 py-1.5 hover:bg-surface-2"
              >
                <input
                  type="checkbox"
                  className="peer sr-only"
                  checked={layers[key]}
                  onChange={(e) => setLayers((prev) => ({ ...prev, [key]: e.target.checked }))}
                />
                <span
                  aria-hidden
                  className={`relative mt-0.5 h-4 w-7 shrink-0 rounded-full transition-colors peer-focus-visible:ring-2 peer-focus-visible:ring-accent ${
                    layers[key] ? "bg-accent" : "bg-line"
                  }`}
                >
                  <span
                    className={`absolute top-0.5 h-3 w-3 rounded-full bg-white shadow transition-all ${
                      layers[key] ? "left-3.5" : "left-0.5"
                    }`}
                  />
                </span>
                <span className="leading-tight">
                  <span className="block font-medium">{label}</span>
                  {hint && <span className="text-xs text-muted">{hint}</span>}
                </span>
              </label>
            ))}
            {layers.buildings && zoom < BUILDINGS_MIN_ZOOM && (
              <p className="px-2 pt-1 text-xs text-muted">Zoom in to a town to see building footprints.</p>
            )}
            {layers.susceptibilityGrid && !rasterAvailable && (
              <p className="px-2 pt-1 text-xs text-muted">The susceptibility map is not available on this server yet.</p>
            )}
          </div>
        )}
      </div>

      {/* Legend */}
      {!legendEmpty && (
        <div className="map-panel absolute bottom-8 right-3 w-[min(15rem,calc(100%-1.5rem))]">
          <button
            type="button"
            onClick={() => setLegendOpen((o) => !o)}
            className="flex w-full items-center justify-between px-4 py-2.5"
            aria-expanded={legendOpen}
          >
            <span className="flex items-center gap-2 font-semibold"><List className="h-4 w-4 text-accent" aria-hidden />Legend</span>
            <Chevron open={legendOpen} />
          </button>
          {legendOpen && (
            <div className="max-h-[calc(100dvh-16rem)] space-y-3 overflow-y-auto border-t border-line px-4 py-3 text-xs">
              {(layers.susceptibilityGrid || layers.susceptibility) && (
                <LegendSection title="Susceptibility (calibrated score)">
                  {SUSCEPTIBILITY_CLASSES.map((c) => (
                    <LegendRow key={c.label} swatch={<Swatch color={c.color} />} label={c.label} note={c.range} />
                  ))}
                  {layers.susceptibility && (
                    <LegendRow swatch={<Swatch color="#a1a1aa" round />} label="Sample with no held-out score" />
                  )}
                </LegendSection>
              )}
              {layers.facilities && (
                <LegendSection title="Critical facilities" columns>
                  {[...FACILITY_GROUPS, OTHER_FACILITY].map((g) => (
                    <LegendRow key={g.label} swatch={<Swatch color={g.color} round />} label={g.label} />
                  ))}
                </LegendSection>
              )}
              {layers.buildings && (
                <LegendSection title="Exposure">
                  <LegendRow swatch={<Swatch color={BUILDING_COLOR} />} label="Building footprint" />
                </LegendSection>
              )}
              <p className="leading-snug text-subtle">
                Relative susceptibility, not calibrated to real-world prevalence. Click the map for a cell&apos;s score.
              </p>
            </div>
          )}
        </div>
      )}

      {/* Details of the clicked feature */}
      {selected && (
        <div className="map-panel absolute right-14 top-3 w-[min(18rem,calc(100%-5rem))]">
          <div className="flex items-center justify-between px-4 py-2.5">
            <span className="flex items-center gap-2 font-semibold"><MapPin className="h-4 w-4 text-accent" aria-hidden />{selected.title}</span>
            <button
              type="button"
              className="rounded p-1 text-muted hover:bg-surface-2 hover:text-fg"
              onClick={() => setSelected(null)}
              aria-label="Close details"
            >
              <X className="h-4 w-4" aria-hidden />
            </button>
          </div>
          <dl className="max-h-64 overflow-y-auto border-t border-line px-4 py-2 text-xs">
            {selected.rows.map(([k, v]) => (
              <div key={k} className="flex justify-between gap-4 py-1">
                <dt className="capitalize text-muted">{k}</dt>
                <dd className="text-right font-medium capitalize tabular-nums">{v}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}

      {loadError && (
        <div className="note-danger absolute left-1/2 top-3 flex -translate-x-1/2 items-center gap-2 text-xs shadow-lg">
          <TriangleAlert className="h-4 w-4 shrink-0" aria-hidden />
          Failed to load map data: {loadError}
        </div>
      )}
    </div>
  );
}

function Chevron({ open }: { open: boolean }) {
  return <ChevronDown className={`h-4 w-4 text-muted transition-transform ${open ? "" : "-rotate-90"}`} aria-hidden />;
}

function LegendSection({ title, columns = false, children }: { title: string; columns?: boolean; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-1.5 font-medium text-fg">{title}</div>
      <div className={columns ? "grid grid-cols-2 gap-x-3 gap-y-1" : "space-y-1"}>{children}</div>
    </div>
  );
}

function LegendRow({ swatch, label, note }: { swatch: React.ReactNode; label: string; note?: string }) {
  return (
    <div className="flex items-center gap-2">
      {swatch}
      <span className="flex-1 text-muted">{label}</span>
      {note && <span className="tabular-nums text-subtle">{note}</span>}
    </div>
  );
}

function Swatch({ color, round = false }: { color: string; round?: boolean }) {
  return (
    <span
      className={`inline-block shrink-0 border border-black/10 ${round ? "h-2.5 w-2.5 rounded-full" : "h-3 w-4 rounded-sm"}`}
      style={{ background: color }}
    />
  );
}
