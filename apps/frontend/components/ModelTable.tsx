import type { ModelComparisonEntry } from "@/lib/api";

const CV_METRICS: Array<[string, string]> = [
  ["roc_auc_mean", "ROC-AUC"],
  ["pr_auc_mean", "PR-AUC"],
  ["f1_mean", "F1"],
  ["balanced_accuracy_mean", "Balanced acc."],
  ["brier_mean", "Brier ↓"],
];

const TEST_METRICS: Array<[string, string]> = [
  ["roc_auc", "ROC-AUC"],
  ["pr_auc", "PR-AUC"],
  ["precision", "Precision"],
  ["recall_sensitivity", "Recall"],
  ["specificity", "Specificity"],
  ["f1", "F1"],
];

function fmt(v: unknown, digits = 3) {
  if (typeof v !== "number" || Number.isNaN(v)) return "—";
  return v.toFixed(digits);
}

export default function ModelTable({
  models,
  bestModel,
}: {
  models: ModelComparisonEntry[];
  bestModel: string;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] border-collapse text-sm">
        <thead>
          <tr className="border-b border-zinc-200 text-left text-zinc-500 dark:border-zinc-800">
            <th className="py-2 pr-4 font-medium">Model</th>
            <th className="py-2 pr-2 font-medium" colSpan={CV_METRICS.length}>
              Nested spatial CV (model selection)
            </th>
            <th className="py-2 pr-2 font-medium" colSpan={TEST_METRICS.length}>
              Held-out test (single evaluation)
            </th>
          </tr>
          <tr className="border-b border-zinc-200 text-left text-xs text-zinc-400 dark:border-zinc-800">
            <th />
            {CV_METRICS.map(([, label]) => (
              <th key={label} className="py-1 pr-3 font-normal">
                {label}
              </th>
            ))}
            {TEST_METRICS.map(([, label]) => (
              <th key={label} className="py-1 pr-3 font-normal">
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {models.map((row) => {
            const isBest = row.model === bestModel;
            return (
              <tr
                key={row.model}
                className={`border-b border-zinc-100 dark:border-zinc-900 ${
                  isBest ? "bg-amber-50 dark:bg-amber-950/30" : ""
                }`}
              >
                <td className="py-2 pr-4 font-medium">
                  {row.model}
                  {isBest && (
                    <span className="ml-2 rounded-full bg-amber-500 px-2 py-0.5 text-[10px] font-semibold text-white">
                      BEST
                    </span>
                  )}
                </td>
                {CV_METRICS.map(([key, label]) => (
                  <td key={label} className="py-2 pr-3 tabular-nums">
                    {fmt(row.cv?.[key])}
                  </td>
                ))}
                {TEST_METRICS.map(([key, label]) => (
                  <td key={label} className="py-2 pr-3 tabular-nums">
                    {fmt(row.test?.[key])}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
