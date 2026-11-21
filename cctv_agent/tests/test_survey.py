"""Site survey against simulated recorders (httpx MockTransport)."""

import os
import sys
from datetime import datetime, timedelta, timezone

import httpx
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cctv_agent.survey import run_survey  # noqa: E402
from cctv_agent.survey.render import html, text  # noqa: E402
from cctv_agent.survey.wsdiscovery import parse  # noqa: E402

NOW = datetime.now(timezone(timedelta(hours=3)))
X = 'xmlns="http://www.hikvision.com/ver20/XMLSchema"'

HIK = {
	"/ISAPI/System/deviceInfo": f"<DeviceInfo {X}><deviceName>Gate NVR</deviceName><model>DS-7616NI-K2</model><serialNumber>DS123</serialNumber>"
		"<firmwareVersion>V4.62.210</firmwareVersion><deviceType>NVR</deviceType></DeviceInfo>",
	"/ISAPI/System/status": f"<DeviceStatus {X}><CPUList><CPU><cpuUtilization>34</cpuUtilization></CPU></CPUList><MemoryList><Memory><memoryUsage>61</memoryUsage></Memory></MemoryList><deviceUpTime>360000</deviceUpTime></DeviceStatus>",
	"/ISAPI/ContentMgmt/InputProxy/channels": f"<InputProxyChannelList {X}>"
		"<InputProxyChannel><id>1</id><name>Main Gate</name><sourceInputPortDescriptor><proxyProtocol>HIKVISION</proxyProtocol><ipAddress>192.168.254.2</ipAddress><model>iDS-TCM403-GIR</model></sourceInputPortDescriptor></InputProxyChannel>"
		"<InputProxyChannel><id>2</id><name>Cold Room</name><sourceInputPortDescriptor><proxyProtocol>ONVIF</proxyProtocol><ipAddress>192.168.254.3</ipAddress></sourceInputPortDescriptor></InputProxyChannel>"
		"</InputProxyChannelList>",
	"/ISAPI/ContentMgmt/InputProxy/channels/status": f"<InputProxyChannelStatusList {X}><InputProxyChannelStatus><id>1</id><online>true</online></InputProxyChannelStatus>"
		"<InputProxyChannelStatus><id>2</id><online>false</online><chanDetectResult>notExist</chanDetectResult></InputProxyChannelStatus></InputProxyChannelStatusList>",
	"/ISAPI/Streaming/channels": f"<StreamingChannelList {X}>"
		+ "".join(f"<StreamingChannel><id>{c}0{k}</id><Video><videoCodecType>H.265</videoCodecType><videoResolutionWidth>{w}</videoResolutionWidth>"
			f"<videoResolutionHeight>{h}</videoResolutionHeight><maxFrameRate>2500</maxFrameRate></Video></StreamingChannel>"
			for c in (1, 2) for k, w, h in ((1, 2560, 1440), (2, 640, 360))) + "</StreamingChannelList>",
	"/ISAPI/ContentMgmt/Storage": f"<storage {X}><hddList><hdd><id>1</id><hddName>hdd1</hddName><status>ok</status><capacity>3815447</capacity><freeSpace>1024</freeSpace></hdd>"
		"<hdd><id>2</id><hddName>hdd2</hddName><status>error</status><capacity>3815447</capacity><freeSpace>0</freeSpace></hdd></hddList></storage>",
	"/ISAPI/ContentMgmt/record/tracks": f"<TrackList {X}><Track><id>101</id><DefaultRecordingMode>CMR</DefaultRecordingMode></Track>"
		"<Track><id>201</id><DefaultRecordingMode>MOTION</DefaultRecordingMode></Track></TrackList>",
	"/ISAPI/Event/triggers": f"<EventTriggerList {X}><EventTrigger><eventType>VMD</eventType><videoInputChannelID>1</videoInputChannelID></EventTrigger>"
		"<EventTrigger><eventType>linedetection</eventType><videoInputChannelID>2</videoInputChannelID></EventTrigger>"
		"<EventTrigger><eventType>videoloss</eventType><videoInputChannelID>2</videoInputChannelID></EventTrigger></EventTriggerList>",
	"/ISAPI/Traffic/capabilities": f"<TrafficCap {X}/>",
	"/ISAPI/System/time": f"<Time {X}><timeMode>manual</timeMode><localTime>{(NOW + timedelta(seconds=47)).isoformat(timespec='seconds')}</localTime><timeZone>CST-3:00:00</timeZone></Time>",
	"/ISAPI/ContentMgmt/logSearch": f"<CMSearchResult {X}><matchList>"
		"<searchMatchItem><logDescriptor><metaId>log.std-cgi.com/Exception/hdError</metaId><StartDateTime>2026-11-20T03:00:00Z</StartDateTime></logDescriptor></searchMatchItem>"
		"<searchMatchItem><logDescriptor><metaId>log.std-cgi.com/Exception/hdError</metaId><StartDateTime>2026-11-21T03:00:00Z</StartDateTime></logDescriptor></searchMatchItem>"
		"<searchMatchItem><logDescriptor><metaId>log.std-cgi.com/Exception/videoLoss</metaId><StartDateTime>2026-11-21T05:00:00Z</StartDateTime></logDescriptor></searchMatchItem>"
		"</matchList></CMSearchResult>",
}


