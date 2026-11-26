import { useCallback, useEffect, useState } from "react";
import { Download } from "lucide-react";
import { Card, TD, TH } from "@/components/Card";
import { FilterSelect } from "@/components/FilterSelect";
import { TableRowsSkeleton } from "@/components/Loading";
import { PageShell } from "@/components/PageShell";
import { RefreshButton } from "@/components/RefreshButton";
import { ScopePicker } from "@/components/ScopePicker";
import { ScrollTable, STICKY_HEAD } from "@/components/ScrollTable";
import { useToast } from "@/components/Toast";
import { isError } from "@/lib/frappe";
import { guardRanking, type Period, type RankRow, type Ranking as RankingData } from "@/lib/patrols-api";
import { useScope, useTerms } from "@/lib/scope";
import { cn } from "@/lib/utils";

const PERIODS: { value: Period; label: string }[] = [
  { value: "today", label: "Today" },
  { value: "yesterday", label: "Yesterday" },
  { value: "this_week", label: "This week" },
  { value: "last_week", label: "Last week" },
  { value: "this_month", label: "This month" },
  { value: "last_month", label: "Last month" },
];
const HALVES = [
  { value: "all", label: "Day and night" },
  { value: "day", label: "Day half" },
  { value: "night", label: "Night half" },
];

const pct = (v: number | null) => (v == null ? "—" : `${v.toFixed(v < 10 ? 1 : 0)}%`);

/** The score as a bar on its own 0-100 track, the number beside it. */
function Score({ value }: { value: number }) {
  return (
    <span className="flex items-center gap-2">
      <span className="h-1.5 w-20 rounded-full bg-[var(--sd-line-soft)]">
        <span className="block h-full rounded-full bg-[var(--chart-1)]" style={{ width: `${Math.max(2, Math.min(100, value))}%` }} />
      </span>
      <span className="tabular-nums font-semibold">{value.toFixed(0)}</span>
    </span>
  );
}

/** Guards of each farm ranked on coverage, distance, checkpoint scans and safety. */
export function Ranking() {
  const T = useTerms();
  const toast = useToast();
  const { scope } = useScope();
  const [period, setPeriod] = useState<Period>("this_week");
  const [half, setHalf] = useState<"all" | "day" | "night">("all");
  const [data, setData] = useState<RankingData | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    const r = await guardRanking({ period, half, company: scope.company || undefined, farm: scope.farm || undefined });
    setLoading(false);
    if (isError(r)) return void toast(r.error, "error");
    setData(r);
  }, [period, half, scope, toast]);
  useEffect(() => {
    void load();
  }, [load]);

  const exportUrl = (fmt: string) => {
    const q = new URLSearchParams({ fmt, period, half });
    if (scope.farm) q.set("farm", scope.farm);
    else if (scope.company) q.set("company", scope.company);
    return `/api/method/upande_security.api.security_report.export_ranking?${q}`;
  };

  const byFarm = new Map<string, RankRow[]>();
  for (const r of data?.rows ?? []) byFarm.set(r.farm, [...(byFarm.get(r.farm) ?? []), r]);

  return (
    <PageShell
      title="Guard ranking"
      eyebrow="Security"
      actions={
        <>
          <ScopePicker />
          <FilterSelect label="Period" value={period} onChange={(v) => setPeriod(v as Period)} options={PERIODS} />
          <FilterSelect label="Shift half" value={half} onChange={(v) => setHalf(v as "all" | "day" | "night")} options={HALVES} />
          <RefreshButton onClick={() => void load()} loading={loading} label="Refresh ranking" />
          <span className="inline-flex h-9 items-center gap-1 rounded-full bg-[var(--sd-card)] px-3 text-[13px] shadow-[var(--sd-shadow-1)]">
            <Download className="h-4 w-4" />
            {["xlsx", "csv", "pdf"].map((f) => (
              <a key={f} href={exportUrl(f)} className="rounded px-1.5 font-medium uppercase hover:bg-[var(--sd-line-soft)]">{f === "xlsx" ? "Excel" : f}</a>
            ))}
          </span>
        </>
      }
      description={
        data
          ? `${data.window_label}. Score out of 100: ${T.site} coverage, distance walked${data.checkpoints ? ", checkpoint scans" : ""} and safety (incidents on their shifts), weighted per ${T.site}.`
          : undefined
      }
    >
      {loading && !data ? (
        <Card><table className="w-full"><tbody><TableRowsSkeleton cols={7} rows={6} /></tbody></table></Card>
      ) : !data?.farms.length ? (
        <Card><p className="px-4 py-10 text-center text-[13px] text-[var(--sd-muted)]">No {T.sites} in view.</p></Card>
      ) : (
        data.farms.map((f) => {
          const rows = byFarm.get(f.farm) ?? [];
          return (
            <Card
              key={f.farm}
              title={f.farm}
              actions={
                <span className="text-[12px] text-[var(--sd-muted)]">
                  {f.guards} guard{f.guards === 1 ? "" : "s"} · {f.distance_km.toFixed(1)} km · {f.patrol_hours.toFixed(1)} h
                  {f.coverage_pct != null && ` · ${pct(f.coverage_pct)} of the ${T.site} covered${f.covered_ha != null ? ` (${f.covered_ha} of ${f.area_ha} ha)` : ""}`}
                </span>
              }
            >
              <ScrollTable className={cn("mt-3", loading && "opacity-60")}>
                <table className="w-full text-[13px]">
                  <thead className={STICKY_HEAD}>
                    <tr>
                      <th className={TH}>#</th><th className={TH}>Guard</th><th className={TH}>Score</th><th className={TH}>Coverage</th>
                      <th className={TH}>Distance</th><th className={TH}>Patrolling</th><th className={TH}>Patrols</th>
                      {data.checkpoints && <th className={TH}>Scans</th>}<th className={TH}>Incidents</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.length === 0 ? (
                      <tr><td colSpan={9} className="px-4 py-6 text-center text-[var(--sd-muted)]">Nobody patrolled this {T.site} in the period.</td></tr>
                    ) : (
                      rows.map((r) => (
                        <tr key={r.guard} className="border-t border-[var(--sd-line-soft)]">
                          <td className={`${TD} tabular-nums font-semibold`}>{r.rank}</td>
                          <td className={TD}>{r.name}<div className="text-[12px] text-[var(--sd-quiet)]">{r.kind === "Internal Guard" ? "Staff" : "External"} · {r.shifts} shift{r.shifts === 1 ? "" : "s"}</div></td>
                          <td className={TD}><Score value={r.score} /></td>
                          <td className={`${TD} tabular-nums`}>{pct(r.coverage_pct)}{r.area_ha != null && <div className="text-[12px] text-[var(--sd-quiet)]">{r.area_ha} ha</div>}</td>
                          <td className={`${TD} tabular-nums`}>{r.distance_km.toFixed(1)} km</td>
                          <td className={`${TD} tabular-nums`}>{r.patrol_hours.toFixed(1)} h</td>
                          <td className={`${TD} tabular-nums`}>{r.patrols}</td>
                          {data.checkpoints && <td className={`${TD} tabular-nums`}>{r.valid_scans}/{r.scans}</td>}
                          <td className={`${TD} tabular-nums`}>
                            {r.incidents || "—"}
                            {r.incidents_serious > 0 && <div className="text-[12px] text-[var(--sd-data-red)]">{r.incidents_serious} serious</div>}
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </ScrollTable>
              <div className="h-2" />
            </Card>
          );
        })
      )}
    </PageShell>
  );
}
