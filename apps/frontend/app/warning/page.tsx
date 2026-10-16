import { api } from "@/lib/api";
import { Badge, CLASS_LABELS } from "@/components/Badge";
import ScenarioPanel from "@/components/ScenarioPanel";

function fmtUtc(iso: string) {
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short", timeZone: "UTC" }) + " UTC";
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
    <div className="mx-auto w-full max-w-6xl flex-1 px-6 py-10">
      <h1 className="text-3xl font-bold tracking-tight">Early Warning</h1>
      <p className="mt-2 max-w-3xl text-zinc-600 dark:text-zinc-400">
        Live impact = <strong>forecast rainfall</strong> (NOAA GFS, next 24 and 72 hours from now, judged against each
        tambon&apos;s own rainfall climate) × <strong>terrain susceptibility</strong> (the machine-learning map) ×{" "}
        <strong>who is exposed</strong> (buildings, facilities, population). The combination is a transparent rule, not a
        validated landslide forecast.
      </p>

      {error && (
        <div className="mt-6 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
          Could not reach the API: {error}. Run <code>scripts/run_live_gfs_forecast.py</code> at least once if{" "}
          <code>results/live_forecast/latest.json</code> doesn&apos;t exist yet.
        </div>
      )}

      {forecast && (
        <>
          <section className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
              <div className="text-xs text-zinc-500">GFS model run</div>
              <div className="mt-1 text-sm font-semibold">{fmtUtc(forecast.gfs_run_utc)}</div>
              <div className="text-xs text-zinc-500">fetched {fmtUtc(forecast.generated_utc)}</div>
            </div>
            <div className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
              <div className="text-xs text-zinc-500">Next 24 h window</div>
              <div className="mt-1 text-sm font-semibold">{fmtUtc(forecast.window_start_utc)}</div>
              <div className="text-xs text-zinc-500">to {fmtUtc(forecast.window_24h_end_utc)}</div>
            </div>
            <div className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
              <div className="text-xs text-zinc-500">Heaviest 24 h forecast</div>
              <div className="mt-1 text-sm font-semibold">{forecast.summary.max_24h_mm?.toFixed(1)} mm</div>
              <div className="text-xs text-zinc-500">median {forecast.summary.median_24h_mm?.toFixed(1)} mm</div>
            </div>
            <div className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
              <div className="text-xs text-zinc-500">Tambons evaluated</div>
              <div className="mt-1 text-sm font-semibold">{forecast.summary.tambons.toLocaleString()}</div>
              <div className="text-xs text-zinc-500">
                {Object.entries(forecast.summary.tambons_by_local_class_24h ?? forecast.summary.tambons_by_class_24h)
                  .map(([k, v]) => `${v} ${CLASS_LABELS[k] ?? k.replace("_", " ")}`)
                  .join(" · ")}
              </div>
            </div>
          </section>

          <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300">
            {forecast.limitations.map((l) => (
              <p key={l} className="mb-1 last:mb-0">
                • {l}
              </p>
            ))}
            <p className="mb-0 mt-1">
              • Rain is classed against each tambon&apos;s own wet-day 24 h rainfall percentiles (CHIRPS 1991–2020, averaged
              onto the GFS grid): below P75, P75–P90, P90–P95, above P95. Fixed mm classes are also in the data:{" "}
              {forecast.rain_classes_mm_24h.map((c) => `${c.class.replace("_", " ")} ≥ ${c.from_mm} mm`).join(", ")}.
            </p>
          </div>
        </>
      )}

      {overlay && totals && (
        <section className="mt-6 rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-900">
          <h2 className="text-lg font-semibold">Live impact by tambon</h2>
          <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
            Right now {totals.population_at_elevated_risk.toLocaleString()} people,{" "}
            {totals.buildings_at_elevated_risk.toLocaleString()} buildings and {totals.facilities_at_elevated_risk}{" "}
            critical facilities are in high-susceptibility terrain inside tambons rated <em>high</em> or{" "}
            <em>very high</em>. Overall, {totals.population_high_vh.toLocaleString()} of{" "}
            {totals.population_total.toLocaleString()} people live in high or very-high susceptibility cells regardless
            of the weather.
          </p>
          <div className="mt-3 flex flex-wrap gap-2 text-sm">
            {cards(totals.tambons_by_live_impact_class).map(({ cls, n }) => (
              <span key={cls} className="flex items-center gap-2 rounded-lg border border-zinc-200 px-3 py-1 dark:border-zinc-800">
                <Badge cls={cls} /> {n} tambons
              </span>
            ))}
          </div>

          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[820px] border-collapse text-sm">
              <thead>
                <tr className="border-b border-zinc-200 text-left text-zinc-500 dark:border-zinc-800">
                  <th className="py-2 pr-4 font-medium">Tambon</th>
                  <th className="py-2 pr-4 font-medium">Province</th>
                  <th className="py-2 pr-3 font-medium">Terrain</th>
                  <th className="py-2 pr-3 text-right font-medium">Rain 24 h</th>
                  <th className="py-2 pr-3 text-right font-medium">Rain 72 h</th>
                  <th className="py-2 pr-3 text-right font-medium">Local P90</th>
                  <th className="py-2 pr-3 font-medium">vs local normal</th>
                  <th className="py-2 pr-3 font-medium">Live impact</th>
                  <th className="py-2 pr-3 text-right font-medium">People at risk</th>
                </tr>
              </thead>
              <tbody>
                {overlay.tambons.slice(0, 25).map((t) => (
                  <tr key={t.GID_3} className="border-b border-zinc-100 dark:border-zinc-900">
                    <td className="py-2 pr-4 font-medium">{t.NAME_3 ?? t.GID_3}</td>
                    <td className="py-2 pr-4 text-zinc-500">{t.NAME_1}</td>
                    <td className="py-2 pr-3">
                      <Badge cls={t.susceptibility_tier} />
                    </td>
                    <td className="py-2 pr-3 text-right tabular-nums">{t.gfs_rain_24h_mm?.toFixed(1) ?? "–"} mm</td>
                    <td className="py-2 pr-3 text-right tabular-nums">{t.gfs_rain_72h_mm?.toFixed(1) ?? "–"} mm</td>
                    <td className="py-2 pr-3 text-right tabular-nums">{t.local_p90_mm?.toFixed(0) ?? "–"} mm</td>
                    <td className="py-2 pr-3">
                      <Badge cls={t.rain_local_class_24h ?? t.rain_class_24h} />
                    </td>
                    <td className="py-2 pr-3">
                      <Badge cls={t.live_impact_class} />
                    </td>
                    <td className="py-2 pr-3 text-right tabular-nums">{t.population_at_elevated_risk.toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-xs text-zinc-500">
            Top 25 of {overlay.tambons.length.toLocaleString()} tambons, ordered by live impact class, then by people at
            risk. Rule: terrain factor (low = 1, moderate = 2, high = 3, from the share of 250 m cells that are high or very
            high) × 24 h rain class against the tambon&apos;s own climate (below P75 = 0, P75–P90 = 1, P90–P95 = 2, above
            P95 = 3) → 0–1 low, 2–3 moderate, 4–6 high, ≥ 7 very high.
            GFS cells are ~28 km wide, so neighbouring tambons often share one rainfall value.
          </p>
          <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300">
            {overlay.metadata.limitations.slice(0, 3).map((l) => (
              <p key={l} className="mb-1 last:mb-0">
                • {l}
              </p>
            ))}
          </div>
        </section>
      )}

      {overlay && <ScenarioPanel provinces={overlay.provinces.map((p) => p.NAME_1).sort()} />}
    </div>
  );
}
