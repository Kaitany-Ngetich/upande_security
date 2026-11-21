"""Dahua NVRs and cameras over the HTTP API (CGI).

Verify against the real firmware - these are the standard paths:

	live      rtsp://host:554/cam/realmonitor?channel=<ch>&subtype=0 (main) | 1 (sub)
	playback  rtsp://host:554/cam/playback?channel=<ch>&starttime=YYYY_MM_DD_HH_MM_SS&endtime=...
	snapshot  /cgi-bin/snapshot.cgi?channel=<ch>
	events    /cgi-bin/eventManager.cgi?action=attach&codes=[All]&heartbeat=5  (multipart)
	info      /cgi-bin/magicBox.cgi?action=getDeviceType | getSoftwareVersion
	time      /cgi-bin/global.cgi?action=getCurrentTime

Dahua playback times are the recorder's LOCAL time, so the site's time zone
(from the agent config) is applied.
"""

import json
import logging
import re
from datetime import datetime, timedelta, timezone

from cctv_agent.adapters.base import CameraAdapter
from cctv_agent.adapters.multipart import MultipartStream, boundary_of
from cctv_agent.envelope import line_direction, make_event, plate_direction, to_utc

log = logging.getLogger("cctv_agent.dahua")

EVENT_MAP = {
	"TrafficJunction": "plate_read", "ANPR": "plate_read", "TrafficParkingSpaceParking": "plate_read",
	"TrafficSnap": "plate_read", "TrafficVehicleRoute": "plate_read",
	"CrossLineDetection": "line_crossing", "CrossRegionDetection": "zone_intrusion", "SmartMotionHuman": "person_detected",
	"VideoMotion": "motion", "VideoLoss": "video_loss", "VideoBlind": "tamper", "SceneChange": "tamper",
	"FaceRecognition": "face_match", "FaceDetection": "person_detected",
	"AccessControl": "access_event", "AlarmLocal": "door_state", "DoorStatus": "door_state",
	"RecordFailure": "recording_gap", "StorageFailure": "recording_gap",
}
_EVENT_RE = re.compile(r"Code=(?P<code>[^;]+);action=(?P<action>[^;]+);index=(?P<index>\d+)(?:;data=(?P<data>\{.*\}))?", re.S)


