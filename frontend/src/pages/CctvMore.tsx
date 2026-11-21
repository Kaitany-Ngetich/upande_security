import { useCallback, useEffect, useRef, useState } from "react";
import maplibregl, { type GeoJSONSource, type LngLatBoundsLike } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { Feature, FeatureCollection } from "geojson";
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
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
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

/** A camera's view as a wedge: apex at the camera, `fov` wide, `range` metres deep, facing `bearing` (0 = north). */
function cone(lng: number, lat: number, bearing: number, fov: number, range: number): [number, number][] {
  const pts: [number, number][] = [[lng, lat]];
  const steps = Math.max(6, Math.round(fov / 6));
  for (let i = 0; i <= steps; i++) {
    const a = ((bearing - fov / 2 + (fov * i) / steps) * Math.PI) / 180;
    pts.push([lng + (range * Math.sin(a)) / (111320 * Math.cos((lat * Math.PI) / 180)), lat + (range * Math.cos(a)) / 111320]);
  }
  pts.push([lng, lat]);
  return pts;
}

interface Pending { camera: string; lng: number | null; lat: number | null; bearing: number; fov: number; range: number; note: string }

export function CctvMap() {
  const toast = useToast();
  const { scope } = useScope();
  const box = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const [d, setD] = useState<api.MapData | null>(null);
  const [layer, setLayer] = useState("all");
  const [loading, setLoading] = useState(true);
  const [ready, setReady] = useState(false);
  const [placing, setPlacing] = useState(false);
  const [pending, setPending] = useState<Pending | null>(null);
  const [links, setLinks] = useState<{ pairs: api.LinkSuggestion[]; created: number; unplaced: number } | null>(null);
  const pendingRef = useRef<Pending | null>(null);
  pendingRef.current = pending;
  const fitted = useRef(false);

  useEffect(() => {
    if (!box.current) return;
    const m = new maplibregl.Map({ container: box.current, style: STYLE, center: [36.82, -1.29], zoom: 12 });
    m.addControl(new maplibregl.NavigationControl(), "top-right");
    m.on("load", () => {
      m.addSource("zones", { type: "geojson", data: empty });
      m.addLayer({ id: "zones-fill", type: "fill", source: "zones", paint: { "fill-color": ["match", ["get", "severity"], "Critical", "#c0392b", "High", "#e67e22", "#2c7be5"], "fill-opacity": 0.12 } });
      m.addLayer({ id: "zones-line", type: "line", source: "zones", paint: { "line-color": "#0B2236", "line-width": 1.5 } });
      m.addLayer({ id: "zones-label", type: "symbol", source: "zones", layout: { "text-field": ["get", "label"], "text-size": 11 } });
      m.addSource("boundary", { type: "geojson", data: empty });
      m.addLayer({ id: "boundary", type: "line", source: "boundary", paint: { "line-color": "#5CA458", "line-width": 2.5, "line-dasharray": [2, 1] } });
      m.addSource("cones", { type: "geojson", data: empty });
      m.addLayer({ id: "cones", type: "fill", source: "cones", paint: { "fill-color": ["match", ["get", "kind"], "pending", "#e67e22", "#2c7be5"], "fill-opacity": ["match", ["get", "kind"], "pending", 0.3, 0.16] } });
      m.addLayer({ id: "cones-edge", type: "line", source: "cones", paint: { "line-color": ["match", ["get", "kind"], "pending", "#e67e22", "#2c7be5"], "line-width": 1 } });
      m.addSource("links", { type: "geojson", data: empty });
      m.addLayer({ id: "links", type: "line", source: "links", paint: { "line-color": "#8e44ad", "line-width": 1.5, "line-dasharray": [1, 2] } });
      for (const [id, color, radius] of [["cameras", "#0B2236", 6], ["vehicles", "#e67e22", 7], ["tracks", "#8e44ad", 6], ["pending", "#e67e22", 8]] as const) {
        m.addSource(id, { type: "geojson", data: empty });
        m.addLayer({ id, type: "circle", source: id, paint: { "circle-radius": radius, "circle-color": id === "cameras" ? ["match", ["get", "status"], "Online", "#2e8b57", "Offline", "#c0392b", color] : color, "circle-stroke-color": "#fff", "circle-stroke-width": 1.5 } });
        m.addLayer({ id: `${id}-label`, type: "symbol", source: id, layout: { "text-field": ["get", "label"], "text-size": 11, "text-offset": [0, 1.2], "text-anchor": "top" }, paint: { "text-halo-color": "#fff", "text-halo-width": 1.2 } });
        if (id !== "pending") m.on("click", id, (e) => {
          if (pendingRef.current) return;
          const f = e.features?.[0];
          if (f) new maplibregl.Popup().setLngLat(e.lngLat).setHTML(String(f.properties?.popup ?? "")).addTo(m);
        });
      }
      m.on("click", (e) => {
        const p = pendingRef.current;
        if (p) setPending({ ...p, lng: e.lngLat.lng, lat: e.lngLat.lat });
      });
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
    fitted.current = false;
    void load();
    const t = setInterval(() => { if (!pendingRef.current) void load(); }, 30000);
    return () => clearInterval(t);
  }, [load]);

  useEffect(() => {
    const m = map.current;
    if (!m || !d) return;
    const esc = (s: unknown) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);
    const pt = (lng: number, lat: number, props: Record<string, unknown>): Feature => ({ type: "Feature", geometry: { type: "Point", coordinates: [lng, lat] }, properties: props });
    const poly = (ring: [number, number][], props: Record<string, unknown>): Feature => ({ type: "Feature", geometry: { type: "Polygon", coordinates: [ring] }, properties: props });
    const show = (k: string) => layer === "all" || layer === k;
    const placed = d.cameras.filter((c) => c.latitude && c.longitude && c.name !== pending?.camera);
    const byName = Object.fromEntries(placed.map((c) => [c.name, c]));
    const set = (id: string, data: FeatureCollection | Feature | typeof empty) => (m.getSource(id) as GeoJSONSource | undefined)?.setData(data as never);
    set("zones", { type: "FeatureCollection", features: d.zones.map((z) => poly(z.ring, { label: z.label, severity: z.severity })) });
    set("boundary", d.boundary ? { type: "Feature", geometry: { type: "LineString", coordinates: d.boundary }, properties: {} } : empty);
    const cones: Feature[] = show("cameras") ? placed.filter((c) => (c.view_range_m ?? 0) > 0 && (c.field_of_view_deg ?? 0) > 0)
      .map((c) => poly(cone(c.longitude!, c.latitude!, c.bearing_deg ?? 0, c.field_of_view_deg!, c.view_range_m!), { kind: "camera" })) : [];
    if (pending?.lng != null && pending.lat != null) cones.push(poly(cone(pending.lng, pending.lat, pending.bearing, pending.fov, pending.range), { kind: "pending" }));
    set("cones", { type: "FeatureCollection", features: cones });
    set("links", { type: "FeatureCollection", features: show("cameras") ? d.links.filter((l) => byName[l.from_camera] && byName[l.to_camera]).map((l) => ({
      type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: [[byName[l.from_camera].longitude!, byName[l.from_camera].latitude!], [byName[l.to_camera].longitude!, byName[l.to_camera].latitude!]] } }) as Feature) : [] });
    set("cameras", { type: "FeatureCollection", features: show("cameras") ? placed.map((c) =>
      pt(c.longitude!, c.latitude!, { label: c.name, status: c.status, popup: `<b>${esc(c.name)}</b> · ${esc(c.camera_name)}<br>${esc(c.role)} · ${esc(c.status)}${c.position_note ? `<br>${esc(c.position_note)}` : ""}<br><a href="#/cctv-live">Live view</a>` })) : [] });
    set("pending", { type: "FeatureCollection", features: pending?.lng != null && pending.lat != null ? [pt(pending.lng, pending.lat, { label: pending.camera })] : [] });
    set("vehicles", { type: "FeatureCollection", features: show("vehicles") ? d.vehicles.map((v, i) =>
      pt(v.longitude + (i % 5) * 0.00004, v.latitude + Math.floor(i / 5) * 0.00004, { label: v.plate, popup: `<b>${esc(v.plate)}</b> · ${esc(v.party_name)}<br>last seen ${esc(when(v.last_seen_time))}` })) : [] });
    set("tracks", { type: "FeatureCollection", features: show("people") ? d.tracks.map((t) =>
      pt(t.longitude, t.latitude, { label: t.label, popup: `<b>${esc(t.label)}</b><br>last seen ${esc(when(t.last_seen))} · ${Math.round(t.confidence)}%` })) : [] });
    if (!fitted.current) {
      const coords: [number, number][] = [...placed.map((c) => [c.longitude!, c.latitude!] as [number, number]), ...(d.boundary ?? []), ...d.zones.flatMap((z) => z.ring)];
      if (coords.length) {
        const lngs = coords.map((c) => c[0]), lats = coords.map((c) => c[1]);
        m.fitBounds([[Math.min(...lngs), Math.min(...lats)], [Math.max(...lngs), Math.max(...lats)]] as LngLatBoundsLike, { padding: 60, maxZoom: 18, duration: 0 });
        fitted.current = true;
      }
    }
  }, [d, layer, ready, pending]);

  const pick = (c: api.MapData["cameras"][number]) => setPending({ camera: c.name, lng: c.longitude || null, lat: c.latitude || null,
    bearing: c.bearing_deg ?? 0, fov: c.field_of_view_deg || 90, range: c.view_range_m || 30, note: c.position_note ?? "" });
  const save = async () => {
    if (!pending || pending.lng == null || pending.lat == null) return;
    const r = await api.setCameraPosition({ camera: pending.camera, latitude: pending.lat, longitude: pending.lng, bearing: pending.bearing,
      field_of_view: pending.fov, range_m: pending.range, note: pending.note });
    if (isError(r)) return void toast(r.error, "error");
    toast(`${pending.camera} placed.`, "ok");
    setPending(null);
    void load();
  };
  const suggest = async (create = 0) => {
    if (!scope.farm) return void toast("Pick one site first (top right).", "warn");
    const r = await api.suggestLinks(scope.farm, create);
    if (isError(r)) return void toast(r.error, "error");
    setLinks(r);
    if (create) { toast(`${r.created} camera link(s) added.`, "ok"); void load(); }
  };

  return (
    <PageShell
      title="Site map"
      eyebrow={EYEBROW}
      tabs={<PillTabs label="Show" value={layer} onChange={setLayer} tabs={[{ key: "all", label: "Everything" }, { key: "cameras", label: "Cameras", count: d?.cameras.length }, { key: "vehicles", label: "Vehicles", count: d?.vehicles.length }, { key: "people", label: "People", count: d?.tracks.length }]} />}
      actions={<>
        <ScopePicker />
        {d?.can_place && <Button variant={placing ? "default" : "outline"} size="sm" onClick={() => { setPlacing(!placing); setPending(null); }}>{placing ? "Done placing" : "Place cameras"}</Button>}
        {d?.can_place && <Button variant="outline" size="sm" onClick={() => void suggest(0)}>Suggest camera links</Button>}
        <RefreshButton onClick={() => void load()} loading={loading} label="Refresh" />
      </>}
      description="Cones show what each camera sees. Vehicles and people are drawn at the camera that last saw them - a last-seen point, not live GPS. Dotted purple lines are camera links used to follow people between views."
    >
      {!!d?.unplaced && !placing && <p className="text-[12px] text-[var(--sd-sev-high)]">{d.unplaced} camera(s) have no position yet - use Place cameras.</p>}
      <div className="relative">
        <div ref={box} className={cn("h-[70vh] min-h-[420px] w-full overflow-hidden rounded-[var(--sd-radius-lg)] shadow-[var(--sd-shadow-1)]", pending && "cursor-crosshair")} />
        {placing && d && (
          <div className="absolute left-3 top-3 z-10 flex max-h-[calc(70vh-24px)] w-72 flex-col gap-2 overflow-y-auto rounded-[var(--sd-radius-lg)] bg-[var(--sd-card)] p-3 text-[13px] shadow-[var(--sd-shadow-1)]">
            {!pending ? (<>
              <div className="font-semibold">Pick a camera, then click its spot</div>
              {d.cameras.map((c) => (
                <button key={c.name} type="button" onClick={() => pick(c)} className="flex items-center justify-between rounded px-2 py-1.5 text-left hover:bg-[var(--sd-line-soft)]">
                  <span><span className="font-mono text-[12px]">{c.name}</span><br /><span className="text-[12px] text-[var(--sd-muted)]">{c.camera_name}</span></span>
                  <span className={cn("text-[11px]", c.latitude ? "text-[var(--sd-muted)]" : "text-[var(--sd-sev-high)]")}>{c.latitude ? "placed" : "not placed"}</span>
                </button>
              ))}
            </>) : (<>
              <div className="font-semibold font-mono">{pending.camera}</div>
              <p className="text-[12px] text-[var(--sd-muted)]">{pending.lat == null ? "Click the map where the camera is mounted." : "Click again to move it. Set where it faces:"}</p>
              <label className="flex flex-col gap-1">Facing: {pending.bearing}° {["N", "NE", "E", "SE", "S", "SW", "W", "NW"].at(Math.round(pending.bearing / 45) % 8)}
                <input type="range" min={0} max={359} value={pending.bearing} onChange={(e) => setPending({ ...pending, bearing: Number(e.target.value) })} /></label>
              <label className="flex flex-col gap-1">Field of view: {pending.fov}°
                <input type="range" min={10} max={360} value={pending.fov} onChange={(e) => setPending({ ...pending, fov: Number(e.target.value) })} /></label>
              <label className="flex flex-col gap-1">Useful range: {pending.range} m
                <input type="range" min={5} max={150} value={pending.range} onChange={(e) => setPending({ ...pending, range: Number(e.target.value) })} /></label>
              <Input value={pending.note} onChange={(e) => setPending({ ...pending, note: e.target.value })} placeholder="Where exactly (e.g. gatehouse pole)" />
              <div className="flex gap-2">
                <Button size="sm" disabled={pending.lat == null} onClick={() => void save()}>Save position</Button>
                <Button size="sm" variant="ghost" onClick={() => setPending(null)}>Cancel</Button>
              </div>
            </>)}
          </div>
        )}
      </div>
      <Dialog open={!!links} onOpenChange={(o) => !o && setLinks(null)}>
        <DialogContent className="max-h-[90vh] max-w-2xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Suggested camera links</DialogTitle>
            <DialogDescription>Cameras within 200 m of each other, with walking times between them. Used to follow an unidentified person from one view to the next.</DialogDescription>
          </DialogHeader>
          {links && (<>
            {!!links.unplaced && <p className="text-[12px] text-[var(--sd-sev-high)]">{links.unplaced} camera(s) are not placed and were left out.</p>}
            <table className="w-full text-[13px]">
              <thead><tr><th className={TH}>From</th><th className={TH}>To</th><th className={TH}>Distance</th><th className={TH}>Walk</th><th className={TH} /></tr></thead>
              <tbody>{links.pairs.length ? links.pairs.map((p) => (
                <tr key={`${p.from_camera}-${p.to_camera}`} className="border-t border-[var(--sd-line-soft)]">
                  <td className={TD}><span className="font-mono">{p.from_camera}</span></td><td className={TD}><span className="font-mono">{p.to_camera}</span></td>
                  <td className={TD}>{p.distance_m} m</td><td className={TD}>{p.min_seconds}-{p.max_seconds} s</td>
                  <td className={TD}>{p.exists ? <span className="text-[var(--sd-muted)]">linked</span> : "new"}</td>
                </tr>)) : <tr><td colSpan={5} className="px-4 py-6 text-center text-[var(--sd-muted)]">No placed cameras near each other.</td></tr>}</tbody>
            </table>
            {links.pairs.some((p) => !p.exists) && <Button onClick={() => void suggest(1)}>Create {links.pairs.filter((p) => !p.exists).length} link(s)</Button>}
          </>)}
        </DialogContent>
      </Dialog>
    </PageShell>
  );
}
