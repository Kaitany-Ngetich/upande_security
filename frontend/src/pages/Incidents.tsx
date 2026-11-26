import { useCallback, useEffect, useState } from "react";
import { Camera, Plus } from "lucide-react";
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Card, TD, TH } from "@/components/Card";
import { ClearFiltersPill } from "@/components/ClearFiltersPill";
import { DateRangePicker, type DateRange } from "@/components/DateRangePicker";
import { FilterSelect } from "@/components/FilterSelect";
import { IncidentDialog, ReportDialog, SeverityTag } from "@/components/incidents/IncidentDialogs";
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
import { isError } from "@/lib/frappe";
import { incidentBoard, incidentOptions, type IncidentBoard, type IncidentOptions } from "@/lib/incidents-api";
import { useScope } from "@/lib/scope";
import { cn, todayISO } from "@/lib/utils";
import { when } from "@/lib/when";

const PAGE = 50;

function daysAgo(n: number) {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}
const LAST_30 = (): DateRange => ({ from: daysAgo(29), to: todayISO() });

/** "1 h 20 min", "2 d 4 h". */
function duration(min: number | null) {
  if (min == null) return "—";
  if (min < 60) return `${min} min`;
  if (min < 60 * 24) return `${Math.floor(min / 60)} h ${min % 60 ? `${min % 60} min` : ""}`.trim();
  const d = Math.floor(min / 1440);
  const h = Math.round((min % 1440) / 60);
  return `${d} d${h ? ` ${h} h` : ""}`;
}

const TABS = [
  { key: "active", label: "Active" },
  { key: "Open", label: "Open" },
  { key: "In Progress", label: "In progress" },
  { key: "Resolved", label: "Resolved" },
  { key: "Closed", label: "Closed" },
  { key: "", label: "All" },
];

