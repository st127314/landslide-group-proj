import type { LucideIcon } from "lucide-react";
import { LABEL } from "@/components/Section";

// One tile for a headline figure. Long values wrap instead of being clipped.
export default function StatCard({
  label,
  value,
  sub,
  icon: Icon,
  small = false,
}: {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  icon?: LucideIcon;
  /** For values that are a phrase (a date, a model name) rather than a figure. */
  small?: boolean;
}) {
  return (
    <div className="min-w-0 rounded-xl border border-line bg-surface p-4">
      <div className="flex items-start justify-between gap-2">
        <div className={LABEL}>{label}</div>
        {Icon && <Icon className="h-4 w-4 shrink-0 text-accent" aria-hidden />}
      </div>
      <div
        className={`mt-2 font-semibold tracking-tight tabular-nums [overflow-wrap:anywhere] ${small ? "text-base leading-snug" : "text-2xl leading-tight"}`}
      >
        {value}
      </div>
      {sub && <div className="mt-1.5 text-xs leading-snug text-muted">{sub}</div>}
    </div>
  );
}
