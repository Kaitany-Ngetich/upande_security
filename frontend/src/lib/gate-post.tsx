import { useEffect, useState } from "react";
import { isError } from "@/lib/frappe";
import { useScope } from "@/lib/scope";
import { farmGates } from "@/lib/visitors-api";

const KEY = "secdash2.gate";

/**
 * Where a gate action is recorded: the farm (the dashboard's farm scope, or the
 * only farm there is) and one of its gates, remembered per farm.
 *
 * Sent as `checking_farm` + `gate`, exactly as the guard app sends them. The
 * server uses checking_farm only as a fallback: a login linked to a farm (its
 * Employee, its Security Guard record or today's roster) always records there,
 * so nobody can book a truck under a farm they are not posted to.
 */
export function useGatePost() {
  const { scope, farmsInScope } = useScope();
  const farm = scope.farm || (farmsInScope.length === 1 ? farmsInScope[0] : "");
  const [gates, setGates] = useState<string[]>([]);
  const [gate, setGateRaw] = useState("");

  useEffect(() => {
    setGates([]);
    if (!farm) return;
    void farmGates(farm).then((r) => {
      const list = isError(r) || !Array.isArray(r) ? [] : r.map((g) => g.gate_name);
      setGates(list);
      let saved = "";
      try {
        saved = JSON.parse(localStorage.getItem(KEY) || "{}")[farm] || "";
      } catch {
        /* no storage */
      }
      setGateRaw(list.includes(saved) ? saved : list[0] ?? "");
    });
  }, [farm]);

  const setGate = (g: string) => {
    setGateRaw(g);
    try {
      const all = JSON.parse(localStorage.getItem(KEY) || "{}");
      localStorage.setItem(KEY, JSON.stringify({ ...all, [farm]: g }));
    } catch {
      /* no storage */
    }
  };

  /** The arguments every gate action carries. */
  const post = { checking_farm: farm || undefined, gate: gate || undefined };
  return { farm, gates, gate, setGate, post };
}
