import * as React from "react";
import * as SwitchPrimitive from "@radix-ui/react-switch";
import { cn } from "@/lib/utils";

/**
 * On/off track-and-thumb control.
 *
 * Same geometry and motion as the mobile app's `components/Switch.tsx` (the
 * profile screen's light/dark toggle, pulled out as a shared primitive) and
 * the desk panel's `<button role="switch">`: a 58×32 track, 3px padding, a
 * 26px thumb that travels 26px, 240ms ease-out. Built on
 * `@radix-ui/react-switch` — already pulled in transitively via this app's
 * `radix-ui` dependency, and the same pattern every other primitive here
 * follows (select, tabs, tooltip, label, separator each wrap an
 * `@radix-ui/react-*` package rather than a hand-rolled button), so it was a
 * one-line, zero-new-surface addition rather than a bespoke build.
 */
export const Switch = React.forwardRef<
  React.ElementRef<typeof SwitchPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof SwitchPrimitive.Root>
>(({ className, ...props }, ref) => (
  <SwitchPrimitive.Root
    ref={ref}
    className={cn(
      "peer inline-flex h-8 w-[58px] shrink-0 cursor-pointer items-center rounded-full border border-[var(--sd-line)] bg-[var(--sd-bg-soft)] p-[3px] transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40 disabled:cursor-not-allowed disabled:opacity-50 data-[state=checked]:bg-[var(--sd-accent-2)]",
      className,
    )}
    {...props}
  >
    <SwitchPrimitive.Thumb
      className={cn(
        "pointer-events-none block h-[26px] w-[26px] rounded-full bg-[var(--sd-card)] shadow-[0_1px_0_rgba(10,10,10,0.06),0_6px_16px_-10px_rgba(10,10,10,0.35)]",
        "translate-x-0 transition-transform duration-[240ms] ease-[cubic-bezier(0.2,0.8,0.2,1)] data-[state=checked]:translate-x-[26px]",
      )}
    />
  </SwitchPrimitive.Root>
));
Switch.displayName = SwitchPrimitive.Root.displayName;
