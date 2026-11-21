"""Tiny numpy image helpers - enough for crops and model input, no OpenCV needed."""

import numpy as np


def resize(img, w, h):
	"""Bilinear resize of an HxWxC uint8 image."""
	H, W = img.shape[:2]
	if (W, H) == (w, h):
		return img
	ys = (np.arange(h) + 0.5) * H / h - 0.5
	xs = (np.arange(w) + 0.5) * W / w - 0.5
	y0 = np.clip(np.floor(ys).astype(int), 0, H - 1)
	x0 = np.clip(np.floor(xs).astype(int), 0, W - 1)
	y1 = np.clip(y0 + 1, 0, H - 1)
	x1 = np.clip(x0 + 1, 0, W - 1)
	wy = np.clip(ys - y0, 0, 1)[:, None, None]
	wx = np.clip(xs - x0, 0, 1)[None, :, None]
	a, b = img[y0][:, x0].astype(np.float32), img[y0][:, x1].astype(np.float32)
	c, d = img[y1][:, x0].astype(np.float32), img[y1][:, x1].astype(np.float32)
	top = a * (1 - wx) + b * wx
	bottom = c * (1 - wx) + d * wx
	return (top * (1 - wy) + bottom * wy).astype(np.uint8)


def crop(img, box, pad=0.0):
	x1, y1, x2, y2 = box
	H, W = img.shape[:2]
	pw, ph = (x2 - x1) * pad, (y2 - y1) * pad
	x1, y1 = max(0, int(x1 - pw)), max(0, int(y1 - ph))
	x2, y2 = min(W, int(x2 + pw)), min(H, int(y2 + ph))
	return img[y1:y2, x1:x2]


def to_input(img, w, h, scale=1 / 255.0, mean=0.0, std=1.0, chw=True):
	x = resize(img, w, h).astype(np.float32) * scale
	x = (x - mean) / std
	if chw:
		x = x.transpose(2, 0, 1)
	return x[None]


def sharpness(img):
	"""Variance of a simple Laplacian on the grey image: higher = sharper."""
	g = img.mean(axis=2) if img.ndim == 3 else img
	if g.shape[0] < 3 or g.shape[1] < 3:
		return 0.0
	lap = -4 * g[1:-1, 1:-1] + g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:]
	return float(lap.var())


def to_jpeg(img, quality=85):
	"""JPEG bytes for snapshots (Pillow, if installed)."""
	try:
		import io

		from PIL import Image
	except ImportError:
		return None
	buf = io.BytesIO()
	Image.fromarray(img).save(buf, format="JPEG", quality=quality)
	return buf.getvalue()


def from_bytes(data):
	from PIL import Image
	import io

	return np.asarray(Image.open(io.BytesIO(data)).convert("RGB"))
