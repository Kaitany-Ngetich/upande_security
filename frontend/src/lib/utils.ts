import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Two decimals with thousands separators — the desk block's `fmt()`, so the
 *  same number reads the same in both UIs while they run side by side. */
export function fmt(n: unknown): string {
  const v = Number(n);
  return (Number.isFinite(v) ? v : 0).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export function num(v: unknown): number {
  const n = parseFloat(String(v));
  return Number.isNaN(n) ? 0 : n;
}

/** Today in the farm's wall clock as YYYY-MM-DD.
 *  Not toISOString(): east of UTC that returns yesterday for the first hours
 *  of the morning, and a feed run posted on the wrong day is a real stock
 *  movement on the wrong day. */
export function todayISO(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

/** A Date as the YYYY-MM-DD the API speaks. Local parts, not UTC: the farm's
 *  day is the farm's day, and toISOString() would shift it across midnight
 *  for anyone east of Greenwich. */
export function ymd(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

/** The inverse. Built from parts rather than new Date(s), which parses a bare
 *  YYYY-MM-DD as UTC midnight and lands on the previous day in a western
 *  timezone. */
export function parseYmd(s: string): Date | undefined {
  const [y, m, d] = (s || "").split("-").map(Number);
  if (!y || !m || !d) return undefined;
  return new Date(y, m - 1, d);
}

/**
 * Convert a 24h ``HH:mm`` into its 12-hour parts. ``hour12`` is zero-padded
 * ("01".."12"); midnight/noon map to "12".
 */
export function to12h(hhmm: string): {
  hour12: string;
  minute: string;
  meridiem: "AM" | "PM";
} {
  const [h, m] = (hhmm || "06:00").split(":").map(Number);
  const hh = Number.isFinite(h) ? h : 6;
  const mm = Number.isFinite(m) ? m : 0;
  const meridiem: "AM" | "PM" = hh < 12 ? "AM" : "PM";
  let h12 = hh % 12;
  if (h12 === 0) h12 = 12;
  const pad = (n: number) => String(n).padStart(2, "0");
  return { hour12: pad(h12), minute: pad(mm), meridiem };
}

/** Build a 24h ``HH:mm`` from 12-hour parts. */
export function from12h(
  hour12: number,
  minute: number,
  meridiem: "AM" | "PM",
): string {
  let h = hour12 % 12; // 12 -> 0
  if (meridiem === "PM") h += 12; // 12PM -> 12, 1PM -> 13
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(h)}:${pad(minute)}`;
}

/** Human 12-hour readout for a 24h ``HH:mm``, e.g. "6:30 AM", "1:05 PM". */
export function format12h(hhmm: string): string {
  const { hour12, minute, meridiem } = to12h(hhmm);
  return `${Number(hour12)}:${minute} ${meridiem}`;
}

/**
 * Step an ``HH:mm`` time by one unit. Minutes move by ``minuteStep`` (default 5)
 * and carry into the hour like a real clock; hours wrap 23 <-> 00. ``dir`` is
 * ``+1`` (up) or ``-1`` (down). Returns a zero-padded ``HH:mm`` string.
 */
export function stepTime(
  value: string,
  field: "hour" | "minute",
  dir: 1 | -1,
  minuteStep = 5,
): string {
  const [hRaw, mRaw] = (value || "06:00").split(":").map(Number);
  let h = Number.isFinite(hRaw) ? hRaw : 6;
  let m = Number.isFinite(mRaw) ? mRaw : 0;
  if (field === "hour") {
    h = (h + dir + 24) % 24;
  } else {
    let total = h * 60 + m + dir * minuteStep;
    total = ((total % 1440) + 1440) % 1440; // wrap within a day
    h = Math.floor(total / 60);
    m = total % 60;
  }
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(h)}:${pad(m)}`;
}


/** Every whitespace-separated word of `query` appears in `text`, ignoring
 *  case, spaces and punctuation ("gh16" finds "GH 16"). */
export function matchesQuery(text: string, query: string): boolean {
  const compact = (v: string) => v.toLowerCase().replace(/[^a-z0-9]+/g, "");
  const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return true;
  const hay = compact(text);
  return words.every((w) => hay.includes(compact(w)));
}

/** {from, to} for the current ISO week (Monday to Sunday). */
export function currentWeekRange(): { from: string; to: string } {
  const mon = new Date();
  const wd = (mon.getDay() + 6) % 7; // 0 = Monday ... 6 = Sunday
  mon.setDate(mon.getDate() - wd);
  const sun = new Date(mon);
  sun.setDate(mon.getDate() + 6);
  return { from: ymd(mon), to: ymd(sun) };
}
