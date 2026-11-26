import * as React from "react";
import { HEADER_PILL } from "@/components/header-controls";
import { cn } from "@/lib/utils";

/**
 * A text action in the page toolbar ("New cycle"): the same rounded pill as
 * FilterSelect (`HEADER_PILL`), so buttons and dropdowns read as one family.
 * Icon-only actions use `HeaderIconButton` (a round pill of the same height).
 */
export const ToolbarButton = React.forwardRef<
  HTMLButtonElement,
  React.ButtonHTMLAttributes<HTMLButtonElement>
>(({ className, type = "button", ...props }, ref) => (
  <button
    ref={ref}
    type={type}
    className={cn(
      HEADER_PILL,
      "inline-flex cursor-pointer items-center justify-center whitespace-nowrap transition-all disabled:pointer-events-none disabled:opacity-50",
      className,
    )}
    {...props}
  />
));
ToolbarButton.displayName = "ToolbarButton";
