import { useState } from "react";
import { Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

/**
 * Type or scan a reference. A USB/Bluetooth scanner types the code and presses
 * Enter, so the box looks it up on Enter as well as on the button.
 */
export function LookupBox({ label, placeholder, busy, onLookup, autoFocus = true }: {
  label: string; placeholder: string; busy: boolean; onLookup: (ref: string) => void; autoFocus?: boolean;
}) {
  const [ref, setRef] = useState("");
  const go = () => ref.trim() && onLookup(ref.trim());
  return (
    <form
      className="flex flex-wrap items-center gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        go();
      }}
    >
      <Input
        aria-label={label}
        autoFocus={autoFocus}
        className="h-10 min-w-[16rem] flex-1"
        placeholder={placeholder}
        value={ref}
        onChange={(e) => setRef(e.target.value)}
      />
      <Button type="submit" disabled={busy || !ref.trim()} className="h-10">
        <Search className="mr-1 h-4 w-4" /> {busy ? "Looking up…" : "Look up"}
      </Button>
    </form>
  );
}
