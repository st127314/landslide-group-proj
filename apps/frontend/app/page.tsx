import Link from "next/link";
import { api } from "@/lib/api";
import StatCard from "@/components/StatCard";
import Page from "@/components/Page";
import { ArrowRight, Building2, ChartColumn, CircleDashed, CloudRain, Hospital, Mountain, Users } from "lucide-react";
import PipelineStatusList from "@/components/PipelineStatusList";

const COMPONENTS = [
  {
    icon: Mountain,
    step: "Where",
    title: "Terrain susceptibility",
    text: "A machine-learning model trained on 6,180 mapped landslides rates every 250 m cell from very low to very high, using terrain, soil, geology, vegetation and land-cover factors.",
  },
  {
    icon: CloudRain,
    step: "When",
    title: "Rainfall forecast",
    text: "The NOAA GFS forecast for the next 24 hours, with totals to 5 days, is compared with each sub-district's own 30-year rainfall record to flag rain that is unusually heavy for that place.",
  },
  {
    icon: Users,
    step: "Who is affected",
    title: "Exposure",
    text: "Population (WorldPop), buildings and public facilities (OpenStreetMap) are matched to the susceptibility map and the forecast to count what is at elevated risk.",
  },
];

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
      title="Landslide risk and impact in southern Thailand"
      description={
        <>
          A decision-support tool for Thailand&apos;s 14 southern provinces. It shows which terrain is most prone to
          landslides, where the rain forecast for the next 24 hours to 5 days is unusually heavy for the area, and how
          many people, buildings and public facilities lie in the most susceptible places.
        </>
      }
    >
      <section className="mb-6 grid gap-4 md:grid-cols-3">
        {COMPONENTS.map(({ icon: Icon, step, title, text }) => (
          <div key={title} className="card p-4">
            <div className="flex items-center gap-3">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent">
                <Icon className="h-5 w-5" aria-hidden />
              </span>
              <div>
                <div className="eyebrow">{step}</div>
                <div className="text-sm font-semibold">{title}</div>
              </div>
            </div>
            <p className="mt-3 text-sm leading-relaxed text-muted">{text}</p>
          </div>
        ))}
      </section>

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
            <StatCard label="Landslide events" icon={Mountain} value={fmt(overview.landslide_events)} />
            <StatCard
              label="Non-landslide samples" icon={CircleDashed}
              value={fmt(overview.non_landslide_samples)}
              sub="Paired pseudo-absence points"
            />
            <StatCard label="Buildings mapped" icon={Building2} value={fmt(overview.buildings_mapped)} sub="OSM footprints" />
            <StatCard label="Facilities" icon={Hospital} value={fmt(overview.facilities_mapped)} sub="Hospitals, schools, emergency, transport, worship" />
            <StatCard
              label="Population (study area)" icon={Users}
              value={fmt(overview.population_estimate)}
              sub={`WorldPop ${overview.population_source_year}, constrained`}
            />
            <StatCard
              label="Best model ROC-AUC" icon={ChartColumn}
              value={overview.best_model_roc_auc ? overview.best_model_roc_auc.toFixed(3) : "—"}
              sub={overview.best_model ?? undefined}
            />
          </div>

          <div className="mt-6 grid gap-6 lg:grid-cols-2">
            <div className="card">
              <h2 className="card-title">Pipeline status</h2>
              <p className="card-desc">
                What each step of the data pipeline last produced, read from its output files.
              </p>
              <PipelineStatusList status={overview.pipeline_status} />
            </div>

            <div className="card">
              <h2 className="card-title">What you can do now</h2>
              <ul className="mt-3 space-y-3 text-sm">
                <li>
                  <Link href="/impact" className="inline-flex items-center gap-1 font-medium text-accent hover:underline">
                    Live Impact map <ArrowRight className="h-3.5 w-3.5" aria-hidden />
                  </Link>
                  <p className="text-muted">
                    The 250 m susceptibility map, buildings and facilities on a map; the
                    Early Warning page adds forecast rainfall and live impact per tambon.
                  </p>
                </li>
                <li>
                  <Link href="/warning" className="inline-flex items-center gap-1 font-medium text-accent hover:underline">
                    Early Warning <ArrowRight className="h-3.5 w-3.5" aria-hidden />
                  </Link>
                  <p className="text-muted">
                    The latest GFS rainfall forecast per tambon, the live impact table and a what-if rainfall
                    scenario.
                  </p>
                </li>
                <li>
                  <Link href="/model" className="inline-flex items-center gap-1 font-medium text-accent hover:underline">
                    Model page <ArrowRight className="h-3.5 w-3.5" aria-hidden />
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
