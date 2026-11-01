import Link from "next/link";
import { api } from "@/lib/api";
import StatCard from "@/components/StatCard";
import Page from "@/components/Page";
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
    <Page
      title="Landslide impact in southern Thailand"
      description={
        <>
          A landslide early-warning pipeline for southern Thailand: a terrain/soil/lithology
          susceptibility model (<strong className="text-fg">where</strong>), NOAA GFS forecast rainfall
          (<strong className="text-fg">when</strong>, next 24&ndash;72 h), and an impact overlay against OSM buildings,
          critical facilities and WorldPop population to report what is actually affected.
        </>
      }
    >

      {error && (
        <div className="mb-6 note-danger">
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

          <div className="mt-6 grid gap-6 lg:grid-cols-2">
            <div className="card">
              <h2 className="card-title">Pipeline status</h2>
              <p className="card-desc">
                Live progress of the background data jobs and which downstream pieces are still pending.
              </p>
              <PipelineStatusList status={overview.pipeline_status} />
            </div>

            <div className="card">
              <h2 className="card-title">What you can do now</h2>
              <ul className="mt-3 space-y-3 text-sm">
                <li>
                  <Link href="/impact" className="font-medium text-accent hover:underline">
                    Live Impact map →
                  </Link>
                  <p className="text-muted">
                    The 250 m susceptibility map, buildings and critical facilities on a map; the
                    Early Warning page adds forecast rainfall and live impact per tambon.
                  </p>
                </li>
                <li>
                  <Link href="/warning" className="font-medium text-accent hover:underline">
                    Early Warning →
                  </Link>
                  <p className="text-muted">
                    The latest GFS rainfall forecast per tambon, the live impact table and a what-if rainfall
                    scenario.
                  </p>
                </li>
                <li>
                  <Link href="/model" className="font-medium text-accent hover:underline">
                    Model page →
                  </Link>
                  <p className="text-muted">
                    Methodology, per-model cross-validation/test metrics, thresholds and
                    calibration for the trained susceptibility model.
                  </p>
                </li>
              </ul>
            </div>
          </div>
        </>
      )}
    </Page>
  );
}
