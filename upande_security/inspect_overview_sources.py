from __future__ import annotations

import json

import frappe


LAYOUT_FIELDS = {
    "Section Break",
    "Column Break",
    "Tab Break",
    "HTML",
    "Heading",
}


def run():
    doctypes = frappe.get_all(
        "DocType",
        filters={
            "module": "Upande Security",
        },
        fields=[
            "name",
            "istable",
            "issingle",
            "is_submittable",
            "title_field",
        ],
        order_by="name asc",
        limit_page_length=500,
    )

    result = {}

    for doctype in doctypes:
        name = doctype.get("name")

        try:
            meta = frappe.get_meta(name)
        except Exception as error:
            result[name] = {
                "error": str(error),
            }
            continue

        fields = []

        for field in meta.fields:
            if field.fieldtype in LAYOUT_FIELDS:
                continue

            fields.append(
                {
                    "fieldname": field.fieldname,
                    "label": field.label,
                    "fieldtype": field.fieldtype,
                    "options": field.options,
                    "required": bool(field.reqd),
                    "read_only": bool(field.read_only),
                }
            )

        try:
            record_count = frappe.db.count(name)
        except Exception:
            record_count = None

        result[name] = {
            "istable": bool(doctype.get("istable")),
            "issingle": bool(doctype.get("issingle")),
            "is_submittable": bool(
                doctype.get("is_submittable")
            ),
            "title_field": doctype.get("title_field"),
            "record_count": record_count,
            "fields": fields,
        }

    return json.dumps(
        result,
        indent=2,
        default=str,
        ensure_ascii=False,
    )
