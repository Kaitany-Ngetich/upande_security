import { useId, useState } from "react";
import { cn } from "@/lib/utils";

export interface SeriesPoint {
  week: string;
  date?: string;
  value: number;
  /** The week is still running: its figure is incomplete, so it is not a basis for a delta. */
  partial?: boolean;
}
export type KpiSeries = Record<string, SeriesPoint[]>;
export interface KpiSeriesPayload { series: KpiSeries }

/** Fewer points than this is not a trend: the line is drawn faint. */
export const MIN_TREND_POINTS = 3;

const W = 58;
const H = 26;
const PAD = 3;

export interface SeriesDelta {
  dir: "up" | "down" | "flat";
  pct: number | null;
  abs: number;
  /** True when the still-running week was skipped to compare the last two full weeks. */
  fullWeeks: boolean;
}

/** Monday of the week a series label names: "YYYY-MM-DD" (any day) or "YYYY-Www". */
function weekStart(week: string): Date | null {
  const iso = /^(\d{4})-W(\d{2})$/.exec(week);
  if (iso) {
    const jan4 = new Date(Number(iso[1]), 0, 4);
    const mon = new Date(jan4.getFullYear(), 0, 4 - ((jan4.getDay() + 6) % 7));
    mon.setDate(mon.getDate() + (Number(iso[2]) - 1) * 7);
    return mon;
  }
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(week);
  if (!m) return null;
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
  return d;
}

/** Flag the point whose ISO week contains `now`: that week is not over, so its figure is incomplete.
 *  For series keyed by week (week start date or "YYYY-Www"), not for point-in-time snapshots. */
export function flagCurrentWeek(points: SeriesPoint[] | undefined, now = new Date()): SeriesPoint[] | undefined {
  if (!points) return points;
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  return points.map((p) => {
    const s = weekStart(p.week);
    if (!s) return p;
    const start = s.getTime();
    const end = new Date(s.getFullYear(), s.getMonth(), s.getDate() + 7).getTime();
    return today >= start && today < end ? { ...p, partial: true } : p;
  });
}

/** Flag the still-running period on any series, weekly or daily, unless the caller already did.
 *  A series is daily when two of its points fall in the same week; then only today's point is
 *  partial. KpiCard applies this to every series so no page can show a delta against a period
 *  that has not finished. */
export function flagRunningPeriod(points: SeriesPoint[] | undefined, now = new Date()): SeriesPoint[] | undefined {
  if (!points || points.some((p) => p.partial)) return points;
  const starts = points.map((p) => weekStart(p.week)?.getTime());
  const daily = starts.some((t, i) => i > 0 && t != null && t === starts[i - 1]);
  if (!daily) return flagCurrentWeek(points, now);
  const pad = (n: number) => String(n).padStart(2, "0");
  const today = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
  return points.map((p) => ((p.date ?? p.week).slice(0, 10) === today ? { ...p, partial: true } : p));
}

/** A line worth drawing: two or more points that are not all the same value. */
export function hasTrend(points?: SeriesPoint[]): points is SeriesPoint[] {
  return !!points && points.length >= 2 && points.some((p) => p.value !== points[0].value);
}

/**
 * Change between the last two COMPLETE periods (a trailing partial week is skipped).
 * Null, so no chip, when there is no meaningful basis: fewer than two periods, a flat
 * series, or a previous value of 0 (a percentage of nothing).
 */
export function seriesDelta(points?: SeriesPoint[]): SeriesDelta | null {
  if (!hasTrend(points)) return null;
  const done = points[points.length - 1].partial ? points.slice(0, -1) : points;
  if (done.length < 2) return null;
  const cur = done[done.length - 1].value;
  const prev = done[done.length - 2].value;
  if (prev === 0) return null;
  const abs = cur - prev;
  return { dir: abs > 0 ? "up" : abs < 0 ? "down" : "flat", pct: (abs / Math.abs(prev)) * 100, abs, fullWeeks: done.length < points.length };
}

/**
 * Tiny inline-SVG trend for a KPI card, after the UFD reference cards: a smooth
 * 2px bezier line with a quiet-to-ink gradient and round caps, 58x26, no axes,
 * fill or gridlines, plus an end dot. Pinned to the card's top-right corner. Hover shows the week and
 * value. Muted (faint) when there are fewer than MIN_TREND_POINTS points.
 */
export function Sparkline({ points, className }: { points?: SeriesPoint[]; className?: string }) {
  const [hover, setHover] = useState<number | null>(null);
  const gid = `spark-${useId().replace(/:/g, "")}`;
  if (!hasTrend(points)) return null;

  const muted = points.length < MIN_TREND_POINTS;
  const vals = points.map((p) => p.value);
  const lo = Math.min(...vals);
  const hi = Math.max(...vals);
  const span = hi - lo || 1;
  const n = points.length;
  const xy = points.map((p, i) => ({
    x: n === 1 ? W / 2 : PAD + (i * (W - PAD * 2)) / (n - 1),
    y: hi === lo ? H / 2 : H - PAD - ((p.value - lo) / span) * (H - PAD * 2),
  }));
  // Smooth cubic through the points (horizontal tangents at each, like the reference).
  const path = xy
    .map((q, i) => {
      if (i === 0) return `M${q.x.toFixed(1)} ${q.y.toFixed(1)}`;
      const p = xy[i - 1];
      const mx = ((p.x + q.x) / 2).toFixed(1);
      return `C${mx} ${p.y.toFixed(1)} ${mx} ${q.y.toFixed(1)} ${q.x.toFixed(1)} ${q.y.toFixed(1)}`;
    })
    .join(" ");
  const end = xy[n - 1];
  const hp = hover === null ? null : points[hover];

  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const x = ((e.clientX - r.left) / (r.width || W)) * W;
    let best = 0;
    xy.forEach((q, i) => { if (Math.abs(q.x - x) < Math.abs(xy[best].x - x)) best = i; });
    setHover(best);
  };

  return (
    <div
      data-testid="kpi-sparkline"
      data-muted={muted ? "true" : "false"}
      className={cn(
        "kpi-sparkline absolute right-4 top-5 text-[var(--sd-ink)]",
        muted ? "opacity-30" : "opacity-90",
        "transition-opacity",
        className,
      )}
    >
      <svg
        width={W} height={H} viewBox={`0 0 ${W} ${H}`}
        role="img" aria-label="Trend by week"
        onMouseMove={onMove} onMouseLeave={() => setHover(null)}
      >
        <defs>
          <linearGradient id={gid} x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="var(--sd-quiet)" />
            <stop offset="100%" stopColor="var(--sd-ink)" />
          </linearGradient>
        </defs>
        <path d={path} fill="none" stroke={`url(#${gid})`} strokeWidth={2}
              strokeLinejoin="round" strokeLinecap="round" />
        {n > 1 && <circle data-testid="spark-dot" cx={end.x} cy={end.y} r={2.2} fill="var(--sd-ink)" />}
        {hover !== null && (
          <circle cx={xy[hover].x} cy={xy[hover].y} r={2.8} fill="var(--sd-ink)" />
        )}
      </svg>
      {hp && (
        <div
          role="tooltip"
          className="pointer-events-none absolute right-0 top-full z-10 mt-1 whitespace-nowrap rounded-md bg-[var(--sd-ink)] px-2 py-1 text-[11px] text-white shadow-md"
        >
          {hp.week}: {hp.value.toLocaleString("en-US")}
        </div>
      )}
    </div>
  );
}
