import { useState } from "react";
import { Card, TD, TH, Verdict } from "@/components/Card";
import { ClearFiltersPill } from "@/components/ClearFiltersPill";
import { DateRangePicker } from "@/components/DateRangePicker";
import { FeatureOff } from "@/components/FeatureOff";
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
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { isError } from "@/lib/frappe";
import { searchVehicle, verifyVehicle, type Leg, type VehicleLogRow, type VehicleMatch } from "@/lib/gate-api";
import { useGatePost } from "@/lib/gate-post";
import { useScope } from "@/lib/scope";
import { cn } from "@/lib/utils";
import { LOG_PAGE, useGateLog } from "@/lib/use-gate-log";
import { when } from "@/lib/when";

/** Where a leg stands: the vehicle is out (exit, no entry) or back in. */
function legSide(l: Leg) {
  return l.gate_exit_time && !l.gate_entry_time ? "out" : "in";
}

function Side({ time, status, place }: { time: string | null; status: string | null; place: string | null }) {
  if (!time) return <span className="text-[var(--sd-quiet)]">—</span>;
  return (
    <span>
      <span className="tabular-nums">{when(time)}</span>{" "}
      <Verdict ok={status === "Verified"}>{status === "Verified" ? "OK" : status}</Verdict>
      {place && <div className="text-[12px] text-[var(--sd-quiet)]">{place}</div>}
    </span>
  );
}

