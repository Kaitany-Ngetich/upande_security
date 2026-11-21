"""One interface for every recorder brand.

A server dict comes from ERPNext's get_site_config (CCTV Server: brand, host,
port, use_tls, verify_tls, username, password, time_offset_seconds); a camera
dict is a CCTV Camera row (name, channel_no, main_stream, sub_stream, role,
direction_in, ...).

Adapters return RTSP URLs WITH credentials - those go only into MediaMTX on
this box, never to ERPNext or a browser.
"""

import urllib.parse
from datetime import datetime, timezone

import httpx


class CameraAdapter:
	brand = "generic"
	rtsp_port = 554

	def __init__(self, server, site):
		self.server = server
		self.site = site
		scheme = "https" if server.get("use_tls") else "http"
		self.base = f"{scheme}://{server['host']}:{server.get('port') or (443 if server.get('use_tls') else 80)}"
		self.user = server.get("username") or ""
		self.password = server.get("password") or ""
		self.offset = float(server.get("time_offset_seconds") or 0)
		self.http = httpx.AsyncClient(auth=httpx.DigestAuth(self.user, self.password), verify=bool(server.get("verify_tls", 1)),
			timeout=httpx.Timeout(15, read=None))

	async def close(self):
		await self.http.aclose()

	# ---- capabilities -------------------------------------------------------------
	def capabilities(self):
		return {"live": True, "playback": True, "events": True, "snapshot": True, "anpr": False, "face": False, "ptz": False}

	# ---- streams ------------------------------------------------------------------
	def _rtsp(self, path_and_query):
		cred = f"{urllib.parse.quote(self.user, safe='')}:{urllib.parse.quote(self.password, safe='')}@" if self.user else ""
		return f"rtsp://{cred}{self.server['host']}:{self.rtsp_port}{path_and_query}"

	def get_stream_uri(self, camera, profile="sub"):
		raise NotImplementedError

	def get_playback_uri(self, camera, start_utc, end_utc):
		raise NotImplementedError

	async def get_snapshot(self, camera):
		return None

	# ---- device -------------------------------------------------------------------
	async def device_time(self):
		"""The device's clock as an aware datetime (for the offset check)."""
		return None

	async def measure_offset(self):
		"""Device clock minus true time, in seconds (None if unknown)."""
		t0 = datetime.now(timezone.utc)
		dev = await self.device_time()
		if dev is None:
			return None
		t1 = datetime.now(timezone.utc)
		mid = t0 + (t1 - t0) / 2
		return round((dev - mid).total_seconds(), 1)

	async def health_check(self):
		"""{'status': Online|Offline|Degraded, 'model', 'firmware', 'time_offset_seconds', 'recording_mode'}"""
		raise NotImplementedError

	# ---- events -------------------------------------------------------------------
	async def subscribe_events(self, cameras, on_event):
		"""Run until cancelled; call on_event(envelope) for each normalised event.
		Raise on disconnect - the agent reconnects with backoff."""
		raise NotImplementedError

	def camera_for_channel(self, cameras, channel):
		for c in cameras:
			if int(c.get("channel_no") or 0) == int(channel):
				return c
		return None
