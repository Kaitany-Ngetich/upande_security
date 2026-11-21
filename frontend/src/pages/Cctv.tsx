import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Bell, BellOff, Car, CheckCircle2, Clock, Eye, FileWarning, LogOut, MapPin, Search, ShieldOff, UserPlus, Video } from "lucide-react";
import { Card, TD, TH } from "@/components/Card";
import { DateRangePicker, type DateRange } from "@/components/DateRangePicker";
import { KpiCard } from "@/components/KpiCard";
import { TableRowsSkeleton } from "@/components/Loading";
import { PageShell } from "@/components/PageShell";
import { Pager } from "@/components/Pager";
import { PillTabs } from "@/components/PillTabs";
import { RefreshButton } from "@/components/RefreshButton";
import { ScopePicker } from "@/components/ScopePicker";
import { ScrollTable, STICKY_HEAD } from "@/components/ScrollTable";
import { SearchInput } from "@/components/SearchInput";
import { useToast } from "@/components/Toast";
import { VideoPlayer } from "@/components/cctv/VideoPlayer";
import { SeverityTag } from "@/components/incidents/IncidentDialogs";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import * as api from "@/lib/cctv-api";
import { isError } from "@/lib/frappe";
import { useScope } from "@/lib/scope";
import { useDebounced } from "@/lib/use-debounced";
import { cn, todayISO } from "@/lib/utils";
import { when } from "@/lib/when";

const EYEBROW = "CCTV";
const daysAgo = (n: number) => {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
};
const LAST_7 = (): DateRange => ({ from: daysAgo(6), to: todayISO() });

function duration(min: number | null | undefined) {
  if (min == null) return "—";
  const h = Math.floor(min / 60);
  return h ? `${h} h ${min % 60} min` : `${min} min`;
}
function ago(min: number | null | undefined) {
  if (min == null) return "";
  return min < 1 ? "just now" : min < 60 ? `${min} min ago` : `${Math.floor(min / 60)} h ago`;
}
/** Local "YYYY-MM-DD HH:MM:SS" +/- seconds, for asking the recorder for a range. */
function shift(dt: string, seconds: number) {
  const d = new Date(dt.replace(" ", "T"));
  d.setSeconds(d.getSeconds() + seconds);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}
function StatusDot({ status }: { status: string }) {
  const tone = status === "Online" ? "bg-[var(--sd-data-green,#3f7d3a)]" : status === "Offline" ? "bg-[var(--sd-data-red)]" : "bg-[var(--sd-quiet)]";
  return <span className="inline-flex items-center gap-1.5"><span className={cn("h-2 w-2 rounded-full", tone)} aria-hidden />{status}</span>;
}
const Empty = ({ cols, text }: { cols: number; text: string }) => (
  <tr><td colSpan={cols} className="px-4 py-10 text-center text-[var(--sd-muted)]">{text}</td></tr>
);

// ===================================================================== Live view

const LAYOUTS = [1, 4, 9, 16] as const;

export function CctvLive() {
  const toast = useToast();
  const { scope } = useScope();
  const [cams, setCams] = useState<api.Camera[] | null>(null);
  const [layout, setLayout] = useState<number>(4);
  const [page, setPage] = useState(0);
  const [big, setBig] = useState<api.Camera | null>(null);
  const [search, setSearch] = useState("");

  const load = useCallback(async () => {
    const r = await api.listCameras({ farm: scope.farm || undefined });
    if (isError(r)) return void toast(r.error, "error");
    setCams(r);
  }, [scope.farm, toast]);
  useEffect(() => void load(), [load]);
  useEffect(() => setPage(0), [layout, search, scope.farm]);

  const shown = (cams ?? []).filter((c) => !search || `${c.camera_name} ${c.zone ?? ""} ${c.gate ?? ""} ${c.role}`.toLowerCase().includes(search.toLowerCase()));
  const pages = Math.max(1, Math.ceil(shown.length / layout));
  const tiles = shown.slice(page * layout, page * layout + layout);
  const cols = layout === 1 ? "grid-cols-1" : layout === 4 ? "grid-cols-1 sm:grid-cols-2" : layout === 9 ? "grid-cols-2 lg:grid-cols-3" : "grid-cols-2 lg:grid-cols-4";

  return (
    <PageShell
      title="Live view"
      eyebrow={EYEBROW}
      tabs={<PillTabs label="Grid" value={String(layout)} onChange={(v) => setLayout(Number(v))} tabs={LAYOUTS.map((n) => ({ key: String(n), label: `${n}` }))} />}
      actions={
        <>
          <ScopePicker />
          <SearchInput value={search} onChange={setSearch} placeholder="Camera, zone, gate" aria-label="Find a camera" />
          <RefreshButton onClick={() => void load()} loading={!cams} label="Reload cameras" />
        </>
      }
      description="Streams come straight from the site's recorder through its media gateway; nothing is recorded here. Grids use the low-bandwidth stream - open a camera for full quality."
    >
      {!cams ? <Card><div className="p-6 text-[13px] text-[var(--sd-muted)]">Loading cameras…</div></Card> : !shown.length ? (
        <Card><div className="p-6 text-[13px] text-[var(--sd-muted)]">No cameras you may view here.</div></Card>
      ) : (
        <>
          <div className={cn("grid gap-3", cols)}>
            {tiles.map((c) => (
              <div key={c.name} className="group relative">
                <VideoPlayer
                  key={`${c.name}-${layout}`}
                  className="aspect-video"
                  label={`${c.camera_name}${c.zone ? ` · ${c.zone}` : ""}`}
                  getTicket={() => api.liveTicket(c.name, layout === 1 ? "main" : "sub")}
                  overlay={
                    <button type="button" onClick={() => setBig(c)} className="absolute bottom-2 right-2 rounded-full bg-black/60 px-2.5 py-1 text-[11px] text-white opacity-0 transition group-hover:opacity-100">
                      Open
                    </button>
                  }
                />
                {c.status !== "Online" && <span className="absolute left-2 bottom-2 rounded bg-black/60 px-1.5 py-0.5 text-[11px] text-white"><StatusDot status={c.status} /></span>}
              </div>
            ))}
          </div>
          {pages > 1 && (
            <div className="flex items-center justify-center gap-2 text-[13px]">
              <Button variant="outline" size="sm" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>Previous</Button>
              <span className="text-[var(--sd-muted)]">{page + 1} / {pages}</span>
              <Button variant="outline" size="sm" disabled={page >= pages - 1} onClick={() => setPage((p) => p + 1)}>Next</Button>
            </div>
          )}
        </>
      )}
      <Dialog open={!!big} onOpenChange={(o) => !o && setBig(null)}>
        <DialogContent className="max-w-5xl">
          <DialogHeader>
            <DialogTitle>{big?.camera_name}</DialogTitle>
            <DialogDescription>{[big?.farm, big?.zone, big?.gate].filter(Boolean).join(" · ")}</DialogDescription>
          </DialogHeader>
          {big && <VideoPlayer className="aspect-video" label={big.camera_name} getTicket={() => api.liveTicket(big.name, "main")} />}
        </DialogContent>
      </Dialog>
    </PageShell>
  );
}