/** Company vehicles and tractors going out and coming back, one leg at a time. */
export function Vehicles() {
  const { boot } = useScope();
  const toast = useToast();
  const post = useGatePost();
  const log = useGateLog<VehicleLogRow>("vehicles");
  const [looking, setLooking] = useState(false);
  const [match, setMatch] = useState<VehicleMatch | null>(null);
  const [ref, setRef] = useState("");
  const [remarks, setRemarks] = useState("");
  const [saving, setSaving] = useState(false);

  if (boot.features.feature_vehicle_gate_tracking === false) return <FeatureOff title="Vehicle check" what="Vehicle gate tracking" />;

  const lookup = async (reference: string) => {
    setLooking(true);
    const r = await searchVehicle(reference);
    setLooking(false);
    if (isError(r)) {
      setMatch(null);
      return void toast(r.error, "error");
    }
    setRef(reference);
    setMatch(r);
    setRemarks("");
  };

  // The likely next move: a vehicle with an open leg is coming back in.
  const out = !!match?.recent_legs?.[0] && legSide(match.recent_legs[0]) === "out";

  const record = async (movement_type: "Exit" | "Entry", status: "Verified" | "Rejected") => {
    if (!match) return;
    if (status === "Rejected" && !remarks.trim()) return void toast("Say why the vehicle is stopped.", "warn");
    setSaving(true);
    const r = await verifyVehicle({ ...post.post, reference: ref, movement_type, gate_verification_status: status, remarks: remarks.trim() || undefined });
    setSaving(false);
    if (isError(r)) return void toast(r.error, "error");
    toast(
      `${match.vehicle_no}: ${movement_type.toLowerCase()} ${status === "Verified" ? "recorded" : "refused"} at ${r.farm}${r.gate ? ` · ${r.gate}` : ""}.`,
      status === "Verified" ? "ok" : "warn",
      { hint: r.unmatched_entry ? "No departure was on record for this vehicle - logged as an arrival without one." : r.leg_complete ? "Trip leg closed." : undefined },
    );
    setMatch(null);
    void log.load();
  };

  const rows = log.page?.rows ?? [];

  return (
    <PageShell title="Vehicle check" eyebrow="Gate operations" actions={<><ScopePicker /><GatePostPicker {...post} /></>}>
      <Card title="Check a company vehicle">
        <div className="flex flex-col gap-4 p-4">
          <LookupBox label="Vehicle reference" placeholder="Scan the asset label or type the vehicle / task" busy={looking} onLookup={lookup} />
          <PostLine farm={post.farm} gate={post.gate} />
          {match && (
            <div className="flex flex-col gap-4 rounded-[var(--sd-radius-md,10px)] border border-[var(--sd-line)] p-4">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <div className="text-[15px] font-semibold">{match.vehicle_no}</div>
                  <div className="text-[12px] text-[var(--sd-quiet)]">{[match.task_description, match.source_status].filter(Boolean).join(" · ")}</div>
                </div>
                <div className="flex gap-1.5">
                  <Verdict ok={match.is_authorized}>{match.is_authorized ? "Cleared to move" : "Not cleared"}</Verdict>
                  <Verdict ok={null}>{out ? "Currently out" : "Currently in"}</Verdict>
                </div>
              </div>
              {match.recent_legs.length > 0 && (
                <table className="w-full text-[13px]">
                  <thead><tr><th className={TH}>Left</th><th className={TH}>From → to</th><th className={TH}>Came in</th></tr></thead>
                  <tbody>
                    {match.recent_legs.map((l) => (
                      <tr key={l.name} className="border-t border-[var(--sd-line-soft)]">
                        <td className={TD}><Side time={l.gate_exit_time} status={l.gate_exit_status} place={null} /></td>
                        <td className={TD}>{l.from_farm || "?"} → {l.to_farm || (l.gate_exit_time ? "out" : "?")}</td>
                        <td className={TD}><Side time={l.gate_entry_time} status={l.gate_entry_status} place={null} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="vh-rem">Remarks</Label>
                <Textarea id="vh-rem" rows={2} value={remarks} onChange={(e) => setRemarks(e.target.value)} placeholder="Required when stopping a vehicle" />
              </div>
              {boot.can_check_in_out ? (
                <div className="flex flex-wrap justify-end gap-2">
                  <Button variant="outline" onClick={() => setMatch(null)} disabled={saving}>Cancel</Button>
                  <Button variant="destructive" onClick={() => record(out ? "Entry" : "Exit", "Rejected")} disabled={saving}>Stop vehicle</Button>
                  <Button variant={out ? "outline" : "default"} onClick={() => record("Exit", "Verified")} disabled={saving}>Going out</Button>
                  <Button variant={out ? "default" : "outline"} onClick={() => record("Entry", "Verified")} disabled={saving}>Coming in</Button>
                </div>
              ) : (
                <p className="text-[12px] text-[var(--sd-quiet)]">Only gate guards and security heads record vehicle movements.</p>
              )}
            </div>
          )}
        </div>
      </Card>

      <Card
        title="Vehicle movements"
        actions={
          <>
            <DateRangePicker label="Dates" value={log.range} onChange={log.setRange} />
            <SearchInput value={log.search} onChange={log.setSearch} placeholder="Vehicle, asset, task" aria-label="Search vehicle movements" />
            <ClearFiltersPill active={log.dirty} onClear={log.clear} />
            <RefreshButton onClick={() => void log.load()} loading={log.loading} label="Refresh vehicle movements" />
          </>
        }
      >
        <ScrollTable className="mt-3">
          <table className="w-full text-[13px]">
            <thead className={STICKY_HEAD}>
              <tr><th className={TH}>Vehicle</th><th className={TH}>Task</th><th className={TH}>Left</th><th className={TH}>Came in</th><th className={TH}>Status</th></tr>
            </thead>
            <tbody>
              {log.loading && !log.page ? (
                <TableRowsSkeleton cols={5} rows={4} />
              ) : rows.length === 0 ? (
                <tr><td colSpan={5} className="px-4 py-8 text-center text-[var(--sd-muted)]">No vehicle movements this period.</td></tr>
              ) : (
                rows.map((r) => (
                  <tr key={r.name} className="border-t border-[var(--sd-line-soft)]">
                    <td className={TD}>{r.vehicle_no}<div className="text-[12px] text-[var(--sd-quiet)]">{r.asset}</div></td>
                    <td className={TD}>{r.task_description || "—"}</td>
                    <td className={TD}><Side time={r.gate_exit_time} status={r.gate_exit_status} place={[r.from_farm, r.exit_gate].filter(Boolean).join(" · ")} /></td>
                    <td className={TD}><Side time={r.gate_entry_time} status={r.gate_entry_status} place={[r.to_farm, r.entry_gate].filter(Boolean).join(" · ")} /></td>
                    <td className={cn(TD, "text-[12px]")}>{legSide(r) === "out" ? <span className="font-medium text-[var(--sd-target)]">Still out</span> : "Back"}</td>
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
