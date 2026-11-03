# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""The patrol point and step rules (patrol_rules), the app Patrols report
built on them (patrol_report) and the Patrol Map's distance.

TestDayFigures writes a few Patrol GPS Log rows on a day nothing else uses
and rolls them back: it checks that the SQL counts what the Python rule
says it should."""

import datetime
import unittest
from unittest.mock import patch

import frappe

from upande_security.api import patrol_report as pr
from upande_security.api import patrol_rules as rules
from upande_security.api.security_dashboard import _walked_km


class TestPointRule(unittest.TestCase):
	def test_valid_fix(self):
		self.assertTrue(rules.valid_fix(0.52, 35.27))
		self.assertFalse(rules.valid_fix(0.0, 0.0))  # no fix yet
		self.assertFalse(rules.valid_fix(None, 35.27))
		self.assertFalse(rules.valid_fix(95.0, 35.27))
		self.assertFalse(rules.valid_fix(0.52, 181.0))
		# A swapped fix is a real place - the step rule is what keeps it
		# out of the distance.
		self.assertTrue(rules.valid_fix(35.27, 0.52))

	def test_accuracy(self):
		self.assertTrue(rules.accurate_enough(None))
		self.assertTrue(rules.accurate_enough(""))
		self.assertTrue(rules.accurate_enough("not a number"))
		self.assertTrue(rules.accurate_enough("12 m"))
		self.assertTrue(rules.accurate_enough(100))
		self.assertFalse(rules.accurate_enough("100.5"))
		self.assertFalse(rules.accurate_enough(900))


class TestStepRule(unittest.TestCase):
	def test_walking_counts(self):
		self.assertTrue(rules.step_counts(40, 30))  # 4.8 km/h
		self.assertTrue(rules.step_counts(5, 0))  # same second, a few metres

	def test_long_gap_does_not_count(self):
		self.assertFalse(rules.step_counts(100, rules.MAX_GAP_S + 1))

	def test_jump_does_not_count(self):
		# 1 km in 30 s is 120 km/h.
		self.assertFalse(rules.step_counts(1000, 30))
		# Kenya to the swapped position: thousands of km in a minute.
		far = rules.haversine_m(0.52, 35.27, 35.27, 0.52)
		self.assertGreater(far, 4_000_000)
		self.assertFalse(rules.step_counts(far, 60))

	def test_backwards_time_does_not_count(self):
		self.assertFalse(rules.step_counts(1, -5))


class TestMapDistance(unittest.TestCase):
	def test_glitch_and_gap_left_out(self):
		t0 = datetime.datetime(2026, 10, 21, 8, 0, 0)
		at = [t0 + datetime.timedelta(seconds=s) for s in (0, 30, 60, 90, 2000)]
		pts = [[0.5, 35.0], [0.5003, 35.0], [35.0, 0.5], [0.5006, 35.0], [0.5009, 35.0]]
		# Only the first step (~33 m) counts: the two steps to and from the
		# swapped fix are jumps, the last one comes after a 32 min gap.
		km = _walked_km(pts, at)
		self.assertAlmostEqual(km, rules.haversine_m(0.5, 35.0, 0.5003, 35.0) / 1000, places=6)


class TestCombine(unittest.TestCase):
	def test_totals_and_routes(self):
		days = [
			{"n": 5, "rows": [["E1", "Internal Guard", "P1", 3, 100.0, "2026-10-20 10:00:00"],
							  ["u@x", "User", "", 2, 50.0, "2026-10-20 11:00:00"]], "sample": []},
			{"n": 4, "rows": [["E1", "Internal Guard", "P1", 1, 10.0, "2026-10-21 01:00:00"],
							  ["E1", "Internal Guard", "P2", 3, 0.0, "2026-10-21 09:00:00"]], "sample": []},
		]
		out = pr._combine(days)
		self.assertEqual(out["points"], 9)
		self.assertEqual(out["metres"], 160.0)
		# P1 crosses midnight and is still one route; blank patrols are not routes.
		self.assertEqual(out["routes"], 2)
		self.assertEqual(set(out["guards"]), {"E1", "u@x"})
		self.assertEqual(out["guards"]["E1"]["points"], 7)
		self.assertEqual(out["guards"]["E1"]["patrols"], {"P1", "P2"})
		self.assertEqual(out["guards"]["E1"]["last"], "2026-10-21 09:00:00")

	def test_draw_sample_is_capped_and_weighted_by_day(self):
		def day(n, tag):
			return {"n": n, "rows": [], "sample": [[0.5, 35.0, f"{tag} {i:05d}", "g", "p"] for i in range(min(n, pr.DRAW_LIMIT))]}

		out = pr._combine([day(30000, "a"), day(10000, "b"), day(0, "c")])
		self.assertLessEqual(len(out["draw"]), pr.DRAW_LIMIT)
		a = sum(1 for p in out["draw"] if p[2].startswith("a"))
		b = sum(1 for p in out["draw"] if p[2].startswith("b"))
		self.assertEqual((a, b), (2250, 750))

	def test_rounding_never_overshoots(self):
		days = [{"n": 1001, "rows": [], "sample": [[0, 0, f"{d} {i}", "g", "p"] for i in range(1001)]} for d in range(7)]
		self.assertEqual(len(pr._combine(days)["draw"]), pr.DRAW_LIMIT)

	def test_small_ranges_send_everything(self):
		out = pr._combine([{"n": 3, "rows": [], "sample": [[0, 0, "x", "g", "p"]] * 3}])
		self.assertEqual(len(out["draw"]), 3)


class TestGuardNames(unittest.TestCase):
	def test_map_style_names(self):
		def get_all(doctype, filters=None, fields=None, as_list=False):
			return {"Employee": [("E1", "Jane Guard")], "Security Guard": [], "User": [("u@x", "Una User")]}[doctype]

		guards = {"E1": {"kind": "Internal Guard"}, "SG-1": {"kind": "External Guard"},
				  "u@x": {"kind": "User"}, "Unassigned": {"kind": ""}}
		with patch("frappe.get_all", side_effect=get_all):
			names = pr.guard_names(guards)
		self.assertEqual(names["E1"], "Jane Guard")
		self.assertEqual(names["SG-1"], "SG-1")
		self.assertEqual(names["u@x"], "Una User (no guard link)")
		self.assertEqual(names["Unassigned"], "Unassigned")


class TestPermissions(unittest.TestCase):
	def test_needs_patrol_log_read(self):
		with patch("frappe.has_permission", return_value=False):
			self.assertRaises(frappe.PermissionError, pr.patrols_report, "2026-10-21", "2026-10-21")

	def test_farm_must_be_readable(self):
		def has_permission(doctype, ptype="read", doc=None, **kw):
			return doctype != "Farm"

		with patch("frappe.has_permission", side_effect=has_permission), \
				patch("frappe.get_list", return_value=[]), \
				patch("frappe.db.exists", return_value=True):
			self.assertRaises(frappe.PermissionError, pr.patrols_report, "2026-10-21", "2026-10-21", "Some Farm")

	def test_range_is_capped(self):
		with patch("frappe.has_permission", return_value=True):
			self.assertRaises(frappe.ValidationError, pr.patrols_report, "2026-01-01", "2026-03-01")

	def report(self, role_perms, farms=("A",)):
		seen = []
		with patch("frappe.has_permission", return_value=True), \
				patch("frappe.get_list", return_value=list(farms)), \
				patch("frappe.db.count", return_value=3), \
				patch("frappe.permissions.get_role_permissions", return_value=role_perms), \
				patch.object(pr, "_day", side_effect=lambda day, scope: seen.append(scope) or {"n": 0, "rows": [], "sample": []}), \
				patch.object(pr, "boundaries", side_effect=lambda farms: [{"farm": f} for f in farms]):
			out = pr.patrols_report("2026-10-21", "2026-10-21")
		return seen[0], out

	def test_limited_user_only_sees_their_farms(self):
		scope, out = self.report({"read": 1, "if_owner": {}})
		self.assertEqual(scope["kind"], "saved")
		self.assertEqual(scope["farms"], ["A"])
		self.assertNotIn("owner", scope)
		self.assertEqual(out["farms"], ["A"])
		self.assertEqual(out["boundaries"], [{"farm": "A"}])

	def test_unlimited_user_sees_every_point(self):
		scope, _ = self.report({"read": 1, "if_owner": {}}, farms=("A", "B", "C"))
		self.assertEqual(scope["kind"], "all")

	def test_if_owner_read_sees_own_points_only(self):
		scope, _ = self.report({"read": 1, "if_owner": {"read": 0}}, farms=("A", "B", "C"))
		self.assertEqual(scope["owner"], frappe.session.user)
		params = {}
		sql = pr._branches(scope, params)[0]
		self.assertIn("owner = %(owner)s", sql)
		self.assertEqual(params["owner"], frappe.session.user)


class TestDayFigures(unittest.TestCase):
	"""The SQL against rows written for the test, then rolled back."""

	DAY = "2031-01-07"

	def setUp(self):
		if not frappe.db:
			self.skipTest("needs a site")
		self.n = 0

	def tearDown(self):
		frappe.db.rollback()

	def add(self, secs, lat, lng, acc="5", internal="", external="", owner="guard@example.com", patrol="P1", mode="Patrol"):
		self.n += 1
		frappe.db.sql(
			"insert into `tabPatrol GPS Log` (name, creation, modified, owner, captured_at, latitude, longitude,"
			" gps_accuracy, internal_guard, external_guard, patrol, tracking_mode)"
			" values (%s, now(), now(), %s, %s, %s, %s, %s, %s, %s, %s, %s)",
			(f"test-pr-{self.n:03d}", owner,
			 datetime.datetime.fromisoformat(self.DAY + " 08:00:00") + datetime.timedelta(seconds=secs),
			 str(lat), str(lng), acc, internal, external, patrol, mode),
		)

	def test_counts_follow_the_rules(self):
		# Guard E1 walks north 33 m every 30 s; one swapped fix with no
		# accuracy recorded sits in the middle.
		self.add(0, 0.5, 35.0, internal="E1")
		self.add(30, 0.5003, 35.0, internal="E1")
		self.add(60, 35.0, 0.5, acc="", internal="E1")
		self.add(90, 0.5006, 35.0, internal="E1")
		self.add(120, 0.5009, 35.0, internal="E1")
		# Left out entirely: (0, 0), a 500 m fix, an On Duty point, a bad latitude.
		self.add(130, 0, 0, internal="E1")
		self.add(140, 0.5010, 35.0, acc="500", internal="E1")
		self.add(150, 0.5011, 35.0, internal="E1", mode="On Duty")
		self.add(160, 95, 35.0, internal="E1")
		# No guard link: counted under the account that sent it.
		self.add(0, 0.6, 35.1, owner="phone@example.com", patrol="")
		self.add(60, 0.6003, 35.1, owner="phone@example.com", patrol="")

		out = pr.day_figures(f"{self.DAY} 00:00:00", f"{self.DAY} 23:59:59", {"kind": "all", "key": "test"})
		by = {(r[0], r[2]): r for r in out["rows"]}
		self.assertEqual(out["n"], 7)
		self.assertEqual(set(by), {("E1", "P1"), ("phone@example.com", "")})
		e1 = by[("E1", "P1")]
		self.assertEqual((e1[1], e1[3]), ("Internal Guard", 5))
		step = rules.haversine_m(0.5, 35.0, 0.5003, 35.0)
		# Steps 1 and 4 count; the two around the swapped fix are jumps.
		self.assertAlmostEqual(e1[4], round(2 * step, 1), places=0)
		phone = by[("phone@example.com", "")]
		self.assertEqual((phone[1], phone[3]), ("User", 2))
		self.assertEqual(len(out["sample"]), 7)
		self.assertEqual(out["sample"][0][2], f"{self.DAY} 08:00:00")


class TestPlaybackGuard(unittest.TestCase):
	def test_map_identity(self):
		from upande_security.api.patrol_playback import _guard_label

		self.assertEqual(_guard_label({"internal_guard": "E1", "external_guard": "SG-1", "personel": "External Guard"}), ("Internal Guard", "E1"))
		self.assertEqual(_guard_label({"external_guard": "SG-1", "owner": "u@x"}), ("External Guard", "SG-1"))
		self.assertEqual(_guard_label({"internal_guard": "", "external_guard": None, "owner": "u@x"}), ("User", "u@x"))
		self.assertEqual(_guard_label({"owner": "Administrator"}), (None, None))
