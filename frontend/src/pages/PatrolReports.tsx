import { useCallback, useEffect, useState } from "react";
import { Camera, ExternalLink } from "lucide-react";
import { Card, TD, TH, Verdict } from "@/components/Card";
import { ClearFiltersPill } from "@/components/ClearFiltersPill";
import { DateRangePicker, type DateRange } from "@/components/DateRangePicker";
import { FilterSelect } from "@/components/FilterSelect";
import { TableRowsSkeleton } from "@/components/Loading";
import { PageShell } from "@/components/PageShell";
import { Pager } from "@/components/Pager";
import { RefreshButton } from "@/components/RefreshButton";
import { ScopePicker } from "@/components/ScopePicker";
import { ScrollTable, STICKY_HEAD } from "@/components/ScrollTable";
import { SearchInput } from "@/components/SearchInput";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { SeverityTag } from "@/components/incidents/IncidentDialogs";
import { isError } from "@/lib/frappe";
import { patrolReports, reviewPatrolReport, type PatrolReport, type PatrolReportPage, type ReviewStatus } from "@/lib/patrols-api";
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
const TABS: { key: string; label: string }[] = [
  { key: "Submitted", label: "To review" },
  { key: "Flagged", label: "Flagged" },
  { key: "Reviewed", label: "Reviewed" },
  { key: "", label: "All" },
];

function ReviewTag({ status }: { status: ReviewStatus }) {
  return <Verdict ok={status === "Reviewed" ? true : status === "Flagged" ? false : null}>{status === "Submitted" ? "To review" : status}</Verdict>;
}

