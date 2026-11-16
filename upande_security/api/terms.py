# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

"""The words an organisation uses for its places.

Security was built for farms, but nothing in it depends on a site being a
farm: a gate, a patrol, a boundary or a shift works the same at a factory, an
office or a hotel. The data model keeps its names (the Farm doctype from
upande_core, `farm` fields, Security Block); only what people READ changes.

Security Ops Settings > Words Used (Beta) holds them, and only counts while
its "Use Custom Words" switch is on; off, everything says Farm and Block:
  site_label / site_label_plural   Farm / Farms   (Site, Branch, Premises ...)
  area_label / area_label_plural   Block / Blocks (Zone, Wing, Floor ...)

get_terms() feeds the Security Dashboard (v2 bootstrap) and anything printed or
sent. apply_desk_labels() relabels the Desk fields that link a Farm or a Security
Block with label-only Property Setters - fieldnames, links and data are untouched,
and setting the words back to Farm / Block removes the relabelling again.
"""

import re

import frappe

DEFAULTS = {"site_label": "Farm", "site_label_plural": "Farms", "area_label": "Block", "area_label_plural": "Blocks"}
MODULE = "Upande Security"
# Custom fields this app adds to other apps' doctypes that link a Farm.
CUSTOM_FARM_FIELDS = (
	("Appointment", "custom_meet_with_farm"),
	("Attendance", "custom_farm"),
	("Employee", "custom_farm"),
)


FLAG = "use_custom_words"


def _effective(values):
	"""The words in effect for a settings doc / dict: the defaults while the
	switch is off, otherwise each word falling back to its default when blank."""
	on = bool(values and frappe.utils.cint(values.get(FLAG)))
	return {k: (((values.get(k) if on else "") or "").strip() or v) for k, v in DEFAULTS.items()}


def get_terms():
	"""The four words currently in effect."""
	values = frappe.db.get_singles_dict("Security Ops Settings")
	return _effective(values)


def _relabel(label, terms):
	"""'From Farm' -> 'From Site'; 'Blocks' -> 'Zones'. Whole words only, case kept."""
	swaps = (
		("Farms", terms["site_label_plural"]), ("Farm", terms["site_label"]),
		("farms", terms["site_label_plural"].lower()), ("farm", terms["site_label"].lower()),
		("Blocks", terms["area_label_plural"]), ("Block", terms["area_label"]),
		("blocks", terms["area_label_plural"].lower()), ("block", terms["area_label"].lower()),
	)
	for word, new in swaps:
		label = re.sub(rf"\b{word}\b", new, label)
	return label


def _target_fields():
	"""(doctype, fieldname, original label, is_custom) for every field to relabel."""
	rows = frappe.db.sql(
		"""
		SELECT df.parent, df.fieldname, df.label
		FROM `tabDocField` df JOIN `tabDocType` dt ON dt.name = df.parent
		WHERE dt.module = %s AND df.fieldtype IN ('Link', 'Table MultiSelect')
		  AND df.options IN ('Farm', 'Security Block') AND IFNULL(df.label, '') != ''
		""",
		MODULE,
	)
	out = [(dt, fn, label, False) for dt, fn, label in rows]
	for dt, fn in CUSTOM_FARM_FIELDS:
		label = frappe.db.get_value("Custom Field", {"dt": dt, "fieldname": fn}, "label")
		if label:
			out.append((dt, fn, label, True))
	return out


def apply_desk_labels(terms=None):
	"""Relabel the Farm / Security Block fields in Desk to the chosen words.
	Idempotent; with the default words every override it made is removed.
	Labels changed by hand in Customize Form (is_system_generated = 0) are
	never touched, so a live site's own customisations survive."""
	from frappe.custom.doctype.property_setter.property_setter import make_property_setter

	terms = terms or get_terms()
	is_default = all(terms[k] == v for k, v in DEFAULTS.items())
	changed = skipped = 0
	for dt, fn, original, _custom in _target_fields():
		existing = frappe.db.get_value(
			"Property Setter",
			{"doc_type": dt, "field_name": fn, "property": "label"},
			["name", "value", "is_system_generated"],
			as_dict=True,
		)
		if existing and not existing.is_system_generated:
			# Relabelled by hand in Customize Form: the site's own choice wins.
			skipped += 1
			continue
		if is_default:
			if existing:
				frappe.delete_doc("Property Setter", existing.name, ignore_permissions=True, force=True)
				changed += 1
			continue
		label = _relabel(original, terms)
		if label == original:
			if existing:
				frappe.delete_doc("Property Setter", existing.name, ignore_permissions=True, force=True)
				changed += 1
			continue
		if existing and existing.value == label:
			continue
		make_property_setter(dt, fn, "label", label, "Data", validate_fields_for_doctype=False)
		changed += 1
	for dt in {t[0] for t in _target_fields()}:
		frappe.clear_cache(doctype=dt)
	return changed


def on_settings_update(doc, method=None):
	"""Security Ops Settings saved: relabel Desk if the words changed."""
	terms = _effective(doc)
	# Compare the words in effect, not the raw values: right after a migrate the
	# new fields are blank, and the first save fills them with Farm / Block -
	# that is no change and must not touch Desk. Switching off reverts Desk.
	if _effective(doc.get_doc_before_save()) == terms:
		return
	apply_desk_labels(terms)
