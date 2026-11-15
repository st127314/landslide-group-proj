import Link from "next/link";
import { LINK, Section } from "@/components/Section";

// Plain-language summary of docs/METHODS.md, section 6 (Known issues). Keep the two in step.
// Each group is stated once, on the page it belongs to (see HOME); the other pages link to it.
const GROUPS = {
  data: {
    title: "Limits of the data",
    items: [
      "Landslide dates are the dates of the satellite images used to map the scars, not the day each landslide happened: the 6,180 points fall on only 164 dates.",
      "All but 4 of the 6,180 dated landslide records lie in 6 of the 14 provinces, so the map for Phuket, Yala, Songkhla, Narathiwat, Pattani, Satun, Nakhon Si Thammarat and Ranong is extrapolated.",
      "Distance to stream was dropped (wrong units in the pre-2020 source); distance to fault and drainage density were too incomplete to use.",
      "Exposure is a snapshot: WorldPop 2020 population and OpenStreetMap buildings and facilities from 2026-09-08, whose completeness varies.",
    ],
  },
  model: {
    title: "Limits of the model",
    items: [
      "Scores are relative. The model was trained on equal numbers of landslide and non-landslide points, so a score ranks terrain; it is not a real-world probability.",
      "The task is easier than it looks: non-landslide points are mostly lowland (median slope 7° against 29° for landslides), so the high ROC-AUC partly reflects that contrast.",
      "Spatial cross-validation with a 5 km embargo is stricter than random splits but cannot remove the issues above.",
      "The model separates hillslopes from lowland; it does not rank comparable slopes. Against negatives matched on slope and elevation its ROC-AUC is about 0.5.",
      "NDVI was removed from the model: it was measured after the scar formed, so it leaked the answer. That lowered the held-out ROC-AUC from 0.94 to 0.89, the more honest figure.",
      "The hydrology factors and the road and river distances come from different sources on the map than in training, and add nothing there.",
    ],
  },
  forecast: {
    title: "Limits of this forecast",
    items: [
      "There is no calibrated rainfall threshold: an attempted machine-learning rainfall trigger had no skill (hold-out ROC-AUC 0.34) because the landslide dates are image dates.",
      "Rain is judged against each tambon's own CHIRPS climate (how unusual it is), not against landslide records, so the live impact class is a triage aid, not a landslide forecast.",
      "GFS is a global model on a ~28 km grid: it smooths local storms, neighbouring tambons often share one value, and any single run can be wrong in timing and amount.",
    ],
  },
} as const;

export type LimitGroup = keyof typeof GROUPS;

/** The one page and anchor where each group of limitations is stated. */
const HOME: Record<LimitGroup, { href: string; label: string }> = {
  data: { href: "/data#limits", label: "Limits of the data" },
  model: { href: "/model#limits", label: "Limits of the model" },
  forecast: { href: "/warning#limits", label: "Limits of the forecast" },
};

/** Links to the limitation sections of the other pages. */
export function LimitLinks({ groups }: { groups: LimitGroup[] }) {
  return (
    <>
      {groups.map((g, i) => (
        <span key={g}>
          {i > 0 && (i === groups.length - 1 ? " and " : ", ")}
          <Link href={HOME[g].href} className={LINK}>
            {HOME[g].label}
          </Link>
        </span>
      ))}
    </>
  );
}

export default function Limitations({ group, children }: { group: LimitGroup; children?: React.ReactNode }) {
  const others = (Object.keys(GROUPS) as LimitGroup[]).filter((g) => g !== group);
  return (
    <Section id="limits" title={GROUPS[group].title} description="Read these before acting on a number from this page.">
      <ul className="max-w-4xl list-disc space-y-2 pl-5 text-sm leading-relaxed text-muted">
        {GROUPS[group].items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
      {children && <div className="mt-4">{children}</div>}
      <p className="mt-4 text-sm text-muted">
        See also: <LimitLinks groups={others} />.
      </p>
    </Section>
  );
}
