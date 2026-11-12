"use client";

import { useMemo, useState } from "react";
import { createPortal } from "react-dom";
import type { OverlayTambon, TambonClasses } from "@/lib/api";

// Charts for the Live Impact map. They read the same per-tambon classes as the map (the GFS forecast or a what-if
// rainfall), so a change of rainfall repaints the map and the charts together. Marks are plain HTML: bars are divs
// sized in percent, which keeps them sharp at any panel width and needs no chart library.

export interface ClassColor {
  key: string;
  label: string;
  color: string;
}

const DAY_HOURS = [24, 48, 72, 96, 120] as const;
type RainKey = "gfs_rain_24h_mm" | "gfs_rain_48h_mm" | "gfs_rain_72h_mm" | "gfs_rain_96h_mm" | "gfs_rain_120h_mm";

/** Rain falling on each of the next five days: the cumulative totals differenced. Days without data are null. */
export function dailyRain(t: OverlayTambon): Array<number | null> {
  const cumulative = DAY_HOURS.map((h) => t[`gfs_rain_${h}h_mm` as RainKey] ?? null);
  return cumulative.map((total, i) => {
    const before = i === 0 ? 0 : cumulative[i - 1];
    return total === null || before === null ? null : Math.max(0, total - before);
  });
}

/** Class of one day's rain against the tambon's own wet-day percentiles (same rule as the 24 h rain class). */
export function rainClassOf(mm: number | null, t: OverlayTambon): string | null {
  const { local_p75_mm: p75, local_p90_mm: p90, local_p95_mm: p95 } = t;
  if (mm === null || p75 == null || p90 == null || p95 == null) return null;
  return mm >= p95 ? "above_p95" : mm >= p90 ? "p90_p95" : mm >= p75 ? "p75_p90" : "below_p75";
}

interface Tip {
  x: number;
  y: number;
  title: string;
  rows: Array<{ color?: string; label: string; value: string }>;
}

function Tooltip({ tip }: { tip: Tip | null }) {
  if (!tip || typeof document === "undefined") return null;
  const left = Math.min(tip.x + 14, window.innerWidth - 200);
  // Rendered on <body>: the map panels use a backdrop filter, which would otherwise become the tooltip's
  // positioning box and push it off screen.
  return createPortal(
    <div
      role="tooltip"
      className="pointer-events-none fixed z-50 w-max max-w-[13rem] rounded-lg border border-line bg-surface px-2.5 py-2 text-xs shadow-lg"
      style={{ left, top: tip.y - 12, transform: "translateY(-100%)" }}
    >
      <div className="mb-1 font-semibold text-fg">{tip.title}</div>
      {tip.rows.map((r) => (
        <div key={r.label} className="flex items-center justify-between gap-4">
          <span className="flex items-center gap-1.5 text-muted">
            {r.color && <span className="h-2 w-2 shrink-0 rounded-[2px]" style={{ background: r.color }} />}
            {r.label}
          </span>
          <span className="font-medium tabular-nums text-fg">{r.value}</span>
        </div>
      ))}
    </div>,
    document.body
  );
}

function ChartFrame({ title, note, legend, children }: { title: string; note?: string; legend?: ClassColor[]; children: React.ReactNode }) {
  return (
    <figure className="flex min-w-0 flex-col">
      <figcaption>
        <div className="text-xs font-semibold text-fg">{title}</div>
        {note && <div className="text-[11px] leading-snug text-subtle">{note}</div>}
      </figcaption>
      {legend && (
        <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-muted">
          {legend.map((c) => (
            <span key={c.key} className="flex items-center gap-1.5">
              <span className="h-2 w-2 shrink-0 rounded-[2px]" style={{ background: c.color }} />
              {c.label}
            </span>
          ))}
        </div>
      )}
      <div className="mt-2 min-h-0 flex-1">{children}</div>
    </figure>
  );
}

const Empty = ({ children }: { children: React.ReactNode }) => (
  <p className="rounded-lg bg-surface-2 px-2.5 py-3 text-[11px] leading-snug text-muted">{children}</p>
);

