# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Which shift a biometric punch belongs to - see api/shift_checkin.py."""

import datetime
import unittest

import frappe

from upande_security.api.shift_checkin import pick_shift


def _shift(name, day, start, end):
	d = datetime.date.fromisoformat(day)
	return frappe._dict(
		name=name,
		start_date=d,
		start_time=datetime.timedelta(hours=start),
		end_date=d,  # overnight shifts store the same end_date, as the roster does
		end_time=datetime.timedelta(hours=end),
		checked_in=0,
	)


def _at(s):
	return datetime.datetime.fromisoformat(s)


class TestPickShift(unittest.TestCase):
	def setUp(self):
		self.first = _shift("first", "2026-11-02", 6, 14)
		self.second = _shift("second", "2026-11-02", 14, 22)
		self.night = _shift("night", "2026-11-01", 22, 6)

	def test_arrival_on_time(self):
		self.assertEqual(pick_shift([self.first], _at("2026-11-02 05:58")).name, "first")

	def test_up_to_an_hour_early_counts(self):
		self.assertEqual(pick_shift([self.first], _at("2026-11-02 05:01")).name, "first")

	def test_more_than_an_hour_early_does_not(self):
		self.assertIsNone(pick_shift([self.first], _at("2026-11-02 04:50")))

	def test_after_the_shift_ended_does_not(self):
		self.assertIsNone(pick_shift([self.first], _at("2026-11-02 14:30")))

	def test_night_shift_runs_past_midnight(self):
		# Stored 22:00 -> 06:00 on one date; a punch at 02:00 the next day is in it.
		self.assertEqual(pick_shift([self.night], _at("2026-11-02 02:00")).name, "night")

	def test_back_to_back_reliever_goes_to_nearest_start(self):
		# 13:40 sits in both First (until 14:00) and Second (from 13:00).
		self.assertEqual(pick_shift([self.first, self.second], _at("2026-11-02 13:40")).name, "second")

	def test_no_shifts(self):
		self.assertIsNone(pick_shift([], _at("2026-11-02 06:00")))
