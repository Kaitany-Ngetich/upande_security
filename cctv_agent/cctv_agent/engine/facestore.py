"""The site's face store: enrolled embeddings, kept ONLY on this box.

ERPNext never receives an embedding - only "enrolled" and a reference. A
withdrawal or erase request deletes the person's rows here.
"""

import sqlite3

import numpy as np


class FaceStore:
	def __init__(self, path):
		self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
		self.db.execute("create table if not exists faces (person text, idx int, vec blob, primary key(person, idx))")
		self._load()

	def _load(self):
		rows = self.db.execute("select person, vec from faces").fetchall()
		self.people = [r[0] for r in rows]
		self.matrix = np.stack([np.frombuffer(r[1], dtype=np.float32) for r in rows]) if rows else np.zeros((0, 1), np.float32)

	def enroll(self, person, vectors):
		self.db.execute("delete from faces where person=?", (person,))
		for i, v in enumerate(vectors):
			v = np.asarray(v, np.float32)
			v = v / (np.linalg.norm(v) or 1.0)
			self.db.execute("insert into faces values (?,?,?)", (person, i, v.tobytes()))
		self._load()
		return len(vectors)

	def delete(self, person):
		n = self.db.execute("delete from faces where person=?", (person,)).rowcount
		self._load()
		return n

	def match(self, vector, threshold=0.6):
		"""(person, similarity) of the best match at or above threshold, else (None, best)."""
		if not len(self.people):
			return None, 0.0
		v = np.asarray(vector, np.float32)
		v = v / (np.linalg.norm(v) or 1.0)
		sims = self.matrix @ v
		i = int(sims.argmax())
		best = float(sims[i])
		return (self.people[i], best) if best >= threshold else (None, best)

	def count(self):
		return len(set(self.people))
