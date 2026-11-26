import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

/**
 * Re-read whatever this card is showing.
 *
 * A glyph, not a word. The button appears on every card that reads from the
 * server, and spelling out "Refresh" eight times down a page turns a quiet
 * control into a row of shouting; the circular arrow is understood without
 * being read. What it will refresh is in the tooltip, because a glyph alone
 * cannot say "the stores" or "the recordings".
 *
 * It spins while loading, which is the same information the word "Refreshing…"
 * carried, in the space the icon already occupies.
 */
export function RefreshButton({
  onClick,
  loading,
  label,
  className,
}: {
  onClick: () => void;
  loading?: boolean;
  /** What gets re-read, in the user's words — "the recordings", "the stores". */
  label: string;
  className?: string;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          onClick={onClick}
          disabled={loading}
          aria-label={loading ? `Re-reading ${label}…` : `Re-read ${label}`}
          className={cn(
            "h-9 w-9 shrink-0 rounded-full bg-[var(--sd-card)] text-[var(--sd-muted)] shadow-[var(--sd-shadow-1)] transition-all",
            "hover:-translate-y-px hover:text-[var(--sd-ink)] hover:shadow-[var(--sd-shadow-2)]",
            "disabled:translate-y-0 disabled:opacity-100 disabled:shadow-[var(--sd-shadow-1)]",
            className,
          )}
        >
          <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
        </Button>
      </TooltipTrigger>
      <TooltipContent>
        {loading ? `Re-reading ${label}…` : `Re-read ${label}`}
      </TooltipContent>
    </Tooltip>
  );
}
