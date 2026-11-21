"""Plate text post-processing: normalise, fit to a known format, vote across frames."""

import re
from collections import Counter, defaultdict

DEFAULT_PATTERNS = [r"^K[A-Z]{2}\d{3}[A-Z]$", r"^KM[A-Z]{2}\d{3}[A-Z]$", r"^KT[A-Z]{2}\d{3}[A-Z]$",
	r"^K[A-Z]{2}\d{3}$", r"^GK[A-Z]?\d{3}[A-Z]?$", r"^\d{2,3}(CD|UN|KE)\d{1,3}[A-Z]?$"]
TO_LETTER = {"0": "O", "1": "I", "8": "B", "5": "S", "2": "Z", "6": "G"}
TO_DIGIT = {v: k for k, v in TO_LETTER.items()} | {"Q": "0", "D": "0", "L": "1"}


def normalize(text):
	return re.sub(r"[^A-Z0-9]", "", (text or "").upper())


def fits(text, patterns):
	return any(re.match(p, text) for p in patterns)


def repair(text, patterns):
	"""Fix look-alike characters so the read fits a format (fewest changes)."""
	import itertools

	t = normalize(text)
	if not t or fits(t, patterns):
		return t
	pos = [i for i, c in enumerate(t) if c in TO_LETTER or c in TO_DIGIT][:8]
	for n in range(1, len(pos) + 1):
		for combo in itertools.combinations(pos, n):
			chars = list(t)
			for i in combo:
				chars[i] = TO_LETTER.get(chars[i]) or TO_DIGIT.get(chars[i]) or chars[i]
			cand = "".join(chars)
			if fits(cand, patterns):
				return cand
	return t


def vote(reads, patterns=None):
	"""reads: [(text, confidence)] from several frames of one vehicle.
	Returns (plate, confidence): the most common length, then per-position
	confidence-weighted majority; confidence = agreement x mean confidence."""
	patterns = patterns or DEFAULT_PATTERNS
	reads = [(repair(t, patterns), c) for t, c in reads if normalize(t)]
	if not reads:
		return None, 0.0
	length = Counter(len(t) for t, _ in reads).most_common(1)[0][0]
	same = [(t, c) for t, c in reads if len(t) == length]
	out, agree = [], []
	for i in range(length):
		w = defaultdict(float)
		for t, c in same:
			w[t[i]] += c
		ch, best = max(w.items(), key=lambda x: x[1])
		out.append(ch)
		agree.append(best / sum(w.values()))
	plate = "".join(out)
	conf = (sum(agree) / len(agree)) * (sum(c for _, c in same) / len(same))
	if not fits(plate, patterns):
		conf *= 0.6  # does not look like a real plate
	return plate, round(conf, 3)
