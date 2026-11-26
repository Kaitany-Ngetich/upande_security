"""Survey a recorder from any laptop on the site network - no ERPNext needed.

	python -m cctv_agent.survey --brand Hikvision --host 192.168.1.64 --user admin --password-file pw.txt
	python -m cctv_agent.survey --scan                      # find ONVIF devices first

Writes survey-<host>.html (send this to the integration team) and .json.
"""

import argparse
import asyncio
import getpass
import json
import sys

from cctv_agent.survey import run_survey
from cctv_agent.survey.render import html, text


def main(argv=None):
	ap = argparse.ArgumentParser(description="Upande Security CCTV site survey")
	ap.add_argument("--scan", action="store_true", help="find ONVIF devices on this network and exit")
	ap.add_argument("--brand", choices=["Hikvision", "Dahua", "ONVIF", "Uniview", "Other"], default="ONVIF")
	ap.add_argument("--host")
	ap.add_argument("--port", type=int)
	ap.add_argument("--tls", action="store_true")
	ap.add_argument("--user", default="admin")
	ap.add_argument("--password-file", help="file holding the password (else you are asked)")
	ap.add_argument("--days", type=int, default=7, help="how many days of device log to read")
	ap.add_argument("--no-streams", action="store_true", help="skip opening the RTSP streams with ffprobe")
	ap.add_argument("--timezone", default="Africa/Nairobi")
	ap.add_argument("--out", help="output file prefix (default survey-<host>)")
	a = ap.parse_args(argv)
	if a.scan:
		from cctv_agent.survey.wsdiscovery import discover

		devices = discover()
		for d in devices:
			print(f"{d['host']:<16} {d.get('brand_hint') or '':<10} {d.get('hardware') or '':<20} {d.get('name') or ''}")
		print(f"{len(devices)} ONVIF device(s) answered. Recorders with ONVIF switched off will not show.")
		return 0
	if not a.host:
		ap.error("--host is needed (or --scan)")
	pw = open(a.password_file).read().strip() if a.password_file else getpass.getpass(f"Password for {a.user}@{a.host}: ")
	server = {"name": a.host, "brand": a.brand, "host": a.host, "port": a.port or (443 if a.tls else 80), "use_tls": a.tls, "verify_tls": 0,
		"username": a.user, "password": pw}
	rep = asyncio.run(run_survey(server, probe_streams=not a.no_streams, log_days=a.days, site_timezone=a.timezone))
	prefix = a.out or f"survey-{a.host}"
	with open(prefix + ".json", "w") as fh:
		json.dump(rep, fh, indent=1, default=str)
	with open(prefix + ".html", "w") as fh:
		fh.write(html(rep))
	print(text(rep))
	print(f"\nWrote {prefix}.html and {prefix}.json")
	return 0 if rep["verdict"] != "Not ready" else 2


if __name__ == "__main__":
	sys.exit(main())
