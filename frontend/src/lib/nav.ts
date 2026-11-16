import type { LucideIcon } from "lucide-react";
import { ArrowLeftRight, Settings2, Backpack, IdCard, ShieldX, Smartphone, Users, CarFront, Eye, QrCode, CalendarDays, CalendarRange, Clock, ClipboardCheck, Footprints, HardHat, History, Map, PackageCheck, ShieldAlert, Trophy, Truck, UserCheck, Warehouse } from "lucide-react";
import type { View } from "@/lib/router";

export interface NavItem {
  view: View;
  label: string;
  icon: LucideIcon;
  /** Not built yet: shown, and opens a "coming next" page. */
  soon?: boolean;
  /** A page outside v2 (still a v1 page): a plain link, a full page load. */
  href?: string;
  /** Listed (and reachable) only for users with this right, from the bootstrap. */
  requires?: "watchlist" | "settings";
}

export interface NavGroup {
  label: string;
  items: NavItem[];
}

/** The sidebar, in order. Gate operations first: they are what v2 is for. */
export const NAV: NavGroup[] = [
  {
    label: "Gate operations",
    items: [
      { view: "visitors", label: "Visitors", icon: UserCheck },
      { view: "contractors", label: "Contractors", icon: HardHat },
      { view: "dispatch", label: "Dispatch check", icon: PackageCheck },
      { view: "receiving", label: "Receiving check", icon: Warehouse },
      { view: "vehicles", label: "Vehicle check", icon: Truck },
      { view: "staff", label: "Staff movement", icon: ArrowLeftRight },
      { view: "stickers", label: "Vehicle stickers", icon: CarFront },
      { view: "badges", label: "Gate badges", icon: IdCard },
      { view: "items", label: "Personal items", icon: Backpack },
    ],
  },
  {
    label: "Security",
    items: [
      { view: "incidents", label: "Incidents", icon: ShieldAlert },
      { view: "alerts", label: "Access alerts", icon: ShieldX },
      { view: "patrols", label: "Patrols", icon: Footprints },
      { view: "patrol-reports", label: "Patrol reports", icon: ClipboardCheck },
      { view: "ranking", label: "Guard ranking", icon: Trophy },
      { view: "checkpoints", label: "Checkpoints", icon: QrCode },
      { view: "watchlist", label: "Watchlist", icon: Eye, requires: "watchlist" },
      // The maps are still v1 pages; linked until they move in.
      { view: "patrols", label: "Patrol map", icon: Map, href: "/patrol-map" },
      { view: "patrols", label: "Patrol playback", icon: History, href: "/patrol-playback" },
    ],
  },
  {
    label: "Scheduling",
    items: [
      { view: "shifts", label: "Shifts", icon: Clock },
      { view: "schedule", label: "Monthly schedule", icon: CalendarDays },
      { view: "rotations", label: "Rotation plans", icon: CalendarRange },
      { view: "guards", label: "Guards", icon: Users },
      { view: "devices", label: "Guard devices", icon: Smartphone },
    ],
  },
  {
    label: "Admin",
    items: [{ view: "settings", label: "Settings", icon: Settings2, requires: "settings" }],
  },
];

export function navItem(view: View): NavItem | undefined {
  for (const g of NAV) for (const it of g.items) if (it.view === view && !it.href) return it;
  return undefined;
}
