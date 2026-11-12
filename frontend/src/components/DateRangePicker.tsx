import { useEffect, useMemo, useRef, useState } from "react";
import { Calendar as CalendarIcon, ChevronLeft, ChevronRight } from "lucide-react";
import type { DateRange as DayRange } from "react-day-picker";
import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { WheelStepper, type WheelOption } from "@/components/WheelPicker";
import { cn, parseYmd as parseYmdMaybe, ymd } from "@/lib/utils";

/** parseYmd that always returns a Date (callers pass validated YYYY-MM-DD). */
const parseYmd = (s: string): Date => parseYmdMaybe(s) ?? new Date(NaN);

export interface DateRange {
  from: string; // YYYY-MM-DD
  to: string; // YYYY-MM-DD
}

export interface DateRangePreset {
  label: string;
  range: () => DateRange;
}

export interface DateRangePickerProps {
  value: DateRange;
  onChange: (next: DateRange) => void;
  /** earliest / latest selectable day, YYYY-MM-DD */
  min?: string;
  max?: string;
  /** extra quick presets, shown after the built-in ones */
  presets?: DateRangePreset[];
  /** a range may start and end on the same day (default true) */
  allowSingleDay?: boolean;
  /** 0 = Sunday … 6 = Saturday; default 1 (Monday) */
  weekStartsOn?: 0 | 1 | 2 | 3 | 4 | 5 | 6;
  disabled?: boolean;
  /** accessible name of the trigger, e.g. "Scouting range" */
  label?: string;
  className?: string;
  /** `field` is a bordered box for form dialogs (as DatePicker's) */
  variant?: "pill" | "field";
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const addDays = (d: Date, n: number): Date => {
  const x = new Date(d);
  x.setDate(x.getDate() + n);
  return x;
};

/** Parse dd/mm/yyyy, d/m/yyyy or yyyy-mm-dd into an ISO string, or null. */
export function parseTypedDate(text: string): string | null {
  const s = text.trim();
  let y: number, m: number, d: number;
  let hit = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(s);
  if (hit) {
    y = +hit[1];
    m = +hit[2];
    d = +hit[3];
  } else if ((hit = /^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})$/.exec(s))) {
    d = +hit[1];
    m = +hit[2];
    y = +hit[3];
  } else {
    return null;
  }
  const date = new Date(y, m - 1, d);
  if (date.getFullYear() !== y || date.getMonth() !== m - 1 || date.getDate() !== d) return null;
  return ymd(date);
}

const validIso = (s: string): boolean => !!s && parseTypedDate(s) === s;

/** "1 – 15 Oct 2026", "28 Sep – 3 Oct 2026", "15 Oct 2026". */
export function formatRange(r: DateRange): string {
  if (!validIso(r.from) || !validIso(r.to)) return "Pick a range";
  const a = parseYmd(r.from);
  const b = parseYmd(r.to);
  const mon = (d: Date) => MONTHS[d.getMonth()];
  if (r.from === r.to) return `${b.getDate()} ${mon(b)} ${b.getFullYear()}`;
  if (a.getFullYear() !== b.getFullYear()) {
    return `${a.getDate()} ${mon(a)} ${a.getFullYear()} – ${b.getDate()} ${mon(b)} ${b.getFullYear()}`;
  }
  if (a.getMonth() !== b.getMonth()) {
    return `${a.getDate()} ${mon(a)} – ${b.getDate()} ${mon(b)} ${b.getFullYear()}`;
  }
  return `${a.getDate()} – ${b.getDate()} ${mon(b)} ${b.getFullYear()}`;
}

const startOfWeek = (d: Date, weekStartsOn: number): Date => addDays(d, -((d.getDay() - weekStartsOn + 7) % 7));

