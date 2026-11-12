import { HEADER_PILL } from "@/components/header-controls";
import { cn } from "@/lib/utils";

/**
 * "Clear" for a filter row: the same pill shape as every other toolbar
 * control, with text, border and a faint background in red. Always red, not
 * just on hover. Renders nothing unless a filter is active.
 */
export function ClearFiltersPill({
  active,
  onClear,
  label = "Clear",
  className,
}: {
  active: boolean;
  onClear: () => void;
  label?: string;
  className?: string;
}) {
  if (!active) return null;
  return (
    <button
      type="button"
      onClick={onClear}
      className={cn(
        HEADER_PILL,
        "inline-flex min-w-0 cursor-pointer items-center justify-center whitespace-nowrap border border-destructive/40 bg-destructive/10 text-destructive shadow-none transition-colors hover:bg-destructive/15 hover:shadow-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-destructive/40",
        className,
      )}
    >
      {label}
    </button>
  );
}

/** Backwards-compatible alias. */
export const ClearFiltersLink = ClearFiltersPill;
