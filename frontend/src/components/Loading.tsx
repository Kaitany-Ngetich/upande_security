import type * as React from "react";
import { PageHeader } from "@/components/PageHeader";
import { ProgressBar } from "@/components/ProgressBar";
import { TableCell, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";

/**
 * Placeholders shaped like the thing that is coming.
 *
 * A spinner says "wait"; a skeleton says "wait, and here is where it will be".
 * The second is worth building only if the box really is the same box — a
 * placeholder half the height of its content makes the page jump when the data
 * lands, which is worse than the spinner it replaced. So each of these takes
 * the dimension that the real component is built on: `RunOutChart` is 300px tall,
 * by a constant at the top of their file, and the
 * caller passes the same number.
 */

export function ChartSkeleton({ height }: { height: number }) {
  return (
    <div
      className="w-full animate-pulse rounded-[var(--sd-radius-lg)] bg-[var(--sd-bg-soft)]"
      style={{ height }}
      aria-hidden
    />
  );
}

/**
 * Rows of a list or a table, at the height the real rows sit at.
 *
 * The widths vary down the column on purpose. A block of identical bars reads
 * as a loading graphic; bars of different lengths read as text that has not
 * arrived, which is what it is.
 */
export function RowsSkeleton({
  rows = 5,
  className,
}: {
  rows?: number;
  className?: string;
}) {
  const widths = ["82%", "64%", "74%", "58%", "70%", "86%", "62%", "78%"];
  return (
    <div className={cn("flex flex-col gap-1", className)} aria-hidden>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex items-center gap-3 px-3 py-2.5">
          <div
            className="h-[13px] animate-pulse rounded bg-[var(--sd-bg-soft)]"
            style={{ width: widths[i % widths.length] }}
          />
        </div>
      ))}
    </div>
  );
}

/** A single bar at text height, for a line that has not arrived. */
export function TextSkeleton({ width = "12ch" }: { width?: string }) {
  return (
    <span
      className="inline-block h-[13px] animate-pulse rounded bg-[var(--sd-bg-soft)] align-middle"
      style={{ width }}
      aria-hidden
    />
  );
}

/** One shimmering placeholder; size it with classes (e.g. "h-5 w-16"). */
export function Bar({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "block animate-pulse rounded-[var(--sd-radius-sm)] bg-[var(--sd-bg-soft)]",
        className,
      )}
    />
  );
}

/**
 * A whole page, before its code has arrived.
 *
 * The route fallback used to be a sweeping progress bar on an empty surface,
 * which is honest about having no figure to report but says nothing about what
 * is coming — so every first visit to a screen flashed an empty page and then
 * reflowed into a layout. This is the silhouette the SCP pages share: a
 * heading, a row of KPI cards, a wide panel. The arrival is then the same shape
 * filling in rather than a different thing replacing it.
 *
 * Deliberately NOT a spinner. On a farm connection the difference between "wait"
 * and "here is what is coming" is whether the operator thinks the app has hung —
 * and on this app the wait being covered can be a 16-second cold aggregate
 * rebuild, which is a long time to look at something that says nothing.
 *
 * Given a `title`, the heading is the real `PageHeader` (the route fallback
 * passes the page's nav label and section), so only the body is a silhouette.
 */
export function PageSkeleton({
  title,
  eyebrow,
}: {
  /** The page's real title (route fallback: from the nav metadata). Without
   *  it the heading is drawn as bars. */
  title?: React.ReactNode;
  eyebrow?: React.ReactNode;
} = {}) {
  return (
    <div
      className="flex flex-col"
      aria-busy="true"
      aria-label="Loading the page"
    >
      {title ? (
        <PageHeader title={title} eyebrow={eyebrow} />
      ) : (
        <div className="flex flex-col gap-2 px-4 pt-4 md:px-6 md:pt-6" aria-hidden>
          <Bar className="h-3 w-24" />
          <Bar className="h-6 w-56" />
          <Bar className="h-3 w-[min(38rem,80%)]" />
        </div>
      )}

      <div className="flex flex-col gap-5 px-4 py-4 md:px-6 md:py-6" aria-hidden>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <div
              key={i}
              className="flex flex-col gap-2 rounded-[var(--sd-radius-lg)] bg-[var(--sd-card)] px-4 py-3.5 shadow-[var(--sd-shadow-1)]"
            >
              <Bar className="h-2.5 w-20" />
              <Bar className="h-5 w-16" />
              <Bar className="h-2.5 w-24" />
            </div>
          ))}
        </div>

        <div className="flex flex-col gap-3 rounded-[var(--sd-radius-lg)] bg-[var(--sd-card)] px-4 py-4 shadow-[var(--sd-shadow-1)]">
          <Bar className="h-4 w-40" />
          <Bar className="h-2.5 w-[min(30rem,70%)]" />
          <RowsSkeleton rows={4} />
        </div>
      </div>
    </div>
  );
}

