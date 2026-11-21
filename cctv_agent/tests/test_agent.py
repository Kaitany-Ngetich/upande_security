"""Unit tests for the parts that need no hardware. Sample payloads follow the
vendors' documented formats; replace with captures from the pilot recorders."""

import hashlib
import hmac
import json
import os
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cctv_agent import envelope, tokens  # noqa: E402
from cctv_agent.adapters.dahua import DahuaAdapter  # noqa: E402
from cctv_agent.adapters.hikvision import HikvisionAdapter  # noqa: E402
from cctv_agent.adapters.multipart import MultipartStream  # noqa: E402
from cctv_agent.adapters.onvif import OnvifAdapter  # noqa: E402
from cctv_agent.buffer import Buffer  # noqa: E402
from cctv_agent.erp import ERP  # noqa: E402
from cctv_agent.gateway import AuthServer  # noqa: E402
from cctv_agent.playback import ffmpeg_cmd, parse_path  # noqa: E402

SERVER = {"name": "NVR-1", "brand": "Hikvision", "host": "10.0.0.5", "port": 80, "username": "api", "password": "p@ss:1", "time_offset_seconds": 2}
CAMS = [
	{"name": "Gate In-NVR-1", "server": "NVR-1", "channel_no": 1, "direction_in": "Towards Camera", "role": "Entry"},
	{"name": "Cold Room Door-NVR-1", "server": "NVR-1", "channel_no": 4, "direction_in": "Left to Right", "role": "Cold Room"},
]


# ---------------------------------------------------------------- envelope
def test_camera_key_matches_erpnext():
	assert envelope.camera_key("DEMO Gate In-DEMO NVR-Kapkolia") == "demo-gate-in-demo-nvr-kapkolia"


def test_offset_removed_and_utc():
	dev = datetime(2026, 11, 21, 12, 0, 10, tzinfo=timezone.utc)
	assert envelope.to_utc(dev, 10) == datetime(2026, 11, 21, 12, 0, 0, tzinfo=timezone.utc)


def test_directions():
	assert envelope.plate_direction("forward", "Towards Camera") == "in"
	assert envelope.plate_direction("forward", "Away From Camera") == "out"
	assert envelope.line_direction("RightToLeft", "Left to Right") == "out"


# ---------------------------------------------------------------- hikvision
HIK_ANPR = b"""<?xml version="1.0" encoding="UTF-8"?>
<EventNotificationAlert version="2.0" xmlns="http://www.hikvision.com/ver20/XMLSchema">
<ipAddress>10.0.0.5</ipAddress><channelID>1</channelID><dateTime>2026-11-21T12:42:17+03:00</dateTime>
<activePostCount>1</activePostCount><eventType>ANPR</eventType><eventState>active</eventState>
<ANPR><licensePlate>KDA123A</licensePlate><confidenceLevel>94</confidenceLevel><direction>forward</direction>
<vehicleType>vehicle</vehicleType><laneNo>1</laneNo></ANPR><VehicleInfo><color>white</color></VehicleInfo>
</EventNotificationAlert>"""

HIK_HEARTBEAT = b"""<EventNotificationAlert><channelID>1</channelID><dateTime>2026-11-21T12:42:17+03:00</dateTime>
<eventType>videoloss</eventType><eventState>inactive</eventState></EventNotificationAlert>"""

HIK_LINE = b"""<EventNotificationAlert xmlns="http://www.hikvision.com/ver20/XMLSchema"><channelID>4</channelID>
<dateTime>2026-11-21T21:15:32+03:00</dateTime><eventType>linedetection</eventType><eventState>active</eventState>
<DetectionRegionList><DetectionRegionEntry><regionID>1</regionID><direction>LeftToRight</direction><detectionTarget>human</detectionTarget></DetectionRegionEntry></DetectionRegionList>
</EventNotificationAlert>"""


def test_hik_anpr():
	a = HikvisionAdapter(SERVER, "KAP")
	[ev] = a.normalise(HIK_ANPR, "application/xml", CAMS)
	assert ev["event_type"] == "plate_read" and ev["camera"] == "Gate In-NVR-1"
	assert ev["data"]["plate"] == "KDA123A" and ev["data"]["direction"] == "in" and ev["data"]["colour"] == "white"
	assert ev["confidence"] == 0.94
	assert ev["event_time"] == "2026-11-21T09:42:15.000Z"  # +03:00 -> UTC, minus 2 s device offset
	assert ev["source"]["device_offset_ms"] == 2000


def test_hik_heartbeat_ignored_and_line():
	a = HikvisionAdapter(SERVER, "KAP")
	assert a.normalise(HIK_HEARTBEAT, "application/xml", CAMS) == []
	[ev] = a.normalise(HIK_LINE, "application/xml", CAMS)
	assert ev["event_type"] == "line_crossing" and ev["camera"] == "Cold Room Door-NVR-1" and ev["data"]["direction"] == "in"


