// Records per local day, counted only from the incident summaries already loaded for the
// overview. No counts endpoint exists, so this never claims totals beyond that window.
import type { IncidentSummary } from "../../lib/api/types";

export interface DayCount {
  /** Local calendar day, YYYY-MM-DD. */
  day: string;
  label: string;
  count: number;
}

const DAY_LABEL = new Intl.DateTimeFormat(undefined, { weekday: "short", day: "numeric", month: "short" });

function localDayKey(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${String(date.getFullYear())}-${month}-${day}`;
}

/** Newest day first; days without records are omitted; invalid timestamps are skipped. */
export function countByDay(items: readonly IncidentSummary[], maxDays = 7): DayCount[] {
  const days = new Map<string, DayCount>();
  for (const item of items) {
    const date = new Date(item.occurred_at);
    if (Number.isNaN(date.getTime())) continue;
    const key = localDayKey(date);
    const entry = days.get(key);
    if (entry === undefined) {
      days.set(key, { day: key, label: DAY_LABEL.format(date), count: 1 });
    } else {
      entry.count += 1;
    }
  }
  return [...days.values()].sort((a, b) => (a.day < b.day ? 1 : -1)).slice(0, maxDays);
}
