# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Patrolled area as the swept corridor along a guard's walked path."""

import datetime
import math
import unittest
from unittest.mock import patch

from shapely.geometry import Polygon, box

from upande_security.api import patrol_ranking as pr
from upande_security.api import patrol_sweep as ps

FARM = box(-5000, -5000, 5000, 5000)  # metres, far bigger than any walk here
# A 100 m end cap drawn with 4 segments per quarter circle is a 16-gon.
CAP = 8 * 100**2 * math.sin(2 * math.pi / 16)


class TestCorridor(unittest.TestCase):
	def test_straight_walk_sweeps_its_length_times_twice_the_offset(self):
		swept = ps.corridor([[(0, 0), (1000, 0)]], 100, FARM)
		self.assertAlmostEqual(swept.area, 1000 * 200 + CAP, delta=50)

	def test_a_long_walk_buffered_in_chunks_is_one_corridor(self):
		# 101 fixes along an L (well past one chunk): same ground as the L.
		walk = [(x * 10, 0) for x in range(51)] + [(500, y * 10) for y in range(1, 51)]
		swept = ps.corridor([walk], 100, FARM)
		whole = ps.corridor([[(0, 0), (500, 0), (500, 500)]], 100, FARM)
		self.assertAlmostEqual(swept.area, whole.area, delta=whole.area * 0.001)

	def test_out_and_back_adds_nothing(self):
		one_way = ps.corridor([[(0, 0), (1000, 0)]], 100, FARM).area
		there_and_back = ps.corridor([[(0, 0), (1000, 0), (0, 0)]], 100, FARM).area
		self.assertAlmostEqual(there_and_back, one_way, delta=50)

	def test_clipped_to_the_farm(self):
		# Walking along the farm's edge: only the inside half counts.
		edge = box(0, 0, 2000, 2000)
		swept = ps.corridor([[(0, 1000), (0, 1500)]], 100, edge)
		self.assertAlmostEqual(swept.area, (500 * 200 + CAP) / 2, delta=50)

	def test_standing_still_watches_around_the_post(self):
		swept = ps.corridor([[(0, 0), (0, 0), (0, 0)]], 100, FARM)
		self.assertAlmostEqual(swept.area, CAP, delta=5)

	def test_a_lone_fix_sweeps_nothing(self):
		self.assertIsNone(ps.corridor([[(0, 0)]], 100, FARM))

	def test_outside_the_farm_sweeps_nothing(self):
		self.assertIsNone(ps.corridor([[(9000, 9000), (9500, 9000)]], 100, FARM))

	def test_guards_on_the_same_path_count_once(self):
		a = ps.corridor([[(0, 0), (1000, 0)]], 100, FARM)
		b = ps.corridor([[(500, 0), (1000, 0)]], 100, FARM)
		self.assertAlmostEqual(ps.union([a, b]).area, a.area, delta=50)

	def test_cache_round_trip(self):
		swept = ps.corridor([[(0, 0), (300, 400)]], 50, FARM)
		self.assertAlmostEqual(ps.decode(ps.encode(swept)).area, swept.area, places=3)
		self.assertIsNone(ps.encode(None))
		self.assertIsNone(ps.decode(None))


class TestFrame(unittest.TestCase):
	def test_metres_near_the_equator(self):
		# ~0.01° square at the equator is ~1.11 km a side, ~123 ha.
		poly = Polygon([(36.66, 0.02), (36.67, 0.02), (36.67, 0.03), (36.66, 0.03)])
		fr = ps.frame(poly)
		shape = ps.farm_shape(poly, fr)
		self.assertAlmostEqual(shape.area / 10000, 111320 * 110540 * 1e-4 / 10000, delta=0.5)
		self.assertEqual(ps.to_metres(fr, 36.66, 0.02), (0.0, 0.0))


class TestGuardStats(unittest.TestCase):
	"""_guard_stats: one pass gives the distance, time and patrols, and one
	unbroken walk per run of counted steps for the corridor."""

	def geos(self):
		poly = Polygon([(36.0, 0.0), (36.1, 0.0), (36.1, 0.1), (36.0, 0.1)])
		fr = ps.frame(poly)
		return [{"farm": "F", "grid": None, "on": None, "off": None, "area": 0,
			"sweep": {"frame": fr, "farm": ps.encode(ps.farm_shape(poly, fr)), "m2": 1}}]

	def run_rows(self, rows, offset=10):
		"""rows: (patrol, lat, lng, secs, metres, ok) for guard G on farm F."""
		at = datetime.datetime(2026, 11, 27, 22, 0)
		full = [
			("F", "G", "External Guard", p, at + datetime.timedelta(minutes=i), lat, lng, None, secs, m, ok)
			for i, (p, lat, lng, secs, m, ok) in enumerate(rows)
		]
		with patch("frappe.db.sql", return_value=full), patch.object(pr, "_force_index", return_value=""):
			return pr._guard_stats(self.geos(), "a", "b", False, offset)[("F", "G")]

	WALK = 111.3 * 20 + 8 * 10**2 * math.sin(2 * math.pi / 16)  # ~111 m walk, 10 m offset

	def test_a_step_that_does_not_count_breaks_the_walk(self):
		# ~111 m east, a GPS jump north (ok = 0), ~111 m east again: two
		# walks, no corridor across the jump, and the jump is not distance.
		d = 0.001
		s = self.run_rows([
			("P1", 0.05, 36.05, None, None, 0),
			("P1", 0.05, 36.05 + d, 60, 111.3, 1),
			("P1", 0.06, 36.05 + d, 60, 1113.0, 0),
			("P1", 0.06, 36.05 + 2 * d, 60, 111.3, 1),
		])
		self.assertAlmostEqual(s["sweeps"][0].area, 2 * self.WALK, delta=10)
		self.assertAlmostEqual(s["metres"], 222.6)
		self.assertEqual((s["seconds"], s["points"], s["patrol_ids"]), (120, 4, {"P1"}))

	def test_patrols_are_walked_separately(self):
		d = 0.001
		s = self.run_rows([
			("P1", 0.05, 36.05, None, None, 0),
			("P1", 0.05, 36.05 + d, 60, 111.3, 1),
			# A new patrol starts back west: not one long walk across.
			("P2", 0.05, 36.04, None, None, 0),
			("P2", 0.05, 36.04 + d, 60, 111.3, 1),
		])
		self.assertAlmostEqual(s["sweeps"][0].area, 2 * self.WALK, delta=10)
		self.assertEqual(s["patrol_ids"], {"P1", "P2"})

	def test_no_offset_no_corridor(self):
		s = self.run_rows([("P1", 0.05, 36.05, None, None, 0), ("P1", 0.05, 36.051, 60, 111.3, 1)], offset=None)
		self.assertEqual(s["sweeps"], [])
		self.assertAlmostEqual(s["metres"], 111.3)
