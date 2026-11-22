"""Survey report as a self-contained HTML page (and plain text)."""

from html import escape

LABELS = {"deviceName": "Name", "model": "Model", "serialNumber": "Serial number", "firmwareVersion": "Firmware",
	"firmwareReleasedDate": "Firmware date", "deviceType": "Type", "macAddress": "MAC address", "hardwareVersion": "Hardware",
	"encoderVersion": "Encoder", "manufacturer": "Manufacturer", "cpu_percent": "CPU %", "memory_percent": "Memory %", "uptime_hours": "Up (hours)"}
COLOURS = {"blocker": "#b42318", "warn": "#b54708", "ok": "#067647", "info": "#344054"}


def _e(v):
	return escape("" if v is None else str(v))


def _table(head, rows):
	if not rows:
		return "<p class='muted'>Nothing returned.</p>"
	h = "".join(f"<th>{_e(x)}</th>" for x in head)
	b = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
	return f"<table><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table>"


def _stream(s):
	if not s:
		return "<span class='muted'>-</span>"
	res = f"{s.get('width')}x{s.get('height')}" if s.get("width") else ""
	return _e(" ".join(str(x) for x in (s.get("codec"), res, f"{s.get('fps')} fps" if s.get("fps") else None) if x))


def html(rep):
	d, t = rep.get("device") or {}, rep.get("target") or {}
	verdict = rep.get("verdict") or "-"
	vcol = {"Ready": "#067647", "Ready with fixes": "#b54708", "Not ready": "#b42318"}.get(verdict, "#344054")
	findings = "".join(f"<li><b style='color:{COLOURS.get(f['level'], '#344054')}'>{_e(f['level'].upper())}</b> "
		f"<span class='muted'>{_e(f['topic'])}</span> - {_e(f['text'])}</li>" for f in rep.get("findings") or [])
	chans = _table(["Ch", "Name", "Camera model", "IP", "Online", "Main stream", "Sub stream", "Recording", "Events"], [[
		_e(c.get("channel_no")), _e(c.get("name")), _e(c.get("model")), _e(c.get("ip")),
		"<b style='color:#067647'>yes</b>" if c.get("online") else "<b style='color:#b42318'>no</b>" if c.get("online") is False else "-",
		_stream(c.get("main")), _stream(c.get("sub")), _e((rep.get("recording", {}).get("modes") or {}).get(str(c.get("channel_no")), "-")),
		_e(", ".join((rep.get("events", {}).get("by_channel") or {}).get(str(c.get("channel_no")), [])) or "-"),
	] for c in rep.get("channels") or []])
	disks = _table(["Disk", "Status", "Size GB", "Free GB", "Type"], [[_e(x.get("name")), _e(x.get("status")), _e(x.get("capacity_gb")),
		_e(x.get("free_gb")), _e(x.get("type"))] for x in rep.get("storage") or []])
	logs = rep.get("logs") or {}
	log_sum = ", ".join(f"{_e(k)}: {v}" for k, v in sorted((logs.get("summary") or {}).items(), key=lambda x: -x[1])) or "no exceptions logged"
	log_rows = _table(["Time", "Type", "Category", "Detail"], [[_e(x.get("time")), _e(x.get("type")), _e(x.get("category")), _e(x.get("detail"))]
		for x in (logs.get("recent") or [])[:30]])
	api = _table(["What", "Endpoint", "Result", "ms"], [[_e(c["what"]), f"<code>{_e(c['method'])} {_e(c['endpoint'])}</code>",
		("<b style='color:#067647'>OK</b>" if c["ok"] else f"<b style='color:#b42318'>{_e(c.get('status') or 'error')}</b> <span class='muted'>{_e(c.get('error'))}</span>"),
		_e(c.get("ms"))] for c in rep.get("api") or []])
	ok_n = sum(1 for c in rep.get("api") or [] if c["ok"])
	ev = rep.get("events") or {}
	tm = rep.get("time") or {}
	return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>CCTV site survey - {_e(t.get('host'))}</title>
<style>body{{font:14px/1.5 system-ui,Segoe UI,Arial;margin:24px;color:#101828;background:#fff}}h1{{margin:0 0 4px;font-size:22px}}
h2{{font-size:16px;margin:28px 0 8px;border-bottom:1px solid #eaecf0;padding-bottom:4px}}table{{border-collapse:collapse;width:100%;font-size:13px}}
th,td{{border-bottom:1px solid #eaecf0;padding:6px 8px;text-align:left;vertical-align:top}}th{{background:#f9fafb;font-weight:600}}
.muted{{color:#667085}}.verdict{{display:inline-block;padding:4px 12px;border-radius:999px;color:#fff;background:{vcol};font-weight:600}}
code{{font-size:12px}}ul{{padding-left:18px}}li{{margin:4px 0}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:8px 24px}}</style></head><body>
<h1>CCTV site survey</h1><p class="muted">{_e(t.get('brand'))} at {_e(t.get('host'))} &middot; {_e(rep.get('surveyed_at'))} UTC</p>
<p><span class="verdict">{_e(verdict)}</span></p>
<h2>Findings</h2><ul>{findings or "<li class='muted'>None.</li>"}</ul>
<h2>Device</h2><div class="grid">{''.join(f"<div><span class='muted'>{_e(LABELS.get(k, k))}</span><br>{_e(v)}</div>" for k, v in {**d, **(rep.get('status') or {})}.items() if v)}</div>
<h2>Cameras ({len(rep.get('channels') or [])})</h2>{chans}
<h2>Recording and disks</h2>{disks}
<h2>Events it can send</h2><p><b>Usable by Upande Security:</b> {_e(', '.join(ev.get('normalised') or []) or 'none found')}<br>
<span class="muted">Device event types: {_e(', '.join(ev.get('device') or []) or '-')}</span></p>
<p><span class="muted">Plate recognition (ANPR):</span> {_e((rep.get('capabilities') or {}).get('anpr'))} &middot;
<span class="muted">Face:</span> {_e((rep.get('capabilities') or {}).get('face'))} &middot;
<span class="muted">Recorder playback:</span> {_e((rep.get('capabilities') or {}).get('playback'))}</p>
<h2>Clock</h2><p>Mode {_e(tm.get('mode'))}, NTP {_e(tm.get('ntp'))} {_e(', '.join(x for x in tm.get('ntp_servers') or [] if x))},
offset {_e(tm.get('offset_seconds'))} s, device time {_e(tm.get('device_time'))}</p>
<h2>Device log - last {_e(logs.get('days', 7))} days</h2><p>{log_sum}</p>{log_rows}
<h2>API coverage ({ok_n} of {len(rep.get('api') or [])} calls answered)</h2>{api}
<p class="muted" style="margin-top:32px">Produced by the Upande Security CCTV site agent. Recorder passwords are not included.</p>
</body></html>"""


def text(rep):
	lines = [f"CCTV site survey - {rep['target'].get('brand')} {rep['target'].get('host')} - {rep.get('verdict')}"]
	d = rep.get("device") or {}
	lines.append(f"Device: {d.get('model')} fw {d.get('firmwareVersion')} sn {d.get('serialNumber')}")
	lines += [f"  [{f['level'].upper()}] {f['topic']}: {f['text']}" for f in rep.get("findings") or []]
	ok_n = sum(1 for c in rep.get("api") or [] if c["ok"])
	lines.append(f"API calls answered: {ok_n}/{len(rep.get('api') or [])}")
	return "\n".join(lines)
