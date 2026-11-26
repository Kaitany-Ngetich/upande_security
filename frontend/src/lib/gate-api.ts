import { call, type Envelope } from "@/lib/frappe";

/** The guard app's own endpoints, called as they are. */
const API = "upande_security.api";
type Post = { checking_farm?: string; gate?: string };

// --- shared log ----------------------------------------------------------------------

export type LogKind = "dispatch" | "receiving" | "vehicles";
export interface LogPage<T> {
  kind: LogKind;
  total: number;
  start: number;
  rows: T[];
}
export function gateLog<T>(args: {
  kind: LogKind; from_date: string; to_date: string; company?: string; farm?: string;
  status?: string; search?: string; start?: number; page_length?: number;
}): Promise<Envelope<LogPage<T>>> {
  return call<LogPage<T>>(`${API}.dashboard_v2.gate_log`, args);
}

// --- dispatch ------------------------------------------------------------------------

export interface ExpectedItem { row_id: string; item_code: string; item_name?: string; qty: number; uom?: string }
export interface DispatchMatch {
  found: boolean;
  reference_doctype: string;
  reference_name: string;
  vehicle_no: string | null;
  driver_name: string | null;
  dispatch_datetime: string | null;
  farm: string | null;
  items_summary: string | null;
  source_status: string | null;
  is_authorized: boolean;
  expected_items: ExpectedItem[];
  already_verified: boolean;
  already_verified_at: string | null;
  already_verified_by: string | null;
  related_by_vehicle?: DispatchMatch[];
}
export interface DispatchResult {
  name?: string;
  reference?: string;
  reference_name?: string;
  gate_verification_status?: string;
  shortfall_incident?: string | null;
  error?: string;
}
export interface DispatchLogRow {
  name: string; reference_doctype: string; reference_name: string; farm: string | null; vehicle_no: string | null;
  driver_name: string | null; items_summary: string | null; gate_verification_status: string;
  gate_verified_by_name?: string; gate: string | null; gate_exit_time: string | null; remarks: string | null;
}

export const searchDispatch = (reference: string) =>
  call<DispatchMatch>(`${API}.gate_dispatch.search_dispatch_for_gate`, { reference });

export const verifyDispatch = (args: Post & {
  reference: string; gate_verification_status: "Verified" | "Rejected"; remarks?: string;
  item_checks?: { row_id: string; actual_qty: number }[]; vehicle_no?: string; driver_name?: string;
}) => call<DispatchResult>(`${API}.gate_dispatch.verify_dispatch_at_gate`, args);

export const verifyDispatchBulk = (args: Post & {
  references: string[]; gate_verification_status: "Verified" | "Rejected"; remarks?: string;
  vehicle_no?: string; driver_name?: string;
}) => call<{ results: DispatchResult[] }>(`${API}.gate_dispatch.verify_dispatch_at_gate_bulk`, args);

// --- receiving -----------------------------------------------------------------------

export interface PoMatch {
  purchase_order: string; supplier: string; supplier_name: string; po_status: string; supplier_active: boolean;
  transaction_date: string | null; schedule_date: string | null; items_summary: string | null; is_authorized: boolean;
}
export interface Truck {
  name: string; purchase_orders: string[]; supplier: string; supplier_name: string; vehicle_no: string | null;
  driver_name: string | null; arrived_at: string; items_inside: number;
}
export interface Departure {
  name: string; records: string[]; supplier_name: string; vehicle_no: string | null; driver_name: string | null;
  departed: boolean; items: { name: string; item: string; qty?: number; serial_notes?: string }[]; receipt_required: boolean;
}
export interface ReceivingLogRow {
  name: string; purchase_order: string; supplier: string; farm: string | null; vehicle_no: string | null;
  driver_name: string | null; items_summary: string | null; gate_verification_status: string;
  gate_verified_by_name?: string; gate: string | null; gate_arrival_time: string | null; gate_departure_time: string | null;
  purchase_receipt: string | null; supplier_delivery_note: string | null; no_receipt_reason: string | null;
}

export const searchReceiving = (reference: string) =>
  call<PoMatch & { found: boolean }>(`${API}.gate_receiving.search_receiving_for_gate`, { reference });
export const searchByBadge = (reference: string) =>
  call<{ found: boolean; badge: string; supplier: string; supplier_name: string; matches: PoMatch[] }>(
    `${API}.gate_receiving.search_receiving_by_supplier_badge`, { reference });
