import json
from pathlib import Path

import frappe


SECURITY_HTML = r'''
<div class="secn">

  <div class="secn-title">Security Operations</div>

  <div class="secn-grid">

    <a
      class="secn-tile"
      data-roles=""
      data-ref-type="Page"
      data-ref-name="security-dashboard"
      href="/app/security-dashboard"
    >
      <span
        class="secn-ic"
        style="background:rgba(59,130,246,.13);color:#3b82f6"
      >
        <svg viewBox="0 0 24 24" fill="none"
          stroke="currentColor" stroke-width="2">
          <rect x="3" y="3" width="7" height="9"/>
          <rect x="14" y="3" width="7" height="5"/>
          <rect x="14" y="12" width="7" height="9"/>
          <rect x="3" y="16" width="7" height="5"/>
        </svg>
      </span>

      <span class="secn-tx">
        <span class="secn-lb">Overview</span>
        <span class="secn-sub">Security dashboard and KPIs</span>
      </span>
    </a>

    <a
      class="secn-tile"
      data-roles=""
      data-ref-type="DocType"
      data-ref-name="Visitor"
      href="/app/visitor"
    >
      <span
        class="secn-ic"
        style="background:rgba(34,197,94,.13);color:#16a34a"
      >
        <svg viewBox="0 0 24 24" fill="none"
          stroke="currentColor" stroke-width="2">
          <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/>
          <circle cx="9" cy="7" r="4"/>
          <polyline points="16 11 18 13 22 9"/>
        </svg>
      </span>

      <span class="secn-tx">
        <span class="secn-lb">Visitors</span>
        <span class="secn-sub">Visitor registration and access</span>
      </span>
    </a>

    <a
      class="secn-tile"
      data-roles=""
      data-ref-type="DocType"
      data-ref-name="Appointment"
      href="/app/appointment"
    >
      <span
        class="secn-ic"
        style="background:rgba(139,92,246,.13);color:#7c53e0"
      >
        <svg viewBox="0 0 24 24" fill="none"
          stroke="currentColor" stroke-width="2">
          <rect x="3" y="4" width="18" height="17" rx="2"/>
          <line x1="16" y1="2" x2="16" y2="6"/>
          <line x1="8" y1="2" x2="8" y2="6"/>
          <line x1="3" y1="10" x2="21" y2="10"/>
          <polyline points="9 16 11 18 15 14"/>
        </svg>
      </span>

      <span class="secn-tx">
        <span class="secn-lb">Appointments</span>
        <span class="secn-sub">Expected visitors and meetings</span>
      </span>
    </a>

    <a
      class="secn-tile"
      data-roles=""
      data-ref-type="DocType"
      data-ref-name="Contractor"
      href="/app/contractor"
    >
      <span
        class="secn-ic"
        style="background:rgba(245,158,11,.13);color:#d97706"
      >
        <svg viewBox="0 0 24 24" fill="none"
          stroke="currentColor" stroke-width="2">
          <rect x="3" y="7" width="18" height="13" rx="2"/>
          <path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
          <line x1="3" y1="12" x2="21" y2="12"/>
          <path d="M10 12v2h4v-2"/>
        </svg>
      </span>

      <span class="secn-tx">
        <span class="secn-lb">Contractors</span>
        <span class="secn-sub">Contractor access and records</span>
      </span>
    </a>

    <a
      class="secn-tile"
      data-roles=""
      data-ref-type="DocType"
      data-ref-name="Vehicle"
      href="/app/vehicle"
    >
      <span
        class="secn-ic"
        style="background:rgba(6,182,212,.13);color:#0891b2"
      >
        <svg viewBox="0 0 24 24" fill="none"
          stroke="currentColor" stroke-width="2">
          <path d="M3 11l2-5h14l2 5"/>
          <rect x="3" y="11" width="18" height="7" rx="2"/>
          <circle cx="7" cy="18" r="2"/>
          <circle cx="17" cy="18" r="2"/>
          <line x1="5" y1="14" x2="7" y2="14"/>
          <line x1="17" y1="14" x2="19" y2="14"/>
        </svg>
      </span>

      <span class="secn-tx">
        <span class="secn-lb">Vehicles</span>
        <span class="secn-sub">Registered and authorised vehicles</span>
      </span>
    </a>

    <a
      class="secn-tile"
      data-roles=""
      data-ref-type="DocType"
      data-ref-name="Patrol"
      href="/app/patrol"
    >
      <span
        class="secn-ic"
        style="background:rgba(16,185,129,.13);color:#059669"
      >
        <svg viewBox="0 0 24 24" fill="none"
          stroke="currentColor" stroke-width="2">
          <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/>
          <circle cx="12" cy="10" r="3"/>
        </svg>
      </span>

      <span class="secn-tx">
        <span class="secn-lb">Patrols</span>
        <span class="secn-sub">Patrol activity and monitoring</span>
      </span>
    </a>

    <a
      class="secn-tile"
      data-roles=""
      data-ref-type="DocType"
      data-ref-name="Incident"
      href="/app/incident"
    >
      <span
        class="secn-ic"
        style="background:rgba(239,68,68,.13);color:#dc2626"
      >
        <svg viewBox="0 0 24 24" fill="none"
          stroke="currentColor" stroke-width="2">
          <path d="M10.3 2.9L1.8 17a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 2.9a2 2 0 0 0-3.4 0z"/>
          <line x1="12" y1="9" x2="12" y2="13"/>
          <line x1="12" y1="17" x2="12.01" y2="17"/>
        </svg>
      </span>

      <span class="secn-tx">
        <span class="secn-lb">Incidents</span>
        <span class="secn-sub">Report and manage incidents</span>
      </span>
    </a>

  </div>

  <div class="secn-title secn-title-admin">
    Security Administration
  </div>

  <div class="secn-grid">

    <a
      class="secn-tile"
      data-roles=""
      data-ref-type="DocType"
      data-ref-name="Security Guard"
      href="/app/security-guard"
    >
      <span
        class="secn-ic"
        style="background:rgba(37,99,235,.13);color:#2563eb"
      >
        <svg viewBox="0 0 24 24" fill="none"
          stroke="currentColor" stroke-width="2">
          <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
          <path d="M9 12l2 2 4-4"/>
        </svg>
      </span>

      <span class="secn-tx">
        <span class="secn-lb">Security Guards</span>
        <span class="secn-sub">Guard profiles and deployment</span>
      </span>
    </a>

    <a
      class="secn-tile"
      data-roles=""
      data-ref-type="DocType"
      data-ref-name="Security Guard Shift Assignment"
      href="/app/security-guard-shift-assignment"
    >
      <span
        class="secn-ic"
        style="background:rgba(168,85,247,.13);color:#9333ea"
      >
        <svg viewBox="0 0 24 24" fill="none"
          stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="9"/>
          <polyline points="12 7 12 12 16 14"/>
        </svg>
      </span>

      <span class="secn-tx">
        <span class="secn-lb">Shift Assignments</span>
        <span class="secn-sub">Guard shifts and duty allocation</span>
      </span>
    </a>

  </div>

</div>
'''