/** Horizontal bars, one row per category; `segments` stack from the baseline with a 2 px gap. */
function BarRows({
  rows,
  max,
  onTip,
}: {
  rows: Array<{ label: string; total: number; valueLabel: string; segments: Array<{ value: number; color: string }>; tip: Tip["rows"] }>;
  max: number;
  onTip: (tip: Tip | null) => void;
}) {
  return (
    <div className="space-y-[3px]">
      {rows.map((row) => (
        <div
          key={row.label}
          className="group flex items-center gap-2 rounded px-1 py-[1px] text-[11px] hover:bg-surface-2"
          onMouseMove={(e) => onTip({ x: e.clientX, y: e.clientY, title: row.label, rows: row.tip })}
          onMouseLeave={() => onTip(null)}
        >
          <span className="w-[7.5rem] shrink-0 truncate text-muted">{row.label}</span>
          <span className="flex h-2 flex-1 items-stretch gap-[2px]">
            {row.segments
              .filter((s) => s.value > 0)
              .map((s, i, shown) => (
                <span
                  key={s.color}
                  className={i === shown.length - 1 ? "rounded-r-[4px]" : ""}
                  style={{ width: `${(100 * s.value) / max}%`, background: s.color, minWidth: 2 }}
                />
              ))}
          </span>
          <span className="w-10 shrink-0 text-right font-medium tabular-nums text-fg">{row.valueLabel}</span>
        </div>
      ))}
    </div>
  );
}

const compact = (v: number) => (v >= 10_000 ? `${Math.round(v / 1000)}k` : v >= 1000 ? `${(v / 1000).toFixed(1)}k` : String(Math.round(v)));

