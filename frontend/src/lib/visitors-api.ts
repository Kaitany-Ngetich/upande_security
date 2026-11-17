import { call, type Envelope } from "@/lib/frappe";

const M = "upande_security.api.dashboard_v2";

export type Bucket = "review" | "expected" | "on_site" | "left" | "rejected";

export const BUCKETS: { key: Bucket; label: string }[] = [
  { key: "review", label: "Awaiting approval" },
  { key: "expected", label: "Expected" },
  { key: "on_site", label: "On site" },
  { key: "left", label: "Checked out" },
  { key: "rejected", label: "Rejected" },
];

export interface Visit {
  name: string;
  customer_name: string | null;
  customer_phone_number: string | null;
  customer_organization: string | null;
  custom_id_number: string | null;
  custom_visitor_type: string | null;
  custom_meet_with: string | null;
  custom_meet_with_name: string | null;
  custom_visit_purpose: string | null;
  custom_company: string | null;
  custom_farmunit: string | null;
  scheduled_time: string | null;
  workflow_state: string | null;
  custom_check_in_time: string | null;
  custom_check_out_time: string | null;
  custom_entry_gate: string | null;
  custom_exit_gate: string | null;
  custom_mode_of_transport: string | null;
  custom_vehicles_number_plate: string | null;
  custom_number_of_passengers: number | null;
  custom_visitor_badge: string | null;
  review_actions: string[];
  can_check_in: boolean;
  can_check_out: boolean;
}

export interface Board {
  bucket: Bucket;
  from_date: string;
  to_date: string;
  counts: Record<Bucket, number>;
  total: number;
  start: number;
  rows: Visit[];
}

export function visitorBoard(args: {
  bucket: Bucket;
  from_date: string;
  to_date: string;
  company?: string;
  farm?: string;
  visitor_type?: string;
  search?: string;
  start?: number;
  page_length?: number;
}): Promise<Envelope<Board>> {
  return call<Board>(`${M}.visitor_board`, args);
}

export function farmGates(farm: string) {
  return call<{ gate_name: string; is_main_gate: boolean }[]>(`${M}.farm_gates`, { farm });
}

export function checkIn(args: {
  name: string;
  entry_gate?: string;
  transport?: string;
  plate?: string;
  colour?: string;
  passengers?: number;
}) {
  return call<{
    ok: true; name: string;
    contractor_badges?: { holder_name: string; badge_number: number }[];
    badge_warning?: string;
  }>(`${M}.check_in_visitor`, args);
}

export function checkOut(args: { name: string; exit_gate?: string }) {
  return call<{ ok: true; name: string }>(`${M}.check_out_visitor`, args);
}

export function walkIn(args: Record<string, unknown>) {
  return call<{ ok: true; name: string; duplicate_suppressed?: boolean }>(`${M}.create_walk_in`, args);
}

export function reviewVisit(args: { name: string; action: string; scheduled_time?: string; new_host?: string; note?: string }) {
  return call<{ name: string; workflow_state: string }>("upande_security.api.visit_review.review_visit", args);
}
