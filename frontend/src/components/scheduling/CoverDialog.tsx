import { useEffect, useState } from "react";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { isError, type Envelope } from "@/lib/frappe";
import { suggestRelievers, toggleDay, type DayCell, type Relievers } from "@/lib/scheduling-api";
import { cn } from "@/lib/utils";

/**
 * A guard's day off and who covers it. The candidates come ranked from
 * suggest_relievers (who covered before, the designated reliever, who knows
 * the farm and shift); booking re-checks they are still free.
 */
export function CoverDialog({ target, onClose, onDone, book: bookWith }: {
  /** The guard, the day, and (optional) the farm and shift to cover. */
  target: { guard: string; guard_name: string; date: string; farm?: string; shift_type?: string } | null;
  onClose: () => void;
  onDone: () => void;
  /** How the day off is booked; the schedule's toggle_guard_day unless given
   *  (a rotation plan books through its own preview row). */
  book?: (cover: string) => Promise<Envelope<DayCell>>;
}) {
  const toast = useToast();
  const [data, setData] = useState<Relievers | null>(null);
  const [pick, setPick] = useState("");
  const [showAll, setShowAll] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setData(null);
    setPick("");
    setShowAll(false);
    if (!target) return;
    void suggestRelievers({ guard: target.guard, date: target.date, farm: target.farm, shift_type: target.shift_type }).then((r) => {
      if (isError(r)) return void toast(r.error, "error");
      setData(r);
      setPick(r.suggestions.find((s) => s.available)?.guard ?? "");
    });
  }, [target, toast]);

  // toggle_guard_day reads a MISSING cover as "the designated reliever", so
  // leaving the day uncovered has to say so: "none".
  const book = async (cover: string) => {
    if (!target) return;
    setBusy(true);
    const r = bookWith
      ? await bookWith(cover)
      : await toggleDay({ guard: target.guard, date: target.date, mark_off: 1, farm: target.farm, shift_type: target.shift_type, cover_guard: cover });
    setBusy(false);
    if (isError(r)) return void toast(r.error, "error");
    if (r.state === "off_covered") toast(`${target.guard_name} is off; ${r.covered_by_name} covers.`, "ok");
    else toast(`${target.guard_name} is off, without cover.`, "warn", { hint: r.reason });
    onClose();
    onDone();
  };

  const list = (data?.suggestions ?? []).filter((s) => showAll || s.shortlist || s.guard === pick);

  return (
    <Dialog open={!!target} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>Day off for {target?.guard_name}</DialogTitle>
          <DialogDescription>
            {target?.date}
            {data
              ? ` · ${data.shift_type} shift ${data.start_time}–${data.end_time}${data.farm ? ` at ${data.farm}` : ""} · ${data.counts.available} of ${data.counts.candidates} guards free`
              : " · finding who is free…"}
          </DialogDescription>
        </DialogHeader>
        {data && (
          <div className="flex max-h-[50vh] flex-col gap-1 overflow-auto">
            {list.length === 0 && <p className="text-[13px] text-[var(--sd-muted)]">No guard is free for this shift.</p>}
            {list.map((s) => (
              <label
                key={s.guard}
                className={cn("flex cursor-pointer items-start gap-2 rounded-md px-2 py-1.5 text-[13px]", pick === s.guard && "bg-[var(--sd-line-soft)]", !s.available && "cursor-not-allowed opacity-55")}
              >
                <input type="radio" name="cover" className="mt-1" disabled={!s.available} checked={pick === s.guard} onChange={() => setPick(s.guard)} />
                <span className="flex-1">
                  <span className="font-medium">{s.full_name}</span>
                  {s.designated ? <span className="ml-1.5 text-[11px] text-[var(--sd-quiet)]">designated reliever</span> : null}
                  {s.on_off_day ? <span className="ml-1.5 text-[11px] text-[var(--sd-target)]">on their own day off</span> : null}
                  <span className="block text-[12px] text-[var(--sd-muted)]">{s.available ? s.reason : s.busy_reason}</span>
                </span>
              </label>
            ))}
            {!showAll && data.suggestions.length > list.length && (
              <button type="button" className="self-start px-2 text-[12px] underline" onClick={() => setShowAll(true)}>
                Show all {data.suggestions.length} guards
              </button>
            )}
          </div>
        )}
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="outline" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button variant="outline" onClick={() => book("none")} disabled={busy || !data}>Off, no cover</Button>
          <Button onClick={() => pick && book(pick)} disabled={busy || !pick}>{busy ? "Booking…" : "Off, with this cover"}</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
