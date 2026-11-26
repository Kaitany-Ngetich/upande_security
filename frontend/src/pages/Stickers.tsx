import { useCallback, useEffect, useState } from "react";
import { Printer } from "lucide-react";
import { Card, TD, TH, Verdict } from "@/components/Card";
import { FeatureOff } from "@/components/FeatureOff";
import { TableRowsSkeleton } from "@/components/Loading";
import { PageShell } from "@/components/PageShell";
import { Pager } from "@/components/Pager";
import { RefreshButton } from "@/components/RefreshButton";
import { ScrollTable, STICKY_HEAD } from "@/components/ScrollTable";
import { SearchInput } from "@/components/SearchInput";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { isError } from "@/lib/frappe";
import {
  approveRequest, rejectRequest, setStickerStatus, stickerBoard, stickerRequests,
  type Sticker, type StickerRequest, type StickerStatus,
} from "@/lib/registers-api";
import { useScope } from "@/lib/scope";
import { cn } from "@/lib/utils";
import { when } from "@/lib/when";

const PAGE = 50;
const printUrl = (name: string) =>
  `/printview?doctype=${encodeURIComponent("Staff Vehicle Sticker")}&name=${encodeURIComponent(name)}&format=${encodeURIComponent("Staff Vehicle Sticker Card")}&trigger_print=1`;

function Pill({ active, n, alert, children, onClick }: { active: boolean; n?: number; alert?: boolean; children: React.ReactNode; onClick: () => void }) {
  return (
    <button
      role="tab" aria-selected={active} onClick={onClick}
      className={cn("flex h-9 items-center gap-2 rounded-full px-3.5 text-[13px] font-medium transition-colors",
        active ? "bg-[var(--sd-ink)] text-white" : "bg-[var(--sd-card)] text-[var(--sd-muted)] shadow-[var(--sd-shadow-1)] hover:text-[var(--sd-ink)]")}
    >
      {children}
      {n != null && <span className={cn("min-w-5 rounded-full px-1.5 text-center text-[11px] font-semibold tabular-nums", active ? "bg-white/20" : alert && n > 0 ? "bg-[var(--sd-data-red)] text-white" : "bg-[var(--sd-line-soft)]")}>{n}</span>}
    </button>
  );
}

