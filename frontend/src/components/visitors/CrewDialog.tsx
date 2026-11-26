import { useCallback, useEffect, useState } from "react";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { crewFor, issueCrewBadges, returnBadge, type Crew } from "@/lib/gate-api";
import { isError } from "@/lib/frappe";
import { useScope } from "@/lib/scope";
import type { Visit } from "@/lib/visitors-api";

/**
 * A contractor visit's crew and the pool badges they hold. Where the company
 * keeps a contractor badge pool, every crew member needs a badge before the
 * visit can be checked in; the badge is then what they are tracked by at every
 * gate of the company.
 */
export function CrewDialog({ visit, onClose, onChanged }: { visit: Visit | null; onClose: () => void; onChanged: () => void }) {
  const toast = useToast();
  const { boot } = useScope();
  const [crew, setCrew] = useState<Crew | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!visit) return;
    const r = await crewFor(visit.name);
    if (isError(r)) {
      toast(r.error, "error");
      return;
    }
    setCrew(r as Crew);
  }, [visit, toast]);

  useEffect(() => {
    setCrew(null);
    void load();
  }, [load]);

  const held = new Map((crew?.badges ?? []).map((b) => [b.holder_name.toLowerCase(), b]));
  const missing = (crew?.crew ?? []).filter((c) => !held.has(c.full_name.toLowerCase())).length;

  const issue = async () => {
    if (!visit) return;
    setBusy(true);
    const r = await issueCrewBadges(visit.name);
    setBusy(false);
    if (isError(r)) return void toast(r.error, "error");
    const n = r.issued.length;
    toast(
      n ? `Issued ${n} badge${n === 1 ? "" : "s"}.` : "No badges issued.",
      r.still_needed ? "warn" : "ok",
      { hint: r.still_needed ? `${r.still_needed} still without a badge: the pool is empty.` : r.issued.map((b) => `${b.holder_name} #${b.badge_number}`).join(", ") },
    );
    void load();
    onChanged();
  };

  const giveBack = async (badge: string, holder: string) => {
    if (!confirm(`Return ${holder}'s badge to the pool?`)) return;
    setBusy(true);
    const r = await returnBadge(badge);
    setBusy(false);
    if (isError(r)) return void toast(r.error, "error");
    toast(`${holder}'s badge is back in the pool.`, "ok");
    void load();
    onChanged();
  };

  return (
    <Dialog open={!!visit} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>Crew &amp; badges</DialogTitle>
          <DialogDescription>
            {visit?.customer_name}
            {crew?.valid_until ? ` · badges valid until ${crew.valid_until}` : ""}
            {crew && !crew.required ? " · this company keeps no contractor badge pool" : ""}
          </DialogDescription>
        </DialogHeader>
        {!crew ? (
          <p className="text-[13px] text-[var(--sd-muted)]">Loading…</p>
        ) : (
          <table className="w-full text-[13px]">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-[0.08em] text-[var(--sd-quiet)]">
                <th className="py-2 font-medium">Name</th>
                <th className="py-2 font-medium">ID</th>
                <th className="py-2 font-medium">Badge</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {crew.crew.map((c) => {
                const b = held.get(c.full_name.toLowerCase());
                return (
                  <tr key={c.full_name} className="border-t border-[var(--sd-line-soft)]">
                    <td className="py-2">{c.full_name}{c.is_team_leader ? <span className="ml-1 text-[11px] text-[var(--sd-quiet)]">lead</span> : null}</td>
                    <td className="py-2 text-[var(--sd-muted)]">{c.id_number || "—"}</td>
                    <td className="py-2">{b ? `#${b.badge_number}` : <span className="text-[var(--sd-data-red)]">{crew.required ? "None yet" : "—"}</span>}</td>
                    <td className="py-2 text-right">
                      {b && boot.can_check_in_out && (
                        <Button size="sm" variant="outline" disabled={busy} onClick={() => giveBack(b.badge, c.full_name)}>Return</Button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
        <div className="flex items-center justify-between gap-2">
          <span className="text-[12px] text-[var(--sd-quiet)]">{crew?.required ? `${crew.available} badge${crew.available === 1 ? "" : "s"} free in the pool` : ""}</span>
          <div className="flex gap-2">
            <Button variant="outline" onClick={onClose}>Close</Button>
            {crew?.required && missing > 0 && boot.can_check_in_out && (
              <Button onClick={issue} disabled={busy}>{busy ? "Issuing…" : `Issue ${missing} badge${missing === 1 ? "" : "s"}`}</Button>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
