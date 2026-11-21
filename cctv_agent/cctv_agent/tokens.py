"""Verify the viewing tokens ERPNext issues (upande_security/cctv/tokens.py).

HS256 JWT signed with CCTV Settings > Gateway Token Secret, which the agent
receives in its site config. Claims: sub (user), cam, path, scope (live |
playback), exp, jti, and for playback rng + once.
"""

import base64
import hashlib
import hmac
import json
import time


class TokenError(Exception):
	pass


def _b64(data):
	return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def sign(claims, secret):
	"""Only used by tests - ERPNext is the issuer."""
	header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
	body = _b64(json.dumps(claims, separators=(",", ":")).encode())
	return f"{header}.{body}.{_b64(hmac.new(secret.encode(), f'{header}.{body}'.encode(), hashlib.sha256).digest())}"


def verify(token, secret, now=None):
	if not token or not secret:
		raise TokenError("missing token or secret")
	try:
		header, body, sig = token.split(".")
	except ValueError as e:
		raise TokenError("malformed") from e
	if json.loads(base64.urlsafe_b64decode(header + "=" * (-len(header) % 4))).get("alg") != "HS256":
		raise TokenError("wrong algorithm")
	expected = _b64(hmac.new(secret.encode(), f"{header}.{body}".encode(), hashlib.sha256).digest())
	if not hmac.compare_digest(expected, sig):
		raise TokenError("bad signature")
	claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
	if claims.get("exp", 0) < (now or time.time()):
		raise TokenError("expired")
	return claims
