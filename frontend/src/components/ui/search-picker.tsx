import { useMemo, useState } from "react";
import { ChevronDown, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

export interface SearchOption {
  value: string;
  label: string;
  /** What the closed picker shows once this is chosen, when the label carries
   *  more than the box has room for (an item's stock, which its row shows). */
  short?: string;
}

/**
 * A choice out of a list the page already holds, found by typing.
 *
 * For the item pickers: the list (the in-stock items of the event's item groups)
 * comes with the page, so searching it is a filter in the browser, not a call
 * per keystroke. Matches on any word of the label or the code, in any order.
 * Enter takes the first match; arrows move.
 */
export function SearchPicker({
  value,
  onChange,
  options,
  placeholder = "Search…",
  id,
  label,
  className,
}: {
  value: string;
  onChange: (next: string) => void;
  options: SearchOption[];
  placeholder?: string;
  id?: string;
  label?: string;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [term, setTerm] = useState("");
  const [active, setActive] = useState(0);

  const chosen = options.find((o) => o.value === value);
  const matches = useMemo(() => {
    const words = term.toLowerCase().split(/\s+/).filter(Boolean);
    const hits = words.length
      ? options.filter((o) => {
          const hay = `${o.label} ${o.value}`.toLowerCase();
          return words.every((w) => hay.includes(w));
        })
      : options;
    return hits.slice(0, 60);
  }, [options, term]);

  function pick(next: string) {
    onChange(next);
    setOpen(false);
    setTerm("");
    setActive(0);
  }

  return (
    <Popover open={open} onOpenChange={(o) => { setOpen(o); if (!o) setTerm(""); }}>
      <PopoverTrigger asChild>
        <Button
          id={id}
          type="button"
          variant="outline"
          aria-label={label}
          className={cn("h-9 w-full justify-between gap-2 px-3 font-normal", className)}
        >
          <span className={cn("truncate text-left", !chosen && "text-[var(--sd-quiet)]")}>
            {chosen ? chosen.short ?? chosen.label : placeholder}
          </span>
          <ChevronDown className="h-3.5 w-3.5 shrink-0 text-[var(--sd-quiet)]" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[min(28rem,90vw)] p-2">
        <div className="flex items-center gap-2 px-1 pb-2">
          <Search className="h-3.5 w-3.5 text-[var(--sd-quiet)]" />
          <Input
            autoFocus
            value={term}
            placeholder="Type to search…"
            className="h-8"
            onChange={(e) => { setTerm(e.target.value); setActive(0); }}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, matches.length - 1)); }
              if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
              if (e.key === "Enter" && matches[active]) { e.preventDefault(); pick(matches[active].value); }
            }}
          />
        </div>
        <div role="listbox" className="max-h-64 overflow-y-auto">
          {matches.length === 0 && (
            <p className="px-2 py-3 text-[12.5px] text-[var(--sd-quiet)]">Nothing matches “{term}”.</p>
          )}
          {matches.map((o, i) => (
            <button
              key={o.value}
              type="button"
              role="option"
              aria-selected={o.value === value}
              onMouseEnter={() => setActive(i)}
              onClick={() => pick(o.value)}
              className={cn(
                "flex w-full rounded-md px-2 py-1.5 text-left text-[13px] text-[var(--sd-ink)]",
                i === active && "bg-[var(--sd-bg-soft)]",
                o.value === value && "font-medium",
              )}
            >
              {o.label}
            </button>
          ))}
          {options.length > matches.length && !term && (
            <p className="px-2 pt-1 text-[11px] text-[var(--sd-quiet)]">Type to find the rest.</p>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}