export function Incidents() {
  const toast = useToast();
  const { scope } = useScope();
  const [options, setOptions] = useState<IncidentOptions | null>(null);
  const [range, setRange] = useState<DateRange>(LAST_30);
  const [tab, setTab] = useState("active");
  const [severity, setSeverity] = useState("");
  const [category, setCategory] = useState("");
  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");
  const [start, setStart] = useState(0);
  const [board, setBoard] = useState<IncidentBoard | null>(null);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState<string | null>(null);
  const [reporting, setReporting] = useState(false);
  const closeIncident = useCallback(() => setOpen(null), []);

  useEffect(() => {
    void incidentOptions().then((r) => (isError(r) ? toast(r.error, "error") : setOptions(r)));
  }, [toast]);
  useEffect(() => {
    const t = window.setTimeout(() => setDebounced(search.trim()), 300);
    return () => window.clearTimeout(t);
  }, [search]);
  useEffect(() => setStart(0), [range, tab, severity, category, debounced, scope]);

  const load = useCallback(async () => {
    setLoading(true);
    const r = await incidentBoard({
      from_date: range.from, to_date: range.to, company: scope.company || undefined, farm: scope.farm || undefined,
      status: tab || undefined, severity: severity || undefined, category: category || undefined,
      search: debounced || undefined, start, page_length: PAGE,
    });
    setLoading(false);
    if (isError(r)) return void toast(r.error, "error");
    setBoard(r);
  }, [range, scope, tab, severity, category, debounced, start, toast]);

  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => {
    const t = window.setInterval(() => document.visibilityState === "visible" && void load(), 120_000);
    return () => window.clearInterval(t);
  }, [load]);

  const k = board?.kpis;
  const dirty = !!severity || !!category || !!search || range.from !== LAST_30().from || range.to !== todayISO();
  const maxCat = Math.max(1, ...(board?.by_category ?? []).map((c) => c.count));
  const counts: Record<string, number> = board
    ? { ...board.by_status, active: k?.active ?? 0, "": k?.total ?? 0 }
    : {};

  return (
    <PageShell
      title="Incidents"
      eyebrow="Security"
      tabs={
        <div role="tablist" aria-label="Incident status" className="flex flex-wrap gap-1.5">
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
          <FilterSelect label="Severity" value={severity} onChange={setSeverity} options={options?.severities ?? []} allLabel="All severities" />
          <FilterSelect
            label="Type" value={category} onChange={setCategory} allLabel="All types"
            options={(options?.categories ?? []).map((c) => ({ value: c.name, label: c.category_name || c.name }))}
          />
          <SearchInput value={search} onChange={setSearch} placeholder="ID, place, description" aria-label="Search incidents" />
          <ClearFiltersPill active={dirty} onClear={() => { setSeverity(""); setCategory(""); setSearch(""); setRange(LAST_30()); }} />
          <RefreshButton onClick={() => void load()} loading={loading} label="Refresh incidents" />
          {options && (
            <ToolbarButton onClick={() => setReporting(true)}>
              <Plus className="h-4 w-4" /> Report incident
            </ToolbarButton>
          )}
        </>
      }
    >
      <KpiGrid cols={5}>
        <KpiCard label="Active" value={k?.active ?? 0} hint={`${k?.total ?? 0} reported in the period`} loading={!board} />
        <KpiCard label="Critical, still open" value={k?.critical_open ?? 0} tone={k?.critical_open ? "critical" : "default"} loading={!board} />
        <KpiCard label="High, still open" value={k?.high_open ?? 0} tone={k?.high_open ? "warning" : "default"} loading={!board} />
        <KpiCard label="Resolved or closed" value={k?.resolved ?? 0} hint={`${k?.in_progress ?? 0} in progress`} loading={!board} />
        <KpiCard label="Average time to resolve" value={duration(k?.avg_resolution_minutes ?? null)} hint="From the incident to its resolution" loading={!board} />
      </KpiGrid>

      <div className="grid gap-6 lg:grid-cols-[2fr_1fr]">
        <Card title="Incidents per day">
          <div className="h-56 px-2 pb-3 pt-2">
            {board && (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={board.over_time} margin={{ top: 8, right: 12, left: 0, bottom: 0 }} barCategoryGap={2}>
                  <XAxis
                    dataKey="day" tickLine={false} axisLine={{ stroke: "var(--sd-line)" }} interval="preserveStartEnd" minTickGap={24}
                    tick={{ fontSize: 11, fill: "var(--sd-quiet)" }}
                    tickFormatter={(d: string) => new Date(d + "T00:00").toLocaleDateString("en-GB", { day: "numeric", month: "short" })}
                  />
                  <YAxis width={28} allowDecimals={false} tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: "var(--sd-quiet)" }} />
                  <Tooltip
                    cursor={{ fill: "rgba(10,10,10,0.04)" }}
                    content={({ active, payload }) => {
                      const p = active ? (payload?.[0]?.payload as { day: string; count: number } | undefined) : undefined;
                      if (!p) return null;
                      return (
                        <div className="rounded-lg bg-foreground px-3 py-2 text-[12px] text-background shadow-[var(--sd-shadow-3)]">
                          <div className="font-semibold">{new Date(p.day + "T00:00").toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" })}</div>
                          <div>{p.count} incident{p.count === 1 ? "" : "s"}</div>
                        </div>
                      );
                    }}
                  />
                  <Bar dataKey="count" fill="var(--chart-1)" radius={[4, 4, 0, 0]} maxBarSize={28} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
        </Card>
        <Card title="By type">
          <div className="flex flex-col gap-2 px-4 pb-4 pt-3">
            {!board ? null : board.by_category.length === 0 ? (
              <p className="text-[13px] text-[var(--sd-muted)]">Nothing reported in this period.</p>
            ) : (
              board.by_category.slice(0, 8).map((c) => (
                <button
                  key={c.category} type="button" title={`Show only ${c.category}`}
                  onClick={() => setCategory(category === c.category ? "" : c.category)}
                  className={cn("group flex flex-col gap-1 rounded-md px-1 py-0.5 text-left text-[13px]", category === c.category && "bg-[var(--sd-line-soft)]")}
                >
                  <span className="flex justify-between"><span>{c.category}</span><span className="tabular-nums text-[var(--sd-muted)]">{c.count}</span></span>
                  <span className="h-1.5 rounded-full bg-[var(--sd-line-soft)]">
                    <span className="block h-full rounded-full bg-[var(--chart-1)]" style={{ width: `${(c.count / maxCat) * 100}%` }} />
                  </span>
                </button>
              ))
            )}
          </div>
        </Card>
      </div>

      <Card>
        <ScrollTable tall>
          <table className="w-full text-[13px]">
            <thead className={STICKY_HEAD}>
              <tr><th className={TH}>When</th><th className={TH}>What</th><th className={TH}>Where</th><th className={TH}>Severity</th><th className={TH}>Status</th><th className={TH}>Reported by</th></tr>
            </thead>
            <tbody>
              {loading && !board ? (
                <TableRowsSkeleton cols={6} rows={6} />
              ) : (board?.rows.length ?? 0) === 0 ? (
                <tr><td colSpan={6} className="px-4 py-10 text-center text-[var(--sd-muted)]">No incidents here{debounced ? ` matching “${debounced}”` : ""}.</td></tr>
              ) : (
                board!.rows.map((r) => (
                  <tr
                    key={r.name} tabIndex={0} onClick={() => setOpen(r.name)} onKeyDown={(e) => e.key === "Enter" && setOpen(r.name)}
                    className={cn("cursor-pointer border-t border-[var(--sd-line-soft)] hover:bg-[var(--sd-line-soft)]/50", loading && "opacity-60")}
                  >
                    <td className={`${TD} tabular-nums`}>{when(r.incident_datetime)}<div className="text-[12px] text-[var(--sd-quiet)]">{r.name}</div></td>
                    <td className={TD}>
                      <div className="font-medium">{r.nature_of_incident}{r.attachments.length > 0 && <Camera className="ml-1 inline h-3.5 w-3.5 text-[var(--sd-quiet)]" aria-label={`${r.attachments.length} photos`} />}</div>
                      <div className="line-clamp-2 max-w-[42ch] text-[12px] text-[var(--sd-quiet)]">{r.description}</div>
                    </td>
                    <td className={TD}>{r.location || "—"}<div className="text-[12px] text-[var(--sd-quiet)]">{r.farm}</div></td>
                    <td className={TD}><SeverityTag severity={r.severity} /></td>
                    <td className={TD}>{r.status || "Open"}{r.assigned_to && <div className="text-[12px] text-[var(--sd-quiet)]">{r.assigned_to}</div>}</td>
                    <td className={TD}>{r.reporter_name || "—"}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </ScrollTable>
        <Pager start={start} total={board?.total ?? 0} page={PAGE} loading={loading} onChange={setStart} />
      </Card>

      <IncidentDialog name={open} statuses={options?.statuses ?? []} onClose={closeIncident} onChanged={load} />
      {options && <ReportDialog open={reporting} options={options} onClose={() => setReporting(false)} onDone={() => void load()} />}
    </PageShell>
  );
}
