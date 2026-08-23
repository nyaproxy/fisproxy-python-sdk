from __future__ import annotations

import hashlib
import hmac
import json
import unittest

from fisproxy._hmac import (
	EMPTY_BODY_SHA256,
	b64url,
	canonical_request,
	dumps_json,
	normalize_content_type,
	parse_admission_payload,
	sha256_b64url,
	sign_request,
	valid_client_id,
)


class HmacTests(unittest.TestCase):
	def test_empty_body_digest(self) -> None:
		self.assertEqual(EMPTY_BODY_SHA256, sha256_b64url(b""))
		self.assertEqual(EMPTY_BODY_SHA256, "47DEQpj8HBSa-_TImW-5JCeuQeRkm5NMpJWZG3hSuFU")

	def test_canonical_and_signature_vector(self) -> None:
		key = bytes(range(32))
		body_sha = sha256_b64url(b"")
		canonical = canonical_request(
			aud="api.fisproxy.org",
			subject="subject",
			credential_id="cred",
			admission_id="adm",
			client_id="client-1",
			sequence="0",
			timestamp="1730000000000",
			method="GET",
			target="/api/v1/sessions/status",
			content_type="",
			content_length="0",
			idempotency_key="",
			body_sha256=body_sha,
		)
		expected = hmac.new(key, canonical.encode("utf-8"), hashlib.sha256).digest()
		self.assertEqual(sign_request(b64url(key), canonical), b64url(expected))
		self.assertEqual(sign_request(b64url(key), canonical), "IQDzGpbe6m6LW0wpp8ugYmcgEuYyziJxvGP6B1RJY-s")

	def test_json_is_compact_utf8(self) -> None:
		self.assertEqual(dumps_json({"autoNfa": True, "target": "mc.hypixel.net"}), b'{"autoNfa":true,"target":"mc.hypixel.net"}')

	def test_content_type_normalization(self) -> None:
		self.assertEqual(normalize_content_type("Application/JSON ; Charset = UTF-8"), "application/json;charset=utf-8")

	def test_client_id_charset(self) -> None:
		self.assertTrue(valid_client_id("script-client_1.abc:def~"))
		self.assertFalse(valid_client_id(""))
		self.assertFalse(valid_client_id("bad id"))
		self.assertFalse(valid_client_id("x" * 97))

	def test_parse_admission_payload(self) -> None:
		payload = {
			"version": 2,
			"aud": "api.fisproxy.org",
			"admissionId": "adm",
			"subject": "sub",
			"credentialId": "cred",
			"clientId": "client-1",
			"serverEpoch": "epoch",
			"expiresAt": 1730000300,
		}
		token = "a2." + b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8")) + ".dGFn"
		parsed = parse_admission_payload(token)
		self.assertEqual(parsed["aud"], "api.fisproxy.org")
		with self.assertRaises(ValueError):
			parse_admission_payload("not-a-token")


if __name__ == "__main__":
	unittest.main()
