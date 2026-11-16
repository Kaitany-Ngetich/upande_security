import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { SidebarMenu, SidebarMenuItem } from "@/components/ui/sidebar";
import { bootstrap } from "@/lib/frappe";

export function initialsOf(name: string): string {
  if (!name) return "?";
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) {
    const single = parts[0];
    // Emails fall back to the first character of the local-part.
    const local = single.includes("@") ? single.split("@")[0] : single;
    return (local[0] || "?").toUpperCase();
  }
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

/**
 * Bottom-of-sidebar profile chip: the signed-in user's avatar (or their
 * initials) beside their name and email.
 *
 * Everything it needs is already on the page — `window.SECURITY.bootstrap`,
 * written by www/security-dashboard-v2.html — so it costs no request. Collapsed to the
 * icon rail the name and email hide and the avatar centres, which is why the
 * whole chip carries a `title`: the avatar alone does not say whose it is.
 */
export function SidebarUser() {
  const { user, full_name, user_image } = bootstrap();
  const displayName = full_name || user || "User";
  const initials = initialsOf(displayName);

  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <div
          title={user ? `${displayName} · ${user}` : displayName}
          className={
            // The avatar sits concentric with the BOTTOM corner, as the mark does
            // with the top one: centre at (R, R) from that corner, so the gap
            // to the border is R - r in every direction. The footer pads 0.8rem
            // for the rows above; this pulls back to the 7.14px the avatar wants.
            "flex items-center gap-2 -ml-[0.35rem] -mb-[0.35rem] " +
            "group-data-[collapsible=icon]:flex-col group-data-[collapsible=icon]:items-start "
            + "group-data-[collapsible=icon]:gap-1 " +
            "group-data-[collapsible=icon]:py-0"
          }
        >
          <Avatar className="h-[2.7rem] w-[2.7rem] shrink-0 group-data-[collapsible=icon]:h-[2.7rem] group-data-[collapsible=icon]:w-[2.7rem]">
            {user_image ? <AvatarImage src={user_image} alt={displayName} /> : null}
            <AvatarFallback>{initials}</AvatarFallback>
          </Avatar>
          <div
            className={
              "grid min-w-0 flex-1 text-left text-xs leading-tight " +
              "group-data-[collapsible=icon]:hidden"
            }
          >
            <span className="truncate font-medium">{displayName}</span>
            <span className="truncate text-[0.7rem] text-muted-foreground">{user}</span>
          </div>
        </div>
      </SidebarMenuItem>
    </SidebarMenu>
  );
}
