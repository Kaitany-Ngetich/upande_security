import { call, type Envelope } from "@/lib/frappe";

const M = "upande_security.api.dashboard_v2";

export type PatrolState = "Active" | "Stale" | "Ended";
export interface PatrolRow {
  patrol: string; guard: string; farm: string | null; points: number; started: string | null; last_fix: string | null;
  minutes: number; state: PatrolState; report: string | null; report_status: string | null; report_type: string | null;
}
export interface PatrolBoard {
  from_date: string; to_date: string;
  kpis: { patrols: number; active: number; stale: number; guards: number; points: number; hours: number; with_report: number; without_report: number };
  counts: Record<PatrolState, number>;
  total: number; start: number; rows: PatrolRow[];
}
export const patrolBoard = (args: {
  from_date: string; to_date: string; company?: string; farm?: string; status?: string; search?: string; start?: number; page_length?: number;
}): Promise<Envelope<PatrolBoard>> => call<PatrolBoard>(`${M}.patrol_board`, args);

export type ReviewStatus = "Submitted" | "Reviewed" | "Flagged";
export interface PatrolReport {
  name: string; patrol: string | null; report_type: "Routine" | "Incident"; farm: string | null; guard: string;
  started_at: string | null; ended_at: string | null; points_logged: number | null; filed_at: string | null;
  observations: string | null; severity: string | null; nature_of_incident: string | null; incident_report: string | null;
  status: ReviewStatus; reviewed_by: string | null; reviewed_by_name: string | null; reviewed_on: string | null;
  supervisor_remarks: string | null; attachments: string[];
}
export interface PatrolReportPage {
  from_date: string; to_date: string; counts: Record<ReviewStatus, number>; total: number; start: number;
  rows: PatrolReport[]; can_review: boolean;
}
export const patrolReports = (args: {
  from_date: string; to_date: string; company?: string; farm?: string; status?: string; report_type?: string;
  search?: string; start?: number; page_length?: number;
}): Promise<Envelope<PatrolReportPage>> => call<PatrolReportPage>(`${M}.patrol_reports`, args);

export const reviewPatrolReport = (args: { name: string; status: ReviewStatus; supervisor_remarks?: string }) =>
  call<{ ok: true; status: ReviewStatus; incident_report: string | null }>(`${M}.review_patrol_report`, args);

// --- guard ranking (patrol_ranking.get_guard_ranking, as it is) ---------------------------

export type Period = "today" | "yesterday" | "this_week" | "last_week" | "this_month" | "last_month";
export interface RankRow {
  farm: string; guard: string; name: string; kind: string; rank: number; score: number; distance_km: number;
  coverage_pct: number | null; area_ha: number | null; patrol_hours: number; patrols: number; points: number;
  scans: number; valid_scans: number; shifts: number; incidents: number; incidents_scored: number; incidents_serious: number;
  first_at: string | null; last_at: string | null;
}
export interface RankFarm {
  farm: string; guards: number; coverage_pct: number | null; area_ha: number | null; covered_ha: number | null;
  distance_km: number; patrol_hours: number; patrols: number; scans: number; valid_scans: number;
  weights: Record<string, number>;
}
export interface Ranking {
  period: string; from_date: string; to_date: string; window_label: string; half: string; checkpoints: boolean;
  farms: RankFarm[]; rows: RankRow[];
}
export const guardRanking = (args: { period: Period; half: "all" | "day" | "night"; company?: string; farm?: string }) =>
  call<Ranking>("upande_security.api.patrol_ranking.get_guard_ranking", args);
