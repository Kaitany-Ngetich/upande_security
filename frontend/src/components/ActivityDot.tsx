/** A small dot in the operation's colour (Field Activity.color). Renders nothing without one. */
export function ActivityDot({ color, label, className = "" }: { color?: string | null; label?: string; className?: string }) {
  if (!color) return null;
  return (
    <span
      data-testid="activity-dot"
      title={label}
      aria-hidden="true"
      className={`mr-1.5 inline-block h-2.5 w-2.5 shrink-0 rounded-full align-middle ${className}`}
      style={{ background: color }}
    />
  );
}