// ===================================================================== Alerts

const STATUS_TABS = ["Active", "Open", "Escalated", "Acknowledged", "Resolved", "False Alarm", ""] as const;

function beep() {
  try {
    const ctx = new AudioContext();
    const o = ctx.createOscillator();
    const g = ctx.createGain();
    o.frequency.value = 880;
    g.gain.setValueAtTime(0.2, ctx.currentTime);
    g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.6);
    o.connect(g).connect(ctx.destination);
    o.start();
    o.stop(ctx.currentTime + 0.6);
  } catch {
    /* no audio */
  }
}

export function CctvAlerts() {
  const toast = useToast();
  const { scope } = useScope();
  const [status, setStatus] = useState<string>("Active");
  const [range, setRange] = useState<DateRange>(LAST_7);
  const [search, setSearch] = useState("");
  const q = useDebounced(search);
  const [start, setStart] = useState(0);
  const [data, setData] = useState<api.AlertBoard | null>(null);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState<string | null>(() => new URLSearchParams(window.location.hash.split("?")[1] || "").get("alert"));
  const [sound, setSound] = useState(() => localStorage.getItem("cctv.sound") === "1");
  const seen = useRef<Set<string> | null>(null);

  useEffect(() => setStart(0), [status, range, q, scope]);
  const load = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    const r = await api.alertBoard({ status: status || undefined, from_date: range.from, to_date: range.to, company: scope.company || undefined,
      farm: scope.farm || undefined, search: q || undefined, start });
    setLoading(false);
    if (isError(r)) return void (!quiet && toast(r.error, "error"));
    // Sound for a new High/Critical alert that appeared since the last poll.
    const urgent = r.rows.filter((a) => (a.severity === "Critical" || a.severity === "High") && a.status === "Open");
    if (seen.current && sound && urgent.some((a) => !seen.current!.has(a.name))) beep();
    seen.current = new Set(r.rows.map((a) => a.name));
    setData(r);
  }, [status, range, scope, q, start, sound, toast]);
  useEffect(() => {
    void load();
    const t = setInterval(() => void load(true), 15000);
    return () => clearInterval(t);
  }, [load]);

  const c = data?.counts;
  return (
    <PageShell
      title="Alert console"
      eyebrow={EYEBROW}
      tabs={
        <PillTabs
          label="Status" value={status} onChange={setStatus}
          tabs={STATUS_TABS.map((s) => ({
            key: s,
            label: s || "All",
            count: !c ? undefined : s === "Active" ? c.Open + c.Escalated + c.Acknowledged : s ? c[s as api.AlertStatus] : undefined,
          }))}
        />
      }
      actions={
        <>
          <ScopePicker />
          <DateRangePicker label="Dates" value={range} onChange={setRange} />
          <SearchInput value={search} onChange={setSearch} placeholder="Plate, person, alert" aria-label="Search alerts" />
          <Button variant="outline" size="sm" onClick={() => { const v = !sound; setSound(v); localStorage.setItem("cctv.sound", v ? "1" : "0"); if (v) beep(); }}
            aria-pressed={sound} title="Sound for new high and critical alerts">
            {sound ? <Bell /> : <BellOff />} {sound ? "Sound on" : "Sound off"}
          </Button>
          <RefreshButton onClick={() => void load()} loading={loading} label="Refresh alerts" />
        </>
      }
      description="Raised by camera events and vehicle checks. Each alert opens the recorder's footage at the moment it happened. Refreshes every 15 seconds."
    >
      <Card>
        <ScrollTable tall>
          <table className="w-full text-[13px]">
            <thead className={STICKY_HEAD}><tr><th className={TH}>When</th><th className={TH}>Alert</th><th className={TH}>Where</th><th className={TH}>Who / what</th><th className={TH}>Status</th></tr></thead>
            <tbody>
              {!data ? <TableRowsSkeleton cols={5} rows={6} /> : !data.rows.length ? <Empty cols={5} text="No alerts here." /> : data.rows.map((a) => (
                <tr key={a.name} onClick={() => setOpen(a.name)} className={cn("cursor-pointer border-t border-[var(--sd-line-soft)] align-top hover:bg-[var(--sd-line-soft)]/40",
                  a.status === "Open" && (a.severity === "Critical" || a.severity === "High") && "bg-[var(--sd-alert-error)]/40", loading && "opacity-60")}>
                  <td className={`${TD} tabular-nums`}>{when(a.event_time)}</td>
                  <td className={TD}>
                    <div className="font-medium">{a.alert_type}</div>
                    <div className="mt-0.5 flex items-center gap-1.5">
                      <SeverityTag severity={a.severity} />
                      {a.repeat_count > 0 && <span className="text-[11px] text-[var(--sd-quiet)]">×{a.repeat_count + 1}</span>}
                      {a.escalation_level > 0 && <span className="text-[11px] text-[var(--sd-sev-high)]">escalated {a.escalation_level}</span>}
                    </div>
                  </td>
                  <td className={TD}>{[a.farm, a.zone, a.camera_name].filter(Boolean).join(" · ") || "—"}</td>
                  <td className={TD}>{a.plate || a.person_name || <span className="text-[var(--sd-muted)] line-clamp-2">{a.summary}</span>}</td>
                  <td className={TD}>{a.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollTable>
        <Pager start={start} total={data?.total ?? 0} page={50} loading={loading} onChange={setStart} />
      </Card>
      <AlertDialog name={open} onClose={() => setOpen(null)} onChanged={() => void load(true)} />
    </PageShell>
  );
}

function AlertDialog({ name, onClose, onChanged }: { name: string | null; onClose: () => void; onChanged: () => void }) {
  const toast = useToast();
  const [a, setA] = useState<api.AlertDetail | null>(null);
  const [cam, setCam] = useState<string | null>(null);
  const [ticket, setTicket] = useState<api.StreamTicket | null>(null);
  const [notes, setNotes] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [elapsed, setElapsed] = useState(0);

  const load = useCallback(async () => {
    if (!name) return;
    const r = await api.alertDetail(name);
    if (isError(r)) return void toast(r.error, "error");
    setA(r);
    setCam((c) => c ?? r.camera);
  }, [name, toast]);
  useEffect(() => {
    setA(null);
    setCam(null);
    setNotes("");
    setReason("");
    if (name) {
      void load();
      void api.markViewed(name);
    }
  }, [name, load]);
  useEffect(() => {
    setElapsed(0);
    if (!ticket) return;
    const t = setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => clearInterval(t);
  }, [ticket]);

  const act = async (fn: () => Promise<unknown>, done: string) => {
    setBusy(true);
    const r = (await fn()) as { error?: string };
    setBusy(false);
    if (r && isError(r as never)) return void toast((r as { error: string }).error, "error");
    toast(done, "ok");
    onChanged();
    void load();
  };
  const offset = ticket?.event_offset_seconds ?? null;
  const cams = a ? [{ camera: a.camera, camera_name: a.camera_name, reason: "Alert camera" }, ...a.related].filter((c) => c.camera) : [];

  return (
    <Dialog open={!!name} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[92vh] max-w-4xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex flex-wrap items-center gap-2">{a?.alert_type ?? "Alert"} {a && <SeverityTag severity={a.severity} />}</DialogTitle>
          <DialogDescription>{a ? `${when(a.event_time)} · ${[a.farm, a.zone, a.camera_name].filter(Boolean).join(" · ")} · ${a.status}` : "Loading…"}</DialogDescription>
        </DialogHeader>
        {a && (
          <div className="grid gap-4 md:grid-cols-[1fr_260px]">
            <div className="flex flex-col gap-2">
              {cam ? (
                <VideoPlayer
                  key={cam}
                  className="aspect-video"
                  label={`Recording · ${cams.find((c) => c.camera === cam)?.camera_name ?? ""}`}
                  getTicket={() => api.alertPlayback(a.name, cam)}
                  onTicket={setTicket}
                  overlay={offset != null && (
                    <div className="absolute bottom-2 left-2 rounded bg-black/70 px-2 py-1 text-[11px] text-white tabular-nums">
                      {elapsed < offset ? `Event in ${offset - elapsed}s` : `Event was ${elapsed - offset}s ago`}
                    </div>
                  )}
                />
              ) : a.snapshot ? <img src={a.snapshot} alt="Snapshot" className="rounded-[var(--sd-radius)]" /> : null}
              {cams.length > 1 && (
                <div className="flex flex-wrap gap-1.5">
                  {cams.map((c) => (
                    <button key={c.camera} type="button" onClick={() => setCam(c.camera)}
                      className={cn("rounded-full px-2.5 py-1 text-[12px]", cam === c.camera ? "bg-[var(--sd-ink)] text-white" : "bg-[var(--sd-line-soft)]")}>
                      <Video className="mr-1 inline h-3 w-3" />{c.camera_name}
                    </button>
                  ))}
                </div>
              )}
              <p className="text-[12px] text-[var(--sd-muted)]">
                Clip {when(a.clip_start)} – {when(a.clip_end)}. Footage plays from the recorder; if it has already been overwritten the player says so.
              </p>
            </div>
            <div className="flex flex-col gap-3 text-[13px]">
              {a.summary && <p>{a.summary}</p>}
              {a.plate && <p><span className="text-[var(--sd-muted)]">Plate</span> <b className="tracking-wide">{a.plate}</b></p>}
              {a.person_name && <p><span className="text-[var(--sd-muted)]">Person</span> {a.person_name}</p>}
              {a.visit && <p><span className="text-[var(--sd-muted)]">Vehicle</span> {a.visit.party_name} ({a.visit.status})</p>}
              {a.incident && <a className="underline" href={`/app/incident-report/${a.incident}`} target="_blank" rel="noreferrer">Incident {a.incident}</a>}
              {a.acknowledged_by && <p className="text-[12px] text-[var(--sd-muted)]">Acknowledged by {a.acknowledged_by} {when(a.acknowledged_at)}</p>}
              {a.can_act && !["Resolved", "False Alarm"].includes(a.status) && (
                <div className="flex flex-col gap-2 border-t border-[var(--sd-line-soft)] pt-3">
                  <Textarea value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Notes (what you found, what you did)" rows={3} />
                  {a.status !== "Acknowledged" && (
                    <Button disabled={busy} onClick={() => act(() => api.acknowledgeAlert(a.name, notes || undefined), "Acknowledged - escalation stopped.")}>
                      <CheckCircle2 /> Acknowledge
                    </Button>
                  )}
                  <Button variant="outline" disabled={busy} onClick={() => act(() => api.resolveAlert(a.name, notes || undefined), "Resolved.")}>Resolve</Button>
                  <div className="flex gap-2">
                    <select value={reason} onChange={(e) => setReason(e.target.value)} aria-label="False alarm reason"
                      className="h-9 min-w-0 flex-1 rounded-md border border-input bg-background px-2 text-[13px]">
                      <option value="">False alarm because…</option>
                      {a.false_alarm_reasons.map((r) => <option key={r}>{r}</option>)}
                    </select>
                    <Button variant="outline" disabled={busy || !reason} onClick={() => act(() => api.falseAlarm(a.name, reason, notes || undefined), "Marked a false alarm.")}>Save</Button>
                  </div>
                  <div className="flex gap-2">
                    <Button variant="outline" size="sm" className="flex-1" disabled={busy} onClick={() => act(() => api.escalateAlert(a.name), "Escalated.")}>Escalate</Button>
                    {!a.incident && (
                      <Button variant="outline" size="sm" className="flex-1" disabled={busy} onClick={() => act(() => api.alertIncident(a.name), "Incident report opened.")}>
                        <FileWarning /> Incident
                      </Button>
                    )}
                  </div>
                </div>
              )}
              {a.notifications.length > 0 && (
                <details className="text-[12px] text-[var(--sd-muted)]">
                  <summary className="cursor-pointer">Who was told ({a.notifications.length})</summary>
                  <ul className="mt-1 space-y-0.5">{a.notifications.map((n, i) => <li key={i}>{n.recipient} · {n.channel} · {n.delivery_status}</li>)}</ul>
                </details>
              )}
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

// ===================================================================== Vehicles

export function CctvVehicles() {
  const toast = useToast();
  const { scope } = useScope();
  const [tab, setTab] = useState("On Site");
  const [range, setRange] = useState<DateRange>(LAST_7);
  const [search, setSearch] = useState("");
  const q = useDebounced(search);
  const [start, setStart] = useState(0);
  const [data, setData] = useState<api.VisitBoard | null>(null);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => setStart(0), [tab, range, q, scope]);
  const load = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    const r = await api.visitBoard({ status: tab, from_date: range.from, to_date: range.to, company: scope.company || undefined,
      farm: scope.farm || undefined, search: q || undefined, start });
    setLoading(false);
    if (isError(r)) return void (!quiet && toast(r.error, "error"));
    setData(r);
  }, [tab, range, scope, q, start, toast]);
  useEffect(() => {
    void load();
    const t = setInterval(() => void load(true), 30000);
    return () => clearInterval(t);
  }, [load]);

  const k = data?.kpis;
  return (
    <PageShell
      title="Vehicles on site"
      eyebrow={EYEBROW}
      tabs={<PillTabs label="View" value={tab} onChange={setTab} tabs={[{ key: "On Site", label: "On site", count: k?.on_site }, { key: "All", label: "Visit log" },
        { key: "Overstayed", label: "Overstayed", count: k?.overstayed }, { key: "Exit Not Recorded", label: "Exit not recorded" }]} />}
      actions={
        <>
          <ScopePicker />
          {tab !== "On Site" && <DateRangePicker label="Dates" value={range} onChange={setRange} />}
          <SearchInput value={search} onChange={setSearch} placeholder="Plate or name" aria-label="Search vehicles" />
          <RefreshButton onClick={() => void load()} loading={loading} label="Refresh" />
        </>
      }
      description="One visit per stay: the gate camera's entry read opens it, later reads update where it was last seen, the exit read closes it. Last seen is where a camera last read the plate - not proof it is still there."
    >
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <KpiCard label="On site now" value={k?.on_site ?? 0} loading={!k} />
        <KpiCard label="Arrivals today" value={k?.arrivals_today ?? 0} loading={!k} />
        <KpiCard label="Departures today" value={k?.departures_today ?? 0} loading={!k} />
        <KpiCard label="Overstayed" value={k?.overstayed ?? 0} tone={k?.overstayed ? "warning" : "default"} loading={!k} />
        <KpiCard label="Not confirmed by gate" value={k?.unconfirmed ?? 0} loading={!k} />
        <KpiCard label="Waiting for review" value={k?.review_open ?? 0} tone={k?.review_open ? "warning" : "default"} loading={!k} href="#/cctv-review" />
      </div>
      {tab === "On Site" ? (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {!data ? <Card><div className="p-6 text-[13px] text-[var(--sd-muted)]">Loading…</div></Card> : !data.rows.length ? (
            <Card><div className="p-6 text-[13px] text-[var(--sd-muted)]">No vehicles on site.</div></Card>
          ) : data.rows.map((v) => (
            <button key={v.name} type="button" onClick={() => setOpen(v.name)}
              className={cn("flex flex-col gap-2 rounded-[var(--sd-radius-lg)] bg-[var(--sd-card)] p-4 text-left shadow-[var(--sd-shadow-1)] hover:shadow-[var(--sd-shadow-2,var(--sd-shadow-1))]",
                v.overdue && "ring-1 ring-[var(--sd-target)]")}>
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className="text-[15px] font-semibold">{v.party_name}</div>
                  <div className="text-[12px] text-[var(--sd-muted)]">{v.party_type}{v.colour ? ` · ${v.colour}` : ""}{v.vehicle_class ? ` · ${v.vehicle_class}` : ""}</div>
                </div>
                <span className="rounded bg-[var(--sd-ink)] px-2 py-0.5 font-mono text-[13px] tracking-wider text-white">{v.plate}</span>
              </div>
              <div className="flex flex-wrap gap-x-4 gap-y-1 text-[12px]">
                <span className="inline-flex items-center gap-1"><Clock className="h-3.5 w-3.5" /> {duration(v.minutes_inside)} inside</span>
                {v.last_seen_camera_name && <span className="inline-flex items-center gap-1"><MapPin className="h-3.5 w-3.5" /> {v.last_seen_camera_name} {ago(v.seen_minutes_ago)}</span>}
              </div>
              <div className="flex flex-wrap gap-1.5 text-[11px]">
                {v.overdue && <span className="rounded-full bg-[var(--sd-alert-warn)] px-2 py-0.5">past expected exit</span>}
                {!v.guard_confirmed && <span className="rounded-full bg-[var(--sd-line-soft)] px-2 py-0.5">not confirmed at gate</span>}
                {v.flags_text?.split("\n").map((f) => <span key={f} className="rounded-full bg-[var(--sd-line-soft)] px-2 py-0.5">{f}</span>)}
              </div>
            </button>
          ))}
        </div>
      ) : (
        <Card>
          <ScrollTable tall>
            <table className="w-full text-[13px]">
              <thead className={STICKY_HEAD}><tr><th className={TH}>Plate</th><th className={TH}>Who</th><th className={TH}>In</th><th className={TH}>Out</th><th className={TH}>Time inside</th><th className={TH}>Status</th></tr></thead>
              <tbody>
                {!data ? <TableRowsSkeleton cols={6} rows={6} /> : !data.rows.length ? <Empty cols={6} text="No visits in this period." /> : data.rows.map((v) => (
                  <tr key={v.name} onClick={() => setOpen(v.name)} className={cn("cursor-pointer border-t border-[var(--sd-line-soft)] hover:bg-[var(--sd-line-soft)]/40", loading && "opacity-60")}>
                    <td className={`${TD} font-mono`}>{v.plate}</td>
                    <td className={TD}>{v.party_name}<div className="text-[12px] text-[var(--sd-muted)]">{v.party_type}</div></td>
                    <td className={`${TD} tabular-nums`}>{when(v.entry_time)}</td>
                    <td className={`${TD} tabular-nums`}>{when(v.exit_time)}</td>
                    <td className={TD}>{duration(v.minutes_inside)}</td>
                    <td className={TD}>{v.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </ScrollTable>
          <Pager start={start} total={data?.total ?? 0} page={50} loading={loading} onChange={setStart} />
        </Card>
      )}
      <VisitDialog name={open} onClose={() => setOpen(null)} onChanged={() => void load(true)} />
    </PageShell>
  );
}

function VisitDialog({ name, onClose, onChanged }: { name: string | null; onClose: () => void; onChanged: () => void }) {
  const toast = useToast();
  const [v, setV] = useState<Awaited<ReturnType<typeof api.visitDetail>> | null>(null);
  const [play, setPlay] = useState<api.Sighting | null>(null);
  const [plate, setPlate] = useState("");
  const load = useCallback(async () => {
    if (!name) return;
    const r = await api.visitDetail(name);
    if (isError(r)) return void toast(r.error, "error");
    setV(r);
    setPlate(r.plate);
  }, [name, toast]);
  useEffect(() => {
    setV(null);
    setPlay(null);
    void load();
  }, [load]);
  const d = v && !isError(v) ? v : null;
  const run = async (p: Promise<unknown>, done: string) => {
    const r = (await p) as never;
    if (isError(r)) return void toast((r as { error: string }).error, "error");
    toast(done, "ok");
    onChanged();
    void load();
  };
  return (
    <Dialog open={!!name} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[92vh] max-w-3xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><Car className="h-5 w-5" /> {d ? `${d.plate} · ${d.party_name}` : "Vehicle visit"}</DialogTitle>
          <DialogDescription>{d ? `${d.party_type} · ${d.status} · ${duration(d.minutes_inside)} inside` : "Loading…"}</DialogDescription>
        </DialogHeader>
        {d && (
          <div className="flex flex-col gap-3 text-[13px]">
            {play && (
              <VideoPlayer key={play.name} className="aspect-video" label={`Recording · ${play.camera_name ?? ""}`}
                getTicket={() => api.rangePlayback(play.camera, shift(play.sighting_time, -15), shift(play.sighting_time, 60), "Vehicle Visit")} />
            )}
            <ol className="flex flex-col gap-2">
              {d.sightings.map((s) => (
                <li key={s.name} className="flex items-center gap-3 rounded-[var(--sd-radius)] bg-[var(--sd-line-soft)]/50 px-3 py-2">
                  {s.vehicle_image || s.plate_image ? <img src={(s.plate_image || s.vehicle_image)!} alt="" className="h-10 w-16 rounded object-cover" /> : <Eye className="h-4 w-4 text-[var(--sd-quiet)]" />}
                  <div className="flex-1">
                    <div className="font-medium">{s.camera_name}{s.direction && s.direction !== "unknown" ? ` · ${s.direction}` : ""}</div>
                    <div className="text-[12px] text-[var(--sd-muted)] tabular-nums">{when(s.sighting_time)} · read “{s.plate_read}” ({Math.round(s.confidence)}%)</div>
                  </div>
                  <Button variant="outline" size="sm" onClick={() => setPlay(s)}><Video /> Footage</Button>
                </li>
              ))}
            </ol>
            {d.reference_name && <p className="text-[12px] text-[var(--sd-muted)]">Linked to {d.reference_doctype} <a className="underline" target="_blank" rel="noreferrer" href={`/app/${d.reference_doctype!.toLowerCase().replace(/ /g, "-")}/${d.reference_name}`}>{d.reference_name}</a></p>}
            {d.flags_text && <p className="text-[12px] text-[var(--sd-sev-high)] whitespace-pre-line">{d.flags_text}</p>}
            {["On Premises", "Overstayed", "Exit Not Recorded"].includes(d.status) && (
              <div className="flex flex-wrap items-center gap-2 border-t border-[var(--sd-line-soft)] pt-3">
                <Input value={plate} onChange={(e) => setPlate(e.target.value.toUpperCase())} className="w-36 font-mono" aria-label="Correct plate" />
                <Button disabled={!!d.guard_confirmed && plate === d.plate} onClick={() => run(api.confirmVisit(d.name, plate !== d.plate ? { corrected_plate: plate } : {}), "Confirmed.")}>
                  <CheckCircle2 /> {plate !== d.plate ? "Correct plate" : "Confirm"}
                </Button>
                <Button variant="outline" onClick={() => run(api.closeVisit(d.name), "Visit closed.")}><LogOut /> Left - close visit</Button>
              </div>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

// ===================================================================== Review queue

export function CctvReview() {
  const toast = useToast();
  const { scope } = useScope();
  const [status, setStatus] = useState("Open");
  const [data, setData] = useState<{ counts: Record<string, number>; rows: api.ReviewRow[] } | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    const r = await api.reviewBoard({ status, company: scope.company || undefined, farm: scope.farm || undefined });
    setLoading(false);
    if (isError(r)) return void (!quiet && toast(r.error, "error"));
    setData(r);
  }, [status, scope, toast]);
  useEffect(() => {
    void load();
    const t = setInterval(() => void load(true), 10000);
    return () => clearInterval(t);
  }, [load]);

  const c = data?.counts;
  return (
    <PageShell
      title="Plate review"
      eyebrow={EYEBROW}
      tabs={<PillTabs label="Status" value={status} onChange={setStatus} tabs={[{ key: "Open", label: "Waiting", count: c ? c.Open + c.Escalated : undefined }, { key: "Resolved", label: "Done", count: c?.Resolved }]} />}
      actions={<><ScopePicker /><RefreshButton onClick={() => void load()} loading={loading} label="Refresh" /></>}
      description="Reads the system was not sure about. Pick who the vehicle belongs to, correct a misread plate, register a walk-in, or ignore it. Every decision also teaches the plate reader."
    >
      <div className="flex flex-col gap-3">
        {!data ? <Card><div className="p-6 text-[13px] text-[var(--sd-muted)]">Loading…</div></Card> : !data.rows.length ? (
          <Card><div className="p-6 text-[13px] text-[var(--sd-muted)]">{status === "Open" ? "Nothing waiting. 👍" : "Nothing resolved yet."}</div></Card>
        ) : data.rows.map((r) => <ReviewCard key={r.name} r={r} onDone={() => void load(true)} />)}
      </div>
    </PageShell>
  );
}

function ReviewCard({ r, onDone }: { r: api.ReviewRow; onDone: () => void }) {
  const toast = useToast();
  const [plate, setPlate] = useState(r.plate);
  const [txt, setTxt] = useState("");
  const q = useDebounced(txt);
  const [targets, setTargets] = useState<api.LinkTarget[]>([]);
  const [walkIn, setWalkIn] = useState(false);
  const [wName, setWName] = useState("");
  const [wPhone, setWPhone] = useState("");
  const [busy, setBusy] = useState(false);
  const done = r.status === "Resolved";

  useEffect(() => {
    if (!q) return setTargets([]);
    void api.linkTargets(r.farm, q).then((x) => !isError(x) && setTargets(x));
  }, [q, r.farm]);

  const resolve = async (resolution: string, doctype?: string, docname?: string) => {
    setBusy(true);
    const res = await api.resolveReview(r.name, resolution, { linked_doctype: doctype, linked_name: docname,
      corrected_plate: plate !== r.plate ? plate : undefined });
    setBusy(false);
    if (isError(res)) return void toast(res.error, "error");
    toast(`${r.plate}: ${resolution.toLowerCase()}.`, "ok");
    onDone();
  };
  const createWalkIn = async () => {
    setBusy(true);
    const res = await api.walkInFromReview(r.name, wName, wPhone || undefined);
    setBusy(false);
    if (isError(res) || res.error) return void toast((res as { error: string }).error, "error");
    toast(`Walk-in ${res.name} registered.`, "ok");
    onDone();
  };

  return (
    <Card className={cn(r.late && !done && "ring-1 ring-[var(--sd-target)]")}>
      <div className="grid gap-4 p-4 md:grid-cols-[220px_1fr]">
        <div className="flex flex-col gap-2">
          {r.sighting_plate_image || r.sighting_vehicle_image ? (
            <img src={(r.sighting_plate_image || r.sighting_vehicle_image)!} alt={`Plate ${r.plate}`} className="w-full rounded-[var(--sd-radius)] object-cover" />
          ) : <div className="flex aspect-video items-center justify-center rounded-[var(--sd-radius)] bg-[var(--sd-line-soft)] text-[12px] text-[var(--sd-muted)]">No image</div>}
          <div className="text-[12px] text-[var(--sd-muted)] tabular-nums">{when(r.sighting_sighting_time || r.creation)} · read “{r.sighting_plate_read}” {r.sighting_confidence != null && `(${Math.round(r.sighting_confidence)}%)`}</div>
        </div>
        <div className="flex flex-col gap-3 text-[13px]">
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded bg-[var(--sd-ink)] px-2 py-0.5 font-mono tracking-wider text-white">{r.plate}</span>
            <span className="rounded-full bg-[var(--sd-alert-warn)] px-2 py-0.5 text-[12px]">{r.reason}</span>
            <span className="text-[12px] text-[var(--sd-muted)]">{r.farm}</span>
            {r.late && !done && <span className="text-[12px] text-[var(--sd-sev-high)]">late - supervisor told</span>}
          </div>
          {done ? <p className="text-[var(--sd-muted)]">Resolved.</p> : (
            <>
              {r.candidates.length > 0 && (
                <div className="flex flex-col gap-1.5">
                  <span className="text-[12px] text-[var(--sd-muted)]">Is it one of these?</span>
                  {r.candidates.map((c) => (
                    <div key={c.reference_name} className="flex items-center justify-between gap-2 rounded-[var(--sd-radius)] bg-[var(--sd-line-soft)]/60 px-3 py-1.5">
                      <span>{c.label} <span className="text-[12px] text-[var(--sd-quiet)]">{c.reference_doctype} · {Math.round(c.score)}%</span></span>
                      <Button size="sm" disabled={busy} onClick={() => resolve("Linked", c.reference_doctype, c.reference_name)}><CheckCircle2 /> This one</Button>
                    </div>
                  ))}
                </div>
              )}
              <div className="flex flex-col gap-1.5">
                <div className="relative">
                  <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-[var(--sd-quiet)]" />
                  <Input value={txt} onChange={(e) => setTxt(e.target.value)} placeholder="Find an appointment, delivery, staff or known vehicle" className="pl-8" />
                </div>
                {targets.map((t) => (
                  <div key={`${t.doctype}-${t.name}`} className="flex items-center justify-between gap-2 px-1">
                    <span>{t.label} {t.plate && <span className="font-mono text-[12px] text-[var(--sd-quiet)]">{t.plate}</span>}</span>
                    <Button size="sm" variant="outline" disabled={busy} onClick={() => resolve("Linked", t.doctype, t.name)}>Link</Button>
                  </div>
                ))}
              </div>
              <div className="flex flex-wrap items-center gap-2 border-t border-[var(--sd-line-soft)] pt-3">
                <Input value={plate} onChange={(e) => setPlate(e.target.value.toUpperCase())} className="w-32 font-mono" aria-label="Correct plate" />
                {plate !== r.plate && <Button size="sm" variant="outline" disabled={busy} onClick={() => resolve("Plate Corrected")}>Save plate</Button>}
                <Button size="sm" variant="outline" disabled={busy} onClick={() => setWalkIn((w) => !w)}><UserPlus /> Walk-in</Button>
                <Button size="sm" variant="ghost" disabled={busy} onClick={() => resolve("Ignored")}>Ignore</Button>
                <Button size="sm" variant="ghost" className="text-[var(--sd-data-red)]" disabled={busy} onClick={() => confirm(`Block ${r.plate}? It goes on the watchlist and every gate will flag it.`) && resolve("Blocked")}>
                  <ShieldOff /> Block
                </Button>
              </div>
              {walkIn && (
                <div className="flex flex-wrap items-center gap-2">
                  <Input value={wName} onChange={(e) => setWName(e.target.value)} placeholder="Driver / visitor name" className="w-56" />
                  <Input value={wPhone} onChange={(e) => setWPhone(e.target.value)} placeholder="Phone" className="w-40" />
                  <Button size="sm" disabled={busy || !wName} onClick={() => void createWalkIn()}>Register walk-in</Button>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </Card>
  );
}

// ===================================================================== Health

export function CctvHealth() {
  const toast = useToast();
  const { scope } = useScope();
  const [d, setD] = useState<api.HealthBoard | null>(null);
  const [loading, setLoading] = useState(true);
  const load = useCallback(async () => {
    setLoading(true);
    const r = await api.healthBoard({ company: scope.company || undefined, farm: scope.farm || undefined });
    setLoading(false);
    if (isError(r)) return void toast(r.error, "error");
    setD(r);
  }, [scope, toast]);
  useEffect(() => {
    void load();
    const t = setInterval(() => void load(), 30000);
    return () => clearInterval(t);
  }, [load]);
  const s = d?.summary;
  const servers = useMemo(() => Object.fromEntries((d?.servers ?? []).map((x) => [x.name, x.server_name])), [d]);

  return (
    <PageShell
      title="Camera health"
      eyebrow={EYEBROW}
      actions={<><ScopePicker /><RefreshButton onClick={() => void load()} loading={loading} label="Refresh" /></>}
      description="Site agents report every 30 seconds. A recorder clock more than 2 seconds off makes alert playback land at the wrong moment - fix NTP on it."
    >
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
        <KpiCard label="Site agents online" value={s ? `${s.agents_online} / ${s.agents}` : "—"} tone={s && s.agents_online < s.agents ? "critical" : "default"} loading={!s} />
        <KpiCard label="Cameras online" value={s ? `${s.cameras_online} / ${s.cameras}` : "—"} tone={s && s.cameras_online < s.cameras ? "warning" : "default"} loading={!s} />
        <KpiCard label="Recorder clocks off" value={s?.drifting ?? 0} tone={s?.drifting ? "warning" : "default"} loading={!s} />
        <KpiCard label="Events waiting (24 h)" value={s?.unprocessed_24h ?? 0} loading={!s} />
        <KpiCard label="Events failed (24 h)" value={s?.failed_24h ?? 0} tone={s?.failed_24h ? "critical" : "default"} loading={!s} />
      </div>
      <Card title="Site agents">
        <ScrollTable>
          <table className="w-full text-[13px]">
            <thead className={STICKY_HEAD}><tr><th className={TH}>Agent</th><th className={TH}>Site</th><th className={TH}>Status</th><th className={TH}>Last report</th><th className={TH}>Queue</th><th className={TH}>CPU</th><th className={TH}>Version</th></tr></thead>
            <tbody>
              {!d ? <TableRowsSkeleton cols={7} rows={2} /> : !d.agents.length ? <Empty cols={7} text="No site agents set up." /> : d.agents.map((a) => (
                <tr key={a.name} className="border-t border-[var(--sd-line-soft)]">
                  <td className={TD}>{a.name}</td><td className={TD}>{a.farm}</td><td className={TD}><StatusDot status={a.status} /></td>
                  <td className={`${TD} tabular-nums`}>{a.seconds_since != null ? `${a.seconds_since}s ago` : "never"}</td>
                  <td className={TD}>{a.queue_depth}</td><td className={TD}>{Math.round(a.cpu_percent)}%</td><td className={TD}>{a.version || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollTable>
      </Card>
      <Card title="Recorders">
        <ScrollTable>
          <table className="w-full text-[13px]">
            <thead className={STICKY_HEAD}><tr><th className={TH}>Recorder</th><th className={TH}>Site</th><th className={TH}>Brand / model</th><th className={TH}>Status</th><th className={TH}>Clock offset</th><th className={TH}>Recording</th></tr></thead>
            <tbody>
              {!d ? <TableRowsSkeleton cols={6} rows={2} /> : !d.servers.length ? <Empty cols={6} text="No recorders set up." /> : d.servers.map((x) => (
                <tr key={x.name} className="border-t border-[var(--sd-line-soft)]">
                  <td className={TD}>{x.server_name}</td><td className={TD}>{x.farm}</td><td className={TD}>{x.brand}{x.model ? ` · ${x.model}` : ""}<div className="text-[12px] text-[var(--sd-quiet)]">{x.firmware}</div></td>
                  <td className={TD}><StatusDot status={x.status} /></td>
                  <td className={cn(TD, "tabular-nums", Math.abs(x.time_offset_seconds ?? 0) > 2 && "text-[var(--sd-sev-high)] font-medium")}>{x.time_offset_seconds != null ? `${x.time_offset_seconds}s` : "—"}</td>
                  <td className={TD}>{x.recording_mode}{x.observed_retention_days ? ` · ${x.observed_retention_days} days` : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollTable>
      </Card>
      <Card title="Cameras">
        <ScrollTable tall>
          <table className="w-full text-[13px]">
            <thead className={STICKY_HEAD}><tr><th className={TH}>Camera</th><th className={TH}>Site / recorder</th><th className={TH}>Role</th><th className={TH}>Status</th><th className={TH}>Last frame</th><th className={TH}>Stream</th><th className={TH}>Analytics</th></tr></thead>
            <tbody>
              {!d ? <TableRowsSkeleton cols={7} rows={4} /> : !d.cameras.length ? <Empty cols={7} text="No cameras set up." /> : d.cameras.map((c) => (
                <tr key={c.name} className="border-t border-[var(--sd-line-soft)]">
                  <td className={TD}>{c.camera_name}<div className="text-[12px] text-[var(--sd-quiet)]">{c.zone}</div></td>
                  <td className={TD}>{c.farm}<div className="text-[12px] text-[var(--sd-quiet)]">{servers[c.server] ?? c.server}</div></td>
                  <td className={TD}>{c.role}</td><td className={TD}><StatusDot status={c.status} /></td>
                  <td className={`${TD} tabular-nums`}>{when(c.last_frame_time)}</td>
                  <td className={TD}>{[c.codec, c.resolution, c.fps ? `${c.fps} fps` : null].filter(Boolean).join(" · ") || "—"}</td>
                  <td className={TD}>{c.analytics_provider}{c.cap_anpr ? " · plates" : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollTable>
      </Card>
    </PageShell>
  );
}
