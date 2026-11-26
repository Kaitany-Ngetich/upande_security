import { useState } from "react";
import { Clock as ClockIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { WheelStepper } from "@/components/WheelPicker";
import { cn, format12h, from12h, stepTime, to12h } from "@/lib/utils";

export interface TimePickerProps {
  value: string; // HH:mm (24-hour)
  onChange: (next: string) => void;
  label?: string;
  className?: string;
  disabled?: boolean;
}

/** Bordered box matching the Select dropdown triggers on form pages (and the
 *  DatePicker `field` variant) so date + time read as one control family. */
const FIELD_TRIGGER =
  "h-9 gap-2 rounded-md border border-input bg-background px-3 text-sm font-medium tabular-nums text-foreground shadow-sm hover:bg-background hover:text-foreground [&>svg]:text-[var(--sd-quiet)]";

// 12-hour clock order: 12, 01, 02 … 11 (noon/midnight read as "12").
const HOURS = [
  "12",
  ...Array.from({ length: 11 }, (_, i) => String(i + 1).padStart(2, "0")),
];
const MINUTES = Array.from({ length: 12 }, (_, i) =>
  String(i * 5).padStart(2, "0"),
);
const MERIDIEMS = ["AM", "PM"];

/**
 * Themed time picker matching the DatePicker `field` trigger. Opens a popover
 * with two odometer-roll columns (12-hour hours, minutes) plus an AM/PM toggle.
 * Minutes step by 5 and carry into the hour; hours roll through the 12-hour
 * clock and flip AM/PM at the noon/midnight boundary. The value stays a 24-hour
 * ``HH:mm`` string; only the display is 12-hour.
 */
export function TimePicker({
  value,
  onChange,
  label,
  className,
  disabled,
}: TimePickerProps) {
  const [open, setOpen] = useState(false);
  const time = value || "06:00";
  const { hour12, minute, meridiem } = to12h(time);

  // Hours/minutes step on the 24-hour value so the carry (and the AM/PM flip at
  // noon/midnight) falls out for free; only the labels are 12-hour.
  const step = (field: "hour" | "minute", dir: 1 | -1) =>
    onChange(stepTime(time, field, dir));
  const setMeridiem = (mer: "AM" | "PM") =>
    onChange(from12h(Number(hour12), Number(minute), mer));

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          disabled={disabled}
          className={cn(FIELD_TRIGGER, className)}
          aria-label={label}
        >
          <ClockIcon className="h-3.5 w-3.5" />
          {format12h(time)}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-auto p-3" align="start">
        <div className="flex items-center gap-2">
          <WheelStepper
            name="hour"
            options={HOURS}
            value={hour12}
            onStep={(dir) => step("hour", dir)}
          />
          <span className="pb-1 text-lg font-semibold text-muted-foreground">
            :
          </span>
          <WheelStepper
            name="minute"
            options={MINUTES}
            value={minute}
            onStep={(dir) => step("minute", dir)}
          />
          <WheelStepper
            name="AM/PM"
            options={MERIDIEMS}
            value={meridiem}
            onStep={() => setMeridiem(meridiem === "AM" ? "PM" : "AM")}
          />
        </div>
      </PopoverContent>
    </Popover>
  );
}
