import { useEffect, useRef, useState } from "react";
import { Input } from "@/components/ui/input";
import { searchLink } from "@/lib/frappe";
import { cn } from "@/lib/utils";

/**
 * Pick an Employee by typing part of their name or ID.
 *
 * Searches on the server (Frappe's own Link-field search, with its permission
 * check) rather than filtering a list held in the page: a farm group has
 * thousands of employees, and a host can be any of them.
 */
export function EmployeePicker({
  id,
  value,
  onChange,
  placeholder = "Search employees",
  doctype = "Employee",
}: {
  id?: string;
  /** Any doctype with a title: Employee by default, Security Guard for planning. */
  doctype?: string;
  /** Employee ID ("" when none is chosen). */
  value: string;
  onChange: (id: string, label: string) => void;
  placeholder?: string;
}) {
  const [text, setText] = useState("");
  const [hits, setHits] = useState<{ value: string; description: string }[]>([]);
  const [open, setOpen] = useState(false);
  const [failed, setFailed] = useState(false);
  const seq = useRef(0);

  useEffect(() => {
    if (!value) setText("");
  }, [value]);

  useEffect(() => {
    if (!open) return;
    const mine = ++seq.current;
    const t = window.setTimeout(() => {
      void searchLink(doctype, text.trim(), 8).then((rows) => {
        if (mine !== seq.current) return;
        setFailed(rows === null);
        setHits(rows ?? []);
      });
    }, 200);
    return () => window.clearTimeout(t);
  }, [text, open, doctype]);

  return (
    <div className="relative">
      <Input
        id={id}
        value={text}
        placeholder={placeholder}
        autoComplete="off"
        onFocus={() => setOpen(true)}
        onBlur={() => window.setTimeout(() => setOpen(false), 150)}
        onChange={(e) => {
          setText(e.target.value);
          if (value) onChange("", "");
          setOpen(true);
        }}
      />
      {open && (hits.length > 0 || failed) && (
        <ul
          role="listbox"
          className="absolute z-50 mt-1 max-h-64 w-full overflow-auto rounded-[var(--sd-radius-md,10px)] border border-[var(--sd-line)] bg-[var(--sd-card)] py-1 shadow-[var(--sd-shadow-3)]"
        >
          {failed && <li className="px-3 py-2 text-[13px] text-[var(--sd-data-red)]">Could not search.</li>}
          {hits.map((h) => {
            const label = h.description ? `${h.description} (${h.value})` : h.value;
            return (
              <li key={h.value} role="option" aria-selected={h.value === value}>
                <button
                  type="button"
                  className={cn(
                    "block w-full px-3 py-2 text-left text-[13px] hover:bg-[var(--sd-line-soft)]",
                    h.value === value && "font-semibold",
                  )}
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => {
                    setText(label);
                    onChange(h.value, label);
                    setOpen(false);
                  }}
                >
                  {label}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
