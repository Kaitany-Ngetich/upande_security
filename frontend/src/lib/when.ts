import { todayISO } from "@/lib/utils";

/** "2026-11-12 09:30:00" -> "12 Nov, 09:30" (today: just the time). */
export function when(v: string | null | undefined): string {
  if (!v) return "—";
  const d = new Date(String(v).replace(" ", "T"));
  if (Number.isNaN(d.getTime())) return String(v);
  const time = d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  if (String(v).slice(0, 10) === todayISO()) return time;
  return `${d.toLocaleDateString("en-GB", { day: "numeric", month: "short" })}, ${time}`;
}
