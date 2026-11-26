import { useCallback, useEffect, useState } from "react";
import { EyeOff, Plus } from "lucide-react";
import { Card, TD, TH, Verdict } from "@/components/Card";
import { EmployeePicker } from "@/components/EmployeePicker";
import { FeatureOff } from "@/components/FeatureOff";
import { TableRowsSkeleton } from "@/components/Loading";
import { PageShell } from "@/components/PageShell";
import { Pager } from "@/components/Pager";
import { RefreshButton } from "@/components/RefreshButton";
import { ScrollTable, STICKY_HEAD } from "@/components/ScrollTable";
import { SearchInput } from "@/components/SearchInput";
import { useToast } from "@/components/Toast";
import { ToolbarButton } from "@/components/ToolbarButton";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Picker } from "@/components/ui/picker";
import { Textarea } from "@/components/ui/textarea";
import { isError } from "@/lib/frappe";
import { saveWatchEntry, watchlistActivity, watchlistBoard, type WatchActivity, type WatchEntry } from "@/lib/registers-api";
import { useScope } from "@/lib/scope";
import { cn } from "@/lib/utils";
import { when } from "@/lib/when";

const PAGE = 50;
const TYPES = ["Visitor", "Contractor", "Employee", "Supplier / Driver", "External"];

function Activity({ a }: { a: WatchActivity }) {
  return (
    <span>
      <span className="font-medium">{a.activity_type}</span>
      <span className="text-[var(--sd-quiet)]">{[a.farm, a.gate, a.matched_on && `matched on ${a.matched_on}`].filter(Boolean).map((x) => ` · ${x}`).join("")}</span>
    </span>
  );
}

/**
 * The covert watchlist. Guards never see any sign of it; every gate record that
 * identifies a watched person is logged here and the Security Heads are told.
 */
