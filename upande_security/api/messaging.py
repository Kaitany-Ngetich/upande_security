# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Security messages inside the gate app: supervisor to guard, guard to
supervisor, guard to guard, and a supervisor to every guard at a farm.

A Security Conversation holds its members (with when each last read it);
each Security Message belongs to one. Every call works only for members of
the conversation, and people can only start conversations with people in
their own company (a Security Head's company and farm User Permissions, a
guard's own company). Each message is pushed to the other members' phones
(data.type "security_message"), and tapping it opens the conversation in
the app.

Everything is kept on the server, so a Security Head can review it in Desk.
"""

import frappe
from frappe import _

from upande_security.api.guard_lookup import guard_filters

SUPERVISOR_ROLES = ("Security Head", "Security Supervisor", "Security Manager", "System Manager")
GUARD_ROLES = ("Security Guard", "Gate Guard")
MESSAGE_CHANNEL_ID = "security-messages"
MAX_BODY = 2000
PAGE = 50


# --- who is who -------------------------------------------------------------

def _enabled(users):
	"""Only logins that exist and are enabled."""
	users = [u for u in dict.fromkeys(users) if u]
	if not users:
		return []
	ok = set(frappe.get_all("User", filters={"name": ["in", users], "enabled": 1}, pluck="name"))
	return [u for u in users if u in ok]


def _name_of(user):
	return frappe.utils.get_fullname(user) or user


def _is_supervisor(user=None):
	return bool(set(SUPERVISOR_ROLES) & set(frappe.get_roles(user or frappe.session.user)))


def _my_scope(user):
	"""(companies, farms) the user belongs to or oversees; (None, None) for
	someone not limited at all (System Manager, an unrestricted head)."""
	roles = set(frappe.get_roles(user))
	if "System Manager" in roles or user == "Administrator":
		return None, None
	perms = frappe.get_all("User Permission", filters={"user": user, "allow": ["in", ["Company", "Farm"]]},
		fields=["allow", "for_value"])
	companies = {p.for_value for p in perms if p.allow == "Company"}
	farms = {p.for_value for p in perms if p.allow == "Farm"}
	emp = frappe.db.get_value("Employee", {"user_id": user}, ["company", "custom_farm"], as_dict=True)
	if emp:
		if emp.company:
			companies.add(emp.company)
		if emp.custom_farm:
			farms.add(emp.custom_farm)
	full = frappe.db.get_value("User", user, "full_name") or ""
	guard = frappe.db.get_value("Security Guard", guard_filters(user, full), ["company", "farm"], as_dict=True)
	if guard:
		if guard.company:
			companies.add(guard.company)
		if guard.farm:
			farms.add(guard.farm)
	for f in farms:
		c = frappe.db.get_value("Farm", f, "company")
		if c:
			companies.add(c)
	if not companies and not farms and ({"Security Head", "Security Manager"} & roles):
		return None, None
	return companies, farms


def _contacts(user):
	"""[{user, name, kind, farm}] this user may start a conversation with:
	security guards and supervisors in the same company (anyone, for an
	unrestricted user). Never themselves."""
	companies, _farms = _my_scope(user)
	out = {}
	guard_filters_ = {"status": "Active", "user": ["is", "set"]}
	if companies is not None:
		guard_filters_["company"] = ["in", list(companies) or ["__none__"]]
	guards = frappe.get_all("Security Guard", filters=guard_filters_, fields=["user", "full_name", "farm"])
	live = set(_enabled([g.user for g in guards]))
	for g in guards:
		if g.user in live:
			out[g.user] = {"user": g.user, "name": g.full_name or g.user, "kind": "Guard", "farm": g.farm}
	role_users = frappe.get_all("Has Role", filters={"parenttype": "User", "role": ["in", list(SUPERVISOR_ROLES[:3]) + list(GUARD_ROLES)]},
		fields=["parent", "role"])
	by_user = {}
	for r in role_users:
		by_user.setdefault(r.parent, set()).add(r.role)
	users = frappe.get_all("User", filters={"name": ["in", list(by_user) or ["__none__"]], "enabled": 1, "user_type": "System User"},
		fields=["name", "full_name"])
	for u in users:
		if u.name in out or u.name in ("Administrator", "Guest"):
			continue
		roles = by_user.get(u.name, set())
		if companies is not None:
			theirs, _f = _my_scope(u.name)
			if theirs is not None and not (theirs & companies):
				continue
		kind = "Supervisor" if roles & set(SUPERVISOR_ROLES) else "Guard"
		emp_farm = frappe.db.get_value("Employee", {"user_id": u.name}, "custom_farm")
		out[u.name] = {"user": u.name, "name": u.full_name or u.name, "kind": kind, "farm": emp_farm}
	out.pop(user, None)
	return sorted(out.values(), key=lambda c: (c["kind"] != "Supervisor", (c["name"] or "").lower()))


# --- conversations ----------------------------------------------------------

def _conversation(name):
	"""The conversation, if the caller is a member; throws otherwise."""
	if not name or not frappe.db.exists("Security Conversation", name):
		frappe.throw(_("Conversation not found."))
	doc = frappe.get_doc("Security Conversation", name)
	if not any(m.user == frappe.session.user for m in doc.members):
		frappe.throw(_("You are not in this conversation."), frappe.PermissionError)
	return doc


def _title_for(doc, user):
	if doc.conversation_type == "Group":
		return doc.title or _("Group")
	others = [m.member_name or m.user for m in doc.members if m.user != user]
	return ", ".join(others) or doc.title or _("Conversation")


def _direct_between(a, b):
	rows = frappe.db.sql(
		"""
		SELECT c.name FROM `tabSecurity Conversation` c
		JOIN `tabSecurity Conversation Member` m1 ON m1.parent = c.name AND m1.user = %(a)s
		JOIN `tabSecurity Conversation Member` m2 ON m2.parent = c.name AND m2.user = %(b)s
		WHERE c.conversation_type = 'Direct'
		  AND (SELECT COUNT(*) FROM `tabSecurity Conversation Member` m WHERE m.parent = c.name) = 2
		LIMIT 1
		""",
		{"a": a, "b": b},
	)
	return rows[0][0] if rows else None


def _new_conversation(kind, members, title=None, farm=None):
	doc = frappe.new_doc("Security Conversation")
	doc.conversation_type = kind
	doc.title = title
	doc.farm = farm
	doc.created_by = frappe.session.user
	for u in dict.fromkeys(members):
		doc.append("members", {"user": u, "member_name": _name_of(u)})
	doc.insert(ignore_permissions=True)
	return doc


def _unread(conversation, user, last_read_at):
	params = {"c": conversation, "u": user}
	since = ""
	if last_read_at:
		since = " AND sent_at > %(since)s"
		params["since"] = last_read_at
	return frappe.db.sql(
		f"SELECT COUNT(*) FROM `tabSecurity Message` WHERE conversation = %(c)s AND sender != %(u)s{since}", params
	)[0][0]


@frappe.whitelist()
def list_conversations():
	"""The caller's conversations, newest activity first, each with its
	title, last message and unread count."""
	user = frappe.session.user
	names = frappe.get_all("Security Conversation Member", filters={"parenttype": "Security Conversation", "user": user},
		fields=["parent", "last_read_at"])
	if not names:
		return []
	read_at = {n.parent: n.last_read_at for n in names}
	convs = frappe.get_all("Security Conversation", filters={"name": ["in", list(read_at)]},
		fields=["name", "title", "conversation_type", "farm", "last_message", "last_message_at"],
		order_by="last_message_at desc", limit_page_length=0)
	out = []
	for c in convs:
		doc = frappe.get_doc("Security Conversation", c.name)
		out.append({
			"name": c.name,
			"title": _title_for(doc, user),
			"type": c.conversation_type,
			"farm": c.farm,
			"members": len(doc.members),
			"last_message": c.last_message or "",
			"last_message_at": str(c.last_message_at) if c.last_message_at else None,
			"unread": _unread(c.name, user, read_at.get(c.name)),
		})
	return out


@frappe.whitelist()
def unread_messages():
	"""Total unread messages for the caller - the app's badge."""
	user = frappe.session.user
	rows = frappe.get_all("Security Conversation Member", filters={"parenttype": "Security Conversation", "user": user},
		fields=["parent", "last_read_at"])
	return {"unread": sum(_unread(r.parent, user, r.last_read_at) for r in rows)}


def _mark_read(doc, user):
	now = frappe.utils.now_datetime()
	for m in doc.members:
		if m.user == user:
			frappe.db.set_value("Security Conversation Member", m.name, "last_read_at", now, update_modified=False)


@frappe.whitelist()
def get_messages(conversation, before=None, limit=PAGE):
	"""Messages of a conversation, oldest first (the newest `limit`, or
	those before `before` for scrolling back), and marks it read."""
	user = frappe.session.user
	doc = _conversation(conversation)
	filters = {"conversation": conversation}
	if before:
		filters["sent_at"] = ["<", before]
	rows = frappe.get_all("Security Message", filters=filters,
		fields=["name", "sender", "sender_name", "body", "sent_at"],
		order_by="sent_at desc", limit_page_length=min(int(limit or PAGE), 200))
	rows.reverse()
	_mark_read(doc, user)
	frappe.db.commit()
	return {
		"conversation": conversation,
		"title": _title_for(doc, user),
		"type": doc.conversation_type,
		"members": [{"user": m.user, "name": m.member_name or m.user} for m in doc.members],
		"messages": [
			{"name": r.name, "sender": r.sender, "sender_name": r.sender_name, "body": r.body,
				"sent_at": str(r.sent_at), "mine": r.sender == user}
			for r in rows
		],
	}


@frappe.whitelist()
def mark_conversation_read(conversation):
	_mark_read(_conversation(conversation), frappe.session.user)
	frappe.db.commit()
	return {"ok": True}


@frappe.whitelist()
def message_contacts(query=None):
	"""People the caller may message, filtered by name when query is given."""
	q = (query or "").strip().lower()
	people = _contacts(frappe.session.user)
	if q:
		people = [p for p in people if q in (p["name"] or "").lower() or q in (p.get("farm") or "").lower()]
	return people[:100]


@frappe.whitelist(methods=["POST"])
def send_message(body, conversation=None, to=None):
	"""Send `body` to a conversation, or start one: `to` is one user (a
	direct conversation, reused if it exists) or a list of users (a new
	group). Pushes it to everyone else in the conversation."""
	user = frappe.session.user
	body = (body or "").strip()
	if not body:
		frappe.throw(_("Type a message first."))
	body = body[:MAX_BODY]
	if conversation:
		doc = _conversation(conversation)
	else:
		targets = frappe.parse_json(to) if isinstance(to, str) and to.strip().startswith("[") else to
		targets = [t for t in (targets if isinstance(targets, list) else [targets]) if t and t != user]
		if not targets:
			frappe.throw(_("Pick who to send it to."))
		allowed = {c["user"] for c in _contacts(user)}
		outside = [t for t in targets if t not in allowed]
		if outside:
			frappe.throw(_("You cannot message {0}.").format(", ".join(_name_of(t) for t in outside)))
		if len(targets) == 1:
			existing = _direct_between(user, targets[0])
			doc = frappe.get_doc("Security Conversation", existing) if existing else _new_conversation("Direct", [user, targets[0]])
		else:
			doc = _new_conversation("Group", [user] + targets, title=", ".join(_name_of(t) for t in targets[:3]))
	now = frappe.utils.now_datetime()
	msg = frappe.get_doc({
		"doctype": "Security Message",
		"conversation": doc.name,
		"sender": user,
		"sender_name": _name_of(user),
		"body": body,
		"sent_at": now,
	}).insert(ignore_permissions=True)
	frappe.db.set_value("Security Conversation", doc.name, {"last_message": body[:140], "last_message_at": now},
		update_modified=False)
	_mark_read(doc, user)
	frappe.enqueue(
		"upande_security.api.messaging.push_message",
		queue="short",
		enqueue_after_commit=True,
		message=msg.name,
	)
	return {
		"conversation": doc.name,
		"message": {"name": msg.name, "sender": user, "sender_name": msg.sender_name, "body": body,
			"sent_at": str(now), "mine": True},
	}


@frappe.whitelist(methods=["POST"])
def message_farm_guards(farm, body=None):
	"""A supervisor's group with every active guard at a farm (created once,
	new guards added as they join); sends `body` to it when given."""
	user = frappe.session.user
	if not _is_supervisor(user):
		frappe.throw(_("Only supervisors can message every guard at a farm."), frappe.PermissionError)
	companies, farms = _my_scope(user)
	farm_company = frappe.db.get_value("Farm", farm, "company")
	if companies is not None and farm not in (farms or set()) and farm_company not in companies:
		frappe.throw(_("{0} is not one of your farms.").format(farm), frappe.PermissionError)
	guards = _enabled(frappe.get_all("Security Guard", filters={"status": "Active", "farm": farm, "user": ["is", "set"]}, pluck="user"))
	existing = frappe.db.get_value("Security Conversation", {"conversation_type": "Group", "farm": farm}, "name")
	if existing:
		doc = frappe.get_doc("Security Conversation", existing)
		have = {m.user for m in doc.members}
		for u in [user] + guards:
			if u not in have:
				doc.append("members", {"user": u, "member_name": _name_of(u)})
		doc.save(ignore_permissions=True)
	else:
		doc = _new_conversation("Group", [user] + guards, title=_("{0} guards").format(farm), farm=farm)
	if body and body.strip():
		return send_message(body, conversation=doc.name)
	return {"conversation": doc.name}


def push_message(message):
	"""Background: push a new message to every other member's phone."""
	from upande_security.api.notifications import _resolve_owner_push_token, _send_expo_push

	msg = frappe.get_doc("Security Message", message)
	conv = frappe.get_doc("Security Conversation", msg.conversation)
	title = msg.sender_name if conv.conversation_type == "Direct" else f"{msg.sender_name} · {conv.title}"
	pushes = []
	for m in conv.members:
		if m.user == msg.sender:
			continue
		token = _resolve_owner_push_token(m.user)
		if token:
			pushes.append({
				"to": token,
				"sound": "default",
				"priority": "high",
				"title": title,
				"body": msg.body[:180],
				"channelId": MESSAGE_CHANNEL_ID,
				"data": {"type": "security_message", "conversation": conv.name, "sender": msg.sender_name},
			})
	for i in range(0, len(pushes), 100):
		_send_expo_push(pushes[i:i + 100])
