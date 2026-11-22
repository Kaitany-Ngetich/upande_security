"""MediaMTX on this box: who may watch (auth hook) and what paths exist (sync).

AUTH
mediamtx.yml sets authMethod: http, authHTTPAddress: http://127.0.0.1:8765/auth,
so MediaMTX asks this agent about every read/publish. A viewer must carry the
token ERPNext issued (as ?jwt=...), for exactly the path it opens. Publishing
and the API are allowed only from this machine (the on-demand ffmpeg runners).
A playback token is bound to the first IP that uses it, so a copied link is
useless elsewhere (HLS makes many requests, so strict single-use would break
it).

PATHS
live/<camera key>/<sub|main> are kept in step with ERPNext's camera list via
the MediaMTX API: pulled from the recorder on demand only, closed when idle,
nothing recorded. pb/... is one regex path in mediamtx.yml whose runOnDemand
starts cctv_agent.playback for the requested range.
"""

import logging
import time
import urllib.parse

import httpx
from aiohttp import web

from cctv_agent.envelope import camera_key
from cctv_agent.tokens import TokenError, verify

log = logging.getLogger("cctv_agent.gateway")
LOCAL = {"127.0.0.1", "::1", "localhost"}


class AuthServer:
	def __init__(self, get_secret, listen="127.0.0.1:8765"):
		self.get_secret = get_secret
		self.host, self.port = listen.rsplit(":", 1)
		self.bound = {}  # jti -> (ip, exp)

	def decide(self, req):
		"""Pure decision (unit-tested): True = allow."""
		action = req.get("action")
		ip = req.get("ip") or ""
		if action in ("publish", "api", "metrics", "pprof"):
			return ip in LOCAL
		if action not in ("read", "playback"):
			return False
		token = req.get("token") or dict(urllib.parse.parse_qsl(req.get("query") or "")).get("jwt") or req.get("password")
		try:
			claims = verify(token, self.get_secret())
		except TokenError as e:
			log.info("denied %s %s: %s", ip, req.get("path"), e)
			return False
		if claims.get("path") != req.get("path"):
			return False
		if claims.get("scope") == "playback" and not str(req.get("path", "")).startswith("pb/"):
			return False
		if claims.get("scope") == "live" and not str(req.get("path", "")).startswith("live/"):
			return False
		if claims.get("once"):
			now = time.time()
			self.bound = {k: v for k, v in self.bound.items() if v[1] > now}
			seen = self.bound.get(claims["jti"])
			if seen and seen[0] != ip:
				return False
			self.bound[claims["jti"]] = (ip, claims["exp"])
		return True

	async def _handle(self, request):
		try:
			body = await request.json()
		except Exception:
			return web.Response(status=400)
		return web.Response(status=200 if self.decide(body) else 401)

	async def start(self):
		app = web.Application()
		app.router.add_post("/auth", self._handle)
		runner = web.AppRunner(app, access_log=None)
		await runner.setup()
		await web.TCPSite(runner, self.host, int(self.port)).start()
		log.info("MediaMTX auth hook on %s:%s", self.host, self.port)
		return runner


class PathSync:
	"""Keep MediaMTX's live/* paths equal to the cameras ERPNext lists."""

	def __init__(self, api="http://127.0.0.1:9997", transcode_h265=False, rtsp_port=8554):
		self.api = api.rstrip("/")
		self.transcode_h265 = transcode_h265
		self.rtsp_port = rtsp_port
		self.http = httpx.AsyncClient(timeout=10)

	def path_conf(self, source, codec=None):
		if self.transcode_h265 and codec == "H.265":
			# Browsers play H.264 everywhere; H.265 only in some. Transcode on demand.
			cmd = (f"ffmpeg -hide_banner -loglevel error -rtsp_transport tcp -i {source} -an -c:v libx264 -preset veryfast "
				f"-tune zerolatency -g 50 -f rtsp rtsp://127.0.0.1:$RTSP_PORT/$MTX_PATH")
			return {"runOnDemand": cmd, "runOnDemandRestart": True, "runOnDemandCloseAfter": "15s"}
		return {"source": source, "sourceOnDemand": True, "sourceOnDemandCloseAfter": "15s", "rtspTransport": "tcp"}

	async def desired(self, cameras, adapters):
		"""{path name: conf} for every enabled camera, both profiles."""
		out = {}
		for cam in cameras:
			adapter = adapters.get(cam.get("server"))
			if not adapter:
				continue
			for profile in ("sub", "main"):
				try:
					src = await adapter.stream_uri(cam, profile) if hasattr(adapter, "stream_uri") else adapter.get_stream_uri(cam, profile)
				except Exception as e:
					log.warning("no %s stream for %s: %s", profile, cam.get("name"), e)
					continue
				out[f"live/{camera_key(cam['name'])}/{profile}"] = self.path_conf(src, cam.get("codec"))
		return out

	async def apply(self, desired):
		r = await self.http.get(f"{self.api}/v3/config/paths/list", params={"itemsPerPage": 1000})
		r.raise_for_status()
		existing = {p["name"] for p in r.json().get("items", [])}
		for name, conf in desired.items():
			verb = "replace" if name in existing else "add"
			resp = await self.http.post(f"{self.api}/v3/config/paths/{verb}/{name}", json=conf)
			if resp.status_code >= 400:
				log.warning("MediaMTX %s %s: %s", verb, name, resp.text[:200])
		for name in existing:
			if name.startswith("live/") and name not in desired:
				await self.http.delete(f"{self.api}/v3/config/paths/delete/{name}")
		return len(desired)
