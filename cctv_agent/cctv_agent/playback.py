"""Recorder playback for one requested range, started by MediaMTX on demand.

mediamtx.yml:
	paths:
	  "~^pb/":
	    runOnDemand: python -m cctv_agent.playback --config /config/agent.yml
	    runOnDemandCloseAfter: 15s

MediaMTX sets MTX_PATH (pb/<camera key>/<startZ>_<endZ>) and RTSP_PORT. This
looks the camera up in the cached site config, asks its adapter for the
recorder's playback URL for that range, and replaces itself with ffmpeg
re-publishing it to MediaMTX. The token was already checked by the auth hook
before MediaMTX ran this.
"""

import argparse
import json
import os
import re
import sys
import zoneinfo
from datetime import datetime, timezone

from cctv_agent.adapters import adapter_for
from cctv_agent.config import load
from cctv_agent.envelope import camera_key

PATH_RE = re.compile(r"^pb/(?P<cam>[^/]+)/(?P<start>\d{8}T\d{6}Z)_(?P<end>\d{8}T\d{6}Z)$")


def parse_path(path):
	m = PATH_RE.match(path or "")
	if not m:
		raise ValueError(f"not a playback path: {path}")
	t = lambda s: datetime.strptime(s, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)  # noqa: E731
	return m.group("cam"), t(m.group("start")), t(m.group("end"))


def ffmpeg_cmd(source, target, transcode=False):
	video = ["-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency"] if transcode else ["-c:v", "copy"]
	return ["ffmpeg", "-hide_banner", "-loglevel", "error", "-rtsp_transport", "tcp", "-re", "-i", source, *video,
		"-c:a", "aac", "-f", "rtsp", target]


def main(argv=None):
	ap = argparse.ArgumentParser()
	ap.add_argument("--config", default="/config/agent.yml")
	args = ap.parse_args(argv)
	cfg = load(args.config)
	path = os.environ.get("MTX_PATH", "")
	key, start, end = parse_path(path)
	with open(cfg.site_config_cache) as fh:
		site = json.load(fh)
	cam = next((c for c in site["cameras"] if camera_key(c["name"]) == key), None)
	if not cam:
		sys.exit(f"unknown camera {key}")
	server = next(s for s in site["servers"] if s["name"] == cam["server"])
	adapter = adapter_for(server, site["site"], zoneinfo.ZoneInfo(cfg.site_timezone))
	source = adapter.get_playback_uri(cam, start, end)
	if not source:
		sys.exit(f"{server.get('brand')} playback is not supported for {cam['name']}")
	target = f"rtsp://127.0.0.1:{os.environ.get('RTSP_PORT', '8554')}/{path}"
	cmd = ffmpeg_cmd(source, target, transcode=cfg.transcode_h265 and cam.get("codec") == "H.265")
	os.execvp(cmd[0], cmd)


if __name__ == "__main__":
	main()
