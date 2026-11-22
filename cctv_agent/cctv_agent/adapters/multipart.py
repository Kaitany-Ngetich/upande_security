"""Incremental multipart/mixed parser for the long-lived event streams both
Hikvision (ISAPI alertStream) and Dahua (eventManager attach) push."""

import re


def boundary_of(content_type):
	m = re.search(r'boundary="?([^";]+)"?', content_type or "", re.I)
	return m.group(1).strip() if m else None


class MultipartStream:
	def __init__(self, boundary):
		b = boundary[2:] if boundary.startswith("--") else boundary
		self.delim = b"--" + b.encode()
		self.buf = b""

	def feed(self, chunk):
		"""Add bytes; return the complete parts now available as [(headers, body)]."""
		self.buf += chunk
		parts = []
		while True:
			start = self.buf.find(self.delim)
			if start < 0:
				# keep a tail in case the delimiter is split across chunks
				self.buf = self.buf[-len(self.delim):]
				return parts
			head_start = start + len(self.delim)
			head_end = self.buf.find(b"\r\n\r\n", head_start)
			if head_end < 0:
				self.buf = self.buf[start:]
				return parts
			headers = {}
			for line in self.buf[head_start:head_end].decode("latin-1").splitlines():
				if ":" in line:
					k, v = line.split(":", 1)
					headers[k.strip().lower()] = v.strip()
			body_start = head_end + 4
			length = headers.get("content-length")
			if length and length.isdigit():
				body_end = body_start + int(length)
				if len(self.buf) < body_end:
					self.buf = self.buf[start:]
					return parts
				body = self.buf[body_start:body_end]
				self.buf = self.buf[body_end:]
			else:
				nxt = self.buf.find(self.delim, body_start)
				if nxt < 0:
					self.buf = self.buf[start:]
					return parts
				body = self.buf[body_start:nxt].rstrip(b"\r\n")
				self.buf = self.buf[nxt:]
			parts.append((headers, body))
