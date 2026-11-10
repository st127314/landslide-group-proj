import { CircleDashed, CloudRain, Database, Layers, Mountain, Users } from "lucide-react";
import Page from "@/components/Page";
import StatCard from "@/components/StatCard";
import Limitations from "@/components/Limitations";

export const metadata = { title: "Data — Landslide Impact" };

// Static description of the inputs, kept in step with docs/METHODS.md (sections 1, 2 and Known issues 5 and 7).
const FACTOR_GROUPS: Array<{ group: string; source: string; factors: Array<[string, string]> }> = [
  {
    group: "Terrain",
    source: "ALOS AW3D30 V4.1 (30 m); SRTM 2000 for the earliest events",
    factors: [
      ["elevation", "Height above sea level (m)"],
      ["slope", "Steepness (degrees)"],
      ["aspect", "Direction the slope faces"],
      ["curvature_general", "Overall surface curvature"],
      ["curvature_profile", "Curvature along the slope, which controls flow speed"],
      ["tri", "Terrain ruggedness index"],
      ["tpi", "Topographic position index (ridge vs valley)"],
      ["ls_factor", "Slope length and steepness factor"],
    ],
  },
  {
    group: "Hydrology",
    source: "HydroSHEDS 15ACC (500 m) for events before 2020, MERIT Hydro (90 m) from 2020",
    factors: [
      ["upstream_area_km2", "Area draining to the point (km²)"],
      ["twi", "Topographic wetness index"],
      ["spi", "Stream power index"],
    ],
  },
  {
    group: "Soil",
    source: "OpenLandMap",
    factors: [
      ["soil_texture", "Texture class (categorical)"],
      ["soil_clay_pct", "Clay content (%)"],
      ["soil_sand_pct", "Sand content (%)"],
      ["soil_bulk_density", "Bulk density"],
    ],
  },
  {
    group: "Geology",
    source: "GLiM global lithology, level 1 (6 classes occur)",
    factors: [["lithology", "Rock type (categorical)"]],
  },
  {
    group: "Vegetation and land cover",
    source: "Landsat 5/7/8/9 and Sentinel-2; SERVIR-Mekong RLCMS with Dynamic World as fallback",
    factors: [
      ["ndvi", "Latest valid NDVI in the 90 days before the event day"],
      ["lulc", "Land cover of the previous year (categorical)"],
    ],
  },
  {
    group: "Human and drainage network",
    source: "OpenStreetMap, searched within 20 km",
    factors: [
      ["dist_to_road", "Distance to the nearest road (m)"],
      ["dist_to_river", "Distance to the nearest river or waterway (m)"],
    ],
  },
];

const OTHER_SOURCES: Array<{ name: string; use: string; detail: string }> = [
  {
    name: "NOAA GFS 0.25° (Earth Engine NOAA/GFS0P25)",
    use: "Forecast rainfall",
    detail: "Hourly forecast steps summed over the next 24, 48 and 72 h per tambon; cells are about 28 km wide.",
  },
  {
    name: "CHIRPS daily rainfall, 1991–2020",
    use: "Local rainfall climate",
    detail: "Wet-day (≥ 1 mm) P75, P90 and P95 per tambon, averaged onto the GFS grid; the yardstick for unusual rain.",
  },
  {
    name: "OpenStreetMap (snapshot 2026-09-08)",
    use: "Exposure",
    detail: "426,519 building footprints and 3,895 public facilities (health, education, emergency, transport, worship) clipped to the study area.",
  },
  {
    name: "WorldPop 2020, constrained, UN-adjusted",
    use: "Exposure",
    detail: "Population per ~100 m pixel; 9.39 million people in the study area.",
  },
  {
    name: "GADM 4.1",
    use: "Boundaries",
    detail: "14 southern provinces and 1,055 tambons (sub-districts).",
  },
];

