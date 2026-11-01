import { TriangleAlert } from "lucide-react";

// Plain-language summary of docs/METHODS.md, section 6 (Known issues). Keep the two in step.
const GROUPS = {
  data: {
    title: "Data",
    items: [
      "Landslide dates are the dates of the satellite images used to map the scars, not the day each landslide happened: the 6,180 points fall on only 164 dates.",
      "Dated landslide records exist in only 6 of the 14 provinces, so the map for Phuket, Yala, Songkhla, Narathiwat, Pattani, Satun, Nakhon Si Thammarat and Ranong is extrapolated.",
      "Distance to stream was dropped (wrong units in the pre-2020 source); distance to fault and drainage density were too incomplete to use.",
      "Exposure is a snapshot: WorldPop 2020 population and OpenStreetMap buildings and facilities from 2026-09-08, whose completeness varies.",
    ],
  },
  model: {
    title: "Model",
    items: [
      "Scores are relative. The model was trained on equal numbers of landslide and non-landslide points, so a score ranks terrain; it is not a real-world probability.",
      "The task is easier than it looks: non-landslide points are mostly lowland (median slope 7° against 29° for landslides), so the high ROC-AUC partly reflects that contrast.",
      "Spatial cross-validation with a 5 km embargo is stricter than random splits but cannot remove the issues above.",
      "The map is scored on a 250 m grid, coarser than the 30 m terrain data the model was trained on.",
    ],
  },
  forecast: {
    title: "Forecast and live impact",
    items: [
      "There is no calibrated rainfall threshold: an attempted machine-learning rainfall trigger had no skill (hold-out ROC-AUC 0.34) because the landslide dates are image dates.",
      "Rain is judged against each tambon's own CHIRPS climate (how unusual it is), not against landslide records, so the live impact class is a triage aid, not a landslide forecast.",
      "GFS is a global model on a ~28 km grid: it smooths local storms, neighbouring tambons often share one value, and any single run can be wrong in timing and amount.",
    ],
  },
} as const;

type Group = keyof typeof GROUPS;

export default function Limitations({ groups = ["data", "model", "forecast"] }: { groups?: Group[] }) {
  return (
    <section className="card mt-6">
      <h2 className="card-title flex items-center gap-2">
        <TriangleAlert className="h-4 w-4 text-[color:var(--warn-fg)]" aria-hidden />
        Limitations
      </h2>
      <p className="card-desc">Read these before using any number on this site.</p>
      <div className={`mt-4 grid gap-6 ${groups.length > 2 ? "lg:grid-cols-3" : groups.length === 2 ? "md:grid-cols-2" : ""}`}>
        {groups.map((g) => (
          <div key={g}>
            <h3 className="eyebrow mb-2">{GROUPS[g].title}</h3>
            <ul className="list-disc space-y-2 pl-4 text-sm leading-relaxed text-muted marker:text-subtle">
              {GROUPS[g].items.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </section>
  );
}
