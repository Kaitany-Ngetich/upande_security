"""Site survey: interrogate one recorder (or camera) and judge how it fits.

Every request is recorded (endpoint, HTTP status, time, error) so the report
shows exactly which parts of the device's API work - the "API coverage" a
developer needs - alongside what the device says about itself.
"""

import asyncio
import json
import shutil
import time
from datetime import datetime, timezone


class Probe:
	"""Wraps the adapter's HTTP client and logs every call."""

	def __init__(self, adapter):
		self.a = adapter
		self.calls = []

	async def request(self, method, path, label, **kw):
		url = path if path.startswith("http") else self.a.base + path
		t0 = time.monotonic()
		entry = {"what": label, "endpoint": path.split("?")[0], "method": method}
		try:
			r = await self.a.http.request(method, url, timeout=15, **kw)
			entry.update(status=r.status_code, ok=r.status_code < 400, ms=int((time.monotonic() - t0) * 1000))
			if r.status_code >= 400:
				entry["error"] = r.text[:160].strip()
			self.calls.append(entry)
			return r if r.status_code < 400 else None
		except Exception as e:
			entry.update(status=None, ok=False, ms=int((time.monotonic() - t0) * 1000), error=f"{type(e).__name__}: {e}"[:160])
			self.calls.append(entry)
			return None

	async def get(self, path, label, **kw):
		return await self.request("GET", path, label, **kw)


def blank_report(server):
	return {
		"schema": "cctv-survey/1",
		"surveyed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
		"target": {"brand": server.get("brand"), "host": server.get("host"), "port": server.get("port"), "name": server.get("name")},
		"device": {}, "status": {}, "channels": [], "storage": [], "recording": {}, "events": {"device": [], "by_channel": {}},
		"capabilities": {}, "time": {}, "logs": {"summary": {}, "recent": []}, "api": [], "streams_probed": [],
		"findings": [], "verdict": None,
	}