/** Staff vehicle stickers: the requests to approve, and every sticker issued. */
export function Stickers() {
  const toast = useToast();
  const { boot, scope } = useScope();
  const [tab, setTab] = useState<"requests" | StickerStatus | "">("requests");
  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");
  const [start, setStart] = useState(0);
  const [requests, setRequests] = useState<StickerRequest[] | null>(null);
  const [board, setBoard] = useState<Awaited<ReturnType<typeof stickerBoard>> | null>(null);
  const [loading, setLoading] = useState(true);
  const [rejecting, setRejecting] = useState<StickerRequest | null>(null);
  const [busy, setBusy] = useState("");

  useEffect(() => {
    const t = window.setTimeout(() => setDebounced(search.trim()), 300);
    return () => window.clearTimeout(t);
  }, [search]);
  useEffect(() => setStart(0), [tab, debounced, scope.company]);

  const load = useCallback(async () => {
    setLoading(true);
    const [q, b] = await Promise.all([
      stickerRequests("Pending"),
      stickerBoard({ company: scope.company || undefined, status: tab === "requests" ? undefined : tab || undefined, search: debounced || undefined, start }),
    ]);
    setLoading(false);
    if (isError(q)) toast(q.error, "error");
    else setRequests(Array.isArray(q) ? q : []);
    if (isError(b)) toast(b.error, "error");
    else setBoard(b);
  }, [tab, debounced, start, scope.company, toast]);
  useEffect(() => {
    void load();
  }, [load]);

  if (boot.features.feature_vehicle_stickers === false) return <FeatureOff title="Vehicle stickers" what="Staff vehicle stickers" />;

  const approve = async (r: StickerRequest) => {
    setBusy(r.name);
    const res = await approveRequest(r.name);
    setBusy("");
    if (isError(res)) return void toast(res.error, "error");
    toast(`Sticker ${res.sticker} issued to ${r.employee_name}.`, "ok", { hint: "Print it from the sticker list." });
    void load();
  };
  const changeStatus = async (s: Sticker, status: StickerStatus) => {
    setBusy(s.name);
    const res = await setStickerStatus(s.name, status);
    setBusy("");
    if (isError(res)) return void toast(res.error, "error");
    toast(res.status === status ? `${s.plate_number}: ${status.toLowerCase()}.` : `${s.plate_number} is ${res.status}: a sticker with no holder cannot be active.`, res.status === status ? "ok" : "warn");
    void load();
  };

  const c = board && !isError(board) ? board.counts : null;
  const rows = board && !isError(board) ? board.rows : [];
  const manage = !!(board && !isError(board) && board.can_manage);
  const q = (requests ?? []).filter((r) => !debounced || `${r.employee_name} ${r.employee} ${r.plate_number}`.toLowerCase().includes(debounced.toLowerCase()));

  return (
    <PageShell
      title="Vehicle stickers"
      eyebrow="Gate operations"
      tabs={
        <div role="tablist" aria-label="Stickers" className="flex flex-wrap gap-1.5">
          <Pill active={tab === "requests"} n={requests?.length} alert onClick={() => setTab("requests")}>Requests</Pill>
          {(["Active", "Unassigned", "Suspended", "Lost"] as StickerStatus[]).map((s) => (
            <Pill key={s} active={tab === s} n={c?.[s]} onClick={() => setTab(s)}>{s}</Pill>
          ))}
          <Pill active={tab === ""} onClick={() => setTab("")}>All</Pill>
        </div>
      }
      actions={
        <>
          <SearchInput value={search} onChange={setSearch} placeholder="Name, staff ID, plate" aria-label="Search stickers" />
          <RefreshButton onClick={() => void load()} loading={loading} label="Refresh stickers" />
        </>
      }
      description={tab === "requests" ? "Staff ask for a sticker on the Request a Sticker page; approving issues the next sticker number for their company and emails them." : undefined}
    >
      {tab === "requests" ? (
        <Card>
          <ScrollTable tall>
            <table className="w-full text-[13px]">
              <thead className={STICKY_HEAD}><tr><th className={TH}>Asked</th><th className={TH}>Staff member</th><th className={TH}>Vehicle</th><th className={TH}>Collect at</th><th className={TH} /></tr></thead>
              <tbody>
                {requests === null ? <TableRowsSkeleton cols={5} rows={4} /> : q.length === 0 ? (
                  <tr><td colSpan={5} className="px-4 py-10 text-center text-[var(--sd-muted)]">No requests waiting.</td></tr>
                ) : q.map((r) => (
                  <tr key={r.name} className="border-t border-[var(--sd-line-soft)]">
                    <td className={`${TD} tabular-nums`}>{when(r.creation)}</td>
                    <td className={TD}>{r.employee_name}<div className="text-[12px] text-[var(--sd-quiet)]">{r.employee}</div></td>
                    <td className={TD}>{r.plate_number}<div className="text-[12px] text-[var(--sd-quiet)]">{[r.vehicle_type, r.color].filter(Boolean).join(" · ")}</div></td>
                    <td className={TD}>{r.collection_farm}<div className="text-[12px] text-[var(--sd-quiet)]">{r.collection_point}</div></td>
                    <td className={`${TD} text-right`}>
                      <span className="flex justify-end gap-1.5">
                        <Button size="sm" variant="outline" className="text-[var(--sd-data-red)]" disabled={!!busy} onClick={() => setRejecting(r)}>Reject</Button>
                        <Button size="sm" disabled={!!busy} onClick={() => approve(r)}>{busy === r.name ? "Issuing…" : "Approve"}</Button>
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </ScrollTable>
          <div className="h-2" />
        </Card>
      ) : (
        <Card>
          <ScrollTable tall>
            <table className="w-full text-[13px]">
              <thead className={STICKY_HEAD}><tr><th className={TH}>Sticker</th><th className={TH}>Holder</th><th className={TH}>Vehicle</th><th className={TH}>Status</th><th className={TH} /></tr></thead>
              <tbody>
                {loading && !board ? <TableRowsSkeleton cols={5} rows={5} /> : rows.length === 0 ? (
                  <tr><td colSpan={5} className="px-4 py-10 text-center text-[var(--sd-muted)]">No stickers here.</td></tr>
                ) : rows.map((s) => (
                  <tr key={s.name} className={cn("border-t border-[var(--sd-line-soft)]", loading && "opacity-60")}>
                    <td className={TD}><span className="font-semibold tabular-nums">#{s.sticker_number}</span><div className="text-[12px] text-[var(--sd-quiet)]">{s.company}</div></td>
                    <td className={TD}>{s.employee_name || <span className="text-[var(--sd-quiet)]">Nobody</span>}{s.employee && <div className="text-[12px] text-[var(--sd-quiet)]">{s.employee}</div>}</td>
                    <td className={TD}>{s.plate_number}<div className="text-[12px] text-[var(--sd-quiet)]">{[s.vehicle_type, s.color].filter(Boolean).join(" · ")}</div></td>
                    <td className={TD}><Verdict ok={s.status === "Active" ? true : s.status === "Unassigned" ? null : false}>{s.status}</Verdict></td>
                    <td className={`${TD} text-right`}>
                      <span className="flex flex-wrap justify-end gap-1.5">
                        <a href={printUrl(s.name)} target="_blank" rel="noreferrer" className="inline-flex h-8 items-center gap-1 rounded-md border border-[var(--sd-line)] px-2.5 text-[12px] hover:bg-[var(--sd-line-soft)]"><Printer className="h-3.5 w-3.5" /> Print</a>
                        {manage && s.status === "Active" && <Button size="sm" variant="outline" disabled={!!busy} onClick={() => changeStatus(s, "Suspended")}>Suspend</Button>}
                        {manage && s.status !== "Lost" && <Button size="sm" variant="outline" disabled={!!busy} onClick={() => changeStatus(s, "Lost")}>Lost</Button>}
                        {manage && (s.status === "Suspended" || s.status === "Lost") && <Button size="sm" variant="outline" disabled={!!busy} onClick={() => changeStatus(s, "Active")}>Reactivate</Button>}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </ScrollTable>
          <Pager start={start} total={board && !isError(board) ? board.total : 0} page={PAGE} loading={loading} onChange={setStart} />
        </Card>
      )}
      <RejectDialog req={rejecting} onClose={() => setRejecting(null)} onDone={load} />
    </PageShell>
  );
}

function RejectDialog({ req, onClose, onDone }: { req: StickerRequest | null; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => setNotes(""), [req]);
  const go = async () => {
    if (!req) return;
    if (!notes.trim()) return void toast("Say why, so the staff member knows.", "warn");
    setBusy(true);
    const r = await rejectRequest(req.name, notes.trim());
    setBusy(false);
    if (isError(r)) return void toast(r.error, "error");
    toast(`${req.employee_name}'s request rejected.`, "ok");
    onClose();
    onDone();
  };
  return (
    <Dialog open={!!req} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Reject {req?.employee_name}'s request</DialogTitle>
          <DialogDescription>{req ? `${req.vehicle_type} ${req.plate_number}` : ""}</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-1.5"><Label htmlFor="rj-notes">Reason</Label><Textarea id="rj-notes" rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} /></div>
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button variant="destructive" onClick={go} disabled={busy}>{busy ? "Saving…" : "Reject"}</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
