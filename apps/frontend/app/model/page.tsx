import Link from "next/link";
import { ChartColumn, CircleCheckBig, Crosshair, Repeat } from "lucide-react";
import { api } from "@/lib/api";
import { SUSCEPTIBILITY_CLASSES } from "@/lib/classes";
import { Swatch } from "@/components/Badge";
import Limitations from "@/components/Limitations";
import ModelTable, { modelName } from "@/components/ModelTable";
import Page, { LoadError } from "@/components/Page";
import { Definition, Details, LINK, Section } from "@/components/Section";
import StatCard from "@/components/StatCard";

export const metadata = { title: "Model — Landslide Impact" };

function num(v: unknown, digits = 3): string {
  return typeof v === "number" && !Number.isNaN(v) ? v.toFixed(digits) : "—";
}

export default async function ModelPage() {
  let metadata: Awaited<ReturnType<typeof api.model>> | null = null;
  let comparison: Awaited<ReturnType<typeof api.modelComparison>> | null = null;
  let error: string | null = null;
  try {
    [metadata, comparison] = await Promise.all([api.model(), api.modelComparison()]);
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  const best = comparison?.models.find((m) => m.model === comparison?.best_model);

  return (
    <Page
      title="Susceptibility model"
      description="How well the terrain map separates landslide-prone ground from the rest, how to read its classes, and how it was built."
    >
      {error && (
        <LoadError
          what="The model results"
          error={error}
          hint={
            <>
              Run the modeling notebook first if <code>models/susceptibility/model_metadata.json</code> doesn&apos;t
              exist yet.
            </>
          }
        />
      )}

      <Section
        id="quality"
        title="How good is the map?"
        description={
          <>
            Good at telling hillsides from lowland; not able to say which of two similar slopes will fail. Use it to
            rank areas, not as a probability of a landslide. The reasons are under{" "}
            <a href="#limits" className={LINK}>
              Limits of the model
            </a>
            .
          </>
        }
      >
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {comparison && (
            <>
              <StatCard
                label="Selected model"
                icon={CircleCheckBig}
                small
                value={modelName(comparison.best_model)}
                sub={
                  <>
                    Best of {comparison.models.length} candidates
                    {metadata?.selection && <> by {metadata.selection}</>}.
                  </>
                }
              />
              <StatCard
                label="ROC-AUC on the held-out area"
                icon={ChartColumn}
                value={num(best?.test?.roc_auc)}
                sub="1.0 is a perfect ranking and 0.5 is chance. Scored once, on an area the model never saw."
              />
              <StatCard
                label="ROC-AUC in cross-validation"
                icon={Repeat}
                value={
                  <>
                    {num(best?.cv?.roc_auc_mean)}
                    {typeof best?.cv?.roc_auc_std === "number" && (
                      <span className="text-base font-medium text-muted"> ± {num(best.cv.roc_auc_std)}</span>
                    )}
                  </>
                }
                sub="Average over repeated tests, each on a different part of the south. This score picked the model."
              />
            </>
          )}
          <StatCard
            label="Landslides in the top fifth of the map"
            icon={Crosshair}
            value="60%"
            sub="of held-out landslides fall in the highest-scoring 20% of 250 m cells: three times chance, below the 70% the project aimed for."
          />
        </div>
      </Section>

      <Section
        id="classes"
        title="Reading the map classes"
        description={
          <>
            Every 250 m cell of ground gets a score from 0 to 1 and one of five classes. The colours are the ones on the{" "}
            <Link href="/impact" className={LINK}>
              Live Impact map
            </Link>
            . A higher score means more landslide-prone than other ground in the south; it is not the chance that a
            landslide happens there.
          </>
        }
      >
        <ul className="grid gap-3 sm:grid-cols-3 lg:grid-cols-5">
          {SUSCEPTIBILITY_CLASSES.map((c) => (
            <li key={c.key} className="flex items-center gap-3 rounded-lg border border-line p-3">
              <span className="scale-150">
                <Swatch color={c.color} />
              </span>
              <span>
                <span className="block text-sm font-medium">{c.label}</span>
                <span className="block text-xs tabular-nums text-muted">Score {c.range}</span>
              </span>
            </li>
          ))}
        </ul>
      </Section>

      {comparison && (
        <Section
          id="comparison"
          title="Models compared"
          description="Every candidate, best cross-validation score first. The held-out columns are a single check made after the model was chosen; they were not used to choose it."
        >
          <ModelTable models={comparison.models} bestModel={comparison.best_model} />
          <div className="mt-3">
            <Details summary="All metrics for every model">
              <ModelTable models={comparison.models} bestModel={comparison.best_model} columns="all" />
              <p className="mt-3">Brier: lower is better. Every other metric: higher is better.</p>
            </Details>
          </div>
          <p className="mt-3 max-w-4xl text-xs leading-relaxed text-muted">
            Precision, PR-AUC and F1 look better here than they would in use: the model was tested on equal numbers of
            landslide and non-landslide points, which is not the real-world share. ROC-AUC and the ranking of the models
            are more robust to that.
          </p>
          <dl className="mt-5 grid gap-x-8 gap-y-4 md:grid-cols-2">
            <Definition term="Cross-validation">
              <p>
                The data is split into regions; the model is trained on some and tested on the others, several times
                over. The average says how the model does on ground it was not trained on.
              </p>
            </Definition>
            <Definition term="Held-out area">
              <p>One region kept aside from the start and scored a single time at the end, as a final check.</p>
            </Definition>
            <Definition term="ROC-AUC">
              <p>
                How often the model scores a real landslide point above a non-landslide point. 1.0 is always, 0.5 is a
                coin toss.
              </p>
            </Definition>
            <Definition term="Recall and specificity">
              <p>
                Recall: the share of real landslide points the model flags. Specificity: the share of non-landslide
                points it correctly leaves unflagged.
              </p>
            </Definition>
          </dl>
        </Section>
      )}

      <Section id="method" title="How it was trained" description="For readers who want the method. Nothing here is needed to use the map.">
        <div className="space-y-3">
          {metadata && (
            <dl className="grid gap-4 sm:grid-cols-3">
              <div className="rounded-lg border border-line p-3">
                <dt className="text-sm font-semibold">Factors used: {metadata.feature_columns.length}</dt>
                <dd className="mt-1 text-xs leading-relaxed text-muted">
                  {metadata.numeric_features.length} numeric, {metadata.categorical_features.length} categorical. They
                  are listed on the{" "}
                  <Link href="/data#factors" className={LINK}>
                    Data page
                  </Link>
                  .
                </dd>
              </div>
              <div className="rounded-lg border border-line p-3">
                <dt className="text-sm font-semibold tabular-nums">
                  Threshold on the raw score: {metadata.threshold_raw_probability.toFixed(3)}
                </dt>
                <dd className="mt-1 text-xs leading-relaxed text-muted">
                  The score above which a point counts as &quot;landslide&quot; when recall, precision and specificity
                  are calculated.
                </dd>
              </div>
              <div className="rounded-lg border border-line p-3">
                <dt className="text-sm font-semibold tabular-nums">
                  Threshold on the calibrated score: {metadata.threshold_calibrated_probability.toFixed(3)}
                </dt>
                <dd className="mt-1 text-xs leading-relaxed text-muted">
                  The same cut-off after calibration, the scale the map classes above use.
                </dd>
              </div>
            </dl>
          )}
          <Details summary="Method in full: candidates, spatial splits, preprocessing, calibration">
            <div className="space-y-2">
              <p>
                Eleven models (Logistic Regression with/without feature selection, Decision Tree, Random Forest,
                SVM-RBF, Gradient Boosting, AdaBoost, KNN, Naive Bayes, XGBoost, LightGBM) are compared on terrain,
                soil, lithology, hydrology and land-cover factors sampled from a 1:1 landslide / paired non-landslide
                (pseudo-absence) point inventory.
              </p>
              <p>
                Splits are grouped by 0.5° spatial blocks (<code>StratifiedGroupKFold</code>), with a 5 km embargo
                around the held-out fold, not plain random splits, so neighbouring, spatially autocorrelated points
                never leak between train and test. Model selection and the decision threshold (Youden&apos;s J) come
                from nested cross-validation&apos;s out-of-fold predictions only; the held-out test set is scored once,
                after selection.
              </p>
              <p>
                Preprocessing (imputation, Yeo-Johnson/scaling for linear models, one-hot encoding, IQR winsorising,
                feature selection) lives inside each model&apos;s pipeline, refit per fold and never fit on the full
                dataset before splitting. The chosen model is also calibrated (isotonic regression on out-of-fold
                predictions) and checked against a temporal (pre/post date) holdout in addition to the spatial one.
              </p>
            </div>
          </Details>
        </div>
      </Section>

      <Limitations group="model" />
    </Page>
  );
}
