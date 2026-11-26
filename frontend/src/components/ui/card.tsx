import * as React from "react";
import { cn } from "@/lib/utils";

export const Card = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn(
      // Reference .card: 20px radius, warm-paper soft layered shadow.
      // Static (no hover-lift) so large panels don't jump; the lift is
      // reserved for interactive KPI/tile cards per the reference.
      "rounded-[var(--sd-radius-card)] border bg-card text-card-foreground shadow-[var(--sd-shadow-1)]",
      className,
    )}
    {...props}
  />
));
Card.displayName = "Card";

export const CardHeader = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn("flex flex-col gap-1 p-5", className)}
    {...props}
  />
));
CardHeader.displayName = "CardHeader";

export const CardTitle = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    data-card-title=""
    className={cn(
      // Reference .card__head h3: ~17px / 600, tight tracking.
      "text-[17px] font-semibold leading-tight tracking-tight",
      className,
    )}
    {...props}
  />
));
CardTitle.displayName = "CardTitle";

export const CardDescription = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn(
      // Sentence case, not uppercase. These carry whole sentences — "Net is
      // what was sellable — total yield less anything discarded" — and a
      // sentence set in tracked capitals is read letter by letter. Caps belong
      // on the two-word labels above a figure, not on prose.
      "text-[12.5px] leading-relaxed text-[var(--sd-muted)]",
      className,
    )}
    {...props}
  />
));
CardDescription.displayName = "CardDescription";

export const CardContent = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div ref={ref} className={cn("p-5 pt-0", className)} {...props} />
));
CardContent.displayName = "CardContent";

export const CardFooter = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn("flex items-center p-5 pt-0", className)}
    {...props}
  />
));
CardFooter.displayName = "CardFooter";

/**
 * The controls that belong to a card — refresh, a filter, a window picker.
 *
 * They sit at the TOP RIGHT of the card head, on the title's own line, so the
 * eye meets the card's name and its controls in one pass instead of reading
 * past a stack of dropdowns to find out what it is looking at. Wrap the title
 * and description in CardHeading beside it.
 */
export const CardTools = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn("flex shrink-0 flex-wrap items-center justify-end gap-2", className)}
    {...props}
  />
));
CardTools.displayName = "CardTools";

/** The title/description column that sits opposite CardTools. */
export const CardHeading = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div ref={ref} className={cn("flex min-w-0 flex-col gap-1", className)} {...props} />
));
CardHeading.displayName = "CardHeading";

/** A card head with its tools pinned top-right. */
export const CardHeaderRow = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn(
      "flex flex-col gap-3 p-5 sm:flex-row sm:items-start sm:justify-between sm:gap-6",
      className,
    )}
    {...props}
  />
));
CardHeaderRow.displayName = "CardHeaderRow";
