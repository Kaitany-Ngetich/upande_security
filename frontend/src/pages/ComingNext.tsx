import { PageShell } from "@/components/PageShell";
import { navItem } from "@/lib/nav";
import type { View } from "@/lib/router";

/** A gate operation that is in the sidebar but not built yet. */
export function ComingNext({ view }: { view: View }) {
  const item = navItem(view);
  return (
    <PageShell title={item?.label ?? view} eyebrow="Gate operations">
      <div className="flex max-w-xl flex-col gap-2 rounded-[var(--sd-radius-lg)] bg-[var(--sd-card)] px-5 py-5 shadow-[var(--sd-shadow-1)]">
        <h2 className="text-[16px] font-semibold text-[var(--sd-ink)]">Coming next</h2>
        <p className="text-[13px] leading-relaxed text-[var(--sd-muted)]">
          This gate operation is being moved into Dashboard v2. Until then, use the{" "}
          <a className="underline" href="/security-dashboard">current Security Dashboard</a> or the gate app.
        </p>
      </div>
    </PageShell>
  );
}
