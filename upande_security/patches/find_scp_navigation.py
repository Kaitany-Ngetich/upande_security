import frappe


def execute():
    matches = []

    for row in frappe.get_all(
        "Custom HTML Block",
        fields=["name"],
        order_by="name asc",
    ):
        doc = frappe.get_doc("Custom HTML Block", row.name)

        parts = []
        field_sizes = {}

        for fieldname in ("html", "style", "css", "script"):
            if doc.meta.has_field(fieldname):
                value = doc.get(fieldname) or ""
                parts.append(value)
                field_sizes[fieldname] = len(value)

        combined = "\n".join(parts).lower()
        block_name = (doc.name or "").lower()

        terms = [
            "scp navigation",
            "scp-dash-v2",
            "scp-tabs",
            "scp-tab-btn",
            "scp-nav",
            "upande scp",
        ]

        if any(term in block_name or term in combined for term in terms):
            matches.append({
                "name": doc.name,
                "sizes": field_sizes,
            })

    return matches
