"""Run what ERPNext asks for (CCTV Agent Command), polled every few seconds.

	export_clip        recorder playback for [start, end] -> MP4 -> uploaded to the alert
	snapshot           a still from a camera -> uploaded
	discover_channels  the recorder's channels -> setup wizard
	test_connection    reach a recorder, model / firmware / clock offset
	enroll_face        fetch the person's images, embed, store locally (face store)
	delete_face        remove the person from the local face store
	sync_models        re-pull engine models
"""

import asyncio
import logging
import os
import tempfile
from datetime import datetime, timezone

from cctv_agent.envelope import camera_key

log = logging.getLogger("cctv_agent.commands")


class CommandRunner:
	def __init__(self, agent, poll_seconds=5):
		self.agent = agent
		self.poll_seconds = poll_seconds

	def _camera(self, name):
		site = self.agent.site or {}
		cam = next((c for c in site.get("cameras", []) if c["name"] == name or camera_key(c["name"]) == name), None)
		if not cam:
			raise ValueError(f"camera {name} is not configured at this site")
		return cam, self.agent.adapters.get(cam["server"])

	async def loop(self):
		erp = self.agent.erp
		while True:
			try:
				for cmd in await erp.poll_commands():
					asyncio.create_task(self.run(cmd))
			except Exception as e:
				log.debug("command poll failed: %s", e)
			await asyncio.sleep(self.poll_seconds)

	async def run(self, cmd):
		erp, cid, kind, p = self.agent.erp, cmd["id"], cmd["command"], cmd.get("payload") or {}
		try:
			result = await getattr(self, kind)(cid, p)
			await erp.command_result(cid, "done", result)
		except Exception as e:
			log.warning("command %s (%s) failed: %s", cid, kind, e)
			try:
				await erp.command_result(cid, "failed", {}, str(e)[:500])
			except Exception:
				pass

	# ---- handlers ------------------------------------------------------------------------
	async def export_clip(self, cid, p):
		cam, adapter = self._camera(p["camera"])
		start = datetime.strptime(p["start_utc"], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
		end = datetime.strptime(p["end_utc"], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
		src = adapter.get_playback_uri(cam, start, end) if adapter else None
		if not src:
			raise RuntimeError("this recorder's playback is not supported by its adapter")
		seconds = int((end - start).total_seconds())
		fd, path = tempfile.mkstemp(suffix=".mp4")
		os.close(fd)
		try:
			proc = await asyncio.create_subprocess_exec("ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-rtsp_transport", "tcp",
				"-i", src, "-t", str(seconds), "-c", "copy", "-movflags", "+faststart", path)
			await asyncio.wait_for(proc.wait(), timeout=seconds * 3 + 120)
			if proc.returncode or os.path.getsize(path) < 1024:
				raise RuntimeError("the recorder returned no footage for that time (overwritten, or not recorded)")
			name = f"evidence-{p.get('label') or cid}-{p['start_utc']}.mp4"
			url = await self.agent.erp.upload_command_file(cid, path, name, "video/mp4")
			return {"file_url": url, "seconds": seconds, "bytes": os.path.getsize(path)}
		finally:
			if os.path.exists(path):
				os.remove(path)

	async def snapshot(self, cid, p):
		cam, adapter = self._camera(p["camera"])
		jpeg = await adapter.get_snapshot(cam) if adapter else None
		if not jpeg:
			raise RuntimeError("no snapshot from the camera")
		fd, path = tempfile.mkstemp(suffix=".jpg")
		with os.fdopen(fd, "wb") as fh:
			fh.write(jpeg)
		try:
			return {"file_url": await self.agent.erp.upload_command_file(cid, path, f"snapshot-{camera_key(cam['name'])}.jpg", "image/jpeg")}
		finally:
			os.remove(path)

	def _server_adapter(self, server):
		adapter = self.agent.adapters.get(server)
		if not adapter:
			raise ValueError(f"recorder {server} is not in this site's config yet (wait a minute and retry)")
		return adapter

	async def discover_channels(self, cid, p):
		channels = await self._server_adapter(p["server"]).discover()
		known = {int(c.get("channel_no") or 0) for c in (self.agent.site or {}).get("cameras", []) if c.get("server") == p["server"]}
		for ch in channels:
			ch["already"] = int(ch["channel_no"]) in known
		return {"channels": channels}

	async def test_connection(self, cid, p):
		return await self._server_adapter(p["server"]).health_check()

	async def enroll_face(self, cid, p):
		engine = self.agent.engine
		if not (engine and engine.faces is not None and engine.models.live.get("face_embedder") and engine.models.live.get("face_detector")):
			raise RuntimeError("faces are not enabled on this site's engine (licence, legal switch or models missing)")
		from cctv_agent.engine.imageops import crop, from_bytes

		vectors, quality = [], []
		for i in range(int(p.get("image_count") or 0)):
			img = from_bytes(await self.agent.erp.fetch_face_image(cid, i))
			faces = sorted(engine.models.live["face_detector"].detect(img), key=lambda d: -d[2])
			if not faces:
				quality.append(0)
				continue
			vectors.append(engine.models.live["face_embedder"].embed(crop(img, faces[0][0], pad=0.1)))
			quality.append(faces[0][2])
		if not vectors:
			raise RuntimeError("no usable face found in the images - use clear, frontal photos")
		engine.faces.enroll(p["person_profile"], vectors)
		return {"embedding_ref": f"{self.agent.cfg.agent_id}:{p['person_profile']}", "quality": quality, "vectors": len(vectors)}

	async def delete_face(self, cid, p):
		engine = self.agent.engine
		n = engine.faces.delete(p["person_profile"]) if engine and engine.faces is not None else 0
		return {"deleted": n}

	async def sync_models(self, cid, p):
		if not self.agent.engine:
			raise RuntimeError("the engine is not running on this site")
		return {"models": await self.agent.engine.models.sync()}
