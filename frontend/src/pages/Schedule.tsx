import { useCallback, useEffect, useMemo, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Card } from "@/components/Card";
import { FilterSelect } from "@/components/FilterSelect";
import { PageShell } from "@/components/PageShell";
import { RefreshButton } from "@/components/RefreshButton";
import { CoverDialog } from "@/components/scheduling/CoverDialog";
import { useToast } from "@/components/Toast";
import { isError } from "@/lib/frappe";
import { monthSchedule, schedulingOptions, toggleDay, type DayCell, type MonthSchedule, type ScheduleGuard } from "@/lib/scheduling-api";
import { useScope, useTerms } from "@/lib/scope";
import { cn } from "@/lib/utils";

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const SHORT: Record<string, string> = { Day: "D", Night: "N", First: "1", Second: "2", Third: "3" };

/** One cell: a letter for the shift, or the day-off state in a word-like mark - never colour alone. */
function cellLook(c: DayCell | undefined) {
  if (!c) return { text: "", cls: "", title: "" };
  if (c.state === "on") return { text: SHORT[c.shift_type ?? ""] ?? "•", cls: "bg-[var(--sd-line-soft)] text-[var(--sd-ink)]", title: `${c.shift_type} shift` };
  if (c.state === "off_covered") return { text: "C", cls: "bg-[var(--sd-alert-ok)] text-[var(--sd-sev-moderate)]", title: `Off - covered by ${c.covered_by_name}` };
  return { text: "!", cls: "bg-[var(--sd-alert-error)] text-[var(--sd-sev-critical)] font-bold", title: c.state === "off_no_reliever" ? "Off - no reliever set" : "Off - no cover" };
}

