from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from typing import Mapping

CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9._~:-]{1,96}$")
MAX_UINT64 = (1 << 64) - 1
CANONICAL_PREFIX = "FISPROXY-REQUEST-V2"


def b64url(data: bytes) -> str:
	return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def b64url_decode(value: str) -> bytes:
	padding = "=" * (-len(value) % 4)
	return base64.urlsafe_b64decode(value.replace("-", "+").replace("_", "/") + padding)


def sha256_b64url(body: bytes) -> str:
	return b64url(hashlib.sha256(body).digest())


EMPTY_BODY_SHA256 = sha256_b64url(b"")


def dumps_json(value: object) -> bytes:
	return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def normalize_content_type(value: str) -> str:
	text = value.strip().lower()
	text = re.sub(r"\s*;\s*", ";", text)
	return re.sub(r"\s*=\s*", "=", text)


def valid_client_id(value: str) -> bool:
	return bool(CLIENT_ID_RE.fullmatch(value))


def canonical_request(
	*,
	aud: str,
	subject: str,
	credential_id: str,
	admission_id: str,
	client_id: str,
	sequence: str,
	timestamp: str,
	method: str,
	target: str,
	content_type: str,
	content_length: str,
	idempotency_key: str,
	body_sha256: str,
) -> str:
	return "\n".join((
		CANONICAL_PREFIX,
		aud,
		subject,
		credential_id,
		admission_id,
		client_id,
		sequence,
		timestamp,
		method,
		target,
		normalize_content_type(content_type),
		content_length,
		idempotency_key,
		body_sha256,
	))


def sign_request(
	request_key: str,
	canonical: str,
) -> str:
	return b64url(hmac.new(b64url_decode(request_key), canonical.encode("utf-8"), hashlib.sha256).digest())


def parse_admission_payload(token: str) -> Mapping[str, object]:
	parts = token.split(".")
	if len(parts) != 3 or parts[0] != "a2" or not parts[1] or not parts[2]:
		raise ValueError("invalid admission token")
	payload = json.loads(b64url_decode(parts[1]))
	if not isinstance(payload, dict):
		raise ValueError("invalid admission payload")
	required = ("version", "aud", "admissionId", "subject", "credentialId", "clientId", "serverEpoch", "expiresAt")
	if payload.get("version") != 2:
		raise ValueError("unsupported admission version")
	for key in required:
		if key not in payload:
			raise ValueError("invalid admission payload")
	return payload


def format_sequence(value: int) -> str:
	if value < 0 or value > MAX_UINT64:
		raise OverflowError("admission sequence exhausted")
	return str(value)
