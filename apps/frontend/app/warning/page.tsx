import Link from "next/link";
import { ArrowRight, CalendarRange, Clock, CloudRain, MapPinned } from "lucide-react";
import { api, type OverlayTambon } from "@/lib/api";
import { ageLabel, isStale, thaiTime } from "@/lib/time";
import { fmtInt, humanise, plural } from "@/lib/classes";
import { ClassCounts, ClassLegend } from "@/components/Badge";
import Limitations from "@/components/Limitations";
import Page, { LoadError } from "@/components/Page";
import ScenarioPanel from "@/components/ScenarioPanel";
import { Definition, Details, LINK, Section } from "@/components/Section";
import StatCard from "@/components/StatCard";
import TambonTable, { type TambonRow } from "@/components/TambonTable";

export const metadata = { title: "Early Warning — Landslide Impact" };

const TOP_N = 25;

function toRow(t: OverlayTambon): TambonRow {
  return {
    id: t.GID_3,
    name: t.NAME_3 ?? t.GID_3,
    province: t.NAME_1,
    impact: t.live_impact_class,
    rainClass: t.rain_local_class_24h ?? t.rain_class_24h,
    terrain: t.susceptibility_tier,
    rain24: t.gfs_rain_24h_mm,
    rain72: t.gfs_rain_72h_mm,
    rain120: t.gfs_rain_120h_mm,
    p90: t.local_p90_mm ?? null,
    people: t.population_at_elevated_risk,
  };
}

