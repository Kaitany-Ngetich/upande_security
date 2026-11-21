"""ONVIF survey - the baseline for any brand."""

import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from cctv_agent.adapters.onvif import NS, TOPICS, _envelope


async def _soap(adapter, p, url, body, label, auth=True):
	r = await p.request("POST", url, label, content=_envelope(body, adapter.user if auth else None, adapter.password).encode(),
		headers={"Content-Type": "application/soap+xml; charset=utf-8"})
	try:
		return ET.fromstring(r.content) if r is not None else None
	except ET.ParseError:
		return None


def _txt(el, path):
	x = el.find(path, NS) if el is not None else None
	return x.text.strip() if x is not None and x.text else None


async def survey(adapter, p, rep, log_days=7):
	dev = adapter.device_url
	info = await _soap(adapter, p, dev, "<tds:GetDeviceInformation/>", "Device information")
	if info is not None:
		rep["device"] = {"manufacturer": _txt(info, ".//tds:Manufacturer"), "model": _txt(info, ".//tds:Model"),
			"firmwareVersion": _txt(info, ".//tds:FirmwareVersion"), "serialNumber": _txt(info, ".//tds:SerialNumber"),
			"hardwareVersion": _txt(info, ".//tds:HardwareId")}
	caps = await _soap(adapter, p, dev, "<tds:GetCapabilities><tds:Category>All</tds:Category></tds:GetCapabilities>", "Capabilities")
	if caps is not None:
		adapter.media_url = _txt(caps, ".//tt:Media/tt:XAddr")
		adapter.events_url = _txt(caps, ".//tt:Events/tt:XAddr")
		rep["capabilities"].update({"media": bool(adapter.media_url), "events_service": bool(adapter.events_url),
			"analytics": caps.find(".//tt:Analytics", NS) is not None, "ptz": caps.find(".//tt:PTZ", NS) is not None})
	services = await _soap(adapter, p, dev, "<tds:GetServices><tds:IncludeCapability>false</tds:IncludeCapability></tds:GetServices>", "Services")
	ns_list = [_txt(s, "tds:Namespace") for s in services.findall(".//tds:Service", NS)] if services is not None else []
	replay = next((s for s in (services.findall(".//tds:Service", NS) if services is not None else []) if "replay" in (_txt(s, "tds:Namespace") or "")), None)
	rep["capabilities"]["playback"] = replay is not None
	rep["capabilities"]["profile_g_recording"] = any("recording" in (n or "") for n in ns_list)

	if adapter.media_url:
		prof = await _soap(adapter, p, adapter.media_url, "<trt:GetProfiles/>", "Media profiles")
		chans = {}
		if prof is not None:
			order = []
			for pr in prof.findall(".//trt:Profiles", NS):
				src = _txt(pr, ".//tt:VideoSourceConfiguration/tt:SourceToken") or "default"
				if src not in order:
					order.append(src)
				n = order.index(src) + 1
				c = chans.setdefault(n, {"channel_no": n, "name": f"Video source {n}", "online": True, "model": rep["device"].get("model")})
				enc = pr.find(".//tt:VideoEncoderConfiguration", NS)
				s = {"stream_id": pr.get("token"), "codec": _txt(enc, "tt:Encoding"), "width": _txt(enc, "tt:Resolution/tt:Width"),
					"height": _txt(enc, "tt:Resolution/tt:Height"), "fps": _txt(enc, "tt:RateControl/tt:FrameRateLimit"),
					"bitrate_kbps": _txt(enc, "tt:RateControl/tt:BitrateLimit")}
				c.setdefault("main" if "main" not in c else "sub", s)
		rep["channels"] = [chans[k] for k in sorted(chans)]

	topics = set()
	if adapter.events_url:
		props = await _soap(adapter, p, adapter.events_url, "<tev:GetEventProperties/>", "Event topics")
		if props is not None:
			ts = props.find(".//{http://docs.oasis-open.org/wsn/t-1}TopicSet")
			if ts is not None:
				def walk(el, path):
					for ch in el:
						tag = ch.tag.split("}")[-1]
						if ch.get("{http://docs.oasis-open.org/wsn/t-1}topic") == "true" or not len(ch):
							topics.add(f"{path}/{tag}".strip("/"))
						walk(ch, f"{path}/{tag}")
				walk(ts, "")
	rep["events"]["device"] = sorted(topics)
	rep["events"]["normalised"] = sorted({kind for t in topics for suffix, kind, _ in TOPICS if t.endswith(suffix)})

	tm = await _soap(adapter, p, dev, "<tds:GetSystemDateAndTime/>", "Clock", auth=False)
	if tm is not None:
		d = tm.find(".//tt:UTCDateTime", NS)
		rep["time"]["mode"] = _txt(tm, ".//tt:DateTimeType")
		rep["time"]["ntp"] = rep["time"]["mode"] == "NTP"
		if d is not None:
			g = lambda x: int(d.find(x, NS).text)  # noqa: E731
			dt = datetime(g("tt:Date/tt:Year"), g("tt:Date/tt:Month"), g("tt:Date/tt:Day"), g("tt:Time/tt:Hour"), g("tt:Time/tt:Minute"),
				g("tt:Time/tt:Second"), tzinfo=timezone.utc)
			rep["time"]["offset_seconds"] = round((dt - datetime.now(timezone.utc)).total_seconds(), 1)
	log = await _soap(adapter, p, dev, "<tds:GetSystemLog><tds:LogType>System</tds:LogType></tds:GetSystemLog>", "Device system log")
	if log is not None:
		text = _txt(log, ".//tt:String") or ""
		lines = [ln for ln in text.splitlines() if ln.strip()][-200:]
		summary = {}
		for ln in lines:
			low = ln.lower()
			cat = ("hdd" if "disk" in low or "hdd" in low or "storage" in low else "video_loss" if "video loss" in low
				else "network" if "network" in low or "link down" in low or "ip conflict" in low else "illegal_login" if "login fail" in low or "auth" in low
				else "abnormal_reboot" if "reboot" in low or "watchdog" in low or "crash" in low or "panic" in low else None)
			if cat:
				summary[cat] = summary.get(cat, 0) + 1
		rep["logs"] = {"summary": summary, "recent": [{"time": None, "type": "log", "category": None, "detail": ln[:200]} for ln in lines[-50:]][::-1],
			"days": log_days}
