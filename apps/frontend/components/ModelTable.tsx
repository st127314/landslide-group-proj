import type { ModelComparisonEntry } from "@/lib/api";
import { STICKY_COL, STICKY_HEAD, TableScroll } from "@/components/Section";

type Metric = [source: "cv" | "test", key: string, label: string];

const CV_METRICS: Metric[] = [
  ["cv", "roc_auc_mean", "ROC-AUC"],
  ["cv", "pr_auc_mean", "PR-AUC"],
  ["cv", "f1_mean", "F1"],
  ["cv", "balanced_accuracy_mean", "Balanced acc."],
  ["cv", "brier_mean", "Brier"],
];

const TEST_METRICS: Metric[] = [
  ["test", "roc_auc", "ROC-AUC"],
  ["test", "pr_auc", "PR-AUC"],
  ["test", "precision", "Precision"],
  ["test", "recall_sensitivity", "Recall"],
  ["test", "specificity", "Specificity"],
  ["test", "f1", "F1"],
];

// The short table: the score that picked the model, and how each model did on the area held back.
const KEY_CV: Metric[] = [["cv", "roc_auc_mean", "ROC-AUC"]];
const KEY_TEST: Metric[] = [
  ["test", "roc_auc", "ROC-AUC"],
  ["test", "recall_sensitivity", "Recall"],
  ["test", "specificity", "Specificity"],
];

const MODEL_NAMES: Record<string, string> = {
  adaboost: "AdaBoost",
  decision_tree: "Decision tree",
  gradient_boosting: "Gradient boosting",
  knn: "K-nearest neighbours",
  lightgbm: "LightGBM",
  logistic_regression: "Logistic regression",
  logistic_regression_feature_selected: "Logistic regression, feature-selected",
  naive_bayes: "Naive Bayes",
  random_forest: "Random forest",
  svm_rbf: "SVM (RBF kernel)",
  xgboost: "XGBoost",
};

/** A readable name for a model id such as "svm_rbf"; unknown ids fall back to the id with spaces. */
export function modelName(id: string | null | undefined): string {
  if (!id) return "—";
  return MODEL_NAMES[id] ?? id.replaceAll("_", " ");
}

function fmt(v: unknown, digits = 3) {
  if (typeof v !== "number" || Number.isNaN(v)) return "—";
  return v.toFixed(digits);
}

export default function ModelTable({
  models,
  bestModel,
  columns = "key",
}: {
  models: ModelComparisonEntry[];
  bestModel: string;
  /** "key": four headline columns. "all": every metric. */
  columns?: "key" | "all";
}) {
  const cv = columns === "all" ? CV_METRICS : KEY_CV;
  const test = columns === "all" ? TEST_METRICS : KEY_TEST;
  // Best cross-validation ROC-AUC first: the order in which the models were ranked for selection.
  const rows = [...models].sort((a, b) => Number(b.cv?.roc_auc_mean ?? -1) - Number(a.cv?.roc_auc_mean ?? -1));
  return (
    <TableScroll label={columns === "all" ? "All metrics for every candidate model" : "Candidate models, best first"}>
      <table className={`data-table ${columns === "all" ? "min-w-[980px]" : "min-w-[440px]"}`}>
        <thead>
          <tr>
            <th scope="col" rowSpan={2} className={`${STICKY_HEAD} align-bottom`}>
              Model
            </th>
            <th scope="colgroup" colSpan={cv.length} className="text-right">
              Cross-validation
            </th>
            <th scope="colgroup" colSpan={test.length} className="border-l border-line text-right">
              Held-out area
            </th>
          </tr>
          <tr>
            {[...cv, ...test].map(([source, key, label], i) => (
              <th
                key={`${source}-${key}`}
                scope="col"
                className={`text-right font-normal normal-case tracking-normal ${i === cv.length ? "border-l border-line" : ""}`}
              >
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const isBest = row.model === bestModel;
            return (
              <tr key={row.model}>
                <th
                  scope="row"
                  className={`${STICKY_COL} max-w-40 border-b border-line px-3 py-2 text-left font-medium sm:max-w-none [tr:last-child_&]:border-b-0`}
                >
                  {modelName(row.model)}
                  {isBest && (
                    <span className="ml-2 inline-block rounded-full bg-accent px-2 py-0.5 text-xs font-semibold text-accent-fg">
                      Selected
                    </span>
                  )}
                </th>
                {[...cv, ...test].map(([source, key], i) => (
                  <td
                    key={`${source}-${key}`}
                    className={`text-right tabular-nums ${isBest ? "font-semibold" : ""} ${i === cv.length ? "border-l border-line" : ""}`}
                  >
                    {fmt(row[source]?.[key])}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </TableScroll>
  );
}
