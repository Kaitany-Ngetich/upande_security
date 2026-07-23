import json

import frappe
from frappe.model.rename_doc import rename_doc


def execute():
    workspace_name = "Security"
    old_block_name = "Security"
    new_block_name = "Security Navigation"

    if not frappe.db.exists("Workspace", workspace_name):
        frappe.throw("Workspace 'Security' was not found.")

    old_exists = bool(
        frappe.db.exists("Custom HTML Block", old_block_name)
    )
    new_exists = bool(
        frappe.db.exists("Custom HTML Block", new_block_name)
    )

    print("\n=== CURRENT STATE ===")
    print("Workspace exists: True")
    print(f"{old_block_name} block exists: {old_exists}")
    print(f"{new_block_name} block exists: {new_exists}")

    # Rename the current block while preserving its HTML, CSS and JS.
    if old_exists and not new_exists:
        rename_doc(
            "Custom HTML Block",
            old_block_name,
            new_block_name,
            force=True,
            ignore_permissions=True,
        )

        block_name = new_block_name
        print(
            f"Renamed Custom HTML Block: "
            f"{old_block_name} -> {new_block_name}"
        )

    elif new_exists:
        block_name = new_block_name
        print(f"Using existing block: {new_block_name}")

    elif old_exists:
        block_name = old_block_name
        print(f"Using existing block: {old_block_name}")

    else:
        frappe.throw(
            "Neither 'Security' nor 'Security Navigation' "
            "Custom HTML Block exists."
        )

    workspace = frappe.get_doc("Workspace", workspace_name)

    # Associate the workspace with the app module.
    if workspace.meta.has_field("module"):
        workspace.module = "Upande Security"

    if workspace.meta.has_field("app"):
        workspace.app = "upande_security"

    workspace.icon = "quality-3"
    workspace.indicator_color = "purple"
    workspace.public = 1
    workspace.is_hidden = 0
    workspace.hide_custom = 0

    # Adopt the SCP-style single full-width custom block structure.
    workspace.content = json.dumps(
        [
            {
                "id": "securityNav0001",
                "type": "custom_block",
                "data": {
                    "custom_block_name": block_name,
                    "col": 12,
                },
            }
        ],
        separators=(",", ":"),
    )

    workspace.set("custom_blocks", [])
    workspace.append(
        "custom_blocks",
        {
            "custom_block_name": block_name,
            "label": block_name,
        },
    )

    workspace.save(ignore_permissions=True)
    frappe.db.commit()

    print("\n=== UPDATED WORKSPACE ===")
    print("Name:", workspace.name)
    print("Module:", workspace.get("module"))
    print("App:", workspace.get("app"))
    print("Icon:", workspace.icon)
    print("Indicator colour:", workspace.indicator_color)
    print("Content:", workspace.content)

    print("\n=== REGISTERED BLOCKS ===")
    for row in workspace.custom_blocks:
        print({
            "custom_block_name": row.custom_block_name,
            "label": row.label,
        })

    block = frappe.get_doc("Custom HTML Block", block_name)

    print("\n=== PRESERVED CUSTOM BLOCK CODE ===")
    for fieldname in ("html", "style", "css", "script"):
        if block.meta.has_field(fieldname):
            value = block.get(fieldname) or ""
            print(f"{fieldname}: {len(value)} characters")

    print("\nSecurity workspace structure updated successfully.")


def verify():
    workspace = frappe.get_doc("Workspace", "Security")

    blocks = [
        {
            "custom_block_name": row.custom_block_name,
            "label": row.label,
        }
        for row in workspace.custom_blocks
    ]

    return {
        "name": workspace.name,
        "module": workspace.get("module"),
        "app": workspace.get("app"),
        "icon": workspace.icon,
        "indicator_color": workspace.indicator_color,
        "content": workspace.content,
        "custom_blocks": blocks,
        "security_block_exists": bool(
            frappe.db.exists(
                "Custom HTML Block",
                "Security Navigation",
            )
        ),
    }
