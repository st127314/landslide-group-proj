import Link from "next/link";
import { ArrowRight, Building2, CloudRain, Hospital, MapPinned, Mountain, Users } from "lucide-react";
import { api } from "@/lib/api";
import { ageLabel, isStale, thaiTime } from "@/lib/time";
import { fmtInt, plural } from "@/lib/classes";
import { ClassCounts } from "@/components/Badge";
import Page, { LoadError } from "@/components/Page";
import PipelineStatusList from "@/components/PipelineStatusList";
import { LABEL, LINK, Section } from "@/components/Section";
import StatCard from "@/components/StatCard";

const COMPONENTS = [
  {
    icon: Mountain,
    step: "Where",
    title: "Terrain susceptibility",
    text: "A machine-learning model trained on mapped landslides rates every 250 m cell of ground from very low to very high.",
    href: "/model",
    link: "How good is the map",
  },
  {
    icon: CloudRain,
    step: "When",
    title: "Rainfall forecast",
    text: "The NOAA GFS forecast for the next 24 hours (with totals to 5 days) is compared with each tambon's own 30-year rainfall record, to flag rain that is unusually heavy for that place.",
    href: "/warning",
    link: "Tambons flagged now",
  },
  {
    icon: Users,
    step: "Who is affected",
    title: "Exposure",
    text: "Population, buildings and public facilities are matched to the map and the forecast, to count what stands on landslide-prone ground.",
    href: "/impact",
    link: "See it on the map",
  },
];

const BUTTON =
  "inline-flex min-h-11 items-center gap-2 rounded-lg px-4 text-sm font-medium transition-colors";

export default async function OverviewPage() {
  let overview: Awaited<ReturnType<typeof api.overview>> | null = null;
  let overlay: Awaited<ReturnType<typeof api.impactOverlay>> | null = null;
  let error: string | null = null;
  try {
    overview = await api.overview();
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }
  try {
    overlay = await api.impactOverlay();
  } catch {
    overlay = null; // the rest of the page still works without the live summary
  }

  const meta = overlay?.metadata;
  const totals = meta?.totals;
  const counts = totals?.tambons_by_live_impact_class;
  const flagged = (counts?.high ?? 0) + (counts?.very_high ?? 0);

  return (
    <Page
      title="Landslide risk and impact in southern Thailand"
      description={
        <>
          A decision-support tool for Thailand&apos;s 14 southern provinces. It shows where the ground is prone to
          landslides, where the rain forecast is unusually heavy, and who lives and works there, by tambon
          (sub-district).
        </>
      }
    >
      {error && (
        <LoadError
          what="The summary figures"
          error={error}
          hint={
            <>
              The page reads the API at <code>NEXT_PUBLIC_API_URL</code>. To run it locally:{" "}
              <code>uvicorn app.main:app --port 8000</code> from <code>apps/backend</code>.
            </>
          }
        />
      )}

      {meta && totals && (
        <Section id="now" title="Right now: the next 24 hours">
          <p className="text-xl font-semibold leading-snug tracking-tight sm:text-2xl">
            {flagged === 0
              ? "No tambon is rated High or Very high."
              : `${plural(flagged, "tambon")} ${flagged === 1 ? "is" : "are"} rated High or Very high.`}
          </p>
          <p className="mt-1 max-w-3xl text-sm leading-relaxed text-muted">
            {flagged > 0 && (
              <>
                <span className="font-medium text-fg">{plural(totals.population_at_elevated_risk, "person", "people")}</span>{" "}
                live on landslide-prone ground inside {flagged === 1 ? "that tambon" : "those tambons"}.{" "}
              </>
            )}
            A tambon is rated High or Very high when landslide-prone terrain meets forecast rain that is unusually heavy
            for that place.
          </p>
          <div className="mt-4">
            <ClassCounts kind="impact" counts={counts} />
          </div>
          <p className="mt-4 text-xs leading-relaxed text-muted">
            Forecast issued {thaiTime(meta.gfs_run_utc)}, updated {ageLabel(meta.generated_utc)}.
            {isStale(meta.generated_utc) && (
              <span className="font-medium text-[color:var(--danger-fg)]"> Stale: the newest forecast has not been fetched.</span>
            )}{" "}
            This is a triage aid, not a landslide forecast:{" "}
            <Link href="/warning#limits" className={LINK}>
              read its limits
            </Link>
            .
          </p>
          <div className="mt-4 flex flex-wrap gap-3">
            <Link href="/warning" className={`${BUTTON} bg-accent text-accent-fg hover:opacity-90`}>
              See the tambon list <ArrowRight className="h-4 w-4" aria-hidden />
            </Link>
            <Link href="/impact" className={`${BUTTON} border border-line hover:bg-surface-2`}>
              <MapPinned className="h-4 w-4" aria-hidden /> Open the map
            </Link>
          </div>
        </Section>
      )}

      <section aria-labelledby="how-title">
        <h2 id="how-title" className="card-title mb-3">
          How the tool works
        </h2>
        <div className="grid gap-4 md:grid-cols-3">
          {COMPONENTS.map(({ icon: Icon, step, title, text, href, link }) => (
            <div key={title} className="card flex flex-col p-4">
              <div className="flex items-center gap-3">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent">
                  <Icon className="h-5 w-5" aria-hidden />
                </span>
                <div>
                  <div className={LABEL}>{step}</div>
                  <h3 className="text-sm font-semibold">{title}</h3>
                </div>
              </div>
              <p className="mt-3 flex-1 text-sm leading-relaxed text-muted">{text}</p>
              <Link href={href} className={`${LINK} mt-3 inline-flex min-h-6 items-center gap-1 text-sm`}>
                {link} <ArrowRight className="h-3.5 w-3.5" aria-hidden />
              </Link>
            </div>
          ))}
        </div>
      </section>

      {overview && (
        <>
          <section aria-labelledby="area-title">
            <h2 id="area-title" className="card-title mb-3">
              The study area
            </h2>
            <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
              <StatCard
                label="People"
                icon={Users}
                value={
                  overview.population_estimate === null ? "—" : `${(overview.population_estimate / 1e6).toFixed(2)} million`
                }
                sub={`WorldPop ${overview.population_source_year}`}
              />
              <StatCard label="Buildings" icon={Building2} value={fmtInt(overview.buildings_mapped)} sub="OpenStreetMap footprints" />
              <StatCard
                label="Public facilities"
                icon={Hospital}
                value={fmtInt(overview.facilities_mapped)}
                sub="Hospitals, schools, emergency, transport, worship"
              />
              <StatCard
                label="Tambons"
                icon={MapPinned}
                value={overlay ? fmtInt(overlay.tambons.length) : "—"}
                sub="Sub-districts, in 14 provinces"
              />
            </div>
            <p className="mt-3 text-sm text-muted">
              Where these figures come from, and the landslide records behind the map:{" "}
              <Link href="/data" className={LINK}>
                Data
              </Link>
              .
            </p>
          </section>

          <Section
            id="status"
            title="System status"
            description="Whether each part of the tool has been produced and is being served."
          >
            <PipelineStatusList status={overview.pipeline_status} />
          </Section>
        </>
      )}
    </Page>
  );
}
