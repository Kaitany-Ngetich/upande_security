import { useCallback, useEffect, useMemo, useState } from "react";
import { MapPin } from "lucide-react";
import { Card, TD, TH, Verdict } from "@/components/Card";
import { TableRowsSkeleton } from "@/components/Loading";
import { PageShell } from "@/components/PageShell";
import { Pager } from "@/components/Pager";
import { RefreshButton } from "@/components/RefreshButton";
import { ScrollTable, STICKY_HEAD } from "@/components/ScrollTable";
import { SearchInput } from "@/components/SearchInput";
import { useToast } from "@/components/Toast";
import { isError } from "@/lib/frappe";
import { deviceBoard } from "@/lib/registers-api";
import { useDebounced } from "@/lib/use-debounced";
import { cn } from "@/lib/utils";
import { when } from "@/lib/when";

const PAGE = 100;

/** "1.2.21" sorts after "1.2.5". */
function cmpVersion(a: string, b: string) {
  const pa = a.split(".").map(Number);
  const pb = b.split(".").map(Number);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const d = (pa[i] ?? 0) - (pb[i] ?? 0);
    if (d) return d;
  }
  return 0;
}

/** The guard app on each phone: who uses it, which version, and when it was last open. */
export function Devices() {
  const toast = useToast();
  const [search, setSearch] = useState("");
  const q = useDebounced(search);
  const [start, setStart] = useState(0);
  const [data, setData] = useState<Awaited<ReturnType<typeof deviceBoard>> | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => setStart(0), [q]);
  const load = useCallback(async () => {
    setLoading(true);
    const r = await deviceBoard({ search: q || undefined, start });
    setLoading(false);
    if (isError(r)) return void toast(r.error, "error");
    setData(r);
  }, [q, start, toast]);
  useEffect(() => {
    void load();
  }, [load]);

  const d = data && !isError(data) ? data : null;
  const versions = useMemo(
    () => Object.entries(d?.versions ?? {}).filter(([v]) => v !== "?").sort((a, b) => cmpVersion(b[0], a[0])),
    [d],
  );
  const latest = versions[0]?.[0];
  const old = versions.filter(([v]) => v !== latest).reduce((t, [, n]) => t + n, 0);

  return (
    <PageShell
      title="Guard devices"
      eyebrow="Scheduling"
      actions={
        <>
          <SearchInput value={search} onChange={setSearch} placeholder="Guard, login, phone model" aria-label="Search devices" />
          <RefreshButton onClick={() => void load()} loading={loading} label="Refresh devices" />
        </>
      }
      description={latest ? `${d?.total ?? 0} phones · newest app ${latest} · ${old} on an older version.` : undefined}
    >
      {versions.length > 0 && (
        <div className="flex flex-wrap gap-2 text-[12px]">
          {versions.map(([v, n]) => (
            <span key={v} className={cn("rounded-full px-2.5 py-1", v === latest ? "bg-[var(--sd-alert-ok)] text-[var(--sd-sev-moderate)]" : "bg-[var(--sd-line-soft)]")}>
              {v} <span className="font-semibold tabular-nums">{n}</span>
            </span>
          ))}
        </div>
      )}
      <Card>
        <ScrollTable tall>
          <table className="w-full text-[13px]">
            <thead className={STICKY_HEAD}><tr><th className={TH}>Guard</th><th className={TH}>Phone</th><th className={TH}>App</th><th className={TH}>Last opened</th><th className={TH}>Last seen</th></tr></thead>
            <tbody>
              {!d ? <TableRowsSkeleton cols={5} rows={6} /> : d.rows.length === 0 ? (
                <tr><td colSpan={5} className="px-4 py-10 text-center text-[var(--sd-muted)]">No devices.</td></tr>
              ) : d.rows.map((r) => (
                <tr key={r.name} className={cn("border-t border-[var(--sd-line-soft)] align-top", loading && "opacity-60")}>
                  <td className={TD}>{r.guard_name || r.login_user || "—"}<div className="text-[12px] text-[var(--sd-quiet)]">{[r.guard_type, r.login_user].filter(Boolean).join(" · ")}</div></td>
                  <td className={TD}>{r.device_model || "—"}<div className="text-[12px] text-[var(--sd-quiet)]">{[r.platform, r.os_version].filter(Boolean).join(" ")}</div></td>
                  <td className={TD}>
                    {r.app_version ? <Verdict ok={r.app_version === latest ? true : null}>{r.app_version}</Verdict> : "—"}
                    {r.update_status && <div className="text-[12px] text-[var(--sd-quiet)]">update: {r.update_status}</div>}
                  </td>
                  <td className={`${TD} tabular-nums`}>{when(r.last_app_open || r.modified)}</td>
                  <td className={TD}>
                    {r.last_seen_lat && r.last_seen_lng ? (
                      <a className="inline-flex items-center gap-1 text-[12px] underline" target="_blank" rel="noreferrer" href={`https://www.openstreetmap.org/?mlat=${r.last_seen_lat}&mlon=${r.last_seen_lng}#map=17/${r.last_seen_lat}/${r.last_seen_lng}`}>
                        <MapPin className="h-3 w-3" /> {when(r.updated_at || r.modified)}
                      </a>
                    ) : <span className="text-[var(--sd-quiet)]">—</span>}
                  </td>
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
