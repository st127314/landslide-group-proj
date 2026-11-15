"use client";

import { useEffect, useState } from "react";
import { api, type ScenarioResult, type ScenarioTambon } from "@/lib/api";
import { fmtInt } from "@/lib/classes";
import { ClassCounts } from "@/components/Badge";
import { Details, LABEL, LINK, Section } from "@/components/Section";
import TambonTable, { type TambonRow } from "@/components/TambonTable";

const PRESETS = [0, 25, 50, 75, 100, 150];
const SLIDER_MAX = 200;
const INPUT_MAX = 1500;
const FIELD = "min-h-11 rounded-lg border border-line bg-surface px-3 text-sm";

function toRow(t: ScenarioTambon): TambonRow {
  return {
    id: t.GID_3,
    name: t.NAME_3 ?? t.GID_3,
    province: t.NAME_1,
    impact: t.impact_class,
    rainClass: t.rain_local_class_24h,
    terrain: t.susceptibility_tier,
    rain24: t.rain_24h_mm,
    p90: t.local_p90_mm,
    people: t.population_at_elevated_risk,
  };
}

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
    <Section
      id="scenario"
      title="What if it rains harder?"
      description={
        <>
          Choose an amount of rain for the next 24 hours and where it falls. The same impact rule is re-applied to the
          stored terrain and exposure figures; no weather model is run.
        </>
      }
    >
      <div className="grid gap-5 md:grid-cols-[2fr_1fr]">
        <div>
          <label className="text-sm font-medium" htmlFor="rain">
            Rain in 24 hours: <span className="tabular-nums">{rain} mm</span>
          </label>
          <input
            id="rain"
            type="range"
            min={0}
            max={SLIDER_MAX}
            step={5}
            value={Math.min(rain, SLIDER_MAX)}
            onChange={(e) => setRain(Number(e.target.value))}
            className="mt-2 h-6 w-full accent-[var(--accent)]"
          />
          <div className="mt-2 flex flex-wrap items-center gap-2" role="group" aria-label="Preset amounts">
            {PRESETS.map((mm) => (
              <button
                key={mm}
                type="button"
                aria-pressed={rain === mm}
                onClick={() => setRain(mm)}
                className={`min-h-11 min-w-16 rounded-lg border px-3 text-sm tabular-nums transition-colors ${
                  rain === mm ? "border-accent bg-accent text-accent-fg" : "border-line hover:bg-surface-2"
                }`}
              >
                {mm} mm
              </button>
            ))}
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <label className="text-sm" htmlFor="rain-exact">
              Or type an amount (0–{INPUT_MAX.toLocaleString("en-US")} mm):
            </label>
            <input
              id="rain-exact"
              type="number"
              inputMode="numeric"
              min={0}
              max={INPUT_MAX}
              value={rain}
              onChange={(e) => setRain(Math.max(0, Math.min(INPUT_MAX, Number(e.target.value) || 0)))}
              className={`${FIELD} w-28 tabular-nums`}
            />
          </div>
          <p className="mt-1 text-xs text-muted">The slider covers 0–{SLIDER_MAX} mm; larger amounts can be typed.</p>
        </div>
        <div>
          <label className="text-sm font-medium" htmlFor="province">
            Where it falls
          </label>
          <select
            id="province"
            value={province}
            onChange={(e) => setProvince(e.target.value)}
            className={`${FIELD} mt-2 w-full`}
          >
            <option value="">All southern provinces</option>
            {provinces.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
          <p className="mt-1 text-xs text-muted">When one province is chosen, the others keep the live forecast.</p>
        </div>
      </div>

      {error && (
        <div role="alert" className="note-danger mt-4">
          The scenario could not be calculated. Try again in a moment. <span className="text-xs">({error})</span>
        </div>
      )}

      {s && result && (
        <div className={`mt-5 transition-opacity ${loading ? "opacity-60" : ""}`} aria-busy={loading}>
          <h3 className="text-sm font-semibold" aria-live="polite">
            Result: {result.scenario.description}
          </h3>
          <dl className="mt-3 grid grid-cols-2 gap-3 lg:grid-cols-4">
            {[
              ["People at elevated risk", s.population_at_elevated_risk],
              ["Buildings at elevated risk", s.buildings_at_elevated_risk],
              ["Facilities at elevated risk", s.facilities_at_elevated_risk],
              ["Tambons with rain above their P95", s.tambons_above_p95],
            ].map(([label, value]) => (
              <div key={label} className="rounded-lg border border-line bg-surface-2 p-3">
                <dt className={LABEL}>{label}</dt>
                <dd className="mt-1 text-xl font-semibold tabular-nums">{fmtInt(value as number)}</dd>
              </div>
            ))}
          </dl>
          <div className="mt-3">
            <ClassCounts kind="impact" counts={s.tambons_by_impact_class} />
          </div>

          <h3 className="mb-2 mt-5 text-sm font-semibold">
            The {result.tambons.length} tambons most affected in this scenario
          </h3>
          <TambonTable rows={result.tambons.map(toRow)} label="Tambons most affected in the scenario" rainDigits={0} />
          <p className="mt-3 max-w-4xl text-xs leading-relaxed text-muted">
            Ordered by impact class, then by people at elevated risk. The classes stop rising once rain passes a
            tambon&apos;s P95 (26–69 mm in the south, typically about 38 mm), so 100 mm and 250 mm give the same answer.
            The columns are explained under{" "}
            <a href="#read" className={LINK}>
              How to read this page
            </a>
            .
          </p>
          <div className="mt-3">
            <Details summary="Notes on what a scenario can and cannot show">
              <ul className="list-disc space-y-2 pl-5">
                {result.limitations.map((l) => (
                  <li key={l}>{l}</li>
                ))}
              </ul>
            </Details>
          </div>
        </div>
      )}
    </Section>
  );
}