/** Guards' patrol reports, reviewed here: mark reviewed, or flag with a reason. */
export function PatrolReports() {
  const T = useTerms();
  const toast = useToast();
  const { scope } = useScope();
  const [range, setRange] = useState<DateRange>(LAST_7);
  const [tab, setTab] = useState("Submitted");
  const [type, setType] = useState("");
  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");
  const [start, setStart] = useState(0);
  const [page, setPage] = useState<PatrolReportPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState<PatrolReport | null>(null);

  useEffect(() => {
    const t = window.setTimeout(() => setDebounced(search.trim()), 300);
    return () => window.clearTimeout(t);
  }, [search]);
  useEffect(() => setStart(0), [range, tab, type, debounced, scope]);

  const load = useCallback(async () => {
    setLoading(true);
    const r = await patrolReports({
      from_date: range.from, to_date: range.to, company: scope.company || undefined, farm: scope.farm || undefined,
      status: tab || undefined, report_type: type || undefined, search: debounced || undefined, start, page_length: PAGE,
    });
    setLoading(false);
    if (isError(r)) return void toast(r.error, "error");
    setPage(r);
  }, [range, scope, tab, type, debounced, start, toast]);
  useEffect(() => {
    void load();
  }, [load]);

  const total = page ? page.counts.Submitted + page.counts.Reviewed + page.counts.Flagged : undefined;
  const dirty = !!type || !!search || range.from !== LAST_7().from || range.to !== todayISO();

  return (
    <PageShell
      title="Patrol reports"
      eyebrow="Security"
      tabs={
        <div role="tablist" aria-label="Review status" className="flex flex-wrap gap-1.5">
          {TABS.map((t) => {
            const active = t.key === tab;
            const n = t.key ? page?.counts[t.key as ReviewStatus] : total;
            return (
              <button
                key={t.key || "all"} role="tab" aria-selected={active} onClick={() => setTab(t.key)}
                className={cn(
                  "flex h-9 items-center gap-2 rounded-full px-3.5 text-[13px] font-medium transition-colors",
                  active ? "bg-[var(--sd-ink)] text-white" : "bg-[var(--sd-card)] text-[var(--sd-muted)] shadow-[var(--sd-shadow-1)] hover:text-[var(--sd-ink)]",
                )}
              >
                {t.label}
                {n != null && (
                  <span className={cn("min-w-5 rounded-full px-1.5 text-center text-[11px] font-semibold tabular-nums",
                    active ? "bg-white/20" : t.key === "Submitted" && n > 0 ? "bg-[var(--sd-data-red)] text-white" : "bg-[var(--sd-line-soft)]")}>{n}</span>
                )}
              </button>
            );
          })}
        </div>
      }
      actions={
        <>
          <ScopePicker />
          <DateRangePicker label="Filed" value={range} onChange={setRange} />
          <FilterSelect label="Type" value={type} onChange={setType} options={["Routine", "Incident"]} allLabel="Routine & incident" />
          <SearchInput value={search} onChange={setSearch} placeholder="Report, patrol, observations" aria-label="Search patrol reports" />
          <ClearFiltersPill active={dirty} onClear={() => { setType(""); setSearch(""); setRange(LAST_7()); }} />
          <RefreshButton onClick={() => void load()} loading={loading} label="Refresh patrol reports" />
        </>
      }
    >
      <Card>
        <ScrollTable tall>
          <table className="w-full text-[13px]">
            <thead className={STICKY_HEAD}>
              <tr><th className={TH}>Filed</th><th className={TH}>Guard</th><th className={TH}>Observations</th><th className={TH}>{T.Site}</th><th className={TH}>Patrol</th><th className={TH}>Review</th></tr>
            </thead>
            <tbody>
              {loading && !page ? (
                <TableRowsSkeleton cols={6} rows={6} />
              ) : (page?.rows.length ?? 0) === 0 ? (
                <tr><td colSpan={6} className="px-4 py-10 text-center text-[var(--sd-muted)]">{tab === "Submitted" ? "Nothing waiting for review." : "No patrol reports here."}</td></tr>
              ) : (
                page!.rows.map((r) => (
                  <tr
                    key={r.name} tabIndex={0} onClick={() => setOpen(r)} onKeyDown={(e) => e.key === "Enter" && setOpen(r)}
                    className={cn("cursor-pointer border-t border-[var(--sd-line-soft)] hover:bg-[var(--sd-line-soft)]/50", loading && "opacity-60")}
                  >
                    <td className={`${TD} tabular-nums`}>{when(r.filed_at)}<div className="text-[12px] text-[var(--sd-quiet)]">{r.name}</div></td>
                    <td className={TD}>{r.guard}</td>
                    <td className={TD}>
                      <div className="flex items-center gap-1.5">
                        {r.report_type === "Incident" && r.severity && <SeverityTag severity={r.severity} />}
                        {r.report_type === "Incident" && <span className="font-medium">{r.nature_of_incident || "Incident"}</span>}
                        {r.attachments.length > 0 && <Camera className="h-3.5 w-3.5 text-[var(--sd-quiet)]" aria-label={`${r.attachments.length} photos`} />}
                      </div>
                      <div className="line-clamp-2 max-w-[48ch] text-[12px] text-[var(--sd-muted)]">{r.observations || "—"}</div>
                    </td>
                    <td className={TD}>{r.farm || "—"}</td>
                    <td className={`${TD} tabular-nums`}>{r.points_logged ?? 0} points<div className="text-[12px] text-[var(--sd-quiet)]">{r.started_at ? `${when(r.started_at)} – ${when(r.ended_at)}` : r.patrol}</div></td>
                    <td className={TD}><ReviewTag status={r.status} />{r.reviewed_by_name && <div className="mt-1 text-[12px] text-[var(--sd-quiet)]">{r.reviewed_by_name}</div>}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </ScrollTable>
        <Pager start={start} total={page?.total ?? 0} page={PAGE} loading={loading} onChange={setStart} />
      </Card>

      <ReviewDialog report={open} canReview={!!page?.can_review} onClose={() => setOpen(null)} onDone={load} />
    </PageShell>
  );
}

function ReviewDialog({ report, canReview, onClose, onDone }: {
  report: PatrolReport | null; canReview: boolean; onClose: () => void; onDone: () => void;
}) {
  const toast = useToast();
  const [remarks, setRemarks] = useState("");
  const [busy, setBusy] = useState<ReviewStatus | null>(null);
  useEffect(() => setRemarks(report?.supervisor_remarks || ""), [report]);

  const act = async (status: ReviewStatus) => {
    if (!report) return;
    if (status === "Flagged" && !remarks.trim()) return void toast("Say why the report is flagged.", "warn");
    setBusy(status);
    const r = await reviewPatrolReport({ name: report.name, status, supervisor_remarks: remarks });
    setBusy(null);
    if (isError(r)) return void toast(r.error, "error");
    toast(`${report.name}: ${status === "Submitted" ? "back to review" : status.toLowerCase()}.`, status === "Flagged" ? "warn" : "ok",
      { hint: r.incident_report && !report.incident_report ? `Incident ${r.incident_report} raised.` : undefined });
    onClose();
    onDone();
  };

  return (
    <Dialog open={!!report} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex flex-wrap items-center gap-2">
            {report?.report_type === "Incident" ? `Incident report · ${report.nature_of_incident || ""}` : "Routine patrol report"}
            {report && <ReviewTag status={report.status} />}
          </DialogTitle>
          <DialogDescription>
            {report ? `${report.name} · ${report.guard} · filed ${when(report.filed_at)}${report.farm ? ` · ${report.farm}` : ""}` : ""}
          </DialogDescription>
        </DialogHeader>
        {report && (
          <div className="flex flex-col gap-4">
            <div className="grid grid-cols-2 gap-2 text-[13px] sm:grid-cols-4">
              <div><div className="text-[12px] text-[var(--sd-quiet)]">Patrol</div>{report.patrol || "—"}</div>
              <div><div className="text-[12px] text-[var(--sd-quiet)]">From</div>{when(report.started_at)}</div>
              <div><div className="text-[12px] text-[var(--sd-quiet)]">To</div>{when(report.ended_at)}</div>
              <div><div className="text-[12px] text-[var(--sd-quiet)]">GPS points</div>{report.points_logged ?? 0}</div>
            </div>
            {report.report_type === "Incident" && (
              <div className="flex flex-wrap items-center gap-2 text-[13px]">
                {report.severity && <SeverityTag severity={report.severity} />}
                {report.incident_report && <a className="underline" href={`/app/incident-report/${encodeURIComponent(report.incident_report)}`}>Incident {report.incident_report}</a>}
              </div>
            )}
            <p className="whitespace-pre-wrap text-[13px] leading-relaxed">{report.observations || "No observations written."}</p>
            {report.attachments.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {report.attachments.map((u) => (
                  <a key={u} href={u} target="_blank" rel="noreferrer" className="block size-24 overflow-hidden rounded-[var(--sd-radius-md,10px)] border border-[var(--sd-line)]">
                    <img src={u} alt="Patrol photo" className="size-full object-cover" />
                  </a>
                ))}
              </div>
            )}
            {report.reviewed_by_name && (
              <p className="text-[12px] text-[var(--sd-quiet)]">{report.status} by {report.reviewed_by_name} {when(report.reviewed_on)}</p>
            )}
            {canReview ? (
              <>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="pr-rem">Supervisor remarks</Label>
                  <Textarea id="pr-rem" rows={3} value={remarks} onChange={(e) => setRemarks(e.target.value)} placeholder="Required when flagging" />
                  <p className="text-[12px] text-[var(--sd-quiet)]">Flagging raises an Incident Report for this patrol.</p>
                </div>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <a className="inline-flex items-center gap-1 text-[12px] text-[var(--sd-muted)] underline" href={`/app/patrol-report/${encodeURIComponent(report.name)}`}>
                    <ExternalLink className="h-3.5 w-3.5" /> Full record
                  </a>
                  <div className="flex flex-wrap gap-2">
                    {report.status !== "Submitted" && <Button variant="outline" onClick={() => act("Submitted")} disabled={!!busy}>Back to review</Button>}
                    <Button variant="destructive" onClick={() => act("Flagged")} disabled={!!busy}>{busy === "Flagged" ? "Saving…" : "Flag"}</Button>
                    <Button onClick={() => act("Reviewed")} disabled={!!busy}>{busy === "Reviewed" ? "Saving…" : "Mark reviewed"}</Button>
                  </div>
                </div>
              </>
            ) : (
              <>
                {report.supervisor_remarks && <p className="text-[13px]"><span className="text-[var(--sd-quiet)]">Supervisor: </span>{report.supervisor_remarks}</p>}
                <p className="text-[12px] text-[var(--sd-quiet)]">Only a Security Head or System Manager reviews patrol reports.</p>
              </>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
