import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { call, isError } from "@/lib/frappe";

/** What api.dashboard_v2.bootstrap says about the signed-in user. */
export interface Boot {
  companies: string[];
  farms: { name: string; company: string | null }[];
  can_check_in_out: boolean;
  can_review: boolean;
  approval_workflow: boolean;
  visitor_types: string[];
  /** Gate operations switched on in Security Ops Settings (feature_* -> on). */
  features: Record<string, boolean>;
  /** Security Head / System Manager: the covert watchlist and checkpoint setup. */
  can_watchlist: boolean;
  can_setup: boolean;
  /** What this organisation calls a site and an area (Security Ops Settings > Words Used). */
  terms: { site_label: string; site_label_plural: string; area_label: string; area_label_plural: string };
  can_settings: boolean;
}

/** The company / farm every page is looking at. Blank = everything the user may see. */
export interface Scope {
  company: string;
  farm: string;
}

interface ScopeState {
  boot: Boot;
  scope: Scope;
  setScope: (s: Scope) => void;
  /** Farms under the chosen company (all farms when none is chosen). */
  farmsInScope: string[];
}

const KEY = "secdash2.scope";
const Ctx = createContext<ScopeState | null>(null);

function readScope(): Scope {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) || "{}");
    return { company: String(raw.company || ""), farm: String(raw.farm || "") };
  } catch {
    return { company: "", farm: "" };
  }
}

export type BootState =
  | { status: "loading" }
  | { status: "error"; error: string; reload: () => void }
  | { status: "ready"; boot: Boot };

export function useBoot(): BootState {
  const [state, setState] = useState<BootState>({ status: "loading" });
  const load = useCallback(() => {
    setState({ status: "loading" });
    void call<Boot>("upande_security.api.dashboard_v2.bootstrap").then((r) => {
      if (isError(r)) setState({ status: "error", error: r.error, reload: load });
      else setState({ status: "ready", boot: r as Boot });
    });
  }, []);
  useEffect(load, [load]);
  return state;
}

export function ScopeProvider({ boot, children }: { boot: Boot; children: React.ReactNode }) {
  const [scope, setScopeRaw] = useState<Scope>(() => {
    const s = readScope();
    // A remembered company/farm the user can no longer see is dropped.
    return {
      company: boot.companies.includes(s.company) ? s.company : "",
      farm: boot.farms.some((f) => f.name === s.farm) ? s.farm : "",
    };
  });
  const setScope = useCallback((s: Scope) => {
    setScopeRaw(s);
    try {
      localStorage.setItem(KEY, JSON.stringify(s));
    } catch {
      /* private window: the choice just is not remembered */
    }
  }, []);
  const farmsInScope = useMemo(
    () => boot.farms.filter((f) => !scope.company || f.company === scope.company).map((f) => f.name),
    [boot.farms, scope.company],
  );
  const value = useMemo(() => ({ boot, scope, setScope, farmsInScope }), [boot, scope, setScope, farmsInScope]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useScope(): ScopeState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useScope outside ScopeProvider");
  return v;
}

/** The organisation's words for its places, ready for labels and sentences:
 *  Site / Sites / site / sites and Area / Areas / area / areas. */
export function useTerms() {
  const v = useContext(Ctx);
  const t = v?.boot.terms ?? { site_label: "Farm", site_label_plural: "Farms", area_label: "Block", area_label_plural: "Blocks" };
  return {
    Site: t.site_label, Sites: t.site_label_plural, site: t.site_label.toLowerCase(), sites: t.site_label_plural.toLowerCase(),
    Area: t.area_label, Areas: t.area_label_plural, area: t.area_label.toLowerCase(), areas: t.area_label_plural.toLowerCase(),
  };
}
