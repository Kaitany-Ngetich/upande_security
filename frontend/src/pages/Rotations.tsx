import { useCallback, useEffect, useState } from "react";
import { Plus, X } from "lucide-react";
import { Card, TD, TH, Verdict } from "@/components/Card";
import { EmployeePicker } from "@/components/EmployeePicker";
import { FilterSelect } from "@/components/FilterSelect";
import { TableRowsSkeleton } from "@/components/Loading";
import { PageShell } from "@/components/PageShell";
import { Pager } from "@/components/Pager";
import { RefreshButton } from "@/components/RefreshButton";
import { ScrollTable, STICKY_HEAD } from "@/components/ScrollTable";
import { CoverDialog } from "@/components/scheduling/CoverDialog";
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
import {
  planAction, rotationPlan, rotationPlans, saveRotationPlan, schedulingOptions, togglePreviewDay,
  type PlanDetail, type PlanRow, type PreviewRow, type SchedulingOptions,
} from "@/lib/scheduling-api";
import { useScope, useTerms } from "@/lib/scope";
import { cn, todayISO } from "@/lib/utils";

const PAGE = 50;

function PlanStatus({ s }: { s: string }) {
  return <Verdict ok={s === "Applied" ? true : s === "Cancelled" ? false : null}>{s}</Verdict>;
}

