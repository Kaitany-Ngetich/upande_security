import { useCallback, useEffect, useState } from "react";
import { MapPin } from "lucide-react";
import { Card, TD, TH } from "@/components/Card";
import { ClearFiltersPill } from "@/components/ClearFiltersPill";
import { DateRangePicker, type DateRange } from "@/components/DateRangePicker";
import { TableRowsSkeleton } from "@/components/Loading";
import { PageShell } from "@/components/PageShell";
import { Pager } from "@/components/Pager";
import { PillTabs } from "@/components/PillTabs";
import { RefreshButton } from "@/components/RefreshButton";
import { ScopePicker } from "@/components/ScopePicker";
import { ScrollTable, STICKY_HEAD } from "@/components/ScrollTable";
import { SearchInput } from "@/components/SearchInput";
import { useToast } from "@/components/Toast";
import { SeverityTag } from "@/components/incidents/IncidentDialogs";
import { isError } from "@/lib/frappe";
import { accessAlerts } from "@/lib/registers-api";
import { useScope } from "@/lib/scope";
import { useDebounced } from "@/lib/use-debounced";
import { cn, todayISO } from "@/lib/utils";
import { when } from "@/lib/when";

const PAGE = 50;
function daysAgo(n: number) {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}
const LAST_7 = (): DateRange => ({ from: daysAgo(6), to: todayISO() });

/** What raises an alert, in a sentence, for the type tabs' tooltips. */
const MEANING: Record<string, string> = {
  "Off-Shift Account Use": "A gate action from a login whose guard is not on shift.",
  "Invalid Checkpoint Scan": "A checkpoint scan refused: too far away, poor or fake GPS, or an unknown code.",
  "Contractor Badge Refused": "A contractor badge that is not issued, expired or from another company.",
  "Invalid Asset Scan": "An asset label scanned where it does not belong.",
  "Gate Dispatch Rejected": "A truck stopped at the gate on a dispatch check.",
  "Gate Receiving Rejected": "A delivery turned away at the gate.",
};

/** Every security alert the gate, patrol and checkpoint checks raise. */
export function Alerts() {
  const toast = useToast();
  const { scope } = useScope();
  const [range, setRange] = useState<DateRange>(LAST_7);
  const [type, setType] = useState("");
  const [search, setSearch] = useState("");
  const q = useDebounced(search);
  const [start, setStart] = useState(0);
  const [data, setData] = useState<Awaited<ReturnType<typeof accessAlerts>> | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => setStart(0), [range, type, q, scope]);
  const load = useCallback(async () => {
    setLoading(true);
    const r = await accessAlerts({ from_date: range.from, to_date: range.to, company: scope.company || undefined, farm: scope.farm || undefined,
      attempt_type: type || undefined, search: q || undefined, start });
    setLoading(false);
    if (isError(r)) return void toast(r.error, "error");
    setData(r);
  }, [range, scope, type, q, start, toast]);
  useEffect(() => {
    void load();
  }, [load]);

  const d = data && !isError(data) ? data : null;
  const types = Object.entries(d?.by_type ?? {}).sort((a, b) => b[1] - a[1]);
  const dirty = !!type || !!search || range.from !== LAST_7().from || range.to !== todayISO();

  return (
    <PageShell
      title="Access alerts"
      eyebrow="Security"
      tabs={
        <PillTabs
          label="Alert type" value={type} onChange={setType}
          tabs={[{ key: "", label: "All", count: d?.total_all }, ...types.map(([t, n]) => ({ key: t, label: t, count: n }))]}
        />
      }
      actions={
        <>
          <ScopePicker />
          <DateRangePicker label="Dates" value={range} onChange={setRange} />
          <SearchInput value={search} onChange={setSearch} placeholder="Reference, person, detail" aria-label="Search alerts" />
          <ClearFiltersPill active={dirty} onClear={() => { setType(""); setSearch(""); setRange(LAST_7()); }} />
          <RefreshButton onClick={() => void load()} loading={loading} label="Refresh alerts" />
        </>
      }
      description={type && MEANING[type] ? MEANING[type] : "Raised automatically by the gate, patrol and checkpoint checks; Security Heads are notified of each one."}
    >
      <Card>
        <ScrollTable tall>
          <table className="w-full text-[13px]">
            <thead className={STICKY_HEAD}><tr><th className={TH}>When</th><th className={TH}>Alert</th><th className={TH}>Who</th><th className={TH}>Where</th><th className={TH}>Detail</th></tr></thead>
            <tbody>
              {!d ? <TableRowsSkeleton cols={5} rows={6} /> : d.rows.length === 0 ? (
                <tr><td colSpan={5} className="px-4 py-10 text-center text-[var(--sd-muted)]">No alerts in this period.</td></tr>
              ) : d.rows.map((a) => (
                <tr key={a.name} className={cn("border-t border-[var(--sd-line-soft)] align-top", loading && "opacity-60")}>
                  <td className={`${TD} tabular-nums`}>{when(a.attempt_time)}</td>
                  <td className={TD}>
                    <div className="font-medium">{a.attempt_type}</div>
                    <div className="mt-0.5 flex items-center gap-1.5">
                      {a.severity && <SeverityTag severity={a.severity} />}
                      {a.reference && <span className="text-[12px] text-[var(--sd-quiet)]">{a.reference}</span>}
                    </div>
                  </td>
                  <td className={TD}>{a.person_name || a.attempted_by_name || "—"}</td>
                  <td className={TD}>
                    {[a.farm, a.zone].filter(Boolean).join(" · ") || "—"}
                    {a.latitude && a.longitude && (
                      <a className="mt-0.5 flex items-center gap-1 text-[12px] underline" target="_blank" rel="noreferrer" href={`https://www.openstreetmap.org/?mlat=${a.latitude}&mlon=${a.longitude}#map=18/${a.latitude}/${a.longitude}`}>
                        <MapPin className="h-3 w-3" /> on the map
                      </a>
                    )}
                  </td>
                  <td className={`${TD} max-w-[48ch] text-[12px] text-[var(--sd-muted)]`}><span className="line-clamp-3 whitespace-pre-wrap">{a.detail || "—"}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollTable>
        <Pager start={start} total={d?.total ?? 0} page={PAGE} loading={loading} onChange={setStart} />
      </Card>
    </PageShell>
  );
}
