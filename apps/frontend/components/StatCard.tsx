import type { LucideIcon } from "lucide-react";

export default function StatCard({
  label,
  value,
  sub,
  icon: Icon,
}: {
  label: string;
  value: string;
  sub?: string;
  icon?: LucideIcon;
}) {
  return (
    <div className="card p-4">
      <div className="flex items-center justify-between gap-2">
        <div className="eyebrow">{label}</div>
        {Icon && <Icon className="h-4 w-4 shrink-0 text-accent" aria-hidden />}
      </div>
      <div className="mt-2 text-2xl font-semibold tabular-nums tracking-tight">{value}</div>
      {sub && <div className="mt-1 text-xs leading-snug text-muted">{sub}</div>}
    </div>
  );
}