/** Plan an external guard across days and farms, check the days, then book them all at once. */
export function Rotations() {
  const T = useTerms();
  const toast = useToast();
  const [opts, setOpts] = useState<SchedulingOptions | null>(null);
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");
  const [start, setStart] = useState(0);
  const [page, setPage] = useState<{ total: number; rows: PlanRow[]; can_plan: boolean } | null>(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<PlanDetail | "new" | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    void schedulingOptions().then((r) => (isError(r) ? toast(r.error, "error") : setOpts(r)));
  }, [toast]);
  useEffect(() => {
    const t = window.setTimeout(() => setDebounced(search.trim()), 300);
    return () => window.clearTimeout(t);
  }, [search]);
  useEffect(() => setStart(0), [status, debounced]);

  const load = useCallback(async () => {
    setLoading(true);
    const r = await rotationPlans({ status: status || undefined, search: debounced || undefined, start });
    setLoading(false);
    if (isError(r)) return void toast(r.error, "error");
    setPage(r);
  }, [status, debounced, start, toast]);
  useEffect(() => {
    void load();
  }, [load]);

  const plan = !!page?.can_plan;

  return (
    <PageShell
      title="Rotation plans"
      eyebrow="Scheduling"
      actions={
        <>
          <FilterSelect label="Status" value={status} onChange={setStatus} options={["Draft", "Applied", "Cancelled"]} allLabel="All plans" />
          <SearchInput value={search} onChange={setSearch} placeholder="Guard name" aria-label="Search plans by guard" />
          <RefreshButton onClick={() => void load()} loading={loading} label="Refresh plans" />
          {plan && opts && <ToolbarButton onClick={() => setEditing("new")}><Plus className="h-4 w-4" /> New plan</ToolbarButton>}
        </>
      }
      description={`A plan moves one external guard through ${T.sites} every few days (and through shifts, if set). Preview it day by day, mark days off with cover, then apply it to book one shift per day.`}
    >
      <Card>
        <ScrollTable tall>
          <table className="w-full text-[13px]">
            <thead className={STICKY_HEAD}>
              <tr><th className={TH}>Guard</th><th className={TH}>Period</th><th className={TH}>{T.Sites}</th><th className={TH}>Shift</th><th className={TH}>Every</th><th className={TH}>Status</th></tr>
            </thead>
            <tbody>
              {loading && !page ? (
                <TableRowsSkeleton cols={6} rows={5} />
              ) : (page?.rows.length ?? 0) === 0 ? (
                <tr><td colSpan={6} className="px-4 py-10 text-center text-[var(--sd-muted)]">No rotation plans.</td></tr>
              ) : (
                page!.rows.map((r) => (
                  <tr
                    key={r.name} tabIndex={0} onClick={() => setOpen(r.name)} onKeyDown={(e) => e.key === "Enter" && setOpen(r.name)}
                    className={cn("cursor-pointer border-t border-[var(--sd-line-soft)] hover:bg-[var(--sd-line-soft)]/50", loading && "opacity-60")}
                  >
                    <td className={TD}>{r.guard_name}<div className="text-[12px] text-[var(--sd-quiet)]">{r.name}</div></td>
                    <td className={`${TD} tabular-nums`}>{r.start_date} → {r.end_date}</td>
                    <td className={TD}>{r.farms.join(" → ") || "—"}</td>
                    <td className={TD}>{r.rotate_shifts ? "Rotating" : r.shift_type}<div className="text-[12px] tabular-nums text-[var(--sd-quiet)]">{r.start_time}–{r.end_time}</div></td>
                    <td className={TD}>{r.rotation_interval_days} day{r.rotation_interval_days === 1 ? "" : "s"}</td>
                    <td className={TD}><PlanStatus s={r.status} /></td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </ScrollTable>
        <Pager start={start} total={page?.total ?? 0} page={PAGE} loading={loading} onChange={setStart} />
      </Card>

      {opts && editing && (
        <PlanForm
          plan={editing === "new" ? null : editing}
          opts={opts}
          onClose={() => setEditing(null)}
          onSaved={(name) => { setEditing(null); void load(); setOpen(name); }}
        />
      )}
      <PlanDialog name={open} onClose={() => setOpen(null)} onChanged={load} onEdit={(p) => { setOpen(null); setEditing(p); }} />
    </PageShell>
  );
}

function PlanForm({ plan, opts, onClose, onSaved }: {
  plan: PlanDetail | null; opts: SchedulingOptions; onClose: () => void; onSaved: (name: string) => void;
}) {
  const T = useTerms();
  const toast = useToast();
  const { farmsInScope } = useScope();
  const [guard, setGuard] = useState(plan?.external_guard ?? "");
  const [type, setType] = useState(plan?.shift_type ?? "Day");
  const [from, setFrom] = useState(plan?.start_date ?? todayISO());
  const [to, setTo] = useState(plan?.end_date ?? "");
  const [every, setEvery] = useState(String(plan?.rotation_interval_days ?? 7));
  const [farms, setFarms] = useState<string[]>(plan?.farms.map((f) => f.farm) ?? []);
  const [rotate, setRotate] = useState(!!plan?.rotate_shifts);
  const [seq, setSeq] = useState<string[]>(plan?.shift_sequence.length ? plan.shift_sequence : ["Day", "Night"]);
  const [changeEvery, setChangeEvery] = useState(String(plan?.shift_change_every_days ?? 7));
  const [remarks, setRemarks] = useState(plan?.remarks ?? "");
  const [busy, setBusy] = useState(false);

  const save = async () => {
    const problems = [
      !guard && "Choose the guard.",
      !farms.length && `Add at least one ${T.site}.`,
      !to && "Choose the end date.",
      to && to < from && "The end date is before the start.",
      !(Number(every) >= 1) && "Rotate at least every 1 day.",
    ].filter(Boolean) as string[];
    if (problems.length) return void toast(problems.join(" "), "warn");
    setBusy(true);
    const r = await saveRotationPlan({
      name: plan?.name, external_guard: guard, shift_type: rotate ? seq[0] : type, start_date: from, end_date: to,
      rotation_interval_days: Number(every), farms: farms.map((farm) => ({ farm })), rotate_shifts: rotate ? 1 : 0,
      shift_sequence: rotate ? seq : [], shift_change_every_days: rotate ? Number(changeEvery) : null, remarks: remarks.trim() || null,
      ...(rotate ? {} : { start_time: opts.times[type]?.start_time, end_time: opts.times[type]?.end_time }),
    });
    setBusy(false);
    if (isError(r)) return void toast(r.error, "error");
    toast(`Plan ${r.name} saved as Draft.`, "ok", { hint: "Preview it, then apply." });
    onSaved(r.name);
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{plan ? `Edit ${plan.name}` : "New rotation plan"}</DialogTitle>
          <DialogDescription>Saved as a Draft: nothing is booked until you apply it.</DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="flex flex-col gap-1.5 sm:col-span-2">
            <Label htmlFor="rp-guard">External guard</Label>
            {plan ? <span className="text-[13px]">{plan.guard_name}</span> : <EmployeePicker id="rp-guard" doctype="Security Guard" placeholder="Search guards" value={guard} onChange={(id) => setGuard(id)} />}
          </div>
          <div className="flex flex-col gap-1.5"><Label htmlFor="rp-from">From</Label><Input id="rp-from" type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></div>
          <div className="flex flex-col gap-1.5"><Label htmlFor="rp-to">To</Label><Input id="rp-to" type="date" value={to} min={from} onChange={(e) => setTo(e.target.value)} /></div>
          <div className="flex flex-col gap-1.5 sm:col-span-2">
            <Label>{T.Sites}, in the order the guard moves through them</Label>
            <div className="flex flex-wrap items-center gap-1.5">
              {farms.map((f, i) => (
                <span key={`${f}-${i}`} className="inline-flex items-center gap-1 rounded-full bg-[var(--sd-line-soft)] px-2.5 py-1 text-[12px]">
                  {i + 1}. {f}
                  <button type="button" aria-label={`Remove ${f}`} onClick={() => setFarms((c) => c.filter((_, j) => j !== i))}><X className="h-3 w-3" /></button>
                </span>
              ))}
              <div className="w-48">
                <Picker label={`Add a ${T.site}`} value="" onChange={(v) => v && setFarms((c) => [...c, v])} options={farmsInScope} placeholder={`+ Add a ${T.site}`} />
              </div>
            </div>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="rp-every">Move to the next {T.site} every (days)</Label>
            <Input id="rp-every" type="number" min={1} value={every} onChange={(e) => setEvery(e.target.value)} />
          </div>
          <label className="flex items-center gap-2 self-end text-[13px]">
            <input type="checkbox" checked={rotate} onChange={(e) => setRotate(e.target.checked)} /> Rotate shifts too
          </label>
          {!rotate ? (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="rp-type">Shift</Label>
              <Picker id="rp-type" label="Shift" value={type} onChange={setType} options={opts.shift_types.map((t) => ({ value: t, label: `${t} (${opts.times[t]?.start_time}–${opts.times[t]?.end_time})` }))} />
            </div>
          ) : (
            <>
              <div className="flex flex-col gap-1.5">
                <Label>Shift order</Label>
                <div className="flex flex-wrap gap-1.5">
                  {opts.shift_types.map((t) => (
                    <button
                      key={t} type="button"
                      onClick={() => setSeq((c) => (c.includes(t) ? c.filter((x) => x !== t) : [...c, t]))}
                      className={cn("rounded-full px-2.5 py-1 text-[12px]", seq.includes(t) ? "bg-[var(--sd-ink)] text-white" : "bg-[var(--sd-line-soft)]")}
                    >
                      {seq.includes(t) ? `${seq.indexOf(t) + 1}. ` : ""}{t}
                    </button>
                  ))}
                </div>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="rp-chg">Change shift every (days)</Label>
                <Input id="rp-chg" type="number" min={1} value={changeEvery} onChange={(e) => setChangeEvery(e.target.value)} />
              </div>
            </>
          )}
          <div className="flex flex-col gap-1.5 sm:col-span-2"><Label htmlFor="rp-rem">Remarks</Label><Textarea id="rp-rem" rows={2} value={remarks} onChange={(e) => setRemarks(e.target.value)} /></div>
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button onClick={save} disabled={busy}>{busy ? "Saving…" : "Save draft"}</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function PlanDialog({ name, onClose, onChanged, onEdit }: {
  name: string | null; onClose: () => void; onChanged: () => void; onEdit: (p: PlanDetail) => void;
}) {
  const T = useTerms();
  const toast = useToast();
  const [p, setP] = useState<PlanDetail | null>(null);
  const [busy, setBusy] = useState("");
  const [cover, setCover] = useState<{ row: string; guard: string; guard_name: string; date: string; farm?: string; shift_type?: string } | null>(null);

  const load = useCallback(async () => {
    if (!name) return;
    const r = await rotationPlan(name);
    if (isError(r)) return void toast(r.error, "error");
    setP(r);
  }, [name, toast]);
  useEffect(() => {
    setP(null);
    void load();
  }, [load]);

  const act = async (action: "preview" | "apply" | "cancel") => {
    if (!p) return;
    if (action === "apply" && !confirm(`Book ${p.preview.filter((r) => !r.is_off_day).length} shifts for ${p.guard_name}?`)) return;
    if (action === "cancel" && !confirm("Cancel this draft plan?")) return;
    setBusy(action);
    const r = await planAction(p.name, action);
    setBusy("");
    if (isError(r)) return void toast(r.error, "error");
    if (action === "preview") toast(`${r.rows} days planned${r.off_days ? `, ${r.off_days} off` : ""}.`, "ok");
    if (action === "apply") toast(`${r.applied} shifts booked.`, r.failed ? "warn" : "ok", { hint: r.failed ? `${r.failed} could not be booked (see the days marked Failed).` : r.uncovered_off_days?.length ? `${r.uncovered_off_days.length} day(s) off without cover.` : undefined });
    if (action === "cancel") toast("Plan cancelled.", "ok");
    void load();
    onChanged();
  };

  const backOn = async (row: PreviewRow) => {
    if (!p) return;
    setBusy(row.name);
    const r = await togglePreviewDay(p.name, row.name, 0);
    setBusy("");
    if (isError(r)) return void toast(r.error, "error");
    void load();
  };

  const draft = p?.status === "Draft";
  const can = !!p?.can_plan;

  return (
    <Dialog open={!!name} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle className="flex flex-wrap items-center gap-2">{p ? <>{p.guard_name} <PlanStatus s={p.status} /></> : name}</DialogTitle>
          <DialogDescription>
            {p ? `${p.name} · ${p.start_date} → ${p.end_date} · ${p.farms.map((f) => f.farm).join(" → ")} · every ${p.rotation_interval_days} day(s) · ${p.rotate_shifts ? `shifts ${p.shift_sequence.join(" → ")}` : `${p.shift_type} ${p.start_time}–${p.end_time}`}` : "Loading…"}
          </DialogDescription>
        </DialogHeader>
        {p && (
          <>
            {p.preview.length === 0 ? (
              <p className="text-[13px] text-[var(--sd-muted)]">No preview yet. Generate it to see the plan day by day.</p>
            ) : (
              <div className="max-h-[50vh] overflow-auto">
                <table className="w-full text-[13px]">
                  <thead className={STICKY_HEAD}><tr><th className={TH}>Date</th><th className={TH}>{T.Site}</th><th className={TH}>Shift</th><th className={TH}>Day</th><th className={TH} /></tr></thead>
                  <tbody>
                    {p.preview.map((r) => (
                      <tr key={r.name} className={cn("border-t border-[var(--sd-line-soft)]", r.is_off_day && "bg-[var(--sd-line-soft)]/40")}>
                        <td className={`${TD} tabular-nums`}>{new Date(r.date + "T00:00").toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" })}</td>
                        <td className={TD}>{r.farm}</td>
                        <td className={`${TD} tabular-nums`}>{r.shift_type} {r.start_time}–{r.end_time}</td>
                        <td className={TD}>
                          {r.is_off_day ? (r.cover_guard ? <span>Off · {r.cover_guard_name} covers</span> : <span className="font-medium text-[var(--sd-data-red)]">Off · no cover</span>) : r.status}
                        </td>
                        <td className={`${TD} text-right`}>
                          {can && p.status !== "Cancelled" && (r.is_off_day ? (
                            <span className="flex justify-end gap-1.5">
                              <Button size="sm" variant="outline" disabled={!!busy} onClick={() => setCover({ row: r.name, guard: p.external_guard, guard_name: p.guard_name, date: r.date, farm: r.farm, shift_type: r.shift_type })}>{r.cover_guard ? "Change cover" : "Cover"}</Button>
                              <Button size="sm" variant="outline" disabled={!!busy} onClick={() => backOn(r)}>Back on</Button>
                            </span>
                          ) : (
                            <Button size="sm" variant="outline" disabled={!!busy} onClick={() => setCover({ row: r.name, guard: p.external_guard, guard_name: p.guard_name, date: r.date, farm: r.farm, shift_type: r.shift_type })}>Day off</Button>
                          ))}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {can && (
              <div className="flex flex-wrap justify-end gap-2">
                {draft && <Button variant="outline" onClick={() => act("cancel")} disabled={!!busy}>Cancel plan</Button>}
                {draft && <Button variant="outline" onClick={() => onEdit(p)} disabled={!!busy}>Edit</Button>}
                {draft && !p.preview.some((r) => r.status === "Applied") && (
                  <Button variant="outline" onClick={() => act("preview")} disabled={!!busy}>{busy === "preview" ? "Working…" : p.preview.length ? "Regenerate preview" : "Generate preview"}</Button>
                )}
                {draft && p.preview.length > 0 && <Button onClick={() => act("apply")} disabled={!!busy}>{busy === "apply" ? "Booking…" : "Apply: book the shifts"}</Button>}
              </div>
            )}
          </>
        )}
        {/* A day off on a plan is the same action as on the schedule: it books the cover for real. */}
        <CoverDialog
          target={cover}
          book={(c) => togglePreviewDay(p!.name, cover!.row, 1, c)}
          onClose={() => setCover(null)}
          onDone={() => { void load(); onChanged(); }}
        />
      </DialogContent>
    </Dialog>
  );
}
