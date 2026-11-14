/** "3 h ago" / "2 d ago" for an ISO timestamp, so a stale forecast is visible at a glance. */
export function ageLabel(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return "";
  const hours = Math.max(0, (now - new Date(iso).getTime()) / 3_600_000);
  if (hours < 1) return "under 1 h ago";
  if (hours < 48) return `${Math.round(hours)} h ago`;
  return `${Math.round(hours / 24)} d ago`;
}

/** True when the forecast run is older than `maxHours` (GFS issues a run every 6 h, so 18 h means at least two were missed). */
export function isStale(iso: string | null | undefined, maxHours = 18, now: number = Date.now()): boolean {
  return !!iso && (now - new Date(iso).getTime()) / 3_600_000 > maxHours;
}

/** A timestamp on the Thai clock (UTC+7, no daylight saving), labelled so it cannot be read as UTC. The dashboard's
 *  users are in Thailand; the forecast files keep UTC. */
export function thaiTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Bangkok" }) + " Thailand time";
}
