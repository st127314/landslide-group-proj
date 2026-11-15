import Link from "next/link";
import { CircleDashed, Layers, Mountain, Users } from "lucide-react";
import { api } from "@/lib/api";
import { fmtInt } from "@/lib/classes";
import Limitations from "@/components/Limitations";
import Page from "@/components/Page";
import { LABEL, LINK, Section } from "@/components/Section";
import StatCard from "@/components/StatCard";

export const metadata = { title: "Data — Landslide Impact" };

// Static description of the inputs, kept in step with docs/METHODS.md (sections 1, 2 and Known issues 5 and 7).
const FACTOR_GROUPS: Array<{ group: string; why: string; source: string; factors: Array<[string, string]> }> = [
  {
    group: "Terrain",
    why: "Steep, rugged slopes are less stable, and the shape of the ground decides where water and debris gather.",
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
    why: "Ground that collects water saturates sooner, and saturated soil is weaker.",
    source: "HydroSHEDS 15ACC (500 m) for events before 2020, MERIT Hydro (90 m) from 2020",
    factors: [
      ["upstream_area_km2", "Area draining to the point (km²)"],
      ["twi", "Topographic wetness index"],
      ["spi", "Stream power index"],
    ],
  },
  {
    group: "Soil",
    why: "Texture and density control how fast soil takes up water and how well it drains.",
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
    why: "Some rock types weather into weaker material than others.",
    source: "GLiM global lithology, level 1 (6 classes occur)",
    factors: [["lithology", "Rock type (categorical)"]],
  },
  {
    group: "Land cover",
    why: "Roots hold soil in place; cleared or cultivated slopes fail more easily.",
    source: "SERVIR-Mekong RLCMS with Dynamic World as fallback",
    factors: [["lulc", "Land cover of the previous year (categorical)"]],
  },
  {
    group: "Human and drainage network",
    why: "Road cuts and river banks undercut slopes.",
    source: "OpenStreetMap, searched within 20 km",
    factors: [
      ["dist_to_road", "Distance to the nearest road (m)"],
      ["dist_to_river", "Distance to the nearest river or waterway (m)"],
    ],
  },
];

// Counts as last published in docs/METHODS.md, used only when the API cannot be reached.
const FALLBACK = { events: 6180, negatives: 6180, buildings: 426519, facilities: 3895, population: 9385882.65, popYear: 2020 };

type Update = "Fixed record" | "Snapshot" | "Every forecast run";

