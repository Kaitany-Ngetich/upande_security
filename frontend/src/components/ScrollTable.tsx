import { cn } from "@/lib/utils";

/**
 * A table that scrolls inside itself, in both directions, with its header kept.
 *
 * THE SAME BUG FOUR TIMES. A table whose rows grow with the herd or with the
 * farm's history — every event ever recorded, every animal
 * picked for a weighing — was written as `overflow-x-auto` and nothing else, so
 * it grew to whatever length the data happened to be and the page scrolled for
 * a minute to get past it. Everything underneath, including the buttons that do
 * the work, went below the fold.
 *
 * So the cap lives in one component rather than in a class list copied from
 * screen to screen and forgotten on the fifth. `max-h` and `overflow-y-auto`
 * together are what make it real: a height with nothing to clip it is not a cap.
 *
 * THE HEADER STAYS. A scrolled table with its column names gone is a grid of
 * numbers nobody can read, and the header is the one row that must never be the
 * thing that scrolls away.
 *
 * `tall` is for a screen where the table IS the page (a register, a day's
 * events) rather than one panel among several.
 */
export function ScrollTable({
  children,
  tall,
  className,
}: {
  children: React.ReactNode;
  tall?: boolean;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "overflow-auto",
        tall ? "max-h-[min(68vh,620px)]" : "max-h-[min(52vh,440px)]",
        className,
      )}
    >
      {children}
    </div>
  );
}

/** The header row of a ScrollTable: stays put while the body moves under it. */
export const STICKY_HEAD =
  "sticky top-0 z-10 bg-[var(--sd-card)] shadow-[0_1px_0_0_var(--sd-line)]";
