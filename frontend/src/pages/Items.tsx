import { useCallback, useEffect, useState } from "react";
import { Card, TD, TH, Verdict } from "@/components/Card";
import { ClearFiltersPill } from "@/components/ClearFiltersPill";
import { DateRangePicker, type DateRange } from "@/components/DateRangePicker";
import { FilterSelect } from "@/components/FilterSelect";
import { TableRowsSkeleton } from "@/components/Loading";
import { PageShell } from "@/components/PageShell";
import { Pager } from "@/components/Pager";
import { PillTabs } from "@/components/PillTabs";
import { RefreshButton } from "@/components/RefreshButton";
import { ScopePicker } from "@/components/ScopePicker";
import { ScrollTable, STICKY_HEAD } from "@/components/ScrollTable";
import { SearchInput } from "@/components/SearchInput";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { isError } from "@/lib/frappe";
import { personalItems, setItemExit, type ExitStatus, type Item } from "@/lib/registers-api";
import { useScope } from "@/lib/scope";
import { useDebounced } from "@/lib/use-debounced";
import { cn, todayISO } from "@/lib/utils";
import { when } from "@/lib/when";

const PAGE = 50;
function daysAgo(n: number) {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}
const LAST_30 = (): DateRange => ({ from: daysAgo(29), to: todayISO() });
const RECORD_ROUTE: Record<string, string> = {
  Appointment: "appointment", "Gate Receiving Verification": "gate-receiving-verification", "Gate Movement": "gate-movement", Attendance: "attendance",
};

function ExitTag({ s }: { s: ExitStatus }) {
  return <Verdict ok={s === "Not seen leaving" ? false : s === "Inside" ? null : true}>{s}</Verdict>;
}

