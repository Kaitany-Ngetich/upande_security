"""The site agent: one process per premises.

	config loop   pull site config from ERPNext; on change rebuild adapters,
	              restart event subscriptions, resync MediaMTX paths
	event tasks   one per recorder: subscribe, normalise, buffer (reconnect w/ backoff)
	uploader      buffer -> ERPNext in signed batches (<=100 events / 1 s)
	heartbeat     agent + camera + recorder health to ERPNext
	health        recorder reachability and clock offset
	auth hook     MediaMTX asks here before anyone watches

If ERPNext is unreachable, everything keeps running on the last cached
config and events wait in the buffer.
"""

import asyncio
import json
import logging
import os
import zoneinfo

from cctv_agent import __version__
from cctv_agent.adapters import adapter_for
from cctv_agent.buffer import Buffer
from cctv_agent.envelope import PRIORITY_TYPES
from cctv_agent.erp import ERP, AuthError, backoff
from cctv_agent.gateway import AuthServer, PathSync

log = logging.getLogger("cctv_agent")


class Agent:
	def __init__(self, cfg):
		self.cfg = cfg
		self.erp = ERP(cfg.erp_url, cfg.api_key, cfg.api_secret, cfg.agent_id, cfg.hmac_secret)
		self.buffer = Buffer(cfg.buffer_path, cfg.buffer_max_mb)
		self.site = self._load_cache()
		self.adapters = {}
		self.event_tasks = []
		self.server_health = {}
		self.paths = PathSync(cfg.mediamtx_api, cfg.transcode_h265, cfg.rtsp_port)
		self.tz = zoneinfo.ZoneInfo(cfg.site_timezone)

	# ---- site config ------------------------------------------------------------------
	def _load_cache(self):
		try:
			with open(self.cfg.site_config_cache) as fh:
				return json.load(fh)
		except (OSError, ValueError):
			return None

	def _save_cache(self, site):
		tmp = self.cfg.site_config_cache + ".tmp"
		fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # holds recorder passwords
		with os.fdopen(fd, "w") as fh:
			json.dump(site, fh)
		os.replace(tmp, self.cfg.site_config_cache)

	def token_secret(self):
		return ((self.site or {}).get("gateway") or {}).get("token_secret") or ""

	async def apply_site(self, site):
		for t in self.event_tasks:
			t.cancel()
		for a in self.adapters.values():
			await a.close()
		self.site = site
		self.adapters = {s["name"]: adapter_for(s, site["site"], self.tz) for s in site.get("servers", [])}
		for name, adapter in self.adapters.items():
			cams = [c for c in site.get("cameras", []) if c.get("server") == name]
			if cams:
				self.event_tasks.append(asyncio.create_task(self.event_loop(adapter, cams), name=f"events:{name}"))
		try:
			n = await self.paths.apply(await self.paths.desired(site.get("cameras", []), self.adapters))
			log.info("MediaMTX: %s live paths", n)
		except Exception as e:
			log.warning("MediaMTX path sync failed: %s", e)

	async def config_loop(self):
		attempt = 0
		if self.site:
			await self.apply_site(self.site)
		while True:
			try:
				site = await self.erp.get_site_config()
				if not self.site or site.get("config_version") != self.site.get("config_version"):
					log.info("site config v%s", site.get("config_version"))
					self._save_cache(site)
					await self.apply_site(site)
				attempt = 0
				await asyncio.sleep(self.cfg.config_poll_seconds)
			except AuthError as e:
				log.error("ERPNext refused the agent (check API key, signing secret, clock): %s", e)
				await asyncio.sleep(300)
			except Exception as e:
				attempt += 1
				log.warning("config pull failed: %s", e)
				await asyncio.sleep(backoff(attempt))

	# ---- events -----------------------------------------------------------------------
	async def on_event(self, ev, image=None):
		if image and self.cfg.upload_snapshots:
			try:
				ev["snapshot_ref"] = await self.erp.upload_snapshot(image, f"{ev['event_id']}.jpg")
			except Exception as e:
				log.debug("snapshot upload skipped: %s", e)
		self.buffer.put(ev, 0 if ev["event_type"] in PRIORITY_TYPES else 1)

	async def event_loop(self, adapter, cams):
		attempt = 0
		while True:
			try:
				log.info("subscribing to %s (%s)", adapter.server.get("name"), adapter.brand)
				await adapter.subscribe_events(cams, self.on_event)
				attempt = 0
			except asyncio.CancelledError:
				raise
			except Exception as e:
				attempt += 1
				log.warning("event stream %s dropped: %s", adapter.server.get("name"), e)
			await asyncio.sleep(backoff(attempt, base=1))

	async def uploader(self):
		attempt = 0
		while True:
			batch = self.buffer.take(self.cfg.batch_size)
			if not batch:
				await asyncio.sleep(self.cfg.batch_interval_ms / 1000)
				continue
			try:
				done, retry_after = await self.erp.ingest(batch)
				self.buffer.ack(done)
				if retry_after:
					await asyncio.sleep(retry_after)
				elif not done:
					attempt += 1
					await asyncio.sleep(backoff(attempt))
				else:
					attempt = 0
			except AuthError as e:
				log.error("ingest refused: %s", e)
				await asyncio.sleep(300)
			except Exception as e:
				attempt += 1
				self.buffer.bump([ev["event_id"] for ev in batch])
				log.warning("ingest failed (%s queued): %s", self.buffer.depth(), e)
				await asyncio.sleep(backoff(attempt))

	# ---- health -----------------------------------------------------------------------
	async def health_loop(self):
		while True:
			for name, adapter in list(self.adapters.items()):
				try:
					self.server_health[name] = await adapter.health_check()
					off = self.server_health[name].get("time_offset_seconds")
					if off is not None:
						adapter.offset = off
						if abs(off) > 2:
							log.warning("%s clock is %.1fs off - fix NTP on the recorder", name, off)
				except Exception as e:
					self.server_health[name] = {"status": "Offline", "error": str(e)[:100]}
			await asyncio.sleep(self.cfg.health_seconds)

	async def heartbeat_loop(self):
		while True:
			try:
				servers = [{"server": n, **h} for n, h in self.server_health.items()]
				up = {n for n, h in self.server_health.items() if h.get("status") == "Online"}
				cameras = [{"camera": c["name"], "state": "online" if c.get("server") in up else "offline"}
					for c in (self.site or {}).get("cameras", [])]
				load = os.getloadavg()[0] / (os.cpu_count() or 1) * 100
				await self.erp.heartbeat(version=__version__, queue_depth=self.buffer.depth(), cpu=round(min(load, 100), 1),
					cameras=cameras, servers=servers)
			except Exception as e:
				log.warning("heartbeat failed: %s", e)
			await asyncio.sleep(self.cfg.heartbeat_seconds)

	async def run(self):
		await AuthServer(self.token_secret, self.cfg.auth_listen).start()
		await asyncio.gather(self.config_loop(), self.uploader(), self.health_loop(), self.heartbeat_loop())
