import { api } from "@/lib/api";
import { Badge, CLASS_LABELS } from "@/components/Badge";
import ScenarioPanel from "@/components/ScenarioPanel";
import Page from "@/components/Page";
import { CalendarRange, Clock, CloudRain, MapPinned, type LucideIcon } from "lucide-react";

function fmtUtc(iso: string) {
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short", timeZone: "UTC" }) + " UTC";
}

function CardLabel({ icon: Icon, children }: { icon: LucideIcon; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <div className="eyebrow">{children}</div>
      <Icon className="h-4 w-4 shrink-0 text-accent" aria-hidden />
    </div>
  );
}

const IMPACT_ORDER = ["very_high", "high", "moderate", "low", "not_assessed"];

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
  const cards = (c: Record<string, number> | undefined) =>
    IMPACT_ORDER.filter((k) => c && c[k]).map((k) => ({ cls: k, n: c![k] }));

  return (
    <Page
      title="Early warning"
      description={
        <>
        Live impact = <strong className="text-fg">forecast rainfall</strong> (NOAA GFS, next 24 and 72 hours from now, judged against each
        tambon&apos;s own rainfall climate) × <strong className="text-fg">terrain susceptibility</strong> (the machine-learning map) ×{" "}
        <strong className="text-fg">who is exposed</strong> (buildings, facilities, population). The combination is a transparent rule, not a
        validated landslide forecast.
        </>
      }
    >

      {error && (
        <div className="mt-6 note-danger">
          Could not reach the API: {error}. Run <code>scripts/run_live_gfs_forecast.py</code> at least once if{" "}
          <code>results/live_forecast/latest.json</code> doesn&apos;t exist yet.
        </div>
      )}

      {forecast && (
        <>
          <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div className="card p-4">
              <CardLabel icon={Clock}>GFS model run</CardLabel>
              <div className="mt-2 text-base font-semibold tabular-nums">{fmtUtc(forecast.gfs_run_utc)}</div>
              <div className="mt-1 text-xs text-muted">fetched {fmtUtc(forecast.generated_utc)}</div>
            </div>
            <div className="card p-4">
              <CardLabel icon={CalendarRange}>Next 24 h window</CardLabel>
              <div className="mt-2 text-base font-semibold tabular-nums">{fmtUtc(forecast.window_start_utc)}</div>
              <div className="mt-1 text-xs text-muted">to {fmtUtc(forecast.window_24h_end_utc)}</div>
            </div>
            <div className="card p-4">
              <CardLabel icon={CloudRain}>Heaviest 24 h forecast</CardLabel>
              <div className="mt-2 text-base font-semibold tabular-nums">{forecast.summary.max_24h_mm?.toFixed(1)} mm</div>
              <div className="mt-1 text-xs text-muted">median {forecast.summary.median_24h_mm?.toFixed(1)} mm</div>
            </div>
            <div className="card p-4">
              <CardLabel icon={MapPinned}>Tambons evaluated</CardLabel>
              <div className="mt-2 text-base font-semibold tabular-nums">{forecast.summary.tambons.toLocaleString()}</div>
              <div className="mt-1 text-xs text-muted">
                {Object.entries(forecast.summary.tambons_by_local_class_24h ?? forecast.summary.tambons_by_class_24h)
                  .map(([k, v]) => `${v} ${CLASS_LABELS[k] ?? k.replaceAll("_", " ")}`)
                  .join(" · ")}
              </div>
            </div>
          </section>

          <div className="mt-4 note-warn">
            {forecast.limitations.map((l) => (
              <p key={l} className="mb-1 last:mb-0">
                • {l}
              </p>
            ))}
            <p className="mb-0 mt-1">
              • Rain is classed against each tambon&apos;s own wet-day 24 h rainfall percentiles (CHIRPS 1991–2020, averaged
              onto the GFS grid): below P75, P75–P90, P90–P95, above P95. Fixed mm classes are also in the data:{" "}
              {forecast.rain_classes_mm_24h.map((c) => `${c.class.replaceAll("_", " ")} ≥ ${c.from_mm} mm`).join(", ")}.
            </p>
          </div>
        </>
      )}

      {overlay && totals && (
        <section className="mt-6 card">
          <h2 className="card-title">Live impact by tambon</h2>
          <p className="mt-1 text-sm text-muted">
            Right now {totals.population_at_elevated_risk.toLocaleString()} people,{" "}
            {totals.buildings_at_elevated_risk.toLocaleString()} buildings and {totals.facilities_at_elevated_risk}{" "}
            facilities are in high-susceptibility terrain inside tambons rated <em>high</em> or{" "}
            <em>very high</em>. Overall, {totals.population_high_vh.toLocaleString()} of{" "}
            {totals.population_total.toLocaleString()} people live in high or very-high susceptibility cells regardless
            of the weather.
          </p>
          <div className="mt-3 flex flex-wrap gap-2 text-sm">
            {cards(totals.tambons_by_live_impact_class).map(({ cls, n }) => (
              <span key={cls} className="flex items-center gap-2 rounded-lg border border-line px-3 py-1">
                <Badge cls={cls} /> {n} tambons
              </span>
            ))}
          </div>

          <div className="mt-4 overflow-x-auto rounded-lg border border-line">
            <table className="data-table min-w-[820px]">
              <thead>
                <tr>
                  <th className="font-medium">Tambon</th>
                  <th className="font-medium">Province</th>
                  <th className="font-medium">Terrain</th>
                  <th className="text-right font-medium">Rain 24 h</th>
                  <th className="text-right font-medium">Rain 72 h</th>
                  <th className="text-right font-medium">Local P90</th>
                  <th className="font-medium">vs local normal</th>
                  <th className="font-medium">Live impact</th>
                  <th className="text-right font-medium">People at risk</th>
                </tr>
              </thead>
              <tbody>
                {overlay.tambons.slice(0, 25).map((t) => (
                  <tr key={t.GID_3}>
                    <td className="font-medium">{t.NAME_3 ?? t.GID_3}</td>
                    <td className="text-muted">{t.NAME_1}</td>
                    <td>
                      <Badge cls={t.susceptibility_tier} />
                    </td>
                    <td className="text-right tabular-nums">{t.gfs_rain_24h_mm?.toFixed(1) ?? "–"} mm</td>
                    <td className="text-right tabular-nums">{t.gfs_rain_72h_mm?.toFixed(1) ?? "–"} mm</td>
                    <td className="text-right tabular-nums">{t.local_p90_mm?.toFixed(0) ?? "–"} mm</td>
                    <td>
                      <Badge cls={t.rain_local_class_24h ?? t.rain_class_24h} />
                    </td>
                    <td>
                      <Badge cls={t.live_impact_class} />
                    </td>
                    <td className="text-right tabular-nums">{t.population_at_elevated_risk.toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-xs text-muted">
            Top 25 of {overlay.tambons.length.toLocaleString()} tambons, ordered by live impact class, then by people at
            risk. Rule: terrain factor (low = 1, moderate = 2, high = 3, from the share of 250 m cells that are high or very
            high) × 24 h rain class against the tambon&apos;s own climate (below P75 = 0, P75–P90 = 1, P90–P95 = 2, above
            P95 = 3) → 0–1 low, 2–3 moderate, 4–6 high, ≥ 7 very high.
            GFS cells are ~28 km wide, so neighbouring tambons often share one rainfall value.
          </p>
          <div className="mt-3 note-warn">
            {overlay.metadata.limitations.slice(0, 3).map((l) => (
              <p key={l} className="mb-1 last:mb-0">
                • {l}
              </p>
            ))}
          </div>
        </section>
      )}

      {overlay && <ScenarioPanel provinces={overlay.provinces.map((p) => p.NAME_1).sort()} />}
    </Page>
  );
}
