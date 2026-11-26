"""IoU tracker: keeps one id per object across frames (ByteTrack-style matching,
simplified). Enough at a gate where objects move slowly through one view."""

import itertools


def iou(a, b):
	x1, y1 = max(a[0], b[0]), max(a[1], b[1])
	x2, y2 = min(a[2], b[2]), min(a[3], b[3])
	inter = max(0, x2 - x1) * max(0, y2 - y1)
	if not inter:
		return 0.0
	return inter / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter)


class Track:
	def __init__(self, tid, box, cls, score, t):
		self.id, self.cls = tid, cls
		self.boxes = [box]
		self.scores = [score]
		self.first, self.last = t, t
		self.misses = 0
		self.best = None  # (quality, frame_crop, box) chosen by the pipeline
		self.reads = []  # per-frame recognitions (plate text, confidence)
		self.emitted = False
		self.plate_crop = None  # sharpest plate image so far (for the event snapshot)
		self.plate_conf = 0.0

	@property
	def box(self):
		return self.boxes[-1]

	def area_trend(self):
		""">1 growing (coming toward the camera), <1 shrinking (going away)."""
		a0 = (self.boxes[0][2] - self.boxes[0][0]) * (self.boxes[0][3] - self.boxes[0][1])
		a1 = (self.box[2] - self.box[0]) * (self.box[3] - self.box[1])
		return a1 / a0 if a0 else 1.0


class IouTracker:
	def __init__(self, iou_threshold=0.3, max_misses=8):
		self.iou_threshold = iou_threshold
		self.max_misses = max_misses
		self.tracks = []
		self._ids = itertools.count(1)

	def update(self, detections, t):
		"""detections: [(box, cls, score)]. Returns (active tracks, tracks that just ended)."""
		unmatched = list(range(len(detections)))
		for tr in self.tracks:
			best, best_iou = None, self.iou_threshold
			for i in unmatched:
				box, cls, _ = detections[i]
				if cls != tr.cls:
					continue
				v = iou(tr.box, box)
				if v >= best_iou:
					best, best_iou = i, v
			if best is None:
				tr.misses += 1
			else:
				box, _, score = detections[best]
				tr.boxes.append(box)
				tr.scores.append(score)
				tr.last, tr.misses = t, 0
				unmatched.remove(best)
		for i in unmatched:
			box, cls, score = detections[i]
			self.tracks.append(Track(next(self._ids), box, cls, score, t))
		ended = [tr for tr in self.tracks if tr.misses > self.max_misses]
		self.tracks = [tr for tr in self.tracks if tr.misses <= self.max_misses]
		return self.tracks, ended