SECURITY_STYLE = r'''
.secn {
  padding: 4px 2px;
  font-family:
    'Poppins',
    var(--font-stack),
    'Inter',
    sans-serif;
}

.secn-title {
  margin: 0 0 10px 2px;
  color: #8a8f98;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: .06em;
  text-transform: uppercase;
}

.secn-title-admin {
  margin-top: 18px;
}

.secn-grid {
  display: grid;
  grid-template-columns:
    repeat(auto-fill, minmax(190px, 1fr));
  gap: 10px;
}

.secn-tile {
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 13px 15px;
  border: 1px solid var(--border-color, #e2e4e9);
  border-radius: 10px;
  background: var(--card-bg, #fff);
  color: inherit;
  text-decoration: none;
  transition:
    box-shadow .18s ease,
    transform .18s ease;
}

.secn-tile:hover {
  box-shadow: 0 2px 6px rgba(0, 0, 0, .06);
  transform: translateY(-1px);
  text-decoration: none;
}

.secn-tile:hover .secn-lb,
.secn-tile:hover .secn-sub {
  text-decoration: none;
}

.secn-ic {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border-radius: 9px;
  flex: 0 0 auto;
  color: inherit;
}

.secn-ic svg {
  width: 18px;
  height: 18px;
}

.secn-tx {
  display: flex;
  min-width: 0;
  flex-direction: column;
}

.secn-lb {
  display: block;
  font-size: 13.5px;
  font-weight: 600;
  line-height: 1.2;
}

.secn-sub {
  display: block;
  margin-top: 2px;
  color: #8a8f98;
  font-size: 11px;
  line-height: 1.3;
}

.secn-hide {
  display: none !important;
}

@media (max-width: 767px) {
  .secn-grid {
    grid-template-columns: 1fr;
  }
}
'''


