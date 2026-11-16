import { Card } from "@/components/ui/card";
import { KpiValueSkeleton, TextSkeleton } from "@/components/Loading";
import { cn } from "@/lib/utils";
import { Sparkline, flagRunningPeriod, seriesDelta, type SeriesPoint } from "@/components/Sparkline";

export interface KpiCardProps {
  label: string;
  value: string | number;
  hint?: string;
  tone?: "default" | "warning" | "critical" | "good" | "accent";
  className?: string;
  /** First load: the label stays, the figure and hint are placeholders. */
  loading?: boolean;
  /** Weekly values for the top-right sparkline; omit for no trend. */
  series?: SeriesPoint[];
  /** Which direction is good news; tints the delta pill. Neutral when omitted. */
  goodDirection?: "up" | "down";
  /** Text after the delta pill (default "vs prev week"). */
  deltaLabel?: string;
  /** Makes the whole card a link (hash route to the page the figure belongs to). */
  href?: string;
  /** Set false for a series whose last point is not "this period" (e.g. a look-ahead forecast). */
  showDelta?: boolean;
}

const TONE: Record<NonNullable<KpiCardProps["tone"]>, string> = {
  default: "text-foreground",
  warning: "text-[var(--sd-target)]",
  critical: "text-[var(--sd-data-red)]",
  /** "good" and "accent" are the crop's own highlight colour (--crop-accent, set by CropProvider);
   *  generic green only when there is no crop. Warnings stay amber/red. */
  good: "text-[var(--crop-accent,var(--sd-data-green))]",
  accent: "text-[var(--crop-accent,var(--sd-data-green))]",
};

export function KpiCard({ label, value, hint, tone = "default", className, loading = false, series, goodDirection, deltaLabel, href, showDelta = true }: KpiCardProps) {
  const delta = loading || !showDelta ? null : seriesDelta(flagRunningPeriod(series));
  // Thousands separators for large counts (e.g. 648361 → 648,361).
  const display =
    typeof value === "number" ? value.toLocaleString("en-US") : String(value);
  const card = (
    <Card
      className={cn(
        href && "h-full cursor-pointer",
        // Reference .kpi: roomy padding, soft shadow (from Card), and a
        // hover-lift so the metric tiles feel alive. No cursor-pointer —
        // these aren't clickable in this app.
        "relative flex flex-col overflow-hidden p-6 transition-all duration-200",
        "hover:-translate-y-[3px] hover:shadow-[var(--sd-shadow-2)]",
        className,
      )}
    >
      {!loading && <Sparkline points={series} />}
      {/* .kpi__label — 11px, uppercase, wide tracking */}
      <div className="mb-3 text-[11px] font-medium uppercase tracking-[0.16em] text-[var(--sd-quiet)] pr-24">
        {label}
      </div>
      {/* .kpi__value — hero 44px number, tight tracking, tabular */}
      {loading ? (
        <KpiValueSkeleton className="h-[36px] md:h-[44px] w-20" />
      ) : (
        <div
          className={cn(
            "font-semibold leading-tight tracking-[-0.03em] tabular-nums break-words",
            figureSize(display),
            TONE[tone],
          )}
        >
          {display}
        </div>
      )}
      {loading ? (
        <div className="mt-2 text-[13px] leading-5">
          <TextSkeleton width="10ch" />
        </div>
      ) : hint && (
        <div className="mt-2 text-[13px] text-[var(--sd-quiet)] line-clamp-2">
          {hint}
        </div>
      )}
      {delta && <DeltaPill delta={delta} goodDirection={goodDirection} label={deltaLabel} />}
    </Card>
  );
  return href ? (
    <a href={href} className="block h-full rounded-[var(--sd-radius-lg)] text-inherit no-underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40">
      {card}
    </a>
  ) : (
    card
  );
}

/** Hero size for short figures, stepping down for long ones ("KES 4,381", "6 Hectare · 309 Tree") so they fit the card. */
function figureSize(display: string): string {
  const n = display.length;
  if (n <= 7) return "text-[36px] md:text-[44px] leading-none";
  if (n <= 10) return "text-[28px] md:text-[32px]";
  if (n <= 16) return "text-[22px] md:text-[26px]";
  return "text-[18px] md:text-[20px]";
}

function DeltaPill({ delta, goodDirection, label }: { delta: NonNullable<ReturnType<typeof seriesDelta>>; goodDirection?: "up" | "down"; label?: string }) {
  label ??= delta.fullWeeks ? "last full week vs prior" : "vs prev week";
  const good = delta.dir === "flat" || !goodDirection ? null : delta.dir === goodDirection;
  const arrow = delta.dir === "up" ? "\u2191" : delta.dir === "down" ? "\u2193" : "\u2192";
  const amount = delta.pct === null
    ? Math.abs(delta.abs).toLocaleString("en-US")
    : `${Math.abs(delta.pct).toFixed(delta.pct !== 0 && Math.abs(delta.pct) < 10 ? 1 : 0)}%`;
  return (
    <div
      data-testid="kpi-delta"
      data-dir={delta.dir}
      className={cn(
        "mt-4 inline-flex w-fit items-center gap-1.5 rounded-full px-3 py-1 text-[12px] font-medium tabular-nums",
        good === null && "bg-[var(--sd-ink)]/[0.05] text-[var(--sd-quiet)]",
        good === true && "bg-[color-mix(in_srgb,var(--crop-accent,var(--sd-data-green))_12%,transparent)] text-[var(--crop-accent,var(--sd-data-green))]",
        good === false && "bg-[var(--sd-data-red)]/10 text-[var(--sd-data-red)]",
      )}
    >
      {arrow} {delta.dir === "flat" ? "0%" : amount}
      <small className="font-medium opacity-65">{label}</small>
    </div>
  );
}

export function KpiGrid({
  children,
  cols = 4,
  className,
}: {
  children: React.ReactNode;
  cols?: 2 | 3 | 4 | 5;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "grid gap-4",
        cols === 4 && "grid-cols-2 lg:grid-cols-4",
        // Five across only where the cards stay readable; 3 + 2 below that.
        cols === 5 && "grid-cols-2 md:grid-cols-3 xl:grid-cols-5",
        cols === 3 && "grid-cols-1 sm:grid-cols-3",
        cols === 2 && "grid-cols-1 sm:grid-cols-2",
        className,
      )}
    >
      {children}
    </div>
  );
}

/** Alias kept so code written against SCP's `Kpi` reads the same. */
export const Kpi = KpiCard;
export type KpiProps = KpiCardProps;
