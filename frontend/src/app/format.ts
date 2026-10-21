import { displayTimeZone } from "./timeRange";

/** Content conventions (PDS §3.3, §7): DD-Mon HH:MM in tables, ISO 8601 in tooltips. */

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function parts(date: Date, timeZone: string): Record<string, string> {
  const formatter = new Intl.DateTimeFormat("en-GB", {
    timeZone,
    year: "numeric",
    month: "numeric",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  });
  return Object.fromEntries(formatter.formatToParts(date).map((p) => [p.type, p.value]));
}

/** "21-Oct 14:05" in the display time zone. */
export function formatDateTime(date: Date, timeZone = displayTimeZone()): string {
  const p = parts(date, timeZone);
  return `${p.day}-${MONTHS[Number(p.month) - 1]} ${p.hour}:${p.minute}`;
}

/** "14:05" in the display time zone. */
export function formatTime(date: Date, timeZone = displayTimeZone()): string {
  const p = parts(date, timeZone);
  return `${p.hour}:${p.minute}`;
}

export function formatIso(date: Date): string {
  return date.toISOString();
}

/** Health Score as an integer (PDS §3.3); "—" when there is none. */
export function formatHealth(health: number | null | undefined): string {
  return health === null || health === undefined ? "—" : String(Math.round(health));
}

/** DI to one decimal with "%". */
export function formatDi(di: number | null | undefined): string {
  return di === null || di === undefined ? "—" : `${di.toFixed(1)} %`;
}

/** z to one decimal with its sign. */
export function formatZ(z: number | null | undefined): string {
  if (z === null || z === undefined) return "—";
  const text = Math.abs(z).toFixed(1);
  return z < 0 ? `−${text}` : `+${text}`;
}

/** "3 h 20 min", "45 min", "2 d 4 h": what is left of a shelf, for example. */
export function formatDuration(ms: number): string {
  const minutes = Math.max(0, Math.round(ms / 60_000));
  const days = Math.floor(minutes / 1440);
  const hours = Math.floor((minutes % 1440) / 60);
  const mins = minutes % 60;
  if (days) return hours ? `${days} d ${hours} h` : `${days} d`;
  if (hours) return mins ? `${hours} h ${mins} min` : `${hours} h`;
  return `${mins} min`;
}
