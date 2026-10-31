"""Report figures from the finished pipeline outputs -> results/figures/*.png

  1_susceptibility_map.png      250 m susceptibility classes over southern Thailand
  2_live_impact_by_tambon.png   terrain tier, GFS 24 h forecast rain class and the live impact class per tambon
  3_model_comparison.png        held-out ROC-AUC (95% CI) of the candidate susceptibility models
  4_population_by_province.png  population living in high / very-high susceptibility cells

Run: python3 scripts/make_figures.py   (needs geopandas and matplotlib)
Colours: one-hue ordinal blue ramp (light -> dark = low -> high), gray = not assessed.
"""

import json
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.ticker  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
import pandas as pd  # noqa: E402

PROJECT_DIR = Path(__file__).resolve().parent.parent
FIG_DIR = PROJECT_DIR / "results" / "figures"

SURFACE, INK, INK2, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
RAMP5 = ["#cde2fb", "#86b6ef", "#2a78d6", "#1c5cab", "#104281"]  # very_low .. very_high
RAMP4 = RAMP5[1:]
NO_DATA = "#c3c2b7"
CLASSES5 = ["very_low", "low", "moderate", "high", "very_high"]
CLASSES4 = ["low", "moderate", "high", "very_high"]
PRETTY = {"below_p75": "below P75", "p75_p90": "P75-P90", "p90_p95": "P90-P95", "above_p95": "above P95"}
label = lambda c: PRETTY.get(c, c.replace("_", " "))  # noqa: E731

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "text.color": INK, "axes.labelcolor": INK2, "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.edgecolor": GRID, "font.size": 10, "axes.titlesize": 12, "axes.titleweight": "bold",
    "axes.titlecolor": INK, "axes.spines.top": False, "axes.spines.right": False,
})


def legend_patches(names, colors):
    return [Line2D([0], [0], marker="s", linestyle="", markersize=9, markerfacecolor=c,
                   markeredgecolor=SURFACE, label=label(n)) for n, c in zip(names, colors)]


def map_axes(ax, boundary):
    boundary.boundary.plot(ax=ax, color=MUTED, linewidth=0.4)
    ax.set_aspect(1 / 0.99)
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)


def fig_susceptibility(boundary):
    grid = pd.read_csv(PROJECT_DIR / "results/susceptibility_map/susceptibility_grid_points.csv",
                       usecols=["px_lon", "px_lat", "susceptibility_class"])
    fig, ax = plt.subplots(figsize=(6.2, 9))
    for cls, col in zip(CLASSES5, RAMP5):
        d = grid[grid["susceptibility_class"] == cls]
        ax.scatter(d["px_lon"], d["px_lat"], s=0.35, c=col, marker="s", linewidths=0, rasterized=True)
    map_axes(ax, boundary)
    ax.set_title("Landslide susceptibility, southern Thailand", loc="left", pad=22)
    meta = json.loads((PROJECT_DIR / "results/susceptibility_map/susceptibility_map_metadata.json").read_text())
    model_name = str(meta.get("model", "model")).replace("_", " ")
    ax.text(0, 1.012, f"250 m grid, {len(grid) / 1e6:.2f} M cells; {model_name} model, calibrated score", transform=ax.transAxes,
            fontsize=9, color=INK2, va="bottom")
    n = grid["susceptibility_class"].value_counts(normalize=True)
    ax.legend(handles=legend_patches(CLASSES5, RAMP5), title="Class (share of cells)", frameon=False,
              loc="lower left", labelcolor=INK2, title_fontproperties={"size": 9})
    for t, c in zip(ax.get_legend().get_texts(), CLASSES5):
        t.set_text(f"{label(c)}  {100 * n.get(c, 0):.0f}%")
    fig.savefig(FIG_DIR / "1_susceptibility_map.png", dpi=170, bbox_inches="tight")
    plt.close(fig)


