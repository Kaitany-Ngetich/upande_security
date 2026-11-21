"""Hikvision NVRs and cameras over ISAPI.

Verify against the real device's firmware - paths below are the ISAPI
defaults used across current NVR/IPC lines:

	live      rtsp://host:554/Streaming/Channels/<ch>01 (main) | <ch>02 (sub)
	playback  rtsp://host:554/Streaming/tracks/<ch>01?starttime=YYYYMMDDTHHMMSSZ&endtime=...
	snapshot  /ISAPI/Streaming/channels/<ch>01/picture
	events    /ISAPI/Event/notification/alertStream   (multipart, long-lived)
	info      /ISAPI/System/deviceInfo, /ISAPI/System/time

On an NVR, <ch> is the NVR's channel number (D1 = 1). On a standalone camera it is 1.
"""

import json
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from cctv_agent.adapters.base import CameraAdapter
from cctv_agent.adapters.multipart import MultipartStream, boundary_of
from cctv_agent.envelope import line_direction, make_event, plate_direction, to_utc

log = logging.getLogger("cctv_agent.hikvision")

# ISAPI eventType -> normalised type
EVENT_MAP = {
	"anpr": "plate_read", "vehicledetection": "plate_read",
	"linedetection": "line_crossing", "fielddetection": "zone_intrusion", "regionentrance": "zone_intrusion",
	"vmd": "motion", "motiondetection": "motion",
	"videoloss": "video_loss", "shelteralarm": "tamper", "tamperdetection": "tamper", "scenechangedetection": "tamper",
	"facesnap": "person_detected", "facedetection": "person_detected", "humanrecognition": "person_detected",
	"facesnapmatch": "face_match", "facelibmatch": "face_match", "facesnapnomatch": "face_unknown",
	"io": "door_state", "accesscontrollerevent": "access_event",
}


def _strip_ns(root):
	for el in root.iter():
		if "}" in el.tag:
			el.tag = el.tag.split("}", 1)[1]
	return root


def _t(el, path):
	found = el.find(path)
	return found.text.strip() if found is not None and found.text else None


def parse_time(value):
	if not value:
		return None
	v = value.strip().replace("Z", "+00:00")
	try:
		return datetime.fromisoformat(v)
	except ValueError:
		return None


