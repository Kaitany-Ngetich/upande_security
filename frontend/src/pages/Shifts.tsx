import { useCallback, useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronRight, ChevronsDownUp, ChevronsUpDown, Plus } from "lucide-react";
import { Card, TD, TH, Verdict } from "@/components/Card";
import { ClearFiltersPill } from "@/components/ClearFiltersPill";
import { DateRangePicker, type DateRange } from "@/components/DateRangePicker";
import { EmployeePicker } from "@/components/EmployeePicker";
import { FilterSelect } from "@/components/FilterSelect";
import { KpiCard, KpiGrid } from "@/components/KpiCard";
import { TableRowsSkeleton } from "@/components/Loading";
import { PageShell } from "@/components/PageShell";
import { RefreshButton } from "@/components/RefreshButton";
import { ScopePicker } from "@/components/ScopePicker";
import { ScrollTable, STICKY_HEAD } from "@/components/ScrollTable";
import { CoverDialog } from "@/components/scheduling/CoverDialog";
import { useToast } from "@/components/Toast";
import { ToolbarButton } from "@/components/ToolbarButton";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Picker } from "@/components/ui/picker";
import { Textarea } from "@/components/ui/textarea";
import { isError } from "@/lib/frappe";
import { cancelShift, createShift, schedulingOptions, shiftBoard, type ShiftBoard, type ShiftRow, type SchedulingOptions } from "@/lib/scheduling-api";
import { useScope, useTerms } from "@/lib/scope";
import { cn, todayISO } from "@/lib/utils";
import { when } from "@/lib/when";

/** Did the guard clock in for this shift, and on time? */
function Attendance({ r }: { r: ShiftRow }) {
  const b = r.biometric;
  if (b?.clock_in) {
    return (
      <span className="text-[12px]">
        <Verdict ok={b.result !== "Late"}>{b.result === "Late" ? `Late ${b.late_min} min` : "On time"}</Verdict>
        <span className="ml-1 tabular-nums text-[var(--sd-muted)]">{when(b.clock_in)}</span>
        {b.departure === "Left early" && <div className="text-[var(--sd-target)]">Left {b.early_min} min early</div>}
      </span>
    );
  }
  if (r.checked_in) return <Verdict ok>Checked in</Verdict>;
  if (b?.result) return <Verdict ok={false}>{b.result}</Verdict>;
  return r.status === "Scheduled" ? <span className="text-[12px] text-[var(--sd-quiet)]">—</span> : <span className="text-[12px] text-[var(--sd-target)]">Not checked in</span>;
}

const COLLAPSE_KEY = "secdash2.shifts.collapsed";
const NO_FARM = "No farm";
const sectionId = (farm: string) => `shifts-farm-${farm.replace(/[^a-z0-9]+/gi, "-")}`;

/** A farm's shifts summed for its section header. */
function farmStats(rows: ShiftRow[]) {
  let inn = 0, late = 0, missing = 0, cancelled = 0;
  for (const r of rows) {
    if (r.status === "Cancelled") { cancelled++; continue; }
    const res = r.biometric?.result;
    if (r.biometric?.clock_in || r.checked_in) inn++;
    if (res === "Late") late++;
    if (res === "Absent" || res === "No clock-in") missing++;
  }
  return { total: rows.length - cancelled, inn, late, missing, cancelled };
}

/** Which farms are folded, remembered in this browser. Farms not seen before
 *  start folded when there are many, so a big group opens as a list of farms. */
function useCollapsed(farms: string[]) {
  const [saved, setSaved] = useState<Record<string, boolean>>(() => {
    try {
      return JSON.parse(localStorage.getItem(COLLAPSE_KEY) || "{}");
    } catch {
      return {};
    }
  });
  const isCollapsed = (farm: string) => saved[farm] ?? farms.length > 3;
  const write = (next: Record<string, boolean>) => {
    setSaved(next);
    try {
      localStorage.setItem(COLLAPSE_KEY, JSON.stringify(next));
    } catch {
      /* private window: not remembered */
    }
  };
  return {
    isCollapsed,
    toggle: (farm: string) => write({ ...saved, [farm]: !isCollapsed(farm) }),
    open: (farm: string) => write({ ...saved, [farm]: false }),
    setAll: (collapsed: boolean) => write(Object.fromEntries(farms.map((f) => [f, collapsed]))),
  };
}

