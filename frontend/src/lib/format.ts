/** Number and date formatting shared by the production pages.
 *  A fixed locale so a figure reads the same on every machine on the farm. */

const LOCALE = "en-US";

/** Thousands separators, no decimals unless asked: 12,345 */
export function qty(n: number | null | undefined, decimals = 0): string {
  if (n == null || !Number.isFinite(Number(n))) return "—";
  return Number(n).toLocaleString(LOCALE, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

/** Kenyan shillings, whole shillings: KES 1,234,567. null (hidden pay) is a dash. */
export function kes(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(Number(n))) return "—";
  return `KES ${qty(n, 0)}`;
}

/** Hectares with one decimal: 12.3 */
export function ha(n: number | null | undefined): string {
  return qty(n, 1);
}

/** 2026-03-09 -> 9 Mar 2026. Anything unparseable comes back as a dash. */
export function shortDate(ymd: string | null | undefined): string {
  if (!ymd) return "—";
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(ymd);
  if (!m) return "—";
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

/** A quantity in plain figures: whole stays whole, otherwise up to 2 decimals with zeros trimmed
 *  (2.1, 6.4, 6, 1,250.25). One formatter for entries, totals and step lines so a number never
 *  reads two ways on the same screen. */
export function trimQty(n: unknown): string {
  const v = Number(n);
  return (Number.isFinite(v) ? v : 0).toLocaleString(LOCALE, { maximumFractionDigits: 2 });
}

/** One quantity with its unit of measure. Never add these across UOMs. */
export interface UomQty {
  uom: string;
  qty: number;
}

/** Sum quantities per UOM (never across), biggest first. */
export function sumByUom<T>(items: T[], pick: (item: T) => { uom?: string | null; qty?: number | null }): UomQty[] {
  const acc = new Map<string, number>();
  for (const it of items) {
    const { uom, qty: n } = pick(it);
    acc.set(uom || "", (acc.get(uom || "") ?? 0) + (Number(n) || 0));
  }
  return [...acc].map(([uom, n]) => ({ uom, qty: n })).sort((a, b) => b.qty - a.qty || a.uom.localeCompare(b.uom));
}

/** Merge several per-UOM lists into one (still per UOM). */
export function mergeUoms(lists: (UomQty[] | undefined)[]): UomQty[] {
  return sumByUom(lists.flatMap((l) => l ?? []), (x) => x);
}

/** "6 Hectare · 309 Tree"; nothing recorded reads "—". */
export function formatUoms(list: UomQty[] | undefined | null): string {
  const parts = (list ?? []).filter((x) => x.qty !== 0).map((x) => `${trimQty(x.qty)}${x.uom ? ` ${x.uom}` : ""}`);
  return parts.length ? parts.join(" · ") : "—";
}