def device(table):
	def handler(request):
		body = table.get(request.url.path)
		if body is None:
			return httpx.Response(404, text="Invalid Operation")
		return httpx.Response(200, text=body, headers={"content-type": "application/xml" if body.lstrip().startswith("<") else "text/plain"})
	return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_hikvision_survey_report():
	rep = await run_survey({"name": "NVR", "brand": "Hikvision", "host": "10.0.0.5", "username": "u", "password": "p"},
		probe_streams=False, _transport=device(HIK))
	assert rep["device"]["model"] == "DS-7616NI-K2" and rep["status"]["uptime_hours"] == 100.0
	ch = {c["channel_no"]: c for c in rep["channels"]}
	assert ch[1]["model"] == "iDS-TCM403-GIR" and ch[1]["online"] is True and ch[2]["online"] is False
	assert ch[1]["main"]["codec"] == "H.265" and ch[1]["sub"]["height"] == "360" and ch[1]["main"]["fps"] == 25.0
	assert rep["recording"]["modes"] == {"1": "Continuous", "2": "Motion"}
	assert {"plate_read", "line_crossing", "motion", "video_loss"} <= set(rep["events"]["normalised"])
	assert rep["logs"]["summary"] == {"hdd": 2, "video_loss": 1}
	assert 40 < rep["time"]["offset_seconds"] < 55 and rep["time"]["ntp"] is False
	topics = {(f["topic"], f["level"]) for f in rep["findings"]}
	assert ("Recording", "blocker") in topics  # hdd2 error
	assert ("Streams", "warn") in topics and ("Clock", "warn") in topics and ("Device log", "warn") in topics
	assert rep["verdict"] == "Not ready"
	failed = [c for c in rep["api"] if not c["ok"]]
	assert any(c["endpoint"] == "/ISAPI/Smart/capabilities" and c["status"] == 404 for c in failed)
	page = html(rep)
	assert "Not ready" in page and "iDS-TCM403-GIR" in page and "hdError" in page and "API coverage" in page and "p@" not in page
	assert "DS-7616NI-K2" in text(rep)


DAHUA = {
	"/cgi-bin/magicBox.cgi": None,  # answered per action below
	"/cgi-bin/configManager.cgi": None,
}