async def ffprobe(url, timeout=12):
	"""Codec / resolution / fps of an RTSP stream (needs ffprobe on the machine)."""
	if not shutil.which("ffprobe"):
		return {"error": "ffprobe not installed"}
	proc = await asyncio.create_subprocess_exec("ffprobe", "-v", "error", "-rtsp_transport", "tcp", "-select_streams", "v:0",
		"-show_entries", "stream=codec_name,width,height,avg_frame_rate,profile", "-of", "json", url,
		stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
	try:
		out, err = await asyncio.wait_for(proc.communicate(), timeout)
	except asyncio.TimeoutError:
		proc.kill()
		return {"error": "no answer in time"}
	if proc.returncode:
		return {"error": err.decode(errors="replace").strip()[:160] or "failed"}
	s = (json.loads(out or "{}").get("streams") or [{}])[0]
	num, _, den = (s.get("avg_frame_rate") or "0/1").partition("/")
	fps = round(float(num) / float(den or 1), 1) if float(den or 1) else None
	return {"codec": s.get("codec_name"), "profile": s.get("profile"), "width": s.get("width"), "height": s.get("height"), "fps": fps}


# ------------------------------------------------------------------ judging the fit

EVENT_NEEDS = {
	"plate_read": "number plates (ANPR)", "line_crossing": "line crossing", "zone_intrusion": "intrusion / restricted zone",
	"motion": "motion", "face_match": "face recognition", "person_detected": "person detection", "tamper": "tamper",
	"video_loss": "video loss", "door_state": "door / alarm input", "access_event": "access control",
}


def judge(rep):
	"""Findings (level, topic, text) and an overall verdict."""
	f = []

	def add(level, topic, text):
		f.append({"level": level, "topic": topic, "text": text})

	api = rep["api"]
	if not any(c["ok"] for c in api):
		add("blocker", "Access", "The device did not answer any API call - wrong address/port, credentials, or the API is disabled. Check reachability and enable ISAPI / CGI / ONVIF on the device.")
	auth = [c for c in api if c.get("status") in (401, 403)]
	if auth and len(auth) == len([c for c in api if c.get("status")]):
		add("blocker", "Access", "Every call was refused (401/403): the account is wrong or lacks rights. Create a dedicated integration user with view, playback and event rights.")

	chans = rep["channels"]
	off = [c for c in chans if c.get("online") is False]
	if chans:
		add("info", "Cameras", f"{len(chans)} channel(s), {len(chans) - len(off)} online.")
	if off:
		add("warn", "Cameras", "Offline: " + ", ".join(c.get("name") or str(c.get("channel_no")) for c in off) + ".")
	codecs = {(s.get("codec") or "").upper() for c in chans for s in (c.get("main"), c.get("sub")) if s and s.get("codec")}
	if codecs and all("265" in x or "HEVC" in x for x in codecs):
		add("warn", "Streams", "Every stream is H.265: most browsers cannot play it. Switch the sub-streams to H.264 on the recorder, or set transcode_h265 on the agent (costs CPU).")
	elif any("265" in x or "HEVC" in x for x in codecs):
		subs = {(c.get("sub") or {}).get("codec", "").upper() for c in chans if c.get("sub")}
		if subs and not any("265" in x or "HEVC" in x for x in subs):
			add("ok", "Streams", "Main streams use H.265 but sub-streams are H.264 - live grids will play in every browser.")
		else:
			add("warn", "Streams", "Some sub-streams are H.265: set them to H.264 for browser playback.")
	lowres = [c for c in chans if (c.get("main") or {}).get("height") and int(c["main"]["height"]) < 720]
	if lowres:
		add("info", "Streams", f"{len(lowres)} camera(s) under 720p main stream: fine for overview, too low for plates or faces.")

	disks = rep["storage"]
	bad = [d for d in disks if str(d.get("status", "")).lower() not in ("ok", "normal", "success", "idle", "")]
	if not disks:
		add("warn", "Recording", "No disk information returned - cannot confirm the recorder is storing footage (needed for alert playback).")
	elif bad:
		add("blocker", "Recording", "Disk problem: " + ", ".join(f"{d.get('name')}: {d.get('status')}" for d in bad) + ". Footage may be missing.")
	else:
		total = sum(float(d.get("capacity_gb") or 0) for d in disks)
		add("ok", "Recording", f"{len(disks)} disk(s), {round(total)} GB, all healthy.")
	modes = rep["recording"].get("modes") or {}
	if modes:
		cont = sum(1 for m in modes.values() if str(m).lower() in ("continuous", "cmr", "always", "schedule"))
		if cont < len(modes):
			add("warn", "Recording", f"{len(modes) - cont} channel(s) record on events only: alert playback can find gaps. Use continuous recording on gate, dock and restricted-area cameras.")

	off_s = rep["time"].get("offset_seconds")
	if off_s is not None:
		if abs(off_s) > 2:
			add("warn", "Clock", f"Device clock is {off_s:+.0f} s off. Turn on NTP - playback for alerts would land at the wrong moment. (The agent corrects for it, but NTP is better.)")
		else:
			add("ok", "Clock", f"Clock within {abs(off_s):.1f} s.")
	if rep["time"].get("ntp") is False:
		add("warn", "Clock", "NTP is off on the device.")

	have = set(rep["events"].get("normalised") or [])
	if have:
		add("info", "Events", "Can send: " + ", ".join(EVENT_NEEDS.get(e, e) for e in sorted(have)) + ".")
	if "plate_read" not in have:
		add("info", "Events", "No number-plate events: plates need a plate-capable camera at the gate, or the own analytics engine on its stream.")
	if "line_crossing" not in have and "zone_intrusion" not in have:
		add("info", "Events", "No line-crossing / intrusion events: restricted-zone alerts will rely on motion or the own engine.")
	pb = rep["capabilities"].get("playback")
	if pb is False:
		add("warn", "Playback", "Recorder playback over RTSP is not available through this API: alerts will show snapshots, not footage.")

	logs = rep["logs"]["summary"]
	for key, label in (("hdd", "disk errors"), ("abnormal_reboot", "abnormal reboots"), ("video_loss", "video-loss events"),
			("network", "network drops / IP conflicts"), ("illegal_login", "failed / illegal logins"), ("record", "recording failures")):
		if logs.get(key):
			add("warn" if key != "illegal_login" else "info", "Device log", f"{logs[key]} {label} in the period.")

	levels = {x["level"] for x in f}
	verdict = "Not ready" if "blocker" in levels else "Ready with fixes" if "warn" in levels else "Ready"
	rep["findings"], rep["verdict"] = f, verdict
	return rep
