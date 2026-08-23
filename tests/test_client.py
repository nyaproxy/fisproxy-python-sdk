from __future__ import annotations

import json
import time
import unittest
from typing import Any, Mapping, Optional
from urllib.parse import urlsplit

from fisproxy import AuthError, Client, ConflictError, OperationFailed
from fisproxy._hmac import b64url, canonical_request, sha256_b64url, sign_request
from fisproxy.client import RawResponse
from fisproxy.models import decimal_str


def _admission_token(client_id: str, expires_at: int = 4_000_000_000) -> str:
	payload = {
		"version": 2,
		"kid": "k1",
		"issuer": "fisproxy",
		"edgeProvider": "cloudflare",
		"aud": "api.fisproxy.org",
		"admissionId": "adm1",
		"subject": "subj1",
		"subjectEpoch": 1,
		"credentialId": "cred1",
		"credentialKind": "user_api_token",
		"clientId": client_id,
		"serverEpoch": "epoch1",
		"issuedAt": 1700000000,
		"expiresAt": expires_at,
	}
	return "a2." + b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8")) + ".dGFn"


class FakeTransport:
	def __init__(self) -> None:
		self.calls: list[tuple[str, str, dict[str, str], Optional[bytes]]] = []
		self.admission_expires_at = 4_000_000_000
		self.status_payload = {
			"ok": True,
			"running": False,
			"session": None,
			"entrances": [],
		}
		self.start_payload = {
			"ok": True,
			"operation": {
				"id": "op-start",
				"kind": "session.start",
				"status": "queued",
				"progressPhase": "queued",
				"createdAt": "2026-01-01T00:00:00.000Z",
				"updatedAt": "2026-01-01T00:00:00.000Z",
			},
		}
		self.operation_payloads = [{
			"ok": True,
			"operation": {
				"id": "op-start",
				"kind": "session.start",
				"status": "succeeded",
				"progressPhase": "done",
				"result": {
					"kind": "start",
					"sessionId": "4242",
					"entrances": [{"id": "e1", "name": "Hong Kong", "host": "hk.example", "address": "4242.hk.example"}],
				},
				"createdAt": "2026-01-01T00:00:00.000Z",
				"updatedAt": "2026-01-01T00:00:00.000Z",
			},
		}]
		self.stop_payload = {
			"ok": True,
			"duration": 12,
			"deduction": "0.40",
			"session": {"legacySessionId": "4242"},
		}
		self.me_payload = {
			"ok": True,
			"user": {
				"id": "user-1",
				"username": "script",
				"balances": {"service_point": "12.50", "nfa_coin": "3", "subscription_pass": "0"},
			},
			"bindings": [],
			"nfa": {"stock": {"total": 0, "available": 0, "hypixelAvailable": 0}, "trialAvailable": False},
		}
		self.fail_next_status: Optional[tuple[int, dict[str, Any]]] = None
		self.request_key = b64url(bytes(range(32)))

	def __call__(self, method: str, url: str, headers: Mapping[str, str], body: Optional[bytes]) -> RawResponse:
		self.calls.append((method, url, dict(headers), body))
		path = urlsplit(url).path
		query = urlsplit(url).query
		target = path + (f"?{query}" if query else "")
		if method == "POST" and path == "/api/v1/auth/admission":
			sent = json.loads(body or b"{}")
			token = _admission_token(sent["clientId"], self.admission_expires_at)
			payload = {
				"ok": True,
				"admission": token,
				"requestKey": self.request_key,
				"subject": "subj1",
				"admissionId": "adm1",
				"expiresAt": self.admission_expires_at,
				"serverTime": int(time.time() * 1000),
				"serverEpoch": "epoch1",
			}
			return RawResponse(200, {"Content-Type": "application/json"}, json.dumps(payload).encode())
		if self.fail_next_status is not None:
			status, payload = self.fail_next_status
			self.fail_next_status = None
			return RawResponse(status, {"Content-Type": "application/json"}, json.dumps(payload).encode())
		if method == "GET" and path == "/api/v1/me":
			self._assert_signed(method, target, body or b"", headers)
			return RawResponse(200, {}, json.dumps(self.me_payload).encode())
		if method == "GET" and path == "/api/v1/sessions/status":
			self._assert_signed(method, target, body or b"", headers)
			return RawResponse(200, {}, json.dumps(self.status_payload).encode())
		if method == "POST" and path == "/api/v1/sessions/start":
			self._assert_signed(method, target, body or b"", headers)
			return RawResponse(202, {}, json.dumps(self.start_payload).encode())
		if method == "GET" and path.startswith("/api/v1/operations/"):
			self._assert_signed(method, target, body or b"", headers)
			payload = self.operation_payloads.pop(0) if len(self.operation_payloads) > 1 else self.operation_payloads[0]
			return RawResponse(200, {}, json.dumps(payload).encode())
		if method == "POST" and path == "/api/v1/sessions/stop":
			self._assert_signed(method, target, body or b"", headers)
			return RawResponse(200, {}, json.dumps(self.stop_payload).encode())
		if method == "POST" and path == "/api/v1/sessions/change-ip":
			self._assert_signed(method, target, body or b"", headers)
			return RawResponse(409, {}, json.dumps({
				"ok": False,
				"errorCode": "OPERATION_CONFLICT",
				"message": "already running",
				"existingOperation": {"id": "op-existing", "status": "running"},
			}).encode())
		if method == "GET" and path == "/api/v1/me/entrances":
			self._assert_signed(method, target, body or b"", headers)
			return RawResponse(200, {}, json.dumps({"ok": True, "entrances": [{"id": "e1", "host": "hk.example"}]}).encode())
		raise AssertionError(f"unexpected {method} {url}")

	def _assert_signed(self, method: str, target: str, body: bytes, headers: Mapping[str, str]) -> None:
		self.assertNotInRequestKey(headers)
		required = [
			"X-FP-Admission",
			"X-FP-Subject",
			"X-FP-Timestamp",
			"X-FP-Client",
			"X-FP-Sequence",
			"X-FP-Content-Length",
			"X-FP-Content-SHA256",
			"X-FP-Signature",
		]
		for name in required:
			if name not in headers:
				raise AssertionError(f"missing {name}")
		canonical = canonical_request(
			aud="api.fisproxy.org",
			subject="subj1",
			credential_id="cred1",
			admission_id="adm1",
			client_id=headers["X-FP-Client"],
			sequence=headers["X-FP-Sequence"],
			timestamp=headers["X-FP-Timestamp"],
			method=method,
			target=target,
			content_type=headers.get("Content-Type", ""),
			content_length=headers["X-FP-Content-Length"],
			idempotency_key=headers.get("Idempotency-Key", ""),
			body_sha256=sha256_b64url(body),
		)
		expected = sign_request(self.request_key, canonical)
		if headers["X-FP-Signature"] != expected:
			raise AssertionError("HMAC mismatch")
		if headers["X-FP-Content-SHA256"] != sha256_b64url(body):
			raise AssertionError("body digest mismatch")
		if headers["X-FP-Content-Length"] != str(len(body)):
			raise AssertionError("content length mismatch")

	def assertNotInRequestKey(self, headers: Mapping[str, str]) -> None:
		blob = json.dumps(headers)
		if self.request_key in blob or "requestKey" in headers:
			raise AssertionError("requestKey leaked into headers")