/**
 * The silhouette of a full-bleed map page — Scouting Map, Observations, Traps,
 * Jobsheet. Those do not have KPI cards; they have a header strip, a legend
 * line and one large canvas with a docked panel, so `PageSkeleton` would draw
 * the wrong shape and reflow on arrival.
 */
export function MapPageSkeleton({
  title,
  eyebrow,
}: {
  title?: React.ReactNode;
  eyebrow?: React.ReactNode;
} = {}) {
  return (
    <div
      className="flex min-h-svh flex-col"
      aria-busy="true"
      aria-label="Loading the map"
    >
      {title ? (
        <PageHeader title={title} eyebrow={eyebrow} />
      ) : (
        <div className="flex flex-col gap-2 px-4 pt-4 md:px-6 md:pt-6" aria-hidden>
          <Bar className="h-6 w-48" />
          <Bar className="h-3 w-[min(28rem,70%)]" />
        </div>
      )}
      <div
        className="grid min-h-0 flex-1 grid-cols-1 gap-4 px-4 py-3 md:px-6 md:pb-6 lg:grid-cols-[1fr_240px]"
        aria-hidden
      >
        <div className="min-h-[24rem] animate-pulse rounded-[20px] bg-[var(--sd-bg-soft)]" />
        <div className="hidden min-h-[24rem] flex-col gap-3 rounded-[20px] bg-[var(--sd-card)] p-3 shadow-[var(--sd-shadow-1)] lg:flex">
          <Bar className="h-3 w-20" />
          <RowsSkeleton rows={6} />
        </div>
      </div>
    </div>
  );
}

/* ─────────────── In-place skeletons (the page frame stays real) ───────────────
 *
 * The rule (skeleton spec, 2026-10-11): a page draws its real frame from the
 * first paint — header, tabs, filters, card and section titles, table headings,
 * labels, legends, buttons — and only the parts that hold DATA are skeletons,
 * each at the size the data will take. Nothing covers the page while it loads.
 */

/** `loading && !hasData`: the first load shows skeletons; a refresh keeps the
 *  old data on screen (with `LoadProgress`) instead of blanking it. */
export function firstLoad(loading: boolean, hasData: boolean): boolean {
  return loading && !hasData;
}

/** A KPI figure that has not arrived, at the figure's own height. */
export function KpiValueSkeleton({ className }: { className?: string }) {
  return <Bar className={cn("h-7 w-16", className)} />;
}

/** A round placeholder for an Employee photo. */
export function AvatarSkeleton({ size = 32 }: { size?: number }) {
  return (
    <span
      aria-hidden
      className="inline-block shrink-0 animate-pulse rounded-full bg-[var(--sd-bg-soft)]"
      style={{ width: size, height: size }}
    />
  );
}

/**
 * Body rows for a real table: render the real `<TableHeader>` and put this in
 * `<TableBody>`. One cell per column, widths varying down the column.
 */
export function TableRowsSkeleton({
  cols,
  rows = 6,
  avatar = false,
}: {
  cols: number;
  rows?: number;
  /** first column starts with a round photo placeholder */
  avatar?: boolean;
}) {
  const widths = ["78%", "56%", "68%", "44%", "62%", "72%", "50%"];
  return (
    <>
      {Array.from({ length: rows }, (_, r) => (
        <TableRow key={r} aria-hidden data-skeleton="row">
          {Array.from({ length: cols }, (_, c) => (
            <TableCell key={c}>
              <span className="flex items-center gap-2">
                {avatar && c === 0 && <AvatarSkeleton size={28} />}
                <span
                  className="block h-[13px] animate-pulse rounded bg-[var(--sd-bg-soft)]"
                  style={{ width: widths[(r + c) % widths.length] }}
                />
              </span>
            </TableCell>
          ))}
        </TableRow>
      ))}
    </>
  );
}

/**
 * A slow load's real progress, inline under the page header — it replaces the
 * full-screen `LoadingOverlay`, so the frame and any old data stay visible.
 * Renders nothing when not loading.
 */
export function LoadProgress({
  active,
  progress,
  label,
  className,
}: {
  active: boolean;
  /** 0–100, or null/undefined for indeterminate */
  progress?: number | null;
  label?: string;
  className?: string;
}) {
  if (!active) return null;
  return (
    <div role="status" aria-live="polite" className={cn("w-[min(22rem,100%)]", className)}>
      <ProgressBar percent={progress ?? null} label={label} />
    </div>
  );
}
