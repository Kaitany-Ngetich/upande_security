/**
 * A page filter dropdown in the header pill style (`HEADER_PILL`) — the one
 * every page uses for farm, status, group-by and the like, so a filter looks
 * and opens the same wherever it is. Ported from SCP; replaces native
 * <select>s, which drew the browser's own control and menu.
 *
 * `options` is either plain strings or `{ value, label }` pairs. `allLabel`
 * adds an "All …" first option that stands for "" (Radix Select cannot hold an
 * empty value, so it travels as a sentinel inside). The accessible name comes
 * from `label` (or `aria-label`).
 */
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { HEADER_PILL } from "@/components/header-controls";
import { cn } from "@/lib/utils";

const ALL = "__all__";

export interface FilterOption {
  value: string;
  label: string;
}

export function FilterSelect({
  label,
  "aria-label": ariaLabel,
  value,
  onChange,
  options,
  allLabel,
  placeholder,
  disabled,
  className,
  format,
}: {
  /** accessible name, e.g. "Farm"; also the placeholder when none is given */
  label?: string;
  "aria-label"?: string;
  value: string;
  onChange: (next: string) => void;
  options: Array<string | FilterOption>;
  allLabel?: string;
  placeholder?: string;
  disabled?: boolean;
  className?: string;
  /** how a plain-string option reads (defaults to itself) */
  format?: (option: string) => string;
}) {
  const seen = new Set<string>();
  const opts: FilterOption[] = [];
  for (const o of options) {
    const item = typeof o === "string" ? { value: o, label: format ? format(o) : o } : o;
    if (!item.value || seen.has(item.value)) continue;
    seen.add(item.value);
    opts.push(item);
  }
  const name = ariaLabel ?? label;
  return (
    <Select
      value={value ? value : allLabel ? ALL : undefined}
      onValueChange={(v) => onChange(v === ALL ? "" : v)}
      disabled={disabled}
    >
      <SelectTrigger aria-label={name} className={cn(HEADER_PILL, className)}>
        <SelectValue placeholder={placeholder ?? label ?? name} />
      </SelectTrigger>
      <SelectContent>
        {allLabel && <SelectItem value={ALL}>{allLabel}</SelectItem>}
        {opts.map((o) => (
          <SelectItem key={o.value} value={o.value}>
            {o.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