def test_hik_urls_hide_nothing_but_escape_credentials():
	a = HikvisionAdapter(SERVER, "KAP")
	assert a.get_stream_uri(CAMS[0], "sub") == "rtsp://api:p%40ss%3A1@10.0.0.5:554/Streaming/Channels/102"
	start = datetime(2026, 11, 21, 18, 15, 17, tzinfo=timezone.utc)
	end = datetime(2026, 11, 21, 18, 16, 32, tzinfo=timezone.utc)
	assert a.get_playback_uri(CAMS[1], start, end).endswith("/Streaming/tracks/401?starttime=20261121T181519Z&endtime=20261121T181634Z")


def test_multipart_stream_split_chunks():
	body = (b"--boundary\r\nContent-Type: application/xml; charset=UTF-8\r\nContent-Length: %d\r\n\r\n" % len(HIK_ANPR)) + HIK_ANPR + b"\r\n"
	body += b"--boundary\r\nContent-Type: image/jpeg\r\nContent-Length: 4\r\n\r\nJPEG\r\n--boundary\r\n"
	p, parts = MultipartStream("boundary"), []
	for i in range(0, len(body), 7):  # awkward chunk sizes
		parts += p.feed(body[i:i + 7])
	assert [h["content-type"].split(";")[0] for h, _ in parts] == ["application/xml", "image/jpeg"]
	assert parts[0][1] == HIK_ANPR and parts[1][1] == b"JPEG"


# ---------------------------------------------------------------- dahua
DAHUA_PLATE = 'Code=TrafficJunction;action=Pulse;index=0;data={"UTC": 1795254137, "TrafficCar": {"PlateNumber": "KMHC329U", "Confidence": 88, "VehicleColor": "Black", "Direction": "Approach"}}'


