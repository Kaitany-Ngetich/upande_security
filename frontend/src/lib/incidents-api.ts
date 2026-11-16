import { call, type Envelope } from "@/lib/frappe";

const M = "upande_security.api.dashboard_v2";

export interface Category { name: string; category_name?: string; default_severity?: string; color?: string }
export interface IncidentOptions { categories: Category[]; statuses: string[]; severities: string[]; can_manage: boolean }

export interface IncidentRow {
  name: string;
  incident_datetime: string | null;
  farm: string | null;
  location: string | null;
  nature_of_incident: string;
  severity: string;
  status: string | null;
  reporter_name: string | null;
  assigned_to: string | null;
  description: string;
  resolution_datetime: string | null;
  attachments: string[];
}

export interface IncidentBoard {
  from_date: string;
  to_date: string;
  kpis: {
    total: number; active: number; critical_open: number; high_open: number;
    in_progress: number; resolved: number; avg_resolution_minutes: number | null;
  };
  by_status: Record<string, number>;
  by_category: { category: string; count: number }[];
  by_location: { location: string; count: number }[];
  over_time: { day: string; count: number }[];
  total: number;
  start: number;
  rows: IncidentRow[];
}

export interface IncidentPerson { person_name?: string; person_type?: string; contact?: string; id_number?: string; notes?: string; statement?: string }

/** get_incident_report plus farm, assignee, resolution and photos (dashboard_v2.incident_detail). */
export interface IncidentDetail extends Record<string, unknown> {
  name: string;
  incident_datetime: string;
  location: string;
  nature_of_incident: string;
  severity: string;
  description: string;
  status: string;
  reporter_name: string;
  farm: string | null;
  assigned_to: string | null;
  resolution: string | null;
  corrective_actions: string | null;
  resolution_datetime: string | null;
  attachments: string[];
  witnesses?: IncidentPerson[];
  victims?: IncidentPerson[];
  can_manage: boolean;
}

export const incidentOptions = () => call<IncidentOptions>(`${M}.incident_options`);

export function incidentBoard(args: {
  from_date: string; to_date: string; company?: string; farm?: string; status?: string;
  severity?: string; category?: string; search?: string; start?: number; page_length?: number;
}): Promise<Envelope<IncidentBoard>> {
  return call<IncidentBoard>(`${M}.incident_board`, args);
}

export const incidentDetail = (name: string) =>
  call<IncidentDetail>(`${M}.incident_detail`, { name });

export const createIncident = (args: Record<string, unknown>) =>
  call<{ ok: true; name: string }>(`${M}.create_incident`, args);

/** Only the keys present are changed (the endpoint tells absent from empty). */
export const updateIncident = (args: {
  name: string; status?: string; resolution?: string; corrective_actions?: string; assigned_to?: string;
}) => call<{ ok: true }>(`${M}.update_incident`, args);

export const attachIncidentPhotos = (name: string, file_urls: string[]) =>
  call<{ ok: true; attached: number; skipped: number }>(`${M}.attach_incident_photos`, { name, file_urls });
