# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""The Guard ranking's calendar periods and its score."""

import datetime
import unittest
from unittest.mock import patch

from upande_security.api import patrol_ranking as pr


def _stats(cells=0, metres=0.0, valid_scans=0):
	s = pr._empty_stats("External Guard")
	s["cells"] = {f"{i}-0" for i in range(cells)}
	s["metres"] = metres
	s["valid_scans"] = valid_scans
	return s


class TestResolvePeriod(unittest.TestCase):
	def resolve(self, period, today, **kw):
		with patch("frappe.utils.getdate", side_effect=lambda d=None: today if d is None else datetime.date.fromisoformat(str(d))):
			return pr.resolve_period(period, **kw)

	def test_weeks_start_on_monday(self):
		wed = datetime.date(2026, 11, 4)
		self.assertEqual(self.resolve("this_week", wed), (datetime.date(2026, 11, 2), wed))
		self.assertEqual(
			self.resolve("last_week", wed), (datetime.date(2026, 10, 26), datetime.date(2026, 11, 1))
		)

	def test_months(self):
		day = datetime.date(2026, 3, 15)
		self.assertEqual(self.resolve("this_month", day), (datetime.date(2026, 3, 1), day))
		self.assertEqual(
			self.resolve("last_month", day), (datetime.date(2026, 2, 1), datetime.date(2026, 2, 28))
		)

	def test_custom_is_put_in_order(self):
		day = datetime.date(2026, 3, 15)
		self.assertEqual(
			self.resolve("custom", day, from_date="2026-03-10", to_date="2026-03-01"),
			(datetime.date(2026, 3, 1), datetime.date(2026, 3, 10)),
		)


class TestRank(unittest.TestCase):
	def test_scores_against_the_best_on_the_farm(self):
		grid = {"cells": 100}
		guards = {"a": _stats(cells=50, metres=10000), "b": _stats(cells=25, metres=20000)}
		rows, weights, farm_cov = pr._rank("F", guards, grid)
		self.assertEqual(weights, pr.NO_SCAN_WEIGHTS)
		by = {r["guard"]: r for r in rows}
		# No incidents: everyone has full safety (0.2).
		# a: 0.5 * 1 + 0.3 * 0.5 + 0.2 = 0.85; b: 0.5 * 0.5 + 0.3 * 1 + 0.2 = 0.75
		self.assertEqual(by["a"]["score"], 85.0)
		self.assertEqual(by["b"]["score"], 75.0)
		self.assertEqual([r["guard"] for r in rows], ["a", "b"])
		self.assertEqual(by["a"]["coverage_pct"], 50.0)
		# Cells 0..49 and 0..24 overlap: the farm as a whole saw 50.
		self.assertEqual(farm_cov, 50.0)

	def test_scans_count_when_the_farm_has_any(self):
		guards = {"a": _stats(cells=10, metres=1000, valid_scans=4), "b": _stats(cells=10, metres=1000)}
		rows, weights, _ = pr._rank("F", guards, {"cells": 20})
		self.assertEqual(weights, pr.WEIGHTS)
		by = {r["guard"]: r for r in rows}
		self.assertEqual(by["a"]["score"], 100.0)
		# 0.4 + 0.25 + 0 scans + 0.2 safety
		self.assertEqual(by["b"]["score"], 85.0)

	def test_no_boundary_ranks_on_distance(self):
		guards = {"a": _stats(metres=3000), "b": _stats(metres=1500)}
		rows, weights, farm_cov = pr._rank("F", guards, None)
		self.assertEqual(weights, pr.DISTANCE_ONLY)
		self.assertIsNone(farm_cov)
		self.assertEqual([(r["guard"], r["score"], r["coverage_pct"]) for r in rows], [("a", 100.0, None), ("b", 60.0, None)])


def _inc(nature, severity="Medium"):
	return {"name": "INC-" + nature, "nature": nature, "severity": severity, "at": "2026-11-01 10:00:00",
		"scored": nature not in pr.UNSCORED_INCIDENT_TYPES}


class TestSafety(unittest.TestCase):
	def rank(self, inc_a, inc_b):
		guards = {"a": _stats(cells=10, metres=1000), "b": _stats(cells=10, metres=1000)}
		rows, weights, _ = pr._rank("F", guards, {"cells": 20}, {("F", "a"): inc_a, ("F", "b"): inc_b})
		self.assertEqual(weights, pr.NO_SCAN_WEIGHTS)
		return {r["guard"]: r["score"] for r in rows}

	def test_incidents_on_shift_lower_the_score(self):
		by = self.rank({"shifts": 3, "incidents": []}, {"shifts": 4, "incidents": [_inc("Theft"), _inc("Intrusion")]})
		self.assertEqual(by, {"a": 100.0, "b": 80.0})

	def test_unscored_types_are_ignored(self):
		unscored = [_inc(t) for t in pr.UNSCORED_INCIDENT_TYPES]
		by = self.rank({"shifts": 3, "incidents": []}, {"shifts": 3, "incidents": unscored})
		self.assertEqual(by, {"a": 100.0, "b": 100.0})

	def test_rate_is_per_shift(self):
		# a: 1 in 10 shifts (0.1), b: 1 in 2 (0.5, the farm's worst).
		by = self.rank({"shifts": 10, "incidents": [_inc("Theft")]}, {"shifts": 2, "incidents": [_inc("Theft")]})
		# a: 0.5 + 0.3 + 0.2 * (1 - 0.1 / 0.5) = 0.96; b: 0.8
		self.assertEqual(by, {"a": 96.0, "b": 80.0})