SECURITY_SCRIPT = r'''
(function () {
  try {
    if (!document.querySelector('link[data-security-poppins]')) {
      var fontLink = document.createElement('link');
      fontLink.rel = 'stylesheet';
      fontLink.setAttribute('data-security-poppins', '1');
      fontLink.href =
        'https://fonts.googleapis.com/css2?family=Poppins:' +
        'wght@400;500;600;700&display=swap';

      document.head.appendChild(fontLink);
    }
  } catch (error) {
    console.warn('Security font loading failed:', error);
  }

  var roles =
    (window.frappe && frappe.user_roles) || [];

  var isAdministrator =
    roles.indexOf('System Manager') >= 0 ||
    roles.indexOf('Administrator') >= 0 ||
    (
      window.frappe &&
      frappe.user &&
      frappe.user.name === 'Administrator'
    );

  var tiles =
    root_element.querySelectorAll('.secn-tile');

  tiles.forEach(function (tile) {
    var requiredRoles =
      (tile.getAttribute('data-roles') || '')
        .split(',')
        .map(function (role) {
          return role.trim();
        })
        .filter(Boolean);

    if (
      requiredRoles.length &&
      !isAdministrator &&
      !requiredRoles.some(function (role) {
        return roles.indexOf(role) >= 0;
      })
    ) {
      tile.classList.add('secn-hide');
      return;
    }

    var referenceType =
      tile.getAttribute('data-ref-type');

    var referenceName =
      tile.getAttribute('data-ref-name');

    if (
      !referenceType ||
      !referenceName ||
      !window.frappe ||
      !frappe.db ||
      !frappe.db.exists
    ) {
      return;
    }

    frappe.db.exists(referenceType, referenceName)
      .then(function (exists) {
        if (!exists) {
          tile.classList.add('secn-hide');
        }
      })
      .catch(function () {
        /*
         * Keep the tile visible when existence checking
         * is unavailable. Frappe permissions will still
         * control access to the destination.
         */
      });
  });
})();
'''


def execute():
    block_name = "Security Navigation"

    if not frappe.db.exists("Custom HTML Block", block_name):
        frappe.throw(
            "Custom HTML Block 'Security Navigation' does not exist."
        )

    block = frappe.get_doc("Custom HTML Block", block_name)

    backup = {
        "name": block.name,
        "html": block.get("html") or "",
        "style": block.get("style") or "",
        "script": block.get("script") or "",
    }

    backup_path = Path(
        "/tmp/security_navigation_before_redesign.json"
    )

    backup_path.write_text(
        json.dumps(backup, indent=2),
        encoding="utf-8",
    )

    block.html = SECURITY_HTML.strip()
    block.style = SECURITY_STYLE.strip()
    block.script = SECURITY_SCRIPT.strip()

    block.save(ignore_permissions=True)
    frappe.db.commit()

    print("\n=== SECURITY NAVIGATION REDESIGNED ===")
    print("Block:", block.name)
    print("HTML characters:", len(block.html or ""))
    print("Style characters:", len(block.style or ""))
    print("Script characters:", len(block.script or ""))
    print("Previous version:", backup_path)


def verify():
    block = frappe.get_doc(
        "Custom HTML Block",
        "Security Navigation",
    )

    workspace = frappe.get_doc("Workspace", "Security")

    return {
        "workspace": workspace.name,
        "workspace_module": workspace.get("module"),
        "workspace_app": workspace.get("app"),
        "custom_block": block.name,
        "html_characters": len(block.get("html") or ""),
        "style_characters": len(block.get("style") or ""),
        "script_characters": len(block.get("script") or ""),
        "uses_security_namespace": (
            'class="secn"' in (block.get("html") or "")
        ),
        "workspace_uses_block": (
            "Security Navigation" in
            (workspace.get("content") or "")
        ),
    }
