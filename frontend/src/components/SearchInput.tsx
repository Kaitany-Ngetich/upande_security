/**
 * The one search bar. A rounded rectangle (8px — `rounded-lg`) with a leading
 * magnifier and a clear (×) button once there is text. 8px is what a popover
 * with 16px corners (`rounded-2xl`) and 8px padding (`p-2`) gives an inner
 * control (outer radius − padding), so inside a picker the corners nest.
 *
 * `className` styles the wrapper (width, margins); other props go to the
 * <input>. `onChange` receives the text, not the event.
 */
import * as React from "react";
import { Search, X } from "lucide-react";
import { cn } from "@/lib/utils";

export type SearchInputProps = Omit<
  React.InputHTMLAttributes<HTMLInputElement>,
  "onChange" | "value" | "type" | "size"
> & {
  value: string;
  onChange: (next: string) => void;
  /** "md" (h-9, 14px) for page toolbars; default "sm" (h-8, 12px) */
  size?: "sm" | "md";
};

export const SearchInput = React.forwardRef<HTMLInputElement, SearchInputProps>(
  ({ value, onChange, size = "sm", className, disabled, placeholder = "Search…", onKeyDown, ...rest }, ref) => {
    const inner = React.useRef<HTMLInputElement | null>(null);
    const setRef = (el: HTMLInputElement | null) => {
      inner.current = el;
      if (typeof ref === "function") ref(el);
      else if (ref) (ref as React.MutableRefObject<HTMLInputElement | null>).current = el;
    };
    const clear = () => {
      onChange("");
      inner.current?.focus();
    };
    return (
      <div className={cn("relative w-full", className)}>
        <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
        <input
          ref={setRef}
          type="text"
          value={value}
          disabled={disabled}
          placeholder={placeholder}
          aria-label={rest["aria-label"] ?? placeholder}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={onKeyDown}
          {...rest}
          className={cn(
            "w-full rounded-lg border border-input bg-background pl-8 pr-8 shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30 disabled:cursor-not-allowed disabled:opacity-50",
            size === "md" ? "h-9 text-sm" : "h-8 text-xs",
          )}
        />
        {value && !disabled && (
          <button
            type="button"
            aria-label="Clear search"
            onClick={clear}
            className="absolute right-1.5 top-1/2 flex h-5 w-5 -translate-y-1/2 items-center justify-center rounded-full text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            <X className="h-3 w-3" />
          </button>
        )}
      </div>
    );
  },
);
SearchInput.displayName = "SearchInput";
