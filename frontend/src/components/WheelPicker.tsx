import { useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { cn } from "@/lib/utils";

/** Height (px) of a single wheel row. Fixed px — not rem — so the roll
 *  translate stays exact regardless of the app's 85% root font-size. */
export const WHEEL_CELL = 34;

export interface WheelOption {
  value: string;
  label?: string;
  disabled?: boolean;
}

export interface WheelColumnProps {
  options: (string | WheelOption)[];
  value: string;
  /** Interactive when given: drag / wheel / arrow keys / tap-to-centre. Without it the
   *  column is a display-only odometer (the TimePicker, driven by its chevrons). */
  onChange?: (value: string) => void;
  /** accessible name of the listbox (interactive mode) */
  label?: string;
  /** visible rows, odd; default 3 */
  rows?: number;
  className?: string;
}

const norm = (o: string | WheelOption): WheelOption => (typeof o === "string" ? { value: o } : o);

const prefersReducedMotion = (): boolean =>
  typeof window !== "undefined" &&
  typeof window.matchMedia === "function" &&
  window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/**
 * Odometer / drum column. Renders every option stacked and slides the strip so
 * the selected one sits centred in a `rows`-row window with faded neighbours.
 * Single-step changes animate; a long jump snaps instead of sliding the long
 * way. Interactive columns also take drag with momentum, mouse wheel, arrow /
 * Home / End / Page keys, and tap-a-row-to-centre; disabled options are greyed
 * and skipped. Respects `prefers-reduced-motion`.
 */
export function WheelColumn({ options, value, onChange, label, rows = 3, className }: WheelColumnProps) {
  const opts = options.map(norm);
  const found = opts.findIndex((o) => o.value === value);
  const index = Math.max(0, found);
  const center = (rows - 1) / 2;
  const interactive = !!onChange;

  const prevIndex = useRef(index);
  const isWrap = Math.abs(index - prevIndex.current) > 1;
  useEffect(() => {
    prevIndex.current = index;
  }, [index]);

  const optsRef = useRef(opts);
  optsRef.current = opts;
  const indexRef = useRef(index);
  indexRef.current = index;
  const changeRef = useRef(onChange);
  changeRef.current = onChange;

  /** nearest enabled index to `target`, preferring the direction of travel */
  const settle = (target: number, dir: 1 | -1 | 0): number => {
    const list = optsRef.current;
    const t = Math.max(0, Math.min(list.length - 1, target));
    if (!list[t]?.disabled) return t;
    for (let d = 1; d < list.length; d++) {
      const order = dir >= 0 ? [t + d, t - d] : [t - d, t + d];
      for (const i of order) if (i >= 0 && i < list.length && !list[i].disabled) return i;
    }
    return indexRef.current;
  };
  const goTo = (target: number, dir: 1 | -1 | 0) => {
    const i = settle(target, dir);
    if (i !== indexRef.current) changeRef.current?.(optsRef.current[i].value);
  };
  /** step n enabled options in a direction */
  const stepBy = (dir: 1 | -1) => {
    const list = optsRef.current;
    for (let i = indexRef.current + dir; i >= 0 && i < list.length; i += dir) {
      if (!list[i].disabled) return changeRef.current?.(list[i].value);
    }
  };

  const [dragY, setDragY] = useState<number | null>(null);
  const drag = useRef<{ startY: number; samples: { t: number; y: number }[]; moved: boolean; id: number } | null>(
    null,
  );
  const suppressClick = useRef(false);
  const rootRef = useRef<HTMLDivElement>(null);

  // wheel: one step per notch (accumulated so trackpads do not fly through the list)
  useEffect(() => {
    const el = rootRef.current;
    if (!el || !interactive) return;
    let acc = 0;
    const onWheel = (e: WheelEvent) => {
      if (!e.deltaY) return;
      e.preventDefault();
      acc += e.deltaY;
      while (Math.abs(acc) >= 40) {
        const dir = acc > 0 ? 1 : -1;
        acc -= dir * 40;
        stepBy(dir);
      }
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [interactive]);

  const onPointerDown = (e: React.PointerEvent) => {
    if (!interactive || e.button !== 0) return;
    drag.current = { startY: e.clientY, samples: [{ t: e.timeStamp, y: e.clientY }], moved: false, id: e.pointerId };
  };
  const onPointerMove = (e: React.PointerEvent) => {
    const d = drag.current;
    if (!d) return;
    const dy = e.clientY - d.startY;
    if (!d.moved) {
      if (Math.abs(dy) < 4) return;
      d.moved = true;
      try {
        (e.currentTarget as HTMLElement).setPointerCapture?.(d.id);
      } catch {
        /* synthetic pointer */
      }
    }
    d.samples.push({ t: e.timeStamp, y: e.clientY });
    if (d.samples.length > 6) d.samples.shift();
    // rubber-band past the ends
    const max = indexRef.current * WHEEL_CELL;
    const min = -(optsRef.current.length - 1 - indexRef.current) * WHEEL_CELL;
    setDragY(dy > max ? max + (dy - max) * 0.3 : dy < min ? min + (dy - min) * 0.3 : dy);
  };
  const endDrag = (e: React.PointerEvent, cancelled: boolean) => {
    const d = drag.current;
    drag.current = null;
    if (!d || !d.moved) return;
    suppressClick.current = true;
    setTimeout(() => (suppressClick.current = false), 0);
    try {
      (e.currentTarget as HTMLElement).releasePointerCapture?.(d.id);
    } catch {
      /* not captured */
    }
    const dy = e.clientY - d.startY;
    const first = d.samples[0];
    const dt = Math.max(1, e.timeStamp - first.t);
    const v = cancelled || prefersReducedMotion() ? 0 : (e.clientY - first.y) / dt; // px / ms
    const projected = dy + v * 220; // momentum carries ~220 ms further
    const delta = -Math.round(projected / WHEEL_CELL);
    setDragY(null);
    goTo(indexRef.current + delta, delta > 0 ? 1 : delta < 0 ? -1 : 0);
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    const k = e.key;
    if (k === "ArrowUp") stepBy(-1);
    else if (k === "ArrowDown") stepBy(1);
    else if (k === "PageUp") goTo(indexRef.current - 5, -1);
    else if (k === "PageDown") goTo(indexRef.current + 5, 1);
    else if (k === "Home") goTo(0, 1);
    else if (k === "End") goTo(opts.length - 1, -1);
    else return;
    e.preventDefault();
  };

  const dragging = dragY !== null;
  return (
    <div
      ref={rootRef}
      className={cn(
        "relative w-11 overflow-hidden",
        interactive &&
          "cursor-grab touch-none select-none rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30 active:cursor-grabbing",
        className,
      )}
      style={{
        height: WHEEL_CELL * rows,
        // Fade the top/bottom edges regardless of surface colour.
        maskImage: "linear-gradient(to bottom, transparent, #000 28%, #000 72%, transparent)",
        WebkitMaskImage: "linear-gradient(to bottom, transparent, #000 28%, #000 72%, transparent)",
      }}
      {...(interactive
        ? {
            role: "listbox",
            tabIndex: 0,
            "aria-label": label,
            "aria-orientation": "vertical" as const,
            onKeyDown,
            onPointerDown,
            onPointerMove,
            onPointerUp: (e: React.PointerEvent) => endDrag(e, false),
            onPointerCancel: (e: React.PointerEvent) => endDrag(e, true),
          }
        : {})}
    >
      <div
        className={cn(
          "flex flex-col will-change-transform",
          !isWrap && !dragging && "transition-transform duration-200 motion-reduce:transition-none",
        )}
        style={{
          transform: `translateY(${(center - index) * WHEEL_CELL + (dragY ?? 0)}px)`,
          transitionTimingFunction: "cubic-bezier(.22,.61,.36,1)",
        }}
      >
        {opts.map((o, i) => (
          <div
            key={o.value}
            {...(interactive
              ? {
                  role: "option",
                  "aria-selected": i === index,
                  "aria-disabled": o.disabled || undefined,
                  "aria-label": o.label ?? o.value,
                  onClick: () => {
                    if (suppressClick.current || o.disabled) return;
                    goTo(i, i > indexRef.current ? 1 : -1);
                  },
                }
              : {})}
            className={cn(
              "flex items-center justify-center text-base tabular-nums",
              i === index ? "font-semibold text-foreground" : "text-muted-foreground opacity-40",
              o.disabled && "cursor-not-allowed opacity-15",
            )}
            style={{ height: WHEEL_CELL }}
          >
            {o.label ?? o.value}
          </div>
        ))}
      </div>
    </div>
  );
}

const CHEV =
  "flex size-7 items-center justify-center rounded-md text-[var(--sd-quiet)] transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-[var(--sd-quiet)]";

export interface WheelStepperProps {
  /** names the Increase / Decrease buttons (and the listbox when interactive) */
  name: string;
  options: (string | WheelOption)[];
  value: string;
  /** TimePicker style: the parent computes the step (carry etc.) */
  onStep?: (dir: 1 | -1) => void;
  /** wheel style: the column is interactive and the chevrons move to the next enabled option */
  onChange?: (value: string) => void;
  rows?: number;
  className?: string;
}

/** A WheelColumn between up / down chevron buttons; the TimePicker and the DateRangePicker counter share it. */
export function WheelStepper({ name, options, value, onStep, onChange, rows, className }: WheelStepperProps) {
  const opts = options.map(norm);
  const at = Math.max(0, opts.findIndex((o) => o.value === value));
  const neighbour = (dir: 1 | -1): WheelOption | undefined => {
    for (let i = at + dir; i >= 0 && i < opts.length; i += dir) if (!opts[i].disabled) return opts[i];
    return undefined;
  };
  const inc = onChange ? neighbour(1) : undefined;
  const dec = onChange ? neighbour(-1) : undefined;
  const press = (dir: 1 | -1) => (onChange ? onChange((dir === 1 ? inc : dec)!.value) : onStep?.(dir));
  return (
    <div className="flex flex-col items-center gap-1">
      <button
        type="button"
        className={CHEV}
        aria-label={`Increase ${name}`}
        disabled={!!onChange && !inc}
        onClick={() => press(1)}
      >
        <ChevronUp className="h-4 w-4" />
      </button>
      <WheelColumn options={options} value={value} onChange={onChange} label={name} rows={rows} className={className} />
      <button
        type="button"
        className={CHEV}
        aria-label={`Decrease ${name}`}
        disabled={!!onChange && !dec}
        onClick={() => press(-1)}
      >
        <ChevronDown className="h-4 w-4" />
      </button>
    </div>
  );
}
