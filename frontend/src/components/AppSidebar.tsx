import { useEffect, useRef, useState } from "react";
import { History, Home, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarSeparator,
  useSidebar,
} from "@/components/ui/sidebar";
import { ScrollArea } from "@/components/ui/scroll-area";
import { SidebarUser } from "@/components/SidebarUser";
import { NAV, type NavItem } from "@/lib/nav";
import { routeHash, type View } from "@/lib/router";
import { cn } from "@/lib/utils";
import { SecurityMark } from "@/components/SecurityMark";

export function AppSidebar({
  view,
  onNavigate,
  allowed = () => true,
}: {
  view: View;
  onNavigate: (view: View) => void;
  /** Whether the user may see an item that requires a right. */
  allowed?: (it: NavItem) => boolean;
}) {
  const { state, toggle } = useSidebar();
  const collapsed = state === "collapsed";

  // The footer is pinned: SidebarContent is the only flexible row in the card
  // (flex-1 min-h-0, overflow hidden) and the nav scrolls INSIDE the ScrollArea
  // it holds, so the footer below it never moves. `moreBelow` is the visual half
  // of that promise — the top border and shadow appear only while nav items are
  // still hidden under the footer, so it reads as sitting over a scrolling list
  // rather than as a permanent rule.
  const navRef = useRef<HTMLDivElement>(null);
  const [moreBelow, setMoreBelow] = useState(false);
  useEffect(() => {
    const vp = navRef.current?.querySelector<HTMLElement>(
      '[data-slot="scroll-area-viewport"]',
    );
    if (!vp) return;
    const update = () =>
      setMoreBelow(vp.scrollHeight - vp.scrollTop - vp.clientHeight > 1);
    update();
    vp.addEventListener("scroll", update, { passive: true });
    // ResizeObserver is not in every test environment, and a missing shadow is
    // not worth a blank sidebar.
    const RO = typeof ResizeObserver === "function" ? ResizeObserver : null;
    const ro = RO ? new RO(update) : null;
    if (ro) {
      ro.observe(vp);
      if (vp.firstElementChild) ro.observe(vp.firstElementChild);
    }
    return () => {
      vp.removeEventListener("scroll", update);
      ro?.disconnect();
    };
  }, [collapsed]);

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        {/* Brand — prominent logo, thin divider, product name with an uppercase
            letter-spaced eyebrow beneath it. */}
        <div className="flex items-center gap-2.5 group-data-[collapsible=icon]:justify-center group-data-[collapsible=icon]:gap-0">
          {/* The animated Security mark (it draws its own disc); links back to
              the Security workspace on the desk. Hover plays the security round. */}
          <a
            href="/app/security"
            title="Open the Security workspace"
            className="flex size-12 shrink-0 items-center justify-center overflow-hidden rounded-full group-data-[collapsible=icon]:size-[3rem]"
          >
            <SecurityMark size={48} title="Upande Security" />
          </a>
          <div className="h-6 w-px shrink-0 bg-border group-data-[collapsible=icon]:hidden" />
          {/* Always rendered, hidden via CSS so the width animation plays around
              it without React inserting/removing nodes mid-transition. */}
          <div
            className={cn(
              "grid min-w-0 flex-1 text-left leading-tight",
              // `hidden` is not animatable, so the name vanished on the first
              // frame and the rail spent the next 260ms closing over the space
              // it left. A 1fr -> 0fr column never measures the text, so there
              // is nothing for it to jump to either.
              "overflow-hidden",
              "grid-cols-[1fr] opacity-100",
              "group-data-[collapsible=icon]:grid-cols-[0fr] group-data-[collapsible=icon]:opacity-0",
            )}
          >
            <span className="truncate text-sm font-semibold tracking-[-0.01em] text-foreground">
              Upande Security
            </span>
            <span className="mt-0.5 truncate text-[10px] font-medium uppercase tracking-[0.16em] text-[var(--sd-quiet)]">
              Dashboard v2
            </span>
          </div>
        </div>
      </SidebarHeader>
      <SidebarSeparator />
      <SidebarContent
        ref={navRef}
        className="overflow-hidden p-0 group-data-[collapsible=icon]:p-0"
      >
        <ScrollArea
          className={cn(
            "h-full w-full",
            // Radix wraps viewport content in a `display: table` div, which
            // sizes to its content rather than to the viewport. Collapsed, the
            // labels are hidden but still measure, so that div keeps the
            // EXPANDED width and every row is laid out against its left edge
            // instead of the rail's centre. Forcing it to block lets it take
            // the rail's width, so the rows have somewhere symmetrical to sit.
            "group-data-[collapsible=icon]:[&>[data-radix-scroll-area-viewport]>div]:!block",
          )}
        >
          <div
            className={cn(
              "flex flex-col gap-1 p-2",
              // Collapsed, this padding IS the centring. A row is 27.2px in
              // a 51px rail, so it wants (51 - 27.2) / 2 = 11.9px either
              // side, less the 1px the scroll viewport insets.
              "group-data-[collapsible=icon]:p-[0.8rem]",
            )}
          >
            {NAV.map((g) => ({ ...g, items: g.items.filter((it) => !it.requires || allowed(it)) })).filter((g) => g.items.length).map((g) => (
              <SidebarGroup key={g.label}>
                <SidebarGroupLabel>{g.label}</SidebarGroupLabel>
                <SidebarGroupContent>
                  <SidebarMenu>
                    {g.items.map((it) => {
                      const Icon = it.icon;
                      return (
                        <SidebarMenuItem key={it.href ?? it.view}>
                          <SidebarMenuButton asChild isActive={!it.href && view === it.view} title={it.href ? `${it.label} (current dashboard)` : it.label}>
                            <a
                              href={it.href ?? routeHash(it.view)}
                              onClick={(e) => {
                                if (it.href) return;
                                e.preventDefault();
                                onNavigate(it.view);
                              }}
                            >
                              <Icon className="h-4 w-4" />
                              <span>{it.label}</span>
                              {it.soon && (
                                <span className="ml-auto text-[10px] font-medium uppercase tracking-[0.08em] text-[var(--sd-quiet)] group-data-[collapsible=icon]:hidden">
                                  Soon
                                </span>
                              )}
                            </a>
                          </SidebarMenuButton>
                        </SidebarMenuItem>
                      );
                    })}
                  </SidebarMenu>
                </SidebarGroupContent>
              </SidebarGroup>
            ))}
          </div>
        </ScrollArea>
      </SidebarContent>
      <SidebarFooter
        className={cn(
          "transition-shadow duration-200",
          moreBelow &&
            "border-t border-sidebar-border shadow-[0_-6px_14px_-10px_rgba(10,10,10,0.16)]",
        )}
      >
        {/* Collapse / Expand — a normal sidebar item, pinned here. The label
            follows the state so the rail's one visible word is never a lie. */}
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton
              onClick={toggle}
              title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            >
              {collapsed ? (
                <PanelLeftOpen className="h-4 w-4" />
              ) : (
                <PanelLeftClose className="h-4 w-4" />
              )}
              <span>{collapsed ? "Expand" : "Collapse"}</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
        <SidebarSeparator />

        {/* Back to Desk, beside the profile chip: a full page load out of this
            app and into Frappe's own workspace at /app. It sits here rather
            than in the nav above because it is not one of this app's surfaces —
            and because somebody new to the app must be able to leave it without
            hunting. A plain <a href>, deliberately: the desk is a different
            document, not a hash route. */}
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton asChild title="Back to Desk — the Frappe workspace at /app">
              {/* No loading cover on the way out: Frappe raises its own the
                  moment /app starts loading, and two covers handing over to
                  each other is one more than the crossing needs. */}
              <a href="/app">
                <Home className="h-4 w-4" />
                <span>Back to Desk</span>
              </a>
            </SidebarMenuButton>
          </SidebarMenuItem>
          <SidebarMenuItem>
            <SidebarMenuButton asChild title="The current Security Dashboard, until v2 replaces it">
              <a href="/security-dashboard">
                <History className="h-4 w-4" />
                <span>Current dashboard</span>
              </a>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
        <SidebarUser />
      </SidebarFooter>
    </Sidebar>
  );
}
