import frappe


def guard_filters(user, full_name=None):
	"""Filters that find the Security Guard behind a login.

	The guard's own User Account link wins. Matching on the full name is
	only the fallback for guards with no linked login: names are typed
	twice, once on the User and once on the guard, and drift apart
	("Stephen Mutinda" / "Steve Mutinda"), which left a linked guard with
	no farm and an empty gate app."""
	if user:
		name = frappe.db.get_value("Security Guard", {"user": user}, "name")
		if name:
			return {"name": name}
	if full_name is None:
		full_name = frappe.db.get_value("User", user, "full_name") if user else None
	return {"full_name": full_name or ""}