def dahua_device():
	def handler(request):
		q = dict(request.url.params)
		path = request.url.path
		a, name = q.get("action"), q.get("name")
		answers = {
			("magicBox.cgi", "getDeviceType"): "type=DHI-NVR4108HS-8P-4KS2",
			("magicBox.cgi", "getSoftwareVersion"): "version=4.001.0000000.3,build:2023-01-01",
			("magicBox.cgi", "getSerialNo"): "sn=7B0123",
			("configManager.cgi", "ChannelTitle"): "table.ChannelTitle[0].Name=Gate\ntable.ChannelTitle[1].Name=Dock",
			("configManager.cgi", "RemoteDevice"): "table.RemoteDevice.uuid1.Address=192.168.1.108\ntable.RemoteDevice.uuid1.DeviceType=IPC-HFW2431S\ntable.RemoteDevice.uuid2.Address=192.168.1.109\ntable.RemoteDevice.uuid2.DeviceType=ITC413-PW4D",
			("LogicDeviceManager.cgi", "getCameraState"): "states[0].channel=0\nstates[0].connectionState=Connected\nstates[1].channel=1\nstates[1].connectionState=Connected",
			("configManager.cgi", "Encode"): "table.Encode[0].MainFormat[0].Video.Compression=H.265\ntable.Encode[0].ExtraFormat[0].Video.Compression=H.264\ntable.Encode[0].ExtraFormat[0].Video.Height=480",
			("storageDevice.cgi", "getDeviceAllInfo"): "list.info[0].Name=/dev/sda\nlist.info[0].State=Success\nlist.info[0].Detail[0].TotalBytes=4000000000000\nlist.info[0].Detail[0].UsedBytes=1000000000000\nlist.info[0].Detail[0].IsError=false",
			("configManager.cgi", "RecordMode"): "table.RecordMode[0].Mode=1\ntable.RecordMode[1].Mode=1",
			("eventManager.cgi", "getExposureEvents"): "events[0]=VideoMotion\nevents[1]=TrafficJunction\nevents[2]=CrossLineDetection",
			("global.cgi", "getCurrentTime"): f"result={NOW.strftime('%Y-%m-%d %H:%M:%S')}",
			("configManager.cgi", "NTP"): "table.NTP.Enable=true\ntable.NTP.Address=pool.ntp.org",
			("log.cgi", "startFind"): "token=42",
			("log.cgi", "doFind"): "found=1\nitems[0].Type=Reboot\nitems[0].Time=2026-11-21 02:00:00",
			("log.cgi", "stopFind"): "OK",
		}
		key = (path.rsplit("/", 1)[-1], name if a == "getConfig" else a)
		body = answers.get(key)
		return httpx.Response(200, text=body) if body is not None else httpx.Response(400, text="Error")
	return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_dahua_survey_report():
	rep = await run_survey({"name": "NVR", "brand": "Dahua", "host": "10.0.0.6", "username": "u", "password": "p"},
		probe_streams=False, _transport=dahua_device())
	assert rep["device"]["model"] == "DHI-NVR4108HS-8P-4KS2"
	ch = {c["channel_no"]: c for c in rep["channels"]}
	assert ch[2]["model"] == "ITC413-PW4D" and ch[1]["online"] and ch[1]["sub"]["codec"] == "H.264"
	assert rep["capabilities"]["anpr"] and "plate_read" in rep["events"]["normalised"]
	assert rep["storage"][0]["capacity_gb"] == 4000.0 and rep["time"]["ntp"] is True and abs(rep["time"]["offset_seconds"]) < 5
	assert rep["recording"]["modes"] == {"1": "Continuous", "2": "Continuous"}  # channel numbers, from 1
	assert rep["logs"]["summary"] == {"reboot": 1}
	assert rep["verdict"] == "Ready", rep["findings"]
	assert any(f["text"].startswith("Main streams use H.265 but sub-streams are H.264") for f in rep["findings"])


@pytest.mark.asyncio
async def test_unreachable_device_is_a_blocker():
	rep = await run_survey({"name": "x", "brand": "Hikvision", "host": "10.9.9.9", "username": "u", "password": "p"},
		probe_streams=False, _transport=httpx.MockTransport(lambda r: httpx.Response(401, text="Unauthorized")))
	assert rep["verdict"] == "Not ready"
	assert any("refused (401/403)" in f["text"] for f in rep["findings"])


def test_ws_discovery_reply_parsing():
	reply = ('<d:XAddrs>http://192.168.1.64/onvif/device_service http://[fe80::1]/onvif/device_service</d:XAddrs>'
		'<d:Scopes>onvif://www.onvif.org/type/video_encoder onvif://www.onvif.org/name/HIKVISION onvif://www.onvif.org/hardware/DS-2CD2143G2-I</d:Scopes>')
	d = parse(reply)
	assert d["host"] == "192.168.1.64" and d["hardware"] == "DS-2CD2143G2-I" and d["brand_hint"] == "Hikvision"