class ClientTests(unittest.TestCase):
	def test_me_keeps_decimal_strings(self) -> None:
		transport = FakeTransport()
		client = Client("tok_live", client_id="client-1", transport=transport)
		me = client.me()
		self.assertEqual(me.id, "user-1")
		self.assertEqual(me.balances.service_point, "12.50")
		self.assertIsInstance(me.balances.service_point, str)
		self.assertIsInstance(me.balances.nfa_coin, str)

	def test_idle_status_and_hmac_headers(self) -> None:
		transport = FakeTransport()
		client = Client("tok_live", client_id="client-1", transport=transport)
		status = client.status()
		self.assertFalse(status.running)
		self.assertEqual(status.entrances, ())
		signed = [call for call in transport.calls if call[1].endswith("/api/v1/sessions/status")][0]
		self.assertNotIn("requestKey", signed[2])
		self.assertTrue(signed[2]["Authorization"].startswith("Bearer "))
		self.assertEqual(signed[2]["X-FP-Sequence"], "0")

	def test_start_waits_and_sends_idempotency_key(self) -> None:
		transport = FakeTransport()
		client = Client("tok_live", client_id="client-1", transport=transport)
		operation = client.start(target="mc.hypixel.net", auto_nfa=True, wait=True, interval=0.01)
		self.assertTrue(operation.succeeded)
		self.assertEqual(operation.session_id, "4242")
		self.assertEqual(operation.entrances[0].address, "4242.hk.example")
		start = [call for call in transport.calls if call[1].endswith("/api/v1/sessions/start")][0]
		self.assertEqual(start[3], b'{"target":"mc.hypixel.net","autoNfa":true}')
		self.assertIn("Idempotency-Key", start[2])
		self.assertEqual(start[0], "POST")

	def test_stop_deduction_is_string(self) -> None:
		transport = FakeTransport()
		client = Client("tok_live", client_id="client-1", transport=transport)
		stopped = client.stop()
		self.assertEqual(stopped.deduction, "0.40")
		self.assertEqual(stopped.duration, 12)

	def test_admission_refresh_on_expired(self) -> None:
		transport = FakeTransport()
		transport.fail_next_status = (401, {"ok": False, "errorCode": "ADMISSION_EXPIRED", "message": "expired"})
		client = Client("tok_live", client_id="client-1", transport=transport)
		status = client.status()
		self.assertFalse(status.running)
		admissions = [call for call in transport.calls if call[1].endswith("/api/v1/auth/admission")]
		self.assertEqual(len(admissions), 2)
		self.assertNotIn("X-FP-Signature", admissions[0][2])

	def test_conflict_exposes_existing_operation(self) -> None:
		transport = FakeTransport()
		client = Client("tok_live", client_id="client-1", transport=transport)
		with self.assertRaises(ConflictError) as raised:
			client.change_ip(wait=False)
		self.assertEqual(raised.exception.error_code, "OPERATION_CONFLICT")
		self.assertEqual(raised.exception.existing_operation["id"], "op-existing")

	def test_query_is_included_in_signature_target(self) -> None:
		transport = FakeTransport()
		client = Client("tok_live", client_id="client-1", transport=transport)
		client.entrances("svc-1")
		call = [item for item in transport.calls if "/api/v1/me/entrances" in item[1]][0]
		self.assertTrue(call[1].endswith("/api/v1/me/entrances?serviceId=svc-1"))

	def test_sequence_increments(self) -> None:
		transport = FakeTransport()
		client = Client("tok_live", client_id="client-1", transport=transport)
		client.status()
		client.me()
		signed = [call for call in transport.calls if "X-FP-Sequence" in call[2]]
		self.assertEqual(signed[0][2]["X-FP-Sequence"], "0")
		self.assertEqual(signed[1][2]["X-FP-Sequence"], "1")

	def test_from_env(self) -> None:
		transport = FakeTransport()
		import os
		os.environ["FISPROXY_API_TOKEN"] = "env-token"
		os.environ["FISPROXY_API_BASE"] = "https://api.fisproxy.org"
		os.environ["FISPROXY_CLIENT_ID"] = "client-1"
		try:
			client = Client.from_env(transport=transport)
			self.assertEqual(client.client_id, "client-1")
			client.me()
		finally:
			del os.environ["FISPROXY_API_TOKEN"]

	def test_missing_token(self) -> None:
		with self.assertRaises(ValueError):
			Client("  ")

	def test_failed_operation(self) -> None:
		transport = FakeTransport()
		transport.operation_payloads = [{
			"ok": True,
			"operation": {
				"id": "op-start",
				"kind": "session.start",
				"status": "failed",
				"progressPhase": "done",
				"errorCode": "INSUFFICIENT_BALANCE",
				"message": "not enough service_point",
			},
		}]
		client = Client("tok_live", client_id="client-1", transport=transport)
		with self.assertRaises(OperationFailed) as raised:
			client.start(wait=True, interval=0.01)
		self.assertEqual(raised.exception.error_code, "INSUFFICIENT_BALANCE")

	def test_unauthorized_token(self) -> None:
		transport = FakeTransport()
		transport.fail_next_status = (401, {"ok": False, "errorCode": "UNAUTHORIZED", "message": "nope"})
		client = Client("tok_live", client_id="client-1", transport=transport)
		# First signed call after admission: fail_next_status applies, not refreshable in the
		# UNAUTHORIZED identity-termination sense after a successful admission retry skip.
		# UNAUTHORIZED is not refreshable; it should raise AuthError.
		with self.assertRaises(AuthError):
			client.me()

	def test_decimal_str_rejects_bool(self) -> None:
		with self.assertRaises(TypeError):
			decimal_str(True)
		self.assertEqual(decimal_str("1.10"), "1.10")
		self.assertEqual(decimal_str(2), "2")


if __name__ == "__main__":
	unittest.main()
