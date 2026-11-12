import { useCallback, useEffect, useMemo, useState } from "react";
import { BadgeCheck, LogIn, LogOut, UserPlus } from "lucide-react";
import { ClearFiltersPill } from "@/components/ClearFiltersPill";
import { DateRangePicker, type DateRange } from "@/components/DateRangePicker";
import { FilterSelect } from "@/components/FilterSelect";
import { TableRowsSkeleton } from "@/components/Loading";
import { PageShell } from "@/components/PageShell";
import { RefreshButton } from "@/components/RefreshButton";
import { ScopePicker } from "@/components/ScopePicker";
import { ScrollTable, STICKY_HEAD } from "@/components/ScrollTable";
import { SearchInput } from "@/components/SearchInput";
import { useToast } from "@/components/Toast";
import { ToolbarButton } from "@/components/ToolbarButton";
import { Button } from "@/components/ui/button";
import { FeatureOff } from "@/components/FeatureOff";
import { CrewDialog } from "@/components/visitors/CrewDialog";
import { CheckInDialog, CheckOutDialog, ReviewDialog, WalkInDialog } from "@/components/visitors/VisitDialogs";
import { isError } from "@/lib/frappe";
import { useScope, useTerms } from "@/lib/scope";
import { cn, todayISO } from "@/lib/utils";
import { BUCKETS, visitorBoard, type Board, type Bucket, type Visit } from "@/lib/visitors-api";

const PAGE = 50;

/** "2026-11-12 09:30:00" -> "12 Nov, 09:30" (today: just the time). */
function when(v: string | null | undefined): string {
  if (!v) return "—";
  const d = new Date(v.replace(" ", "T"));
  if (Number.isNaN(d.getTime())) return v;
  const time = d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  if (v.slice(0, 10) === todayISO()) return time;
  return `${d.toLocaleDateString("en-GB", { day: "numeric", month: "short" })}, ${time}`;
}

/** The time that matters for the list being looked at. */
function timeFor(bucket: Bucket, v: Visit) {
  if (bucket === "on_site") return when(v.custom_check_in_time);
  if (bucket === "left") return when(v.custom_check_out_time);
  return when(v.scheduled_time);
}

const TIME_HEAD: Record<Bucket, string> = {
  review: "Expected",
  expected: "Expected",
  on_site: "Checked in",
  left: "Checked out",
  rejected: "Was expected",
};

/** The approve-type action goes first and stands out; the rest are quieter. */
function orderActions(actions: string[]) {
  const rank = (a: string) => (a.startsWith("Approve") ? 0 : a === "Reject Visit" ? 3 : 1);
  return [...actions].sort((a, b) => rank(a) - rank(b));
}

type Kind = "visitors" | "contractors";

export function Visitors() {
  return <VisitBoard kind="visitors" />;
}

export function Contractors() {
  return <VisitBoard kind="contractors" />;
}

