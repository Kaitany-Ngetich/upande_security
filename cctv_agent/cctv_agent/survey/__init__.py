"""Site survey: what a CCTV recorder is, what it can do, how healthy it is,
and how it fits Upande Security. See run_survey()."""

import re
import zoneinfo

from cctv_agent.adapters import adapter_for
from cctv_agent.survey.core import Probe, blank_report, ffprobe, judge


def _mask(url):
	return re.sub(r"//[^@/]+@", "//***@", url or "")


async def run_survey(server, site="survey", probe_streams=True, max_streams=8, log_days=7, site_timezone="Africa/Nairobi", _transport=None):
	"""server: {brand, host, port, use_tls, verify_tls, username, password, name}. Returns the report dict.
	_transport: an httpx transport (tests use a mock device)."""
	adapter = adapter_for(server, site, zoneinfo.ZoneInfo(site_timezone))
	if _transport is not None:
		import httpx

		await adapter.http.aclose()
		adapter.http = httpx.AsyncClient(transport=_transport)
	p = Probe(adapter)
	rep = blank_report(server)
	brand = (server.get("brand") or "ONVIF").lower()
	try:
		if brand == "hikvision":
			from cctv_agent.survey.hikvision import survey
		elif brand == "dahua":
			from cctv_agent.survey.dahua import survey
		else:
			from cctv_agent.survey.onvif import survey
		await survey(adapter, p, rep, log_days)

		if probe_streams:
			for ch in rep["channels"][:max_streams]:
				cam = {"name": ch.get("name") or f"ch{ch['channel_no']}", "channel_no": ch["channel_no"],
					"main_stream": (ch.get("main") or {}).get("stream_id"), "sub_stream": (ch.get("sub") or {}).get("stream_id")}
				for profile in ("sub", "main"):
					try:
						url = await adapter.stream_uri(cam, profile) if hasattr(adapter, "stream_uri") else adapter.get_stream_uri(cam, profile)
					except Exception as e:
						rep["streams_probed"].append({"channel_no": ch["channel_no"], "profile": profile, "error": str(e)[:120]})
						continue
					res = await ffprobe(url)
					rep["streams_probed"].append({"channel_no": ch["channel_no"], "profile": profile, "url": _mask(url), **res})
					if not res.get("error"):
						s = ch.setdefault(profile, {})
						for k in ("codec", "width", "height", "fps"):
							if res.get(k) and not s.get(k):
								s[k] = res[k].upper() if k == "codec" else res[k]
						ch["stream_ok"] = True
	finally:
		rep["api"] = p.calls
		await adapter.close()
	return judge(rep)
