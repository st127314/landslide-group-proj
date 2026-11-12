"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import type { Map as MapLibreMap } from "maplibre-gl";
import type { FeatureCollection } from "geojson";
import "maplibre-gl/dist/maplibre-gl.css";
import { Protocol } from "pmtiles";
import { ChartNoAxesColumn, ChevronDown, Layers as LayersIcon, List, MapPin, MapPinned, Search, TriangleAlert, X } from "lucide-react";
import ImpactCharts, { RainOutlook } from "@/components/ImpactCharts";
import { ageLabel, isStale } from "@/lib/time";
import { api, type ImpactOverlay, type OverlayTambon, type ScenarioResult, type TambonClasses } from "@/lib/api";

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
const SUSCEPTIBILITY_CLASSES: Array<{ key: string; label: string; range: string; color: string }> = [
  { key: "very_low", label: "Very low", range: "≤ 0.2", color: "#cde2fb" },
  { key: "low", label: "Low", range: "0.2–0.4", color: "#86b6ef" },
  { key: "moderate", label: "Moderate", range: "0.4–0.6", color: "#2a78d6" },
  { key: "high", label: "High", range: "0.6–0.8", color: "#1c5cab" },
  { key: "very_high", label: "Very high", range: "> 0.8", color: "#104281" },
];

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

// Tambon risk layer. Each mode colours tambons by one value held in the feature state (set from the impact overlay,
// or from a what-if scenario). The classes and their order follow scripts/build_impact_overlay.py.
type ColourBy = "impact" | "tier" | "rain";
interface TambonClass {
  key: string;
  label: string;
  note?: string;
  color: string;
}
const TAMBON_MODES: Record<ColourBy, { label: string; legend: string; state: string; classes: TambonClass[] }> = {
  impact: {
    label: "Impact",
    legend: "Live impact (terrain × rain)",
    state: "impact",
    classes: [
      // #b91c1c, not the brighter #dc2626: it stays clearly apart from the orange for every kind of colour vision.
      { key: "very_high", label: "Very high", color: "#b91c1c" },
      { key: "high", label: "High", color: "#f97316" },
      { key: "moderate", label: "Moderate", color: "#facc15" },
      { key: "low", label: "Low", note: "not shaded", color: "transparent" },
      { key: "not_assessed", label: "Not assessed", color: "#9ca3af" },
    ],
  },
  tier: {
    label: "Terrain",
    legend: "Terrain tier (share of cells high or very high)",
    state: "tier",
    classes: [
      { key: "high", label: "High", note: "≥ 40%", color: "#104281" },
      { key: "moderate", label: "Moderate", note: "15–40%", color: "#2a78d6" },
      { key: "low", label: "Low", note: "< 15%", color: "#86b6ef" },
      { key: "no_data", label: "No data", color: "#9ca3af" },
    ],
  },
  rain: {
    label: "Rain",
    legend: "24 h rain against the tambon's own climate",
    state: "rain",
    classes: [
      { key: "above_p95", label: "Above P95", color: "#5b21b6" },
      { key: "p90_p95", label: "P90–P95", color: "#8b5cf6" },
      { key: "p75_p90", label: "P75–P90", color: "#c4b5fd" },
      { key: "below_p75", label: "Below P75", color: "#ede9fe" },
    ],
  },
};
const IMPACT_ORDER = ["very_high", "high", "moderate", "low", "not_assessed"];
const WHAT_IF_MAX_MM = 200;

function tambonFill(mode: ColourBy): maplibregl.ExpressionSpecification {
  const { state, classes } = TAMBON_MODES[mode];
  return [
    "match",
    ["coalesce", ["feature-state", state], ""],
    ...classes.filter((c) => c.color !== "transparent").flatMap((c) => [c.key, c.color]),
    "rgba(0,0,0,0)",
  ] as unknown as maplibregl.ExpressionSpecification;
}

function classLabel(mode: ColourBy, key: string | null | undefined): string {
  return TAMBON_MODES[mode].classes.find((c) => c.key === key)?.label ?? "—";
}

interface Layers {
  tambons: boolean;
  boundary: boolean;
  susceptibilityGrid: boolean;
  susceptibility: boolean;
  facilities: boolean;
  buildings: boolean;
}

