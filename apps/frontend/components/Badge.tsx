import { CLASSES, classDef, type ClassKind } from "@/lib/classes";

// A class is shown as a colour swatch plus its name in normal text. The swatch carries the Live Impact map's colour
// unchanged; the name stays readable in both themes, which coloured text on a tinted pill would not for the yellows
// and pale violets.
export function Swatch({ color }: { color: string | null }) {
  return (
    <span
      aria-hidden
      className={`inline-block h-3 w-3 shrink-0 rounded-[3px] border ${color ? "border-black/15 dark:border-white/25" : "border-dashed border-muted"}`}
      style={color ? { backgroundColor: color } : undefined}
    />
  );
}

export function Badge({ kind, cls }: { kind: ClassKind; cls: string }) {
  const def = classDef(kind, cls);
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-sm">
      <Swatch color={def.color} />
      {def.label}
    </span>
  );
}

/** How many tambons fall in each class, as a wrapping row of chips. Classes with no tambon are left out. */
export function ClassCounts({
  kind,
  counts,
  unit = "tambon",
}: {
  kind: ClassKind;
  counts: Record<string, number> | undefined;
  unit?: string;
}) {
  const rows = CLASSES[kind].filter((c) => counts && counts[c.key]);
  if (!rows.length) return null;
  return (
    <ul className="flex flex-wrap gap-2">
      {rows.map((c) => (
        <li key={c.key} className="flex items-center gap-2 rounded-lg border border-line bg-surface px-3 py-1.5 text-sm">
          <Badge kind={kind} cls={c.key} />
          <span className="tabular-nums text-muted">
            {counts![c.key].toLocaleString("en-US")} {counts![c.key] === 1 ? unit : `${unit}s`}
          </span>
        </li>
      ))}
    </ul>
  );
}

/** The classes of one kind with their short notes: the legend for the badges in a table. */
export function ClassLegend({ kind, exclude = [] }: { kind: ClassKind; exclude?: string[] }) {
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1.5">
      {CLASSES[kind]
        .filter((c) => !exclude.includes(c.key))
        .map((c) => (
          <li key={c.key} className="flex items-center gap-1.5 text-sm">
            <Swatch color={c.color} />
            <span>{c.label}</span>
            {c.note && <span className="text-xs text-muted">({c.note})</span>}
          </li>
        ))}
    </ul>
  );
}
