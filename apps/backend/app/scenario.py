"""What-if rainfall scenarios on top of the live-impact overlay.

"What if X mm falls in 24 hours (optionally in one province only)?" is answered from the finished overlay
(`results/impact_overlay/impact_overlay.json`): every tambon already carries its terrain tier, its local wet-day
rainfall percentiles (P75 / P90 / P95) and the people, buildings and facilities living on its high / very-high
susceptibility ground. A scenario only swaps the tambon's 24 h rainfall for X mm and re-applies the same rule as
`scripts/build_impact_overlay.py`, so it needs no Earth Engine call and answers in milliseconds.

Keep the constants below in step with that script (RAIN_BASIS = "percentile"):
  impact class = bins of (terrain factor x local rain class index)
  terrain factor low / moderate / high tier         -> 1 / 2 / 3
  local class    below P75 / P75-P90 / P90-P95 / above P95 -> 0 / 1 / 2 / 3
  bins           0-1 low, 2-3 moderate, 4-6 high, >= 7 very_high
A product, not a sum: rain alone creates no risk on terrain that cannot slide, and "very high" needs the steepest tier
AND rain above the tambon's P95.
No machine-learning model and no AI assistant is involved: this is plain arithmetic on published numbers.
"""

MAX_RAIN_24H_MM = 1500.0   # same ceiling other screening tools use; larger inputs are rejected
TIER_FACTOR = {"low": 1, "moderate": 2, "high": 3}
LOCAL_CLASS_NAMES = ["below_p75", "p75_p90", "p90_p95", "above_p95"]
IMPACT_ORDER = ["very_high", "high", "moderate", "low", "not_assessed"]
ELEVATED = ("high", "very_high")

LIMITATIONS = [
    "A scenario applies the same 24 h rainfall to every tambon in scope, but real storms are patchy.",
    "Rain is classed against each tambon's own wet-day rainfall percentiles (CHIRPS 1991-2020, on the GFS grid): this says "
    "how unusual the rain is for the place, not whether it triggers landslides. The thresholds are not calibrated on "
    "landslide records.",
    "The impact class is a transparent triage rule (terrain tier + rain class), not a calibrated probability or a "
    "validated landslide forecast; terrain susceptibility is a relative ranking.",
    "Exposure counts people, buildings and facilities on high / very-high susceptibility ground only (WorldPop 2020, OSM).",
]


def local_class_index(rain_mm, p75, p90, p95):
    """0..3 against the tambon's own percentiles; None when the tambon has no thresholds."""
    if rain_mm is None or p75 is None or p90 is None or p95 is None:
        return None
    if rain_mm >= p95:
        return 3
    if rain_mm >= p90:
        return 2
    if rain_mm >= p75:
        return 1
    return 0


def impact_class(tier, rain_index):
    if tier not in TIER_FACTOR or rain_index is None:
        return "not_assessed"
    product = TIER_FACTOR[tier] * rain_index
    return "low" if product <= 1 else "moderate" if product <= 3 else "high" if product <= 6 else "very_high"


def run(overlay, rain_24h_mm=None, province=None, limit=25):
    """Evaluate the overlay under a scenario.

    rain_24h_mm None  -> the live GFS forecast already stored in the overlay (reproduces the overlay's own classes);
    otherwise         -> that amount replaces the 24 h rainfall of every tambon in `province` (all tambons if None);
                         tambons outside the province keep the live forecast.
    """
    tambons = overlay["tambons"]
    rows = []
    for t in tambons:
        in_scope = province is None or t.get("NAME_1") == province
        rain = rain_24h_mm if (rain_24h_mm is not None and in_scope) else t.get("gfs_rain_24h_mm")
        idx = local_class_index(rain, t.get("local_p75_mm"), t.get("local_p90_mm"), t.get("local_p95_mm"))
        cls = impact_class(t.get("susceptibility_tier"), idx)
        elevated = cls in ELEVATED
        rows.append({
            "GID_3": t["GID_3"], "NAME_3": t.get("NAME_3"), "NAME_2": t.get("NAME_2"), "NAME_1": t.get("NAME_1"),
            "susceptibility_tier": t.get("susceptibility_tier"),
            "rain_24h_mm": None if rain is None else round(float(rain), 1),
            "local_p90_mm": t.get("local_p90_mm"),
            "rain_local_class_24h": None if idx is None else LOCAL_CLASS_NAMES[idx],
            "impact_class": cls, "in_scope": in_scope,
            "population_at_elevated_risk": int(t.get("population_high_vh") or 0) if elevated else 0,
            "buildings_at_elevated_risk": int(t.get("buildings_high_vh") or 0) if elevated else 0,
            "facilities_at_elevated_risk": int(t.get("facilities_high_vh") or 0) if elevated else 0,
        })

    by_class = {}
    for r in rows:
        by_class[r["impact_class"]] = by_class.get(r["impact_class"], 0) + 1
    by_province = {}
    for r in rows:
        p = by_province.setdefault(r["NAME_1"], {"NAME_1": r["NAME_1"], "tambons_high_or_above": 0,
                                                 "population_at_elevated_risk": 0})
        p["tambons_high_or_above"] += r["impact_class"] in ELEVATED
        p["population_at_elevated_risk"] += r["population_at_elevated_risk"]
    ranked = sorted(rows, key=lambda r: (IMPACT_ORDER.index(r["impact_class"]), -r["population_at_elevated_risk"],
                                         -(r["rain_24h_mm"] or 0)))
    in_scope = [r for r in rows if r["in_scope"]]
    return {
        "scenario": {
            "rain_24h_mm": rain_24h_mm, "province": province,
            "description": ("live GFS forecast (no scenario applied)" if rain_24h_mm is None else
                            f"{rain_24h_mm:g} mm in 24 h applied to " + (province if province else "every tambon")
                            + ("; other provinces keep the live forecast" if province else "")),
            "basis": "24 h rain vs each tambon's own wet-day percentiles (P75 / P90 / P95)",
        },
        "summary": {
            "tambons": len(rows), "tambons_in_scope": len(in_scope),
            "tambons_by_impact_class": {k: by_class[k] for k in IMPACT_ORDER if k in by_class},
            "tambons_above_p95": sum(r["rain_local_class_24h"] == "above_p95" for r in rows),
            "population_at_elevated_risk": sum(r["population_at_elevated_risk"] for r in rows),
            "buildings_at_elevated_risk": sum(r["buildings_at_elevated_risk"] for r in rows),
            "facilities_at_elevated_risk": sum(r["facilities_at_elevated_risk"] for r in rows),
        },
        "provinces": sorted(by_province.values(), key=lambda p: (-p["population_at_elevated_risk"], p["NAME_1"] or "")),
        "tambons": ranked[:limit],
        "limitations": LIMITATIONS,
    }