def fig_combined(boundary, tambons, overlay):
    cols = ["GID_3", "susceptibility_tier", "rain_local_class_24h", "live_impact_class"]
    gdf = tambons.merge(overlay[cols], on="GID_3", how="left")
    meta = json.loads((PROJECT_DIR / "results/impact_overlay/impact_overlay.json").read_text())["metadata"]
    panels = [
        ("susceptibility_tier", "Terrain susceptibility tier", ["low", "moderate", "high"], [RAMP5[1], RAMP5[2], RAMP5[4]]),
        ("rain_local_class_24h", "GFS forecast rain vs local normal (24 h)", ["below_p75", "p75_p90", "p90_p95", "above_p95"],
         [RAMP5[0], RAMP5[1], RAMP5[3], RAMP5[4]]),
        ("live_impact_class", "Live impact class", CLASSES4, RAMP4),
    ]
    fig, axes = plt.subplots(1, len(panels), figsize=(5.6 * len(panels), 8.5), squeeze=False)
    for ax, (col, title, names, colors) in zip(axes[0], panels):
        gdf.plot(ax=ax, color=NO_DATA, linewidth=0)
        for n, c in zip(names, colors):
            sub = gdf[gdf[col] == n]
            if len(sub):
                sub.plot(ax=ax, color=c, linewidth=0.05, edgecolor=SURFACE)
        map_axes(ax, boundary)
        counts = gdf[col].value_counts()
        ax.set_title(title, loc="left")
        shown = [(n, c) for n, c in zip(names, colors) if counts.get(n, 0) or n in ("below_p75", "low")]
        ax.legend(handles=legend_patches([n for n, _ in shown], [c for _, c in shown]), frameon=False,
                  loc="lower left", labelcolor=INK2)
        for t, (n, _) in zip(ax.get_legend().get_texts(), shown):
            t.set_text(f"{label(n)}  ({counts.get(n, 0)} tambons)")
    import textwrap
    run = str(meta.get("gfs_run_utc", ""))[:16].replace("T", " ")
    note = (f"GFS run {run} UTC. Live impact = terrain factor (share of 250 m cells high/very high: <15% low=1, 15-40% moderate=2, "
            ">=40% high=3) x 24 h rain class against each tambon's own wet-day rainfall percentiles (CHIRPS 1991-2020: "
            "below P75 = 0, P75-P90 = 1, P90-P95 = 2, above P95 = 3). A transparent triage rule, not a validated landslide forecast. "
            "Gray = no data.")
    fig.text(0.01, 0.01, "\n".join(textwrap.wrap(note, 60 * len(panels))), fontsize=8.5, color=INK2, va="bottom")
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    fig.savefig(FIG_DIR / "2_live_impact_by_tambon.png", dpi=170, bbox_inches="tight")
    plt.close(fig)


def fig_models():
    meta = json.loads((PROJECT_DIR / "models/susceptibility/model_metadata.json").read_text())
    df = pd.DataFrame(meta["test_results"]).sort_values("roc_auc")
    selected = meta["best_model"]
    fig, ax = plt.subplots(figsize=(8, 5))
    y = range(len(df))
    ax.barh(list(y), df["roc_auc"], color=RAMP5[2], height=0.55)
    ax.errorbar(df["roc_auc"], list(y), xerr=[df["roc_auc"] - df["roc_auc_ci_low"], df["roc_auc_ci_high"] - df["roc_auc"]],
                fmt="none", ecolor=INK2, elinewidth=1, capsize=2.5)
    ax.set_yticks(list(y)); ax.set_yticklabels([m.replace("_", " ") for m in df["model"]])
    for yi, (m, v, hi) in enumerate(zip(df["model"], df["roc_auc"], df["roc_auc_ci_high"])):
        ax.text(hi + 0.006, yi, f"{v:.3f}" + ("  <- selected (nested spatial CV)" if m == selected else ""), va="center",
                fontsize=8.5, color=INK, fontweight="bold" if m == selected else "normal")
    ax.set_xlim(0.5, 1.14)
    ax.set_xticks([0.5, 0.6, 0.7, 0.8, 0.9, 1.0])
    ax.set_xlabel("Held-out ROC-AUC (95% CI)")
    ax.xaxis.grid(True, color=GRID, linewidth=0.6); ax.set_axisbelow(True)
    ax.set_title("Susceptibility models on the spatial hold-out fold", loc="left")
    fig.savefig(FIG_DIR / "3_model_comparison.png", dpi=170, bbox_inches="tight")
    plt.close(fig)


def fig_population(prov):
    prov = prov[prov["population_high_vh"] > 0].sort_values("population_high_vh")
    fig, ax = plt.subplots(figsize=(8, 5.2))
    y = list(range(len(prov)))
    ax.barh(y, prov["population_high_vh"], color=RAMP5[2], height=0.55)
    ax.set_yticks(y); ax.set_yticklabels(prov["NAME_1"])
    for yi, (v, pct) in enumerate(zip(prov["population_high_vh"], prov["pct_population_in_high_vh"])):
        ax.text(v + prov["population_high_vh"].max() * 0.01, yi, f"{v:,.0f}  ({pct:.1f}% of province)", va="center",
                fontsize=8.5, color=INK2)
    ax.set_xlim(0, prov["population_high_vh"].max() * 1.35)
    ax.set_xlabel("People living in high / very-high susceptibility cells (WorldPop 2020)")
    ax.xaxis.grid(True, color=GRID, linewidth=0.6); ax.set_axisbelow(True)
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.set_title("Population exposed to high landslide susceptibility, by province", loc="left")
    fig.savefig(FIG_DIR / "4_population_by_province.png", dpi=170, bbox_inches="tight")
    plt.close(fig)


def main():
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    boundary = gpd.read_file(PROJECT_DIR / "data/boundary/southern_thailand.geojson").to_crs("EPSG:4326")
    tambons = gpd.read_file(PROJECT_DIR / "data/boundary/southern_thailand_tambons.geojson").to_crs("EPSG:4326")
    overlay = pd.read_csv(PROJECT_DIR / "results/impact_overlay/impact_overlay_by_tambon.csv")
    prov = pd.read_csv(PROJECT_DIR / "results/impact_overlay/impact_overlay_by_province.csv")
    fig_susceptibility(boundary)
    fig_combined(boundary, tambons, overlay)
    fig_models()
    fig_population(prov)
    print("Saved", *sorted(p.name for p in FIG_DIR.glob("*.png")), sep="\n  ")


if __name__ == "__main__":
    main()
