import * as React from "react";
import { cn } from "@/lib/utils";

/** One toolbar control, optionally scoped to the tabs it applies to. */
export type ToolbarFilter = {
  key: string;
  /** the tab ids this control applies to; omit for "every tab" */
  tabs?: string[];
  node: React.ReactNode;
};

/**
 * The one controls row every SCP page uses: tabs / segmented control on the
 * LEFT, then ALL of the page's filters and action buttons (refresh, New ...)
 * on the RIGHT, on the same row. It wraps only when it must (a phone).
 *
 * `filters` may be tagged with the `tabs` they apply to. With `tab` set, a
 * filter that does not apply to the active tab is hidden (faded and collapsed,
 * not unmounted, so its state survives a tab switch); `motion-reduce` turns
 * the transition off. Untagged filters and plain `children` always show.
 */
export function PageToolbar({
  left,
  children,
  filters,
  tab,
  className,
}: {
  /** tabs / segmented control */
  left?: React.ReactNode;
  /** filters, toggles, Clear and icon tools shown on every tab */
  children?: React.ReactNode;
  /** tab-scoped filters, rendered before `children` */
  filters?: ToolbarFilter[];
  /** the active tab id, matched against each filter's `tabs` */
  tab?: string;
  className?: string;
}) {
  const scoped = (filters ?? []).filter((f) => f.node);
  if (!left && !children && !scoped.length) return null;
  return (
    <div
      data-testid="page-toolbar"
      className={cn("flex flex-wrap items-center gap-x-3 gap-y-2", className)}
    >
      {left ? (
        <div data-slot="left" className="flex min-w-0 max-w-full flex-wrap items-center gap-2">
          {left}
        </div>
      ) : null}
      {children || scoped.length ? (
        <div data-slot="right" className="ml-auto flex min-w-0 flex-wrap items-center justify-end">
          {scoped.map((f) => {
            const shown = !f.tabs || tab === undefined || f.tabs.includes(tab);
            return (
              <div
                key={f.key}
                data-filter={f.key}
                data-state={shown ? "shown" : "hidden"}
                aria-hidden={shown ? undefined : true}
                inert={shown ? undefined : true}
                className={cn(
                  "flex items-center transition-all duration-200 ease-out motion-reduce:transition-none",
                  shown
                    ? "visible max-w-[48rem] pl-2 opacity-100"
                    : "invisible max-w-0 overflow-hidden pl-0 opacity-0",
                )}
              >
                {f.node}
              </div>
            );
          })}
          {children ? (
            <div className="flex min-w-0 flex-wrap items-center justify-end gap-2 pl-2">{children}</div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
