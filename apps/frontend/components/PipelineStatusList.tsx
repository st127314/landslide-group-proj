import { CircleCheck, LoaderCircle } from "lucide-react";
import type { PipelineStatus, JobStatus } from "@/lib/api";
import { Details } from "@/components/Section";

// Plain names for the four pipeline steps. The API's own labels and notes (script and file names) are kept behind
// the "Technical detail" expander for the people who run the pipeline.
const STEPS: Array<{ key: keyof PipelineStatus; name: string; what: string }> = [
  { key: "factor_grid", name: "Terrain factors", what: "Slope, soil, geology and the other inputs, sampled every 250 m." },
  { key: "susceptibility_raster", name: "Susceptibility map", what: "Every 250 m cell scored by the model." },
  { key: "live_forecast", name: "Rainfall forecast", what: "The latest GFS run, summed per tambon." },
  { key: "impact_overlay", name: "Live impact", what: "Terrain, forecast rain and exposure combined per tambon." },
];

function Row({ name, what, job }: { name: string; what: string; job: JobStatus }) {
  const hasCount = typeof job.total === "number" && job.total > 0 && job.complete !== undefined;
  const pct = hasCount ? Math.round((job.complete! / job.total!) * 100) : null;
  return (
    <li className="flex items-start gap-3 py-3">
      {job.done ? (
        <CircleCheck className="mt-0.5 h-5 w-5 shrink-0 text-emerald-600 dark:text-emerald-400" aria-hidden />
      ) : (
        <LoaderCircle className="mt-0.5 h-5 w-5 shrink-0 text-amber-600 dark:text-amber-400" aria-hidden />
      )}
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline justify-between gap-x-3">
          <span className="text-sm font-medium">{name}</span>
          <span className="text-xs font-medium text-muted">
            {job.done ? "Ready" : "In progress"}
            {hasCount && !job.done && (
              <span className="tabular-nums">
                {" "}
                · {job.complete!.toLocaleString("en-US")} of {job.total!.toLocaleString("en-US")} ({pct}%)
              </span>
            )}
          </span>
        </div>
        <p className="mt-0.5 text-xs leading-snug text-muted">
          {what}
          {hasCount && job.done && <span className="tabular-nums"> {job.total!.toLocaleString("en-US")} cells.</span>}
        </p>
        {pct !== null && !job.done && (
          <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-surface-2">
            <div className="h-full rounded-full bg-amber-500" style={{ width: `${pct}%` }} />
          </div>
        )}
      </div>
    </li>
  );
}

export default function PipelineStatusList({ status }: { status: PipelineStatus }) {
  return (
    <>
      <ul className="divide-y divide-line">
        {STEPS.map((s) => (
          <Row key={s.key} name={s.name} what={s.what} job={status[s.key]} />
        ))}
      </ul>
      <div className="mt-3">
        <Details summary="Technical detail (scripts, files, UTC times)">
          <dl className="space-y-3">
            {STEPS.map((s) => (
              <div key={s.key}>
                <dt className="font-medium text-fg">{status[s.key].label}</dt>
                {status[s.key].note && <dd className="mt-0.5 text-xs [overflow-wrap:anywhere]">{status[s.key].note}</dd>}
              </div>
            ))}
          </dl>
        </Details>
      </div>
    </>
  );
}
