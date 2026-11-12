import { useCallback, useEffect, useMemo, useState } from "react";
import { LogIn, LogOut } from "lucide-react";
import { Card, TD, TH } from "@/components/Card";
import { ClearFiltersPill } from "@/components/ClearFiltersPill";
import { DateRangePicker, type DateRange } from "@/components/DateRangePicker";
import { EmployeePicker } from "@/components/EmployeePicker";
import { FeatureOff } from "@/components/FeatureOff";
import { FilterSelect } from "@/components/FilterSelect";
import { GatePostPicker, PostLine } from "@/components/GatePostPicker";
import { TableRowsSkeleton } from "@/components/Loading";
import { PageShell } from "@/components/PageShell";
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
import { isError } from "@/lib/frappe";
import { staffIn, staffInside, staffMoves, staffOut, type StaffInside, type StaffMove } from "@/lib/gate-api";
import { useGatePost } from "@/lib/gate-post";
import { useScope, useTerms } from "@/lib/scope";
import { todayISO } from "@/lib/utils";
import { when } from "@/lib/when";

/** Staff (and badge-holding contractors) through the gate. */
export function Staff() {
  const T = useTerms();
  const { boot, scope, farmsInScope } = useScope();
  const toast = useToast();
  const post = useGatePost();
  const [inside, setInside] = useState<StaffInside[] | null>(null);
  const [moves, setMoves] = useState<StaffMove[] | null>(null);
  const [range, setRange] = useState<DateRange>({ from: todayISO(), to: todayISO() });
  const [who, setWho] = useState("");
  const [search, setSearch] = useState("");
  const [signingIn, setSigningIn] = useState(false);
  const [busy, setBusy] = useState("");

  const loadInside = useCallback(async () => {
    const r = await staffInside({ checking_farm: post.farm || undefined });
    if (isError(r)) return void toast(r.error, "error");
    setInside(r.staff ?? []);
  }, [post.farm, toast]);

  const loadMoves = useCallback(async () => {
    setMoves(null);
    const r = await staffMoves({ checking_farm: post.farm || undefined, from_date: range.from, to_date: range.to });
    if (isError(r)) return void toast(r.error, "error");
    setMoves(r.staff ?? []);
  }, [post.farm, range, toast]);

  const on = boot.features.feature_staff_checkin !== false;
  useEffect(() => {
    if (on) void loadInside();
  }, [loadInside, on]);
  useEffect(() => {
    if (on) void loadMoves();
  }, [loadMoves, on]);

  // The movement log comes back for the date range; scope and search narrow it here.
  const shown = useMemo(() => {
    const q = search.trim().toLowerCase();
    const farms = scope.farm ? [scope.farm] : scope.company ? farmsInScope : null;
    return (moves ?? []).filter(
      (m) =>
        (!farms || (m.farm && farms.includes(m.farm))) &&
        (!who || m.party_type === who) &&
        (!q || [m.employee_name, m.employee, m.plate, m.badge].some((v) => (v || "").toLowerCase().includes(q))),
    );
  }, [moves, scope, farmsInScope, who, search]);

  if (!on) return <FeatureOff title="Staff movement" what="Staff check-in" />;

  const signOut = async (s: StaffInside) => {
    setBusy(s.name);
    const r = await staffOut({ ...post.post, attendance_name: s.name, exit_gate: post.gate || undefined });
    setBusy("");
    if (isError(r)) return void toast(r.error, "error");
    toast(`${s.employee_name} signed out.`, "ok", { hint: r.working_hours ? `${Number(r.working_hours).toFixed(1)} h on site` : undefined });
    void loadInside();
    void loadMoves();
  };

  const parties = Array.from(new Set((moves ?? []).map((m) => m.party_type))).sort();
  const dirty = !!search || !!who || range.from !== todayISO() || range.to !== todayISO();

  return (
    <PageShell
      title="Staff movement"
      eyebrow="Gate operations"
      actions={
        <>
          <ScopePicker />
          <GatePostPicker {...post} />
          {boot.can_check_in_out && (
            <ToolbarButton onClick={() => setSigningIn(true)}>
              <LogIn className="h-4 w-4" /> Sign in staff
            </ToolbarButton>
          )}
        </>
      }
    >
      <PostLine farm={post.farm} gate={post.gate} />
      <Card title={`On site now${inside ? ` (${inside.length})` : ""}`} actions={<RefreshButton onClick={() => void loadInside()} loading={inside === null} label="Refresh staff on site" />}>
        <ScrollTable className="mt-3">
          <table className="w-full text-[13px]">
            <thead className={STICKY_HEAD}><tr><th className={TH}>Name</th><th className={TH}>Department</th><th className={TH}>In since</th><th className={TH} /></tr></thead>
            <tbody>
              {inside === null ? (
                <TableRowsSkeleton cols={4} rows={3} />
              ) : inside.length === 0 ? (
                <tr><td colSpan={4} className="px-4 py-8 text-center text-[var(--sd-muted)]">Nobody signed in through the gate today.</td></tr>
              ) : (
                inside.map((s) => (
                  <tr key={s.name} className="border-t border-[var(--sd-line-soft)]">
                    <td className={TD}>{s.employee_name}<div className="text-[12px] text-[var(--sd-quiet)]">{s.employee}</div></td>
                    <td className={TD}>{s.department || "—"}</td>
                    <td className={`${TD} tabular-nums`}>{when(s.in_time)}</td>
                    <td className={`${TD} text-right`}>
                      {boot.can_check_in_out && (
                        <Button size="sm" variant="outline" disabled={busy === s.name} onClick={() => signOut(s)}>
                          <LogOut className="mr-1 h-3.5 w-3.5" /> {busy === s.name ? "Signing out…" : "Sign out"}
                        </Button>
                      )}
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
        title="Movement log"
        actions={
          <>
            <DateRangePicker label="Dates" value={range} onChange={setRange} />
            {parties.length > 1 && <FilterSelect label="Who" value={who} onChange={setWho} options={parties} allLabel="Everyone" />}
            <SearchInput value={search} onChange={setSearch} placeholder="Name, ID, plate, badge" aria-label="Search movements" />
            <ClearFiltersPill active={dirty} onClear={() => { setSearch(""); setWho(""); setRange({ from: todayISO(), to: todayISO() }); }} />
            <RefreshButton onClick={() => void loadMoves()} loading={moves === null} label="Refresh movement log" />
          </>
        }
      >
        <ScrollTable className="mt-3" tall>
          <table className="w-full text-[13px]">
            <thead className={STICKY_HEAD}>
              <tr><th className={TH}>Name</th><th className={TH}>{T.Site}</th><th className={TH}>In</th><th className={TH}>Out</th><th className={TH}>Vehicle</th></tr>
            </thead>
            <tbody>
              {moves === null ? (
                <TableRowsSkeleton cols={5} rows={5} />
              ) : shown.length === 0 ? (
                <tr><td colSpan={5} className="px-4 py-8 text-center text-[var(--sd-muted)]">No gate movements this period.</td></tr>
              ) : (
                shown.map((m) => (
                  <tr key={m.name} className="border-t border-[var(--sd-line-soft)]">
                    <td className={TD}>
                      {m.employee_name || m.employee || "—"}
                      <div className="text-[12px] text-[var(--sd-quiet)]">{[m.party_type, m.badge && `badge #${m.badge}`].filter(Boolean).join(" · ")}</div>
                    </td>
                    <td className={TD}>{m.farm || "—"}</td>
                    <td className={TD}><span className="tabular-nums">{when(m.in_time)}</span><div className="text-[12px] text-[var(--sd-quiet)]">{m.entry_gate}</div></td>
                    <td className={TD}>
                      {m.out_time ? <span className="tabular-nums">{when(m.out_time)}</span> : <span className="font-medium text-[var(--sd-target)]">Inside</span>}
                      <div className="text-[12px] text-[var(--sd-quiet)]">{m.exit_gate}</div>
                    </td>
                    <td className={TD}>{m.plate || "—"}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </ScrollTable>
        <div className="h-2" />
      </Card>

      <SignInDialog open={signingIn} post={post} onClose={() => setSigningIn(false)} onDone={() => { void loadInside(); void loadMoves(); }} />
    </PageShell>
  );
}

function SignInDialog({ open, post, onClose, onDone }: {
  open: boolean; post: ReturnType<typeof useGatePost>; onClose: () => void; onDone: () => void;
}) {
  const toast = useToast();
  const [employee, setEmployee] = useState("");
  const [label, setLabel] = useState("");
  const [plate, setPlate] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setEmployee("");
    setPlate("");
  }, [open]);

  const save = async () => {
    if (!employee) return void toast("Choose the staff member.", "warn");
    setBusy(true);
    const r = await staffIn({ ...post.post, employee, vehicle_plate: plate.trim() || undefined, entry_gate: post.gate || undefined });
    setBusy(false);
    if (isError(r)) return void toast(r.error, "error");
    toast(`${r.employee_name || label} signed in.`, "ok");
    onClose();
    onDone();
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Sign in staff</DialogTitle>
          <DialogDescription>Records the staff member entering {post.farm ? `${post.farm}${post.gate ? ` at ${post.gate}` : ""}` : "the gate"}.</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="st-emp">Staff member</Label>
          <EmployeePicker id="st-emp" value={employee} onChange={(id, l) => { setEmployee(id); setLabel(l); }} />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="st-plate">Vehicle plate (if driving in)</Label>
          <Input id="st-plate" value={plate} onChange={(e) => setPlate(e.target.value.toUpperCase())} />
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button onClick={save} disabled={busy}>{busy ? "Saving…" : "Sign in"}</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
