import { lazy, Suspense } from "react";
import { AppSidebar } from "@/components/AppSidebar";
import { PageSkeleton } from "@/components/Loading";
import { Page } from "@/components/PageShell";
import { ToastProvider } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";
import { navItem, type NavItem } from "@/lib/nav";
import { DEFAULT_VIEW, useRoute, type View } from "@/lib/router";
import { ScopeProvider, useBoot } from "@/lib/scope";
import { ComingNext } from "@/pages/ComingNext";

// Built pages load lazily, so first paint never pulls the whole app and each
// gate operation added later does not grow it.
const Visitors = lazy(() => import("@/pages/Visitors").then((m) => ({ default: m.Visitors })));
const Contractors = lazy(() => import("@/pages/Visitors").then((m) => ({ default: m.Contractors })));
const Dispatch = lazy(() => import("@/pages/Dispatch").then((m) => ({ default: m.Dispatch })));
const Receiving = lazy(() => import("@/pages/Receiving").then((m) => ({ default: m.Receiving })));
const Vehicles = lazy(() => import("@/pages/Vehicles").then((m) => ({ default: m.Vehicles })));
const Staff = lazy(() => import("@/pages/Staff").then((m) => ({ default: m.Staff })));
const Incidents = lazy(() => import("@/pages/Incidents").then((m) => ({ default: m.Incidents })));
const Patrols = lazy(() => import("@/pages/Patrols").then((m) => ({ default: m.Patrols })));
const PatrolReports = lazy(() => import("@/pages/PatrolReports").then((m) => ({ default: m.PatrolReports })));
const Ranking = lazy(() => import("@/pages/Ranking").then((m) => ({ default: m.Ranking })));
const Shifts = lazy(() => import("@/pages/Shifts").then((m) => ({ default: m.Shifts })));
const Schedule = lazy(() => import("@/pages/Schedule").then((m) => ({ default: m.Schedule })));
const Rotations = lazy(() => import("@/pages/Rotations").then((m) => ({ default: m.Rotations })));
const Stickers = lazy(() => import("@/pages/Stickers").then((m) => ({ default: m.Stickers })));
const Checkpoints = lazy(() => import("@/pages/Checkpoints").then((m) => ({ default: m.Checkpoints })));
const Watchlist = lazy(() => import("@/pages/Watchlist").then((m) => ({ default: m.Watchlist })));
const Alerts = lazy(() => import("@/pages/Alerts").then((m) => ({ default: m.Alerts })));
const Items = lazy(() => import("@/pages/Items").then((m) => ({ default: m.Items })));
const Badges = lazy(() => import("@/pages/Badges").then((m) => ({ default: m.Badges })));
const Guards = lazy(() => import("@/pages/Guards").then((m) => ({ default: m.Guards })));
const Devices = lazy(() => import("@/pages/Devices").then((m) => ({ default: m.Devices })));
const Settings = lazy(() => import("@/pages/Settings").then((m) => ({ default: m.Settings })));
const CctvLive = lazy(() => import("@/pages/Cctv").then((m) => ({ default: m.CctvLive })));
const CctvAlerts = lazy(() => import("@/pages/Cctv").then((m) => ({ default: m.CctvAlerts })));
const CctvVehicles = lazy(() => import("@/pages/Cctv").then((m) => ({ default: m.CctvVehicles })));
const CctvReview = lazy(() => import("@/pages/Cctv").then((m) => ({ default: m.CctvReview })));
const CctvHealth = lazy(() => import("@/pages/Cctv").then((m) => ({ default: m.CctvHealth })));
const CctvPresence = lazy(() => import("@/pages/CctvMore").then((m) => ({ default: m.CctvPresence })));
const CctvMap = lazy(() => import("@/pages/CctvMore").then((m) => ({ default: m.CctvMap })));

const PAGES: Partial<Record<View, React.ComponentType>> = {
  visitors: Visitors,
  contractors: Contractors,
  dispatch: Dispatch,
  receiving: Receiving,
  vehicles: Vehicles,
  staff: Staff,
  incidents: Incidents,
  patrols: Patrols,
  "patrol-reports": PatrolReports,
  ranking: Ranking,
  shifts: Shifts,
  schedule: Schedule,
  rotations: Rotations,
  stickers: Stickers,
  checkpoints: Checkpoints,
  watchlist: Watchlist,
  alerts: Alerts,
  items: Items,
  badges: Badges,
  guards: Guards,
  devices: Devices,
  settings: Settings,
  "cctv-live": CctvLive,
  "cctv-alerts": CctvAlerts,
  "cctv-vehicles": CctvVehicles,
  "cctv-review": CctvReview,
  "cctv-health": CctvHealth,
  "cctv-presence": CctvPresence,
  "cctv-map": CctvMap,
};

/** Says why the workspace is empty, and what to do, in place of a blank page. */
function Notice({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <Page>
      <div className="flex max-w-xl flex-col items-start gap-3 rounded-[var(--sd-radius-lg)] bg-[var(--sd-card)] px-5 py-5 shadow-[var(--sd-shadow-1)]">
        <h1 className="text-[18px] font-semibold text-[var(--sd-ink)]">{title}</h1>
        {children}
      </div>
    </Page>
  );
}

export function App() {
  const state = useBoot();
  const [view, navigate] = useRoute();
  const item = navItem(view);
  const may = (it: NavItem) => {
    if (state.status !== "ready") return false;
    const r = it.requires;
    if (!r) return true;
    if (r === "watchlist") return state.boot.can_watchlist;
    if (r === "settings") return state.boot.can_settings;
    const caps = state.boot.cctv;
    const key = r.slice("cctv:".length) as keyof NonNullable<typeof caps>;
    return !!caps?.enabled && !!caps[key];
  };
  const allowed = !item?.requires || may(item);
  // A restricted page asked for by URL shows the default page, not a notice
  // that would say it exists.
  const shown: View = allowed ? view : DEFAULT_VIEW;
  const Built = item?.soon && allowed ? undefined : PAGES[shown];

  let main: React.ReactNode;
  if (state.status === "loading") {
    main = <PageSkeleton />;
  } else if (state.status === "error") {
    main = (
      <Notice title="Could not load the Security Dashboard">
        <p className="text-[13px] text-[var(--sd-muted)]">{state.error}</p>
        <Button onClick={state.reload}>Try again</Button>
      </Notice>
    );
  } else {
    main = (
      <ScopeProvider boot={state.boot}>
        <Suspense fallback={<PageSkeleton />}>{Built ? <Built key={shown} /> : <ComingNext view={shown} />}</Suspense>
      </ScopeProvider>
    );
  }

  return (
    <TooltipProvider delayDuration={200}>
      <ToastProvider>
        <SidebarProvider>
          <AppSidebar view={view} onNavigate={navigate} allowed={may} />
          {/* min-w-0 so a wide table scrolls in its own box instead of pushing the page sideways. */}
          <SidebarInset className="min-w-0">{main}</SidebarInset>
        </SidebarProvider>
      </ToastProvider>
    </TooltipProvider>
  );
}