export default function ImpactCharts({
  tambons,
  classes,
  scenarioMm,
  impactColors,
  rainColors,
}: {
  tambons: OverlayTambon[];
  classes: TambonClasses;
  scenarioMm: number | null;
  impactColors: ClassColor[];
  rainColors: ClassColor[];
}) {
  const [tip, setTip] = useState<Tip | null>(null);
  const basis = scenarioMm === null ? "GFS forecast, next 24 h" : `What-if: ${scenarioMm} mm in 24 h everywhere`;

  const byProvince = useMemo(() => {
    const map = new Map<string, { very_high: number; high: number; moderate: number; people: number; tambons: number }>();
    for (const t of tambons) {
      const name = t.NAME_1 ?? "Unknown";
      const row = map.get(name) ?? { very_high: 0, high: 0, moderate: 0, people: 0, tambons: 0 };
      const impact = classes[t.GID_3]?.[0] ?? t.live_impact_class;
      row.tambons += 1;
      if (impact === "very_high" || impact === "high" || impact === "moderate") row[impact] += 1;
      if (impact === "very_high" || impact === "high") row.people += t.population_high_vh;
      map.set(name, row);
    }
    return [...map.entries()].map(([name, v]) => ({ name, ...v, flagged: v.very_high + v.high + v.moderate }));
  }, [tambons, classes]);

  const impactRows = useMemo(
    () =>
      byProvince
        .filter((p) => p.flagged > 0)
        .sort((a, b) => b.flagged - a.flagged || b.very_high + b.high - (a.very_high + a.high) || a.name.localeCompare(b.name))
        .slice(0, 6),
    [byProvince]
  );
  const peopleRows = useMemo(
    () => byProvince.filter((p) => p.people > 0).sort((a, b) => b.people - a.people || a.name.localeCompare(b.name)).slice(0, 6),
    [byProvince]
  );

  // Tambons whose rain on each day reaches their own P75 or more, from the GFS forecast (not the what-if amount).
  const outlook = useMemo(() => {
    const days = DAY_HOURS.map(() => ({ above_p95: 0, p90_p95: 0, p75_p90: 0, known: 0 }));
    for (const t of tambons) {
      dailyRain(t).forEach((mm, i) => {
        const cls = rainClassOf(mm, t);
        if (cls === null) return;
        days[i].known += 1;
        if (cls !== "below_p75") days[i][cls as "above_p95" | "p90_p95" | "p75_p90"] += 1;
      });
    }
    return days.map((d, i) => ({ ...d, day: i + 1, total: d.above_p95 + d.p90_p95 + d.p75_p90 })).filter((d) => d.known > 0);
  }, [tambons]);

  const color = (list: ClassColor[], key: string) => list.find((c) => c.key === key)?.color ?? "var(--subtle)";
  const impactLegend = impactColors.filter((c) => ["very_high", "high", "moderate"].includes(c.key));
  const rainLegend = rainColors.filter((c) => ["above_p95", "p90_p95", "p75_p90"].includes(c.key));
  const impactMax = Math.max(1, ...impactRows.map((p) => p.flagged));
  const peopleMax = Math.max(1, ...peopleRows.map((p) => p.people));
  const outlookMax = Math.max(1, ...outlook.map((d) => d.total));

  return (
    <div className="grid gap-x-6 gap-y-4 [grid-template-columns:repeat(auto-fit,minmax(13.5rem,1fr))]">
      <ChartFrame title="Tambons rated moderate or above" note={`${basis}. Top provinces.`} legend={impactLegend}>
        {impactRows.length ? (
          <BarRows
            max={impactMax}
            onTip={setTip}
            rows={impactRows.map((p) => ({
              label: p.name,
              total: p.flagged,
              valueLabel: String(p.flagged),
              segments: (["very_high", "high", "moderate"] as const).map((k) => ({ value: p[k], color: color(impactColors, k) })),
              tip: [
                ...impactLegend.map((c) => ({ color: c.color, label: c.label, value: String(p[c.key as "very_high" | "high" | "moderate"]) })),
                { label: "Tambons in province", value: String(p.tambons) },
              ],
            }))}
          />
        ) : (
          <Empty>No tambon is rated moderate or above under this rain.</Empty>
        )}
      </ChartFrame>

      <ChartFrame title="People at elevated risk" note="On high or very-high ground, in tambons rated high or above.">
        {peopleRows.length ? (
          <BarRows
            max={peopleMax}
            onTip={setTip}
            rows={peopleRows.map((p) => ({
              label: p.name,
              total: p.people,
              valueLabel: compact(p.people),
              segments: [{ value: p.people, color: "var(--accent)" }],
              tip: [
                { label: "People at elevated risk", value: p.people.toLocaleString() },
                { label: "Tambons high or above", value: String(p.very_high + p.high) },
              ],
            }))}
          />
        ) : (
          <Empty>No one is counted at elevated risk: that needs a tambon rated high or above.</Empty>
        )}
      </ChartFrame>

      <ChartFrame title="Tambons with unusual rain, by day" note="GFS forecast: daily rain at or above the tambon's own P75. Days 4–5 are an outlook." legend={rainLegend}>
        {outlook.length ? (
          <div className="flex h-[6.25rem] items-end gap-2 border-b border-line px-1">
            {outlook.map((d) => (
              <div
                key={d.day}
                className="flex h-full flex-1 flex-col items-center justify-end rounded-t hover:bg-surface-2"
                style={{ opacity: d.day > 3 ? 0.6 : 1 }}
                onMouseMove={(e) =>
                  setTip({
                    x: e.clientX,
                    y: e.clientY,
                    title: `Day ${d.day}${d.day > 3 ? " (outlook)" : ""}`,
                    rows: [
                      ...rainLegend.map((c) => ({ color: c.color, label: c.label, value: String(d[c.key as "above_p95" | "p90_p95" | "p75_p90"]) })),
                      { label: "Tambons with data", value: d.known.toLocaleString() },
                    ],
                  })
                }
                onMouseLeave={() => setTip(null)}
              >
                <span className="mb-0.5 text-[11px] font-medium tabular-nums text-fg">{d.total}</span>
                <span className="flex w-full max-w-[1.75rem] flex-col-reverse gap-[2px]" style={{ height: `${(78 * d.total) / outlookMax}%` }}>
                  {(["p75_p90", "p90_p95", "above_p95"] as const)
                    .filter((k) => d[k] > 0)
                    .map((k, i, shown) => (
                      <span
                        key={k}
                        className={`dark:ring-1 dark:ring-inset dark:ring-white/25 ${i === shown.length - 1 ? "rounded-t-[4px]" : ""}`}
                        style={{ flexGrow: d[k], flexBasis: 0, minHeight: 2, background: color(rainColors, k) }}
                      />
                    ))}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <Empty>The forecast has no daily totals yet.</Empty>
        )}
        {outlook.length > 0 && (
          <div className="mt-1 flex gap-2 px-1 text-[11px] text-muted">
            {outlook.map((d) => (
              <span key={d.day} className="flex-1 text-center">
                Day {d.day}
              </span>
            ))}
          </div>
        )}
      </ChartFrame>

      {/* Table view of the same numbers, for screen readers. */}
      <table className="sr-only">
        <caption>Tambons rated moderate or above and people at elevated risk, by province ({basis})</caption>
        <thead>
          <tr>
            <th>Province</th><th>Very high</th><th>High</th><th>Moderate</th><th>People at elevated risk</th>
          </tr>
        </thead>
        <tbody>
          {byProvince.map((p) => (
            <tr key={p.name}>
              <td>{p.name}</td><td>{p.very_high}</td><td>{p.high}</td><td>{p.moderate}</td><td>{p.people}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <Tooltip tip={tip} />
    </div>
  );
}

/** One tambon's rain on each of the next five days, against its own P75 and P95 (dashed). Used in the details panel. */
export function RainOutlook({ tambon, rainColors }: { tambon: OverlayTambon; rainColors: ClassColor[] }) {
  const days = dailyRain(tambon);
  if (days.every((d) => d === null)) return null;
  const p75 = tambon.local_p75_mm ?? null;
  const p95 = tambon.local_p95_mm ?? null;
  const top = Math.max(1, ...days.map((d) => d ?? 0), (p95 ?? 0) * 1.08);
  const refLine = (value: number | null, label: string) =>
    value === null ? null : (
      <div className="pointer-events-none absolute inset-x-0 border-t border-dashed border-subtle" style={{ bottom: `${(100 * value) / top}%` }}>
        <span className="absolute -top-[0.8rem] right-0 bg-surface px-0.5 text-[10px] leading-none text-subtle">
          {label} {value.toFixed(0)}
        </span>
      </div>
    );
  return (
    <figure className="mt-2 border-t border-line pt-2">
      <figcaption className="eyebrow mb-1">Daily rain, next 5 days (mm)</figcaption>
      <div className="relative flex h-20 items-end gap-2 border-b border-line pr-12">
        {refLine(p95, "P95")}
        {refLine(p75, "P75")}
        {days.map((mmDay, i) => {
          const cls = rainClassOf(mmDay, tambon);
          const fill = rainColors.find((c) => c.key === cls)?.color ?? "var(--line)";
          return (
            <div key={i} className="relative z-10 flex h-full flex-1 flex-col items-center justify-end" style={{ opacity: i > 2 ? 0.6 : 1 }}
              title={mmDay === null ? `Day ${i + 1}: no data` : `Day ${i + 1}: ${mmDay.toFixed(1)} mm (${rainColors.find((c) => c.key === cls)?.label ?? "no local thresholds"})`}>
              <span className="mb-0.5 text-[10px] font-medium tabular-nums text-fg">{mmDay === null ? "–" : mmDay.toFixed(mmDay >= 10 ? 0 : 1)}</span>
              <span
                className="w-full max-w-[1.5rem] rounded-t-[4px] border border-b-0 border-black/10 dark:border-white/15"
                style={{ height: `${mmDay === null ? 0 : Math.max(2, (100 * mmDay) / top * 0.82)}%`, background: fill }}
              />
            </div>
          );
        })}
      </div>
      <div className="mt-1 flex gap-2 pr-12 text-[10px] text-muted">
        {days.map((_, i) => (
          <span key={i} className="flex-1 text-center">
            D{i + 1}
          </span>
        ))}
      </div>
      <p className="mt-1 text-[10px] leading-snug text-subtle">Darker bars are more unusual for this tambon (its own P75, P90, P95). Days 4–5 are an outlook.</p>
    </figure>
  );
}
