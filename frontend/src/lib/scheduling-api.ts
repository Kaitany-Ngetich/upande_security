import { call } from "@/lib/frappe";

const M = "upande_security.api.dashboard_v2";

export interface SchedulingOptions {
  shift_types: string[];
  times: Record<string, { start_time: string; end_time: string }>;
  can_plan: boolean;
}
export const schedulingOptions = () => call<SchedulingOptions>(`${M}.scheduling_options`);

// --- shifts (security_dashboard.fetchSecurityDasboardData, tab "shifts") ------------

export interface Biometric { clock_in: string | null; clock_out: string | null; result: string | null; late_min: number | null; departure: string | null; early_min: number | null }
export interface ShiftRow {
  name: string; guard_key: string; guard_name: string; guard_type: "Internal Guard" | "External Guard"; farm: string; block: string;
  shift_type: string; start_date: string | null; end_date: string | null; status: string; remarks: string;
  biometric: Biometric | null; checked_in: number; covering_for: string | null; covering_for_name: string | null;
}
export interface OffDay { guard: string; guard_name: string; farm: string; date: string; covered_by: string | null }
export interface ShiftBoard {
  success: boolean;
  off_days: OffDay[];
  summary: {
    total_assignments: number; off_count: number; off_uncovered: number; checked_in_total: number; on_duty_total: number;
    farms_covered: number; farms_total: number; unfilled_slots: number; guards_on_rotation: number;
    shift_type_summary: { shift_type: string; total: number; checked_in: number; not_checked_in: number }[];
  };
  coverage_board: { farm: string; shifts: { shift_type: string; guard_name: string | null }[] }[];
  rows: ShiftRow[];
}
export const shiftBoard = (args: { from_date: string; to_date: string; company?: string; farm?: string; shift_type?: string; status?: string }) =>
  call<ShiftBoard>("upande_security.api.security_dashboard.fetchSecurityDasboardData", { tab: "shifts", period: "custom", ...args });

export const createShift = (args: {
  external_guard: string; farm: string; shift_type: string; date: string; start_time?: string; end_time?: string; block?: string; remarks?: string;
}) => call<{ ok: true; name: string; status: string }>(`${M}.create_shift`, args);
export const cancelShift = (name: string, reason?: string) => call<{ ok: true }>(`${M}.cancel_shift`, { name, reason });

// --- monthly schedule (shift_schedule, as it is) ------------------------------------

export type DayState = "on" | "off_covered" | "off_unfilled" | "off_no_reliever";
export interface DayCell { state: DayState; shift_type?: string; covered_by?: string; covered_by_name?: string; is_off_day: boolean; reason?: string }
export interface ScheduleGuard { name: string; full_name: string; farm: string; post: string; reliever: string | null; reliever_name: string | null }
export interface MonthSchedule {
  guards: ScheduleGuard[]; farms: string[]; days: number[]; statuses: Record<string, Record<number, DayCell>>; month: number; year: number;
}
export const monthSchedule = (year: number, month: number, farm?: string) =>
  call<MonthSchedule>("upande_security.api.shift_schedule.get_shift_schedule", { year, month, farm });

/** Mark a guard's day off (with an optional cover) or back on. */
export const toggleDay = (args: { guard: string; date: string; mark_off: 0 | 1; farm?: string; shift_type?: string; cover_guard?: string }) =>
  call<DayCell>("upande_security.api.shift_schedule.toggle_guard_day", args);

export interface Suggestion {
  guard: string; full_name: string; home_farm: string | null; designated: number; previous: string | null; available: number;
  busy_reason: string | null; on_off_day: number; farm_shifts: number; shift_type_shifts: number; reason: string; shortlist: number;
}
export interface Relievers {
  guard: string; guard_name: string; date: string; farm: string | null; shift_type: string; start_time: string; end_time: string;
  designated_reliever: string | null; suggestions: Suggestion[]; counts: { candidates: number; available: number };
}
export const suggestRelievers = (args: { guard: string; date: string; farm?: string; shift_type?: string }) =>
  call<Relievers>("upande_security.api.relievers.suggest_relievers", { ...args, limit: "all" });

// --- rotation plans -----------------------------------------------------------------

export interface PlanRow {
  name: string; external_guard: string; guard_name: string; status: "Draft" | "Applied" | "Cancelled"; mode: string;
  shift_type: string; start_time: string; end_time: string; start_date: string; end_date: string;
  rotation_interval_days: number; rotate_shifts: number; farms: string[]; modified: string;
}
export const rotationPlans = (args: { status?: string; search?: string; start?: number }) =>
  call<{ total: number; start: number; rows: PlanRow[]; can_plan: boolean }>(`${M}.rotation_plans`, args);

export interface PreviewRow {
  name: string; date: string; farm: string; block: string | null; is_off_day: number; status: string; shift_type: string;
  start_time: string; end_time: string; cover_guard: string | null; cover_guard_name: string | null;
}
export interface PlanDetail extends Omit<PlanRow, "farms"> {
  farms: { farm: string; block: string | null }[]; shift_sequence: string[]; shift_change_every_days: number | null;
  remarks: string | null; preview: PreviewRow[]; can_plan: boolean;
}
export const rotationPlan = (name: string) => call<PlanDetail>(`${M}.rotation_plan`, { name });
export const saveRotationPlan = (data: Record<string, unknown>) => call<{ ok: true; name: string }>(`${M}.save_rotation_plan`, { data });
export const planAction = (name: string, action: "preview" | "apply" | "preview_and_apply" | "cancel") =>
  call<{ ok: true; rows?: number; off_days?: number; applied?: number; failed?: number; skipped?: number; status?: string; uncovered_off_days?: unknown[] }>(
    `${M}.rotation_plan_action`, { name, action });
export const togglePreviewDay = (plan_name: string, row_name: string, mark_off: 0 | 1, cover_guard?: string) =>
  call<DayCell>("upande_security.upande_security.doctype.security_guard_rotation_plan.security_guard_rotation_plan.toggle_preview_row_off_day",
    { plan_name, row_name, mark_off, cover_guard });
