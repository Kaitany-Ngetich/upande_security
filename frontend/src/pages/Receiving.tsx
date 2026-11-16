import { useCallback, useEffect, useState } from "react";
import { LogOut } from "lucide-react";
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
import { TogglePill } from "@/components/TogglePill";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { isError } from "@/lib/frappe";
import {
  confirmDeparture, getDeparture, searchByBadge, searchReceiving, trucksInside, verifyReceivingBulk,
  type Departure, type PoMatch, type ReceivingLogRow, type Truck,
} from "@/lib/gate-api";
import { useGatePost } from "@/lib/gate-post";
import { useScope, useTerms } from "@/lib/scope";
import { LOG_PAGE, useGateLog } from "@/lib/use-gate-log";
import { when } from "@/lib/when";

/** Supplier deliveries: check the paperwork in, see who is still inside, check them out. */
export function Receiving() {
  const T = useTerms();
  const { boot } = useScope();
  const toast = useToast();
  const post = useGatePost();
  const log = useGateLog<ReceivingLogRow>("receiving");
  const [byBadge, setByBadge] = useState(false);
  const [looking, setLooking] = useState(false);
  const [found, setFound] = useState<{ supplier_name: string; badge?: string; pos: PoMatch[] } | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [vehicle, setVehicle] = useState("");
  const [driver, setDriver] = useState("");
  const [remarks, setRemarks] = useState("");
  const [saving, setSaving] = useState(false);
  const [trucks, setTrucks] = useState<Truck[] | null>(null);
  const [leaving, setLeaving] = useState<Truck | null>(null);

  const loadTrucks = useCallback(async () => {
    const r = await trucksInside(post.post);
    if (isError(r)) return void toast(r.error, "error");
    setTrucks(Array.isArray(r) ? r : []);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [post.post.checking_farm, toast]);
  useEffect(() => {
    if (boot.features.feature_gate_receiving !== false) void loadTrucks();
  }, [loadTrucks, boot.features.feature_gate_receiving]);

  if (boot.features.feature_gate_receiving === false) return <FeatureOff title="Receiving check" what="Gate receiving checking" />;

  const lookup = async (ref: string) => {
    setLooking(true);
    setFound(null);
    if (byBadge) {
      const r = await searchByBadge(ref);
      setLooking(false);
      if (isError(r)) return void toast(r.error, "error");
      setFound({ supplier_name: r.supplier_name, badge: r.badge, pos: r.matches });
      setPicked(r.matches.length === 1 ? [r.matches[0].purchase_order] : []);
    } else {
      const r = await searchReceiving(ref);
      setLooking(false);
      if (isError(r)) return void toast(r.error, "error");
      setFound({ supplier_name: r.supplier_name, pos: [r] });
      setPicked([r.purchase_order]);
    }
    setVehicle("");
    setDriver("");
    setRemarks("");
  };

  const decide = async (status: "Verified" | "Rejected") => {
    if (!picked.length) return void toast("Pick the purchase order(s) on this truck.", "warn");
    if (status === "Verified" && !vehicle.trim()) return void toast("Enter the truck's number plate.", "warn");
    if (status === "Rejected" && !remarks.trim()) return void toast("Say why the delivery is turned away.", "warn");
    setSaving(true);
    const r = await verifyReceivingBulk({
      ...post.post, references: picked, gate_verification_status: status,
      vehicle_no: vehicle.trim() || undefined, driver_name: driver.trim() || undefined, remarks: remarks.trim() || undefined,
    });
    setSaving(false);
    if (isError(r)) return void toast(r.error, "error");
    const failed = r.results.filter((x) => x.error);
    if (failed.length) toast(failed.map((x) => `${x.reference}: ${x.error}`).join(" "), "error");
    const done = r.results.length - failed.length;
    if (done) toast(`${done} delivery record${done === 1 ? "" : "s"} ${status === "Verified" ? "checked in" : "turned away"}.`, status === "Verified" ? "ok" : "warn");
    setFound(null);
    void loadTrucks();
    void log.load();
  };

  const rows = log.page?.rows ?? [];
  const gateUser = boot.can_check_in_out;

  return (
    <PageShell title="Receiving check" eyebrow="Gate operations" actions={<><ScopePicker /><GatePostPicker {...post} /></>}>
      <Card
        title="Check in a delivery"
        actions={<TogglePill pressed={byBadge} onPressedChange={setByBadge}>Supplier badge</TogglePill>}
      >
        <div className="flex flex-col gap-4 p-4">
          <LookupBox
            label={byBadge ? "Supplier badge" : "PO number or supplier"}
            placeholder={byBadge ? "Scan the supplier badge" : "Scan or type the PO number, or the supplier's name"}
            busy={looking}
            onLookup={lookup}
          />
          <PostLine farm={post.farm} gate={post.gate} />
          {found && (
            <div className="flex flex-col gap-4 rounded-[var(--sd-radius-md,10px)] border border-[var(--sd-line)] p-4">
              <div className="text-[15px] font-semibold">{found.supplier_name}{found.badge ? <span className="ml-2 text-[12px] font-normal text-[var(--sd-quiet)]">badge {found.badge}</span> : null}</div>
              <div className="flex flex-col gap-2">
                {found.pos.map((po) => (
                  <label key={po.purchase_order} className="flex items-start gap-2 text-[13px]">
                    <input
                      type="checkbox"
                      className="mt-1"
                      checked={picked.includes(po.purchase_order)}
                      onChange={(e) => setPicked((cur) => (e.target.checked ? [...cur, po.purchase_order] : cur.filter((x) => x !== po.purchase_order)))}
                    />
                    <span className="flex-1">
                      <span className="font-medium">{po.purchase_order}</span>{" "}
                      <Verdict ok={po.is_authorized}>{po.is_authorized ? po.po_status : !po.supplier_active ? "Supplier disabled" : `Not open (${po.po_status})`}</Verdict>
                      <span className="block text-[12px] text-[var(--sd-quiet)]">
                        {[po.items_summary, po.schedule_date && `due ${po.schedule_date}`].filter(Boolean).join(" · ")}
                      </span>
                    </span>
                  </label>
                ))}
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="flex flex-col gap-1.5"><Label htmlFor="rc-veh">Number plate</Label><Input id="rc-veh" value={vehicle} onChange={(e) => setVehicle(e.target.value.toUpperCase())} /></div>
                <div className="flex flex-col gap-1.5"><Label htmlFor="rc-drv">Driver</Label><Input id="rc-drv" value={driver} onChange={(e) => setDriver(e.target.value)} /></div>
              </div>
              <div className="flex flex-col gap-1.5"><Label htmlFor="rc-rem">Remarks</Label><Textarea id="rc-rem" rows={2} value={remarks} onChange={(e) => setRemarks(e.target.value)} placeholder="Required when turning a delivery away" /></div>
              {gateUser ? (
                <div className="flex justify-end gap-2">
                  <Button variant="outline" onClick={() => setFound(null)} disabled={saving}>Cancel</Button>
                  <Button variant="destructive" onClick={() => decide("Rejected")} disabled={saving}>Turn away</Button>
                  <Button onClick={() => decide("Verified")} disabled={saving}>{saving ? "Saving…" : "Let in"}</Button>
                </div>
              ) : (
                <p className="text-[12px] text-[var(--sd-quiet)]">Only gate guards and security heads check deliveries in.</p>
              )}
            </div>
          )}
        </div>
      </Card>

      <Card title="Trucks inside" actions={<RefreshButton onClick={() => void loadTrucks()} loading={trucks === null} label="Refresh trucks inside" />}>
        <ScrollTable className="mt-3">
          <table className="w-full text-[13px]">
            <thead className={STICKY_HEAD}>
              <tr><th className={TH}>Arrived</th><th className={TH}>Supplier</th><th className={TH}>Purchase orders</th><th className={TH}>Vehicle / driver</th><th className={TH}>Items inside</th><th className={TH} /></tr>
            </thead>
            <tbody>
              {trucks === null ? (
                <TableRowsSkeleton cols={6} rows={3} />
              ) : trucks.length === 0 ? (
                <tr><td colSpan={6} className="px-4 py-8 text-center text-[var(--sd-muted)]">No supplier trucks inside{post.farm ? ` ${post.farm}` : ""} right now.</td></tr>
              ) : (
                trucks.map((t) => (
                  <tr key={t.name} className="border-t border-[var(--sd-line-soft)]">
                    <td className={`${TD} tabular-nums`}>{when(t.arrived_at)}</td>
                    <td className={TD}>{t.supplier_name}</td>
                    <td className={TD}>{t.purchase_orders.join(", ")}</td>
                    <td className={TD}>{t.vehicle_no || "—"}<div className="text-[12px] text-[var(--sd-quiet)]">{t.driver_name}</div></td>
                    <td className={`${TD} tabular-nums`}>{t.items_inside || "—"}</td>
                    <td className={`${TD} text-right`}>
                      {gateUser && <Button size="sm" variant="outline" onClick={() => setLeaving(t)}><LogOut className="mr-1 h-3.5 w-3.5" /> Check out</Button>}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </ScrollTable>
        <div className="h-2" />
      </Card>

      <Card
        title="Receiving log"
        actions={
          <>
            <DateRangePicker label="Dates" value={log.range} onChange={log.setRange} />
            <FilterSelect label="Result" value={log.status} onChange={log.setStatus} options={["Verified", "Rejected"]} allLabel="All results" />
            <SearchInput value={log.search} onChange={log.setSearch} placeholder="PO, supplier, vehicle" aria-label="Search receiving log" />
            <ClearFiltersPill active={log.dirty} onClear={log.clear} />
            <RefreshButton onClick={() => void log.load()} loading={log.loading} label="Refresh receiving log" />
          </>
        }
      >
        <ScrollTable className="mt-3">
          <table className="w-full text-[13px]">
            <thead className={STICKY_HEAD}>
              <tr><th className={TH}>Arrived</th><th className={TH}>PO / supplier</th><th className={TH}>Vehicle / driver</th><th className={TH}>{T.Site} · gate</th><th className={TH}>Result</th><th className={TH}>Left</th></tr>
            </thead>
            <tbody>
              {log.loading && !log.page ? (
                <TableRowsSkeleton cols={6} rows={4} />
              ) : rows.length === 0 ? (
                <tr><td colSpan={6} className="px-4 py-8 text-center text-[var(--sd-muted)]">No deliveries checked in this period.</td></tr>
              ) : (
                rows.map((r) => (
                  <tr key={r.name} className="border-t border-[var(--sd-line-soft)]">
                    <td className={`${TD} tabular-nums`}>{when(r.gate_arrival_time)}</td>
                    <td className={TD}>{r.purchase_order}<div className="text-[12px] text-[var(--sd-quiet)]">{r.supplier}</div></td>
                    <td className={TD}>{r.vehicle_no || "—"}<div className="text-[12px] text-[var(--sd-quiet)]">{r.driver_name}</div></td>
                    <td className={TD}>{[r.farm, r.gate].filter(Boolean).join(" · ") || "—"}</td>
                    <td className={TD}><Verdict ok={r.gate_verification_status === "Verified"}>{r.gate_verification_status === "Verified" ? "Let in" : "Turned away"}</Verdict><div className="mt-1 text-[12px] text-[var(--sd-quiet)]">{r.gate_verified_by_name}</div></td>
                    <td className={TD}>
                      {r.gate_departure_time ? when(r.gate_departure_time) : r.gate_verification_status === "Verified" ? "Inside" : "—"}
                      <div className="text-[12px] text-[var(--sd-quiet)]">{r.purchase_receipt || r.supplier_delivery_note || r.no_receipt_reason || ""}</div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </ScrollTable>
        <Pager start={log.start} total={log.page?.total ?? 0} page={LOG_PAGE} loading={log.loading} onChange={log.setStart} />
      </Card>

      <DepartureDialog truck={leaving} post={post.post} onClose={() => setLeaving(null)} onDone={() => { void loadTrucks(); void log.load(); }} />
    </PageShell>
  );
}

/** The exit check: what left with the truck, and the receipt for what stayed. */
function DepartureDialog({ truck, post, onClose, onDone }: {
  truck: Truck | null; post: { checking_farm?: string; gate?: string }; onClose: () => void; onDone: () => void;
}) {
  const toast = useToast();
  const [dep, setDep] = useState<Departure | null>(null);
  const [out, setOut] = useState<string[]>([]);
  const [receipt, setReceipt] = useState("");
  const [dn, setDn] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setDep(null);
    setReceipt(""); setDn(""); setReason("");
    if (!truck) return;
    void getDeparture(truck.name).then((r) => {
      if (isError(r)) return void toast(r.error, "error");
      setDep(r);
      setOut(r.items.map((i) => i.name));
    });
  }, [truck, toast]);

  const save = async () => {
    if (!truck) return;
    if (!receipt.trim() && !dn.trim() && !reason.trim()) {
      return void toast("Enter the goods receipt note, the supplier's delivery note, or why there is none.", "warn");
    }
    setBusy(true);
    const r = await confirmDeparture({
      ...post,
      name: truck.name,
      receipts: receipt.trim() ? [receipt.trim()] : undefined,
      supplier_delivery_note: dn.trim() || undefined,
      no_receipt_reason: reason.trim() || undefined,
      items_out: dep && dep.items.length ? out : undefined,
    });
    setBusy(false);
    if (isError(r)) return void toast(r.error, "error");
    toast(`${truck.supplier_name}'s truck checked out.`, "ok");
    onClose();
    onDone();
  };

  return (
    <Dialog open={!!truck} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Check out {truck?.vehicle_no || "truck"}</DialogTitle>
          <DialogDescription>{truck?.supplier_name} · {truck?.purchase_orders.join(", ")}</DialogDescription>
        </DialogHeader>
        {dep && dep.items.length > 0 && (
          <div className="flex flex-col gap-1.5">
            <Label>Declared items leaving with the truck</Label>
            {dep.items.map((i) => (
              <label key={i.name} className="flex items-center gap-2 text-[13px]">
                <input type="checkbox" checked={out.includes(i.name)} onChange={(e) => setOut((c) => (e.target.checked ? [...c, i.name] : c.filter((x) => x !== i.name)))} />
                {i.item}{i.qty && i.qty > 1 ? ` ×${i.qty}` : ""}{i.serial_notes ? <span className="text-[var(--sd-quiet)]"> · {i.serial_notes}</span> : null}
              </label>
            ))}
            <p className="text-[12px] text-[var(--sd-quiet)]">Anything left unticked is recorded as not seen leaving.</p>
          </div>
        )}
        <div className="flex flex-col gap-1.5"><Label htmlFor="dp-grn">Goods receipt note</Label><Input id="dp-grn" value={receipt} onChange={(e) => setReceipt(e.target.value)} placeholder="Scan or type the Purchase Receipt" /></div>
        <div className="flex flex-col gap-1.5"><Label htmlFor="dp-dn">Or the supplier's delivery note number</Label><Input id="dp-dn" value={dn} onChange={(e) => setDn(e.target.value)} /></div>
        <div className="flex flex-col gap-1.5"><Label htmlFor="dp-why">Or why there is no receipt</Label><Textarea id="dp-why" rows={2} value={reason} onChange={(e) => setReason(e.target.value)} /></div>
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button onClick={save} disabled={busy || !dep}>{busy ? "Saving…" : "Confirm departure"}</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
