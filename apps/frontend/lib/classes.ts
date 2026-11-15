// Class colours and labels for the content pages (Overview, Early Warning, Model, Data).
// The hex values mirror the legends of the Live Impact map (SUSCEPTIBILITY_CLASSES and TAMBON_MODES in
// components/ImpactMap.tsx), so a class looks the same on every page. Keep the two in step.

export type ClassKind = "impact" | "terrain" | "rain";

export interface ClassDef {
  key: string;
  label: string;
  /** null = not shaded on the map; drawn as a hollow swatch. */
  color: string | null;
  note?: string;
}

/** Live impact class of a tambon (terrain tier × rain class). */
export const IMPACT_CLASSES: ClassDef[] = [
  { key: "very_high", label: "Very high", color: "#b91c1c" },
  { key: "high", label: "High", color: "#f97316" },
  { key: "moderate", label: "Moderate", color: "#facc15" },
  { key: "low", label: "Low", color: null, note: "not shaded on the map" },
  { key: "not_assessed", label: "Not assessed", color: "#9ca3af" },
];

/** Terrain tier of a tambon: the share of its 250 m cells that are high or very high. */
export const TERRAIN_CLASSES: ClassDef[] = [
  { key: "high", label: "High", color: "#104281", note: "40% or more" },
  { key: "moderate", label: "Moderate", color: "#2a78d6", note: "15–40%" },
  { key: "low", label: "Low", color: "#86b6ef", note: "under 15%" },
  { key: "no_data", label: "No data", color: "#9ca3af" },
];

/** Forecast 24 h rain against the tambon's own wet-day percentiles. */
export const RAIN_CLASSES: ClassDef[] = [
  { key: "above_p95", label: "Above P95", color: "#5b21b6", note: "top 5% of rainy days" },
  { key: "p90_p95", label: "P90–P95", color: "#8b5cf6", note: "top 10%" },
  { key: "p75_p90", label: "P75–P90", color: "#c4b5fd", note: "top 25%" },
  { key: "below_p75", label: "Below P75", color: "#ede9fe", note: "ordinary rain" },
];

/** The five classes of the 250 m susceptibility map, with their calibrated score ranges. */
export const SUSCEPTIBILITY_CLASSES: Array<ClassDef & { range: string }> = [
  { key: "very_low", label: "Very low", range: "0.2 or less", color: "#cde2fb" },
  { key: "low", label: "Low", range: "0.2–0.4", color: "#86b6ef" },
  { key: "moderate", label: "Moderate", range: "0.4–0.6", color: "#2a78d6" },
  { key: "high", label: "High", range: "0.6–0.8", color: "#1c5cab" },
  { key: "very_high", label: "Very high", range: "above 0.8", color: "#104281" },
];

export const CLASSES: Record<ClassKind, ClassDef[]> = {
  impact: IMPACT_CLASSES,
  terrain: TERRAIN_CLASSES,
  rain: RAIN_CLASSES,
};

/** Order used wherever impact classes are listed, most severe first. */
export const IMPACT_ORDER = IMPACT_CLASSES.map((c) => c.key);

/** "very_heavy" -> "Very heavy", for class keys with no entry above (e.g. the fixed-mm rain classes). */
export function humanise(key: string): string {
  const s = key.replaceAll("_", " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function classDef(kind: ClassKind, key: string): ClassDef {
  return CLASSES[kind].find((c) => c.key === key) ?? { key, label: humanise(key), color: "#9ca3af" };
}

/** "1 tambon" / "27 tambons". */
export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n.toLocaleString("en-US")} ${n === 1 ? one : many}`;
}

/** Whole numbers with thousands separators; an em dash when the value is missing. */
export function fmtInt(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return Math.round(n).toLocaleString("en-US");
}

/** A number of millimetres to a fixed number of decimals, without the unit (the unit goes in the column header). */
export function fmtMm(n: number | null | undefined, digits = 1): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return n.toFixed(digits);
}
