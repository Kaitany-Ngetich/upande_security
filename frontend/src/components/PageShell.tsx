import { PageHeader } from "@/components/PageHeader";
import type { ToolbarFilter } from "@/components/PageToolbar";

/**
 * The frame every surface sits in.
 *
 * `flex-1` with padding and no max width: the workspace is whatever the
 * window leaves after the sidebar, and it reflows when the sidebar collapses
 * to its icon rail. A centred `max-w` column here would pin the content to
 * one width and leave a gutter on a wide screen — which is exactly what the
 * first slice did, and what this replaces.
 *
 * `min-w-0` matters as much as `flex-1`: without it a wide table inside a
 * flex child refuses to shrink and pushes the whole page into a horizontal
 * scroll. Wide content scrolls inside its own box instead.
 */
export function Page({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-w-0 flex-1 flex-col gap-6 px-4 py-4 md:px-6 md:py-6">
      {children}
    </div>
  );
}

/**
 * Page + SCP header in one: what every production view renders.
 *
 * The header is SCP's `PageHeader` (eyebrow with a thin rule, big title, then
 * ONE toolbar row under it). `eyebrow` defaults to the product name; views
 * pass the crop's name instead.
 *
 * Toolbar slots, all optional:
 * - `tabs`     left side of the row (a pill TabsList / segmented control)
 * - `filters`  tab-scoped filters (`{ key, tabs?, node }`, see PageToolbar);
 *              pair with `tab` (the active tab id)
 * - `actions`  right side of the row: FilterSelect / DateRangePicker pills,
 *              refresh, ClearFiltersPill, ToolbarButton ... (legacy name kept)
 * - `description` a quiet sentence under the toolbar
 *
 * The body is padded to line up with the header; give it cards, not padding.
 */
export function PageShell({
  title,
  eyebrow = "Upande Security",
  actions,
  tabs,
  filters,
  tab,
  description,
  children,
}: {
  title: React.ReactNode;
  eyebrow?: React.ReactNode;
  actions?: React.ReactNode;
  tabs?: React.ReactNode;
  filters?: ToolbarFilter[];
  tab?: string;
  description?: React.ReactNode;
  children?: React.ReactNode;
}) {
  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <PageHeader title={title} eyebrow={eyebrow} switcher={tabs} filters={filters} tab={tab}>
        {actions}
      </PageHeader>
      <div className="flex min-w-0 flex-1 flex-col gap-6 px-4 pt-4 pb-6 md:px-6">
        {description && (
          <p className="max-w-[68ch] text-[13px] leading-relaxed text-[var(--sd-muted)]">
            {description}
          </p>
        )}
        {children}
      </div>
    </div>
  );
}
