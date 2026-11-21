# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Registration plates: normalising, format checks, misread repair and scoring.

Typed plates and camera reads disagree in small ways - "KDA 123A", "kda123a",
"KDA-123A" - and OCR swaps look-alike characters (0/O, 1/I, 8/B, 5/S, 2/Z).
Everything that compares plates goes through here so the rules live once.

Formats come from CCTV Settings > Plate Formats; the defaults are Kenya's.
The live data shows why the motorcycle and KT patterns matter: about a
quarter of plates typed on appointments are motorcycles (KMxx 123A), and
they are typed into the car-plate field.
"""

import itertools
import re

DEFAULT_FORMATS = [
	{"label": "Kenya car", "pattern": r"^K[A-Z]{2}\d{3}[A-Z]$", "vehicle_class": "Car", "example": "KDA 123A"},
	{"label": "Kenya motorcycle", "pattern": r"^KM[A-Z]{2}\d{3}[A-Z]$", "vehicle_class": "Motorcycle", "example": "KMHC 329U"},
	{"label": "Kenya KT series", "pattern": r"^KT[A-Z]{2}\d{3}[A-Z]$", "vehicle_class": "Other", "example": "KTCB 658T"},
	{"label": "Kenya old car", "pattern": r"^K[A-Z]{2}\d{3}$", "vehicle_class": "Car", "example": "KAA 123"},
	{"label": "Government", "pattern": r"^GK[A-Z]?\d{3}[A-Z]?$", "vehicle_class": "Government", "example": "GK A 123B"},
	{"label": "Diplomatic", "pattern": r"^\d{2,3}(CD|UN|KE)\d{1,3}[A-Z]?$", "vehicle_class": "Diplomatic", "example": "21CD 5K"},
]

# Characters OCR confuses, grouped. Each group collapses to one symbol in
# the skeleton, so two reads that differ only by look-alikes share a skeleton.
_GROUPS = ["0OQD", "1IL", "8B", "5S", "2Z", "6G"]
_SKELETON = {ch: grp[0] for grp in _GROUPS for ch in grp}
_LETTER_FOR = {"0": "O", "1": "I", "8": "B", "5": "S", "2": "Z", "6": "G"}
_DIGIT_FOR = {v: k for k, v in _LETTER_FOR.items()} | {"Q": "0", "D": "0", "L": "1"}


def normalize(plate):
	"""Upper case, letters and digits only. '' for nothing usable."""
	return re.sub(r"[^A-Z0-9]", "", str(plate or "").upper())


def display(plate):
	"""'KDA123A' -> 'KDA 123A', 'KMHC329U' -> 'KMHC 329U' (space before the digits)."""
	p = normalize(plate)
	m = re.match(r"^([A-Z]+)(\d.*)$", p)
	return f"{m.group(1)} {m.group(2)}" if m else p


def skeleton(plate):
	return "".join(_SKELETON.get(ch, ch) for ch in normalize(plate))


def _formats(formats=None):
	return formats or DEFAULT_FORMATS


def classify(plate, formats=None):
	"""The first format row the plate fits, or None."""
	p = normalize(plate)
	for f in _formats(formats):
		if re.match(f["pattern"], p):
			return f
	return None


def repair(plate, formats=None):
	"""Fix look-alike swaps so a read fits a known format.

	Returns (plate, swaps): the read unchanged when it already fits or when
	nothing fits, else the variant needing the fewest swaps."""
	p = normalize(plate)
	if not p or classify(p, formats):
		return p, 0
	positions = [i for i, ch in enumerate(p) if ch in _LETTER_FOR or ch in _DIGIT_FOR]
	if len(positions) > 8:
		return p, 0
	for n in range(1, len(positions) + 1):
		for combo in itertools.combinations(positions, n):
			chars = list(p)
			for i in combo:
				ch = chars[i]
				chars[i] = _LETTER_FOR.get(ch) or _DIGIT_FOR.get(ch) or ch
			candidate = "".join(chars)
			if classify(candidate, formats):
				return candidate, n
	return p, 0


def _distance(a, b):
	"""Levenshtein distance (plates are short, so the simple DP is fine)."""
	if a == b:
		return 0
	prev = list(range(len(b) + 1))
	for i, ca in enumerate(a, 1):
		cur = [i]
		for j, cb in enumerate(b, 1):
			cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
		prev = cur
	return prev[-1]


def similarity(read, typed, fuzzy=True):
	"""0..1: how likely a camera read and a typed plate are the same vehicle.

	1.0 exact, 0.92 same apart from look-alike characters, 0.75 one
	character off, 0.5 two off, else 0."""
	a, b = normalize(read), normalize(typed)
	if not a or not b:
		return 0.0
	if a == b:
		return 1.0
	if not fuzzy:
		return 0.0
	if skeleton(a) == skeleton(b):
		return 0.92
	d = _distance(skeleton(a), skeleton(b))
	if d == 1:
		return 0.75
	if d == 2 and min(len(a), len(b)) >= 6:
		return 0.5
	return 0.0