export function builtInPresets(weekStartsOn: number, now: () => Date = () => new Date()): DateRangePreset[] {
  const today = () => {
    const n = now();
    return new Date(n.getFullYear(), n.getMonth(), n.getDate());
  };
  const span = (a: Date, b: Date): DateRange => ({ from: ymd(a), to: ymd(b) });
  return [
    { label: "Today", range: () => span(today(), today()) },
    {
      label: "Yesterday",
      range: () => span(addDays(today(), -1), addDays(today(), -1)),
    },
    {
      label: "This week",
      range: () => {
        const s = startOfWeek(today(), weekStartsOn);
        return span(s, addDays(s, 6));
      },
    },
    { label: "Last 7 days", range: () => span(addDays(today(), -6), today()) },
    {
      label: "Last 14 days",
      range: () => span(addDays(today(), -13), today()),
    },
    {
      label: "This month",
      range: () => {
        const t = today();
        return span(new Date(t.getFullYear(), t.getMonth(), 1), new Date(t.getFullYear(), t.getMonth() + 1, 0));
      },
    },
    {
      label: "Last month",
      range: () => {
        const t = today();
        return span(new Date(t.getFullYear(), t.getMonth() - 1, 1), new Date(t.getFullYear(), t.getMonth(), 0));
      },
    },
  ];
}

function useWide(): boolean {
  const q = "(min-width: 640px)";
  const get = () => (typeof window !== "undefined" && window.matchMedia ? window.matchMedia(q).matches : false);
  const [wide, setWide] = useState(get);
  useEffect(() => {
    if (!window.matchMedia) return;
    const mq = window.matchMedia(q);
    const on = () => setWide(mq.matches);
    on();
    mq.addEventListener?.("change", on);
    return () => mq.removeEventListener?.("change", on);
  }, []);
  return wide;
}

/** Pill trigger, same look as DatePicker / the header filter pills. */
const PILL_TRIGGER =
  "h-9 gap-2 rounded-full border-transparent bg-card px-4 text-xs font-medium tabular-nums text-foreground shadow-[var(--sd-shadow-1)] hover:bg-card hover:text-foreground hover:shadow-[var(--sd-shadow-2)] [&>svg]:text-[var(--sd-quiet)]";

const FIELD_TRIGGER =
  "h-9 gap-2 rounded-xl border border-input bg-background px-3 text-sm font-medium tabular-nums text-foreground shadow-sm hover:bg-background hover:text-foreground [&>svg]:text-[var(--sd-quiet)]";

export type StepUnit = "year" | "month" | "day";
export interface StepOptions {
  min?: string;
  max?: string;
  allowSingleDay?: boolean;
}

const daysInMonth = (y: number, m: number): number => new Date(y, m + 1, 0).getDate();

/** Move one date by a year / month / day, clamping the day to the target month's length. */
export function stepDate(iso: string, unit: StepUnit, delta: number): string {
  const d = parseYmd(iso);
  if (unit === "day") return ymd(new Date(d.getFullYear(), d.getMonth(), d.getDate() + delta));
  const total =
    unit === "year" ? d.getFullYear() * 12 + d.getMonth() + delta * 12 : d.getFullYear() * 12 + d.getMonth() + delta;
  const y = Math.floor(total / 12);
  const m = total - y * 12;
  return ymd(new Date(y, m, Math.min(d.getDate(), daysInMonth(y, m))));
}

/**
 * Step one end of a range. Day clamps to the month's length and min / max are
 * respected; a step that would put From after To is refused (nothing is carried
 * along). Returns the input unchanged when the step is not possible.
 */
export function stepRange(
  r: DateRange,
  end: "from" | "to",
  unit: StepUnit,
  delta: number,
  opts: StepOptions = {},
): DateRange {
  if (!validIso(r.from) || !validIso(r.to)) return r;
  let moved = stepDate(r[end], unit, delta);
  if (opts.min && moved < opts.min) moved = opts.min;
  if (opts.max && moved > opts.max) moved = opts.max;
  return commitEnd(r, end, moved, opts);
}

/** Whether `iso` fits on one end: inside min / max and never putting From after To. */
function fits(r: DateRange, end: "from" | "to", iso: string, opts: StepOptions): boolean {
  const { min, max, allowSingleDay = true } = opts;
  if ((min && iso < min) || (max && iso > max)) return false;
  const other = end === "from" ? r.to : r.from;
  const [from, to] = end === "from" ? [iso, other] : [other, iso];
  return allowSingleDay ? from <= to : from < to;
}

