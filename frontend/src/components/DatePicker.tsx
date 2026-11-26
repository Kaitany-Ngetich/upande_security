import { useMemo, useState } from "react";
import { CalendarDays } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { cn, parseYmd, ymd } from "@/lib/utils";

/**
 * The app's one date control, ported from the scouting frontend so both farm
 * apps open the same calendar.
 *
 * It replaces `<input type="date">`, which renders as whatever the browser
 * feels like — a different width, a different glyph and a different popup on
 * every machine on the farm — and cannot be told to stop offering tomorrow in
 * any way the user can see before they click it.
 *
 * `max` is honoured as a real boundary: days past it are struck out in the
 * calendar rather than refused after the fact.
 */
export function DatePicker({
  value,
  onChange,
  max,
  min,
  disabled,
  id,
  className,
  placeholder = "Pick a date",
  "aria-label": ariaLabel,
}: {
  value: string;
  onChange: (next: string) => void;
  /** Latest selectable day, YYYY-MM-DD. */
  max?: string;
  /** Earliest selectable day, YYYY-MM-DD. */
  min?: string;
  disabled?: boolean;
  id?: string;
  className?: string;
  placeholder?: string;
  "aria-label"?: string;
}) {
  const [open, setOpen] = useState(false);
  const selected = useMemo(() => parseYmd(value), [value]);
  const maxDate = useMemo(() => parseYmd(max || ""), [max]);
  const minDate = useMemo(() => parseYmd(min || ""), [min]);

  const label = useMemo(() => {
    if (!selected) return placeholder;
    return selected.toLocaleDateString(undefined, {
      weekday: "short",
      day: "numeric",
      month: "short",
      year: "numeric",
    });
  }, [selected, placeholder]);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          id={id}
          type="button"
          variant="outline"
          size="sm"
          disabled={disabled}
          aria-label={ariaLabel}
          className={cn(
            "h-9 justify-start gap-2 rounded-[var(--sd-radius)] border-[var(--sd-line)] bg-[var(--sd-card)] px-3 text-[13px] font-medium tabular-nums text-[var(--sd-ink)] shadow-[var(--sd-shadow-1)]",
            "hover:bg-[var(--sd-card)] hover:text-[var(--sd-ink)] hover:shadow-[var(--sd-shadow-2)]",
            "disabled:bg-[var(--sd-bg-soft)] disabled:text-[var(--sd-quiet)] disabled:shadow-none",
            !selected && "font-normal text-[var(--sd-quiet)]",
            className,
          )}
        >
          <CalendarDays className="h-3.5 w-3.5 shrink-0 text-[var(--sd-quiet)]" />
          {label}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-auto p-0" align="start">
        <Calendar
          mode="single"
          defaultMonth={selected}
          selected={selected}
          disabled={[
            ...(maxDate ? [{ after: maxDate }] : []),
            ...(minDate ? [{ before: minDate }] : []),
          ]}
          onSelect={(d) => {
            if (!d) return;
            onChange(ymd(d));
            setOpen(false);
          }}
        />
      </PopoverContent>
    </Popover>
  );
}