export default function DataPage() {
  const factorCount = FACTOR_GROUPS.reduce((n, g) => n + g.factors.length, 0);
  return (
    <Page
      title="Data"
      description="The landslide records, the conditioning factors the susceptibility model learns from, and the rainfall and exposure data behind the live impact view."
    >
      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Landslide events" value="6,180" sub="Point events, 2000–2025" icon={Mountain} />
        <StatCard label="Non-landslide points" value="6,180" sub="One paired point per landslide" icon={CircleDashed} />
        <StatCard label="Conditioning factors" value={String(factorCount)} sub="17 numeric, 3 categorical" icon={Layers} />
        <StatCard label="People in study area" value="9.39 M" sub="WorldPop 2020" icon={Users} />
      </section>

      <section className="card mt-6">
        <h2 className="card-title flex items-center gap-2">
          <Database className="h-4 w-4 text-accent" aria-hidden />
          Event data
        </h2>
        <div className="mt-3 grid gap-4 text-sm leading-relaxed text-muted md:grid-cols-2">
          <p>
            <span className="font-medium text-fg">Landslide inventory.</span> 6,180 mapped landslide points in the 14
            southern provinces, dated 2000-03-14 to 2025-01-05. The dates are the satellite-image dates of the mapping
            layers, not the day each landslide happened. All 23,284 southern landslide records, dated or not, are used
            to keep non-landslide points away from real landslides.
          </p>
          <p>
            <span className="font-medium text-fg">Non-landslide points.</span> One pseudo-absence per landslide, placed
            2–10 km from it in the same province, at least 2 km from every recorded landslide and 250 m from other
            negatives, and given its landslide&apos;s date. Both classes therefore share the same years, provinces and
            regional weather.
          </p>
        </div>
      </section>

      <section className="card mt-6">
        <h2 className="card-title flex items-center gap-2">
          <Layers className="h-4 w-4 text-accent" aria-hidden />
          Conditioning factors
        </h2>
        <p className="card-desc">
          The {factorCount} factors the model uses, sampled at each point. Factors that change over time use only
          information from before the local event day.
        </p>
        <div className="mt-4 overflow-x-auto rounded-lg border border-line">
          <table className="data-table min-w-[720px]">
            <thead>
              <tr>
                <th>Group</th>
                <th>Factor</th>
                <th>Meaning</th>
                <th>Source</th>
              </tr>
            </thead>
            <tbody>
              {FACTOR_GROUPS.flatMap((g) =>
                g.factors.map(([factor, meaning], i) => (
                  <tr key={factor}>
                    {i === 0 && (
                      <td rowSpan={g.factors.length} className="align-top font-medium">
                        {g.group}
                      </td>
                    )}
                    <td>
                      <code className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-xs">{factor}</code>
                    </td>
                    <td className="text-muted">{meaning}</td>
                    {i === 0 && (
                      <td rowSpan={g.factors.length} className="align-top text-muted">
                        {g.source}
                      </td>
                    )}
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        <ul className="mt-4 list-disc space-y-1 pl-5 text-xs leading-relaxed text-muted">
          <li>
            Missing values are filled inside the model pipeline, fitted on training folds only (largest gaps: NDVI 446
            rows, soil 132, lithology 46).
          </li>
          <li>
            Distance to stream was dropped: the pre-2020 hydrology source returned values that are not metres.
          </li>
          <li>
            Ids, dates and coordinates are kept out of the features so the model cannot learn location directly.
          </li>
        </ul>
      </section>

      <section className="card mt-6">
        <h2 className="card-title flex items-center gap-2">
          <CloudRain className="h-4 w-4 text-accent" aria-hidden />
          Rainfall, exposure and boundaries
        </h2>
        <p className="card-desc">Used by the live impact view and the early-warning rule, not by the susceptibility model.</p>
        <div className="mt-4 overflow-x-auto rounded-lg border border-line">
          <table className="data-table min-w-[640px]">
            <thead>
              <tr>
                <th>Dataset</th>
                <th>Used for</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {OTHER_SOURCES.map((s) => (
                <tr key={s.name}>
                  <td className="font-medium">{s.name}</td>
                  <td className="whitespace-nowrap text-muted">{s.use}</td>
                  <td className="text-muted">{s.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <Limitations />
    </Page>
  );
}