/** Visitors and contractors are both Appointments; one board serves both. */
function VisitBoard({ kind }: { kind: Kind }) {
  const T = useTerms();
  const contractors = kind === "contractors";
  const toast = useToast();
  const { boot, scope } = useScope();
  const [bucket, setBucket] = useState<Bucket>("expected");
  const [range, setRange] = useState<DateRange>({ from: todayISO(), to: todayISO() });
  const [type, setType] = useState("");
  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");
  const [start, setStart] = useState(0);
  const [board, setBoard] = useState<Board | null>(null);
  const [loading, setLoading] = useState(true);

  const [checkingIn, setCheckingIn] = useState<Visit | null>(null);
  const [checkingOut, setCheckingOut] = useState<Visit | null>(null);
  const [reviewing, setReviewing] = useState<{ visit: Visit; action: string } | null>(null);
  const [walkIn, setWalkIn] = useState(false);
  const [crewOf, setCrewOf] = useState<Visit | null>(null);

  useEffect(() => {
    const t = window.setTimeout(() => setDebounced(search.trim()), 300);
    return () => window.clearTimeout(t);
  }, [search]);
  // A new filter starts the list from its first page.
  useEffect(() => setStart(0), [bucket, range, type, debounced, scope]);

  const load = useCallback(async () => {
    setLoading(true);
    const r = await visitorBoard({
      bucket,
      from_date: range.from,
      to_date: range.to,
      company: scope.company || undefined,
      farm: scope.farm || undefined,
      visitor_type: JSON.stringify(contractors ? ["Contractor"] : type ? [type] : ["Visitor", "Customer"]),
      search: debounced || undefined,
      start,
      page_length: PAGE,
    });
    setLoading(false);
    if (isError(r)) {
      toast(r.error, "error");
      return;
    }
    setBoard(r as Board);
  }, [bucket, range, scope, type, debounced, start, toast, contractors]);

  useEffect(() => {
    void load();
  }, [load]);

  // The gate does not wait for someone to press refresh.
  useEffect(() => {
    const t = window.setInterval(() => {
      if (document.visibilityState === "visible") void load();
    }, 60_000);
    return () => window.clearInterval(t);
  }, [load]);

  const dirty = !!type || !!search || range.from !== todayISO() || range.to !== todayISO();
  const rows = board?.rows ?? [];
  const total = board?.total ?? 0;
  const showActions = useMemo(
    () => contractors || rows.some((r) => r.can_check_in || r.can_check_out || r.review_actions.length),
    [rows, contractors],
  );

  if (contractors && boot.features.feature_contractor_checkin === false) {
    return <FeatureOff title="Contractors" what="Contractor check-in" />;
  }

  return (
    <PageShell
      title={contractors ? "Contractors" : "Visitors"}
      eyebrow="Gate operations"
      tabs={
        <div role="tablist" aria-label="Visit status" className="flex flex-wrap gap-1.5">
          {BUCKETS.map((b) => {
            const n = board?.counts?.[b.key];
            const active = b.key === bucket;
            return (
              <button
                key={b.key}
                role="tab"
                aria-selected={active}
                onClick={() => setBucket(b.key)}
                className={cn(
                  "flex h-9 items-center gap-2 rounded-full px-3.5 text-[13px] font-medium transition-colors",
                  active
                    ? "bg-[var(--sd-ink)] text-white"
                    : "bg-[var(--sd-card)] text-[var(--sd-muted)] shadow-[var(--sd-shadow-1)] hover:text-[var(--sd-ink)]",
                )}
              >
                {b.label}
                {n != null && (
                  <span
                    className={cn(
                      "min-w-5 rounded-full px-1.5 text-center text-[11px] font-semibold tabular-nums",
                      active ? "bg-white/20" : b.key === "review" && n > 0 ? "bg-[var(--sd-data-red)] text-white" : "bg-[var(--sd-line-soft)]",
                    )}
                  >
                    {n}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      }
      actions={
        <>
          <ScopePicker />
          {bucket !== "on_site" && <DateRangePicker label="Dates" value={range} onChange={setRange} />}
          {!contractors && (
            <FilterSelect label="Type" value={type} onChange={setType} options={boot.visitor_types.filter((t) => t !== "Contractor")} allLabel="Visitors & customers" />
          )}
          <SearchInput value={search} onChange={setSearch} placeholder="Name, phone, ID, plate" aria-label="Search visits" />
          <ClearFiltersPill
            active={dirty}
            onClear={() => {
              setType("");
              setSearch("");
              setRange({ from: todayISO(), to: todayISO() });
            }}
          />
          <RefreshButton onClick={() => void load()} loading={loading} label="Refresh visits" />
          {boot.can_check_in_out && !contractors && (
            <ToolbarButton onClick={() => setWalkIn(true)}>
              <UserPlus className="h-4 w-4" /> Walk-in
            </ToolbarButton>
          )}
        </>
      }
      description={
        bucket === "on_site"
          ? "Everyone checked in and not yet out, whatever day they arrived."
          : !boot.can_check_in_out
            ? "Only gate guards and security heads check people in and out; you can approve, reschedule and redirect visits."
            : undefined
      }
    >
      <div className="rounded-[var(--sd-radius-lg)] bg-[var(--sd-card)] shadow-[var(--sd-shadow-1)]">
        <ScrollTable tall>
          <table className="w-full text-[13px]">
            <thead className={STICKY_HEAD}>
              <tr className="text-left text-[11px] uppercase tracking-[0.08em] text-[var(--sd-quiet)]">
                <th className="px-4 py-3 font-medium">Visitor</th>
                <th className="px-4 py-3 font-medium">Host</th>
                <th className="px-4 py-3 font-medium">{T.Site}</th>
                <th className="px-4 py-3 font-medium">{TIME_HEAD[bucket]}</th>
                <th className="px-4 py-3 font-medium">Transport</th>
                <th className="px-4 py-3 font-medium">Status</th>
                {showActions && <th className="px-4 py-3 text-right font-medium">Actions</th>}
              </tr>
            </thead>
            <tbody>
              {loading && !board ? (
                <TableRowsSkeleton cols={showActions ? 7 : 6} rows={6} />
              ) : rows.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-10 text-center text-[var(--sd-muted)]">
                    No visits here{debounced ? ` matching “${debounced}”` : ""}.
                  </td>
                </tr>
              ) : (
                rows.map((v) => (
                  <tr key={v.name} className={cn("border-t border-[var(--sd-line-soft)] align-top", loading && "opacity-60")}>
                    <td className="px-4 py-3">
                      <div className="font-medium text-[var(--sd-ink)]">{v.customer_name || "—"}</div>
                      <div className="text-[12px] text-[var(--sd-quiet)]">
                        {[v.custom_visitor_type, v.customer_organization, v.customer_phone_number].filter(Boolean).join(" · ")}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <div>{v.custom_meet_with_name || v.custom_meet_with || "—"}</div>
                      {v.custom_visit_purpose && <div className="text-[12px] text-[var(--sd-quiet)]">{v.custom_visit_purpose}</div>}
                    </td>
                    <td className="px-4 py-3">{v.custom_farmunit || v.custom_company || "—"}</td>
                    <td className="px-4 py-3 tabular-nums">
                      {timeFor(bucket, v)}
                      {bucket === "on_site" && v.custom_entry_gate && <div className="text-[12px] text-[var(--sd-quiet)]">{v.custom_entry_gate}</div>}
                    </td>
                    <td className="px-4 py-3">
                      {v.custom_mode_of_transport || "—"}
                      {v.custom_vehicles_number_plate && <div className="text-[12px] text-[var(--sd-quiet)]">{v.custom_vehicles_number_plate}</div>}
                    </td>
                    <td className="px-4 py-3">
                      <span className="text-[12px] text-[var(--sd-muted)]">{v.workflow_state || "Open"}</span>
                      {v.custom_visitor_badge && <div className="text-[12px] text-[var(--sd-quiet)]">Badge {v.custom_visitor_badge}</div>}
                    </td>
                    {showActions && (
                      <td className="px-4 py-3">
                        <div className="flex flex-wrap justify-end gap-1.5">
                          {orderActions(v.review_actions).map((a, i) => (
                            <Button
                              key={a}
                              size="sm"
                              variant={i === 0 && a.startsWith("Approve") ? "default" : "outline"}
                              className={a === "Reject Visit" ? "text-[var(--sd-data-red)]" : undefined}
                              onClick={() => setReviewing({ visit: v, action: a })}
                            >
                              {a === "Approve on Behalf of Host" ? "Approve" : a === "Redirect to Another Host" ? "Redirect" : a === "Reject Visit" ? "Reject" : a}
                            </Button>
                          ))}
                          {contractors && bucket !== "left" && bucket !== "rejected" && (
                            <Button size="sm" variant="outline" onClick={() => setCrewOf(v)}>
                              <BadgeCheck className="mr-1 h-3.5 w-3.5" /> Crew &amp; badges
                            </Button>
                          )}
                          {v.can_check_in && (
                            <Button size="sm" onClick={() => setCheckingIn(v)}>
                              <LogIn className="mr-1 h-3.5 w-3.5" /> Check in
                            </Button>
                          )}
                          {v.can_check_out && (
                            <Button size="sm" variant="outline" onClick={() => setCheckingOut(v)}>
                              <LogOut className="mr-1 h-3.5 w-3.5" /> Check out
                            </Button>
                          )}
                        </div>
                      </td>
                    )}
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </ScrollTable>
        {total > PAGE && (
          <div className="flex items-center justify-between border-t border-[var(--sd-line-soft)] px-4 py-3 text-[12px] text-[var(--sd-muted)]">
            <span className="tabular-nums">
              {start + 1}–{Math.min(start + PAGE, total)} of {total}
            </span>
            <div className="flex gap-2">
              <Button size="sm" variant="outline" disabled={start === 0 || loading} onClick={() => setStart(Math.max(0, start - PAGE))}>
                Previous
              </Button>
              <Button size="sm" variant="outline" disabled={start + PAGE >= total || loading} onClick={() => setStart(start + PAGE)}>
                Next
              </Button>
            </div>
          </div>
        )}
      </div>

      <CheckInDialog visit={checkingIn} onClose={() => setCheckingIn(null)} onDone={load} />
      <CheckOutDialog visit={checkingOut} onClose={() => setCheckingOut(null)} onDone={load} />
      <ReviewDialog
        visit={reviewing?.visit ?? null}
        action={reviewing?.action ?? ""}
        onClose={() => setReviewing(null)}
        onDone={load}
      />
      <WalkInDialog open={walkIn} onClose={() => setWalkIn(false)} onDone={load} />
      <CrewDialog visit={crewOf} onClose={() => setCrewOf(null)} onChanged={load} />
    </PageShell>
  );
}
