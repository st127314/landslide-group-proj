import Link from "next/link";
import { api } from "@/lib/api";
import StatCard from "@/components/StatCard";
import PipelineStatusList from "@/components/PipelineStatusList";

function fmt(n: number | null | undefined, digits = 0) {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return n.toLocaleString(undefined, { maximumFractionDigits: digits });
}

export default async function OverviewPage() {
  let overview: Awaited<ReturnType<typeof api.overview>> | null = null;
  let error: string | null = null;
  try {
    overview = await api.overview();
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  return (
    <div className="mx-auto w-full max-w-6xl flex-1 px-6 py-10">
      <div className="mb-8">
        <h1 className="text-3xl font-bold tracking-tight">Landslide Impact — Overview</h1>
        <p className="mt-2 max-w-3xl text-zinc-600 dark:text-zinc-400">
          A landslide early-warning pipeline for southern Thailand: a terrain/soil/lithology
          susceptibility model (<strong>where</strong>), NOAA GFS forecast rainfall
          (<strong>when</strong>, next 24&ndash;72 h), and an impact overlay against OSM buildings,
          critical facilities and WorldPop population to report what is actually affected.
        </p>
      </div>

      {error && (
        <div className="mb-6 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
          Could not reach the API at the configured <code>NEXT_PUBLIC_API_URL</code>: {error}.
          Make sure the backend is running (<code>uvicorn app.main:app --port 8000</code> from{" "}
          <code>apps/backend</code>).
        </div>
      )}

      {overview && (
        <>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
            <StatCard label="Landslide events" value={fmt(overview.landslide_events)} />
            <StatCard
              label="Non-landslide samples"
              value={fmt(overview.non_landslide_samples)}
              sub="Paired pseudo-absence points"
            />
            <StatCard label="Buildings mapped" value={fmt(overview.buildings_mapped)} sub="OSM footprints" />
            <StatCard label="Critical facilities" value={fmt(overview.facilities_mapped)} sub="Hospitals, schools, emergency, transport, worship" />
            <StatCard
              label="Population (study area)"
              value={fmt(overview.population_estimate)}
              sub={`WorldPop ${overview.population_source_year}, constrained`}
            />
            <StatCard
              label="Best model ROC-AUC"
              value={overview.best_model_roc_auc ? overview.best_model_roc_auc.toFixed(3) : "—"}
              sub={overview.best_model ?? undefined}
            />
          </div>

          <div className="mt-8 grid gap-6 lg:grid-cols-2">
            <div className="rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-900">
              <h2 className="text-lg font-semibold">Pipeline status</h2>
              <p className="mt-1 text-sm text-zinc-500">
                Live progress of the background data jobs and which downstream pieces are still pending.
              </p>
              <PipelineStatusList status={overview.pipeline_status} />
            </div>

            <div className="rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-900">
              <h2 className="text-lg font-semibold">What you can do now</h2>
              <ul className="mt-3 space-y-3 text-sm">
                <li>
                  <Link href="/impact" className="font-medium text-blue-600 hover:underline dark:text-blue-400">
                    Live Impact map →
                  </Link>
                  <p className="text-zinc-500">
                    The 250 m susceptibility map, buildings and critical facilities on a map; the
                    Early Warning page adds forecast rainfall and live impact per tambon.
                  </p>
                </li>
                <li>
                  <Link href="/model" className="font-medium text-blue-600 hover:underline dark:text-blue-400">
                    Model page →
                  </Link>
                  <p className="text-zinc-500">
                    Methodology, per-model cross-validation/test metrics, thresholds and
                    calibration for the trained susceptibility model.
                  </p>
                </li>
              </ul>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
