// Thin typed client for apps/backend's read-only API. Live data (forecast, overlay, scenario) is never cached;
// the static map layers use the browser's HTTP cache, following the backend's Cache-Control headers.

// Browser: NEXT_PUBLIC_API_URL (baked in at build time; set it to "" to call the same origin,
// e.g. behind a reverse proxy that routes /api to the backend).
// Server components inside a container: INTERNAL_API_URL (e.g. http://backend:8000).
const PUBLIC_API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const API_URL =
  typeof window === "undefined"
    ? (process.env.INTERNAL_API_URL ?? PUBLIC_API_URL)
    : PUBLIC_API_URL;

async function getJSON<T>(path: string, signal?: AbortSignal, cache: RequestCache = "no-store"): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, { cache, signal });
  if (!res.ok) {
    throw new Error(`${path} -> HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export interface JobStatus {
  label: string;
  complete?: number;
  total?: number | null;
  done: boolean;
  note?: string;
}

export interface PipelineStatus {
  factor_grid: JobStatus;
  susceptibility_raster: JobStatus;
  live_forecast: JobStatus;
  impact_overlay: JobStatus;
}

export interface Overview {
  study_area: string;
  landslide_events: number | null;
  non_landslide_samples: number | null;
  buildings_mapped: number | null;
  facilities_mapped: number | null;
  facility_breakdown: Record<string, number>;
  population_estimate: number | null;
  population_source_year: number;
  best_model: string | null;
  best_model_roc_auc: number | null;
  best_model_selection: string | null;
  pipeline_status: PipelineStatus;
}

export interface ModelMetricRow {
  model: string;
  [metric: string]: number | string;
}

export interface ModelComparisonEntry {
  model: string;
  cv: ModelMetricRow | null;
  test: ModelMetricRow | null;
}

export interface ModelComparison {
  best_model: string;
  models: ModelComparisonEntry[];
}

export interface ModelMetadata {
  best_model: string;
  selection: string;
  best_params: Record<string, Record<string, unknown>>;
  threshold_raw_probability: number;
  threshold_calibrated_probability: number;
  sample_prevalence?: number;
  score_interpretation?: string;
  spatial_buffer_km?: number;
  feature_columns: string[];
  numeric_features: string[];
  categorical_features: string[];
  excluded_columns: string[];
  cv_results: ModelMetricRow[];
  test_results: ModelMetricRow[];
  temporal_holdout_descriptive?: Record<string, unknown>;
  [key: string]: unknown;
}

export type GeoJSONFeatureCollection = {
  type: "FeatureCollection";
  features: Array<{
    type: "Feature";
    geometry: { type: string; coordinates: unknown };
    properties: Record<string, unknown>;
  }>;
};

export interface WorldPopManifest {
  stats: {
    total_population: number;
    mean_pixel_population: number | null;
    max_pixel_population: number | null;
  };
  citation: string;
  license: string;
  limitations: string[];
}

export interface TambonForecast {
  GID_3: string;
  NAME_3: string | null;
  NAME_2: string | null;
  NAME_1: string | null;
  lon: number;
  lat: number;
  gfs_rain_24h_mm: number | null;
  gfs_rain_48h_mm: number | null;
  gfs_rain_72h_mm: number | null;
  gfs_peak_hourly_mm_24h: number | null;
  rain_class_24h: string;
  local_p75_mm: number | null;
  local_p90_mm: number | null;
  local_p95_mm: number | null;
  rain_local_class_24h: string;
}

export interface LiveForecast {
  generated_utc: string;
  gfs_run_utc: string;
  window_start_utc: string;
  window_24h_end_utc: string;
  window_72h_end_utc: string;
  rain_classes_mm_24h: { class: string; from_mm: number }[];
  summary: {
    tambons: number;
    tambons_by_class_24h: Record<string, number>;
    tambons_by_local_class_24h?: Record<string, number>;
    max_24h_mm: number | null;
    median_24h_mm: number | null;
  };
  method: string;
  tambons: TambonForecast[];
  limitations: string[];
}

export interface OverlayTambon {
  GID_3: string;
  NAME_3: string | null;
  NAME_2: string | null;
  NAME_1: string | null;
  area_km2: number;
  pct_cells_high_vh: number | null;
  susceptibility_tier: string;
  buildings_total: number;
  buildings_high_vh: number;
  population_total: number;
  population_high_vh: number;
  facilities_total: number;
  facilities_high_vh: number;
  critical_facilities_high_vh: number;
  gfs_rain_24h_mm: number | null;
  gfs_rain_48h_mm: number | null;
  gfs_rain_72h_mm: number | null;
  rain_class_24h: string;
  local_p75_mm?: number | null;
  local_p90_mm?: number | null;
  local_p95_mm?: number | null;
  rain_local_class_24h?: string;
  live_impact_class: string;
  population_at_elevated_risk: number;
  buildings_at_elevated_risk: number;
  facilities_at_elevated_risk: number;
}

export interface OverlayProvince {
  NAME_1: string;
  tambons: number;
  population_total: number;
  population_high_vh: number;
  pct_population_in_high_vh: number | null;
  buildings_high_vh: number;
  population_at_elevated_risk: number;
  tambons_live_impact_high_or_above: number;
  max_rain_24h_mm: number | null;
}

export interface ImpactOverlay {
  metadata: {
    generated_utc: string;
    forecast_generated_utc: string;
    gfs_run_utc: string;
    forecast_window_start_utc: string;
    forecast_window_24h_end_utc: string;
    rain_basis?: string;
    totals: {
      buildings_total: number;
      buildings_high_vh: number;
      population_total: number;
      population_high_vh: number;
      facilities_total: number;
      facilities_high_vh: number;
      population_at_elevated_risk: number;
      buildings_at_elevated_risk: number;
      facilities_at_elevated_risk: number;
      tambons_by_live_impact_class: Record<string, number>;
      tambons_by_rain_class_24h: Record<string, number>;
      tambons_by_rain_local_class_24h?: Record<string, number>;
    };
    limitations: string[];
  };
  tambons: OverlayTambon[];
  provinces: OverlayProvince[];
}

export interface ScenarioTambon {
  GID_3: string;
  NAME_3: string | null;
  NAME_2: string | null;
  NAME_1: string | null;
  susceptibility_tier: string;
  rain_24h_mm: number | null;
  local_p90_mm: number | null;
  rain_local_class_24h: string | null;
  impact_class: string;
  in_scope: boolean;
  population_at_elevated_risk: number;
  buildings_at_elevated_risk: number;
  facilities_at_elevated_risk: number;
}

export interface ScenarioResult {
  scenario: { rain_24h_mm: number | null; province: string | null; description: string; basis: string };
  summary: {
    tambons: number;
    tambons_in_scope: number;
    tambons_by_impact_class: Record<string, number>;
    tambons_above_p95: number;
    population_at_elevated_risk: number;
    buildings_at_elevated_risk: number;
    facilities_at_elevated_risk: number;
  };
  provinces: { NAME_1: string; tambons_high_or_above: number; population_at_elevated_risk: number }[];
  tambons: ScenarioTambon[];
  limitations: string[];
}

// [impact class, rain class against local percentiles, 24 h rain in mm] for one tambon.
export type TambonClasses = Record<string, [string, string | null, number | null]>;

export const api = {
  overview: () => getJSON<Overview>("/api/overview"),
  status: () => getJSON<PipelineStatus>("/api/status"),
  model: () => getJSON<ModelMetadata>("/api/model"),
  modelComparison: () => getJSON<ModelComparison>("/api/model/comparison"),
  boundary: () => getJSON<GeoJSONFeatureCollection>("/api/impact/boundary", undefined, "default"),
  susceptibility: () => getJSON<GeoJSONFeatureCollection>("/api/impact/susceptibility", undefined, "default"),
  facilities: () => getJSON<GeoJSONFeatureCollection>("/api/impact/facilities", undefined, "default"),
  population: () => getJSON<WorldPopManifest>("/api/impact/population"),
  buildings: (bbox: [number, number, number, number], limit = 5000) =>
    getJSON<GeoJSONFeatureCollection & { truncated: boolean }>(
      `/api/impact/buildings?min_lon=${bbox[0]}&min_lat=${bbox[1]}&max_lon=${bbox[2]}&max_lat=${bbox[3]}&limit=${limit}`
    ),
  susceptibilityGrid: (bbox: [number, number, number, number], limit = 8000) =>
    getJSON<GeoJSONFeatureCollection & { truncated: boolean }>(
      `/api/impact/susceptibility-grid?min_lon=${bbox[0]}&min_lat=${bbox[1]}&max_lon=${bbox[2]}&max_lat=${bbox[3]}&limit=${limit}`,
      undefined,
      "default"
    ),
  susceptibilityRaster: () =>
    getJSON<{ coordinates: [number, number][]; width: number; height: number; cell_m: number; version?: string }>(
      "/api/impact/susceptibility-raster.json",
      undefined,
      "no-cache"
    ),
  buildingsTilesUrl: () => `${API_URL}/api/impact/buildings.pmtiles`,
  // ?v= is the PNG's content hash, so a regenerated map gets a new URL past any cached copy.
  susceptibilityRasterUrl: (version?: string) =>
    `${API_URL}/api/impact/susceptibility-raster.png${version ? `?v=${version}` : ""}`,
  susceptibilityAt: (lon: number, lat: number) =>
    getJSON<{ lon: number; lat: number; calibrated_probability: number; susceptibility_class: string | null }>(
      `/api/impact/susceptibility-at?lon=${lon}&lat=${lat}`,
      undefined,
      "default"
    ),
  impactOverlay: () => getJSON<ImpactOverlay>("/api/impact/overlay"),
  scenario: (rain24hMm: number | null, province: string | null, limit = 15, signal?: AbortSignal) => {
    const q = new URLSearchParams({ limit: String(limit) });
    if (rain24hMm !== null) q.set("rain_24h_mm", String(rain24hMm));
    if (province) q.set("province", province);
    return getJSON<ScenarioResult>(`/api/impact/scenario?${q.toString()}`, signal);
  },
  tambons: () => getJSON<GeoJSONFeatureCollection>("/api/impact/tambons", undefined, "default"),
  // The scenario rule runs on the server; the map only needs every tambon's resulting classes and the totals.
  scenarioClasses: (rain24hMm: number, signal?: AbortSignal) =>
    getJSON<ScenarioResult & { tambon_classes: TambonClasses }>(
      `/api/impact/scenario?rain_24h_mm=${rain24hMm}&limit=1&classes=true`,
      signal
    ),
  liveForecast: () => getJSON<LiveForecast>("/api/impact/live-forecast"),
};

export { API_URL };