export default async function WarningPage() {
  let forecast: Awaited<ReturnType<typeof api.liveForecast>> | null = null;
  let overlay: Awaited<ReturnType<typeof api.impactOverlay>> | null = null;
  let error: string | null = null;
  try {
    forecast = await api.liveForecast();
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }
  try {
    overlay = await api.impactOverlay();
  } catch {
    overlay = null; // optional layer: the forecast part still works without it
  }

  const totals = overlay?.metadata.totals;
  const counts = totals?.tambons_by_live_impact_class;
  const flagged = (counts?.high ?? 0) + (counts?.very_high ?? 0);

  // The API orders tambons by impact class, then by people at elevated risk. Rows rated moderate or above are shown
  // first; any "low" rows that complete the top 25 sit behind an expander.
  const top = overlay?.tambons.slice(0, TOP_N) ?? [];
  const rated = top.filter((t) => ["very_high", "high", "moderate"].includes(t.live_impact_class));
  const rest = top.filter((t) => !rated.includes(t));

  // Every technical note the forecast and overlay files carry, each one once.
  const technicalNotes = [...new Set([...(forecast?.limitations ?? []), ...(overlay?.metadata.limitations.slice(0, 3) ?? [])])];

  return (
    <Page
      title="Early warning"
      description={
        <>
          Which tambons (sub-districts) combine landslide-prone terrain with forecast rain that is unusually heavy for
          that place in the next 24 hours, and how many people live there.
        </>
      }
    >
      {error && (
        <LoadError
          what="The rainfall forecast"
          error={error}
          hint={
            <>
              Run <code>scripts/run_live_gfs_forecast.py</code> at least once if{" "}
              <code>results/live_forecast/latest.json</code> doesn&apos;t exist yet.
            </>
          }
        />
      )}

      {(forecast || (overlay && totals)) && (
        <Section id="now" title="Next 24 hours">
          {overlay && totals && (
            <>
              <p className="text-xl font-semibold leading-snug tracking-tight sm:text-2xl">
                {flagged === 0
                  ? "No tambon is rated High or Very high."
                  : `${plural(flagged, "tambon")} ${flagged === 1 ? "is" : "are"} rated High or Very high.`}
              </p>
              <p className="mt-1 max-w-3xl text-sm leading-relaxed text-muted">
                At elevated risk right now:{" "}
                <span className="font-medium text-fg">
                  {plural(totals.population_at_elevated_risk, "person", "people")},{" "}
                  {plural(totals.buildings_at_elevated_risk, "building")} and{" "}
                  {plural(totals.facilities_at_elevated_risk, "facility", "facilities")}
                </span>
                . These stand on high or very-high susceptibility ground inside tambons rated High or Very high.
              </p>
              <div className="mt-4">
                <ClassCounts kind="impact" counts={counts} />
              </div>
            </>
          )}

          {forecast && (
            <div className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <StatCard
                label="Forecast issued"
                icon={Clock}
                small
                value={thaiTime(forecast.gfs_run_utc)}
                sub={
                  <>
                    NOAA GFS model run. Fetched {ageLabel(forecast.generated_utc)}; refreshed about every 3 hours.
                    {isStale(forecast.generated_utc) && (
                      <span className="mt-1 block font-medium text-[color:var(--danger-fg)]">
                        Stale: the newest run has not been fetched.
                      </span>
                    )}
                  </>
                }
              />
              <StatCard
                label="Period covered"
                icon={CalendarRange}
                small
                value={thaiTime(forecast.window_start_utc)}
                sub={
                  <>
                    to {thaiTime(forecast.window_24h_end_utc)}.
                    {forecast.window_120h_end_utc && <> The 5-day outlook runs to {thaiTime(forecast.window_120h_end_utc)}.</>}
                  </>
                }
              />
              <StatCard
                label="Heaviest 24 h rain"
                icon={CloudRain}
                value={`${forecast.summary.max_24h_mm?.toFixed(1) ?? "—"} mm`}
                sub={`In any tambon. The median tambon gets ${forecast.summary.median_24h_mm?.toFixed(1) ?? "—"} mm.`}
              />
              <StatCard
                label="Tambons evaluated"
                icon={MapPinned}
                value={fmtInt(forecast.summary.tambons)}
                sub={
                  forecast.summary.tambons_by_local_class_24h ? (
                    <>Rain against local normal, by tambon, is listed below.</>
                  ) : (
                    Object.entries(forecast.summary.tambons_by_class_24h)
                      .map(([k, v]) => `${v} ${humanise(k).toLowerCase()}`)
                      .join(" · ")
                  )
                }
              />
            </div>
          )}

          {forecast?.summary.tambons_by_local_class_24h && (
            <div className="mt-4">
              <h3 className="mb-2 text-sm font-semibold">Forecast rain against each tambon&apos;s local normal</h3>
              <ClassCounts kind="rain" counts={forecast.summary.tambons_by_local_class_24h} />
            </div>
          )}

          {totals && (
            <p className="mt-4 max-w-3xl text-sm leading-relaxed text-muted">
              Whatever the weather, {fmtInt(totals.population_high_vh)} of {fmtInt(totals.population_total)} people in
              the study area live on high or very-high susceptibility ground.
            </p>
          )}

          <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2 text-sm">
            <Link href="/impact" className={`${LINK} inline-flex min-h-6 items-center gap-1`}>
              See these tambons on the map <ArrowRight className="h-3.5 w-3.5" aria-hidden />
            </Link>
            <a href="#limits" className={`${LINK} inline-flex min-h-6 items-center`}>
              This is a triage aid, not a landslide forecast: read its limits
            </a>
          </div>
        </Section>
      )}

      {overlay && totals && (
        <Section
          id="tambons"
          title="Tambons to check first"
          description={
            <>
              The top {TOP_N} of {fmtInt(overlay.tambons.length)} tambons, ordered by impact class, then by people at
              elevated risk. To look up any other tambon, search for it on the{" "}
              <Link href="/impact" className={LINK}>
                Live Impact map
              </Link>
              .
            </>
          }
        >
          <div className="mb-4 space-y-2">
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <span className="w-40 shrink-0 text-xs font-medium uppercase tracking-wider text-muted">Impact</span>
              <ClassLegend kind="impact" />
            </div>
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <span className="w-40 shrink-0 text-xs font-medium uppercase tracking-wider text-muted">Rain vs local normal</span>
              <ClassLegend kind="rain" />
            </div>
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <span className="w-40 shrink-0 text-xs font-medium uppercase tracking-wider text-muted">Terrain tier</span>
              <ClassLegend kind="terrain" exclude={["no_data"]} />
            </div>
            <p className="text-sm text-muted">
              <a href="#read" className={LINK}>
                What these classes and columns mean
              </a>
            </p>
          </div>

          {rated.length > 0 ? (
            <TambonTable rows={rated.map(toRow)} label="Tambons rated moderate or above" outlook />
          ) : (
            <p className="rounded-lg border border-line bg-surface-2 p-3 text-sm">
              No tambon is rated Moderate or above in this forecast.
            </p>
          )}
          {rest.length > 0 && (
            <div className="mt-3">
              <Details summary={`Show the next ${plural(rest.length, "tambon")}, rated Low or not assessed`}>
                <TambonTable rows={rest.map(toRow)} label="Remaining tambons of the top 25" outlook />
              </Details>
            </div>
          )}
          <p className="mt-3 text-xs leading-relaxed text-muted">
            Forecast cells are about 28 km wide, so neighbouring tambons often share one rainfall value.
          </p>
        </Section>
      )}

      {overlay && (
        <Section id="read" title="How to read this page">
          <dl className="grid gap-x-8 gap-y-5 md:grid-cols-2">
            <Definition term="Tambon">
              <p>
                A sub-district, the unit used for every figure here. The 14 southern provinces have{" "}
                {fmtInt(overlay.tambons.length)} of them.
              </p>
            </Definition>
            <Definition term="Terrain tier">
              <p>
                How much of the tambon is landslide-prone: the share of its 250 m cells that the susceptibility map
                rates high or very high. It does not change with the weather.
              </p>
              <ClassLegend kind="terrain" exclude={["no_data"]} />
            </Definition>
            <Definition term="Rain vs local normal (P75, P90, P95)">
              <p>
                The forecast 24-hour rain compared with that tambon&apos;s own rainy days in 1991–2020 (CHIRPS
                records). P90 is the amount exceeded on only 1 rainy day in 10; P75 on 1 in 4; P95 on 1 in 20. So
                &quot;Above P95&quot; means rain that is rare for that place, whatever the millimetres. &quot;Local
                P90&quot; in the table is that tambon&apos;s P90 amount.
              </p>
              <ClassLegend kind="rain" />
            </Definition>
            <Definition term="Impact class">
              <p>
                Terrain tier combined with the rain class. Ordinary rain (below P75) gives Low everywhere, low terrain
                never goes above Moderate, and Very high needs High terrain and rain above P95.
              </p>
              <ClassLegend kind="impact" />
              <p>
                Not assessed: a tambon too small to contain any cell of the susceptibility map gets no class.
              </p>
            </Definition>
            <Definition term="People, buildings and facilities at elevated risk">
              <p>
                Those standing on high or very-high susceptibility ground inside a tambon rated High or Very high. In
                any other tambon the count is 0, even where landslide-prone ground is inhabited.
              </p>
            </Definition>
            <Definition term="24 h, 72 h and 5 days">
              <p>
                Total forecast rain from the start of the period covered. Only the 24-hour total sets the classes; the
                72-hour and 5-day totals are an outlook, and days 4 and 5 are the least certain.
              </p>
            </Definition>
          </dl>
          <div className="mt-5">
            <Details summary="The exact scoring rule and the fixed millimetre classes">
              <p>
                Terrain factor (low = 1, moderate = 2, high = 3, from the share of 250 m cells that are high or very
                high) × 24 h rain class against the tambon&apos;s own climate (below P75 = 0, P75–P90 = 1, P90–P95 = 2,
                above P95 = 3) → 0–1 low, 2–3 moderate, 4–6 high, ≥ 7 very high.
              </p>
              <p className="mt-2">
                The percentiles are wet-day 24 h rainfall percentiles from CHIRPS 1991–2020, averaged onto the forecast
                grid.
                {forecast && (
                  <>
                    {" "}
                    Fixed millimetre classes are also in the data:{" "}
                    {forecast.rain_classes_mm_24h.map((c) => `${c.class.replaceAll("_", " ")} ≥ ${c.from_mm} mm`).join(", ")}.
                  </>
                )}
              </p>
            </Details>
          </div>
        </Section>
      )}

      {overlay && <ScenarioPanel provinces={overlay.provinces.map((p) => p.NAME_1).sort()} />}

      <Limitations group="forecast">
        {technicalNotes.length > 0 && (
          <Details summary="Technical notes supplied with the forecast files">
            <ul className="list-disc space-y-2 pl-5">
              {technicalNotes.map((l) => (
                <li key={l}>{l}</li>
              ))}
            </ul>
          </Details>
        )}
      </Limitations>
    </Page>
  );
}
