import re
from pathlib import Path

import frappe


def execute():
    block_name = "Security Navigation"

    if not frappe.db.exists("Custom HTML Block", block_name):
        frappe.throw(
            "Custom HTML Block 'Security Navigation' was not found."
        )

    block = frappe.get_doc("Custom HTML Block", block_name)
    original_html = block.get("html") or ""

    backup_path = Path(
        "/tmp/security_navigation_before_dashboard_removal.html"
    )
    backup_path.write_text(original_html, encoding="utf-8")

    # Remove the tile that points to the standalone Security Dashboard page.
    pattern = re.compile(
        r'''
        \s*
        <a\b
        (?=[^>]*class=["'][^"']*\bsecn-tile\b[^"']*["'])
        (?=[^>]*data-ref-name=["']security-dashboard["'])
        [^>]*>
        .*?
        </a>
        \s*
        ''',
        re.IGNORECASE | re.DOTALL | re.VERBOSE,
    )

    updated_html, removed = pattern.subn(
        "\n",
        original_html,
        count=1,
    )

    # Fallback in case the data-ref attribute was edited.
    if removed == 0:
        fallback = re.compile(
            r'''
            \s*
            <a\b
            (?=[^>]*class=["'][^"']*\bsecn-tile\b[^"']*["'])
            (?=[^>]*href=["']/app/security-dashboard["'])
            [^>]*>
            .*?
            </a>
            \s*
            ''',
            re.IGNORECASE | re.DOTALL | re.VERBOSE,
        )

        updated_html, removed = fallback.subn(
            "\n",
            original_html,
            count=1,
        )

    if removed == 0:
        frappe.throw(
            "The Security Dashboard tile was not found. "
            "No changes were made."
        )

    block.html = updated_html.strip()
    block.save(ignore_permissions=True)
    frappe.db.commit()

    print("\n=== DASHBOARD REMOVED FROM WORKSPACE ===")
    print("Custom block:", block.name)
    print("Tiles removed:", removed)
    print("Backup:", backup_path)
    print("Standalone dashboard: /app/security-dashboard")


def verify():
    block = frappe.get_doc(
        "Custom HTML Block",
        "Security Navigation",
    )

    html = block.get("html") or ""

    return {
        "custom_block": block.name,
        "dashboard_tile_present": (
            'data-ref-name="security-dashboard"' in html
            or 'href="/app/security-dashboard"' in html
        ),
        "dashboard_page_exists": bool(
            frappe.db.exists("Page", "security-dashboard")
        ),
        "dashboard_route": "/app/security-dashboard",
    }