class HikvisionAdapter(CameraAdapter):
	brand = "Hikvision"

	def capabilities(self):
		return {**super().capabilities(), "anpr": True, "face": True, "ptz": True}

	def _track(self, camera, profile):
		stream = camera.get("main_stream") if profile == "main" else camera.get("sub_stream")
		if stream and str(stream).isdigit():
			return str(stream)
		return f"{int(camera.get('channel_no') or 1)}{'01' if profile == 'main' else '02'}"

	def get_stream_uri(self, camera, profile="sub"):
		return self._rtsp(f"/Streaming/Channels/{self._track(camera, profile)}")

	def get_playback_uri(self, camera, start_utc, end_utc):
		# Recorder time = true time + device offset
		from datetime import timedelta
		s = (start_utc + timedelta(seconds=self.offset)).strftime("%Y%m%dT%H%M%SZ")
		e = (end_utc + timedelta(seconds=self.offset)).strftime("%Y%m%dT%H%M%SZ")
		return self._rtsp(f"/Streaming/tracks/{int(camera.get('channel_no') or 1)}01?starttime={s}&endtime={e}")

	async def get_snapshot(self, camera):
		r = await self.http.get(f"{self.base}/ISAPI/Streaming/channels/{int(camera.get('channel_no') or 1)}01/picture")
		return r.content if r.status_code == 200 and r.headers.get("content-type", "").startswith("image") else None

	async def device_time(self):
		r = await self.http.get(f"{self.base}/ISAPI/System/time")
		r.raise_for_status()
		return parse_time(_t(_strip_ns(ET.fromstring(r.content)), "localTime"))

	async def health_check(self):
		try:
			r = await self.http.get(f"{self.base}/ISAPI/System/deviceInfo")
			r.raise_for_status()
			info = _strip_ns(ET.fromstring(r.content))
			offset = await self.measure_offset()
			return {"status": "Online", "model": _t(info, "model"), "firmware": _t(info, "firmwareVersion"),
				"time_offset_seconds": offset}
		except Exception as e:
			log.warning("%s health check failed: %s", self.server.get("name"), e)
			return {"status": "Offline"}

	async def subscribe_events(self, cameras, on_event):
		async with self.http.stream("GET", f"{self.base}/ISAPI/Event/notification/alertStream") as resp:
			resp.raise_for_status()
			parser = MultipartStream(boundary_of(resp.headers.get("content-type")) or "boundary")
			pending_image = None
			async for chunk in resp.aiter_bytes():
				for headers, body in parser.feed(chunk):
					ctype = headers.get("content-type", "")
					if ctype.startswith("image"):
						pending_image = body  # ANPR/face pictures follow their event part
						continue
					for ev in self.normalise(body, ctype, cameras):
						await on_event(ev, pending_image)
					pending_image = None

	# ---- parsing (pure, unit-tested) --------------------------------------------------
	def normalise(self, body, ctype, cameras):
		try:
			if "json" in ctype or body.lstrip().startswith(b"{"):
				return self._from_json(json.loads(body), cameras)
			return self._from_xml(_strip_ns(ET.fromstring(body)), cameras)
		except Exception as e:
			log.debug("unparsed ISAPI part: %s (%s)", body[:200], e)
			return []

	def _from_xml(self, root, cameras):
		etype = (_t(root, "eventType") or "").lower()
		state = (_t(root, "eventState") or "active").lower()
		kind = EVENT_MAP.get(etype)
		if not kind or state == "inactive":
			return []  # Hikvision sends 'videoloss inactive' every few seconds as a heartbeat
		channel = _t(root, "channelID") or _t(root, "dynChannelID") or "1"
		cam = self.camera_for_channel(cameras, channel)
		if not cam:
			return []
		when = to_utc(parse_time(_t(root, "dateTime")), self.offset)
		data, conf = {}, None
		if kind == "plate_read":
			anpr = root.find("ANPR")
			if anpr is None:
				return []
			plate = _t(anpr, "licensePlate")
			if not plate or plate.lower() in ("unknown", "noplate"):
				return []
			conf = float(_t(anpr, "confidenceLevel") or 0) / 100
			data = {"plate": plate, "direction": plate_direction(_t(anpr, "direction"), cam.get("direction_in")),
				"vehicle_type": _t(anpr, "vehicleType"), "colour": _t(root, "VehicleInfo/color") or _t(anpr, "color"),
				"lane": _t(anpr, "laneNo")}
		elif kind == "line_crossing":
			data = {"direction": line_direction(_t(root, ".//direction"), cam.get("direction_in")),
				"line_id": _t(root, ".//regionID"), "object_class": _t(root, ".//detectionTarget")}
		elif kind == "zone_intrusion":
			data = {"roi_id": _t(root, ".//regionID"), "object_class": _t(root, ".//detectionTarget")}
		elif kind == "door_state":
			data = {"door_id": _t(root, "inputIOPortID") or channel, "state": "open" if state == "active" else "closed"}
		elif kind == "tamper":
			data = {"kind": etype}
		return [make_event(self.site, cam["name"], kind, when, data, conf, offset_seconds=self.offset)]

	def _from_json(self, obj, cameras):
		etype = (obj.get("eventType") or "").lower()
		kind = EVENT_MAP.get(etype)
		if not kind:
			return []
		cam = self.camera_for_channel(cameras, obj.get("channelID") or 1)
		if not cam:
			return []
		when = to_utc(parse_time(obj.get("dateTime")), self.offset)
		if kind == "access_event":
			ace = obj.get("AccessControllerEvent") or {}
			granted = int(ace.get("majorEventType") or 0) == 5 and int(ace.get("subEventType") or 0) in (1, 75, 38)
			data = {"reader_id": ace.get("cardReaderNo"), "credential_ref": ace.get("employeeNoString") or ace.get("cardNo"),
				"result": "granted" if granted else "denied", "employee_no": ace.get("employeeNoString")}
			return [make_event(self.site, cam["name"], "access_event", when, data, offset_seconds=self.offset)]
		return [make_event(self.site, cam["name"], kind, when, {}, offset_seconds=self.offset)]


def parse_channel(value):
	m = re.search(r"\d+", str(value or ""))
	return int(m.group()) if m else 1
