# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Reliever suggestions and picked covers - see api/relievers.py and
toggle_guard_day(cover_guard=...) in api/shift_schedule.py.

Every test runs on its own farm, company and guards inside one transaction
that is rolled back; toggle_guard_day's own commits are turned off.
"""

import datetime
import unittest
from unittest.mock import patch

import frappe
from frappe.utils import add_days, getdate

from upande_security.api import relievers
from upande_security.api.shift_schedule import toggle_guard_day

FARM = "_Test Relief Farm"
OTHER_FARM = "_Test Relief Farm 2"
COMPANY = "_Test Relief Co"
DAY = getdate("2026-10-15")  # in the past, so the 60 days of history end here
FIRST = ("06:00:00", "14:00:00")
SECOND = ("14:00:00", "22:00:00")
THIRD = ("22:00:00", "06:00:00")
NIGHT = ("17:00:00", "06:30:00")


def _td(t):
	h, m, s = (int(x) for x in t.split(":"))
	return datetime.timedelta(hours=h, minutes=m, seconds=s)


class RelieverTestCase(unittest.TestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._commit = patch.object(frappe.db, "commit", lambda *a, **k: None)
		self._commit.start()
		self._n = 0
		for farm in (FARM, OTHER_FARM):
			frappe.get_doc({"doctype": "Farm", "name": farm, "farm": farm, "company": COMPANY}).db_insert()
		self.off = self.guard("Off Guard")
		self.addCleanup(self.cleanup)

	def cleanup(self):
		self._commit.stop()
		frappe.db.rollback()

	def guard(self, full_name, company=COMPANY, farm=FARM, **kw):
		self._n += 1
		name = "_TST-REL-%02d" % self._n
		doc = frappe.get_doc(
			{
				"doctype": "Security Guard",
				"name": name,
				"first_name": full_name,
				"full_name": full_name,
				"company": company,
				"farm": farm,
				"status": "Active",
				"gender": "Male",
				**kw,
			}
		)
		doc.db_insert()
		return name

	def shift(self, guard, day, times, farm=FARM, shift_type="First", end_date=None, status="Ended", covering_for=None):
		self._n += 1
		frappe.get_doc(
			{
				"doctype": "Security Guard Shift Assignment",
				"name": "_TST-RELSA-%04d" % self._n,
				"security_guard": "External Guard",
				"external_guard": guard,
				"farm": farm,
				"shift_type": shift_type,
				"start_date": getdate(day),
				"end_date": getdate(end_date or day),
				"start_time": _td(times[0]),
				"end_time": _td(times[1]),
				"status": status,
				"covering_for": covering_for,
			}
		).db_insert()

	def rank(self, shift_type="First", times=FIRST, **kw):
		return relievers.rank_relievers(
			self.off, DAY, farm=FARM, shift_type=shift_type, start_time=times[0], end_time=times[1], **kw
		)

	def by_guard(self, result):
		return {c["guard"]: c for c in result.suggestions}


class TestAvailability(RelieverTestCase):
	def test_free_guard_is_available(self):
		g = self.guard("Free")
		c = self.by_guard(self.rank())[g]
		self.assertEqual(c["available"], 1)
		self.assertIsNone(c["busy_reason"])

	def test_off_guard_and_other_company_are_not_candidates(self):
		other = self.guard("Elsewhere", company="_Test Other Co")
		ids = self.by_guard(self.rank())
		self.assertNotIn(self.off, ids)
		self.assertNotIn(other, ids)

	def test_overnight_from_day_before_stored_same_date_blocks(self):
		# Night 17:00-06:30 the day before, stored with end_date = start_date,
		# still runs into a 06:00 First shift.
		g = self.guard("Night Before")
		self.shift(g, add_days(DAY, -1), NIGHT, shift_type="Night", status="Scheduled")
		c = self.by_guard(self.rank())[g]
		self.assertEqual(c["available"], 0)
		self.assertIn("Night", c["busy_reason"])

	def test_third_shift_day_before_only_touches_first(self):
		# 22:00-06:00 ending exactly when the 06:00 cover starts is a handover.
		g = self.guard("Third Before")
		self.shift(g, add_days(DAY, -1), THIRD, shift_type="Third", status="Scheduled")
		self.assertEqual(self.by_guard(self.rank())[g]["available"], 1)

	def test_own_shift_same_window_blocks(self):
		g = self.guard("Own Shift")
		self.shift(g, DAY, THIRD, shift_type="Third", farm=OTHER_FARM, status="Scheduled")
		self.assertEqual(self.by_guard(self.rank("Third", THIRD))[g]["available"], 0)
		# ...but not a cover of the First shift that day.
		self.assertEqual(self.by_guard(self.rank())[g]["available"], 1)

	def test_already_covering_someone_that_day_blocks(self):
		g = self.guard("Covering")
		other = self.guard("Other Off")
		self.shift(g, DAY, SECOND, shift_type="Second", status="Scheduled", covering_for=other)
		c = self.by_guard(self.rank())[g]
		self.assertEqual(c["available"], 0)
		self.assertIn("Already covering Other Off", c["busy_reason"])

	def test_cancelled_shift_does_not_block(self):
		g = self.guard("Cancelled")
		self.shift(g, DAY, FIRST, status="Cancelled")
		self.assertEqual(self.by_guard(self.rank())[g]["available"], 1)

	def test_own_day_off_is_allowed_but_labelled(self):
		g = self.guard("Resting")
		frappe.get_doc(
			{"doctype": "Security Guard Off Days", "external_guard": g, "off_days": [{"off_date": DAY}]}
		).insert()
		c = self.by_guard(self.rank())[g]
		self.assertEqual(c["available"], 1)
		self.assertEqual(c["on_off_day"], 1)
		self.assertIn("own day off", c["reason"])

	def test_exclude(self):
		g = self.guard("Excluded")
		self.assertNotIn(g, self.by_guard(self.rank(exclude=[g])))
		self.assertNotIn(g, self.by_guard(self.rank(exclude='["%s"]' % g)))


class TestRanking(RelieverTestCase):
	def test_order(self):
		designated = self.guard("Designated")
		frappe.db.set_value("Security Guard", self.off, "reliever", designated)
		busy = self.guard("Busy Veteran")
		many = self.guard("Many Shifts")
		same_type = self.guard("Same Type")
		other_type = self.guard("Other Type")
		recent = self.guard("Long Ago Recent")
		older = self.guard("Long Ago Older")
		resting = self.guard("Resting Veteran")
		nobody = self.guard("A Never Here", farm=OTHER_FARM)
		based_here = self.guard("Z Based Here")

		for i in range(1, 6):
			self.shift(busy, add_days(DAY, -i), FIRST)
			self.shift(many, add_days(DAY, -i), SECOND, shift_type="Second")
			self.shift(resting, add_days(DAY, -i), FIRST)
		self.shift(busy, DAY, FIRST, status="Scheduled")
		frappe.get_doc(
			{"doctype": "Security Guard Off Days", "external_guard": resting, "off_days": [{"off_date": DAY}]}
		).insert()
		for i in (1, 2):
			self.shift(same_type, add_days(DAY, -i), FIRST)
			self.shift(other_type, add_days(DAY, -i), THIRD, shift_type="Third")
		self.shift(recent, add_days(DAY, -90), FIRST)
		self.shift(older, add_days(DAY, -120), FIRST)

		order = [c["guard"] for c in self.rank().suggestions]
		self.assertEqual(
			order, [designated, many, same_type, other_type, recent, older, based_here, nobody, resting, busy]
		)

		c = self.by_guard(self.rank())
		self.assertIn("Designated reliever for Off Guard", c[designated]["reason"])
		self.assertEqual(c[same_type]["reason"], "Worked %s First shift 2x in the last 60 days" % FARM)
		self.assertEqual((c[many]["farm_shifts"], c[many]["shift_type_shifts"]), (5, 0))
		self.assertIn("none on First shift", c[many]["reason"])
		self.assertIn("Last worked at", c[recent]["reason"])
		self.assertIn("based at %s" % OTHER_FARM, c[nobody]["reason"])

	def test_designated_but_busy_goes_below_free_guards(self):
		designated = self.guard("Designated")
		frappe.db.set_value("Security Guard", self.off, "reliever", designated)
		free = self.guard("Free")
		self.shift(designated, DAY, FIRST, status="Scheduled", covering_for=self.guard("Someone"))
		order = [c["guard"] for c in self.rank().suggestions]
		self.assertLess(order.index(free), order.index(designated))

	def test_history_stops_at_today_for_future_dates(self):
		# A shift scheduled between today and a future cover date is not
		# experience yet.
		g = self.guard("Future")
		future = add_days(getdate(), 10)
		self.shift(g, add_days(getdate(), 2), FIRST, status="Scheduled")
		r = relievers.rank_relievers(self.off, future, farm=FARM, shift_type="First", start_time=FIRST[0], end_time=FIRST[1])
		self.assertEqual(self.by_guard(r)[g]["farm_shifts"], 0)


class TestCoverGuard(RelieverTestCase):
	def toggle(self, mark_off=1, **kw):
		return toggle_guard_day(
			self.off, str(DAY), mark_off, farm=FARM, shift_type="First", start_time=FIRST[0], end_time=FIRST[1], **kw
		)

	def covers(self):
		return frappe.get_all(
			"Security Guard Shift Assignment",
			filters={"covering_for": self.off, "start_date": DAY},
			fields=["name", "external_guard", "start_time", "end_time", "farm"],
		)

	def test_picked_guard_covers(self):
		g = self.guard("Picked")
		res = self.toggle(cover_guard=g)
		self.assertEqual(res["state"], "off_covered")
		self.assertEqual(res["covered_by"], g)
		self.assertEqual(res["covered_by_name"], "Picked")
		[cover] = self.covers()
		self.assertEqual((cover.external_guard, cover.farm, cover.start_time), (g, FARM, _td(FIRST[0])))

	def test_picked_guard_used_instead_of_designated_reliever(self):
		frappe.db.set_value("Security Guard", self.off, "reliever", self.guard("Designated"))
		g = self.guard("Picked")
		self.assertEqual(self.toggle(cover_guard=g)["covered_by"], g)

	def test_no_cover(self):
		frappe.db.set_value("Security Guard", self.off, "reliever", self.guard("Designated"))
		for none in ("", "none"):
			res = self.toggle(cover_guard=none)
			self.assertEqual(res["state"], "off_unfilled")
			self.assertEqual(self.covers(), [])

	def test_busy_pick_is_refused(self):
		g = self.guard("Busy")
		self.shift(g, DAY, FIRST, farm=OTHER_FARM, status="Scheduled")
		res = self.toggle(cover_guard=g)
		self.assertEqual(res["state"], "off_unfilled")
		self.assertIn("no longer free", res["reason"])
		self.assertEqual(self.covers(), [])

	def test_repick_replaces_cover_and_unmark_removes_it(self):
		a, b = self.guard("First Pick"), self.guard("Second Pick")
		self.toggle(cover_guard=a)
		self.assertEqual(self.toggle(cover_guard=b)["covered_by"], b)
		self.assertEqual([c.external_guard for c in self.covers()], [b])
		# The first pick's cover row was made only for the cover: it is gone.
		self.assertFalse(frappe.db.exists("Security Guard Shift Assignment", {"external_guard": a, "start_date": DAY}))
		self.assertEqual(self.toggle(mark_off=0, create_shift=0)["state"], "on")
		self.assertEqual(self.covers(), [])
		self.assertFalse(frappe.db.exists("Security Guard Shift Assignment", {"external_guard": b, "start_date": DAY}))

	def test_busy_repick_keeps_current_cover(self):
		a, b = self.guard("Current"), self.guard("Busy")
		self.shift(b, DAY, FIRST, farm=OTHER_FARM, status="Scheduled")
		self.toggle(cover_guard=a)
		res = self.toggle(cover_guard=b)
		self.assertEqual((res["state"], res["covered_by"]), ("off_covered", a))
		self.assertIn("no longer free", res["reason"])

	def test_one_guard_cannot_take_two_overlapping_covers(self):
		g = self.guard("Popular")
		self.toggle(cover_guard=g)
		second_off = self.guard("Second Off")
		res = toggle_guard_day(
			second_off, str(DAY), 1, farm=FARM, shift_type="First", start_time=FIRST[0], end_time=FIRST[1], cover_guard=g
		)
		self.assertEqual(res["state"], "off_unfilled")

	def test_without_cover_guard_designated_reliever_tag_path_unchanged(self):
		rel = self.guard("Designated", farm=OTHER_FARM)
		frappe.db.set_value("Security Guard", self.off, "reliever", rel)
		self.shift(rel, DAY, FIRST, farm=OTHER_FARM, status="Scheduled")  # their own baseline shift
		res = self.toggle()
		self.assertEqual((res["state"], res["covered_by"]), ("off_covered", rel))
		[cover] = self.covers()
		self.assertEqual(cover.farm, FARM)
		# Marking back on untags their own shift (back at their home farm)
		# instead of deleting it.
		self.toggle(mark_off=0, create_shift=0)
		self.assertEqual(self.covers(), [])
		self.assertEqual(frappe.db.get_value("Security Guard Shift Assignment", cover.name, "farm"), OTHER_FARM)


class TestRotationPlanFill(RelieverTestCase):
	def test_fill_off_days(self):
		from upande_security.upande_security.doctype.security_guard_rotation_plan.security_guard_rotation_plan import (
			fill_off_day_covers,
			get_off_day_cover_options,
		)

		start = add_days(getdate(), 30)
		plan = frappe.get_doc(
			{
				"doctype": "Security Guard Rotation Plan",
				"external_guard": self.off,
				"mode": "Semi-Automatic",
				"shift_type": "First",
				"start_time": FIRST[0],
				"end_time": FIRST[1],
				"start_date": start,
				"end_date": add_days(start, 3),
				"rotation_interval_days": 7,
				"rotation_farms": [{"farm": FARM}],
			}
		)
		plan.insert()
		frappe.get_doc(
			{
				"doctype": "Security Guard Off Days",
				"external_guard": self.off,
				"off_days": [{"off_date": add_days(start, 1)}, {"off_date": add_days(start, 2)}],
			}
		).insert()
		only = self.guard("Only Reliever")
		plan.generate_preview()
		opts = get_off_day_cover_options(plan.name)
		self.assertEqual(len(opts["rows"]), 2)
		# Different days do not overlap, so the same guard is pre-picked for both.
		self.assertEqual([r["selected"] for r in opts["rows"]], [only, only])

		choices = {opts["rows"][0]["row"]: only, opts["rows"][1]["row"]: "none"}
		res = fill_off_day_covers(plan.name, frappe.as_json(choices))
		self.assertEqual([c["guard"] for c in res["covered"]], [only])
		self.assertEqual(res["uncovered"][0]["reason"], "Left without cover")
		plan.reload()
		self.assertEqual([r.cover_guard for r in plan.preview_rows if r.is_off_day], [only, None])

		# Apply lists the off day still without cover.
		applied = plan.apply_rotation()
		self.assertEqual([u["date"] for u in applied["uncovered_off_days"]], [str(add_days(start, 2))])
