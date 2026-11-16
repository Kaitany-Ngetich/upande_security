import { DOCK_LINE, dockFade } from "@/lib/use-dock-progress";
import { cn } from "@/lib/utils";

/**
 * The page's name, after it has finished travelling out of the page.
 *
 * Driven by the same progress value that fades the heading, so the two are one
 * movement rather than two: the pill starts small and a little high, at the
 * size and place the heading is leaving from, and settles into the dock as the
 * heading goes. Nothing appears while something else is still there.
 *
 * The scale runs from 0.86 to 1 rather than from the heading's real ratio. A
 * 40px title shrinking to 14px is a 3× collapse, and at that ratio the text
 * spends most of the movement illegibly small and arrives with a snap; the
 * shorter range reads as the same gesture and stays readable throughout.
 *
 * The TRANSFORM runs across the whole handover and the OPACITY only across its
 * second half. Motion is what makes it read as one title travelling; a shared
 * fade is what made it read as two.
 */
export function PageDock({
  eyebrow,
  title,
  progress,
  children,
}: {
  eyebrow: string;
  title: string;
  /** 0 while the heading holds the title, 1 once the dock does. */
  progress: number;
  /** Controls to carry along — a refresh, a filter the page still needs. */
  children?: React.ReactNode;
}) {
  // The eyebrow reads "Upande Livestock · Animals", and beside a title that
  // already says "Animals" the pill came out "Animals  UPANDE LIVESTOCK ·
  // ANIMALS" — the page name three times in one pill. Only the part that adds
  // something is kept: the section, and only when it is not the title again.
  const section = (() => {
    const tail = eyebrow.split("·").pop()?.trim() ?? "";
    if (!tail || tail.toLowerCase() === title.toLowerCase()) return "";
    return tail;
  })();

  const opacity = dockFade(progress);
  const shown = opacity > 0.02;

  return (
    <div
      aria-hidden={!shown}
      className="pointer-events-none fixed inset-x-0 z-40 flex justify-center px-4"
      style={{ top: DOCK_LINE - 34 }}
    >
      <div
        className={cn(
          "flex max-w-full items-center gap-3 rounded-[var(--sd-radius-pill)]",
          "border border-[var(--sd-line-soft)] bg-[color-mix(in_srgb,var(--sd-card)_78%,transparent)]",
          "px-4 py-2 shadow-[var(--sd-shadow-3)] backdrop-blur-xl",
          shown ? "pointer-events-auto" : "pointer-events-none",
          // No CSS transition: the movement IS the scroll, and a duration on
          // top of it would make the pill lag the finger that is dragging it.
          //
          // No motion-reduce class either — it would be decoration. The
          // transform is set inline, and an inline style beats any class, so
          // motion-reduce:transform-none could never have fired. Nothing here
          // moves on its own: the 14px lift and 14% scale happen only while the
          // reader is already scrolling, which is the motion they asked for.
          "will-change-[transform,opacity]",
        )}
        style={{
          opacity,
          transform: `translateY(${(1 - progress) * -14}px) scale(${0.86 + progress * 0.14})`,
          transformOrigin: "top center",
        }}
      >
        <span className="h-px w-3.5 shrink-0 bg-[var(--sd-text)]" aria-hidden />
        <span className="flex min-w-0 items-baseline gap-2">
          <span className="truncate text-[14px] font-semibold tracking-[-0.01em] text-[var(--sd-ink)]">
            {title}
          </span>
          {section && (
            <span className="hidden truncate text-[11px] uppercase tracking-[0.14em] text-[var(--sd-quiet)] sm:inline">
              {section}
            </span>
          )}
        </span>
        {children && <span className="flex shrink-0 items-center gap-2">{children}</span>}
      </div>
    </div>
  );
}
