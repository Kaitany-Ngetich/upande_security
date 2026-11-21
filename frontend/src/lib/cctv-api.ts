import { call } from "@/lib/frappe";

const D = "upande_security.cctv.dashboard";
const T = "upande_security.cctv.tokens";
const A = "upande_security.cctv.alerts";
const V = "upande_security.cctv.vehicles";

/** bootstrap().cctv — which CCTV pages this user gets (all false while the module is off). */
export interface CctvCaps {
  enabled: boolean;
  live?: boolean;
  alerts?: boolean;
  vehicles?: boolean;
  review?: boolean;
  health?: boolean;
  manage?: boolean;
}

// --- cameras / video -------------------------------------------------------------------

export interface Camera {
  name: string; camera_name: string; farm: string; zone: string | null; gate: string | null; role: string;
  status: "Unknown" | "Online" | "Offline"; last_frame_time: string | null; cap_ptz: number; cap_anpr: number;
}
export interface StreamTicket {
  token: string; path: string; whep_url: string; hls_url: string; expires_in: number;
  start?: string; end?: string; event_offset_seconds?: number | null;
}
/** list_cameras answers with a bare list. */
export const listCameras = (args: { farm?: string; zone?: string }) => call<Camera[]>(`${T}.list_cameras`, args);
export const liveTicket = (camera: string, profile: "sub" | "main" = "sub") => call<StreamTicket>(`${T}.get_live_token`, { camera, profile });
export const alertPlayback = (alert: string, camera?: string) => call<StreamTicket>(`${T}.get_playback_session`, { alert, camera });
export const rangePlayback = (camera: string, start: string, end: string, source: "Manual" | "Vehicle Visit" = "Manual") =>
  call<StreamTicket>(`${T}.get_playback_session`, { camera, start, end, source });

// --- alerts ----------------------------------------------------------------------------

export type AlertStatus = "Open" | "Acknowledged" | "Escalated" | "Resolved" | "False Alarm";
export interface AlertRow {
  name: string; alert_type: string; severity: string; status: AlertStatus; summary: string | null; farm: string | null;
  zone: string | null; camera: string | null; camera_name: string | null; event_time: string; plate: string | null;
  person_name: string | null; snapshot: string | null; acknowledged_by: string | null; escalation_level: number;
  repeat_count: number; vehicle_visit: string | null; incident: string | null;
}
export interface AlertBoard { counts: Record<AlertStatus, number>; total: number; start: number; rows: AlertRow[] }
export interface AlertDetail extends AlertRow {
  clip_start: string; clip_end: string; resolution_notes: string | null; false_alarm_reason: string | null;
  first_viewed_by: string | null; acknowledged_at: string | null; confidence: number | null; appointment: string | null;
  related: { camera: string; camera_name: string | null; reason: string | null }[];
  notifications: { channel: string; recipient: string; sent_at: string; delivery_status: string; error: string | null }[];
  can_act: boolean; false_alarm_reasons: string[];
  visit?: { name: string; plate: string; party_name: string; party_type: string; entry_time: string | null; exit_time: string | null; status: string };
}
export const alertBoard = (args: { status?: string; severity?: string; company?: string; farm?: string; from_date?: string; to_date?: string; search?: string; start?: number }) =>
  call<AlertBoard>(`${D}.alert_board`, args);
export const alertDetail = (name: string) => call<AlertDetail>(`${D}.alert_detail`, { name });
export const acknowledgeAlert = (name: string, note?: string) => call<{ ok: true; status: string }>(`${A}.acknowledge`, { name, note });
export const resolveAlert = (name: string, notes?: string) => call<{ ok: true; status: string }>(`${A}.resolve`, { name, notes });
export const falseAlarm = (name: string, reason: string, notes?: string) => call<{ ok: true; status: string }>(`${A}.mark_false_alarm`, { name, reason, notes });
export const escalateAlert = (name: string) => call<{ ok: true }>(`${A}.escalate`, { name });
export const alertIncident = (name: string) => call<{ ok: true; incident: string }>(`${A}.create_incident`, { name });
export const markViewed = (name: string) => call<{ ok: true }>(`${A}.mark_viewed`, { name });

// --- vehicles ----------------------------------------------------------------------------

