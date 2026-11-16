import { useCallback, useEffect, useState } from "react";
import { Plus, Printer } from "lucide-react";
import { Card, TD, TH, Verdict } from "@/components/Card";
import { ClearFiltersPill } from "@/components/ClearFiltersPill";
import { DateRangePicker, type DateRange } from "@/components/DateRangePicker";
import { FeatureOff } from "@/components/FeatureOff";
import { FilterSelect } from "@/components/FilterSelect";
import { KpiCard, KpiGrid } from "@/components/KpiCard";
import { TableRowsSkeleton } from "@/components/Loading";
import { PageShell } from "@/components/PageShell";
import { Pager } from "@/components/Pager";
import { RefreshButton } from "@/components/RefreshButton";
import { ScopePicker } from "@/components/ScopePicker";
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
import { checkpointBoard, saveCheckpoint, type Checkpoint, type CheckpointBoard } from "@/lib/registers-api";
import { useScope, useTerms } from "@/lib/scope";
import { cn, todayISO } from "@/lib/utils";
import { when } from "@/lib/when";

const PAGE = 50;
function daysAgo(n: number) {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}
const LAST_7 = (): DateRange => ({ from: daysAgo(6), to: todayISO() });
const printUrl = (name: string) =>
  `/printview?doctype=${encodeURIComponent("Security Checkpoint")}&name=${encodeURIComponent(name)}&format=${encodeURIComponent("Checkpoint QR Label")}&trigger_print=1`;

