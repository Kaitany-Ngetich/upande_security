import { useCallback, useEffect, useState } from "react";
import { Plus, Printer } from "lucide-react";
import { Card, TD, TH, Verdict } from "@/components/Card";
import { FilterSelect } from "@/components/FilterSelect";
import { TableRowsSkeleton } from "@/components/Loading";
import { PageShell } from "@/components/PageShell";
import { Pager } from "@/components/Pager";
import { PillTabs } from "@/components/PillTabs";
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
import { isError } from "@/lib/frappe";
import { badgeBoard, createBadges, setBadgeStatus, type Badge } from "@/lib/registers-api";
import { useScope, useTerms } from "@/lib/scope";
import { useDebounced } from "@/lib/use-debounced";
import { cn } from "@/lib/utils";
import { when } from "@/lib/when";

const PAGE = 100;
const printUrl = (name: string) =>
  `/printview?doctype=${encodeURIComponent("Gate Badge")}&name=${encodeURIComponent(name)}&format=${encodeURIComponent("Gate Badge Card")}&trigger_print=1`;

/** The visitor, supplier and contractor badge pools: who holds which badge, and for what. */
export function Badges() {
  const T = useTerms();
  const toast = useToast();
  const { scope } = useScope();
  const [status, setStatus] = useState("Issued");
  const [type, setType] = useState("");
  const [search, setSearch] = useState("");
  const q = useDebounced(search);
  const [start, setStart] = useState(0);
  const [data, setData] = useState<Awaited<ReturnType<typeof badgeBoard>> | null>(null);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState("");

  useEffect(() => setStart(0), [status, type, q, scope]);
  const load = useCallback(async () => {
    setLoading(true);
    const r = await badgeBoard({ status: status || undefined, badge_type: type || undefined, company: scope.company || undefined,
      farm: type === "Visitor" ? scope.farm || undefined : undefined, search: q || undefined, start });
    setLoading(false);
    if (isError(r)) return void toast(r.error, "error");
    setData(r);
  }, [status, type, scope, q, start, toast]);
  useEffect(() => {
    void load();
  }, [load]);

  const mark = async (b: Badge, s: "Available" | "Lost") => {
    if (s === "Available" && b.status === "Issued" && !confirm(`Take badge ${b.badge_number} back from ${b.holder_name || "its holder"}?`)) return;
    setBusy(b.name);
    const r = await setBadgeStatus(b.name, s);
    setBusy("");
    if (isError(r)) return void toast(r.error, "error");
    toast(`${b.badge_type} badge ${b.badge_number}: ${r.status.toLowerCase()}.`, "ok");
    void load();
  };

  const d = data && !isError(data) ? data : null;
  const c = d?.counts;

  return (
    <PageShell
      title="Gate badges"
      eyebrow="Gate operations"
      tabs={
        <PillTabs label="Badge status" value={status} onChange={setStatus} tabs={[
          { key: "Issued", label: "Out", count: c?.Issued },
          { key: "Available", label: "In stock", count: c?.Available },
          { key: "Held at Other Farm", label: `At another ${T.site}`, count: c?.["Held at Other Farm"], alert: true },
          { key: "Lost", label: "Lost", count: c?.Lost, alert: true },
          { key: "", label: "All" },
        ]} />
      }
      actions={
        <>
          <FilterSelect label="Type" value={type} onChange={setType} options={["Visitor", "Supplier", "Contractor"]} allLabel="All badges" />
          <SearchInput value={search} onChange={setSearch} placeholder="Number, holder, visit" aria-label="Search badges" />
          <RefreshButton onClick={() => void load()} loading={loading} label="Refresh badges" />
          {d?.can_manage && <ToolbarButton onClick={() => setAdding(true)}><Plus className="h-4 w-4" /> Add badges</ToolbarButton>}
        </>
      }
      description="Badges are handed out and taken back at the gate. Here you can take one back by hand, report it lost, or add new badges to a pool."
    >
      <Card>
        <ScrollTable tall>
          <table className="w-full text-[13px]">
            <thead className={STICKY_HEAD}><tr><th className={TH}>Badge</th><th className={TH}>Pool</th><th className={TH}>Status</th><th className={TH}>Held by</th><th className={TH}>Since</th><th className={TH} /></tr></thead>
            <tbody>
              {!d ? <TableRowsSkeleton cols={6} rows={6} /> : d.rows.length === 0 ? (
                <tr><td colSpan={6} className="px-4 py-10 text-center text-[var(--sd-muted)]">No badges here.</td></tr>
              ) : d.rows.map((b) => (
                <tr key={b.name} className={cn("border-t border-[var(--sd-line-soft)] align-top", loading && "opacity-60")}>
                  <td className={TD}><span className="font-semibold tabular-nums">#{b.badge_number}</span><div className="text-[12px] text-[var(--sd-quiet)]">{b.badge_type}</div></td>
                  <td className={TD}>{b.farm || b.company}{b.farm && <div className="text-[12px] text-[var(--sd-quiet)]">{b.company}</div>}</td>
                  <td className={TD}>
                    <Verdict ok={b.status === "Available" ? true : b.status === "Issued" ? null : false}>{b.status}</Verdict>
                    {b.held_at_farm && <div className="text-[12px] text-[var(--sd-quiet)]">at {b.held_at_farm}</div>}
                  </td>
                  <td className={TD}>
                    {b.holder_name || b.supplier || "—"}
                    <div className="text-[12px] text-[var(--sd-quiet)]">{b.current_appointment || b.current_receiving || ""}{b.valid_until ? ` · until ${b.valid_until}` : ""}</div>
                  </td>
                  <td className={`${TD} tabular-nums`}>{b.issued_at ? when(b.issued_at) : "—"}</td>
                  <td className={`${TD} text-right`}>
                    <span className="flex flex-wrap justify-end gap-1.5">
                      <a href={printUrl(b.name)} target="_blank" rel="noreferrer" className="inline-flex h-8 items-center gap-1 rounded-md border border-[var(--sd-line)] px-2.5 text-[12px] hover:bg-[var(--sd-line-soft)]"><Printer className="h-3.5 w-3.5" /> Print</a>
                      {d.can_manage && b.status !== "Available" && <Button size="sm" variant="outline" disabled={busy === b.name} onClick={() => mark(b, "Available")}>{b.status === "Lost" ? "Found" : "Take back"}</Button>}
                      {d.can_manage && b.status !== "Lost" && <Button size="sm" variant="outline" disabled={busy === b.name} onClick={() => mark(b, "Lost")}>Lost</Button>}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollTable>
        <Pager start={start} total={d?.total ?? 0} page={PAGE} loading={loading} onChange={setStart} />
      </Card>
      {adding && <AddBadges onClose={() => setAdding(false)} onDone={load} />}
    </PageShell>
  );
}

function AddBadges({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const T = useTerms();
  const toast = useToast();
  const { boot, scope, farmsInScope } = useScope();
  const [type, setType] = useState("Visitor");
  const [company, setCompany] = useState(scope.company || (boot.companies.length === 1 ? boot.companies[0] : ""));
  const [farm, setFarm] = useState(scope.farm || "");
  const [count, setCount] = useState("10");
  const [busy, setBusy] = useState(false);
  const farms = boot.farms.filter((f) => !company || f.company === company).map((f) => f.name);
  const go = async () => {
    const co = type === "Visitor" ? boot.farms.find((f) => f.name === farm)?.company || company : company;
    if (!co) return void toast("Choose the company.", "warn");
    if (type === "Visitor" && !farm) return void toast(`Visitor badges belong to a ${T.site}: choose one.`, "warn");
    setBusy(true);
    const r = await createBadges(type, co, Number(count), type === "Visitor" ? farm : undefined);
    setBusy(false);
    if (isError(r)) return void toast(r.error, "error");
    toast(`${r.created} ${type.toLowerCase()} badges added: #${r.first}–#${r.last}.`, "ok", { hint: "Each has its QR; print them from the list." });
    onClose();
    onDone();
  };
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Add badges</DialogTitle>
          <DialogDescription>Numbered on from the pool's highest. Visitor badges belong to a {T.site}; supplier and contractor badges to a company.</DialogDescription>
        </DialogHeader>
        <div className="grid gap-4">
          <div className="flex flex-col gap-1.5"><Label htmlFor="ab-type">Type</Label><Picker id="ab-type" label="Type" value={type} onChange={setType} options={["Visitor", "Supplier", "Contractor"]} /></div>
          <div className="flex flex-col gap-1.5"><Label htmlFor="ab-co">Company</Label><Picker id="ab-co" label="Company" value={company} onChange={(v) => { setCompany(v); setFarm(""); }} options={boot.companies} placeholder="Choose" /></div>
          {type === "Visitor" && <div className="flex flex-col gap-1.5"><Label htmlFor="ab-farm">{T.Site}</Label><Picker id="ab-farm" label={T.Site} value={farm} onChange={setFarm} options={farms.length ? farms : farmsInScope} placeholder="Choose" /></div>}
          <div className="flex flex-col gap-1.5"><Label htmlFor="ab-n">How many</Label><Input id="ab-n" type="number" min={1} value={count} onChange={(e) => setCount(e.target.value)} /></div>
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button onClick={go} disabled={busy || !(Number(count) >= 1)}>{busy ? "Adding…" : `Add ${count || 0} badges`}</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
