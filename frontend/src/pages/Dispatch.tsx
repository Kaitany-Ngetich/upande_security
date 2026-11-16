import { useState } from "react";
import { Card, TD, TH, Verdict } from "@/components/Card";
import { ClearFiltersPill } from "@/components/ClearFiltersPill";
import { DateRangePicker } from "@/components/DateRangePicker";
import { FeatureOff } from "@/components/FeatureOff";
import { FilterSelect } from "@/components/FilterSelect";
import { GatePostPicker, PostLine } from "@/components/GatePostPicker";
import { TableRowsSkeleton } from "@/components/Loading";
import { LookupBox } from "@/components/LookupBox";
import { PageShell } from "@/components/PageShell";
import { Pager } from "@/components/Pager";
import { RefreshButton } from "@/components/RefreshButton";
import { ScopePicker } from "@/components/ScopePicker";
import { ScrollTable, STICKY_HEAD } from "@/components/ScrollTable";
import { SearchInput } from "@/components/SearchInput";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { isError } from "@/lib/frappe";
import { searchDispatch, verifyDispatch, verifyDispatchBulk, type DispatchLogRow, type DispatchMatch } from "@/lib/gate-api";
import { useGatePost } from "@/lib/gate-post";
import { useScope, useTerms } from "@/lib/scope";
import { LOG_PAGE, useGateLog } from "@/lib/use-gate-log";
import { when } from "@/lib/when";

