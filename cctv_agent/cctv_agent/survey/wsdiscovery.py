"""Find ONVIF devices on the local network (WS-Discovery multicast probe)."""

import re
import socket
import time
import uuid

PROBE = """<?xml version="1.0" encoding="UTF-8"?>
<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope" xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing"
 xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery" xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
<e:Header><w:MessageID>uuid:{id}</w:MessageID><w:To e:mustUnderstand="true">urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>
<w:Action e:mustUnderstand="true">http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action></e:Header>
<e:Body><d:Probe><d:Types>dn:NetworkVideoTransmitter</d:Types></d:Probe></e:Body></e:Envelope>"""


def parse(xml):
	xaddrs = re.search(r"XAddrs>([^<]+)<", xml)
	scopes = re.search(r"Scopes[^>]*>([^<]+)<", xml)
	sc = (scopes.group(1) if scopes else "").split()
	pick = lambda key: next((s.split(f"/{key}/", 1)[1] for s in sc if f"/{key}/" in s), None)  # noqa: E731
	urls = (xaddrs.group(1) if xaddrs else "").split()
	host = re.search(r"//([^/:]+)", urls[0]).group(1) if urls else None
	return {"host": host, "xaddrs": urls, "name": pick("name"), "hardware": pick("hardware"), "location": pick("location"),
		"brand_hint": next((b for b in ("Hikvision", "Dahua", "Uniview", "Axis", "Hanwha", "Bosch") if b.lower() in " ".join(sc).lower()), None)}


def discover(timeout=3.0, iface_ip=None):
	sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
	sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
	if iface_ip:
		sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(iface_ip))
	sock.settimeout(0.5)
	sock.sendto(PROBE.format(id=uuid.uuid4()).encode(), ("239.255.255.250", 3702))
	found, end = {}, time.time() + timeout
	while time.time() < end:
		try:
			data, addr = sock.recvfrom(65535)
		except socket.timeout:
			continue
		d = parse(data.decode(errors="replace"))
		found[d["host"] or addr[0]] = d
	sock.close()
	return list(found.values())