const LAYER_ROWS: Array<{ key: keyof Layers; label: string; hint?: string }> = [
  { key: "tambons", label: "Tambon risk", hint: "1,055 sub-districts" },
  { key: "susceptibilityGrid", label: "Susceptibility map", hint: "250 m grid, calibrated score" },
  { key: "facilities", label: "Facilities", hint: "OSM, 3,895 points" },
  { key: "buildings", label: "Buildings", hint: "426,519 footprints" },
  { key: "susceptibility", label: "Training / test samples", hint: "Held-out score per point" },
  { key: "boundary", label: "Province boundaries" },
];

const VECTOR_LAYERS = ["susceptibility-points", "facilities-points", "buildings-fill"];

interface Cell {
  calibrated_probability: number;
  susceptibility_class: string | null;
}
type Selection =
  | { kind: "feature"; title: string; rows: Array<[string, string]> }
  | { kind: "tambon"; gid: string; cell?: Cell }
  | { kind: "cell"; cell: Cell & { lon: number; lat: number } };

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
  const text = String(value).replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function toRows(props: Record<string, unknown>): Array<[string, string]> {
  return Object.entries(props).map(([k, v]) => [FIELD_LABELS[k] ?? k.replace(/_/g, " "), formatValue(k, v)]);
}

const mm = (v: number | null | undefined, digits = 1) => (v === null || v === undefined ? "—" : `${v.toFixed(digits)} mm`);
const count = (v: number | null | undefined) => (v ?? 0).toLocaleString();

function isDark() {
  return document.documentElement.classList.contains("dark");
}

function bboxOf(coords: unknown, box: [number, number, number, number]) {
  const c = coords as unknown[];
  if (typeof c[0] === "number") {
    const [x, y] = c as number[];
    box[0] = Math.min(box[0], x);
    box[1] = Math.min(box[1], y);
    box[2] = Math.max(box[2], x);
    box[3] = Math.max(box[3], y);
  } else {
    for (const part of c) bboxOf(part, box);
  }
  return box;
}

