import { api } from "@/lib/api";
import ModelTable from "@/components/ModelTable";
import Page from "@/components/Page";

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
    <Page
      title="Susceptibility model"
      description="How the terrain susceptibility map was trained, validated and calibrated, with every candidate model's scores."
    >

      {error && (
        <div className="mt-6 note-danger">
          Could not reach the API: {error}. Run the modeling notebook first if{" "}
          <code>models/susceptibility/model_metadata.json</code> doesn&apos;t exist yet.
        </div>
      )}

      <section className="card">
        <h2 className="card-title">Methodology</h2>
        <div className="mt-3 space-y-2 text-sm text-muted">
          <p>
            Eleven models (Logistic Regression with/without feature selection, Decision Tree,
            Random Forest, SVM-RBF, Gradient Boosting, AdaBoost, KNN, Naive Bayes, XGBoost,
            LightGBM) are compared on terrain, soil, lithology, hydrology and land-cover
            factors sampled from a 1:1 landslide / paired non-landslide (pseudo-absence)
            point inventory.
          </p>
          <p>
            Splits are grouped by 0.5° spatial blocks (<code>StratifiedGroupKFold</code>), with a
            5 km embargo around the held-out fold, not plain random splits, so neighbouring,
            spatially autocorrelated points never leak between train and test. Model selection and the decision threshold
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
          <p className="text-[color:var(--warn-fg)]">
            Caveat: the 1:1 sample is not the real-world landslide prevalence, so
            precision/PR-AUC/F1 here are optimistic for real deployment; ROC-AUC and the
            relative ranking across models are more robust to that.
          </p>
        </div>
      </section>

      {metadata && (
        <section className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <div className="card p-4">
            <div className="eyebrow">Selected model</div>
            <div className="mt-2 text-xl font-semibold tabular-nums">{metadata.best_model}</div>
            <div className="text-xs text-muted">{metadata.selection}</div>
          </div>
          <div className="card p-4">
            <div className="eyebrow">Threshold (raw)</div>
            <div className="mt-2 text-xl font-semibold tabular-nums">
              {metadata.threshold_raw_probability.toFixed(3)}
            </div>
          </div>
          <div className="card p-4">
            <div className="eyebrow">Threshold (calibrated)</div>
            <div className="mt-2 text-xl font-semibold tabular-nums">
              {metadata.threshold_calibrated_probability.toFixed(3)}
            </div>
          </div>
          <div className="card p-4">
            <div className="eyebrow">Features used</div>
            <div className="mt-2 text-xl font-semibold tabular-nums">{metadata.feature_columns.length}</div>
            <div className="text-xs text-muted">
              {metadata.numeric_features.length} numeric, {metadata.categorical_features.length}{" "}
              categorical
            </div>
          </div>
        </section>
      )}

      {comparison && (
        <section className="mt-6 card">
          <h2 className="card-title">Model comparison</h2>
          <p className="card-desc">
            Nested spatial cross-validation drives model selection; the held-out columns are a
            single, after-the-fact check, not used to pick the model.
          </p>
          <div className="mt-4">
            <ModelTable models={comparison.models} bestModel={comparison.best_model} />
          </div>
        </section>
      )}

      {metadata && (
        <section className="mt-6 card">
          <h2 className="card-title">Excluded / feature columns</h2>
          <div className="mt-3 grid gap-4 text-sm sm:grid-cols-3">
            <div>
              <div className="mb-1 font-medium text-muted">Numeric</div>
              <div className="text-fg">
                {metadata.numeric_features.join(", ")}
              </div>
            </div>
            <div>
              <div className="mb-1 font-medium text-muted">Categorical</div>
              <div className="text-fg">
                {metadata.categorical_features.join(", ")}
              </div>
            </div>
            <div>
              <div className="mb-1 font-medium text-muted">Excluded (ids/coords/target)</div>
              <div className="text-fg">
                {metadata.excluded_columns.join(", ")}
              </div>
            </div>
          </div>
        </section>
      )}
    </Page>
  );
}
