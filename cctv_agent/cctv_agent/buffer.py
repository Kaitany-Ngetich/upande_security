"""Store-and-forward queue (SQLite).

Every event is written here before any send, so a dead link, a restart or a
crash never loses one. event_id is the primary key: ERPNext treats a resend
as a duplicate, so replay after an outage is safe. Alert-relevant events
(priority 0) go before bulk ones (priority 1).
"""

import json
import os
import sqlite3
import threading
import time


class Buffer:
	def __init__(self, path, max_size_mb=20480):
		os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
		self.path = path
		self.max_bytes = max_size_mb * 1024 * 1024
		self._lock = threading.Lock()
		self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
		self.db.execute("pragma journal_mode=wal")
		self.db.execute(
			"create table if not exists events (event_id text primary key, priority int, created real, attempts int default 0, body text)"
		)
		self.db.execute("create index if not exists ix_events_order on events(priority, created)")

	def put(self, event, priority=1):
		with self._lock:
			self.db.execute("insert or ignore into events(event_id, priority, created, body) values (?,?,?,?)",
				(event["event_id"], priority, time.time(), json.dumps(event, separators=(",", ":"))))
			self._trim()

	def take(self, limit=100, max_bytes=1_000_000):
		"""Oldest high-priority events first, up to `limit` events / ~max_bytes."""
		with self._lock:
			rows = self.db.execute("select event_id, body from events order by priority, created limit ?", (limit,)).fetchall()
		out, size = [], 0
		for _, body in rows:
			size += len(body)
			if out and size > max_bytes:
				break
			out.append(json.loads(body))
		return out

	def ack(self, event_ids):
		if not event_ids:
			return
		with self._lock:
			self.db.executemany("delete from events where event_id=?", [(e,) for e in event_ids])

	def bump(self, event_ids):
		with self._lock:
			self.db.executemany("update events set attempts=attempts+1 where event_id=?", [(e,) for e in event_ids])

	def depth(self):
		return self.db.execute("select count(*) from events").fetchone()[0]

	def _trim(self):
		"""Over the size cap: drop the oldest bulk events first, never priority ones unless nothing else is left."""
		try:
			if os.path.getsize(self.path) < self.max_bytes:
				return
		except OSError:
			return
		self.db.execute("delete from events where event_id in (select event_id from events where priority=1 order by created limit 1000)")
		if os.path.getsize(self.path) >= self.max_bytes:
			self.db.execute("delete from events where event_id in (select event_id from events order by created limit 1000)")