/** What people carried through the gate, and whether it went back out. */
export function Items() {
  const toast = useToast();
  const { scope } = useScope();
  const [range, setRange] = useState<DateRange>(LAST_30);
  const [tab, setTab] = useState<string>("Not seen leaving");
  const [party, setParty] = useState("");
  const [search, setSearch] = useState("");
  const q = useDebounced(search);
  const [start, setStart] = useState(0);
  const [data, setData] = useState<Awaited<ReturnType<typeof personalItems>> | null>(null);
  const [loading, setLoading] = useState(true);
  const [settling, setSettling] = useState<Item | null>(null);

  useEffect(() => setStart(0), [range, tab, party, q, scope]);
  const load = useCallback(async () => {
    setLoading(true);
    const r = await personalItems({ from_date: range.from, to_date: range.to, company: scope.company || undefined, farm: scope.farm || undefined,
      exit_status: tab || undefined, party_type: party || undefined, search: q || undefined, start });
    setLoading(false);
    if (isError(r)) return void toast(r.error, "error");
    setData(r);
  }, [range, scope, tab, party, q, start, toast]);
  useEffect(() => {
    void load();
  }, [load]);

  const d = data && !isError(data) ? data : null;
  const c = d?.counts;
  const dirty = !!party || !!search || range.from !== LAST_30().from || range.to !== todayISO();

  return (
    <PageShell
      title="Personal items"
      eyebrow="Gate operations"
      tabs={
        <PillTabs label="Exit status" value={tab} onChange={setTab} tabs={[
          { key: "Not seen leaving", label: "Not seen leaving", count: c?.["Not seen leaving"], alert: true },
          { key: "Inside", label: "Still inside", count: c?.Inside },
          { key: "Left with owner", label: "Left with owner", count: c?.["Left with owner"] },
          { key: "Left with document", label: "Left with a document", count: c?.["Left with document"] },
          { key: "", label: "All" },
        ]} />
      }
      actions={
        <>
          <ScopePicker />
          <DateRangePicker label="Brought in" value={range} onChange={setRange} />
          <FilterSelect label="Who" value={party} onChange={setParty} options={["Visitor", "Customer", "Contractor", "Supplier", "Staff"]} allLabel="Everyone" />
          <SearchInput value={search} onChange={setSearch} placeholder="Item, person, serial" aria-label="Search items" />
          <ClearFiltersPill active={dirty} onClear={() => { setParty(""); setSearch(""); setRange(LAST_30()); }} />
          <RefreshButton onClick={() => void load()} loading={loading} label="Refresh items" />
        </>
      }
      description={tab === "Not seen leaving" ? "Declared on the way in but not ticked off on the way out. Follow each one up, then settle it here." : undefined}
    >
      <Card>
        <ScrollTable tall>
          <table className="w-full text-[13px]">
            <thead className={STICKY_HEAD}><tr><th className={TH}>Item</th><th className={TH}>Carried by</th><th className={TH}>In</th><th className={TH}>Out</th><th className={TH}>Gate record</th><th className={TH} /></tr></thead>
            <tbody>
              {!d ? <TableRowsSkeleton cols={6} rows={6} /> : d.rows.length === 0 ? (
                <tr><td colSpan={6} className="px-4 py-10 text-center text-[var(--sd-muted)]">No items here.</td></tr>
              ) : d.rows.map((it) => (
                <tr key={it.name} className={cn("border-t border-[var(--sd-line-soft)] align-top", loading && "opacity-60")}>
                  <td className={TD}>{it.item}{it.qty && it.qty > 1 ? ` ×${it.qty}` : ""}{it.serial_notes && <div className="text-[12px] text-[var(--sd-quiet)]">{it.serial_notes}</div>}</td>
                  <td className={TD}>{it.carried_by || it.employee || "—"}<div className="text-[12px] text-[var(--sd-quiet)]">{[it.party_type, it.farm].filter(Boolean).join(" · ")}</div></td>
                  <td className={`${TD} tabular-nums`}>{when(it.entry_time)}{it.declared_at === "Exit" && <div className="text-[12px] text-[var(--sd-quiet)]">declared at exit</div>}</td>
                  <td className={TD}><ExitTag s={it.exit_status} />{it.exit_time && <div className="text-[12px] tabular-nums text-[var(--sd-quiet)]">{when(it.exit_time)}</div>}{it.supporting_document && <div className="text-[12px] text-[var(--sd-quiet)]">doc {it.supporting_document}</div>}</td>
                  <td className={TD}>
                    {it.reference_name ? <a className="underline" href={`/app/${RECORD_ROUTE[it.reference_doctype ?? ""] ?? ""}/${encodeURIComponent(it.reference_name)}`}>{it.reference_name}</a> : "—"}
                    <div className="text-[12px] text-[var(--sd-quiet)]">{it.reference_doctype}</div>
                  </td>
                  <td className={`${TD} text-right`}>{d.can_edit && it.exit_status !== "Left with owner" && it.exit_status !== "Left with document" && <Button size="sm" variant="outline" onClick={() => setSettling(it)}>Settle</Button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollTable>
        <Pager start={start} total={d?.total ?? 0} page={PAGE} loading={loading} onChange={setStart} />
      </Card>
      <SettleDialog item={settling} onClose={() => setSettling(null)} onDone={load} />
    </PageShell>
  );
}

function SettleDialog({ item, onClose, onDone }: { item: Item | null; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => setNote(""), [item]);
  const go = async (s: ExitStatus) => {
    if (!item) return;
    if (!note.trim()) return void toast("Say how it was settled.", "warn");
    setBusy(true);
    const r = await setItemExit(item.name, s, note.trim());
    setBusy(false);
    if (isError(r)) return void toast(r.error, "error");
    toast(`${item.item}: ${s.toLowerCase()}.`, "ok");
    onClose();
    onDone();
  };
  return (
    <Dialog open={!!item} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Settle: {item?.item}</DialogTitle>
          <DialogDescription>{item ? `${item.carried_by || item.employee || ""} · brought in ${when(item.entry_time)} · now ${item.exit_status}` : ""}</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-1.5"><Label htmlFor="st-note">What was found</Label><Textarea id="st-note" rows={2} value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Owner confirmed by phone it left with them" /></div>
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="outline" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button variant="outline" onClick={() => go("Left with document")} disabled={busy}>Left with a document</Button>
          <Button onClick={() => go("Left with owner")} disabled={busy}>{busy ? "Saving…" : "Left with owner"}</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
