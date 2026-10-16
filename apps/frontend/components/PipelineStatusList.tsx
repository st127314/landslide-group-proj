import type { PipelineStatus, JobStatus } from "@/lib/api";

function Row({ job }: { job: JobStatus }) {
  const pct =
    job.total && job.total > 0 && job.complete !== undefined
      ? Math.round((job.complete / job.total) * 100)
      : null;
  return (
    <li className="flex items-start gap-3 py-3">
      <span
        className={`mt-1 h-2.5 w-2.5 shrink-0 rounded-full ${
          job.done ? "bg-emerald-500" : "bg-amber-500 animate-pulse"
        }`}
      />
      <div className="flex-1">
        <div className="flex items-center justify-between gap-2">
          <span className="text-sm font-medium">{job.label}</span>
          {pct !== null && (
            <span className="text-xs tabular-nums text-zinc-500">
              {job.complete}/{job.total} ({pct}%)
            </span>
          )}
        </div>
        {pct !== null && (
          <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-800">
            <div
              className="h-full rounded-full bg-amber-500 transition-all"
              style={{ width: `${pct}%` }}
            />
          </div>
        )}
        {job.note && <p className="mt-1 text-xs text-zinc-500">{job.note}</p>}
      </div>
    </li>
  );
}

export default function PipelineStatusList({ status }: { status: PipelineStatus }) {
  const jobs = [
    status.factor_grid,
    status.susceptibility_raster,
    status.live_forecast,
    status.impact_overlay,
  ];
  return (
    <ul className="divide-y divide-zinc-200 dark:divide-zinc-800">
      {jobs.map((job) => (
        <Row key={job.label} job={job} />
      ))}
    </ul>
  );
}
