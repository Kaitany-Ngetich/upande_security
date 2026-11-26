import { useCallback, useEffect, useState } from "react";
import { Map } from "lucide-react";
import { Card, TD, TH, Verdict } from "@/components/Card";
import { ClearFiltersPill } from "@/components/ClearFiltersPill";
import { DateRangePicker, type DateRange } from "@/components/DateRangePicker";
import { KpiCard, KpiGrid } from "@/components/KpiCard";
import { TableRowsSkeleton } from "@/components/Loading";
import { PageShell } from "@/components/PageShell";
import { Pager } from "@/components/Pager";
import { RefreshButton } from "@/components/RefreshButton";
import { ScopePicker } from "@/components/ScopePicker";
import { ScrollTable, STICKY_HEAD } from "@/components/ScrollTable";
import { SearchInput } from "@/components/SearchInput";
import { useToast } from "@/components/Toast";
import { isError } from "@/lib/frappe";
import { patrolBoard, type PatrolBoard, type PatrolState } from "@/lib/patrols-api";
import { routeHash } from "@/lib/router";
import { useScope, useTerms } from "@/lib/scope";
import { cn, todayISO } from "@/lib/utils";
import { when } from "@/lib/when";

const PAGE = 50;
const TABS: { key: string; label: string }[] = [
  { key: "", label: "All" },
  { key: "Active", label: "Live" },
  { key: "Stale", label: "Gone quiet" },
  { key: "Ended", label: "Ended" },
  { key: "no_report", label: "No report" },
];

function mins(m: number) {
  if (m < 60) return `${m} min`;
  return `${Math.floor(m / 60)} h${m % 60 ? ` ${m % 60} min` : ""}`;
}

/** A patrol's state, in words and with a dot, never colour alone. */
function State({ state }: { state: PatrolState }) {
  const dot = { Active: "bg-[var(--sd-data-green)]", Stale: "bg-[var(--sd-target)]", Ended: "bg-[var(--sd-line)]" }[state];
  const word = { Active: "Live", Stale: "Gone quiet", Ended: "Ended" }[state];
  return (
    <span className="inline-flex items-center gap-1.5 text-[12px]">
      <span className={cn("size-2 rounded-full", dot, state === "Active" && "animate-pulse")} aria-hidden />
      {word}
    </span>
  );
}