/** QR checkpoints guards scan on patrol: which are set up, which get visited, and every scan. */
export function Checkpoints() {
  const T = useTerms();
  const toast = useToast();
  const { boot, scope } = useScope();
  const [range, setRange] = useState<DateRange>(LAST_7);
  const [result, setResult] = useState("");
  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");
  const [start, setStart] = useState(0);
  const [data, setData] = useState<CheckpointBoard | null>(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<Checkpoint | "new" | null>(null);

  useEffect(() => {
    const t = window.setTimeout(() => setDebounced(search.trim()), 300);
    return () => window.clearTimeout(t);
  }, [search]);
  useEffect(() => setStart(0), [range, result, debounced, scope]);

  const load = useCallback(async () => {
    setLoading(true);
    const r = await checkpointBoard({ from_date: range.from, to_date: range.to, company: scope.company || undefined, farm: scope.farm || undefined,
      result: result || undefined, search: debounced || undefined, start });
    setLoading(false);
    if (isError(r)) return void toast(r.error, "error");
    setData(r);
  }, [range, scope, result, debounced, start, toast]);
  useEffect(() => {
    void load();
  }, [load]);

  if (boot.features.feature_checkpoint_scanning === false) return <FeatureOff title="Checkpoints" what="Checkpoint scanning" />;
  const k = data?.kpis;
  const dirty = !!result || !!search || range.from !== LAST_7().from || range.to !== todayISO();

  return (
    <PageShell
      title="Checkpoints"
      eyebrow="Security"
      actions={
        <>
          <ScopePicker />
          <DateRangePicker label="Dates" value={range} onChange={setRange} />
          <RefreshButton onClick={() => void load()} loading={loading} label="Refresh checkpoints" />
          {boot.can_setup && <ToolbarButton onClick={() => setEditing("new")}><Plus className="h-4 w-4" /> Add checkpoint</ToolbarButton>}
        </>
      }
    >
      <KpiGrid cols={5}>
        <KpiCard label="Active checkpoints" value={k?.active ?? 0} hint={`${k?.checkpoints ?? 0} in all`} loading={!data} />
        <KpiCard label="Position not set" value={k?.no_position ?? 0} hint="Set on site from the guard app" tone={k?.no_position ? "warning" : "default"} loading={!data} />
        <KpiCard label="Valid scans" value={k?.valid ?? 0} loading={!data} />
        <KpiCard label="Refused scans" value={k?.refused ?? 0} hint="Too far, poor or fake GPS, unknown code" tone={k?.refused ? "critical" : "default"} loading={!data} />
        <KpiCard label="Not visited" value={k?.unvisited ?? 0} hint="No valid scan in the period" tone={k?.unvisited ? "warning" : "default"} loading={!data} />
      </KpiGrid>

      <Card title="Checkpoints">
        <ScrollTable className="mt-3">
          <table className="w-full text-[13px]">
            <thead className={STICKY_HEAD}><tr><th className={TH}>Checkpoint</th><th className={TH}>{T.Site}</th><th className={TH}>Position</th><th className={TH}>Valid</th><th className={TH}>Refused</th><th className={TH}>Last valid scan</th><th className={TH} /></tr></thead>
            <tbody>
              {!data ? <TableRowsSkeleton cols={7} rows={4} /> : data.checkpoints.length === 0 ? (
                <tr><td colSpan={7} className="px-4 py-8 text-center text-[var(--sd-muted)]">No checkpoints{scope.farm ? ` at ${scope.farm}` : ""} yet.</td></tr>
              ) : data.checkpoints.map((c) => (
                <tr key={c.name} className={cn("border-t border-[var(--sd-line-soft)]", !c.active && "opacity-55")}>
                  <td className={TD}>{c.checkpoint_name}<div className="text-[12px] text-[var(--sd-quiet)]">{[c.name, c.location_hint].filter(Boolean).join(" · ")}{!c.active && " · inactive"}</div></td>
                  <td className={TD}>{c.farm || "—"}</td>
                  <td className={TD}>{c.has_position ? <span>Set{c.position_accuracy_m ? ` (±${Math.round(c.position_accuracy_m)} m)` : ""}<div className="text-[12px] text-[var(--sd-quiet)]">fence {c.radius_m ?? 3} m</div></span> : <Verdict ok={false}>Not set</Verdict>}</td>
                  <td className={`${TD} tabular-nums`}>{c.valid}</td>
                  <td className={`${TD} tabular-nums`}>{c.refused ? <span className="font-medium text-[var(--sd-data-red)]">{c.refused}</span> : 0}</td>
                  <td className={`${TD} tabular-nums`}>{c.last_valid ? when(c.last_valid) : <span className="text-[var(--sd-quiet)]">—</span>}</td>
                  <td className={`${TD} text-right`}>
                    <span className="flex justify-end gap-1.5">
                      <a href={printUrl(c.name)} target="_blank" rel="noreferrer" className="inline-flex h-8 items-center gap-1 rounded-md border border-[var(--sd-line)] px-2.5 text-[12px] hover:bg-[var(--sd-line-soft)]"><Printer className="h-3.5 w-3.5" /> QR</a>
                      {boot.can_setup && <Button size="sm" variant="outline" onClick={() => setEditing(c)}>Edit</Button>}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollTable>
        <div className="h-2" />
      </Card>

      <Card
        title="Scans"
        actions={
          <>
            <FilterSelect label="Result" value={result} onChange={setResult} options={data?.results ?? []} allLabel="All results" />
            <SearchInput value={search} onChange={setSearch} placeholder="Guard, checkpoint, patrol" aria-label="Search scans" />
            <ClearFiltersPill active={dirty} onClear={() => { setResult(""); setSearch(""); setRange(LAST_7()); }} />
          </>
        }
      >
        <ScrollTable className="mt-3" tall>
          <table className="w-full text-[13px]">
            <thead className={STICKY_HEAD}><tr><th className={TH}>When</th><th className={TH}>Checkpoint</th><th className={TH}>Guard</th><th className={TH}>Result</th><th className={TH}>Distance</th></tr></thead>
            <tbody>
              {!data ? <TableRowsSkeleton cols={5} rows={5} /> : data.scans.length === 0 ? (
                <tr><td colSpan={5} className="px-4 py-8 text-center text-[var(--sd-muted)]">No scans in this period.</td></tr>
              ) : data.scans.map((s) => (
                <tr key={s.name} className="border-t border-[var(--sd-line-soft)]">
                  <td className={`${TD} tabular-nums`}>{when(s.scanned_at)}</td>
                  <td className={TD}>{s.checkpoint_name || s.checkpoint}<div className="text-[12px] text-[var(--sd-quiet)]">{s.farm}</div></td>
                  <td className={TD}>{s.guard_name || "—"}<div className="text-[12px] text-[var(--sd-quiet)]">{s.patrol}</div></td>
                  <td className={TD}><Verdict ok={s.result === "Valid"}>{s.result}</Verdict>{s.mocked ? <div className="text-[12px] text-[var(--sd-data-red)]">mock location app</div> : null}</td>
                  <td className={`${TD} tabular-nums`}>{s.distance_m != null ? `${Math.round(s.distance_m)} m` : "—"}{s.allowed_m != null && <div className="text-[12px] text-[var(--sd-quiet)]">allowed {Math.round(s.allowed_m)} m{s.gps_accuracy ? ` · ±${Math.round(s.gps_accuracy)} m` : ""}</div>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollTable>
        <Pager start={start} total={data?.total ?? 0} page={PAGE} loading={loading} onChange={setStart} />
      </Card>

      {editing && <CheckpointForm cp={editing === "new" ? null : editing} onClose={() => setEditing(null)} onSaved={load} />}
    </PageShell>
  );
}

function CheckpointForm({ cp, onClose, onSaved }: { cp: Checkpoint | null; onClose: () => void; onSaved: () => void }) {
  const T = useTerms();
  const toast = useToast();
  const { scope, farmsInScope } = useScope();
  const [name, setName] = useState(cp?.checkpoint_name ?? "");
  const [hint, setHint] = useState(cp?.location_hint ?? "");
  const [farm, setFarm] = useState(cp?.farm ?? (scope.farm || (farmsInScope.length === 1 ? farmsInScope[0] : "")));
  const [radius, setRadius] = useState(String(cp?.radius_m ?? 3));
  const [active, setActive] = useState(cp ? !!cp.active : true);
  const [busy, setBusy] = useState(false);
  const save = async () => {
    if (!name.trim()) return void toast("Name the checkpoint.", "warn");
    if (!farm) return void toast(`Choose the ${T.site}.`, "warn");
    setBusy(true);
    const r = await saveCheckpoint({ name: cp?.name, checkpoint_name: name.trim(), location_hint: hint.trim() || null, farm, radius_m: Number(radius) || 3, active: active ? 1 : 0 });
    setBusy(false);
    if (isError(r)) return void toast(r.error, "error");
    toast(cp ? "Checkpoint saved." : `Checkpoint ${r.name} added.`, "ok", { hint: cp ? undefined : "Print its QR, fix it in place, then set its position from the guard app standing next to it." });
    onClose();
    onSaved();
  };
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{cp ? `Edit ${cp.checkpoint_name}` : "Add a checkpoint"}</DialogTitle>
          <DialogDescription>Its QR is made when it is added. The position is set on site from the guard app: a typed position is too far off for the {radius || 3} m fence.</DialogDescription>
        </DialogHeader>
        <div className="grid gap-4">
          <div className="flex flex-col gap-1.5"><Label htmlFor="cp-name">Name</Label><Input id="cp-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. North fence pump house" /></div>
          <div className="flex flex-col gap-1.5"><Label htmlFor="cp-hint">Where to find it</Label><Input id="cp-hint" value={hint} onChange={(e) => setHint(e.target.value)} /></div>
          <div className="flex flex-col gap-1.5"><Label htmlFor="cp-farm">{T.Site}</Label><Picker id="cp-farm" label={T.Site} value={farm} onChange={setFarm} options={farmsInScope} placeholder={`Choose a ${T.site}`} /></div>
          <div className="flex flex-col gap-1.5"><Label htmlFor="cp-r">Fence radius (m)</Label><Input id="cp-r" type="number" min={1} value={radius} onChange={(e) => setRadius(e.target.value)} /></div>
          <label className="flex items-center gap-2 text-[13px]"><input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} /> Active (part of patrols)</label>
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button onClick={save} disabled={busy}>{busy ? "Saving…" : "Save"}</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
