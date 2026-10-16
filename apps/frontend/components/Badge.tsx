// Shared colour-coded badges for impact, terrain and rainfall classes.
export const CLASS_COLORS: Record<string, string> = {
  // terrain tier + live impact class
  low: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  moderate: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  high: "bg-orange-100 text-orange-800 dark:bg-orange-950 dark:text-orange-300",
  very_high: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
  // 24 h rainfall class against the tambon's own wet-day percentiles
  below_p75: "bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-300",
  p75_p90: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  p90_p95: "bg-orange-100 text-orange-800 dark:bg-orange-950 dark:text-orange-300",
  above_p95: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
  // 24 h rainfall class, absolute mm
  light: "bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-300",
  heavy: "bg-orange-100 text-orange-800 dark:bg-orange-950 dark:text-orange-300",
  very_heavy: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
};

export const CLASS_LABELS: Record<string, string> = {
  below_p75: "below P75",
  p75_p90: "P75–P90",
  p90_p95: "P90–P95",
  above_p95: "above P95",
  not_assessed: "not assessed",
};

export function Badge({ cls }: { cls: string }) {
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-xs font-medium ${
        CLASS_COLORS[cls] ?? "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300"
      }`}
    >
      {CLASS_LABELS[cls] ?? cls.replace("_", " ")}
    </span>
  );
}