export function Watchlist() {
  const toast = useToast();
  const { boot } = useScope();
  const [status, setStatus] = useState<"Active" | "Inactive">("Active");
  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");
  const [start, setStart] = useState(0);
  const [data, setData] = useState<Awaited<ReturnType<typeof watchlistBoard>> | null>(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<WatchEntry | "new" | null>(null);
  const [open, setOpen] = useState<WatchEntry | null>(null);

  useEffect(() => {
    const t = window.setTimeout(() => setDebounced(search.trim()), 300);
    return () => window.clearTimeout(t);
  }, [search]);
  useEffect(() => setStart(0), [status, debounced]);

  const load = useCallback(async () => {
    setLoading(true);
    const r = await watchlistBoard({ status, search: debounced || undefined, start });
    setLoading(false);
    if (isError(r)) return void toast(r.error, "error");
    setData(r);
  }, [status, debounced, start, toast]);
  useEffect(() => {
    void load();
  }, [load]);

  if (boot.features.feature_watchlist === false) return <FeatureOff title="Watchlist" what="The watchlist" />;
  const d = data && !isError(data) ? data : null;

  return (
    <PageShell
      title="Watchlist"
      eyebrow="Security"
      tabs={
        <div role="tablist" className="flex gap-1.5">
          {(["Active", "Inactive"] as const).map((s) => (
            <button key={s} role="tab" aria-selected={status === s} onClick={() => setStatus(s)}
              className={cn("flex h-9 items-center gap-2 rounded-full px-3.5 text-[13px] font-medium",
                status === s ? "bg-[var(--sd-ink)] text-white" : "bg-[var(--sd-card)] text-[var(--sd-muted)] shadow-[var(--sd-shadow-1)]")}>
              {s === "Active" ? "Being watched" : "Closed"}
              {d && <span className={cn("min-w-5 rounded-full px-1.5 text-center text-[11px] font-semibold tabular-nums", status === s ? "bg-white/20" : "bg-[var(--sd-line-soft)]")}>{d.counts[s]}</span>}
            </button>
          ))}
        </div>
      }
      actions={
        <>
          <SearchInput value={search} onChange={setSearch} placeholder="Name, ID, phone, plate" aria-label="Search watchlist" />
          <RefreshButton onClick={() => void load()} loading={loading} label="Refresh watchlist" />
          <ToolbarButton onClick={() => setEditing("new")}><Plus className="h-4 w-4" /> Watch someone</ToolbarButton>
        </>
      }
    >
      <p className="flex items-center gap-2 text-[12px] text-[var(--sd-quiet)]">
        <EyeOff className="h-3.5 w-3.5" /> Confidential: only Security Heads and System Managers see this page. Guards are never told someone is watched.
      </p>
      <div className="grid gap-6 lg:grid-cols-[2fr_1fr]">
        <Card>
          <ScrollTable tall>
            <table className="w-full text-[13px]">
              <thead className={STICKY_HEAD}><tr><th className={TH}>Person</th><th className={TH}>Watching for</th><th className={TH}>Seen</th><th className={TH}>Reason</th></tr></thead>
              <tbody>
                {!d ? <TableRowsSkeleton cols={4} rows={5} /> : d.rows.length === 0 ? (
                  <tr><td colSpan={4} className="px-4 py-10 text-center text-[var(--sd-muted)]">{status === "Active" ? "Nobody is being watched." : "No closed entries."}</td></tr>
                ) : d.rows.map((w) => (
                  <tr key={w.name} tabIndex={0} onClick={() => setOpen(w)} onKeyDown={(e) => e.key === "Enter" && setOpen(w)} className="cursor-pointer border-t border-[var(--sd-line-soft)] align-top hover:bg-[var(--sd-line-soft)]/50">
                    <td className={TD}>{w.full_name}<div className="text-[12px] text-[var(--sd-quiet)]">{[w.person_type, w.employee, w.restrict_to_company && `only ${w.restrict_to_company}`].filter(Boolean).join(" · ")}</div></td>
                    <td className={`${TD} text-[12px]`}>{[w.id_number && `ID ${w.id_number}`, w.phone_number, w.vehicle_plate].filter(Boolean).join(" · ") || "Name only"}</td>
                    <td className={`${TD} tabular-nums`}>{w.activity_count ? <><span className="font-semibold">{w.activity_count}×</span><div className="text-[12px] text-[var(--sd-quiet)]">last {when(w.last_activity_on)}</div></> : <span className="text-[var(--sd-quiet)]">Not yet</span>}</td>
                    <td className={`${TD} text-[12px] text-[var(--sd-muted)]`}><span className="line-clamp-2">{w.reason || "—"}</span>{w.incident && <div>Incident {w.incident}</div>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </ScrollTable>
          <Pager start={start} total={d?.total ?? 0} page={PAGE} loading={loading} onChange={setStart} />
        </Card>
        <Card title="Latest sightings">
          <div className="flex flex-col gap-2 px-4 pb-4 pt-3 text-[13px]">
            {!d?.recent.length ? <p className="text-[var(--sd-muted)]">Nothing logged yet.</p> : d.recent.map((a) => (
              <div key={a.name} className="border-b border-[var(--sd-line-soft)] pb-2 last:border-0">
                <div className="flex justify-between gap-2"><span className="font-medium">{a.person}</span><span className="tabular-nums text-[12px] text-[var(--sd-quiet)]">{when(a.occurred_at)}</span></div>
                <div className="text-[12px]"><Activity a={a} /></div>
              </div>
            ))}
          </div>
        </Card>
      </div>

      {editing && <WatchForm entry={editing === "new" ? null : editing} onClose={() => setEditing(null)} onSaved={load} />}
      <WatchDialog entry={open} onClose={() => setOpen(null)} onEdit={(w) => { setOpen(null); setEditing(w); }} />
    </PageShell>
  );
}

function WatchDialog({ entry, onClose, onEdit }: { entry: WatchEntry | null; onClose: () => void; onEdit: (w: WatchEntry) => void }) {
  const toast = useToast();
  const [rows, setRows] = useState<WatchActivity[] | null>(null);
  useEffect(() => {
    setRows(null);
    if (!entry) return;
    void watchlistActivity(entry.name).then((r) => (isError(r) ? toast(r.error, "error") : setRows(r.rows)));
  }, [entry, toast]);
  return (
    <Dialog open={!!entry} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">{entry?.full_name} {entry && <Verdict ok={entry.status === "Inactive" ? null : false}>{entry.status === "Active" ? "Watched" : "Closed"}</Verdict>}</DialogTitle>
          <DialogDescription>
            {entry ? `Added by ${entry.added_by} ${when(entry.added_on)}${entry.closed_on ? ` · closed ${when(entry.closed_on)}${entry.closure_notes ? `: ${entry.closure_notes}` : ""}` : ""}` : ""}
          </DialogDescription>
        </DialogHeader>
        {entry?.reason && <p className="whitespace-pre-wrap text-[13px]">{entry.reason}</p>}
        <div className="max-h-[50vh] overflow-auto">
          <table className="w-full text-[13px]">
            <thead className={STICKY_HEAD}><tr><th className={TH}>When</th><th className={TH}>What</th><th className={TH}>Record</th></tr></thead>
            <tbody>
              {rows === null ? <TableRowsSkeleton cols={3} rows={3} /> : rows.length === 0 ? (
                <tr><td colSpan={3} className="px-4 py-6 text-center text-[var(--sd-muted)]">Not seen at any gate yet.</td></tr>
              ) : rows.map((a) => (
                <tr key={a.name} className="border-t border-[var(--sd-line-soft)]">
                  <td className={`${TD} tabular-nums`}>{when(a.occurred_at)}</td>
                  <td className={TD}><Activity a={a} />{a.details && <div className="text-[12px] text-[var(--sd-muted)]">{a.details}</div>}</td>
                  <td className={TD}>{a.reference_name ? <a className="underline" href={`/app/${(a.reference_doctype || "").toLowerCase().replace(/ /g, "-")}/${encodeURIComponent(a.reference_name)}`}>{a.reference_name}</a> : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>Close</Button>
          {entry && <Button onClick={() => onEdit(entry)}>{entry.status === "Active" ? "Edit or close" : "Edit or reopen"}</Button>}
        </div>
      </DialogContent>
    </Dialog>
  );
}

function WatchForm({ entry, onClose, onSaved }: { entry: WatchEntry | null; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const { boot } = useScope();
  const [f, setF] = useState({
    full_name: entry?.full_name ?? "", person_type: entry?.person_type ?? "", employee: entry?.employee ?? "", id_number: entry?.id_number ?? "",
    phone_number: entry?.phone_number ?? "", vehicle_plate: entry?.vehicle_plate ?? "", reason: entry?.reason ?? "",
    restrict_to_company: entry?.restrict_to_company ?? "", status: entry?.status ?? "Active", closure_notes: entry?.closure_notes ?? "",
  });
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof f) => (v: string) => setF((c) => ({ ...c, [k]: v }));
  const closing = entry?.status === "Active" && f.status === "Inactive";

  const save = async () => {
    if (!(f.full_name.trim() || f.employee || f.id_number.trim() || f.phone_number.trim() || f.vehicle_plate.trim())) {
      return void toast("Give at least one detail to watch for: a name, staff member, ID, phone or plate.", "warn");
    }
    if (closing && !f.closure_notes.trim()) return void toast("Say why the entry is closed.", "warn");
    setBusy(true);
    const r = await saveWatchEntry({ ...f, name: entry?.name, full_name: f.full_name.trim(), vehicle_plate: f.vehicle_plate.trim().toUpperCase() });
    setBusy(false);
    if (isError(r)) return void toast(r.error, "error");
    toast(entry ? (closing ? "Entry closed." : "Entry saved.") : `${f.full_name || "The person"} is now watched.`, "ok");
    onClose();
    onSaved();
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{entry ? `Watchlist: ${entry.full_name}` : "Watch someone"}</DialogTitle>
          <DialogDescription>Each detail given is matched on every gate record: visits, staff movement, deliveries, dispatches, vehicles and incidents. For a staff member, their ID, phone and sticker plate fill in by themselves.</DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="flex flex-col gap-1.5"><Label htmlFor="wl-type">Who they are</Label><Picker id="wl-type" label="Person type" value={f.person_type} onChange={set("person_type")} options={TYPES} clearable placeholder="Choose" /></div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="wl-emp">Staff member (if staff)</Label>
            <EmployeePicker id="wl-emp" value={f.employee} onChange={(id, label) => setF((c) => ({ ...c, employee: id, full_name: c.full_name || label.replace(/ \(.*\)$/, "") }))} />
          </div>
          <div className="flex flex-col gap-1.5"><Label htmlFor="wl-name">Full name</Label><Input id="wl-name" value={f.full_name} onChange={(e) => set("full_name")(e.target.value)} /></div>
          <div className="flex flex-col gap-1.5"><Label htmlFor="wl-id">ID number</Label><Input id="wl-id" value={f.id_number} onChange={(e) => set("id_number")(e.target.value)} /></div>
          <div className="flex flex-col gap-1.5"><Label htmlFor="wl-ph">Phone</Label><Input id="wl-ph" inputMode="tel" value={f.phone_number} onChange={(e) => set("phone_number")(e.target.value)} /></div>
          <div className="flex flex-col gap-1.5"><Label htmlFor="wl-plate">Vehicle plate</Label><Input id="wl-plate" value={f.vehicle_plate} onChange={(e) => set("vehicle_plate")(e.target.value.toUpperCase())} /></div>
          {boot.companies.length > 1 && (
            <div className="flex flex-col gap-1.5"><Label htmlFor="wl-co">Only at</Label><Picker id="wl-co" label="Only at company" value={f.restrict_to_company} onChange={set("restrict_to_company")} options={boot.companies} clearable clearLabel="Every company" placeholder="Every company" /></div>
          )}
          <div className="flex flex-col gap-1.5 sm:col-span-2"><Label htmlFor="wl-why">Why</Label><Textarea id="wl-why" rows={2} value={f.reason} onChange={(e) => set("reason")(e.target.value)} /></div>
          {entry && (
            <>
              <div className="flex flex-col gap-1.5"><Label htmlFor="wl-st">Status</Label><Picker id="wl-st" label="Status" value={f.status} onChange={set("status")} options={[{ value: "Active", label: "Watched" }, { value: "Inactive", label: "Closed" }]} /></div>
              {f.status === "Inactive" && <div className="flex flex-col gap-1.5 sm:col-span-2"><Label htmlFor="wl-close">Closing notes</Label><Textarea id="wl-close" rows={2} value={f.closure_notes} onChange={(e) => set("closure_notes")(e.target.value)} /></div>}
            </>
          )}
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button onClick={save} disabled={busy}>{busy ? "Saving…" : entry ? (closing ? "Close entry" : "Save") : "Start watching"}</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
