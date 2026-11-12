import { Check } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * A checkbox drawn as a circle.
 *
 * The app's selected states are round — the animal search avatars, the stage
 * dots, the pills — so a square tick box reads as something borrowed from
 * another page. This is the same control with the same keyboard behaviour
 * (a real `<input type="checkbox">`, visually hidden, so space toggles it and
 * a screen reader calls it a checkbox); only the mark is round.
 *
 * The input is hidden rather than styled away with `appearance: none` because
 * a hidden input keeps its own focus ring target: the ring is drawn on the
 * circle through `peer-focus-visible`, which is the only way it lands in the
 * right place at every zoom level.
 */
export function CheckCircle({
  checked,
  onCheckedChange,
  label,
  className,
}: {
  checked: boolean;
  onCheckedChange: (next: boolean) => void;
  /** What this ticks, for anybody not looking at the row. */
  label: string;
  className?: string;
}) {
  return (
    <label className={cn("relative inline-flex shrink-0 cursor-pointer items-center", className)}>
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onCheckedChange(e.target.checked)}
        aria-label={label}
        className="peer sr-only"
      />
      <span
        aria-hidden
        className={cn(
          "flex h-[18px] w-[18px] items-center justify-center rounded-full border transition-all",
          "peer-focus-visible:ring-2 peer-focus-visible:ring-[var(--sd-data-cyan)] peer-focus-visible:ring-offset-2",
          checked
            ? "border-transparent bg-[var(--sd-ink)] text-[var(--sd-card)]"
            : "border-[var(--sd-line)] bg-[var(--sd-card)] text-transparent",
        )}
      >
        <Check className="h-3 w-3" strokeWidth={3} />
      </span>
    </label>
  );
}
