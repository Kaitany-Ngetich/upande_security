import { useCallback, useEffect, useState } from "react";

/**
 * Hash routing: `#/<view>`.
 *
 * A hash router because Frappe serves the app at one route
 * (/security-dashboard-v2); a path router would need a server-side catch-all.
 */

export const VIEWS = [
  // Gate operations
  "visitors",
  "contractors",
  "dispatch",
  "receiving",
  "vehicles",
  "staff",
  "stickers",
  "items",
  "badges",
  // Security
  "incidents",
  "patrols",
  "patrol-reports",
  "ranking",
  "checkpoints",
  "watchlist",
  "alerts",
  // CCTV (shown only while the module is switched on)
  "cctv-live",
  "cctv-alerts",
  "cctv-vehicles",
  "cctv-review",
  "cctv-health",
  // Scheduling
  "shifts",
  "schedule",
  "rotations",
  "guards",
  "devices",
  // Admin
  "settings",
] as const;

export type View = (typeof VIEWS)[number];

export const DEFAULT_VIEW: View = "visitors";

const KNOWN: ReadonlySet<string> = new Set<string>(VIEWS);

export function isView(v: string): v is View {
  return KNOWN.has(v);
}

/** `#/visitors` -> "visitors"; anything unreadable lands on the default view. */
export function parseRoute(hash: string): View {
  const v = (hash || "").replace(/^#\/?/, "").split(/[/?]/)[0].toLowerCase();
  return isView(v) ? v : DEFAULT_VIEW;
}

export function routeHash(view: View): string {
  return `#/${view}`;
}

export function useRoute(): [View, (view: View) => void] {
  const [view, setView] = useState<View>(() => parseRoute(window.location.hash));

  useEffect(() => {
    const onChange = () => setView(parseRoute(window.location.hash));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);

  const navigate = useCallback((next: View) => {
    const h = routeHash(next);
    if (window.location.hash !== h) window.location.hash = h;
  }, []);

  return [view, navigate];
}
