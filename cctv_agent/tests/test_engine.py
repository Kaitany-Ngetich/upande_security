"""Engine logic with fake models (no ONNX, no camera)."""

import asyncio
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cctv_agent.engine.facestore import FaceStore  # noqa: E402
from cctv_agent.engine.pipeline import CameraWorker  # noqa: E402
from cctv_agent.engine.plates import repair, vote  # noqa: E402
from cctv_agent.engine.tracker import IouTracker, iou  # noqa: E402


def test_vote_beats_single_misreads():
	reads = [("KDA123A", 0.9), ("KDA12BA", 0.6), ("KDA123A", 0.8), ("K0A123A", 0.5)]
	plate, conf = vote(reads)
	assert plate == "KDA123A" and conf > 0.5


def test_repair_lookalikes():
	assert repair("KMHC 32GU", None or __import__("cctv_agent.engine.plates", fromlist=["x"]).DEFAULT_PATTERNS) == "KMHC326U"


def test_tracker_keeps_identity_and_ends():
	t = IouTracker(max_misses=1)
	a, _ = t.update([((0, 0, 10, 10), "car", 0.9)], 0)
	b, _ = t.update([((1, 1, 11, 11), "car", 0.9)], 1)
	assert a[0].id == b[0].id and len(b[0].boxes) == 2
	t.update([], 2)
	_, ended = t.update([], 3)
	assert ended and ended[0].id == a[0].id
	assert iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0


def test_facestore_match_and_delete(tmp_path):
	fs = FaceStore(str(tmp_path / "f.db"))
	rng = np.random.default_rng(1)
	alice, bob = rng.normal(size=512), rng.normal(size=512)
	fs.enroll("PRF-alice", [alice, alice + rng.normal(scale=0.05, size=512)])
	fs.enroll("PRF-bob", [bob])
	who, sim = fs.match(alice + rng.normal(scale=0.05, size=512), 0.6)
	assert who == "PRF-alice" and sim > 0.9
	assert fs.match(rng.normal(size=512), 0.6)[0] is None
	fs.delete("PRF-alice")
	assert fs.match(alice, 0.6)[0] is None and fs.count() == 1


class FakeDet:
	"""A car that drives toward the camera (box grows) - plus its plate."""
	def __init__(self, boxes):
		self.boxes, self.i = boxes, 0

	def detect(self, img):
		b = self.boxes[min(self.i, len(self.boxes) - 1)]
		self.i += 1
		return [(b, "car", 0.9)] if b else []


class FakePlateDet:
	def detect(self, crop):
		h, w = crop.shape[:2]
		return [((w * 0.3, h * 0.7, w * 0.7, h * 0.9), "plate", 0.95)]


class FakeOCR:
	seq = ["KDA123A", "KDA12BA", "KDA123A", "KDA123A"]

	def __init__(self):
		self.i = 0

	def read(self, crop):
		t = self.seq[self.i % len(self.seq)]
		self.i += 1
		return t, 0.9


@pytest.mark.asyncio
async def test_pipeline_reads_plate_once_with_direction():
	events = []

	async def on_event(ev, jpeg):
		events.append(ev)

	boxes = [(500, 300, 600, 380), (480, 290, 620, 400), (450, 280, 650, 430), (420, 260, 700, 470), None, None, None, None, None, None, None, None, None, None]
	cam = {"name": "Gate In-NVR-1", "direction_in": "Towards Camera", "analytics_config": {"motion_threshold": -1}}
	w = CameraWorker("KAP", cam, {"vehicle_detector": FakeDet(boxes), "plate_detector": FakePlateDet(), "plate_ocr": FakeOCR()}, on_event)
	rng = np.random.default_rng(0)
	for i in range(len(boxes)):
		await w.process(rng.integers(0, 255, (720, 1280, 3), dtype=np.uint8), t=i)
	plates = [e for e in events if e["event_type"] == "plate_read"]
	assert len(plates) == 1, events
	assert plates[0]["data"]["plate"] == "KDA123A" and plates[0]["data"]["direction"] == "in"
	assert plates[0]["source"]["provider"] == "own_engine"


@pytest.mark.asyncio
async def test_pipeline_person_and_face_match(tmp_path):
	events = []

	async def on_event(ev, jpeg):
		events.append(ev)

	class PersonDet:
		def detect(self, img):
			return [((100, 100, 300, 600), "person", 0.9)]

	class FaceDet:
		def detect(self, crop):
			return [((40, 20, 160, 160), "face", 0.95)]

	vec = np.ones(512, np.float32)

	class Emb:
		def embed(self, crop):
			return vec

	fs = FaceStore(str(tmp_path / "f.db"))
	fs.enroll("PRF-0001", [vec])
	cam = {"name": "Door", "analytics_config": {"motion_threshold": -1}}
	w = CameraWorker("KAP", cam, {"person_detector": PersonDet(), "face_detector": FaceDet(), "face_embedder": Emb()}, on_event, faces=fs)
	img = np.random.default_rng(0).integers(0, 255, (720, 1280, 3), dtype=np.uint8)
	for i in range(4):
		await w.process(img, t=i)
	kinds = [e["event_type"] for e in events]
	assert kinds.count("person_detected") == 1 and "face_match" in kinds
	assert next(e for e in events if e["event_type"] == "face_match")["data"]["person_ref"] == "PRF-0001"