/** A truck leaving with goods: find its dispatch document, count, release or stop it. */
export function Dispatch() {
  const T = useTerms();
  const { boot } = useScope();
  const toast = useToast();
  const post = useGatePost();
  const log = useGateLog<DispatchLogRow>("dispatch");
  const [looking, setLooking] = useState(false);
  const [match, setMatch] = useState<DispatchMatch | null>(null);
  const [counts, setCounts] = useState<Record<string, string>>({});
  const [related, setRelated] = useState<string[]>([]);
  const [vehicle, setVehicle] = useState("");
  const [driver, setDriver] = useState("");
  const [remarks, setRemarks] = useState("");
  const [saving, setSaving] = useState(false);

  if (boot.features.feature_gate_dispatch === false) return <FeatureOff title="Dispatch check" what="Gate dispatch checking" />;

  const lookup = async (ref: string) => {
    setLooking(true);
    const r = await searchDispatch(ref);
    setLooking(false);
    if (isError(r)) {
      setMatch(null);
      return void toast(r.error, "error");
    }
    setMatch(r);
    setCounts({});
    setRelated([]);
    setVehicle(r.vehicle_no || "");
    setDriver(r.driver_name || "");
    setRemarks("");
  };

  const decide = async (status: "Verified" | "Rejected") => {
    if (!match) return;
    if (status === "Rejected" && !remarks.trim()) return void toast("Say why the truck is stopped.", "warn");
    setSaving(true);
    const item_checks = Object.entries(counts)
      .filter(([, v]) => v.trim() !== "" && Number(v) >= 0)
      .map(([row_id, v]) => ({ row_id, actual_qty: Number(v) }));
    const common = {
      ...post.post, gate_verification_status: status, remarks: remarks.trim() || undefined,
      vehicle_no: vehicle.trim() || undefined, driver_name: driver.trim() || undefined,
    };
    const r = await verifyDispatch({ ...common, reference: match.reference_name, item_checks });
    if (isError(r)) {
      setSaving(false);
      return void toast(r.error, "error");
    }
    let extra = "";
    if (related.length) {
      const b = await verifyDispatchBulk({ ...common, references: related });
      const failed = isError(b) ? related.length : b.results.filter((x) => x.error).length;
      extra = failed ? ` ${failed} of the other ${related.length} documents could not be recorded.` : ` Plus ${related.length} more on the same truck.`;
    }
    setSaving(false);
    toast(
      `${match.reference_name} ${status === "Verified" ? "released" : "stopped"}.${extra}`,
      status === "Verified" ? "ok" : "warn",
      { hint: r.shortfall_incident ? `Short count: incident ${r.shortfall_incident} filed.` : undefined },
    );
    setMatch(null);
    void log.load();
  };

  const canAct = boot.can_check_in_out && match && !match.already_verified;
  const rows = log.page?.rows ?? [];

  return (
    <PageShell
      title="Dispatch check"
      eyebrow="Gate operations"
      actions={
        <>
          <ScopePicker />
          <GatePostPicker {...post} />
        </>
      }
    >
      <Card title="Check a truck leaving">
        <div className="flex flex-col gap-4 p-4">
          <LookupBox label="Dispatch reference" placeholder="Scan or type the dispatch / delivery note number" busy={looking} onLookup={lookup} />
          <PostLine farm={post.farm} gate={post.gate} />
          {match && (
            <div className="flex flex-col gap-4 rounded-[var(--sd-radius-md,10px)] border border-[var(--sd-line)] p-4">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <div className="text-[15px] font-semibold">{match.reference_name}</div>
                  <div className="text-[12px] text-[var(--sd-quiet)]">
                    {[match.reference_doctype, match.farm, match.dispatch_datetime && when(match.dispatch_datetime), match.source_status].filter(Boolean).join(" · ")}
                  </div>
                </div>
                <div className="flex gap-1.5">
                  <Verdict ok={match.is_authorized}>{match.is_authorized ? "Authorised" : "Not authorised"}</Verdict>
                  {match.already_verified && <Verdict ok={null}>Already released {when(match.already_verified_at)} by {match.already_verified_by}</Verdict>}
                </div>
              </div>
              {match.items_summary && <p className="text-[13px] text-[var(--sd-muted)]">{match.items_summary}</p>}

              {match.expected_items.length > 0 && (
                <table className="w-full text-[13px]">
                  <thead>
                    <tr>
                      <th className={TH}>Item</th>
                      <th className={TH}>Expected</th>
                      <th className={TH}>Counted</th>
                    </tr>
                  </thead>
                  <tbody>
                    {match.expected_items.map((it) => {
                      const c = counts[it.row_id] ?? "";
                      const off = c.trim() !== "" && Number(c) !== Number(it.qty);
                      return (
                        <tr key={it.row_id} className="border-t border-[var(--sd-line-soft)]">
                          <td className={TD}>{it.item_name}<div className="text-[12px] text-[var(--sd-quiet)]">{it.item_code}</div></td>
                          <td className={`${TD} tabular-nums`}>{it.qty} {it.uom || ""}</td>
                          <td className={TD}>
                            <Input
                              aria-label={`Counted ${it.item_name}`}
                              type="number"
                              min={0}
                              className={off ? "w-28 border-[var(--sd-data-red)]" : "w-28"}
                              value={c}
                              placeholder="not counted"
                              onChange={(e) => setCounts((cur) => ({ ...cur, [it.row_id]: e.target.value }))}
                            />
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}

              {!!match.related_by_vehicle?.length && (
                <div className="flex flex-col gap-1.5">
                  <Label>Also on this truck ({match.vehicle_no})</Label>
                  {match.related_by_vehicle.map((o) => (
                    <label key={o.reference_name} className="flex items-center gap-2 text-[13px]">
                      <input
                        type="checkbox"
                        checked={related.includes(o.reference_name)}
                        onChange={(e) => setRelated((cur) => (e.target.checked ? [...cur, o.reference_name] : cur.filter((x) => x !== o.reference_name)))}
                      />
                      {o.reference_name}
                      <span className="text-[var(--sd-quiet)]">{[o.reference_doctype, o.items_summary].filter(Boolean).join(" · ")}</span>
                    </label>
                  ))}
                </div>
              )}

              <div className="grid gap-4 sm:grid-cols-2">
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="dp-veh">Vehicle</Label>
                  <Input id="dp-veh" value={vehicle} onChange={(e) => setVehicle(e.target.value.toUpperCase())} />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="dp-drv">Driver</Label>
                  <Input id="dp-drv" value={driver} onChange={(e) => setDriver(e.target.value)} />
                </div>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="dp-rem">Remarks</Label>
                <Textarea id="dp-rem" rows={2} value={remarks} onChange={(e) => setRemarks(e.target.value)} placeholder="Required when stopping a truck" />
              </div>
              {canAct ? (
                <div className="flex justify-end gap-2">
                  <Button variant="outline" onClick={() => setMatch(null)} disabled={saving}>Cancel</Button>
                  <Button variant="destructive" onClick={() => decide("Rejected")} disabled={saving}>Stop truck</Button>
                  <Button onClick={() => decide("Verified")} disabled={saving}>
                    {saving ? "Saving…" : related.length ? `Release ${related.length + 1} documents` : "Release truck"}
                  </Button>
                </div>
              ) : (
                !boot.can_check_in_out && <p className="text-[12px] text-[var(--sd-quiet)]">Only gate guards and security heads release or stop trucks.</p>
              )}
            </div>
          )}
        </div>
      </Card>

      <Card
        title="Dispatch log"
        actions={
          <>
            <DateRangePicker label="Dates" value={log.range} onChange={log.setRange} />
            <FilterSelect label="Result" value={log.status} onChange={log.setStatus} options={["Verified", "Rejected"]} allLabel="All results" />
            <SearchInput value={log.search} onChange={log.setSearch} placeholder="Reference, vehicle, driver" aria-label="Search dispatch log" />
            <ClearFiltersPill active={log.dirty} onClear={log.clear} />
            <RefreshButton onClick={() => void log.load()} loading={log.loading} label="Refresh dispatch log" />
          </>
        }
      >
        <ScrollTable className="mt-3">
          <table className="w-full text-[13px]">
            <thead className={STICKY_HEAD}>
              <tr>
                <th className={TH}>When</th>
                <th className={TH}>Document</th>
                <th className={TH}>Vehicle / driver</th>
                <th className={TH}>{T.Site} · gate</th>
                <th className={TH}>Result</th>
                <th className={TH}>By</th>
              </tr>
            </thead>
            <tbody>
              {log.loading && !log.page ? (
                <TableRowsSkeleton cols={6} rows={4} />
              ) : rows.length === 0 ? (
                <tr><td colSpan={6} className="px-4 py-8 text-center text-[var(--sd-muted)]">No trucks checked in this period.</td></tr>
              ) : (
                rows.map((r) => (
                  <tr key={r.name} className="border-t border-[var(--sd-line-soft)]">
                    <td className={`${TD} tabular-nums`}>{when(r.gate_exit_time)}</td>
                    <td className={TD}>{r.reference_name}<div className="text-[12px] text-[var(--sd-quiet)]">{r.items_summary || r.reference_doctype}</div></td>
                    <td className={TD}>{r.vehicle_no || "—"}<div className="text-[12px] text-[var(--sd-quiet)]">{r.driver_name}</div></td>
                    <td className={TD}>{[r.farm, r.gate].filter(Boolean).join(" · ") || "—"}</td>
                    <td className={TD}>
                      <Verdict ok={r.gate_verification_status === "Verified"}>{r.gate_verification_status === "Verified" ? "Released" : "Stopped"}</Verdict>
                      {r.remarks && <div className="mt-1 text-[12px] text-[var(--sd-quiet)]">{r.remarks}</div>}
                    </td>
                    <td className={TD}>{r.gate_verified_by_name || "—"}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </ScrollTable>
        <Pager start={log.start} total={log.page?.total ?? 0} page={LOG_PAGE} loading={log.loading} onChange={log.setStart} />
      </Card>
    </PageShell>
  );
}
