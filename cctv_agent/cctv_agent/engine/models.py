"""Model interfaces and ONNX implementations, plus the model manager.

INTERFACES (anything with these methods works - tests use fakes):
	Detector.detect(img) -> [(box(x1,y1,x2,y2), class_name, score)]
	PlateOCR.read(crop)  -> (text, confidence)
	FaceEmbedder.embed(crop) -> unit vector (numpy)

ONNX CONVENTIONS (export your models to match, or wrap them):
	detectors   input  1x3xHxW float 0..1 RGB;  output Nx6 [x1,y1,x2,y2,score,class_id]
	            in input pixels, NMS already applied (export with end-to-end NMS).
	plate OCR   input  1xHxWx3 uint8 (fast-plate-ocr style), output 1xSLOTSxALPHABET
	            probabilities; CCTV Engine Model > Labels holds the alphabet,
	            last character = padding.
	face embed  input  1x3x112x112 float (x-127.5)/127.5, output 1xD embedding.
Models, versions and licences are managed in ERPNext (CCTV Engine Model);
the agent downloads enabled ones and checks their sha256.
"""

import hashlib
import logging
import os

import numpy as np

from cctv_agent.engine.imageops import resize, to_input

log = logging.getLogger("cctv_agent.engine")


def _session(path):
	import onnxruntime as ort

	providers = [p for p in ("CUDAExecutionProvider", "OpenVINOExecutionProvider", "CPUExecutionProvider") if p in ort.get_available_providers()]
	return ort.InferenceSession(path, providers=providers)


class OnnxDetector:
	def __init__(self, path, labels, size=(640, 640), min_score=0.4):
		self.sess = _session(path)
		self.inp = self.sess.get_inputs()[0].name
		self.labels = labels
		self.w, self.h = size
		self.min_score = min_score

	def detect(self, img):
		H, W = img.shape[:2]
		out = self.sess.run(None, {self.inp: to_input(img, self.w, self.h)})[0]
		out = out.reshape(-1, out.shape[-1])
		sx, sy = W / self.w, H / self.h
		dets = []
		for x1, y1, x2, y2, score, cls in out[:, :6]:
			if score < self.min_score:
				continue
			name = self.labels[int(cls)] if int(cls) < len(self.labels) else str(int(cls))
			dets.append(((float(x1 * sx), float(y1 * sy), float(x2 * sx), float(y2 * sy)), name, float(score)))
		return dets


class OnnxPlateOCR:
	def __init__(self, path, alphabet, size=(140, 70)):
		self.sess = _session(path)
		self.inp = self.sess.get_inputs()[0].name
		self.alphabet = alphabet
		self.pad = alphabet[-1]
		self.w, self.h = size

	def read(self, crop):
		x = resize(crop, self.w, self.h)[None].astype(np.uint8)
		probs = self.sess.run(None, {self.inp: x})[0].reshape(-1, len(self.alphabet))
		idx = probs.argmax(axis=1)
		chars = [self.alphabet[i] for i in idx]
		conf = [probs[i, j] for i, j in enumerate(idx) if self.alphabet[j] != self.pad]
		text = "".join(c for c in chars if c != self.pad)
		return text, float(np.mean(conf)) if conf else 0.0


class OnnxFaceEmbedder:
	def __init__(self, path, size=(112, 112)):
		self.sess = _session(path)
		self.inp = self.sess.get_inputs()[0].name
		self.w, self.h = size

	def embed(self, crop):
		x = to_input(crop, self.w, self.h, scale=1.0, mean=127.5, std=127.5)
		v = self.sess.run(None, {self.inp: x})[0].reshape(-1).astype(np.float32)
		return v / (np.linalg.norm(v) or 1.0)


class ModelManager:
	"""Downloads the enabled models from ERPNext, verifies them, builds runners.
	A shadow-mode model is loaded beside the live one; its results are only logged."""

	def __init__(self, erp, folder):
		self.erp = erp
		self.folder = folder
		os.makedirs(folder, exist_ok=True)
		self.live = {}
		self.shadow = {}
		self.versions = {}

	async def sync(self):
		models = await self.erp.engine_models()
		live, shadow, versions = {}, {}, {}
		for m in models:
			path = os.path.join(self.folder, f"{m['name']}-{m['version']}.onnx")
			if not os.path.exists(path) or _sha(path) != m.get("sha256"):
				await self.erp.download_model(m["name"], path + ".part")
				if m.get("sha256") and _sha(path + ".part") != m["sha256"]:
					log.error("model %s failed its checksum - not used", m["name"])
					os.remove(path + ".part")
					continue
				os.replace(path + ".part", path)
			try:
				runner = build(m, path)
			except Exception as e:
				log.error("model %s could not load: %s", m["name"], e)
				continue
			(shadow if m.get("shadow_mode") else live)[m["task"]] = runner
			versions[m["task"]] = f"{m['name']}:{m['version']}"
		self.live, self.shadow, self.versions = live, shadow, versions
		log.info("engine models: %s", versions or "none")
		return versions


def build(m, path):
	labels = [l.strip() for l in (m.get("labels") or "").splitlines() if l.strip()]
	w, h = (int(x) for x in (m.get("input_size") or "640x640").lower().split("x"))
	if m["task"].endswith("_detector"):
		return OnnxDetector(path, labels, (w, h))
	if m["task"] == "plate_ocr":
		return OnnxPlateOCR(path, "".join(labels) if len(labels) > 1 else (labels[0] if labels else ""), (w, h))
	if m["task"] == "face_embedder":
		return OnnxFaceEmbedder(path, (w, h))
	raise ValueError(m["task"])


def _sha(path):
	h = hashlib.sha256()
	with open(path, "rb") as fh:
		for chunk in iter(lambda: fh.read(1 << 20), b""):
			h.update(chunk)
	return h.hexdigest()
