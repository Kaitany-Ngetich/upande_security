import json
import os

import frappe


def execute():
    output_dir = "/tmp/security-workspace-reference"
    os.makedirs(output_dir, exist_ok=True)

    block_names = [
        "SCP Navigation",
        "Security Navigation",
    ]

    manifest = {}

    for block_name in block_names:
        if not frappe.db.exists("Custom HTML Block", block_name):
            print(f"NOT FOUND: {block_name}")
            continue

        block = frappe.get_doc("Custom HTML Block", block_name)

        safe_name = (
            block_name.lower()
            .replace(" ", "_")
            .replace("/", "_")
        )

        manifest[block_name] = {
            "name": block.name,
            "fields": {},
        }

        for fieldname in ("html", "style", "css", "script"):
            if not block.meta.has_field(fieldname):
                continue

            value = block.get(fieldname) or ""
            extension = {
                "html": "html",
                "style": "css",
                "css": "css",
                "script": "js",
            }[fieldname]

            filename = (
                f"{safe_name}_{fieldname}.{extension}"
            )
            filepath = os.path.join(output_dir, filename)

            with open(filepath, "w", encoding="utf-8") as file:
                file.write(value)

            manifest[block_name]["fields"][fieldname] = {
                "file": filepath,
                "characters": len(value),
                "lines": value.count("\n") + 1 if value else 0,
            }

            print(
                f"Exported {block_name}.{fieldname}: "
                f"{len(value)} characters -> {filepath}"
            )

    manifest_path = os.path.join(output_dir, "manifest.json")

    with open(manifest_path, "w", encoding="utf-8") as file:
        json.dump(manifest, file, indent=2)

    print(f"\nManifest: {manifest_path}")
    print("Workspace block export completed.")