class DahuaAdapter(CameraAdapter):
	brand = "Dahua"

	def __init__(self, server, site, site_tz=None):
		super().__init__(server, site)
		self.tz = site_tz or timezone(timedelta(hours=3))

	def capabilities(self):
		return {**super().capabilities(), "anpr": True, "face": True, "ptz": True}

	def get_stream_uri(self, camera, profile="sub"):
		ch = int(camera.get("channel_no") or 1)
		return self._rtsp(f"/cam/realmonitor?channel={ch}&subtype={0 if profile == 'main' else 1}")

	def get_playback_uri(self, camera, start_utc, end_utc):
		def local(t):
			return (t + timedelta(seconds=self.offset)).astimezone(self.tz).strftime("%Y_%m_%d_%H_%M_%S")
		return self._rtsp(f"/cam/playback?channel={int(camera.get('channel_no') or 1)}&starttime={local(start_utc)}&endtime={local(end_utc)}")

	async def get_snapshot(self, camera):
		r = await self.http.get(f"{self.base}/cgi-bin/snapshot.cgi?channel={int(camera.get('channel_no') or 1)}")
		return r.content if r.status_code == 200 and r.headers.get("content-type", "").startswith("image") else None

	async def device_time(self):
		r = await self.http.get(f"{self.base}/cgi-bin/global.cgi?action=getCurrentTime")
		r.raise_for_status()
		m = re.search(r"result=(.+)", r.text)
		return datetime.strptime(m.group(1).strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=self.tz) if m else None

	async def health_check(self):
		try:
			kv = {}
			for action in ("getDeviceType", "getSoftwareVersion"):
				r = await self.http.get(f"{self.base}/cgi-bin/magicBox.cgi?action={action}")
				r.raise_for_status()
				for line in r.text.splitlines():
					if "=" in line:
						k, v = line.split("=", 1)
						kv[k.strip()] = v.strip()
			return {"status": "Online", "model": kv.get("type"), "firmware": kv.get("version"),
				"time_offset_seconds": await self.measure_offset()}
		except Exception as e:
			log.warning("%s health check failed: %s", self.server.get("name"), e)
			return {"status": "Offline"}

	async def subscribe_events(self, cameras, on_event):
		url = f"{self.base}/cgi-bin/eventManager.cgi?action=attach&codes=[All]&heartbeat=5"
		async with self.http.stream("GET", url) as resp:
			resp.raise_for_status()
			parser = MultipartStream(boundary_of(resp.headers.get("content-type")) or "myboundary")
			async for chunk in resp.aiter_bytes():
				for headers, body in parser.feed(chunk):
					if headers.get("content-type", "").startswith("image"):
						continue
					for ev in self.normalise(body.decode("utf-8", "replace"), cameras):
						await on_event(ev, None)

	# ---- parsing (pure, unit-tested) --------------------------------------------------
	def normalise(self, text, cameras):
		m = _EVENT_RE.search(text or "")
		if not m or m.group("code") == "Heartbeat":
			return []
		code, action = m.group("code"), m.group("action")
		kind = EVENT_MAP.get(code)
		if not kind:
			return []
		data_raw = {}
		if m.group("data"):
			try:
				data_raw = json.loads(m.group("data"))
			except ValueError:
				data_raw = {}
		# Start/Pulse are the event; Stop only matters for doors (closed).
		if action == "Stop" and kind != "door_state":
			return []
		cam = self.camera_for_channel(cameras, int(m.group("index")) + 1)
		if not cam:
			return []
		utc = data_raw.get("UTC")
		when = to_utc(datetime.fromtimestamp(float(utc), timezone.utc) if utc else None, self.offset)
		data, conf = {}, None
		if kind == "plate_read":
			car = data_raw.get("TrafficCar") or {}
			obj = data_raw.get("Object") or {}
			plate = car.get("PlateNumber") or obj.get("Text")
			if not plate:
				return []
			conf = (car.get("Confidence") or obj.get("Confidence") or 0) / 100 if (car.get("Confidence") or obj.get("Confidence")) else None
			data = {"plate": plate, "direction": plate_direction(car.get("Direction") or data_raw.get("Direction"), cam.get("direction_in")),
				"vehicle_type": car.get("VehicleType") or (data_raw.get("Vehicle") or {}).get("Category"),
				"colour": car.get("VehicleColor"), "lane": data_raw.get("Lane")}
		elif kind == "line_crossing":
			data = {"direction": line_direction(data_raw.get("Direction"), cam.get("direction_in")), "line_id": data_raw.get("Name"),
				"object_class": (data_raw.get("Object") or {}).get("ObjectType")}
		elif kind == "zone_intrusion":
			data = {"roi_id": data_raw.get("Name"), "object_class": (data_raw.get("Object") or {}).get("ObjectType"),
				"dwell_seconds": data_raw.get("StayTime")}
		elif kind == "door_state":
			data = {"door_id": data_raw.get("Name") or m.group("index"), "state": "closed" if action == "Stop" else "open"}
		elif kind == "access_event":
			data = {"reader_id": data_raw.get("ReaderID"), "credential_ref": data_raw.get("UserID") or data_raw.get("CardNo"),
				"result": "granted" if int(data_raw.get("Status") or 0) == 1 else "denied", "employee_no": data_raw.get("UserID")}
		elif kind == "face_match":
			cands = data_raw.get("Candidates") or []
			if not cands:
				kind = "face_unknown"
			else:
				best = cands[0]
				person = best.get("Person") or {}
				conf = (best.get("Similarity") or 0) / 100
				data = {"person_ref": person.get("ID") or person.get("Name"), "similarity": conf}
		elif kind == "tamper":
			data = {"kind": code}
		return [make_event(self.site, cam["name"], kind, when, data, conf, offset_seconds=self.offset)]
