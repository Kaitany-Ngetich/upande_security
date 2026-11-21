"""One camera through the engine:

	stream (sampled frames) -> motion trigger -> detectors -> tracker
	-> best frame per object -> plate OCR / face embedding -> vote / match
	-> normalised event (same schema as camera-native analytics)

Heavy models run only while something moves. Each vehicle is read on several
frames and the readings are voted into one plate; each person gets one
person_detected event per track and, where faces are licensed and enrolled,
one face_match / face_unknown.

CCTV Camera > Analytics Config (JSON) per camera, all optional:
	{"fps": 4, "width": 1280, "height": 720, "roi": [x1, y1, x2, y2] (0..1),
	 "min_plate_width": 80, "motion_threshold": 6, "max_track_seconds": 60}
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone

import numpy as np

from cctv_agent.engine.imageops import crop, resize, sharpness, to_jpeg
from cctv_agent.engine.plates import vote
from cctv_agent.engine.tracker import IouTracker
from cctv_agent.envelope import make_event, plate_direction

log = logging.getLogger("cctv_agent.engine")
VEHICLES = {"car", "truck", "bus", "motorcycle", "motorbike", "vehicle", "van"}
PEOPLE = {"person", "pedestrian"}


class CameraWorker:
	def __init__(self, site, camera, models, on_event, faces=None, face_threshold=0.6, plate_patterns=None, shadow=None):
		self.site, self.camera = site, camera
		self.m = models  # {"vehicle_detector", "person_detector", "plate_detector", "plate_ocr", "face_detector", "face_embedder"}
		self.shadow = shadow or {}
		self.on_event = on_event
		self.faces = faces
		self.face_threshold = face_threshold
		self.patterns = plate_patterns
		cfg = camera.get("analytics_config") or {}
		self.cfg = json.loads(cfg) if isinstance(cfg, str) and cfg.strip() else (cfg if isinstance(cfg, dict) else {})
		self.tracker = IouTracker()
		self.prev = None
		self.model_version = ",".join(sorted(getattr(models, "versions", {}).values())) if hasattr(models, "versions") else "engine"

	# ---- per frame ------------------------------------------------------------------
	def _moving(self, img):
		small = resize(img, 64, 36).mean(axis=2)
		moving = self.prev is not None and float(np.abs(small - self.prev).mean()) > self.cfg.get("motion_threshold", 6)
		self.prev = small
		return moving

	def _in_roi(self, box, W, H):
		roi = self.cfg.get("roi")
		if not roi:
			return True
		cx, cy = (box[0] + box[2]) / 2 / W, (box[1] + box[3]) / 2 / H
		return roi[0] <= cx <= roi[2] and roi[1] <= cy <= roi[3]

	async def process(self, img, t=None):
		t = t or time.time()
		H, W = img.shape[:2]
		dets = []
		if self._moving(img) or self.tracker.tracks:
			for key in ("vehicle_detector", "person_detector"):
				det = self.m.get(key)
				# One combined detector (vehicles + people) is common: run it once.
				if det and (key == "vehicle_detector" or det is not self.m.get("vehicle_detector")):
					dets += [d for d in det.detect(img) if self._in_roi(d[0], W, H) and (d[1] in VEHICLES or d[1] in PEOPLE)]
		active, ended = self.tracker.update(dets, t)
		for tr in active:
			if tr.misses:
				continue
			if tr.cls in VEHICLES:
				self._observe_vehicle(tr, img)
			elif tr.cls in PEOPLE:
				await self._observe_person(tr, img, t)
			if t - tr.first > self.cfg.get("max_track_seconds", 60) and not tr.emitted:
				await self._finish(tr)
		for tr in ended:
			await self._finish(tr)

	def _observe_vehicle(self, tr, img):
		vcrop = crop(img, tr.box)
		q = sharpness(vcrop) * (vcrop.shape[0] * vcrop.shape[1]) ** 0.5
		if not tr.best or q > tr.best[0]:
			tr.best = (q, vcrop, tr.box)
		pdet, ocr = self.m.get("plate_detector"), self.m.get("plate_ocr")
		if not (pdet and ocr) or not vcrop.size:
			return
		plates = sorted(pdet.detect(vcrop), key=lambda d: -d[2])
		if not plates:
			return
		pbox = plates[0][0]
		if pbox[2] - pbox[0] < self.cfg.get("min_plate_width", 0):
			return  # too few pixels across the plate to read reliably
		pcrop = crop(vcrop, pbox, pad=0.05)
		if not pcrop.size:
			return
		text, conf = ocr.read(pcrop)
		if text:
			tr.reads.append((text, conf * plates[0][2]))
			if tr.plate_crop is None or conf > tr.plate_conf:
				tr.plate_crop, tr.plate_conf = pcrop, conf
		sh = self.shadow.get("plate_ocr")
		if sh:
			try:
				s_text, s_conf = sh.read(pcrop)
				if s_text != text:
					log.info("shadow OCR differs on %s: live=%s shadow=%s", self.camera["name"], text, s_text)
			except Exception:
				pass

	async def _observe_person(self, tr, img, t):
		pcrop = crop(img, tr.box)
		q = sharpness(pcrop) * (pcrop.shape[0] * pcrop.shape[1]) ** 0.5 if pcrop.size else 0
		if not tr.best or q > tr.best[0]:
			tr.best = (q, pcrop, tr.box)
		if not tr.emitted and len(tr.boxes) >= 3:
			tr.emitted = True
			await self._emit("person_detected", {"track_id": str(tr.id), "count": 1}, tr.scores[-1], pcrop)
			await self._face(tr)

	async def _face(self, tr):
		fdet, emb = self.m.get("face_detector"), self.m.get("face_embedder")
		if not (self.faces is not None and fdet and emb and tr.best):
			return
		pcrop = tr.best[1]
		faces = sorted(fdet.detect(pcrop), key=lambda d: -d[2])
		if not faces:
			return
		fcrop = crop(pcrop, faces[0][0], pad=0.1)
		if fcrop.shape[0] < 40:
			return  # too small to recognise
		person, sim = self.faces.match(emb.embed(fcrop), self.face_threshold)
		if person:
			await self._emit("face_match", {"person_ref": person, "similarity": round(sim, 3), "track_id": str(tr.id)}, sim, fcrop)
		else:
			await self._emit("face_unknown", {"quality": round(faces[0][2], 3), "track_id": str(tr.id)}, None, fcrop)

	async def _finish(self, tr):
		if tr.emitted:
			return
		tr.emitted = True
		if tr.cls not in VEHICLES:
			return
		trend = tr.area_trend()
		raw_dir = "forward" if trend > 1.2 else "reverse" if trend < 0.8 else ""
		direction = plate_direction(raw_dir, self.camera.get("direction_in")) if raw_dir else "unknown"
		vtype = "motorcycle" if tr.cls in ("motorcycle", "motorbike") else tr.cls
		if tr.reads:
			plate, conf = vote(tr.reads, self.patterns)
			if plate:
				await self._emit("plate_read", {"plate": plate, "direction": direction, "vehicle_type": vtype, "frames": len(tr.reads)},
					conf, tr.plate_crop if tr.plate_crop is not None else (tr.best[1] if tr.best else None))
				return
		await self._emit("vehicle_detected", {"track_id": str(tr.id), "vehicle_type": vtype, "direction": direction},
			max(tr.scores), tr.best[1] if tr.best else None)

	async def _emit(self, kind, data, conf, image=None):
		ev = make_event(self.site, self.camera["name"], kind, datetime.now(timezone.utc), data, conf,
			provider="own_engine", model_version=self.model_version)
		jpeg = to_jpeg(image) if image is not None and getattr(image, "size", 0) else None
		await self.on_event(ev, jpeg)

	# ---- stream -----------------------------------------------------------------------
	async def run(self, source_url):
		"""Pull frames with ffmpeg (RGB, scaled, sampled) and process them. Raises on stream end."""
		fps = self.cfg.get("fps", 4)
		w, h = self.cfg.get("width", 1280), self.cfg.get("height", 720)
		proc = await asyncio.create_subprocess_exec(
			"ffmpeg", "-hide_banner", "-loglevel", "error", "-rtsp_transport", "tcp", "-i", source_url,
			"-vf", f"fps={fps},scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
			stdout=asyncio.subprocess.PIPE)
		size = w * h * 3
		try:
			while True:
				buf = await proc.stdout.readexactly(size)
				img = np.frombuffer(buf, np.uint8).reshape(h, w, 3)
				await self.process(img)
		finally:
			if proc.returncode is None:
				proc.kill()
