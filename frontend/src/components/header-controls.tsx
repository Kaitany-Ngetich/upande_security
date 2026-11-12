import * as React from "react";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

/**
 * Shared header control styling so every page's header reads identically to
 * the dashboard's: pill-shaped dropdowns and circular icon-only buttons.
 *
 * `HEADER_PILL` is the trigger className for header dropdowns (Select or
 * Popover triggers). `HeaderIconButton` is the circular icon button used for
 * refresh / thresholds / any single-glyph header action.
 */
export const HEADER_PILL =
  "h-9 w-auto min-w-[7rem] gap-2 rounded-full border-transparent bg-card px-4 text-xs font-medium shadow-[var(--sd-shadow-1)] hover:shadow-[var(--sd-shadow-2)] focus:ring-0";

export const HeaderIconButton = React.forwardRef<
  HTMLButtonElement,
  React.ComponentProps<typeof Button> & {
    active?: boolean;
    /**
     * A sentence describing what the button does, shown on hover and on
     * keyboard focus. A round button holding one glyph tells the operator
     * nothing about itself; `title` is the browser's own tooltip, which is
     * slow, unstyled and never appears on touch, so the glyph stays a guess.
     * Give this wherever the icon alone is not obvious — refresh, thresholds,
     * exports. The accessible NAME still comes from `aria-label`: this is the
     * description, not the label.
     */
    tooltip?: React.ReactNode;
  }
>(({ className, active, tooltip, ...props }, ref) => {
  const button = (
    <Button
      ref={ref}
      type="button"
      variant="ghost"
      size="icon"
      aria-pressed={active}
      className={cn(
        "h-9 w-9 shrink-0 rounded-full bg-card text-[var(--sd-muted)] shadow-[var(--sd-shadow-1)] transition-all hover:-translate-y-px hover:text-foreground hover:shadow-[var(--sd-shadow-2)]",
        active &&
          "bg-primary text-primary-foreground hover:bg-primary hover:text-primary-foreground",
        className,
      )}
      {...props}
    />
  );

  if (!tooltip) return button;

  // The provider lives here rather than at the app root so a caller can drop
  // one of these into any page without remembering to wrap it. Nesting
  // providers is allowed; the outer one wins where there is one.
  return (
    <TooltipProvider delayDuration={200}>
      <Tooltip>
        <TooltipTrigger asChild>{button}</TooltipTrigger>
        <TooltipContent>{tooltip}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
});
HeaderIconButton.displayName = "HeaderIconButton";
