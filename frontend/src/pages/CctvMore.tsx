import { useCallback, useEffect, useRef, useState } from "react";
import maplibregl, { type GeoJSONSource, type LngLatBoundsLike } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { Feature } from "geojson";
import { Card, TD, TH } from "@/components/Card";
import { KpiCard } from "@/components/KpiCard";
import { TableRowsSkeleton } from "@/components/Loading";
import { PageShell } from "@/components/PageShell";
import { PillTabs } from "@/components/PillTabs";
import { RefreshButton } from "@/components/RefreshButton";
import { ScopePicker } from "@/components/ScopePicker";
import { ScrollTable, STICKY_HEAD } from "@/components/ScrollTable";
import { SearchInput } from "@/components/SearchInput";
import { useToast } from "@/components/Toast";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import * as api from "@/lib/cctv-api";
import { isError } from "@/lib/frappe";
import { useScope } from "@/lib/scope";
import { cn } from "@/lib/utils";
import { when } from "@/lib/when";

const EYEBROW = "CCTV";
const ago = (m: number) => (m < 1 ? "just now" : m < 60 ? `${m} min ago` : `${Math.floor(m / 60)} h ${m % 60} min ago`);

// ===================================================================== Presence

export function CctvPresence() {
  const toast = useToast();
  const { scope } = useScope();
  const [d, setD] = useState<Awaited<ReturnType<typeof api.presence>> | null>(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState<{ profile?: string; track?: string; label: string } | null>(null);

  const load = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    const r = await api.presence({ company: scope.company || undefined, farm: scope.farm || undefined });
    setLoading(false);
    if (isError(r)) return void (!quiet && toast(r.error, "error"));
    setD(r);
  }, [scope, toast]);
  useEffect(() => {
    void load();
    const t = setInterval(() => void load(true), 30000);
    return () => clearInterval(t);
  }, [load]);

  const data = d && !isError(d) ? d : null;
  const people = (data?.people ?? []).filter((p) => !search || `${p.full_name} ${p.zone ?? ""}`.toLowerCase().includes(search.toLowerCase()));
  return (
    <PageShell
      title="People on site"
      eyebrow={EYEBROW}
      actions={<><ScopePicker /><SearchInput value={search} onChange={setSearch} placeholder="Name or zone" aria-label="Search people" /><RefreshButton onClick={() => void load()} loading={loading} label="Refresh" /></>}
      description={`Where cameras last saw each person in the last ${data?.window_hours ?? 12} hours. "Last seen" is not proof someone is still there. Named people come from consented face enrolment; anonymous tracks are linked by camera layout and timing only.`}
    >
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <KpiCard label="Named people seen" value={data?.people.length ?? 0} loading={!data} />
        <KpiCard label="Anonymous tracks" value={data?.anonymous_tracks.length ?? 0} loading={!data} />
        {Object.entries(data?.by_zone ?? {}).slice(0, 2).map(([z, n]) => <KpiCard key={z} label={`In ${z}`} value={n} />)}
      </div>
      <Card title="Named people">
        <ScrollTable tall>
          <table className="w-full text-[13px]">
            <thead className={STICKY_HEAD}><tr><th className={TH}>Name</th><th className={TH}>Type</th><th className={TH}>Last seen</th><th className={TH}>Where</th><th className={TH}>Match</th></tr></thead>
            <tbody>
              {!data ? <TableRowsSkeleton cols={5} rows={4} /> : !people.length ? (
                <tr><td colSpan={5} className="px-4 py-10 text-center text-[var(--sd-muted)]">Nobody seen in the window.</td></tr>
              ) : people.map((p) => (
                <tr key={p.person_profile} onClick={() => setOpen({ profile: p.person_profile, label: p.full_name })} className="cursor-pointer border-t border-[var(--sd-line-soft)] hover:bg-[var(--sd-line-soft)]/40">
                  <td className={`${TD} font-medium`}>{p.full_name}</td>
                  <td className={TD}>{p.person_type}</td>
                  <td className={cn(TD, "tabular-nums", p.minutes_ago > 120 && "text-[var(--sd-muted)]")}>{ago(p.minutes_ago)}</td>
                  <td className={TD}>{[p.farm, p.zone].filter(Boolean).join(" · ")}</td>
                  <td className={TD}>{Math.round(p.confidence)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollTable>
      </Card>
      <Card title="Anonymous tracks">
        <ScrollTable>
          <table className="w-full text-[13px]">
            <thead className={STICKY_HEAD}><tr><th className={TH}>Track</th><th className={TH}>Last seen</th><th className={TH}>Where</th><th className={TH}>Cameras</th><th className={TH}>Link confidence</th></tr></thead>
            <tbody>
              {!data ? <TableRowsSkeleton cols={5} rows={2} /> : !data.anonymous_tracks.length ? (
                <tr><td colSpan={5} className="px-4 py-8 text-center text-[var(--sd-muted)]">No active tracks.</td></tr>
              ) : data.anonymous_tracks.map((t) => (
                <tr key={t.name} onClick={() => setOpen({ track: t.name, label: t.label })} className="cursor-pointer border-t border-[var(--sd-line-soft)] hover:bg-[var(--sd-line-soft)]/40">
                  <td className={TD}>{t.label}</td><td className={`${TD} tabular-nums`}>{when(t.last_seen)}</td>
                  <td className={TD}>{[t.farm, t.last_zone].filter(Boolean).join(" · ")}</td><td className={TD}>{t.sighting_count}</td>
                  <td className={TD}>{Math.round(t.confidence)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollTable>
      </Card>
      <TimelineDialog target={open} onClose={() => setOpen(null)} />
    </PageShell>
  );
}

function TimelineDialog({ target, onClose }: { target: { profile?: string; track?: string; label: string } | null; onClose: () => void }) {
  const toast = useToast();
  const [rows, setRows] = useState<api.TimelineRow[] | null>(null);
  useEffect(() => {
    setRows(null);
    if (!target) return;
    void api.timeline({ profile: target.profile, track: target.track }).then((r) => (isError(r) ? toast(r.error, "error") : setRows(r)));
  }, [target, toast]);
  return (
    <Dialog open={!!target} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[90vh] max-w-xl overflow-y-auto">
        <DialogHeader><DialogTitle>{target?.label}</DialogTitle><DialogDescription>Today's sightings, in order.</DialogDescription></DialogHeader>
        {!rows ? <p className="text-[13px] text-[var(--sd-muted)]">Loading…</p> : !rows.length ? <p className="text-[13px] text-[var(--sd-muted)]">No sightings today.</p> : (
          <ol className="relative ml-2 border-l border-[var(--sd-line-soft)] text-[13px]">
            {rows.map((r) => (
              <li key={r.name} className="mb-3 ml-4">
                <span className="absolute -left-1.5 mt-1.5 h-3 w-3 rounded-full bg-[var(--sd-ink)]" aria-hidden />
                <div className="font-medium">{r.camera_name}{r.direction && r.direction !== "unknown" ? ` · ${r.direction}` : ""}</div>
                <div className="text-[12px] text-[var(--sd-muted)] tabular-nums">{when(r.sighting_time)} · {r.zone ?? "no zone"} · {Math.round(r.confidence)}%</div>
              </li>
            ))}
          </ol>
        )}
      </DialogContent>
    </Dialog>
  );
}

// ===================================================================== Site map

const STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: { osm: { type: "raster", tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"], tileSize: 256, attribution: "© OpenStreetMap contributors" } },
  layers: [{ id: "osm", type: "raster", source: "osm" }],
};
const empty = { type: "FeatureCollection" as const, features: [] as Feature[] };

export function CctvMap() {
  const toast = useToast();
  const { scope } = useScope();
  const box = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const [d, setD] = useState<api.MapData | null>(null);
  const [layer, setLayer] = useState("all");
  const [loading, setLoading] = useState(true);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!box.current) return;
    const m = new maplibregl.Map({ container: box.current, style: STYLE, center: [36.82, -1.29], zoom: 12 });
    m.addControl(new maplibregl.NavigationControl(), "top-right");
    m.on("load", () => {
      m.addSource("zones", { type: "geojson", data: empty });
      m.addLayer({ id: "zones-fill", type: "fill", source: "zones", paint: { "fill-color": ["match", ["get", "severity"], "Critical", "#c0392b", "High", "#e67e22", "#2c7be5"], "fill-opacity": 0.15 } });
      m.addLayer({ id: "zones-line", type: "line", source: "zones", paint: { "line-color": "#0B2236", "line-width": 1.5 } });
      m.addLayer({ id: "zones-label", type: "symbol", source: "zones", layout: { "text-field": ["get", "label"], "text-size": 11 } });
      m.addSource("boundary", { type: "geojson", data: empty });
      m.addLayer({ id: "boundary", type: "line", source: "boundary", paint: { "line-color": "#5CA458", "line-width": 2.5, "line-dasharray": [2, 1] } });
      for (const [id, color, radius] of [["cameras", "#0B2236", 6], ["vehicles", "#e67e22", 7], ["tracks", "#8e44ad", 6]] as const) {
        m.addSource(id, { type: "geojson", data: empty });
        m.addLayer({ id, type: "circle", source: id, paint: { "circle-radius": radius, "circle-color": id === "cameras" ? ["match", ["get", "status"], "Online", "#2e8b57", "Offline", "#c0392b", color] : color, "circle-stroke-color": "#fff", "circle-stroke-width": 1.5 } });
        m.addLayer({ id: `${id}-label`, type: "symbol", source: id, layout: { "text-field": ["get", "label"], "text-size": 11, "text-offset": [0, 1.2], "text-anchor": "top" }, paint: { "text-halo-color": "#fff", "text-halo-width": 1.2 } });
        m.on("click", id, (e) => {
          const f = e.features?.[0];
          if (f) new maplibregl.Popup().setLngLat(e.lngLat).setHTML(String(f.properties?.popup ?? "")).addTo(m);
        });
      }
      map.current = m;
      setReady(true);
    });
    return () => m.remove();
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    const r = await api.mapData({ company: scope.company || undefined, farm: scope.farm || undefined });
    setLoading(false);
    if (isError(r)) return void toast(r.error, "error");
    setD(r);
  }, [scope, toast]);
  useEffect(() => {
    void load();
    const t = setInterval(() => void load(), 30000);
    return () => clearInterval(t);
  }, [load]);

  useEffect(() => {
    const m = map.current;
    if (!m || !d) return;
    const esc = (s: unknown) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);
    const pt = (lng: number, lat: number, props: Record<string, unknown>): Feature => ({ type: "Feature", geometry: { type: "Point", coordinates: [lng, lat] }, properties: props });
    const show = (k: string) => layer === "all" || layer === k;
    (m.getSource("zones") as GeoJSONSource)?.setData({ type: "FeatureCollection", features: d.zones.map((z) => ({ type: "Feature", geometry: { type: "Polygon", coordinates: [z.ring] }, properties: { label: z.label, severity: z.severity } })) });
    (m.getSource("boundary") as GeoJSONSource)?.setData(d.boundary ? { type: "Feature", geometry: { type: "LineString", coordinates: d.boundary }, properties: {} } : empty);
    (m.getSource("cameras") as GeoJSONSource)?.setData({ type: "FeatureCollection", features: show("cameras") ? d.cameras.filter((c) => c.latitude && c.longitude).map((c) =>
      pt(c.longitude!, c.latitude!, { label: c.camera_name, status: c.status, popup: `<b>${esc(c.camera_name)}</b><br>${esc(c.role)} · ${esc(c.status)}<br><a href="#/cctv-live">Live view</a>` })) : [] });
    (m.getSource("vehicles") as GeoJSONSource)?.setData({ type: "FeatureCollection", features: show("vehicles") ? d.vehicles.map((v, i) =>
      pt(v.longitude + (i % 5) * 0.00004, v.latitude + Math.floor(i / 5) * 0.00004, { label: v.plate, popup: `<b>${esc(v.plate)}</b> · ${esc(v.party_name)}<br>last seen ${esc(when(v.last_seen_time))}` })) : [] });
    (m.getSource("tracks") as GeoJSONSource)?.setData({ type: "FeatureCollection", features: show("people") ? d.tracks.map((t) =>
      pt(t.longitude, t.latitude, { label: t.label, popup: `<b>${esc(t.label)}</b><br>last seen ${esc(when(t.last_seen))} · ${Math.round(t.confidence)}%` })) : [] });
    const coords: [number, number][] = [
      ...d.cameras.filter((c) => c.latitude && c.longitude).map((c) => [c.longitude!, c.latitude!] as [number, number]),
      ...(d.boundary ?? []), ...d.zones.flatMap((z) => z.ring),
    ];
    if (coords.length) {
      const lngs = coords.map((c) => c[0]), lats = coords.map((c) => c[1]);
      m.fitBounds([[Math.min(...lngs), Math.min(...lats)], [Math.max(...lngs), Math.max(...lats)]] as LngLatBoundsLike, { padding: 60, maxZoom: 18, duration: 0 });
    }
  }, [d, layer, ready]);

  return (
    <PageShell
      title="Site map"
      eyebrow={EYEBROW}
      tabs={<PillTabs label="Show" value={layer} onChange={setLayer} tabs={[{ key: "all", label: "Everything" }, { key: "cameras", label: "Cameras", count: d?.cameras.length }, { key: "vehicles", label: "Vehicles", count: d?.vehicles.length }, { key: "people", label: "People", count: d?.tracks.length }]} />}
      actions={<><ScopePicker /><RefreshButton onClick={() => void load()} loading={loading} label="Refresh" /></>}
      description="Vehicles and people are drawn at the camera that last saw them - a last-seen point, not live GPS. Set each camera's latitude and longitude on the CCTV Camera to place it."
    >
      {!!d?.unplaced && <p className="text-[12px] text-[var(--sd-sev-high)]">{d.unplaced} camera(s) have no position yet and are not on the map.</p>}
      <div ref={box} className="h-[70vh] min-h-[420px] w-full overflow-hidden rounded-[var(--sd-radius-lg)] shadow-[var(--sd-shadow-1)]" />
    </PageShell>
  );
}