def test_dahua_plate_and_heartbeat():
	a = DahuaAdapter({**SERVER, "brand": "Dahua", "time_offset_seconds": 0}, "KAP")
	[ev] = a.normalise(DAHUA_PLATE, CAMS)
	assert ev["event_type"] == "plate_read" and ev["data"]["plate"] == "KMHC329U" and ev["data"]["direction"] == "in"
	assert ev["confidence"] == 0.88
	assert ev["event_time"] == datetime.fromtimestamp(1795254137, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
	assert a.normalise("Code=Heartbeat;action=Pulse;index=0", CAMS) == []
	assert a.normalise("Code=VideoMotion;action=Stop;index=0", CAMS) == []
	[door] = a.normalise("Code=AlarmLocal;action=Stop;index=3", CAMS)
	assert door["event_type"] == "door_state" and door["data"]["state"] == "closed"


def test_dahua_playback_uses_local_time():
	a = DahuaAdapter({**SERVER, "brand": "Dahua", "time_offset_seconds": 0}, "KAP")
	start = datetime(2026, 11, 21, 18, 15, 0, tzinfo=timezone.utc)
	url = a.get_playback_uri(CAMS[0], start, start.replace(minute=16))
	assert "starttime=2026_11_21_21_15_00&endtime=2026_11_21_21_16_00" in url


# ---------------------------------------------------------------- onvif
ONVIF_PULL = b"""<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:wsnt="http://docs.oasis-open.org/wsn/b-2" xmlns:tt="http://www.onvif.org/ver10/schema" xmlns:tns1="http://www.onvif.org/ver10/topics"><s:Body><tev:PullMessagesResponse xmlns:tev="http://www.onvif.org/ver10/events/wsdl">
<wsnt:NotificationMessage><wsnt:Topic Dialect="x">tns1:RuleEngine/CellMotionDetector/Motion</wsnt:Topic><wsnt:Message>
<tt:Message UtcTime="2026-11-21T18:15:32Z" PropertyOperation="Changed"><tt:Source><tt:SimpleItem Name="VideoSourceConfigurationToken" Value="VideoSource_1"/></tt:Source>
<tt:Data><tt:SimpleItem Name="IsMotion" Value="true"/></tt:Data></tt:Message></wsnt:Message></wsnt:NotificationMessage>
<wsnt:NotificationMessage><wsnt:Topic Dialect="x">tns1:RuleEngine/CellMotionDetector/Motion</wsnt:Topic><wsnt:Message>
<tt:Message UtcTime="2026-11-21T18:15:40Z" PropertyOperation="Changed"><tt:Source><tt:SimpleItem Name="VideoSourceConfigurationToken" Value="VideoSource_1"/></tt:Source>
<tt:Data><tt:SimpleItem Name="IsMotion" Value="false"/></tt:Data></tt:Message></wsnt:Message></wsnt:NotificationMessage>
</tev:PullMessagesResponse></s:Body></s:Envelope>"""


def test_onvif_motion_start_only():
	a = OnvifAdapter({**SERVER, "brand": "ONVIF", "time_offset_seconds": 0}, "KAP")
	evs = a.normalise(ET.fromstring(ONVIF_PULL), CAMS)
	assert len(evs) == 1 and evs[0]["event_type"] == "motion" and evs[0]["camera"] == "Gate In-NVR-1"


# ---------------------------------------------------------------- erp signing = server check
def test_signature_matches_erpnext_check():
	erp = ERP("https://erp.example.com", "k", "s", "KAP-agent", "sig-secret")
	req = erp._sign(erp.client.build_request("POST", "https://erp.example.com/x", json={"events": [{"a": 1}]}))
	ts, sig = req.headers["X-CCTV-Timestamp"], req.headers["X-CCTV-Signature"]
	# same computation as upande_security/cctv/ingest.py::_agent
	expected = hmac.new(b"sig-secret", ts.encode() + b"." + req.content, hashlib.sha256).hexdigest()
	assert hmac.compare_digest(expected, sig) and req.headers["X-CCTV-Agent"] == "KAP-agent"


# ---------------------------------------------------------------- buffer
def test_buffer_priority_and_idempotency(tmp_path):
	b = Buffer(str(tmp_path / "b.db"))
	t = datetime.now(timezone.utc)
	bulk = envelope.make_event("S", "c", "motion", t)
	urgent = envelope.make_event("S", "c", "plate_read", t, {"plate": "KDA123A"})
	b.put(bulk, 1)
	b.put(urgent, 0)
	b.put(urgent, 0)  # duplicate ignored
	assert b.depth() == 2
	assert [e["event_id"] for e in b.take(10)] == [urgent["event_id"], bulk["event_id"]]
	b.ack([urgent["event_id"]])
	assert b.depth() == 1


# ---------------------------------------------------------------- tokens + auth hook
def test_auth_decisions():
	secret = "gw-secret"
	srv = AuthServer(lambda: secret)
	live = tokens.sign({"sub": "u", "cam": "c", "path": "live/c/sub", "scope": "live", "exp": time.time() + 60, "jti": "a"}, secret)
	assert srv.decide({"action": "read", "ip": "1.2.3.4", "path": "live/c/sub", "query": f"jwt={live}"})
	assert not srv.decide({"action": "read", "ip": "1.2.3.4", "path": "live/other/sub", "query": f"jwt={live}"})
	assert not srv.decide({"action": "read", "ip": "1.2.3.4", "path": "live/c/sub", "query": "jwt=" + tokens.sign({"path": "live/c/sub", "scope": "live", "exp": time.time() + 60}, "wrong")})
	expired = tokens.sign({"path": "live/c/sub", "scope": "live", "exp": time.time() - 1, "jti": "b"}, secret)
	assert not srv.decide({"action": "read", "ip": "1.2.3.4", "path": "live/c/sub", "query": f"jwt={expired}"})
	pb = tokens.sign({"path": "pb/c/20261121T181517Z_20261121T181632Z", "scope": "playback", "exp": time.time() + 60, "jti": "p", "once": 1}, secret)
	req = {"action": "read", "path": "pb/c/20261121T181517Z_20261121T181632Z", "query": f"jwt={pb}"}
	assert srv.decide({**req, "ip": "5.5.5.5"}) and srv.decide({**req, "ip": "5.5.5.5"})
	assert not srv.decide({**req, "ip": "6.6.6.6"})  # forwarded link from elsewhere
	assert srv.decide({"action": "publish", "ip": "127.0.0.1", "path": "pb/x"})
	assert not srv.decide({"action": "publish", "ip": "10.0.0.9", "path": "pb/x"})


def test_erpnext_token_verifies_here():
	"""Run ERPNext's own sign() (lifted out of upande_security/cctv/tokens.py,
	which imports frappe) and verify its token with the agent."""
	import ast
	path = os.path.join(os.path.dirname(__file__), "..", "..", "upande_security", "cctv", "tokens.py")
	if not os.path.exists(path):
		pytest.skip("ERPNext app not alongside")
	tree = ast.parse(open(path).read())
	funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ("_b64", "sign")]
	ns = {}
	exec(compile(ast.Module(body=[ast.parse("import base64, hashlib, hmac, json").body[0], *funcs], type_ignores=[]), path, "exec"), ns)
	claims = {"sub": "u", "path": "live/x/sub", "scope": "live", "exp": int(time.time()) + 30, "jti": "z"}
	assert tokens.verify(ns["sign"](claims, "s3cret"), "s3cret")["jti"] == "z"


# ---------------------------------------------------------------- playback runner
def test_playback_path_and_cmd():
	key, s, e = parse_path("pb/demo-gate-in-demo-nvr-kapkolia/20261121T181517Z_20261121T181632Z")
	assert key == "demo-gate-in-demo-nvr-kapkolia" and s.hour == 18 and (e - s).seconds == 75
	with pytest.raises(ValueError):
		parse_path("live/x/sub")
	cmd = ffmpeg_cmd("rtsp://nvr/x", "rtsp://127.0.0.1:8554/pb/x")
	assert cmd[-1] == "rtsp://127.0.0.1:8554/pb/x" and "copy" in cmd
