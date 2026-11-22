"""Dahua (HTTP CGI) survey."""

import re
from datetime import datetime, timedelta, timezone

from cctv_agent.adapters.dahua import EVENT_MAP

LOG_TYPES = {
	"DiskError": "hdd", "DiskFull": "hdd", "StorageFailure": "hdd", "StorageLowSpace": "hdd", "NoDisk": "hdd",
	"VideoLoss": "video_loss", "NetAbort": "network", "IPConflict": "network", "NetworkAbort": "network",
	"LoginFailure": "illegal_login", "LoginLocked": "illegal_login", "RecordFailure": "record",
	"Reboot": "reboot", "AbnormalReboot": "abnormal_reboot", "ShutDown": "abnormal_reboot",
}


def kv(text):
	"""'a.b[0].c=1' lines -> {'a.b[0].c': '1'}"""
	out = {}
	for line in (text or "").splitlines():
		if "=" in line:
			k, v = line.split("=", 1)
			out[k.strip()] = v.strip()
	return out


def _get(d, *keys):
	for k in keys:
		if d.get(k) not in (None, ""):
			return d[k]
	return None


async def survey(adapter, p, rep, log_days=7):
	B = "/cgi-bin/"
	dev = {}
	for action, label in (("getDeviceType", "Device type"), ("getSerialNo", "Serial number"), ("getSoftwareVersion", "Firmware"),
			("getHardwareVersion", "Hardware version"), ("getMachineName", "Device name")):
		r = await p.get(f"{B}magicBox.cgi?action={action}", label)
		if r is not None:
			dev.update(kv(r.text))
	rep["device"] = {"deviceName": _get(dev, "name"), "model": _get(dev, "type"), "serialNumber": _get(dev, "sn"),
		"firmwareVersion": _get(dev, "version"), "hardwareVersion": _get(dev, "version.hardware", "hardwareVersion")}

	titles = kv(getattr(await p.get(f"{B}configManager.cgi?action=getConfig&name=ChannelTitle", "Channel names"), "text", ""))
	chans = {}
	for k, v in titles.items():
		m = re.match(r"table\.ChannelTitle\[(\d+)\]\.Name", k)
		if m:
			n = int(m.group(1)) + 1
			chans[n] = {"channel_no": n, "name": v}
	remote = kv(getattr(await p.get(f"{B}configManager.cgi?action=getConfig&name=RemoteDevice", "Connected IP cameras"), "text", ""))
	devices = {}
	for k, v in remote.items():
		m = re.match(r"table\.RemoteDevice\.([^.]+)\.(Address|DeviceType|Name|Enable|Version|VideoInputs\[0\]\.Name|VideoInputChannels)", k)
		if m:
			devices.setdefault(m.group(1), {})[m.group(2)] = v
	# Dahua numbers remote devices by uuid; map in order onto channels with no better key
	for i, d in enumerate(devices.values(), start=1):
		c = chans.setdefault(i, {"channel_no": i})
		c.update({"ip": d.get("Address"), "model": d.get("DeviceType"), "camera_firmware": d.get("Version")})
	state = await p.get(f"{B}LogicDeviceManager.cgi?action=getCameraState&uniqueChannels[0]=-1", "Camera online state")
	if state is not None:
		for k, v in kv(state.text).items():
			m = re.match(r"states\[(\d+)\]\.connectionState", k)
			if m:
				ch = chans.setdefault(int(m.group(1)) + 1, {"channel_no": int(m.group(1)) + 1})
				ch["online"] = v.lower() == "connected"
				ch["detail"] = v
	enc = kv(getattr(await p.get(f"{B}configManager.cgi?action=getConfig&name=Encode", "Stream settings"), "text", ""))
	for k, v in enc.items():
		m = re.match(r"table\.Encode\[(\d+)\]\.(MainFormat|ExtraFormat)\[0\]\.Video\.(Compression|Width|Height|FPS|BitRate)$", k)
		if m:
			c = chans.setdefault(int(m.group(1)) + 1, {"channel_no": int(m.group(1)) + 1})
			s = c.setdefault("main" if m.group(2) == "MainFormat" else "sub", {})
			s[{"Compression": "codec", "Width": "width", "Height": "height", "FPS": "fps", "BitRate": "bitrate_kbps"}[m.group(3)]] = v
	rep["channels"] = [chans[k] for k in sorted(chans)]

	stor = await p.get(f"{B}storageDevice.cgi?action=getDeviceAllInfo", "Disks")
	if stor is not None:
		info = kv(stor.text)
		disks = {}
		for k, v in info.items():
			m = re.match(r"list\.info\[(\d+)\]\.(State|Name|Detail\[0\]\.TotalBytes|Detail\[0\]\.UsedBytes|Detail\[0\]\.IsError)", k)
			if m:
				disks.setdefault(m.group(1), {})[m.group(2)] = v
		for d in disks.values():
			total = float(d.get("Detail[0].TotalBytes") or 0)
			used = float(d.get("Detail[0].UsedBytes") or 0)
			err = (d.get("Detail[0].IsError") or "false").lower() == "true"
			rep["storage"].append({"name": d.get("Name"), "status": "error" if err else (d.get("State") or "ok"),
				"capacity_gb": round(total / 1e9, 1) if total else None, "free_gb": round((total - used) / 1e9, 1) if total else None})
	rec = kv(getattr(await p.get(f"{B}configManager.cgi?action=getConfig&name=RecordMode", "Recording mode"), "text", ""))
	rep["recording"]["modes"] = {str(int(re.search(r"\[(\d+)\]", k).group(1)) + 1): {"0": "Schedule", "1": "Continuous", "2": "Off"}.get(v, v)
		for k, v in rec.items() if k.endswith(".Mode")}

	ev = await p.get(f"{B}eventManager.cgi?action=getExposureEvents", "Supported events")
	if ev is not None:
		rep["events"]["device"] = sorted({v for k, v in kv(ev.text).items() if k.startswith("events[")})
	norm = {EVENT_MAP[e] for e in rep["events"]["device"] if e in EVENT_MAP}
	rep["capabilities"].update({"anpr": "plate_read" in norm, "face": "face_match" in norm})
	rep["events"]["normalised"] = sorted(norm)

	tm = await p.get(f"{B}global.cgi?action=getCurrentTime", "Clock")
	if tm is not None:
		m = re.search(r"result=(.+)", tm.text)
		if m:
			dev_t = datetime.strptime(m.group(1).strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=adapter.tz)
			rep["time"].update({"device_time": m.group(1).strip(), "offset_seconds": round((dev_t - datetime.now(timezone.utc)).total_seconds(), 1)})
	ntp = kv(getattr(await p.get(f"{B}configManager.cgi?action=getConfig&name=NTP", "NTP"), "text", ""))
	if ntp:
		rep["time"].update({"ntp": (ntp.get("table.NTP.Enable") or "").lower() == "true", "ntp_servers": [ntp.get("table.NTP.Address")]})

	end = datetime.now(adapter.tz)
	start = end - timedelta(days=log_days)
	f = await p.get(f"{B}log.cgi?action=startFind&condition.StartTime={start:%Y-%m-%d%%20%H:%M:%S}&condition.EndTime={end:%Y-%m-%d%%20%H:%M:%S}",
		"Device log (start search)")
	token = kv(getattr(f, "text", "")).get("token")
	if token:
		r = await p.get(f"{B}log.cgi?action=doFind&token={token}&count=500", "Device log (read)")
		await p.get(f"{B}log.cgi?action=stopFind&token={token}", "Device log (close search)")
		items = {}
		for k, v in kv(getattr(r, "text", "")).items():
			m = re.match(r"items\[(\d+)\]\.(Type|Time|User|Detail\.?[^=]*)", k)
			if m:
				items.setdefault(int(m.group(1)), {})[m.group(2).split(".")[0]] = v
		summary, recent = {}, []
		for it in items.values():
			cat = LOG_TYPES.get(it.get("Type"), "other")
			summary[cat] = summary.get(cat, 0) + 1
			recent.append({"time": it.get("Time"), "type": it.get("Type"), "category": cat, "detail": it.get("Detail"), "user": it.get("User")})
		rep["logs"] = {"summary": summary, "recent": sorted(recent, key=lambda x: x["time"] or "", reverse=True)[:50], "days": log_days}
	rep["capabilities"]["playback"] = True  # Dahua's RTSP playback path is standard; confirmed by the stream probe
