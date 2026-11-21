"""Generic ONVIF devices (Profile S live + events; Profile G playback where present).

Plain SOAP over httpx with a WS-Security UsernameToken, so no heavy ONVIF
library is needed. Covers: device time, profiles -> RTSP URIs, snapshot URI,
and the PullPoint event subscription (motion, line crossing, field/intrusion,
tamper, digital input / door).

ONVIF has no standard plate-read event: plate reading on a generic ONVIF
camera needs the vendor adapter or the own analytics engine. Recorder
playback (Profile G GetReplayUri) differs a lot between devices; it is tried,
and reported as unsupported rather than guessed when it fails.
"""

import base64
import hashlib
import logging
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from cctv_agent.adapters.base import CameraAdapter
from cctv_agent.envelope import line_direction, make_event, to_utc

log = logging.getLogger("cctv_agent.onvif")

NS = {
	"s": "http://www.w3.org/2003/05/soap-envelope",
	"tds": "http://www.onvif.org/ver10/device/wsdl",
	"trt": "http://www.onvif.org/ver10/media/wsdl",
	"tev": "http://www.onvif.org/ver10/events/wsdl",
	"trp": "http://www.onvif.org/ver10/replay/wsdl",
	"tt": "http://www.onvif.org/ver10/schema",
	"wsnt": "http://docs.oasis-open.org/wsn/b-2",
	"wsa": "http://www.w3.org/2005/08/addressing",
}

TOPICS = [
	("RuleEngine/CellMotionDetector/Motion", "motion", "IsMotion"),
	("VideoSource/MotionAlarm", "motion", "State"),
	("RuleEngine/LineDetector/Crossed", "line_crossing", None),
	("RuleEngine/FieldDetector/ObjectsInside", "zone_intrusion", "IsInside"),
	("RuleEngine/MyRuleDetector/PeopleDetect", "person_detected", "IsPeople"),
	("VideoSource/GlobalSceneChange", "tamper", "State"),
	("VideoSource/ImageTooBlurry", "tamper", "State"),
	("VideoSource/SignalLoss", "video_loss", "State"),
	("Device/Trigger/DigitalInput", "door_state", "LogicalState"),
]


def _security(user, password):
	nonce = os.urandom(16)
	created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
	digest = base64.b64encode(hashlib.sha1(nonce + created.encode() + password.encode()).digest()).decode()
	return (
		'<Security s:mustUnderstand="1" xmlns="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd">'
		f"<UsernameToken><Username>{user}</Username>"
		'<Password Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest">'
		f"{digest}</Password>"
		f'<Nonce EncodingType="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary">{base64.b64encode(nonce).decode()}</Nonce>'
		f'<Created xmlns="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd">{created}</Created>'
		"</UsernameToken></Security>"
	)


def _envelope(body, user=None, password=None, extra_header=""):
	header = (_security(user, password) if user else "") + extra_header
	ns = " ".join(f'xmlns:{k}="{v}"' for k, v in NS.items())
	return f'<?xml version="1.0" encoding="UTF-8"?><s:Envelope {ns}><s:Header>{header}</s:Header><s:Body>{body}</s:Body></s:Envelope>'


