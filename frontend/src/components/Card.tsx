import { cn } from "@/lib/utils";

/** The app's card surface with an optional heading row. */
export function Card({ title, actions, children, className }: {
  title?: React.ReactNode; actions?: React.ReactNode; children: React.ReactNode; className?: string;
}) {
  return (
    <section className={cn("rounded-[var(--sd-radius-lg)] bg-[var(--sd-card)] shadow-[var(--sd-shadow-1)]", className)}>
      {(title || actions) && (
        <div className="flex flex-wrap items-center justify-between gap-2 px-4 pt-4">
          {title && <h2 className="text-[15px] font-semibold text-[var(--sd-ink)]">{title}</h2>}
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

/** A small coloured verdict ("Verified", "Rejected", "Not authorised"). */
export function Verdict({ ok, children }: { ok: boolean | null; children: React.ReactNode }) {
  return (
    <span
      className={cn(
        "inline-flex rounded-full px-2 py-0.5 text-[11px] font-semibold",
        ok === null ? "bg-[var(--sd-line-soft)] text-[var(--sd-muted)]"
          : ok ? "bg-[var(--sd-alert-ok)] text-[var(--sd-data-green,#3f7d3a)]"
          : "bg-[var(--sd-alert-error)] text-[var(--sd-data-red)]",
      )}
    >
      {children}
    </span>
  );
}

export const TH = "px-4 py-3 text-left text-[11px] font-medium uppercase tracking-[0.08em] text-[var(--sd-quiet)]";
export const TD = "px-4 py-3 align-top";