export interface VisitRow {
  name: string; plate: string; party_type: string; party_name: string; source: string; reference_doctype: string | null;
  reference_name: string | null; appointment: string | null; farm: string; status: string; entry_time: string | null;
  exit_time: string | null; expected_exit: string | null; total_minutes: number | null; last_seen_time: string | null;
  last_seen_camera: string | null; last_seen_camera_name: string | null; last_seen_zone: string | null; entry_camera: string | null;
  entry_snapshot: string | null; guard_confirmed: number; flags_text: string | null; colour: string | null; vehicle_class: string | null;
  minutes_inside: number | null; seen_minutes_ago: number | null; overdue: boolean;
}
export interface VisitBoard {
  kpis: { on_site: number; overstayed: number; arrivals_today: number; departures_today: number; unconfirmed: number; review_open: number };
  total: number; start: number; rows: VisitRow[];
}
export interface Sighting {
  name: string; sighting_time: string; camera: string; camera_name: string | null; zone: string | null; gate: string | null;
  direction: string | null; plate_read: string; confidence: number; plate_image: string | null; vehicle_image: string | null;
}
export const visitBoard = (args: { status?: string; company?: string; farm?: string; from_date?: string; to_date?: string; search?: string; start?: number }) =>
  call<VisitBoard>(`${D}.visit_board`, args);
export const visitDetail = (name: string) => call<VisitRow & { sightings: Sighting[]; notes: string | null; host: string | null }>(`${D}.visit_detail`, { name });
export const confirmVisit = (name: string, args: { reference_doctype?: string; reference_name?: string; corrected_plate?: string; notes?: string } = {}) =>
  call<{ visit: string; appointment: string | null }>(`${V}.confirm_visit`, { name, ...args });
export const closeVisit = (name: string, notes?: string) => call<{ ok: true; status: string }>(`${V}.close_visit`, { name, notes });

// --- review queue ------------------------------------------------------------------------

export interface ReviewRow {
  name: string; reason: string; status: "Open" | "Escalated" | "Resolved"; plate: string; farm: string; sighting: string | null;
  vehicle_visit: string | null; sla_due: string | null; creation: string; late: boolean;
  candidates: { reference_doctype: string; reference_name: string; label: string; score: number }[];
  sighting_plate_read?: string; sighting_confidence?: number; sighting_plate_image?: string | null; sighting_vehicle_image?: string | null;
  sighting_camera?: string; sighting_sighting_time?: string; sighting_direction?: string; sighting_colour?: string | null;
}
export interface LinkTarget { doctype: string; name: string; label: string; plate: string | null; when?: string }
export const reviewBoard = (args: { company?: string; farm?: string; status?: string }) =>
  call<{ counts: Record<string, number>; rows: ReviewRow[] }>(`${D}.review_board`, args);
export const linkTargets = (farm: string | undefined, txt: string) => call<LinkTarget[]>(`${D}.search_link_targets`, { farm, txt });
export const resolveReview = (name: string, resolution: string, args: { linked_doctype?: string; linked_name?: string; corrected_plate?: string; notes?: string } = {}) =>
  call<{ ok: true; name: string }>(`${V}.resolve_review_item`, { name, resolution, ...args });
export const walkInFromReview = (name: string, customer_name: string, phone?: string, purpose?: string) =>
  call<{ name?: string; error?: string }>(`${V}.create_walkin_from_review`, { name, customer_name, phone, purpose });

// --- health ------------------------------------------------------------------------------

export interface HealthBoard {
  agents: { name: string; farm: string; status: string; last_heartbeat: string | null; seconds_since: number | null; version: string | null;
    queue_depth: number; cpu_percent: number; gpu_percent: number; gateway_url: string | null }[];
  servers: { name: string; server_name: string; farm: string; brand: string; model: string | null; firmware: string | null; status: string;
    last_seen: string | null; time_offset_seconds: number | null; recording_mode: string; observed_retention_days: number | null }[];
  cameras: { name: string; camera_name: string; farm: string; server: string; zone: string | null; role: string; status: string;
    last_frame_time: string | null; codec: string | null; resolution: string | null; fps: number | null; cap_anpr: number; analytics_provider: string }[];
  summary: { agents_online: number; agents: number; cameras_online: number; cameras: number; drifting: number; unprocessed_24h: number; failed_24h: number };
}
export const healthBoard = (args: { company?: string; farm?: string }) => call<HealthBoard>(`${D}.health_board`, args);
