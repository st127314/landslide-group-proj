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
    <div className="overflow-x-auto rounded-lg border border-line">
      <table className="data-table min-w-[720px]">
        <thead>
          <tr>
            <th className="font-medium">Model</th>
            <th className="font-medium" colSpan={CV_METRICS.length}>
              Nested spatial CV (model selection)
            </th>
            <th className="font-medium" colSpan={TEST_METRICS.length}>
              Held-out test (single evaluation)
            </th>
          </tr>
          <tr>
            <th />
            {CV_METRICS.map(([, label]) => (
              <th key={label} className="font-normal normal-case tracking-normal">
                {label}
              </th>
            ))}
            {TEST_METRICS.map(([, label]) => (
              <th key={label} className="font-normal normal-case tracking-normal">
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
                className={`${
                  isBest ? "bg-accent-soft" : ""
                }`}
              >
                <td className="font-medium">
                  {row.model}
                  {isBest && (
                    <span className="ml-2 rounded-full bg-accent px-2 py-0.5 text-[10px] font-semibold text-accent-fg">
                      BEST
                    </span>
                  )}
                </td>
                {CV_METRICS.map(([key, label]) => (
                  <td key={label} className="tabular-nums">
                    {fmt(row.cv?.[key])}
                  </td>
                ))}
                {TEST_METRICS.map(([key, label]) => (
                  <td key={label} className="tabular-nums">
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