/** Put `moved` on one end; unchanged when it would reverse the range or leave min / max (no carrying). */
function commitEnd(r: DateRange, end: "from" | "to", moved: string, opts: StepOptions): DateRange {
  if (!fits(r, end, moved, opts)) return r;
  return end === "from" ? { from: moved, to: r.to } : { from: r.from, to: moved };
}

/** Inclusive day count of a range. */
export function daysInRange(r: DateRange): number {
  const a = parseYmd(r.from);
  const b = parseYmd(r.to);
  return (
    Math.round(
      (Date.UTC(b.getFullYear(), b.getMonth(), b.getDate()) - Date.UTC(a.getFullYear(), a.getMonth(), a.getDate())) /
        86400000,
    ) + 1
  );
}

type Mode = "calendar" | "counter";
const MODE_KEY = "scp.dateRangePicker.mode";
const readMode = (): Mode => {
  try {
    return window.localStorage.getItem(MODE_KEY) === "counter" ? "counter" : "calendar";
  } catch {
    return "calendar";
  }
};
const writeMode = (m: Mode) => {
  try {
    window.localStorage.setItem(MODE_KEY, m);
  } catch {
    /* storage unavailable */
  }
};

/** Set one part (day / month / year) of one end to an exact value; day clamps to the month's length. */
export function setRangePart(
  r: DateRange,
  end: "from" | "to",
  unit: StepUnit,
  n: number,
  opts: StepOptions = {},
): DateRange {
  if (!validIso(r.from) || !validIso(r.to)) return r;
  return commitEnd(r, end, partCandidate(r[end], unit, n), opts);
}

/** `iso` with one part replaced; the day clamps to the resulting month's length. */
export function partCandidate(iso: string, unit: StepUnit, n: number): string {
  const d = parseYmd(iso);
  const y = unit === "year" ? n : d.getFullYear();
  const m = unit === "month" ? n : d.getMonth();
  const day = Math.min(unit === "day" ? n : d.getDate(), daysInMonth(y, m));
  return ymd(new Date(y, m, day));
}

const currentPart = (d: Date, unit: StepUnit): number =>
  unit === "year" ? d.getFullYear() : unit === "month" ? d.getMonth() : d.getDate();

const pad2 = (n: number) => String(n).padStart(2, "0");

/**
 * One picker for a from/to range. Click a start day then an end day (the
 * second click earlier than the first swaps them) or pick a preset. There are
 * no typed fields: picking is the only way in, and the chosen From / To read
 * back as labels. Click the month caption to zoom out to a month grid, and
 * again to a list of years, to jump far quickly. Two months side by side on
 * wide screens, one on a phone. A segmented switch flips to a Counter view:
 * day / month / year wheels (the TimePicker odometer) for From and To (no typing), for long jumps
 * such as January to December. Both modes edit the same draft.
 */
type View = "days" | "months" | "years";

const MONTH_LONG = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

const nice = (iso: string): string => {
  const d = parseYmd(iso);
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
};

const GRID_BTN =
  "rounded-full px-2 py-2 text-sm font-medium tabular-nums transition-[transform,background-color,color] duration-150 hover:bg-[var(--sidebar-accent)] active:scale-95 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30 disabled:cursor-not-allowed disabled:text-muted-foreground/40 disabled:hover:bg-transparent disabled:active:scale-100 motion-reduce:transition-none motion-reduce:active:scale-100";

