import { call } from "@/lib/frappe";

const M = "upande_security.api.dashboard_v2";
const SA = "upande_security.api.security_api";

// --- vehicle stickers ----------------------------------------------------------------

export type StickerStatus = "Unassigned" | "Active" | "Suspended" | "Lost";
export interface Sticker {
  name: string; sticker_number: number; company: string; employee: string | null; employee_name: string | null;
  vehicle_type: string; plate_number: string; color: string | null; status: StickerStatus; qr_image: string | null; creation: string;
}
export interface StickerRequest {
  name: string; employee: string; employee_name: string; vehicle_type: string; plate_number: string; color: string;
  collection_farm: string; collection_point: string; status: "Pending" | "Approved" | "Rejected"; review_notes: string;
  linked_sticker: string; creation: string;
}
export const stickerBoard = (args: { company?: string; status?: string; search?: string; start?: number }) =>
  call<{ counts: Record<StickerStatus, number>; total: number; start: number; rows: Sticker[]; can_manage: boolean }>(`${M}.sticker_board`, args);
export const setStickerStatus = (name: string, status: StickerStatus) => call<{ ok: true; status: StickerStatus }>(`${M}.set_sticker_status`, { name, status });
/** list_sticker_requests answers with a bare list; call() hands arrays back as they are. */
export const stickerRequests = (status: string) => call<StickerRequest[]>(`${SA}.list_sticker_requests`, { status, limit: 500 });
export const approveRequest = (request_name: string) => call<{ sticker?: string; sticker_number?: number }>(`${SA}.approve_staff_sticker_request`, { request_name });
export const rejectRequest = (request_name: string, review_notes: string) => call<{ ok?: boolean }>(`${SA}.reject_staff_sticker_request`, { request_name, review_notes });

// --- checkpoints ---------------------------------------------------------------------

export interface Checkpoint {
  name: string; checkpoint_name: string; location_hint: string | null; company: string | null; farm: string | null; active: number;
  radius_m: number | null; position_accuracy_m: number | null; position_set_at: string | null; qr_image: string | null;
  has_position: boolean; valid: number; refused: number; last_valid: string | null;
}
export interface Scan {
  name: string; checkpoint: string; checkpoint_name: string; result: string; scanned_at: string; guard_name: string | null;
  farm: string | null; patrol: string | null; distance_m: number | null; allowed_m: number | null; gps_accuracy: number | null; mocked: number;
}
export interface CheckpointBoard {
  from_date: string; to_date: string; checkpoints: Checkpoint[]; total: number; start: number; scans: Scan[]; results: string[];
  kpis: { checkpoints: number; active: number; no_position: number; valid: number; refused: number; unvisited: number };
}
export const checkpointBoard = (args: { from_date: string; to_date: string; company?: string; farm?: string; result?: string; search?: string; start?: number }) =>
  call<CheckpointBoard>(`${M}.checkpoint_board`, args);
export const saveCheckpoint = (data: Record<string, unknown>) => call<{ ok: true; name: string; qr_image: string | null }>(`${M}.save_checkpoint`, { data });

// --- watchlist -----------------------------------------------------------------------

export interface WatchEntry {
  name: string; full_name: string; person_type: string | null; employee: string | null; supplier: string | null; id_number: string | null;
  phone_number: string | null; vehicle_plate: string | null; status: "Active" | "Inactive"; incident: string | null;
  close_with_incident: number; restrict_to_company: string | null; reason: string | null; added_by: string | null; added_on: string | null;
  activity_count: number | null; last_activity_on: string | null; closed_on: string | null; closed_by: string | null; closure_notes: string | null;
}
export interface WatchActivity {
  name: string; watchlist?: string; person?: string; activity_type: string; occurred_at: string; matched_on: string | null;
  reference_doctype: string | null; reference_name: string | null; farm: string | null; gate: string | null; handled_by?: string | null; details?: string | null;
}
export const watchlistBoard = (args: { status?: string; search?: string; start?: number }) =>
  call<{ counts: { Active: number; Inactive: number }; total: number; start: number; rows: WatchEntry[]; recent: WatchActivity[] }>(`${M}.watchlist_board`, args);
export const watchlistActivity = (watchlist: string) => call<{ total: number; rows: WatchActivity[] }>(`${M}.watchlist_activity`, { watchlist });
export const saveWatchEntry = (data: Record<string, unknown>) => call<{ ok: true; name: string; status: string }>(`${M}.save_watchlist_entry`, { data });