export const verifyReceivingBulk = (args: Post & {
  references: string[]; gate_verification_status: "Verified" | "Rejected"; vehicle_no?: string; driver_name?: string; remarks?: string;
}) => call<{ results: { name?: string; reference?: string; error?: string }[] }>(`${API}.gate_receiving.verify_receiving_at_gate_bulk`, args);
export const trucksInside = (post: Post) =>
  call<Truck[]>(`${API}.gate_receiving.list_receivings_awaiting_departure`, post);
export const getDeparture = (name: string) => call<Departure>(`${API}.gate_receiving.get_receiving_departure`, { name });
export const confirmDeparture = (args: Post & {
  name: string; items_out?: string[]; receipts?: string[]; no_receipt_reason?: string; supplier_delivery_note?: string;
}) => call<{ ok?: boolean; error?: string }>(`${API}.gate_receiving.confirm_receiving_departure`, args);

// --- vehicles ------------------------------------------------------------------------

export interface Leg {
  name: string; from_farm: string | null; to_farm: string | null; task_description: string | null;
  gate_exit_time: string | null; gate_exit_status: string | null; gate_entry_time: string | null; gate_entry_status: string | null;
}
export interface VehicleMatch {
  found: boolean; reference_doctype: string; reference_name: string; asset: string | null; has_task: boolean;
  vehicle_no: string; task_description: string | null; source_status: string | null; is_authorized: boolean; recent_legs: Leg[];
}
export interface VehicleLogRow extends Leg {
  vehicle_no: string; asset: string | null; exit_gate: string | null; entry_gate: string | null;
  gate_exit_verified_by_name?: string; gate_entry_verified_by_name?: string; remarks: string | null;
}
export const searchVehicle = (reference: string) =>
  call<VehicleMatch>(`${API}.gate_vehicle.search_vehicle_task_for_gate`, { reference });
export const verifyVehicle = (args: Post & {
  reference: string; movement_type: "Exit" | "Entry"; gate_verification_status: "Verified" | "Rejected"; remarks?: string;
}) => call<{ name: string; leg_complete: boolean; unmatched_entry: boolean; farm: string; gate: string }>(
  `${API}.gate_vehicle.verify_vehicle_task_at_gate`, args);

// --- staff ---------------------------------------------------------------------------

export interface StaffInside { name: string; employee: string; employee_name: string; department: string; in_time: string }
export interface StaffMove {
  name: string; employee: string | null; employee_name: string | null; company: string | null; farm: string | null;
  date: string; in_time: string | null; out_time: string | null; plate: string | null; entry_gate: string | null;
  exit_gate: string | null; party_type: string; badge?: string | null;
}
export const staffInside = (post: Post) => call<{ staff: StaffInside[] }>(`${API}.security_api.list_checked_in_staff`, post);
export const staffMoves = (args: Post & { from_date: string; to_date: string }) =>
  call<{ staff: StaffMove[] }>(`${API}.security_api.list_staff_movements`, args);
export const staffIn = (args: Post & { employee: string; vehicle_plate?: string; entry_gate?: string }) =>
  call<{ name: string; employee_name: string; in_time: string }>(`${API}.security_api.create_staff_attendance`, args);
export const staffOut = (args: Post & { attendance_name: string; exit_gate?: string }) =>
  call<{ success: boolean; working_hours?: number }>(`${API}.security_api.staff_gate_checkout`, args);

// --- contractors ---------------------------------------------------------------------

export interface Crew {
  crew: { full_name: string; id_number?: string; is_team_leader?: number }[];
  badges: { badge: string; badge_number: string; holder_name: string; holder_id_number?: string; valid_until?: string }[];
  valid_until: string;
  /** The company keeps a contractor badge pool: every crew member needs one before check-in. */
  required: boolean;
  available: number;
}
export const crewFor = (appointment: string) => call<Crew>(`${API}.contractor_badge.badges_for_visit`, { appointment });
export const issueCrewBadges = (appointment: string) =>
  call<{ issued: { holder_name: string; badge_number: string }[]; still_needed: number }>(`${API}.contractor_badge.issue_badges_to_crew`, { appointment });
export const returnBadge = (badge: string) => call<{ ok?: boolean }>(`${API}.contractor_badge.return_contractor_badge`, { badge });
