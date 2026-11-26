"""The agent's only link to ERPNext: outbound HTTPS, every request signed.

Auth = the CCTV Agent API user's key:secret, plus
	X-CCTV-Agent / X-CCTV-Timestamp / X-CCTV-Signature
where the signature is HMAC-SHA256(agent secret, "<timestamp>." + raw body),
exactly what upande_security/cctv/ingest.py checks.
"""

import asyncio
import hashlib
import hmac
import logging
import random
import time

import httpx

log = logging.getLogger("cctv_agent.erp")
M = "/api/method/upande_security.cctv.ingest."


class AuthError(Exception):
	"""Credentials, signature or clock wrong: retrying blindly will not help."""


class ERP:
	def __init__(self, url, api_key, api_secret, agent_id, hmac_secret, timeout=20):
		self.url = url.rstrip("/")
		self.agent_id = agent_id
		self.hmac_secret = hmac_secret.encode()
		self.client = httpx.AsyncClient(timeout=timeout, headers={"Authorization": f"token {api_key}:{api_secret}",
			"Accept": "application/json", "User-Agent": "upande-cctv-agent"})

	async def close(self):
		await self.client.aclose()

	def _sign(self, request):
		body = request.read() if request.method != "GET" else b""
		ts = str(int(time.time()))
		request.headers["X-CCTV-Agent"] = self.agent_id
		request.headers["X-CCTV-Timestamp"] = ts
		request.headers["X-CCTV-Signature"] = hmac.new(self.hmac_secret, ts.encode() + b"." + body, hashlib.sha256).hexdigest()
		return request

	async def _send(self, method, name, **kw):
		req = self._sign(self.client.build_request(method, self.url + M + name, **kw))
		resp = await self.client.send(req)
		if resp.status_code in (401, 403):
			raise AuthError(f"{resp.status_code}: {resp.text[:200]}")
		return resp

	async def get_site_config(self):
		resp = await self._send("GET", "get_site_config")
		resp.raise_for_status()
		return resp.json()["message"]

	async def heartbeat(self, **payload):
		resp = await self._send("POST", "agent_heartbeat", json=payload)
		resp.raise_for_status()
		return resp.json()["message"]

	async def upload_snapshot(self, jpeg, filename="snapshot.jpg"):
		# Raw body (not multipart) so the signature covers exactly the bytes sent.
		resp = await self._send("POST", "upload_snapshot", params={"filename": filename}, content=jpeg,
			headers={"Content-Type": "application/octet-stream"})
		resp.raise_for_status()
		return resp.json()["message"]["snapshot_ref"]

	# ---- commands (ERPNext -> agent, polled) ------------------------------------
	C = "/api/method/upande_security.cctv.commands."

	async def _cmd(self, method, name, **kw):
		req = self._sign(self.client.build_request(method, self.url + self.C + name, **kw))
		resp = await self.client.send(req)
		if resp.status_code in (401, 403):
			raise AuthError(f"{resp.status_code}: {resp.text[:200]}")
		resp.raise_for_status()
		return resp.json()["message"]

	async def poll_commands(self):
		return (await self._cmd("GET", "poll_commands"))["commands"]

	async def command_result(self, command, status, result=None, error=None):
		return await self._cmd("POST", "command_result", json={"command": command, "status": status, "result": result or {}, "error": error})

	async def upload_command_file(self, command, path, filename, mime):
		with open(path, "rb") as fh:
			data = fh.read()
		return (await self._cmd("POST", "upload_command_file", params={"command": command, "filename": filename},
			content=data, headers={"Content-Type": "application/octet-stream"}))["file_url"]

	async def fetch_face_image(self, command, index):
		import base64

		r = await self._cmd("GET", "fetch_face_image", params={"command": command, "index": index})
		return base64.b64decode(r["content"])

	async def engine_models(self):
		resp = await self._send("GET", "engine_models")
		resp.raise_for_status()
		return resp.json()["message"]["models"]

	async def download_model(self, name, dest):
		req = self._sign(self.client.build_request("GET", self.url + M + "download_model", params={"name": name}))
		async with self.client.stream(req.method, req.url, headers=req.headers) as resp:
			resp.raise_for_status()
			with open(dest, "wb") as fh:
				async for chunk in resp.aiter_bytes():
					fh.write(chunk)
		return dest

	async def ingest(self, events):
		"""Send one batch. Returns (done_ids, retry_after_seconds or None).

		done = accepted + duplicate + rejected (a rejected event will never
		be accepted, so keeping it would block the queue - it is logged)."""
		resp = await self._send("POST", "ingest_events", json={"events": events})
		if resp.status_code == 429:
			return [], float(resp.headers.get("Retry-After") or 30)
		if resp.status_code == 413 and len(events) > 1:
			half = len(events) // 2
			a, ra = await self.ingest(events[:half])
			b, rb = await self.ingest(events[half:])
			return a + b, ra or rb
		if resp.status_code >= 500:
			return [], None
		if resp.status_code != 200:
			log.warning("ingest refused (%s): %s", resp.status_code, resp.text[:300])
			return [], 60.0
		done = []
		for r in resp.json()["message"]["results"]:
			if r["status"] == "rejected":
				log.warning("event %s rejected: %s", r.get("event_id"), r.get("ref"))
			done.append(r["event_id"])
		return done, None


def backoff(attempt, base=2.0, cap=300.0):
	"""Exponential backoff with jitter."""
	return min(cap, base * (2 ** min(attempt, 8))) * (0.5 + random.random() / 2)


async def sleep(seconds):
	await asyncio.sleep(seconds)