// --- access alerts -------------------------------------------------------------------

export interface Alert {
  name: string; attempt_type: string; reference: string | null; company: string | null; farm: string | null; attempt_time: string;
  detail: string | null; attempted_by: string | null; attempted_by_name: string | null; zone: string | null; person_name: string | null;
  severity: string | null; latitude: string | null; longitude: string | null;
}
export const accessAlerts = (args: { from_date: string; to_date: string; company?: string; farm?: string; attempt_type?: string; severity?: string; search?: string; start?: number }) =>
  call<{ by_type: Record<string, number>; by_severity: Record<string, number>; total_all: number; types: string[]; total: number; start: number; rows: Alert[] }>(`${M}.access_alerts`, args);

// --- personal items ------------------------------------------------------------------

export type ExitStatus = "Inside" | "Left with owner" | "Not seen leaving" | "Left with document";
export interface Item {
  name: string; party_type: string; carried_by: string | null; employee: string | null; supplier: string | null; reference_doctype: string | null;
  reference_name: string | null; farm: string | null; company: string | null; item: string; qty: number | null; serial_notes: string | null;
  declared_at: string | null; entry_time: string | null; recorded_by: string | null; exit_status: ExitStatus; exit_time: string | null;
  exit_checked_by: string | null; supporting_document: string | null; supporting_document_file: string | null;
}
export const personalItems = (args: { from_date: string; to_date: string; company?: string; farm?: string; exit_status?: string; party_type?: string; search?: string; start?: number }) =>
  call<{ counts: Record<ExitStatus, number>; total: number; start: number; rows: Item[]; can_edit: boolean }>(`${M}.personal_items`, args);
export const setItemExit = (name: string, exit_status: ExitStatus, note?: string) => call<{ ok: true; exit_status: ExitStatus }>(`${M}.set_item_exit`, { name, exit_status, note });

// --- gate badges ---------------------------------------------------------------------

export type BadgeStatus = "Available" | "Issued" | "Held at Other Farm" | "Lost";
export interface Badge {
  name: string; badge_type: "Visitor" | "Supplier" | "Contractor"; badge_number: number; company: string; farm: string | null; status: BadgeStatus;
  held_at_farm: string | null; current_appointment: string | null; current_receiving: string | null; supplier: string | null; holder_name: string | null;
  valid_until: string | null; issued_at: string | null; issued_by: string | null; qr_image: string | null;
}
export const badgeBoard = (args: { badge_type?: string; status?: string; company?: string; farm?: string; search?: string; start?: number }) =>
  call<{ counts: Record<BadgeStatus, number>; total: number; start: number; rows: Badge[]; can_manage: boolean }>(`${M}.badge_board`, args);
export const setBadgeStatus = (name: string, status: "Available" | "Lost") => call<{ ok: true; status: BadgeStatus }>(`${M}.set_badge_status`, { name, status });
const GB = "upande_security.upande_security.doctype.gate_badge.gate_badge";
export const createBadges = (badge_type: string, company: string, count: number, farm?: string) =>
  call<{ created: number; first: number; last: number }>(`${GB}.create_badges`, { badge_type, company, count, farm });

// --- guards and devices --------------------------------------------------------------

export interface Guard {
  name: string; full_name: string; status: string; company: string; farm: string | null; post: string | null; reliever: string | null; reliever_name: string | null;
  designation: string | null; phone_number: string | null; date_of_joining: string | null; user: string | null;
  shifts_this_week: number; last_punch: string | null; app_version: string | null; app_last_open: string | null;
}
export const guardBoard = (args: { company?: string; farm?: string; status?: string; search?: string; start?: number }) =>
  call<{ counts: Record<string, number>; total: number; start: number; rows: Guard[]; can_edit: boolean }>(`${M}.guard_board`, args);
export const saveGuard = (args: { name: string; post?: string; farm?: string; reliever?: string; status?: string }) => call<{ ok: true }>(`${M}.save_guard`, args);

export interface Device {
  name: string; login_user: string | null; guard_name: string | null; guard_type: string | null; platform: string | null; app_version: string | null;
  runtime_version: string | null; update_status: string | null; update_channel: string | null; device_model: string | null; os_version: string | null;
  last_app_open: string | null; last_seen_lat: string | null; last_seen_lng: string | null; updated_at: string | null; modified: string;
}
export const deviceBoard = (args: { search?: string; start?: number }) =>
  call<{ total: number; start: number; rows: Device[]; versions: Record<string, number> }>(`${M}.device_board`, args);
