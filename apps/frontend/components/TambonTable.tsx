import { Badge } from "@/components/Badge";
import { STICKY_COL, STICKY_HEAD, TableScroll } from "@/components/Section";
import { fmtInt, fmtMm } from "@/lib/classes";

// One table layout for the live forecast and the what-if scenario, so both read the same way.
// The tambon name stays in view while the other columns scroll; units are in the headers.
export interface TambonRow {
  id: string;
  name: string;
  province: string | null;
  impact: string;
  /** Class against the tambon's own percentiles; `rainKind` says whether it is that or the fixed-mm fallback. */
  rainClass: string | null;
  terrain: string;
  rain24: number | null;
  rain72?: number | null;
  rain120?: number | null;
  p90: number | null;
  people: number;
}

export default function TambonTable({
  rows,
  label,
  outlook = false,
  rainDigits = 1,
}: {
  rows: TambonRow[];
  label: string;
  /** Show the 72 h and 5-day totals (the live forecast has them; a scenario does not). */
  outlook?: boolean;
  rainDigits?: number;
}) {
  return (
    <TableScroll label={label}>
      <table className={`data-table ${outlook ? "min-w-[820px]" : "min-w-[680px]"}`}>
        <thead>
          <tr>
            <th scope="col" className={STICKY_HEAD}>
              Tambon
            </th>
            <th scope="col">Impact</th>
            <th scope="col">Rain vs local normal</th>
            <th scope="col">Terrain tier</th>
            <th scope="col" className="text-right">
              Rain 24 h (mm)
            </th>
            {outlook && (
              <>
                <th scope="col" className="text-right">
                  72 h (mm)
                </th>
                <th scope="col" className="text-right">
                  5 days (mm)
                </th>
              </>
            )}
            <th scope="col" className="text-right">
              Local P90 (mm)
            </th>
            <th scope="col" className="text-right">
              People at elevated risk
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((t) => (
            <tr key={t.id}>
              <th scope="row" className={`${STICKY_COL} max-w-36 border-b border-line px-3 py-2 text-left font-normal sm:max-w-none [tr:last-child_&]:border-b-0`}>
                <span className="block font-medium">{t.name}</span>
                <span className="block text-xs text-muted">{t.province ?? "—"}</span>
              </th>
              <td>
                <Badge kind="impact" cls={t.impact} />
              </td>
              <td>{t.rainClass ? <Badge kind="rain" cls={t.rainClass} /> : "—"}</td>
              <td>
                <Badge kind="terrain" cls={t.terrain} />
              </td>
              <td className="text-right tabular-nums">{fmtMm(t.rain24, rainDigits)}</td>
              {outlook && (
                <>
                  <td className="text-right tabular-nums">{fmtMm(t.rain72, rainDigits)}</td>
                  <td className="text-right tabular-nums">{fmtMm(t.rain120, rainDigits)}</td>
                </>
              )}
              <td className="text-right tabular-nums">{fmtMm(t.p90, 0)}</td>
              <td className="text-right tabular-nums">{fmtInt(t.people)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </TableScroll>
  );
}
