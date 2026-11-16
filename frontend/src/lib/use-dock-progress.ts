import { useEffect, useRef, useState } from "react";

/** Where the docked pill comes to rest, measured from the top of the viewport. */
export const DOCK_LINE = 56;
/** How much scrolling the handoff takes. Short enough to feel like one
 *  movement rather than a long dissolve. */
export const RAMP = 72;

/**
 * The two halves of the handover, staggered.
 *
 * A straight crossfade puts both copies at half opacity in the middle, which
 * is exactly the "they are both there" the dock was meant to stop — the eye
 * does not read two faint titles as one moving title, it reads them as two.
 * So the heading is gone by 55% and the pill does not start until 45%: they
 * cross within a tenth of the movement, both below a fifth of opacity, and
 * what carries the eye across the gap is the transform, which runs the whole
 * way without interruption.
 */
export function headingFade(p: number): number {
  return 1 - Math.min(1, p / 0.55);
}

export function dockFade(p: number): number {
  return Math.max(0, Math.min(1, (p - 0.45) / 0.55));
}

/**
 * How far a heading is through handing itself over to the dock: 0 while it is
 * sitting in the page, 1 once the dock has it.
 *
 * A NUMBER, NOT A BOOLEAN, and that is the whole point. A boolean can only
 * make one thing appear as another disappears, which is two events that happen
 * to be adjacent; the eye reads it as a flicker and, in the window where both
 * are drawn, as a duplicate. One progress value drives the heading out and the
 * pill in together, so what the eye sees is a single piece of text moving.
 *
 * Read off getBoundingClientRect rather than scrollY: the heading is not
 * always at the top of the document — a notice or an error banner above it
 * shifts everything down — and its own position on screen is the thing that
 * actually decides when it has gone.
 *
 * Sampled on a frame, not on the scroll event. Scroll fires far faster than
 * the screen repaints, and the answer is only ever used to paint.
 *
 * LISTENED FOR IN THE CAPTURE PHASE, ON THE DOCUMENT. The served page puts
 * `overflow: hidden` on the body and makes #security-root the scroller, so
 * the window never scrolls and a listener on it never fires — which is exactly
 * how this shipped doing nothing at all. Scroll events do not bubble, but they
 * do capture, so one listener on the document catches the scroll whatever
 * element is doing it and this cannot break again if the shell changes.
 */
export function useDockProgress(ref: React.RefObject<HTMLElement | null>): number {
  const [progress, setProgress] = useState(0);
  const frame = useRef<number | undefined>(undefined);
  const last = useRef(0);
  // Nothing has been handed over until the reader has actually scrolled: a
  // short heading (no description yet, say) already sits above the dock line.
  const scrolled = useRef(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    const measure = () => {
      frame.current = undefined;
      const bottom = el.getBoundingClientRect().bottom;
      const raw = (DOCK_LINE + RAMP - bottom) / RAMP;
      const next = scrolled.current ? Math.max(0, Math.min(1, raw)) : 0;
      // Only re-render when it would show. Sub-pixel churn on a fast scroll is
      // a render per frame for a transform nobody can see move.
      if (Math.abs(next - last.current) > 0.004 || next === 0 || next === 1) {
        last.current = next;
        setProgress(next);
      }
    };

    const schedule = (e?: Event) => {
      if (e && e.type === "scroll") {
        const t = e.target;
        const top = t instanceof Element ? t.scrollTop : window.scrollY;
        scrolled.current = top > 0;
      }
      if (frame.current === undefined) frame.current = window.requestAnimationFrame(measure);
    };

    measure();
    document.addEventListener("scroll", schedule, { capture: true, passive: true });
    window.addEventListener("resize", schedule);
    return () => {
      document.removeEventListener("scroll", schedule, { capture: true });
      window.removeEventListener("resize", schedule);
      if (frame.current !== undefined) window.cancelAnimationFrame(frame.current);
    };
  }, [ref]);

  return progress;
}
