"""Hikvision (ISAPI) survey."""

import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

from cctv_agent.adapters.hikvision import EVENT_MAP, _strip_ns, _t, parse_time

LOG_TYPES = {
	"hdError": "hdd", "hdFull": "hdd", "hdUnformatted": "hdd", "hddError": "hdd",
	"videoLoss": "video_loss", "videoloss": "video_loss",
	"netBroken": "network", "ipConflict": "network", "networkDisconnected": "network", "ipcDisconnect": "network",
	"illegalAccess": "illegal_login", "illegaAccess": "illegal_login", "loginFailed": "illegal_login",
	"recordException": "record", "recordError": "record",
	"abnormalReboot": "abnormal_reboot", "abnormalShutdown": "abnormal_reboot", "powerOff": "abnormal_reboot",
}


def _xml(r):
	try:
		return _strip_ns(ET.fromstring(r.content)) if r is not None else None
	except ET.ParseError:
		return None


async def survey(adapter, p, rep, log_days=7):
	info = _xml(await p.get("/ISAPI/System/deviceInfo", "Device information"))
	if info is not None:
		rep["device"] = {k: _t(info, k) for k in ("deviceName", "model", "serialNumber", "firmwareVersion", "firmwareReleasedDate",
			"deviceType", "macAddress", "hardwareVersion", "encoderVersion")}
	st = _xml(await p.get("/ISAPI/System/status", "Health (CPU, memory, uptime)"))
	if st is not None:
		rep["status"] = {"cpu_percent": _t(st, ".//cpuUtilization"), "memory_percent": _t(st, ".//memoryUsage"),
			"uptime_hours": round(int(_t(st, "deviceUpTime") or 0) / 3600, 1) or None}

	# channels: an NVR's IP channels, else a camera's own inputs
	chans = {}
	proxy = _xml(await p.get("/ISAPI/ContentMgmt/InputProxy/channels", "IP channels (NVR)"))
	if proxy is not None:
		for ch in proxy.iter("InputProxyChannel"):
			cid = int(_t(ch, "id") or 0)
			chans[cid] = {"channel_no": cid, "name": _t(ch, "name"), "ip": _t(ch, ".//ipAddress"), "protocol": _t(ch, ".//proxyProtocol"),
				"model": _t(ch, ".//model"), "camera_firmware": _t(ch, ".//firmwareVersion")}
		status = _xml(await p.get("/ISAPI/ContentMgmt/InputProxy/channels/status", "IP channel online state"))
		if status is not None:
			for s in status.iter("InputProxyChannelStatus"):
				cid = int(_t(s, "id") or 0)
				if cid in chans:
					chans[cid]["online"] = (_t(s, "online") or "").lower() == "true"
					chans[cid]["detail"] = _t(s, "chanDetectResult")
	if not chans:
		vin = _xml(await p.get("/ISAPI/System/Video/inputs/channels", "Video inputs (camera)"))
		if vin is not None:
			for ch in vin.iter("VideoInputChannel"):
				cid = int(_t(ch, "id") or 0)
				chans[cid] = {"channel_no": cid, "name": _t(ch, "name"), "online": (_t(ch, "videoInputEnabled") or "true") == "true",
					"model": rep["device"].get("model")}

	streams = _xml(await p.get("/ISAPI/Streaming/channels", "Stream settings"))
	if streams is not None:
		for sc in streams.iter("StreamingChannel"):
			sid = _t(sc, "id") or ""
			if not sid.isdigit() or len(sid) < 3:
				continue
			cid, kind = int(sid[:-2]), "main" if sid.endswith("01") else "sub" if sid.endswith("02") else None
			if not kind:
				continue
			fps = _t(sc, ".//maxFrameRate")
			chans.setdefault(cid, {"channel_no": cid})[kind] = {
				"stream_id": sid, "codec": (_t(sc, ".//videoCodecType") or "").replace("H.", "H").replace("H", "H.", 1) or None,
				"width": _t(sc, ".//videoResolutionWidth"), "height": _t(sc, ".//videoResolutionHeight"),
				"fps": round(int(fps) / 100, 1) if fps and fps.isdigit() else None, "bitrate_kbps": _t(sc, ".//vbrUpperCap") or _t(sc, ".//constantBitRate")}
	rep["channels"] = [chans[k] for k in sorted(chans)]

	disks = _xml(await p.get("/ISAPI/ContentMgmt/Storage", "Disks"))
	if disks is not None:
		for h in disks.iter("hdd"):
			cap, free = _t(h, "capacity"), _t(h, "freeSpace")
			rep["storage"].append({"name": _t(h, "hddName") or f"HDD {_t(h, 'id')}", "status": _t(h, "status"), "type": _t(h, "hddType"),
				"capacity_gb": round(int(cap) / 1024, 1) if cap and cap.isdigit() else None,
				"free_gb": round(int(free) / 1024, 1) if free and free.isdigit() else None, "property": _t(h, "property")})

	tracks = _xml(await p.get("/ISAPI/ContentMgmt/record/tracks", "Recording schedule"))
	if tracks is not None:
		modes = {}
		for t in tracks.iter("Track"):
			tid = _t(t, "id") or ""
			mode = _t(t, ".//DefaultRecordingMode") or _t(t, ".//Actions/ActionRecordingMode")
			if tid.endswith("01"):
				modes[tid[:-2]] = {"CMR": "Continuous", "MOTION": "Motion", "ALARM": "Alarm", "EDR": "Event"}.get((mode or "").upper(), mode)
		rep["recording"]["modes"] = modes

	trig = _xml(await p.get("/ISAPI/Event/triggers", "Event triggers"))
	if trig is not None:
		by = {}
		for et in trig.iter("EventTrigger"):
			kind = (_t(et, "eventType") or "").lower()
			ch = _t(et, "videoInputChannelID") or _t(et, "dynVideoInputChannelID") or "device"
			by.setdefault(ch, set()).add(kind)
		rep["events"]["by_channel"] = {k: sorted(v) for k, v in by.items()}
		rep["events"]["device"] = sorted({e for v in by.values() for e in v})
	rep["capabilities"]["anpr"] = (await p.get("/ISAPI/Traffic/capabilities", "Plate recognition (ANPR) capability")) is not None
	rep["capabilities"]["smart"] = (await p.get("/ISAPI/Smart/capabilities", "Smart events capability")) is not None
	rep["capabilities"]["face"] = (await p.get("/ISAPI/Intelligent/FDLib/capabilities", "Face library capability")) is not None
	norm = {EVENT_MAP[e] for e in rep["events"]["device"] if e in EVENT_MAP}
	if rep["capabilities"]["anpr"]:
		norm.add("plate_read")
	if rep["capabilities"]["face"]:
		norm.add("face_match")
	rep["events"]["normalised"] = sorted(norm)

	tm = _xml(await p.get("/ISAPI/System/time", "Clock"))
	if tm is not None:
		rep["time"].update({"mode": _t(tm, "timeMode"), "ntp": (_t(tm, "timeMode") or "").upper() == "NTP", "timezone": _t(tm, "timeZone"),
			"device_time": _t(tm, "localTime")})
		dev = parse_time(_t(tm, "localTime"))
		if dev:
			rep["time"]["offset_seconds"] = round((dev - datetime.now(timezone.utc)).total_seconds(), 1)
	ntp = _xml(await p.get("/ISAPI/System/time/ntpServers", "NTP servers"))
	if ntp is not None:
		rep["time"]["ntp_servers"] = [_t(n, "hostName") or _t(n, "ipAddress") for n in ntp.iter("NTPServer")]

	# the device's own exception log - the "crash report"
	end = datetime.now(timezone.utc)
	start = end - timedelta(days=log_days)
	body = (f'<?xml version="1.0" encoding="UTF-8"?><CMSearchDescription><searchID>{uuid.uuid4()}</searchID>'
		f'<metaId>log.std-cgi.com/Exception</metaId><timeSpanList><timeSpan><startTime>{start:%Y-%m-%dT%H:%M:%SZ}</startTime>'
		f'<endTime>{end:%Y-%m-%dT%H:%M:%SZ}</endTime></timeSpan></timeSpanList><maxResults>500</maxResults><searchResultPostion>0</searchResultPostion>'
		"</CMSearchDescription>")
	logs = _xml(await p.request("POST", "/ISAPI/ContentMgmt/logSearch", "Device exception log", content=body.encode(),
		headers={"Content-Type": "application/xml"}))
	if logs is not None:
		recent, summary = [], {}
		for item in logs.iter("searchMatchItem"):
			meta = _t(item, ".//metaId") or ""
			kind = meta.rsplit("/", 1)[-1]
			cat = LOG_TYPES.get(kind, "other")
			summary[cat] = summary.get(cat, 0) + 1
			recent.append({"time": _t(item, ".//StartDateTime") or _t(item, ".//startTime"), "type": kind, "category": cat,
				"channel": _t(item, ".//channelNo") or _t(item, ".//localId"), "detail": _t(item, ".//paraType") or _t(item, ".//info")})
		rep["logs"] = {"summary": summary, "recent": sorted(recent, key=lambda x: x["time"] or "", reverse=True)[:50], "days": log_days}
	rep["capabilities"]["playback"] = any(c["ok"] for c in p.calls if c["what"] == "Recording schedule") or None