export default async function DataPage() {
  const factorCount = FACTOR_GROUPS.reduce((n, g) => n + g.factors.length, 0);

  // The same counts the Overview shows come from the API, so the two pages cannot drift apart.
  let n = FALLBACK;
  try {
    const o = await api.overview();
    n = {
      events: o.landslide_events ?? FALLBACK.events,
      negatives: o.non_landslide_samples ?? FALLBACK.negatives,
      buildings: o.buildings_mapped ?? FALLBACK.buildings,
      facilities: o.facilities_mapped ?? FALLBACK.facilities,
      population: o.population_estimate ?? FALLBACK.population,
      popYear: o.population_source_year ?? FALLBACK.popYear,
    };
  } catch {
    // keep the published figures
  }
  const millions = `${(n.population / 1e6).toFixed(2)} million`;

  const otherSources: Array<{ name: string; use: string; update: Update; detail: string }> = [
    {
      name: "NOAA GFS 0.25° (Earth Engine NOAA/GFS0P25)",
      use: "Forecast rainfall",
      update: "Every forecast run",
      detail:
        "Forecast steps summed over the next 24, 48, 72, 96 and 120 h per tambon (hourly to +120 h of the run, 3-hourly after); cells are about 28 km wide.",
    },
    {
      name: "CHIRPS daily rainfall, 1991–2020",
      use: "Local rainfall normal",
      update: "Fixed record",
      detail:
        "Wet-day (≥ 1 mm) P75, P90 and P95 per tambon, averaged onto the GFS grid: the yardstick for unusually heavy rain.",
    },
    {
      name: "OpenStreetMap (snapshot 2026-09-08)",
      use: "Exposure",
      update: "Snapshot",
      detail: `${fmtInt(n.buildings)} building footprints and ${fmtInt(n.facilities)} public facilities (health, education, emergency, transport, worship) clipped to the study area.`,
    },
    {
      name: `WorldPop ${n.popYear}, constrained, UN-adjusted`,
      use: "Exposure",
      update: "Snapshot",
      detail: `Population per ~100 m pixel; ${n.population.toLocaleString("en-US", { maximumFractionDigits: 0 })} people in the study area.`,
    },
    {
      name: "GADM 4.1",
      use: "Boundaries",
      update: "Fixed record",
      detail: "14 southern provinces and 1,055 tambons (sub-districts).",
    },
  ];

  return (
    <Page
      title="Data"
      description="What the tool is built from: the landslide records, the ground factors the susceptibility model learns from, and the rainfall and exposure data behind the live impact view."
    >
      <section aria-label="Key figures" className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="Landslide records" value={fmtInt(n.events)} sub="Mapped points, 2000–2025" icon={Mountain} />
        <StatCard label="Comparison points" value={fmtInt(n.negatives)} sub="One non-landslide point per landslide" icon={CircleDashed} />
        <StatCard label="Ground factors" value={String(factorCount)} sub="16 numeric, 3 categorical" icon={Layers} />
        <StatCard label="People in the study area" value={millions} sub={`WorldPop ${n.popYear}`} icon={Users} />
      </section>

      <Section id="events" title="Landslide records and comparison points">
        <div className="grid gap-x-8 gap-y-4 text-sm leading-relaxed text-muted md:grid-cols-2">
          <div>
            <h3 className="font-semibold text-fg">Landslide records</h3>
            <p className="mt-1">
              Mapped landslide points in the 14 southern provinces, dated 2000-03-14 to 2025-01-05. The dates are the
              satellite-image dates of the mapping layers, not the day each landslide happened. All 23,284 southern
              landslide records, dated or not, are used to keep comparison points away from real landslides.
            </p>
          </div>
          <div>
            <h3 className="font-semibold text-fg">Comparison (non-landslide) points</h3>
            <p className="mt-1">
              The model needs examples of ground that did not slide. One such point (a &quot;pseudo-absence&quot;) is
              placed for each landslide, 2–10 km from it in the same province, at least 2 km from every recorded
              landslide and 250 m from other comparison points, and given its landslide&apos;s date. Both groups
              therefore share the same years, provinces and regional weather.
            </p>
          </div>
        </div>
      </Section>

      <Section
        id="factors"
        title="Ground factors the model learns from"
        description={
          <>
            The {factorCount} conditioning factors, sampled at each point. Factors that change over time use only
            information from before the local event day. The name in grey is the column name in the data files.
          </>
        }
      >
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {FACTOR_GROUPS.map((g) => (
            <div key={g.group} className="flex flex-col rounded-lg border border-line p-4">
              <h3 className="text-sm font-semibold">
                {g.group} <span className="font-normal text-muted">· {g.factors.length}</span>
              </h3>
              <p className="mt-1 text-sm leading-relaxed text-muted">{g.why}</p>
              <ul className="mt-3 flex-1 divide-y divide-line border-y border-line">
                {g.factors.map(([factor, meaning]) => (
                  <li key={factor} className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 py-2">
                    <span className="text-sm">{meaning}</span>
                    <code className="font-mono text-xs text-muted">{factor}</code>
                  </li>
                ))}
              </ul>
              <p className="mt-3 text-xs leading-relaxed text-muted">
                <span className="font-medium">Source:</span> {g.source}
              </p>
            </div>
          ))}
        </div>
        <ul className="mt-4 max-w-4xl list-disc space-y-1 pl-5 text-sm leading-relaxed text-muted">
          <li>
            Missing values are filled inside the model pipeline, fitted on training folds only (largest gaps: soil 132
            rows, lithology 46).
          </li>
          <li>Ids, dates and coordinates are kept out of the factors so the model cannot learn location directly.</li>
          <li>
            Left out on purpose: NDVI (vegetation greenness), distance to stream, distance to fault and drainage
            density. The reasons are under{" "}
            <a href="#limits" className={LINK}>
              Limits of the data
            </a>{" "}
            and{" "}
            <Link href="/model#limits" className={LINK}>
              Limits of the model
            </Link>
            .
          </li>
        </ul>
      </Section>

      <Section
        id="sources"
        title="Rainfall, exposure and boundaries"
        description="Used by the live impact view and the early-warning rule, not by the susceptibility model."
      >
        <ul className="divide-y divide-line border-y border-line">
          {otherSources.map((s) => (
            <li key={s.name} className="grid gap-x-6 gap-y-1 py-3 md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,3fr)]">
              <div className="text-sm font-medium">{s.name}</div>
              <div className="text-sm">
                <span className={`${LABEL} md:hidden`}>Used for: </span>
                {s.use}
                <span className="block text-xs text-muted">{s.update}</span>
              </div>
              <div className="text-sm leading-relaxed text-muted">{s.detail}</div>
            </li>
          ))}
        </ul>
        <p className="mt-3 text-xs leading-relaxed text-muted">
          Only the rainfall forecast changes between visits. Everything else is a fixed record or a snapshot taken on
          the date shown.
        </p>
      </Section>

      <Limitations group="data" />
    </Page>
  );
}