/** Every rostered external guard by day of the month: who is on, who is off, and who covers. */
export function Schedule() {
  const T = useTerms();
  const toast = useToast();
  const { scope } = useScope();
  const now = new Date();
  const [ym, setYm] = useState({ y: now.getFullYear(), m: now.getMonth() + 1 });
  const [farm, setFarm] = useState(scope.farm);
  const [data, setData] = useState<MonthSchedule | null>(null);
  const [loading, setLoading] = useState(true);
  const [canPlan, setCanPlan] = useState(false);
  const [cover, setCover] = useState<{ guard: string; guard_name: string; date: string; farm?: string; shift_type?: string } | null>(null);
  const [busy, setBusy] = useState("");

  useEffect(() => setFarm(scope.farm), [scope.farm]);
  useEffect(() => {
    void schedulingOptions().then((r) => !isError(r) && setCanPlan(r.can_plan));
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    const r = await monthSchedule(ym.y, ym.m, farm || undefined);
    setLoading(false);
    if (isError(r)) return void toast(r.error, "error");
    setData(r);
  }, [ym, farm, toast]);
  useEffect(() => {
    void load();
  }, [load]);

  const step = (d: number) => setYm(({ y, m }) => (m + d < 1 ? { y: y - 1, m: 12 } : m + d > 12 ? { y: y + 1, m: 1 } : { y, m: m + d }));
  const iso = (day: number) => `${ym.y}-${String(ym.m).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
  const todayIso = new Date().toISOString().slice(0, 10);

  const totals = useMemo(() => {
    let uncovered = 0;
    let covered = 0;
    for (const g of data?.guards ?? []) {
      for (const c of Object.values(data!.statuses[g.name] ?? {})) {
        if (c.state === "off_covered") covered++;
        else if (c.state !== "on") uncovered++;
      }
    }
    return { uncovered, covered };
  }, [data]);

  const click = async (g: ScheduleGuard, day: number, c: DayCell | undefined) => {
    if (!canPlan || !c) return;
    if (c.state === "on") {
      setCover({ guard: g.name, guard_name: g.full_name, date: iso(day), farm: g.farm, shift_type: c.shift_type });
      return;
    }
    // Off: put them back on (their usual shift, the cover released).
    if (!confirm(`Put ${g.full_name} back on duty on ${iso(day)}?${c.covered_by_name ? ` ${c.covered_by_name}'s cover is released.` : ""}`)) return;
    setBusy(`${g.name}-${day}`);
    const r = await toggleDay({ guard: g.name, date: iso(day), mark_off: 0, farm: g.farm });
    setBusy("");
    if (isError(r)) return void toast(r.error, "error");
    toast(`${g.full_name} is on duty on ${iso(day)}.`, "ok");
    void load();
  };

  return (
    <PageShell
      title="Monthly schedule"
      eyebrow="Scheduling"
      actions={
        <>
          <span className="inline-flex h-9 items-center gap-1 rounded-full bg-[var(--sd-card)] px-1.5 shadow-[var(--sd-shadow-1)]">
            <button type="button" aria-label="Previous month" className="grid size-7 place-items-center rounded-full hover:bg-[var(--sd-line-soft)]" onClick={() => step(-1)}><ChevronLeft className="h-4 w-4" /></button>
            <span className="min-w-[8.5rem] text-center text-[13px] font-medium">{MONTHS[ym.m - 1]} {ym.y}</span>
            <button type="button" aria-label="Next month" className="grid size-7 place-items-center rounded-full hover:bg-[var(--sd-line-soft)]" onClick={() => step(1)}><ChevronRight className="h-4 w-4" /></button>
          </span>
          <FilterSelect label={T.Site} value={farm} onChange={setFarm} options={data?.farms ?? []} allLabel={`All ${T.sites}`} />
          <RefreshButton onClick={() => void load()} loading={loading} label="Refresh schedule" />
        </>
      }
      description={
        canPlan
          ? "Click a working day to give that guard the day off, with cover. Click a day off to put them back on."
          : "Read only: planning is for Security Heads and those who can edit shift assignments."
      }
    >
      <div className="flex flex-wrap items-center gap-4 text-[12px] text-[var(--sd-muted)]">
        <span className="flex items-center gap-1.5"><span className="grid size-5 place-items-center rounded bg-[var(--sd-line-soft)] text-[11px] font-semibold">D</span>On (D day, N night, 1–3 shift)</span>
        <span className="flex items-center gap-1.5"><span className="grid size-5 place-items-center rounded bg-[var(--sd-alert-ok)] text-[11px] font-semibold text-[var(--sd-sev-moderate)]">C</span>Off, covered ({totals.covered})</span>
        <span className="flex items-center gap-1.5"><span className="grid size-5 place-items-center rounded bg-[var(--sd-alert-error)] text-[11px] font-bold text-[var(--sd-sev-critical)]">!</span>Off, no cover ({totals.uncovered})</span>
      </div>

      <Card>
        {!data ? (
          <p className="px-4 py-10 text-center text-[13px] text-[var(--sd-muted)]">Loading…</p>
        ) : data.guards.length === 0 ? (
          <p className="px-4 py-10 text-center text-[13px] text-[var(--sd-muted)]">No rostered external guards{farm ? ` at ${farm}` : ""}. A guard appears here once they are Active with a {T.site} and a post.</p>
        ) : (
          <div className={cn("overflow-auto", loading && "opacity-60")}>
            <table className="border-separate border-spacing-0.5 text-[12px]">
              <thead>
                <tr>
                  <th className="sticky left-0 z-10 bg-[var(--sd-card)] px-3 py-2 text-left font-medium text-[var(--sd-quiet)]">Guard</th>
                  {data.days.map((d) => {
                    const dt = new Date(ym.y, ym.m - 1, d);
                    const weekend = dt.getDay() === 0 || dt.getDay() === 6;
                    return (
                      <th key={d} className={cn("w-7 py-1 text-center font-medium", iso(d) === todayIso ? "rounded bg-[var(--sd-ink)] text-white" : weekend ? "text-[var(--sd-ink)]" : "text-[var(--sd-quiet)]")}>
                        <div>{d}</div>
                        <div className="text-[9px] uppercase opacity-70">{dt.toLocaleDateString("en-GB", { weekday: "narrow" })}</div>
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {data.guards.map((g) => (
                  <tr key={g.name}>
                    <td className="sticky left-0 z-10 min-w-[12rem] bg-[var(--sd-card)] px-3 py-1">
                      <div className="font-medium">{g.full_name}</div>
                      <div className="text-[11px] text-[var(--sd-quiet)]">{[g.farm, g.post].filter(Boolean).join(" · ")}{g.reliever_name ? ` · reliever ${g.reliever_name}` : ""}</div>
                    </td>
                    {data.days.map((d) => {
                      const c = data.statuses[g.name]?.[d];
                      const look = cellLook(c);
                      return (
                        <td key={d} className="p-0">
                          <button
                            type="button"
                            disabled={!canPlan || busy === `${g.name}-${d}`}
                            title={`${g.full_name}, ${iso(d)}: ${look.title}${c?.is_off_day ? " (rostered day off)" : ""}`}
                            onClick={() => void click(g, d, c)}
                            className={cn("grid size-7 place-items-center rounded text-[11px] font-semibold", look.cls, canPlan && "hover:ring-2 hover:ring-[var(--sd-ink)]/30", c?.is_off_day && "underline")}
                          >
                            {look.text}
                          </button>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <CoverDialog target={cover} onClose={() => setCover(null)} onDone={load} />
    </PageShell>
  );
}
