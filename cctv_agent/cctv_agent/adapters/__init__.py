from cctv_agent.adapters.dahua import DahuaAdapter
from cctv_agent.adapters.hikvision import HikvisionAdapter
from cctv_agent.adapters.onvif import OnvifAdapter

ADAPTERS = {"Hikvision": HikvisionAdapter, "Dahua": DahuaAdapter, "ONVIF": OnvifAdapter}


def adapter_for(server, site, site_tz=None):
	"""Brand -> adapter. Uniview / Other fall back to ONVIF, which most IP devices speak."""
	cls = ADAPTERS.get(server.get("brand"), OnvifAdapter)
	if cls is DahuaAdapter:
		return cls(server, site, site_tz)
	return cls(server, site)
