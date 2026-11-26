"""Runs the engine for every camera set to "Own Engine" with analytics enabled."""

import asyncio
import logging
import os

from cctv_agent.engine.models import ModelManager
from cctv_agent.erp import backoff

log = logging.getLogger("cctv_agent.engine")


class Engine:
	def __init__(self, agent, data_dir):
		self.agent = agent
		self.models = ModelManager(agent.erp, os.path.join(data_dir, "models"))
		self.faces = None
		self.face_db = os.path.join(data_dir, "faces.db")
		self.tasks = []

	async def apply(self, site):
		for t in self.tasks:
			t.cancel()
		self.tasks = []
		analytics = site.get("analytics") or {}
		if not analytics.get("engine"):
			log.info("engine not licensed for this site")
			return
		try:
			await self.models.sync()
		except Exception as e:
			log.warning("engine model sync failed: %s", e)
		if analytics.get("faces"):
			from cctv_agent.engine.facestore import FaceStore

			self.faces = self.faces or FaceStore(self.face_db)
		else:
			self.faces = None  # faces switched off: stored embeddings stay untouched but unused
		from cctv_agent.engine.plates import DEFAULT_PATTERNS

		patterns = [f["pattern"] for f in analytics.get("plate_formats") or []] or DEFAULT_PATTERNS
		for cam in site.get("cameras", []):
			if cam.get("analytics_provider") == "Own Engine" and cam.get("analytics_enabled"):
				self.tasks.append(asyncio.create_task(self._camera(cam, analytics, patterns), name=f"engine:{cam['name']}"))
		log.info("engine on %s camera(s)", len(self.tasks))

	async def _camera(self, cam, analytics, patterns):
		from cctv_agent.engine.pipeline import CameraWorker

		adapter = self.agent.adapters.get(cam["server"])
		attempt = 0
		while True:
			try:
				src = await adapter.stream_uri(cam, "main") if hasattr(adapter, "stream_uri") else adapter.get_stream_uri(cam, "main")
				worker = CameraWorker(self.agent.site["site"], cam, self.models.live, self.agent.on_event,
					faces=self.faces, face_threshold=analytics.get("face_match_threshold", 0.6), plate_patterns=patterns,
					shadow=self.models.shadow)
				await worker.run(src)
			except asyncio.CancelledError:
				raise
			except Exception as e:
				attempt += 1
				log.warning("engine on %s stopped: %s", cam["name"], e)
			await asyncio.sleep(backoff(attempt, base=2))
