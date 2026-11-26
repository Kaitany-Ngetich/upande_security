"""agent.yml -> settings. Secrets are read from files (Docker secrets), never inline."""

import os
from dataclasses import dataclass, field

import yaml


def _read(path):
	if not path:
		return ""
	with open(path) as fh:
		return fh.read().strip()


@dataclass
class Config:
	agent_id: str
	erp_url: str
	api_key: str
	api_secret: str
	hmac_secret: str
	site_timezone: str = "Africa/Nairobi"
	batch_size: int = 100
	batch_interval_ms: int = 1000
	heartbeat_seconds: int = 30
	config_poll_seconds: int = 60
	health_seconds: int = 60
	buffer_path: str = "/data/buffer.db"
	buffer_max_mb: int = 20480
	site_config_cache: str = "/data/site_config.json"
	upload_snapshots: bool = True
	mediamtx_api: str = "http://127.0.0.1:9997"
	auth_listen: str = "127.0.0.1:8765"
	rtsp_port: int = 8554
	transcode_h265: bool = False
	log_level: str = "INFO"
	extra: dict = field(default_factory=dict)


def load(path):
	with open(path) as fh:
		raw = yaml.safe_load(fh) or {}
	a, b, g = raw.get("agent", {}), raw.get("buffer", {}), raw.get("gateway", {})
	return Config(
		agent_id=a["id"],
		erp_url=a["erp_url"],
		api_key=os.environ.get("CCTV_API_KEY") or _read(a.get("api_key_file")),
		api_secret=os.environ.get("CCTV_API_SECRET") or _read(a.get("api_secret_file")),
		hmac_secret=os.environ.get("CCTV_HMAC_SECRET") or _read(a.get("hmac_secret_file")),
		site_timezone=a.get("site_timezone", "Africa/Nairobi"),
		batch_size=min(int(a.get("batch_size", 100)), 100),
		batch_interval_ms=int(a.get("batch_interval_ms", 1000)),
		heartbeat_seconds=int(a.get("heartbeat_seconds", 30)),
		config_poll_seconds=int(a.get("config_poll_seconds", 60)),
		health_seconds=int(a.get("health_seconds", 60)),
		buffer_path=b.get("path", "/data/buffer.db"),
		buffer_max_mb=int(b.get("max_size_mb", 20480)),
		site_config_cache=b.get("site_config_cache", os.path.join(os.path.dirname(b.get("path", "/data/buffer.db")), "site_config.json")),
		upload_snapshots=bool(a.get("upload_snapshots", True)),
		mediamtx_api=g.get("api", "http://127.0.0.1:9997"),
		auth_listen=g.get("auth_listen", "127.0.0.1:8765"),
		rtsp_port=int(g.get("rtsp_port", 8554)),
		transcode_h265=bool(g.get("transcode_h265", False)),
		log_level=raw.get("log_level", "INFO"),
		extra=raw,
	)
