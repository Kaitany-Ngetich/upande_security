import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";

/**
 * A dropdown in the app's own clothes.
 *
 * Eight screens were reaching for a bare `<select>`, which the browser draws
 * itself — a grey system control with a system font, sitting between two cards
 * that were styled to the farm's palette. Radix's Select is already here and
 * already used on the Dashboard and in Settings; this is the same thing with
 * the plumbing that made people skip it (a placeholder, an optional blank, a
 * list of plain strings) done once.
 *
 * `Select` cannot hold "" as a value — Radix reserves the empty string for
 * "nothing chosen" — so an optional picker uses a sentinel internally and gives
 * the caller back "" for it. Every screen that offered a blank "—" row got that
 * wrong or worked around it separately.
 */

const NONE = "__none__";

export interface PickerOption {
  value: string;
  label: string;
}

export function Picker({
  value,
  onChange,
  options,
  placeholder = "Choose…",
  /** Offer a "nothing" row. Off by default: most pickers are required. */
  clearable = false,
  clearLabel = "—",
  id,
  label,
  className,
  disabled,
}: {
  value: string;
  onChange: (next: string) => void;
  options: (PickerOption | string)[];
  placeholder?: string;
  clearable?: boolean;
  clearLabel?: string;
  id?: string;
  /** For anybody not looking at the field's own label. */
  label?: string;
  className?: string;
  disabled?: boolean;
}) {
  // An option with no value is dropped rather than rendered. Radix reserves
  // the empty string for "nothing chosen" and throws on an item that uses it,
  // so one bad row would take the whole screen down — and a list built from a
  // server payload can always carry one.
  const rows: PickerOption[] = options
    .map((o) => (typeof o === "string" ? { value: o, label: o } : o))
    .filter((o): o is PickerOption => !!o && !!o.value);
  return (
    <Select
      value={value === "" ? (clearable ? NONE : undefined) : value}
      onValueChange={(next) => onChange(next === NONE ? "" : next)}
      disabled={disabled}
    >
      <SelectTrigger id={id} aria-label={label} className={cn("h-9 text-[13px]", className)}>
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent>
        {clearable && <SelectItem value={NONE}>{clearLabel}</SelectItem>}
        {rows.map((o) => (
          <SelectItem key={o.value} value={o.value}>
            {o.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