export default function ImpactMap() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const [layers, setLayers] = useState<Layers>({
    tambons: true,
    boundary: true,
    susceptibilityGrid: true,
    susceptibility: false,
    facilities: true,
    buildings: true,
  });
  // Panels start collapsed on a phone so the map is not covered.
  const [wide] = useState(() => typeof window === "undefined" || window.innerWidth >= 640);
  // The layer list starts collapsed on a short screen, where the tambon controls need the room.
  const [panelOpen, setPanelOpen] = useState(
    () => typeof window === "undefined" || (window.innerWidth >= 640 && window.innerHeight >= 820)
  );
  const [riskOpen, setRiskOpen] = useState(wide);
  const [legendOpen, setLegendOpen] = useState(wide);
  // The charts sit between the left column and the legend, so they open by default only where that gap is wide.
  const [chartsOpen, setChartsOpen] = useState(
    () => typeof window !== "undefined" && window.innerWidth >= 1280 && window.innerHeight >= 860
  );
  const [zoom, setZoom] = useState(STUDY_AREA_ZOOM);
  const [rasterAvailable, setRasterAvailable] = useState(true);
  const [selected, setSelected] = useState<Selection | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [overlay, setOverlay] = useState<ImpactOverlay | null>(null);
  const [tambonsReady, setTambonsReady] = useState(false);
  const tambonBounds = useRef(new Map<string, [number, number, number, number]>());
  const [colourBy, setColourBy] = useState<ColourBy>("impact");
  const [whatIf, setWhatIf] = useState(false);
  const [whatIfMm, setWhatIfMm] = useState(50);
  const [scenario, setScenario] = useState<(ScenarioResult & { tambon_classes: TambonClasses }) | null>(null);
  const [query, setQuery] = useState("");

  const tambonById = useMemo(() => new Map((overlay?.tambons ?? []).map((t) => [t.GID_3, t])), [overlay]);
  const liveClasses = useMemo(() => {
    const out: TambonClasses = {};
    for (const t of overlay?.tambons ?? []) {
      out[t.GID_3] = [t.live_impact_class, t.rain_local_class_24h ?? null, t.gfs_rain_24h_mm];
    }
    return out;
  }, [overlay]);
  const scenarioActive = whatIf && scenario !== null && scenario.scenario.rain_24h_mm === whatIfMm;
  const classes = scenarioActive ? scenario.tambon_classes : liveClasses;
  const summary = useMemo(() => {
    if (scenarioActive) {
      return { byClass: scenario.summary.tambons_by_impact_class, people: scenario.summary.population_at_elevated_risk };
    }
    const totals = overlay?.metadata.totals;
    return totals ? { byClass: totals.tambons_by_live_impact_class, people: totals.population_at_elevated_risk } : null;
  }, [scenarioActive, scenario, overlay]);
  const searchOptions = useMemo(
    () =>
      (overlay?.tambons ?? [])
        .map((t) => ({ gid: t.GID_3, label: `${t.NAME_3 ?? t.GID_3}, ${t.NAME_2 ?? ""}, ${t.NAME_1 ?? ""}` }))
        .sort((a, b) => a.label.localeCompare(b.label)),
    [overlay]
  );

  // Latest values for the map's click handler, which is registered once.
  const live = useRef({ layers, selected });
  useEffect(() => {
    live.current = { layers, selected };
  }, [layers, selected]);

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
        const [boundary, facilities, raster, tambons, impact] = await Promise.all([
          api.boundary(),
          api.facilities(),
          // Optional layers: the rest of the map still works if one has not been generated or synced yet.
          api.susceptibilityRaster().catch(() => null),
          api.tambons().catch(() => null),
          api.impactOverlay().catch(() => null),
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

        // Tambon polygons carry only ids and names; the risk values are joined by GID_3 through the feature state,
        // so a what-if scenario recolours the map without reloading the geometry.
        if (tambons && impact) {
          for (const f of tambons.features) {
            tambonBounds.current.set(String(f.properties.GID_3), bboxOf(f.geometry.coordinates, [180, 90, -180, -90]));
          }
          map.addSource("tambons", { type: "geojson", data: tambons as unknown as FeatureCollection, promoteId: "GID_3" });
          map.addLayer(
            {
              id: "tambons-fill",
              type: "fill",
              source: "tambons",
              paint: { "fill-color": tambonFill("impact"), "fill-opacity": 0.6 },
            },
            "boundary-line"
          );
          const selectedState: maplibregl.ExpressionSpecification = ["boolean", ["feature-state", "selected"], false];
          map.addLayer(
            {
              id: "tambons-line",
              type: "line",
              source: "tambons",
              paint: {
                "line-color": ["case", selectedState, "#0f172a", "#64748b"],
                "line-width": ["interpolate", ["linear"], ["zoom"], 6, ["case", selectedState, 2, 0.15], 10, ["case", selectedState, 3, 0.9]],
                "line-opacity": ["case", selectedState, 1, 0.6],
              },
            },
            "boundary-line"
          );
          setOverlay(impact);
          setTambonsReady(true);
        }

        map.addSource("susceptibility", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
        map.addLayer({
          id: "susceptibility-points",
          type: "circle",
          source: "susceptibility",
          layout: { visibility: "none" },
          paint: {
            "circle-radius": ["interpolate", ["linear"], ["zoom"], 6, 2.5, 12, 6],
            // The class of each point's own calibrated held-out score (set when the model was evaluated), so a point
            // and the map cell under it use the same class definition; grey = no held-out score (embargoed row).
            "circle-color": [
              "match",
              ["coalesce", ["get", "relative_score_class"], ""],
              ...SUSCEPTIBILITY_CLASSES.flatMap((c) => [c.key, c.color]),
              "#a1a1aa",
            ] as unknown as maplibregl.ExpressionSpecification,
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
          if (f) setSelected({ kind: "feature", title: "Training / test sample", rows: toRows(f.properties) });
        });
        map.on("click", "facilities-points", (e) => {
          const f = e.features?.[0];
          if (f) setSelected({ kind: "feature", title: "Facility", rows: toRows(f.properties) });
        });
        map.on("click", "buildings-fill", (e) => {
          const f = e.features?.[0];
          if (f) setSelected({ kind: "feature", title: "Building", rows: toRows(f.properties) });
        });
        // A click that misses every point and building selects the tambon under it and, because a raster has no
        // features to click, asks the API for the score of the nearest 250 m cell.
        map.on("click", async (e) => {
          if (map.queryRenderedFeatures(e.point, { layers: VECTOR_LAYERS.filter((id) => map.getLayer(id)) }).length) return;
          const shown = live.current.layers;
          const tambon =
            shown.tambons && map.getLayer("tambons-fill")
              ? map.queryRenderedFeatures(e.point, { layers: ["tambons-fill"] })[0]
              : undefined;
          const gid = tambon ? String(tambon.properties.GID_3) : null;
          if (gid) setSelected({ kind: "tambon", gid });
          if (!shown.susceptibilityGrid || !map.getLayer("susceptibility-raster")) {
            if (!gid) setSelected(null);
            return;
          }
          try {
            const cell = await api.susceptibilityAt(+e.lngLat.lng.toFixed(5), +e.lngLat.lat.toFixed(5));
            setSelected(gid ? { kind: "tambon", gid, cell } : { kind: "cell", cell });
          } catch {
            if (!gid) setSelected(null); // outside the study area
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
    set("tambons-fill", layers.tambons);
    set("tambons-line", layers.tambons);
    set("boundary-line", layers.boundary);
    set("susceptibility-raster", layers.susceptibilityGrid);
    set("susceptibility-points", layers.susceptibility);
    set("facilities-points", layers.facilities);
    set("buildings-fill", layers.buildings);
  }, [layers, tambonsReady]);

  // What-if rainfall: the rule is applied by the API, the map only repaints.
  useEffect(() => {
    if (!whatIf) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      api
        .scenarioClasses(whatIfMm, controller.signal)
        .then(setScenario)
        .catch((e) => {
          if ((e as Error).name !== "AbortError") setLoadError(e instanceof Error ? e.message : String(e));
        });
    }, 200);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [whatIf, whatIfMm]);

  // Join the risk values to the polygons.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !tambonsReady) return;
    for (const [gid, [impact, rain]] of Object.entries(classes)) {
      map.setFeatureState({ source: "tambons", id: gid }, { impact, rain: rain ?? "", tier: tambonById.get(gid)?.susceptibility_tier ?? "" });
    }
  }, [classes, tambonById, tambonsReady]);

  useEffect(() => {
    const map = mapRef.current;
    if (map?.getLayer("tambons-fill")) map.setPaintProperty("tambons-fill", "fill-color", tambonFill(colourBy));
  }, [colourBy, tambonsReady]);

  // While the charts are open on a wide screen, treat the strip they cover as padding so the study area stays in view.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !tambonsReady) return;
    const covered = chartsOpen && window.innerWidth >= 1024 ? Math.min(280, Math.round(window.innerHeight * 0.3)) : 0;
    map.easeTo({ padding: { top: 0, right: 0, bottom: covered, left: 0 }, duration: 300 });
  }, [chartsOpen, tambonsReady]);

  const selectedGid = selected?.kind === "tambon" ? selected.gid : null;
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !tambonsReady || !selectedGid) return;
    map.setFeatureState({ source: "tambons", id: selectedGid }, { selected: true });
    return () => {
      if (mapRef.current?.getSource("tambons")) map.setFeatureState({ source: "tambons", id: selectedGid }, { selected: false });
    };
  }, [selectedGid, tambonsReady]);

  const goToTambon = (label: string) => {
    setQuery(label);
    const match = searchOptions.find((o) => o.label === label);
    const box = match && tambonBounds.current.get(match.gid);
    if (!match || !box) return;
    setLayers((prev) => ({ ...prev, tambons: true }));
    setSelected({ kind: "tambon", gid: match.gid });
    mapRef.current?.fitBounds([[box[0], box[1]], [box[2], box[3]]], { padding: 120, maxZoom: 12, duration: 800 });
  };

  const details = selected && describe(selected, tambonById, classes, scenarioActive ? whatIfMm : null);
  const selectedTambon = selectedGid ? tambonById.get(selectedGid) : undefined;
  const mode = TAMBON_MODES[colourBy];
  const legendEmpty =
    !(layers.tambons && tambonsReady) && !layers.susceptibilityGrid && !layers.susceptibility && !layers.facilities && !layers.buildings;

  return (
    <div className="relative h-full w-full">
      <div ref={containerRef} className="h-full w-full" />

      <div className="pointer-events-none absolute bottom-24 left-3 top-3 flex w-[min(17rem,calc(100%-1.5rem))] flex-col gap-3 lg:bottom-10">
        {/* Tambon risk controls */}
        {layers.tambons && tambonsReady && overlay && (
          <div className="map-panel pointer-events-auto flex min-h-11 flex-col overflow-hidden">
            <button
              type="button"
              onClick={() => setRiskOpen((o) => !o)}
              className="flex w-full shrink-0 items-center justify-between px-4 py-3"
              aria-expanded={riskOpen}
            >
              <span className="flex items-center gap-2 font-semibold"><MapPinned className="h-4 w-4 text-accent" aria-hidden />Tambon risk</span>
              <Chevron open={riskOpen} />
            </button>
            {riskOpen && (
              <div className="space-y-3 overflow-y-auto border-t border-line px-4 py-3 text-xs">
                <label className="relative block">
                  <span className="sr-only">Find a tambon</span>
                  <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-subtle" aria-hidden />
                  <input
                    type="search"
                    list="tambon-names"
                    value={query}
                    onChange={(e) => goToTambon(e.target.value)}
                    placeholder="Find a tambon…"
                    className="w-full rounded-lg border border-line bg-surface py-1.5 pl-7 pr-2 text-sm outline-none focus:border-accent"
                  />
                  <datalist id="tambon-names">
                    {searchOptions.map((o) => (
                      <option key={o.gid} value={o.label} />
                    ))}
                  </datalist>
                </label>

                <div>
                  <div className="mb-1 font-medium">Colour tambons by</div>
                  <Segmented
                    options={(Object.keys(TAMBON_MODES) as ColourBy[]).map((k) => ({ value: k, label: TAMBON_MODES[k].label }))}
                    value={colourBy}
                    onChange={setColourBy}
                  />
                </div>

                <div>
                  <div className="mb-1 font-medium">Rainfall</div>
                  <Segmented
                    options={[
                      { value: "live", label: "GFS forecast" },
                      { value: "whatif", label: "What-if" },
                    ]}
                    value={whatIf ? "whatif" : "live"}
                    onChange={(v) => setWhatIf(v === "whatif")}
                  />
                  {whatIf ? (
                    <label className="mt-2 block">
                      <span className="flex justify-between">
                        <span className="text-muted">Rain in 24 h, every tambon</span>
                        <span className="font-semibold tabular-nums">{whatIfMm} mm</span>
                      </span>
                      <input
                        type="range"
                        min={0}
                        max={WHAT_IF_MAX_MM}
                        step={5}
                        value={whatIfMm}
                        onChange={(e) => setWhatIfMm(Number(e.target.value))}
                        className="mt-1 w-full accent-[var(--accent)]"
                      />
                    </label>
                  ) : (
                    <p className="mt-1.5 text-muted">
                      GFS run{" "}
                      {new Date(overlay.metadata.gfs_run_utc).toLocaleString(undefined, {
                        dateStyle: "medium",
                        timeStyle: "short",
                        timeZone: "UTC",
                      })}{" "}
                      UTC ({ageLabel(overlay.metadata.gfs_run_utc)}), next 24 h.
                      {isStale(overlay.metadata.gfs_run_utc) && <span className="ml-1 font-medium" style={{ color: "var(--danger-fg)" }}>Forecast is stale.</span>}
                    </p>
                  )}
                </div>

                {summary && (
                  <div className="rounded-lg bg-surface-2 p-2.5">
                    <div className="flex flex-wrap gap-x-3 gap-y-1">
                      {IMPACT_ORDER.filter((k) => summary.byClass[k]).map((k) => (
                        <span key={k} className="flex items-center gap-1.5">
                          <Swatch color={TAMBON_MODES.impact.classes.find((c) => c.key === k)?.color ?? "transparent"} />
                          <span className="tabular-nums">
                            {summary.byClass[k].toLocaleString()} {classLabel("impact", k).toLowerCase()}
                          </span>
                        </span>
                      ))}
                    </div>
                    <p className="mt-1.5 text-muted">
                      <span className="font-semibold tabular-nums text-fg">{summary.people.toLocaleString()}</span> people on high or
                      very-high ground in tambons rated high or above.
                    </p>
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* Layers */}
        <div className="map-panel pointer-events-auto flex min-h-11 flex-col overflow-hidden">
          <button
            type="button"
            onClick={() => setPanelOpen((o) => !o)}
            className="flex w-full shrink-0 items-center justify-between px-4 py-3"
            aria-expanded={panelOpen}
          >
            <span className="flex items-center gap-2 font-semibold"><LayersIcon className="h-4 w-4 text-accent" aria-hidden />Layers</span>
            <Chevron open={panelOpen} />
          </button>
          {panelOpen && (
            <div className="space-y-0.5 overflow-y-auto border-t border-line px-2 py-2">
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
      </div>

      {/* Legend */}
      {!legendEmpty && (
        <div className="map-panel absolute bottom-8 right-3 flex max-h-[45%] w-[min(15rem,calc(100%-1.5rem))] flex-col">
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
            <div className="space-y-3 overflow-y-auto border-t border-line px-4 py-3 text-xs">
              {layers.tambons && tambonsReady && (
                <LegendSection title={`Tambons: ${mode.legend}`}>
                  {mode.classes.map((c) => (
                    <LegendRow key={c.key} swatch={<Swatch color={c.color} />} label={c.label} note={c.note} />
                  ))}
                </LegendSection>
              )}
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
                <LegendSection title="Facilities" columns>
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
                Live impact is a triage rule, not a landslide forecast. Susceptibility is relative, not a probability.
              </p>
            </div>
          )}
        </div>
      )}

      {/* Charts: bottom centre on a wide screen (between the left column and the legend); a bottom sheet on a narrow one. */}
      {layers.tambons && tambonsReady && overlay && (
        <div
          className={`map-panel absolute bottom-8 left-3 flex max-h-[55%] flex-col lg:left-[18.5rem] lg:right-[16.5rem] lg:max-h-[46%] ${
            chartsOpen ? "right-3 z-10" : "lg:w-fit lg:right-auto"
          }`}
        >
          <button
            type="button"
            onClick={() => setChartsOpen((o) => !o)}
            className="flex w-full shrink-0 items-center justify-between gap-6 px-4 py-2.5"
            aria-expanded={chartsOpen}
          >
            <span className="flex items-center gap-2 font-semibold">
              <ChartNoAxesColumn className="h-4 w-4 text-accent" aria-hidden />
              Charts
              <span className="hidden text-xs font-normal text-muted sm:inline">
                {scenarioActive ? `what-if ${whatIfMm} mm` : "GFS forecast"}
              </span>
            </span>
            <Chevron open={chartsOpen} />
          </button>
          {chartsOpen && (
            <div className="overflow-y-auto border-t border-line px-4 py-3">
              <ImpactCharts
                tambons={overlay.tambons}
                classes={classes}
                scenarioMm={scenarioActive ? whatIfMm : null}
                impactColors={TAMBON_MODES.impact.classes}
                rainColors={TAMBON_MODES.rain.classes}
              />
            </div>
          )}
        </div>
      )}

      {/* Details of the clicked tambon, cell or feature */}
      {details && (
        <div className="map-panel absolute right-14 top-3 flex max-h-[calc(55%-2.5rem)] w-[min(19rem,calc(100%-5rem))] flex-col">
          <div className="flex shrink-0 items-start justify-between gap-2 px-4 py-2.5">
            <span className="flex items-start gap-2">
              <MapPin className="mt-0.5 h-4 w-4 shrink-0 text-accent" aria-hidden />
              <span className="leading-tight">
                <span className="block font-semibold">{details.title}</span>
                {details.subtitle && <span className="text-xs text-muted">{details.subtitle}</span>}
              </span>
            </span>
            <button
              type="button"
              className="rounded p-1 text-muted hover:bg-surface-2 hover:text-fg"
              onClick={() => setSelected(null)}
              aria-label="Close details"
            >
              <X className="h-4 w-4" aria-hidden />
            </button>
          </div>
          <div className="overflow-y-auto border-t border-line px-4 py-2 text-xs">
            {details.sections.map((section, i) => (
              <dl key={section.heading ?? i} className={i ? "mt-2 border-t border-line pt-2" : ""}>
                {section.heading && <div className="eyebrow mb-1">{section.heading}</div>}
                {section.rows.map(([k, v]) => (
                  <div key={k} className="flex justify-between gap-4 py-1">
                    <dt className="text-muted">{k}</dt>
                    <dd className="text-right font-medium tabular-nums">{v}</dd>
                  </div>
                ))}
              </dl>
            ))}
            {selectedTambon && !scenarioActive && <RainOutlook tambon={selectedTambon} rainColors={TAMBON_MODES.rain.classes} />}
            {details.note && <p className="mt-2 border-t border-line pt-2 leading-snug text-subtle">{details.note}</p>}
          </div>
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

interface Details {
  title: string;
  subtitle?: string;
  sections: Array<{ heading?: string; rows: Array<[string, string]> }>;
  note?: string;
}

function cellRows(cell: Cell): Array<[string, string]> {
  return [
    ["Calibrated score", cell.calibrated_probability.toFixed(3)],
    ["Susceptibility class", formatValue("susceptibility_class", cell.susceptibility_class)],
  ];
}

// What the details panel shows for the current selection; a what-if scenario replaces the forecast rain and the classes.
function describe(
  selected: Selection,
  tambonById: Map<string, OverlayTambon>,
  classes: TambonClasses,
  whatIfMm: number | null
): Details | null {
  if (selected.kind === "feature") {
    return { title: selected.title, sections: [{ rows: selected.rows.map(([k, v]) => [k.charAt(0).toUpperCase() + k.slice(1), v]) }] };
  }
  if (selected.kind === "cell") {
    return { title: "Susceptibility cell (250 m)", sections: [{ rows: toRows({ ...selected.cell }) }] };
  }
  const t = tambonById.get(selected.gid);
  if (!t) return null;
  const [impact, rainClass, rain] = classes[selected.gid] ?? [t.live_impact_class, t.rain_local_class_24h ?? null, t.gfs_rain_24h_mm];
  const elevated = impact === "high" || impact === "very_high";
  const share = t.pct_cells_high_vh === null ? "" : ` (${t.pct_cells_high_vh.toFixed(0)}% of cells high or very high)`;
  const risk: Array<[string, string]> = [
    [whatIfMm === null ? "Live impact" : `Impact at ${whatIfMm} mm`, classLabel("impact", impact)],
    ["Terrain tier", `${classLabel("tier", t.susceptibility_tier)}${share}`],
    [whatIfMm === null ? "Rain, next 24 h" : "What-if rain, 24 h", `${mm(rain)} (${classLabel("rain", rainClass)})`],
  ];
  if (whatIfMm === null) {
    risk.push(["Rain, next 3 days", mm(t.gfs_rain_72h_mm)]);
    if (t.gfs_rain_120h_mm != null) risk.push(["Rain, next 5 days (outlook)", mm(t.gfs_rain_120h_mm)]);
  }
  risk.push(["Local P75 / P90 / P95", `${mm(t.local_p75_mm, 0)} / ${mm(t.local_p90_mm, 0)} / ${mm(t.local_p95_mm, 0)}`.replace(/ mm \//g, " /")]);
  const sections: Details["sections"] = [
    { heading: "Risk", rows: risk },
    {
      heading: "On high or very-high ground / total",
      rows: [
        ["People", `${count(t.population_high_vh)} / ${count(t.population_total)}`],
        ["Buildings", `${count(t.buildings_high_vh)} / ${count(t.buildings_total)}`],
        ["Facilities", `${count(t.facilities_high_vh)} / ${count(t.facilities_total)}`],
      ],
    },
  ];
  if (selected.cell) sections.push({ heading: "250 m cell at the click", rows: cellRows(selected.cell) });
  return {
    title: t.NAME_3 ?? t.GID_3,
    subtitle: [t.NAME_2, t.NAME_1].filter(Boolean).join(", "),
    sections,
    note: elevated
      ? `${count(t.population_high_vh)} people and ${count(t.buildings_high_vh)} buildings are at elevated risk under this rain.`
      : "No one is counted at elevated risk: that needs an impact class of high or above.",
  };
}

function Chevron({ open }: { open: boolean }) {
  return <ChevronDown className={`h-4 w-4 text-muted transition-transform ${open ? "" : "-rotate-90"}`} aria-hidden />;
}

function Segmented<T extends string>({
  options,
  value,
  onChange,
}: {
  options: Array<{ value: T; label: string }>;
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <div className="flex rounded-lg border border-line p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={o.value === value}
          onClick={() => onChange(o.value)}
          className={`flex-1 rounded-md px-2 py-1 font-medium transition-colors ${
            o.value === value ? "bg-accent text-accent-fg" : "text-muted hover:text-fg"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
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
      className={`inline-block shrink-0 border ${color === "transparent" ? "border-dashed border-subtle" : "border-black/10"} ${
        round ? "h-2.5 w-2.5 rounded-full" : "h-3 w-4 rounded-sm"
      }`}
      style={{ background: color }}
    />
  );
}
