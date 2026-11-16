import { cn } from "@/lib/utils";

export interface PillTab {
  key: string;
  label: string;
  count?: number;
  /** Count shown red when above zero (things waiting for someone). */
  alert?: boolean;
}

/** The status tabs every list page uses: pills with a count. */
export function PillTabs({ tabs, value, onChange, label }: { tabs: PillTab[]; value: string; onChange: (key: string) => void; label: string }) {
  return (
    <div role="tablist" aria-label={label} className="flex flex-wrap gap-1.5">
      {tabs.map((t) => {
        const active = t.key === value;
        return (
          <button
            key={t.key || "all"} role="tab" aria-selected={active} onClick={() => onChange(t.key)}
            className={cn(
              "flex h-9 items-center gap-2 rounded-full px-3.5 text-[13px] font-medium transition-colors",
              active ? "bg-[var(--sd-ink)] text-white" : "bg-[var(--sd-card)] text-[var(--sd-muted)] shadow-[var(--sd-shadow-1)] hover:text-[var(--sd-ink)]",
            )}
          >
            {t.label}
            {t.count != null && (
              <span className={cn("min-w-5 rounded-full px-1.5 text-center text-[11px] font-semibold tabular-nums",
                active ? "bg-white/20" : t.alert && t.count > 0 ? "bg-[var(--sd-data-red)] text-white" : "bg-[var(--sd-line-soft)]")}>
                {t.count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

/** Debounced text for search boxes (300 ms). */
export { useDebounced } from "@/lib/use-debounced";