/** Who is patrolling, who has gone quiet, and which patrols were never reported. */
export function Patrols() {
  const T = useTerms();
  const toast = useToast();
  const { scope } = useScope();
  const [range, setRange] = useState<DateRange>({ from: todayISO(), to: todayISO() });
  const [tab, setTab] = useState("");
  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");
  const [start, setStart] = useState(0);
  const [board, setBoard] = useState<PatrolBoard | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const t = window.setTimeout(() => setDebounced(search.trim()), 300);
    return () => window.clearTimeout(t);
  }, [search]);
  useEffect(() => setStart(0), [range, tab, debounced, scope]);

  const load = useCallback(async () => {
    setLoading(true);
    const r = await patrolBoard({
      from_date: range.from, to_date: range.to, company: scope.company || undefined, farm: scope.farm || undefined,
      status: tab || undefined, search: debounced || undefined, start, page_length: PAGE,
    });
    setLoading(false);
    if (isError(r)) return void toast(r.error, "error");
    setBoard(r);
  }, [range, scope, tab, debounced, start, toast]);

  useEffect(() => {
    void load();
  }, [load]);
  // Live patrols move: refresh every minute while the page is in view.
  useEffect(() => {
    const t = window.setInterval(() => document.visibilityState === "visible" && void load(), 60_000);
    return () => window.clearInterval(t);
  }, [load]);

  const k = board?.kpis;
  const counts: Record<string, number | undefined> = {
    "": k?.patrols, Active: board?.counts.Active, Stale: board?.counts.Stale, Ended: board?.counts.Ended, no_report: k?.without_report,
  };
  const dirty = !!search || range.from !== todayISO() || range.to !== todayISO();

  return (
    <PageShell
      title="Patrols"
      eyebrow="Security"
      tabs={
        <div role="tablist" aria-label="Patrol state" className="flex flex-wrap gap-1.5">
          {TABS.map((t) => {
            const active = t.key === tab;
            const n = counts[t.key];
            return (
              <button
                key={t.key || "all"} role="tab" aria-selected={active} onClick={() => setTab(t.key)}
                className={cn(
                  "flex h-9 items-center gap-2 rounded-full px-3.5 text-[13px] font-medium transition-colors",
                  active ? "bg-[var(--sd-ink)] text-white" : "bg-[var(--sd-card)] text-[var(--sd-muted)] shadow-[var(--sd-shadow-1)] hover:text-[var(--sd-ink)]",
                )}
              >
                {t.label}
                {n != null && <span className={cn("min-w-5 rounded-full px-1.5 text-center text-[11px] font-semibold tabular-nums", active ? "bg-white/20" : "bg-[var(--sd-line-soft)]")}>{n}</span>}
              </button>
            );
          })}
        </div>
      }
      actions={
        <>
          <ScopePicker />
          <DateRangePicker label="Dates" value={range} onChange={setRange} />
          <SearchInput value={search} onChange={setSearch} placeholder={`Guard, patrol, ${T.site}`} aria-label="Search patrols" />
          <ClearFiltersPill active={dirty} onClear={() => { setSearch(""); setRange({ from: todayISO(), to: todayISO() }); }} />
          <RefreshButton onClick={() => void load()} loading={loading} label="Refresh patrols" />
          <a
            href="/patrol-map"
            className="inline-flex h-9 items-center gap-1.5 rounded-full bg-[var(--sd-card)] px-3.5 text-[13px] font-medium shadow-[var(--sd-shadow-1)] hover:text-[var(--sd-ink)]"
          >
            <Map className="h-4 w-4" /> Map
          </a>
        </>
      }
    >
      <KpiGrid cols={5}>
        <KpiCard label="Patrolling now" value={k?.active ?? 0} hint={`${k?.stale ?? 0} gone quiet (no fix in 15 min)`} tone={k?.active ? "good" : "default"} loading={!board} />
        <KpiCard label="Patrols" value={k?.patrols ?? 0} hint={`${k?.guards ?? 0} guard${k?.guards === 1 ? "" : "s"}`} loading={!board} />
        <KpiCard label="Hours patrolled" value={k ? k.hours.toFixed(1) : "0"} hint={`${(k?.points ?? 0).toLocaleString()} GPS points`} loading={!board} />
        <KpiCard label="Reported" value={k?.with_report ?? 0} loading={!board} />
        <KpiCard label="Ended without a report" value={k?.without_report ?? 0} tone={k?.without_report ? "warning" : "default"} loading={!board} />
      </KpiGrid>

      <Card>
        <ScrollTable tall>
          <table className="w-full text-[13px]">
            <thead className={STICKY_HEAD}>
              <tr>
                <th className={TH}>Guard</th><th className={TH}>{T.Site}</th><th className={TH}>Started</th><th className={TH}>Last fix</th>
                <th className={TH}>Duration</th><th className={TH}>Points</th><th className={TH}>State</th><th className={TH}>Report</th>
              </tr>
            </thead>
            <tbody>
              {loading && !board ? (
                <TableRowsSkeleton cols={8} rows={6} />
              ) : (board?.rows.length ?? 0) === 0 ? (
                <tr><td colSpan={8} className="px-4 py-10 text-center text-[var(--sd-muted)]">No patrols here.</td></tr>
              ) : (
                board!.rows.map((r) => (
                  <tr key={`${r.guard}::${r.patrol}`} className={cn("border-t border-[var(--sd-line-soft)]", loading && "opacity-60")}>
                    <td className={TD}>{r.guard}<div className="text-[12px] text-[var(--sd-quiet)]">{r.patrol}</div></td>
                    <td className={TD}>{r.farm || "—"}</td>
                    <td className={`${TD} tabular-nums`}>{when(r.started)}</td>
                    <td className={`${TD} tabular-nums`}>{when(r.last_fix)}</td>
                    <td className={`${TD} tabular-nums`}>{mins(r.minutes)}</td>
                    <td className={`${TD} tabular-nums`}>{r.points}</td>
                    <td className={TD}><State state={r.state} /></td>
                    <td className={TD}>
                      {r.report ? (
                        <a className="underline" href={routeHash("patrol-reports")} title="Open the patrol reports">
                          <Verdict ok={r.report_status === "Flagged" ? false : r.report_status === "Reviewed" ? true : null}>{r.report_status}</Verdict>
                          {r.report_type === "Incident" && <span className="ml-1 text-[12px] text-[var(--sd-data-red)]">incident</span>}
                        </a>
                      ) : r.state === "Ended" ? (
                        <span className="text-[12px] font-medium text-[var(--sd-target)]">Not filed</span>
                      ) : (
                        <span className="text-[12px] text-[var(--sd-quiet)]">—</span>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </ScrollTable>
        <Pager start={start} total={board?.total ?? 0} page={PAGE} loading={loading} onChange={setStart} />
      </Card>
    </PageShell>
  );
}