/** Who is on which farm's shift, whether they turned up, and who covers the days off. */
export function Shifts() {
  const T = useTerms();
  const toast = useToast();
  const { scope } = useScope();
  const [opts, setOpts] = useState<SchedulingOptions | null>(null);
  const [range, setRange] = useState<DateRange>({ from: todayISO(), to: todayISO() });
  const [shiftType, setShiftType] = useState("");
  const [status, setStatus] = useState("");
  const [board, setBoard] = useState<ShiftBoard | null>(null);
  const [loading, setLoading] = useState(true);
  const [booking, setBooking] = useState(false);
  const [cover, setCover] = useState<{ guard: string; guard_name: string; date: string; farm?: string } | null>(null);
  const [cancelling, setCancelling] = useState<ShiftRow | null>(null);

  useEffect(() => {
    void schedulingOptions().then((r) => (isError(r) ? toast(r.error, "error") : setOpts(r)));
  }, [toast]);

  const load = useCallback(async () => {
    setLoading(true);
    const r = await shiftBoard({
      from_date: range.from, to_date: range.to, company: scope.company || undefined, farm: scope.farm || undefined,
      shift_type: shiftType || undefined, status: status || undefined,
    });
    setLoading(false);
    if (isError(r)) return void toast(r.error, "error");
    setBoard(r);
  }, [range, scope, shiftType, status, toast]);
  useEffect(() => {
    void load();
  }, [load]);

  const s = board?.summary;
  const plan = !!opts?.can_plan;
  const groups = useMemo(() => {
    const m = new Map<string, ShiftRow[]>();
    for (const r of board?.rows ?? []) {
      const f = r.farm || NO_FARM;
      m.set(f, [...(m.get(f) ?? []), r]);
    }
    return [...m.entries()].sort(([a], [b]) => (a === NO_FARM ? 1 : b === NO_FARM ? -1 : a.localeCompare(b)));
  }, [board]);
  const farms = groups.map(([f]) => f);
  const fold = useCollapsed(farms);
  const nameOf = (farm: string) => (farm === NO_FARM ? `No ${T.site}` : farm);
  const jumpTo = (farm: string) => {
    if (!farm) return;
    fold.open(farm);
    // After the section has opened.
    window.setTimeout(() => document.getElementById(sectionId(farm))?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
  };
  const dirty = !!shiftType || !!status || range.from !== todayISO() || range.to !== todayISO();

  return (
    <PageShell
      title="Shifts"
      eyebrow="Scheduling"
      actions={
        <>
          <ScopePicker />
          <DateRangePicker label="Dates" value={range} onChange={setRange} />
          <FilterSelect label="Shift" value={shiftType} onChange={setShiftType} options={opts?.shift_types ?? []} allLabel="All shifts" />
          <FilterSelect label="Status" value={status} onChange={setStatus} options={["Scheduled", "Active", "Ended", "Cancelled"]} allLabel="All statuses" />
          <ClearFiltersPill active={dirty} onClear={() => { setShiftType(""); setStatus(""); setRange({ from: todayISO(), to: todayISO() }); }} />
          <RefreshButton onClick={() => void load()} loading={loading} label="Refresh shifts" />
          {plan && <ToolbarButton onClick={() => setBooking(true)}><Plus className="h-4 w-4" /> Book shift</ToolbarButton>}
        </>
      }
    >
      <KpiGrid cols={5}>
        <KpiCard label="Shifts" value={s?.total_assignments ?? 0} hint={(s?.shift_type_summary ?? []).map((t) => `${t.total} ${t.shift_type}`).join(" · ") || undefined} loading={!board} />
        <KpiCard label="Checked in" value={s?.checked_in_total ?? 0} hint={`of ${s?.on_duty_total ?? 0} on duty`} loading={!board} />
        <KpiCard label={`${T.Sites} covered now`} value={s ? `${s.farms_covered}/${s.farms_total}` : "0"} hint={`${s?.unfilled_slots ?? 0} shift slot${s?.unfilled_slots === 1 ? "" : "s"} unfilled`} tone={s?.unfilled_slots ? "warning" : "default"} loading={!board} />
        <KpiCard label="Days off" value={s?.off_count ?? 0} hint={`${s?.off_uncovered ?? 0} without cover`} tone={s?.off_uncovered ? "critical" : "default"} loading={!board} />
        <KpiCard label="Guards on rotation" value={s?.guards_on_rotation ?? 0} loading={!board} />
      </KpiGrid>

      {!!board?.coverage_board.length && (
        <Card title={`Right now, by ${T.site}`}>
          <div className="grid gap-3 p-4 sm:grid-cols-2 xl:grid-cols-3">
            {board.coverage_board.map((f) => (
              <button
                type="button" key={f.farm} onClick={() => jumpTo(f.farm || NO_FARM)} title={`Show ${nameOf(f.farm || NO_FARM)}'s shifts`}
                className="rounded-[var(--sd-radius-md,10px)] border border-[var(--sd-line-soft)] p-3 text-left hover:border-[var(--sd-line)] hover:bg-[var(--sd-line-soft)]/40"
              >
                <div className="mb-1.5 text-[13px] font-semibold">{nameOf(f.farm || NO_FARM)}</div>
                {f.shifts.map((sh) => (
                  <div key={sh.shift_type} className="flex justify-between gap-2 text-[13px]">
                    <span className="text-[var(--sd-muted)]">{sh.shift_type}</span>
                    {sh.guard_name ? <span>{sh.guard_name}</span> : <span className="font-medium text-[var(--sd-data-red)]">Unfilled</span>}
                  </div>
                ))}
              </button>
            ))}
          </div>
        </Card>
      )}

      {!!board?.off_days.length && (
        <Card title="Days off">
          <ScrollTable className="mt-3">
            <table className="w-full text-[13px]">
              <thead className={STICKY_HEAD}><tr><th className={TH}>Date</th><th className={TH}>Guard</th><th className={TH}>{T.Site}</th><th className={TH}>Cover</th><th className={TH} /></tr></thead>
              <tbody>
                {board.off_days.map((o) => (
                  <tr key={`${o.guard}-${o.date}`} className="border-t border-[var(--sd-line-soft)]">
                    <td className={`${TD} tabular-nums`}>{o.date}</td>
                    <td className={TD}>{o.guard_name}</td>
                    <td className={TD}>{o.farm || "—"}</td>
                    <td className={TD}>{o.covered_by || <span className="font-medium text-[var(--sd-data-red)]">No cover</span>}</td>
                    <td className={`${TD} text-right`}>
                      {plan && (
                        <Button size="sm" variant="outline" onClick={() => setCover({ guard: o.guard, guard_name: o.guard_name, date: o.date, farm: o.farm || undefined })}>
                          {o.covered_by ? "Change cover" : "Find cover"}
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </ScrollTable>
          <div className="h-2" />
        </Card>
      )}

      <Card
        title={groups.length ? `Shifts by ${T.site} (${groups.length})` : "Shifts"}
        actions={
          groups.length > 1 && (
            <>
              <FilterSelect
                label={`Jump to ${T.site}`} value="" onChange={jumpTo} placeholder={`Jump to ${T.site}`}
                options={groups.map(([f, rows]) => ({ value: f, label: `${nameOf(f)} (${farmStats(rows).total})` }))}
              />
              <Button size="sm" variant="outline" onClick={() => fold.setAll(false)}><ChevronsUpDown className="mr-1 h-3.5 w-3.5" /> Expand all</Button>
              <Button size="sm" variant="outline" onClick={() => fold.setAll(true)}><ChevronsDownUp className="mr-1 h-3.5 w-3.5" /> Collapse all</Button>
            </>
          )
        }
      >
        <ScrollTable tall className="mt-3">
          <table className="w-full text-[13px]">
            <thead className={STICKY_HEAD}>
              <tr><th className={TH}>Guard</th><th className={TH}>{T.Area}</th><th className={TH}>Shift</th><th className={TH}>From – to</th><th className={TH}>Status</th><th className={TH}>Attendance</th><th className={TH} /></tr>
            </thead>
            {loading && !board ? (
              <tbody><TableRowsSkeleton cols={7} rows={6} /></tbody>
            ) : groups.length === 0 ? (
              <tbody><tr><td colSpan={7} className="px-4 py-10 text-center text-[var(--sd-muted)]">No shifts in this period.</td></tr></tbody>
            ) : (
              groups.map(([farm, rows]) => {
                const st = farmStats(rows);
                const closed = fold.isCollapsed(farm);
                return (
                  <tbody key={farm} id={sectionId(farm)} className="scroll-mt-12">
                    <tr className="border-t-2 border-[var(--sd-line)] bg-[var(--sd-line-soft)]/50">
                      <td colSpan={7} className="p-0">
                        <button
                          type="button" aria-expanded={!closed} onClick={() => fold.toggle(farm)}
                          className="flex w-full flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2.5 text-left hover:bg-[var(--sd-line-soft)]"
                        >
                          <span className="flex items-center gap-1.5 font-semibold text-[var(--sd-ink)]">
                            {closed ? <ChevronRight className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                            {nameOf(farm)}
                          </span>
                          <span className="text-[12px] tabular-nums text-[var(--sd-muted)]">{st.total} shift{st.total === 1 ? "" : "s"}</span>
                          <span className="text-[12px] tabular-nums text-[var(--sd-muted)]">{st.inn} in</span>
                          {st.late > 0 && <span className="text-[12px] tabular-nums text-[var(--sd-target)]">{st.late} late</span>}
                          {st.missing > 0 && <span className="text-[12px] font-medium tabular-nums text-[var(--sd-data-red)]">{st.missing} absent</span>}
                          {st.cancelled > 0 && <span className="text-[12px] tabular-nums text-[var(--sd-quiet)]">{st.cancelled} cancelled</span>}
                        </button>
                      </td>
                    </tr>
                    {!closed && rows.map((r) => (
                      <tr key={r.name} className={cn("border-t border-[var(--sd-line-soft)] align-top", r.status === "Cancelled" && "opacity-55", loading && "opacity-60")}>
                        <td className={TD}>
                          {r.guard_name}
                          <div className="text-[12px] text-[var(--sd-quiet)]">
                            {r.guard_type === "Internal Guard" ? "Staff (from HR)" : "External"}
                            {r.covering_for_name && ` · covering ${r.covering_for_name}`}
                          </div>
                        </td>
                        <td className={TD}>{r.block || <span className="text-[var(--sd-quiet)]">—</span>}</td>
                        <td className={TD}>{r.shift_type}</td>
                        <td className={`${TD} tabular-nums`}>{when(r.start_date)} – {when(r.end_date)}</td>
                        <td className={TD}>{r.status}</td>
                        <td className={TD}><Attendance r={r} /></td>
                        <td className={`${TD} text-right`}>
                          {plan && r.guard_type === "External Guard" && r.status !== "Cancelled" && r.status !== "Ended" && (
                            <Button size="sm" variant="outline" onClick={() => setCancelling(r)}>Cancel</Button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                );
              })
            )}
          </table>
        </ScrollTable>
        <div className="h-2" />
      </Card>

      {opts && <BookShiftDialog open={booking} opts={opts} onClose={() => setBooking(false)} onDone={load} />}
      <CancelShiftDialog shift={cancelling} onClose={() => setCancelling(null)} onDone={load} />
      <CoverDialog target={cover} onClose={() => setCover(null)} onDone={load} />
    </PageShell>
  );
}

function BookShiftDialog({ open, opts, onClose, onDone }: { open: boolean; opts: SchedulingOptions; onClose: () => void; onDone: () => void }) {
  const T = useTerms();
  const toast = useToast();
  const { scope, farmsInScope } = useScope();
  const [guard, setGuard] = useState("");
  const [farm, setFarm] = useState("");
  const [type, setType] = useState("Day");
  const [date, setDate] = useState(todayISO());
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [remarks, setRemarks] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setGuard("");
    setFarm(scope.farm || (farmsInScope.length === 1 ? farmsInScope[0] : ""));
    setType("Day");
    setDate(todayISO());
    setRemarks("");
  }, [open, scope.farm, farmsInScope]);
  useEffect(() => {
    setStart(opts.times[type]?.start_time ?? "");
    setEnd(opts.times[type]?.end_time ?? "");
  }, [type, opts]);

  const overnight = !!start && !!end && end <= start;
  const save = async () => {
    if (!guard) return void toast("Choose the guard.", "warn");
    if (!farm) return void toast(`Choose the ${T.site}.`, "warn");
    setBusy(true);
    const r = await createShift({ external_guard: guard, farm, shift_type: type, date, start_time: start, end_time: end, remarks: remarks.trim() || undefined });
    setBusy(false);
    if (isError(r)) return void toast(r.error, "error");
    toast(`Shift ${r.name} booked.`, "ok");
    onClose();
    onDone();
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Book a shift</DialogTitle>
          <DialogDescription>One shift for an external guard. Staff guards' shifts come from HR. For many days, use a rotation plan.</DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="flex flex-col gap-1.5 sm:col-span-2">
            <Label htmlFor="bs-guard">Guard</Label>
            <EmployeePicker id="bs-guard" doctype="Security Guard" placeholder="Search guards" value={guard} onChange={(id) => setGuard(id)} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="bs-farm">{T.Site}</Label>
            <Picker id="bs-farm" label={T.Site} value={farm} onChange={setFarm} options={farmsInScope} placeholder={`Choose a ${T.site}`} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="bs-type">Shift</Label>
            <Picker id="bs-type" label="Shift" value={type} onChange={setType} options={opts.shift_types} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="bs-date">Date</Label>
            <Input id="bs-date" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          </div>
          <div className="flex items-end gap-2">
            <div className="flex flex-1 flex-col gap-1.5"><Label htmlFor="bs-start">From</Label><Input id="bs-start" type="time" value={start} onChange={(e) => setStart(e.target.value)} /></div>
            <div className="flex flex-1 flex-col gap-1.5"><Label htmlFor="bs-end">To</Label><Input id="bs-end" type="time" value={end} onChange={(e) => setEnd(e.target.value)} /></div>
          </div>
          {overnight && <p className="text-[12px] text-[var(--sd-quiet)] sm:col-span-2">Runs past midnight: ends the next morning.</p>}
          <div className="flex flex-col gap-1.5 sm:col-span-2">
            <Label htmlFor="bs-rem">Remarks</Label>
            <Textarea id="bs-rem" rows={2} value={remarks} onChange={(e) => setRemarks(e.target.value)} />
          </div>
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button onClick={save} disabled={busy}>{busy ? "Booking…" : "Book shift"}</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function CancelShiftDialog({ shift, onClose, onDone }: { shift: ShiftRow | null; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => setReason(""), [shift]);
  const go = async () => {
    if (!shift) return;
    setBusy(true);
    const r = await cancelShift(shift.name, reason.trim() || undefined);
    setBusy(false);
    if (isError(r)) return void toast(r.error, "error");
    toast(`${shift.guard_name}'s shift cancelled.`, "ok");
    onClose();
    onDone();
  };
  return (
    <Dialog open={!!shift} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Cancel {shift?.guard_name}'s shift?</DialogTitle>
          <DialogDescription>{shift ? `${shift.shift_type} · ${shift.farm} · ${when(shift.start_date)} – ${when(shift.end_date)}. It stays on record as Cancelled. To give a day off with cover, use the monthly schedule.` : ""}</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="cs-why">Reason</Label>
          <Textarea id="cs-why" rows={2} value={reason} onChange={(e) => setReason(e.target.value)} />
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose} disabled={busy}>Keep it</Button>
          <Button variant="destructive" onClick={go} disabled={busy}>{busy ? "Cancelling…" : "Cancel shift"}</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