export function DateRangePicker({
  value,
  onChange,
  min,
  max,
  presets,
  allowSingleDay = true,
  weekStartsOn = 1,
  disabled,
  label = "Date range",
  className,
  variant = "pill",
}: DateRangePickerProps) {
  const [open, setOpen] = useState(false);
  // anchor = first click waiting for its second; null = nothing pending
  const [anchor, setAnchor] = useState<string | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  const [month, setMonth] = useState<Date>(() => parseYmd(validIso(value.from) ? value.from : ymd(new Date())));
  const [view, setView] = useState<View>("days");
  const [slide, setSlide] = useState<{
    dir: "none" | "next" | "prev";
    tick: 0 | 1;
  }>({ dir: "none", tick: 0 });
  const [mode, setModeState] = useState<Mode>(readMode);
  const [monthAnchor, setMonthAnchor] = useState<{
    y: number;
    m: number;
  } | null>(null);
  const [wholeMonths, setWholeMonths] = useState(false);
  const wide = useWide();

  const clampIso = (iso: string) => (min && iso < min ? min : max && iso > max ? max : iso);
  const initialDraft = (): DateRange =>
    validIso(value.from) && validIso(value.to)
      ? value.from <= value.to
        ? { from: value.from, to: value.to }
        : { from: value.to, to: value.from }
      : { from: clampIso(ymd(new Date())), to: clampIso(ymd(new Date())) };
  // what both modes edit; calendar picks and presets commit it straight away,
  // the counter commits it with Apply
  const [draft, setDraft] = useState<DateRange>(initialDraft);
  const setMode = (m: Mode) => {
    setModeState(m);
    writeMode(m);
    setAnchor(null);
    setHover(null);
    setMonthAnchor(null);
    setView("days");
    if (m === "calendar" && validIso(draft.from)) setMonth(parseYmd(draft.from));
  };
  const stepOpts = { min, max, allowSingleDay };
  const setPart = (end: "from" | "to", unit: StepUnit, n: number) =>
    setDraft((d) => setRangePart(d, end, unit, n, stepOpts));
  const wheelOptions = (end: "from" | "to", unit: StepUnit): WheelOption[] => {
    const d = parseYmd(draft[end]);
    const ok = (n: number) => validIso(draft[end]) && fits(draft, end, partCandidate(draft[end], unit, n), stepOpts);
    if (unit === "day")
      return Array.from({ length: daysInMonth(d.getFullYear(), d.getMonth()) }, (_, i) => ({
        value: String(i + 1),
        label: pad2(i + 1),
        disabled: !ok(i + 1),
      }));
    if (unit === "month") return MONTHS.map((l, i) => ({ value: String(i), label: l, disabled: !ok(i) }));
    const thisYear = new Date().getFullYear();
    const lo = min ? +min.slice(0, 4) : Math.min(thisYear - 10, +draft.from.slice(0, 4));
    const hi = max ? +max.slice(0, 4) : Math.max(thisYear + 5, +draft.to.slice(0, 4));
    return Array.from({ length: Math.max(1, hi - lo + 1) }, (_, i) => ({
      value: String(lo + i),
      disabled: !ok(lo + i),
    }));
  };

  const allPresets = useMemo(() => [...builtInPresets(weekStartsOn), ...(presets ?? [])], [weekStartsOn, presets]);

  const inBounds = (iso: string) => (!min || iso >= min) && (!max || iso <= max);
  const clamp = (iso: string) => (min && iso < min ? min : max && iso > max ? max : iso);

  const openChange = (next: boolean) => {
    setOpen(next);
    setAnchor(null);
    setHover(null);
    setView("days");
    setSlide({ dir: "none", tick: 0 });
    setMonthAnchor(null);
    setWholeMonths(false);
    if (next) {
      setMonth(parseYmd(validIso(value.from) ? value.from : ymd(new Date())));
      setDraft(initialDraft());
      setModeState(readMode());
    }
  };

  const onMonthPick = (y: number, m: number) => {
    if (!wholeMonths) {
      changeMonth(new Date(y, m, 1));
      setView("days");
      return;
    }
    if (!monthAnchor) {
      setMonthAnchor({ y, m });
      return;
    }
    const a = monthAnchor.y * 12 + monthAnchor.m;
    const b = y * 12 + m;
    const [lo, hi] = a <= b ? [a, b] : [b, a];
    const first = ymd(new Date(Math.floor(lo / 12), lo % 12, 1));
    const last = ymd(new Date(Math.floor(hi / 12), (hi % 12) + 1, 0));
    const from = clamp(first);
    const to = clamp(last);
    if (!allowSingleDay && from === to) return;
    onChange({ from, to });
    setMonthAnchor(null);
    setOpen(false);
  };

  const commit = (a: string, b: string) => {
    const [from, to] = a <= b ? [a, b] : [b, a];
    onChange({ from, to });
  };

  const onDay = (day: Date) => {
    const iso = ymd(day);
    if (!inBounds(iso)) return;
    if (anchor == null) {
      setAnchor(iso);
      return;
    }
    if (iso === anchor && !allowSingleDay) return;
    commit(anchor, iso);
    setAnchor(null);
    setHover(null);
    setOpen(false);
  };

  const applyPreset = (p: DateRangePreset) => {
    const r = p.range();
    // a preset that comes back reversed is swapped, never stored reversed
    const [lo, hi] = r.from <= r.to ? [r.from, r.to] : [r.to, r.from];
    const from = clamp(lo);
    const to = clamp(hi);
    if (!allowSingleDay && from === to) return;
    onChange({ from, to });
    setOpen(false);
  };

  const applyDraft = () => {
    if (!validIso(draft.from) || !validIso(draft.to)) return;
    const [from, to] = draft.from <= draft.to ? [draft.from, draft.to] : [draft.to, draft.from];
    onChange({ from, to });
    setOpen(false);
  };

  const changeMonth = (next: Date) => {
    const dir = next.getTime() === month.getTime() ? "none" : next > month ? "next" : "prev";
    setSlide((t) => ({ dir, tick: t.tick ? 0 : 1 }));
    setMonth(next);
  };

  const monthOk = (y: number, m: number) => {
    const first = ymd(new Date(y, m, 1));
    const last = ymd(new Date(y, m + 1, 0));
    return (!min || last >= min) && (!max || first <= max);
  };
  const yearOk = (y: number) => (!min || `${y}-12-31` >= min) && (!max || `${y}-01-01` <= max);

  const year = month.getFullYear();
  const yearStart = Math.floor(year / 12) * 12;

  // What the calendar paints: a pending anchor with the hover as its preview,
  // otherwise the committed value.
  const shown: DayRange | undefined = useMemo(() => {
    if (anchor) {
      const other = hover ?? anchor;
      const [a, b] = anchor <= other ? [anchor, other] : [other, anchor];
      return { from: parseYmd(a), to: parseYmd(b) };
    }
    if (validIso(draft.from) && validIso(draft.to)) return { from: parseYmd(draft.from), to: parseYmd(draft.to) };
    return undefined;
  }, [anchor, hover, draft.from, draft.to]);

  const disabledDays = [...(min ? [{ before: parseYmd(min) }] : []), ...(max ? [{ after: parseYmd(max) }] : [])];

  const display = formatRange(value);
  const valid = validIso(value.from) && validIso(value.to);

  return (
    <Popover open={open} onOpenChange={openChange}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          disabled={disabled}
          className={cn(
            variant === "field" ? FIELD_TRIGGER : PILL_TRIGGER,
            !valid && "text-muted-foreground",
            className,
          )}
          aria-label={label}
          aria-haspopup="dialog"
        >
          <CalendarIcon className="h-3.5 w-3.5" />
          {display}
        </Button>
      </PopoverTrigger>
      <PopoverContent
        role="dialog"
        aria-label={`${label} picker`}
        className="w-auto max-w-[calc(100vw-1rem)] p-0"
        align="start"
      >
        <div
          role="tablist"
          aria-label="Picker mode"
          className="m-2 mb-0 flex w-fit gap-0.5 rounded-full bg-[var(--sidebar-accent)] p-0.5"
        >
          {(["calendar", "counter"] as Mode[]).map((m) => (
            <button
              key={m}
              type="button"
              role="tab"
              aria-selected={mode === m}
              onClick={() => setMode(m)}
              className={cn(
                "rounded-full px-3 py-1 text-xs font-medium capitalize transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30 motion-reduce:transition-none",
                mode === m ? "bg-foreground text-background shadow-sm" : "text-foreground hover:bg-foreground/10",
              )}
            >
              {m}
            </button>
          ))}
        </div>
        <div className="flex flex-col sm:flex-row">
          <div
            role="group"
            aria-label="Quick ranges"
            className="flex flex-row flex-wrap gap-1 border-b p-2 sm:w-32 sm:flex-col sm:flex-nowrap sm:border-b-0 sm:border-r"
          >
            {allPresets.map((p) => (
              <button
                key={p.label}
                type="button"
                onClick={() => applyPreset(p)}
                className="rounded-full px-3 py-1 text-left text-xs font-medium text-foreground hover:bg-[var(--sidebar-accent)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30"
              >
                {p.label}
              </button>
            ))}
          </div>
          {mode === "counter" && (
            <div className="scp-cal-zoom w-[17.5rem] p-3 sm:w-[23rem]" data-testid="counter-view">
              <div className="grid gap-3 sm:grid-cols-2">
                {(["from", "to"] as const).map((end) => {
                  const ok = validIso(draft[end]);
                  const d = ok ? parseYmd(draft[end]) : null;
                  return (
                    <div
                      key={end}
                      role="group"
                      aria-label={end === "from" ? "From" : "To"}
                      className="flex flex-col gap-1"
                    >
                      <span className="px-1 text-xs font-medium text-muted-foreground">
                        {end === "from" ? "From" : "To"}
                      </span>
                      <div className="flex items-center justify-center gap-1">
                        {(["day", "month", "year"] as const).map((unit) => (
                          <WheelStepper
                            key={unit}
                            rows={3}
                            className={unit === "year" ? "w-14" : "w-12"}
                            name={`${end === "from" ? "From" : "To"} ${unit}`}
                            options={wheelOptions(end, unit)}
                            value={d ? String(currentPart(d, unit)) : ""}
                            onChange={(v) => setPart(end, unit, Number(v))}
                          />
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>
              <div className="mt-3 flex items-center justify-between gap-2 border-t pt-3">
                <span
                  className="text-xs font-medium tabular-nums text-foreground"
                  aria-live="polite"
                  data-testid="counter-summary"
                >
                  {validIso(draft.from) && validIso(draft.to)
                    ? `${nice(draft.from)} → ${nice(draft.to)} (${daysInRange(draft)} ${daysInRange(draft) === 1 ? "day" : "days"})`
                    : "Pick a range"}
                </span>
                <button
                  type="button"
                  onClick={applyDraft}
                  className="rounded-full bg-foreground px-4 py-1.5 text-xs font-medium text-background transition-[transform,opacity] duration-150 hover:opacity-90 active:scale-95 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30 motion-reduce:transition-none motion-reduce:active:scale-100"
                >
                  Apply
                </button>
              </div>
            </div>
          )}
          {mode === "calendar" && (
            <div>
              <div
                className="flex items-center gap-x-2 gap-y-0.5 border-b px-3 py-2 text-xs tabular-nums"
                aria-live="polite"
                data-testid="range-readout"
              >
                <span className="text-muted-foreground">From</span>{" "}
                <span className="font-medium text-foreground">
                  {anchor ? nice(anchor) : validIso(draft.from) ? nice(draft.from) : "—"}
                </span>{" "}
                <span className="text-muted-foreground">·</span> <span className="text-muted-foreground">To</span>{" "}
                <span className="font-medium text-foreground">
                  {anchor ? "pick the end day" : validIso(draft.to) ? nice(draft.to) : "—"}
                </span>
              </div>
              {view === "days" && (
                <div className="scp-cal-slide" data-dir={slide.dir} data-tick={slide.tick} data-testid="day-view">
                  <Calendar
                    mode="range"
                    numberOfMonths={wide ? 2 : 1}
                    month={month}
                    onMonthChange={changeMonth}
                    onCaptionClick={() => setView("months")}
                    selected={shown}
                    onSelect={() => {}}
                    onDayClick={onDay}
                    onDayMouseEnter={(d) => anchor && setHover(ymd(d))}
                    onDayFocus={(d) => anchor && setHover(ymd(d))}
                    onDayMouseLeave={() => setHover(null)}
                    disabled={disabledDays}
                    weekStartsOn={weekStartsOn}
                    ISOWeek={weekStartsOn === 1}
                    showWeekNumber={false}
                    classNames={{
                      months: "relative flex flex-col gap-4 sm:flex-row sm:gap-6",
                    }}
                  />
                </div>
              )}
              {view === "months" && (
                <div className="scp-cal-zoom w-[17.5rem] p-3 sm:w-[20rem]" data-testid="month-view">
                  <div className="mb-2 flex items-center justify-between">
                    <button
                      type="button"
                      aria-label="Previous year"
                      className={cn(GRID_BTN, "p-1.5")}
                      onClick={() => changeMonth(new Date(year - 1, month.getMonth(), 1))}
                    >
                      <ChevronLeft className="h-4 w-4" />
                    </button>
                    <button
                      type="button"
                      aria-label="Choose year"
                      className={GRID_BTN}
                      onClick={() => setView("years")}
                    >
                      {year}
                    </button>
                    <button
                      type="button"
                      aria-label="Next year"
                      className={cn(GRID_BTN, "p-1.5")}
                      onClick={() => changeMonth(new Date(year + 1, month.getMonth(), 1))}
                    >
                      <ChevronRight className="h-4 w-4" />
                    </button>
                  </div>
                  <button
                    type="button"
                    aria-pressed={wholeMonths}
                    onClick={() => {
                      setWholeMonths((w) => !w);
                      setMonthAnchor(null);
                    }}
                    className={cn(
                      "mb-2 w-full rounded-full px-3 py-1 text-xs font-medium transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30 motion-reduce:transition-none",
                      wholeMonths
                        ? "bg-foreground text-background"
                        : "bg-[var(--sidebar-accent)] text-foreground hover:bg-foreground/10",
                    )}
                  >
                    {wholeMonths ? (monthAnchor ? "Pick the last month" : "Pick the first month") : "Pick whole months"}
                  </button>
                  <div className="grid grid-cols-3 gap-1">
                    {MONTH_LONG.map((name, i) => {
                      const chosen =
                        [anchor ?? draft.from, anchor ? null : draft.to].some(
                          (iso) =>
                            iso &&
                            validIso(iso) &&
                            parseYmd(iso).getFullYear() === year &&
                            parseYmd(iso).getMonth() === i,
                        ) ||
                        (monthAnchor?.y === year && monthAnchor.m === i);
                      return (
                        <button
                          key={name}
                          type="button"
                          aria-label={`${name} ${year}`}
                          disabled={!monthOk(year, i)}
                          className={cn(GRID_BTN, chosen && "bg-foreground/10 font-semibold")}
                          onClick={() => onMonthPick(year, i)}
                        >
                          {MONTHS[i]}
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}
              {view === "years" && (
                <div className="scp-cal-zoom w-[17.5rem] p-3 sm:w-[20rem]" data-testid="year-view">
                  <div className="mb-2 flex items-center justify-between">
                    <button
                      type="button"
                      aria-label="Previous years"
                      className={cn(GRID_BTN, "p-1.5")}
                      onClick={() => changeMonth(new Date(year - 12, month.getMonth(), 1))}
                    >
                      <ChevronLeft className="h-4 w-4" />
                    </button>
                    <span className="text-sm font-medium tabular-nums">
                      {yearStart} – {yearStart + 11}
                    </span>
                    <button
                      type="button"
                      aria-label="Next years"
                      className={cn(GRID_BTN, "p-1.5")}
                      onClick={() => changeMonth(new Date(year + 12, month.getMonth(), 1))}
                    >
                      <ChevronRight className="h-4 w-4" />
                    </button>
                  </div>
                  <div className="grid grid-cols-3 gap-1">
                    {Array.from({ length: 12 }, (_, i) => yearStart + i).map((y) => (
                      <button
                        key={y}
                        type="button"
                        aria-label={`Year ${y}`}
                        disabled={!yearOk(y)}
                        className={cn(GRID_BTN, y === year && "bg-foreground/10 font-semibold")}
                        onClick={() => {
                          changeMonth(new Date(y, month.getMonth(), 1));
                          setView("months");
                        }}
                      >
                        {y}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}