class OnvifAdapter(CameraAdapter):
	brand = "ONVIF"

	def __init__(self, server, site):
		super().__init__(server, site)
		self.device_url = f"{self.base}/onvif/device_service"
		self.media_url = None
		self.events_url = None
		self.replay_url = None
		self.sources = []  # [[profile tokens of source 1], [source 2] ...] main first

	def capabilities(self):
		return {**super().capabilities(), "playback": bool(self.replay_url)}

	async def _call(self, url, body, auth=True, extra_header=""):
		payload = _envelope(body, self.user if auth else None, self.password, extra_header)
		r = await self.http.post(url, content=payload.encode(), headers={"Content-Type": "application/soap+xml; charset=utf-8"})
		if r.status_code >= 400:
			raise RuntimeError(f"ONVIF {url} -> {r.status_code}: {r.text[:200]}")
		return ET.fromstring(r.content)

	async def connect(self):
		caps = await self._call(self.device_url, '<tds:GetCapabilities><tds:Category>All</tds:Category></tds:GetCapabilities>')
		for path, attr in (("Media", "media_url"), ("Events", "events_url")):
			el = caps.find(f".//tt:{path}/tt:XAddr", NS)
			if el is not None:
				setattr(self, attr, el.text.strip())
		el = caps.find(".//tt:Extension//tt:Replay/tt:XAddr", NS) or caps.find(".//tt:Replay/tt:XAddr", NS)
		self.replay_url = el.text.strip() if el is not None else None
		profiles = await self._call(self.media_url, "<trt:GetProfiles/>")
		by_source = {}
		for p in profiles.findall(".//trt:Profiles", NS):
			src = p.find(".//tt:VideoSourceConfiguration/tt:SourceToken", NS)
			by_source.setdefault(src.text if src is not None else "default", []).append(p.get("token"))
		self.sources = list(by_source.values())

	def _profile(self, camera, profile):
		idx = max(0, int(camera.get("channel_no") or 1) - 1)
		tokens = self.sources[idx] if idx < len(self.sources) else (self.sources[0] if self.sources else [])
		if not tokens:
			raise RuntimeError("no ONVIF profiles")
		return tokens[0] if profile == "main" or len(tokens) == 1 else tokens[1]

	async def stream_uri(self, camera, profile="sub"):
		if not self.sources:
			await self.connect()
		res = await self._call(self.media_url,
			f'<trt:GetStreamUri><trt:StreamSetup><tt:Stream>RTP-Unicast</tt:Stream><tt:Transport><tt:Protocol>RTSP</tt:Protocol></tt:Transport></trt:StreamSetup>'
			f"<trt:ProfileToken>{self._profile(camera, profile)}</trt:ProfileToken></trt:GetStreamUri>")
		uri = res.find(".//tt:Uri", NS).text.strip()
		return self._with_credentials(uri)

	def _with_credentials(self, uri):
		if not self.user or "@" in uri.split("//", 1)[-1].split("/", 1)[0]:
			return uri
		import urllib.parse
		cred = f"{urllib.parse.quote(self.user, safe='')}:{urllib.parse.quote(self.password, safe='')}@"
		return uri.replace("rtsp://", "rtsp://" + cred, 1)

	def get_stream_uri(self, camera, profile="sub"):
		# ONVIF needs a SOAP round trip; the agent resolves it with stream_uri() when building paths.
		raise RuntimeError("use await stream_uri()")

	def get_playback_uri(self, camera, start_utc, end_utc):
		return None  # resolved asynchronously via replay_uri(); None = unsupported

	async def replay_uri(self, recording_token):
		if not self.replay_url:
			return None
		res = await self._call(self.replay_url,
			f'<trp:GetReplayUri><trp:StreamSetup><tt:Stream>RTP-Unicast</tt:Stream><tt:Transport><tt:Protocol>RTSP</tt:Protocol></tt:Transport></trp:StreamSetup>'
			f"<trp:RecordingToken>{recording_token}</trp:RecordingToken></trp:GetReplayUri>")
		el = res.find(".//trp:Uri", NS)
		return self._with_credentials(el.text.strip()) if el is not None else None

	async def get_snapshot(self, camera):
		if not self.sources:
			await self.connect()
		res = await self._call(self.media_url, f"<trt:GetSnapshotUri><trt:ProfileToken>{self._profile(camera, 'main')}</trt:ProfileToken></trt:GetSnapshotUri>")
		r = await self.http.get(res.find(".//tt:Uri", NS).text.strip())
		return r.content if r.status_code == 200 else None

	async def device_time(self):
		res = await self._call(self.device_url, "<tds:GetSystemDateAndTime/>", auth=False)
		d = res.find(".//tt:UTCDateTime", NS)
		if d is None:
			return None
		g = lambda p: int(d.find(p, NS).text)  # noqa: E731
		return datetime(g("tt:Date/tt:Year"), g("tt:Date/tt:Month"), g("tt:Date/tt:Day"), g("tt:Time/tt:Hour"),
			g("tt:Time/tt:Minute"), g("tt:Time/tt:Second"), tzinfo=timezone.utc)

	async def health_check(self):
		try:
			info = await self._call(self.device_url, "<tds:GetDeviceInformation/>")
			model = info.find(".//tds:Model", NS)
			fw = info.find(".//tds:FirmwareVersion", NS)
			return {"status": "Online", "model": model.text if model is not None else None,
				"firmware": fw.text if fw is not None else None, "time_offset_seconds": await self.measure_offset()}
		except Exception as e:
			log.warning("%s health check failed: %s", self.server.get("name"), e)
			return {"status": "Offline"}

	async def discover(self):
		await self.connect()
		return [{"channel_no": i + 1, "name": f"Video source {i + 1}", "main_stream": tokens[0], "sub_stream": tokens[1] if len(tokens) > 1 else tokens[0]}
			for i, tokens in enumerate(self.sources)]

	async def subscribe_events(self, cameras, on_event):
		if not self.events_url:
			await self.connect()
		res = await self._call(self.events_url, "<tev:CreatePullPointSubscription><tev:InitialTerminationTime>PT600S</tev:InitialTerminationTime></tev:CreatePullPointSubscription>")
		addr = res.find(".//wsa:Address", NS).text.strip()
		to = f'<wsa:To s:mustUnderstand="1">{addr}</wsa:To>'
		pulls = 0
		while True:
			msgs = await self._call(addr, "<tev:PullMessages><tev:Timeout>PT10S</tev:Timeout><tev:MessageLimit>50</tev:MessageLimit></tev:PullMessages>",
				extra_header=to)
			for ev in self.normalise(msgs, cameras):
				await on_event(ev, None)
			pulls += 1
			if pulls % 30 == 0:
				await self._call(addr, "<wsnt:Renew><wsnt:TerminationTime>PT600S</wsnt:TerminationTime></wsnt:Renew>", extra_header=to)

	# ---- parsing (pure, unit-tested) --------------------------------------------------
	def normalise(self, root, cameras):
		out = []
		for msg in root.findall(".//wsnt:NotificationMessage", NS):
			topic = (msg.findtext("wsnt:Topic", default="", namespaces=NS) or "").strip()
			match = next(((k, f) for t, k, f in TOPICS if topic.endswith(t)), None)
			if not match:
				continue
			kind, flag = match
			m = msg.find(".//tt:Message", NS)
			if m is None or m.get("PropertyOperation") == "Initialized":
				continue
			items = {si.get("Name"): si.get("Value") for si in m.findall(".//tt:SimpleItem", NS)}
			if flag and str(items.get(flag, "true")).lower() == "false" and kind != "door_state":
				continue
			source = items.get("VideoSourceConfigurationToken") or items.get("VideoSourceToken") or items.get("InputToken") or ""
			num = re.search(r"(\d+)$", source)
			cam = None
			if num:
				# Tokens are numbered from 0 on some devices and from 1 on others.
				n = int(num.group(1))
				cam = self.camera_for_channel(cameras, n) or self.camera_for_channel(cameras, n + 1)
			if not cam and len(cameras) == 1:
				cam = cameras[0]
			if not cam:
				continue
			when_raw = m.get("UtcTime")
			when = to_utc(datetime.fromisoformat(when_raw.replace("Z", "+00:00")) if when_raw else None, self.offset)
			data = {}
			if kind == "line_crossing":
				data = {"direction": line_direction(items.get("Direction"), cam.get("direction_in"))}
			elif kind == "door_state":
				data = {"door_id": source or "1", "state": "open" if str(items.get(flag)).lower() == "true" else "closed"}
			out.append(make_event(self.site, cam["name"], kind, when, data, offset_seconds=self.offset))
		return out
