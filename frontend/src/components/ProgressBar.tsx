import { cn } from "@/lib/utils";
import "./ProgressBar.css";

export interface ProgressBarProps {
  /** 0–100. Pass `null` when there is no real figure — see below. */
  percent: number | null;
  /** What is happening, e.g. "loading disease rows". */
  label?: string;
  /** Optional secondary count, e.g. "3 of 14 weeks". */
  detail?: string;
  className?: string;
}

/**
 * The app's one loader: a status bar that fills left to right.
 *
 * **`percent: null` means indeterminate, and that is a deliberate mode rather than
 * a missing value.** The previous loaders eased a simulated percentage toward 92%
 * whenever the real channel was silent, which meant the number on screen was
 * frequently invented — a page could sit at "78%" having loaded nothing. A bar with
 * no figure and a travelling highlight says "working" honestly; a made-up number
 * says something false about the work.
 *
 * Themed off the same ink gradient as the active sidebar pill (`--sd-grad-ink`), so
 * it reads as part of the app rather than a browser affordance.
 */
export function ProgressBar({
  percent,
  label,
  detail,
  className,
}: ProgressBarProps) {
  const determinate = percent !== null && Number.isFinite(percent);
  const pct = determinate ? Math.max(0, Math.min(100, percent as number)) : 0;

  return (
    <div
      className={cn("scp-progress", className)}
      role="progressbar"
      aria-valuenow={determinate ? Math.round(pct) : undefined}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuetext={determinate ? undefined : "Loading"}
      aria-label={label || "Loading"}
    >
      <div className="scp-progress__track">
        <div
          className={cn(
            "scp-progress__fill",
            !determinate && "scp-progress__fill--indeterminate",
          )}
          // Width is the only thing that animates, so the fill can be
          // transitioned smoothly without the label jittering with it.
          style={determinate ? { width: `${pct}%` } : undefined}
        />
      </div>
      {(label || detail || determinate) && (
        <div className="scp-progress__meta">
          <span className="scp-progress__label">{label || "Loading"}</span>
          <span className="scp-progress__figure">
            {detail ? <span className="scp-progress__detail">{detail}</span> : null}
            {determinate ? <span>{Math.round(pct)}%</span> : null}
          </span>
        </div>
      )}
    </div>
  );
}

export default ProgressBar;
