"use client";

import { useEffect, useState } from "react";
import { api, type ScenarioResult } from "@/lib/api";
import { Badge } from "@/components/Badge";

const PRESETS = [0, 25, 50, 75, 100, 150];
const ORDER = ["very_high", "high", "moderate", "low", "not_assessed"];

export default function ScenarioPanel({ provinces }: { provinces: string[] }) {
  const [rain, setRain] = useState(50);
  const [province, setProvince] = useState("");
  const [result, setResult] = useState<ScenarioResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      setLoading(true);
      try {
        setResult(await api.scenario(rain, province || null, 15, controller.signal));
        setError(null);
      } catch (e) {
        if ((e as Error).name !== "AbortError") setError(e instanceof Error ? e.message : String(e));
      } finally {
        setLoading(false);
      }
    }, 250);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [rain, province]);

  const s = result?.summary;
  return (
    <section className="mt-6 rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-900">
      <h2 className="text-lg font-semibold">What-if rainfall scenario</h2>
      <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
        Pick an amount of rain for the next 24 hours and where it falls. The same rule as above is re-applied, with each
        tambon&apos;s own rainfall climate as the yardstick. It runs instantly on stored numbers: no forecast model, no
        assistant.
      </p>

      <div className="mt-4 grid gap-4 md:grid-cols-[2fr_1fr]">
        <div>
          <label className="text-sm font-medium" htmlFor="rain">
            24 h rainfall: <span className="tabular-nums">{rain} mm</span>
          </label>
          <input
            id="rain"
            type="range"
            min={0}
            max={200}
            step={5}
            value={Math.min(rain, 200)}
            onChange={(e) => setRain(Number(e.target.value))}
            className="mt-2 w-full"
          />
          <div className="mt-2 flex flex-wrap gap-2">
            {PRESETS.map((mm) => (
              <button
                key={mm}
                onClick={() => setRain(mm)}
                className={`rounded-lg border px-3 py-1 text-xs ${
                  rain === mm
                    ? "border-zinc-900 bg-zinc-900 text-white dark:border-zinc-100 dark:bg-zinc-100 dark:text-zinc-900"
                    : "border-zinc-200 hover:bg-zinc-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
                }`}
              >
                {mm} mm
              </button>
            ))}
            <input
              aria-label="Rainfall in mm"
              type="number"
              min={0}
              max={1500}
              value={rain}
              onChange={(e) => setRain(Math.max(0, Math.min(1500, Number(e.target.value) || 0)))}
              className="w-24 rounded-lg border border-zinc-200 bg-transparent px-2 py-1 text-xs dark:border-zinc-700"
            />
          </div>
        </div>
        <div>
          <label className="text-sm font-medium" htmlFor="province">
            Where
          </label>
          <select
            id="province"
            value={province}
            onChange={(e) => setProvince(e.target.value)}
            className="mt-2 w-full rounded-lg border border-zinc-200 bg-transparent px-2 py-2 text-sm dark:border-zinc-700"
          >
            <option value="">All southern provinces</option>
            {provinces.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
          <p className="mt-1 text-xs text-zinc-500">Other provinces keep the live forecast.</p>
        </div>
      </div>

      {error && (
        <div className="mt-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
          {error}
        </div>
      )}

      {s && result && (
        <div className={loading ? "opacity-60" : ""}>
          <p className="mt-4 text-sm font-medium">{result.scenario.description}</p>
          <div className="mt-2 grid gap-3 sm:grid-cols-4">
            <div className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
              <div className="text-xs text-zinc-500">People at elevated risk</div>
              <div className="text-lg font-semibold tabular-nums">{s.population_at_elevated_risk.toLocaleString()}</div>
            </div>
            <div className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
              <div className="text-xs text-zinc-500">Buildings</div>
              <div className="text-lg font-semibold tabular-nums">{s.buildings_at_elevated_risk.toLocaleString()}</div>
            </div>
            <div className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
              <div className="text-xs text-zinc-500">Critical facilities</div>
              <div className="text-lg font-semibold tabular-nums">{s.facilities_at_elevated_risk.toLocaleString()}</div>
            </div>
            <div className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
              <div className="text-xs text-zinc-500">Tambons above their P95</div>
              <div className="text-lg font-semibold tabular-nums">{s.tambons_above_p95.toLocaleString()}</div>
            </div>
          </div>
          <div className="mt-3 flex flex-wrap gap-2 text-sm">
            {ORDER.filter((k) => s.tambons_by_impact_class[k]).map((k) => (
              <span key={k} className="flex items-center gap-2 rounded-lg border border-zinc-200 px-3 py-1 dark:border-zinc-800">
                <Badge cls={k} /> {s.tambons_by_impact_class[k]} tambons
              </span>
            ))}
          </div>

          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[760px] border-collapse text-sm">
              <thead>
                <tr className="border-b border-zinc-200 text-left text-zinc-500 dark:border-zinc-800">
                  <th className="py-2 pr-4 font-medium">Tambon</th>
                  <th className="py-2 pr-4 font-medium">Province</th>
                  <th className="py-2 pr-3 font-medium">Terrain</th>
                  <th className="py-2 pr-3 text-right font-medium">Rain 24 h</th>
                  <th className="py-2 pr-3 text-right font-medium">Local P90</th>
                  <th className="py-2 pr-3 font-medium">vs local normal</th>
                  <th className="py-2 pr-3 font-medium">Impact</th>
                  <th className="py-2 pr-3 text-right font-medium">People at risk</th>
                </tr>
              </thead>
              <tbody>
                {result.tambons.map((t) => (
                  <tr key={t.GID_3} className="border-b border-zinc-100 dark:border-zinc-900">
                    <td className="py-2 pr-4 font-medium">{t.NAME_3 ?? t.GID_3}</td>
                    <td className="py-2 pr-4 text-zinc-500">{t.NAME_1}</td>
                    <td className="py-2 pr-3">
                      <Badge cls={t.susceptibility_tier} />
                    </td>
                    <td className="py-2 pr-3 text-right tabular-nums">{t.rain_24h_mm?.toFixed(0) ?? "–"} mm</td>
                    <td className="py-2 pr-3 text-right tabular-nums">{t.local_p90_mm?.toFixed(0) ?? "–"} mm</td>
                    <td className="py-2 pr-3">{t.rain_local_class_24h && <Badge cls={t.rain_local_class_24h} />}</td>
                    <td className="py-2 pr-3">
                      <Badge cls={t.impact_class} />
                    </td>
                    <td className="py-2 pr-3 text-right tabular-nums">{t.population_at_elevated_risk.toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-xs text-zinc-500">
            Top 15 tambons by impact class, then people at risk. Terrain × rain: no unusual rain means low everywhere;
            flat terrain never exceeds moderate; very high needs the steepest terrain and rain above that tambon&apos;s
            P95. Classes saturate once rain passes a tambon&apos;s P95 (about 40–70 mm in the south), so 100 mm and 250 mm
            give the same answer.
          </p>
          <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300">
            {result.limitations.map((l) => (
              <p key={l} className="mb-1 last:mb-0">
                • {l}
              </p>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
