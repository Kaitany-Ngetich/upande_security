import * as React from "react";
import { PageToolbar, type ToolbarFilter } from "@/components/PageToolbar";

/** The standard header metrics, measured from the Scouting Dashboard. */
export const PAGE_HEADER_CLASS =
  "flex flex-col gap-6 bg-transparent px-4 pt-5 pb-2 md:gap-9 md:px-6 md:pt-6 md:pb-3";
export const PAGE_EYEBROW_CLASS =
  "mb-2.5 flex items-center gap-2.5 text-[11px] font-medium uppercase tracking-[0.2em] text-[var(--sd-quiet)]";
export const PAGE_TITLE_CLASS =
  "text-[32px] font-semibold leading-[1.05] tracking-[-0.03em] text-foreground md:text-[44px]";

/**
 * Shared page header, styled to the reference `.pagehead`: an uppercase
 * eyebrow with a leading rule over a large editorial title, sitting as plain
 * text on the same paper background as the content (no header bar, not
 * sticky). Optional ``children`` render as a right-aligned tools cluster on
 * the same baseline as the title.
 */
export function PageHeader({
  title,
  eyebrow,
  switcher,
  filters,
  tab,
  children,
}: {
  title: React.ReactNode;
  eyebrow?: React.ReactNode;
  /** A pill switcher (e.g. TabsList) rendered on the LEFT of the controls
   *  row, on the same line as the right-aligned dropdowns. */
  switcher?: React.ReactNode;
  /** tab-scoped filters (see PageToolbar) and the active tab id */
  filters?: ToolbarFilter[];
  tab?: string;
  children?: React.ReactNode;
}) {
  return (
    <header className={PAGE_HEADER_CLASS}>
      {/* Title (the sidebar collapse toggle now lives in the sidebar). */}
      <div className="min-w-0">
        {eyebrow ? (
          <div className={PAGE_EYEBROW_CLASS}>
            <span className="h-px w-[18px] shrink-0 bg-[var(--sd-text)]" />
            <span className="truncate">{eyebrow}</span>
          </div>
        ) : null}
        <h1 className={PAGE_TITLE_CLASS}>
          {title}
        </h1>
      </div>
      {/* Controls row — BELOW the heading: tabs left, filters right. */}
      <PageToolbar left={switcher} filters={filters} tab={tab}>{children}</PageToolbar>
    </header>
  );
}
