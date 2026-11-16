import * as React from "react";
import { Check } from "lucide-react";
import { HEADER_PILL } from "@/components/header-controls";
import { cn } from "@/lib/utils";

/**
 * A toggle-style filter ("Group by farm") in exactly FilterSelect's pill
 * (`HEADER_PILL`). Its on-state is a check mark and a subtle tint, never a
 * different shape.
 */
export const TogglePill = React.forwardRef<
  HTMLButtonElement,
  Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "onChange"> & {
    pressed: boolean;
    onPressedChange?: (next: boolean) => void;
  }
>(({ pressed, onPressedChange, className, children, onClick, ...props }, ref) => (
  <button
    ref={ref}
    type="button"
    aria-pressed={pressed}
    onClick={(e) => {
      onClick?.(e);
      onPressedChange?.(!pressed);
    }}
    className={cn(
      HEADER_PILL,
      "inline-flex cursor-pointer items-center justify-center whitespace-nowrap transition-all",
      pressed && "bg-[var(--sd-bg-soft)] text-foreground ring-1 ring-foreground/20",
      className,
    )}
    {...props}
  >
    {pressed ? <Check className="h-3.5 w-3.5" aria-hidden /> : null}
    {children}
  </button>
));
TogglePill.displayName = "TogglePill";
