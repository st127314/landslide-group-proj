import { api } from "@/lib/api";
import ModelTable from "@/components/ModelTable";

export default async function ModelPage() {
  let metadata: Awaited<ReturnType<typeof api.model>> | null = null;
  let comparison: Awaited<ReturnType<typeof api.modelComparison>> | null = null;
  let error: string | null = null;
  try {
    [metadata, comparison] = await Promise.all([api.model(), api.modelComparison()]);
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  return (
    <div className="mx-auto w-full max-w-6xl flex-1 px-6 py-10">
      <h1 className="text-3xl font-bold tracking-tight">Susceptibility Model</h1>

      {error && (
        <div className="mt-6 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
          Could not reach the API: {error}. Run the modeling notebook first if{" "}
          <code>models/susceptibility/model_metadata.json</code> doesn&apos;t exist yet.
        </div>
      )}

      <section className="mt-6 rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-900">
        <h2 className="text-lg font-semibold">Methodology</h2>
        <div className="mt-3 space-y-2 text-sm text-zinc-600 dark:text-zinc-400">
          <p>
            Eleven models (Logistic Regression with/without feature selection, Decision Tree,
            Random Forest, SVM-RBF, Gradient Boosting, AdaBoost, KNN, Naive Bayes, XGBoost,
            LightGBM) are compared on terrain, soil, lithology, hydrology and land-cover
            factors sampled from a 1:1 landslide / paired non-landslide (pseudo-absence)
            point inventory.
          </p>
          <p>
            Splits are grouped by ~0.25° spatial blocks (<code>StratifiedGroupKFold</code>),
            not plain random splits, so neighbouring/spatially-autocorrelated points never
            leak between train and test. Model selection and the decision threshold
            (Youden&apos;s J) come from nested cross-validation&apos;s out-of-fold
            predictions only; the held-out test set is scored once, after selection.
          </p>
          <p>
            Preprocessing (imputation, Yeo-Johnson/scaling for linear models, one-hot
            encoding, IQR winsorising, feature selection) lives inside each model&apos;s
            pipeline, refit per fold — never fit on the full dataset before splitting.
            The chosen model is also calibrated (isotonic regression on out-of-fold
            predictions) and checked against a temporal (pre/post date) holdout in
            addition to the spatial one.
          </p>
          <p className="text-amber-700 dark:text-amber-400">
            Caveat: the 1:1 sample is not the real-world landslide prevalence, so
            precision/PR-AUC/F1 here are optimistic for real deployment; ROC-AUC and the
            relative ranking across models are more robust to that.
          </p>
        </div>
      </section>

      {metadata && (
        <section className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <div className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
            <div className="text-xs text-zinc-500">Selected model</div>
            <div className="mt-1 text-lg font-semibold">{metadata.best_model}</div>
            <div className="text-xs text-zinc-500">{metadata.selection}</div>
          </div>
          <div className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
            <div className="text-xs text-zinc-500">Decision threshold (raw prob.)</div>
            <div className="mt-1 text-lg font-semibold">
              {metadata.threshold_raw_probability.toFixed(3)}
            </div>
          </div>
          <div className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
            <div className="text-xs text-zinc-500">Decision threshold (calibrated)</div>
            <div className="mt-1 text-lg font-semibold">
              {metadata.threshold_calibrated_probability.toFixed(3)}
            </div>
          </div>
          <div className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
            <div className="text-xs text-zinc-500">Features used</div>
            <div className="mt-1 text-lg font-semibold">{metadata.feature_columns.length}</div>
            <div className="text-xs text-zinc-500">
              {metadata.numeric_features.length} numeric, {metadata.categorical_features.length}{" "}
              categorical
            </div>
          </div>
        </section>
      )}

      {comparison && (
        <section className="mt-6 rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-900">
          <h2 className="text-lg font-semibold">Model comparison</h2>
          <p className="mt-1 text-sm text-zinc-500">
            Nested spatial cross-validation drives model selection; the held-out columns are a
            single, after-the-fact check, not used to pick the model.
          </p>
          <div className="mt-4">
            <ModelTable models={comparison.models} bestModel={comparison.best_model} />
          </div>
        </section>
      )}

      {metadata && (
        <section className="mt-6 rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-900">
          <h2 className="text-lg font-semibold">Excluded / feature columns</h2>
          <div className="mt-3 grid gap-4 text-sm sm:grid-cols-3">
            <div>
              <div className="mb-1 font-medium text-zinc-500">Numeric</div>
              <div className="text-zinc-700 dark:text-zinc-300">
                {metadata.numeric_features.join(", ")}
              </div>
            </div>
            <div>
              <div className="mb-1 font-medium text-zinc-500">Categorical</div>
              <div className="text-zinc-700 dark:text-zinc-300">
                {metadata.categorical_features.join(", ")}
              </div>
            </div>
            <div>
              <div className="mb-1 font-medium text-zinc-500">Excluded (ids/coords/target)</div>
              <div className="text-zinc-700 dark:text-zinc-300">
                {metadata.excluded_columns.join(", ")}
              </div>
            </div>
          </div>
        </section>
      )}
    </div>
  );
}
