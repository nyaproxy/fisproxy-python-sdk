from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Sequence

from ._version import __version__
from ._hmac import (
	canonical_request,
	dumps_json,
	format_sequence,
	parse_admission_payload,
	sha256_b64url,
	sign_request,
	valid_client_id,
)
from .errors import (
	AdmissionError,
	AuthError,
	ConflictError,
	FisProxyError,
	OperationFailed,
	OperationTimeout,
	TransportError,
	error_code_of,
	error_message_of,
)
from .models import Operation, SessionStatus, StopResult, UserProfile

DEFAULT_BASE_URL = "https://api.fisproxy.org"
DEFAULT_TIMEOUT = 30.0
ADMISSION_REFRESH_SKEW_SECONDS = 5
REFRESHABLE_ADMISSION_CODES = frozenset({
	"ADMISSION_EXPIRED",
	"ADMISSION_PROCESS_EXPIRED",
	"ADMISSION_INVALID",
	"EDGE_ADMISSION_EXPIRED",
	"REQUEST_TIMESTAMP_INVALID",
})
IDENTITY_TERMINATION_CODES = frozenset({
	"USER_BANNED",
	"ACCOUNT_PERMANENTLY_BANNED",
	"SESSION_EXPIRED",
	"SESSION_REVOKED",
	"TOKEN_REVOKED",
})
UNSIGNED_PATHS = frozenset({
	"/api/v1/auth/admission",
})
Transport = Callable[[str, str, Mapping[str, str], Optional[bytes]], "RawResponse"]


@dataclass
class RawResponse:
	status: int
	headers: Mapping[str, str]
	body: bytes


@dataclass
class _Admission:
	admission: str
	request_key: str
	subject: str
	admission_id: str
	expires_at: int
	server_time: int
	server_epoch: str
	payload: Mapping[str, Any]
	clock_offset_ms: int
	sequence: int


def _urllib_transport(method: str, url: str, headers: Mapping[str, str], body: Optional[bytes], timeout: float) -> RawResponse:
	request = urllib.request.Request(url, data=body if body else None, method=method, headers=dict(headers))
	try:
		with urllib.request.urlopen(request, timeout=timeout) as response:
			return RawResponse(status=int(response.status), headers=dict(response.headers), body=response.read())
	except urllib.error.HTTPError as error:
		return RawResponse(status=int(error.code), headers=dict(error.headers or {}), body=error.read())
	except urllib.error.URLError as error:
		raise TransportError(0, {"errorCode": "TRANSPORT_ERROR", "message": str(error.reason or error)}) from error


class Client:
	"""User-token client for start / status / change-ip / stop.

	Create the token on the signed-in API page. Pass it as Bearer; this client
	does not implement a browser login flow.
	"""

	def __init__(
		self,
		token: str,
		*,
		base_url: str = DEFAULT_BASE_URL,
		client_id: Optional[str] = None,
		timeout: float = DEFAULT_TIMEOUT,
		user_agent: Optional[str] = None,
		transport: Optional[Transport] = None,
	) -> None:
		cleaned = token.strip()
		if not cleaned:
			raise ValueError("token is required")
		generated = client_id or uuid.uuid4().hex
		if not valid_client_id(generated):
			raise ValueError("client_id must match [A-Za-z0-9._~:-]{1,96}")
		self._token = cleaned
		self._base_url = base_url.rstrip("/")
		self._client_id = generated
		self._timeout = timeout
		self._user_agent = user_agent or f"fisproxy-python/{__version__}"
		self._transport = transport
		self._lock = threading.RLock()
		self._admission: Optional[_Admission] = None

	@classmethod
	def from_env(cls, **kwargs: Any) -> "Client":
		token = os.environ.get("FISPROXY_API_TOKEN", "").strip()
		if not token:
			raise ValueError("FISPROXY_API_TOKEN is required")
		base = os.environ.get("FISPROXY_API_BASE", DEFAULT_BASE_URL)
		client_id = os.environ.get("FISPROXY_CLIENT_ID") or None
		return cls(token, base_url=base, client_id=client_id, **kwargs)

	@property
	def base_url(self) -> str:
		return self._base_url

	@property
	def client_id(self) -> str:
		return self._client_id

	def close(self) -> None:
		with self._lock:
			self._admission = None

	def __enter__(self) -> "Client":
		return self

	def __exit__(self, *exc: object) -> None:
		self.close()

	def me(self) -> UserProfile:
		return UserProfile.from_response(self.request("GET", "/api/v1/me"))

	def services(self) -> Sequence[Mapping[str, Any]]:
		payload = self.request("GET", "/api/v1/me/services")
		items = payload.get("services")
		return tuple(items) if isinstance(items, list) else ()

	def status(self) -> SessionStatus:
		return SessionStatus.from_response(self.request("GET", "/api/v1/sessions/status"))

	def entrances(self, service_id: Optional[str] = None) -> Sequence[Mapping[str, Any]]:
		query = {"serviceId": service_id} if service_id else None
		payload = self.request("GET", "/api/v1/me/entrances", query=query)
		items = payload.get("entrances")
		return tuple(items) if isinstance(items, list) else ()

	def start(
		self,
		*,
		service_id: Optional[str] = None,
		target: Optional[str] = None,
		auto_nfa: Optional[bool] = None,
		nfa_item_id: Optional[str] = None,
		reuse_nfa_item_id: Optional[str] = None,
		nfa_source: Optional[str] = None,
		nfa_sku: Optional[str] = None,
		try_previous_nfa: Optional[bool] = None,
		idempotency_key: Optional[str] = None,
		wait: bool = True,
		timeout: float = 180.0,
		interval: float = 1.0,
	) -> Operation:
		body: dict[str, Any] = {}
		if service_id is not None:
			body["serviceId"] = service_id
		if target is not None:
			body["target"] = target
		if auto_nfa is not None:
			body["autoNfa"] = auto_nfa
		if nfa_item_id is not None:
			body["nfaItemId"] = nfa_item_id
		if reuse_nfa_item_id is not None:
			body["reuseNfaItemId"] = reuse_nfa_item_id
		if nfa_source is not None:
			body["nfaSource"] = nfa_source
		if nfa_sku is not None:
			body["nfaSku"] = nfa_sku
		if try_previous_nfa is not None:
			body["tryPreviousNfa"] = try_previous_nfa
		payload = self.request(
			"POST",
			"/api/v1/sessions/start",
			json_body=body,
			idempotency_key=idempotency_key or _new_idempotency_key(),
		)
		operation = _operation_from_payload(payload)
		if wait:
			return self.wait_operation(operation.id, timeout=timeout, interval=interval)
		return operation

	def change_ip(
		self,
		*,
		idempotency_key: Optional[str] = None,
		wait: bool = True,
		wait_route_ack: bool = True,
		timeout: float = 180.0,
		interval: float = 1.0,
	) -> Operation:
		payload = self.request(
			"POST",
			"/api/v1/sessions/change-ip",
			json_body={},
			idempotency_key=idempotency_key or _new_idempotency_key(),
		)
		operation = _operation_from_payload(payload)
		if not wait:
			return operation
		finished = self.wait_operation(operation.id, timeout=timeout, interval=interval)
		if wait_route_ack and finished.succeeded and not finished.route_acked:
			return self.wait_operation(
				operation.id,
				timeout=timeout,
				interval=interval,
				until=lambda item: item.terminal and (item.route_acked or not item.succeeded),
			)
		return finished

	def stop(self) -> StopResult:
		return StopResult.from_response(self.request("POST", "/api/v1/sessions/stop", json_body={}))

	def get_operation(self, operation_id: str) -> Operation:
		payload = self.request("GET", f"/api/v1/operations/{urllib.parse.quote(operation_id, safe='')}")
		return _operation_from_payload(payload)

	def list_operations(
		self,
		*,
		status: Optional[str] = None,
		kind: Optional[str] = None,
		limit: Optional[int] = None,
	) -> Sequence[Operation]:
		payload = self.request("GET", "/api/v1/operations", query={
			"status": status,
			"kind": kind,
			"limit": None if limit is None else str(limit),
		})
		items = payload.get("operations")
		if not isinstance(items, list):
			return ()
		return tuple(Operation.from_mapping(item) for item in items)

	def cancel_operation(self, operation_id: str) -> Operation:
		payload = self.request(
			"POST",
			f"/api/v1/operations/{urllib.parse.quote(operation_id, safe='')}/cancel",
			json_body={},
		)
		return _operation_from_payload(payload)

	def wait_operation(
		self,
		operation_id: str,
		*,
		timeout: float = 180.0,
		interval: float = 1.0,
		until: Optional[Callable[[Operation], bool]] = None,
	) -> Operation:
		deadline = time.monotonic() + timeout
		last: Optional[Operation] = None
		predicate = until or (lambda item: item.terminal)
		while time.monotonic() < deadline:
			last = self.get_operation(operation_id)
			if predicate(last):
				if last.status == "failed":
					raise OperationFailed(last)
				if last.status == "canceled":
					raise OperationFailed(last)
				return last
			time.sleep(max(interval, 0.05))
		raise OperationTimeout(operation_id, last)

	def request(
		self,
		method: str,
		path: str,
		*,
		json_body: Optional[Mapping[str, Any]] = None,
		query: Optional[Mapping[str, Any]] = None,
		idempotency_key: Optional[str] = None,
		sign: Optional[bool] = None,
	) -> dict[str, Any]:
		if not path.startswith("/") or path.startswith("//") or "\\" in path:
			raise ValueError("path must be an absolute URL path")
		target = _with_query(path, query)
		method_upper = method.upper()
		if json_body is None:
			body = b""
			content_type = ""
		else:
			body = dumps_json(dict(json_body))
			content_type = "application/json"
		pathname = path.split("?", 1)[0]
		should_sign = (pathname not in UNSIGNED_PATHS) if sign is None else sign
		return self._send(
			method_upper,
			target,
			body,
			content_type,
			idempotency_key or "",
			should_sign,
			allow_refresh=True,
		)

	def _send(
		self,
		method: str,
		target: str,
		body: bytes,
		content_type: str,
		idempotency_key: str,
		sign: bool,
		*,
		allow_refresh: bool,
	) -> dict[str, Any]:
		headers = {
			"Accept": "application/json",
			"Authorization": f"Bearer {self._token}",
			"User-Agent": self._user_agent,
		}
		if content_type:
			headers["Content-Type"] = content_type
		if idempotency_key:
			headers["Idempotency-Key"] = idempotency_key
		if sign:
			with self._lock:
				admission = self._ensure_admission()
				headers.update(_signature_headers(
					admission,
					method=method,
					target=target,
					body=body,
					content_type=content_type,
					idempotency_key=idempotency_key,
				))
		response = self._do_transport(method, f"{self._base_url}{target}", headers, body or None)
		payload = _decode_payload(response)
		if (
			sign
			and allow_refresh
			and _is_refreshable_admission_failure(response.status, payload)
		):
			with self._lock:
				self._admission = None
			return self._send(
				method,
				target,
				body,
				content_type,
				idempotency_key,
				sign,
				allow_refresh=False,
			)
		if response.status >= 400 or _is_error_payload(payload):
			raise _error_from_response(response.status, payload)
		if not isinstance(payload, dict):
			raise FisProxyError(response.status, {"errorCode": "INVALID_RESPONSE", "message": "expected a JSON object"})
		return payload

	def _ensure_admission(self) -> _Admission:
		now = time.time()
		current = self._admission
		if current and current.expires_at > now + ADMISSION_REFRESH_SKEW_SECONDS:
			return current
		return self._exchange_admission()

	def _exchange_admission(self) -> _Admission:
		payload = self._send(
			"POST",
			"/api/v1/auth/admission",
			dumps_json({"clientId": self._client_id}),
			"application/json",
			"",
			False,
			allow_refresh=False,
		)
		admission_token = payload.get("admission")
		request_key = payload.get("requestKey")
		subject = payload.get("subject")
		admission_id = payload.get("admissionId")
		expires_at = payload.get("expiresAt")
		server_time = payload.get("serverTime")
		server_epoch = payload.get("serverEpoch")
		expires_at_n = _as_int(expires_at)
		server_time_n = _as_int(server_time)
		if not (
			payload.get("ok") is True
			and isinstance(admission_token, str)
			and isinstance(request_key, str)
			and isinstance(subject, str)
			and isinstance(admission_id, str)
			and expires_at_n is not None
			and server_time_n is not None
			and isinstance(server_epoch, str)
		):
			raise AdmissionError(500, {"errorCode": "INVALID_ADMISSION", "message": "invalid admission exchange response"})
		parsed = parse_admission_payload(admission_token)
		if (
			parsed.get("subject") != subject
			or parsed.get("admissionId") != admission_id
			or parsed.get("clientId") != self._client_id
			or _as_int(parsed.get("expiresAt")) != expires_at_n
		):
			raise AdmissionError(500, {"errorCode": "INVALID_ADMISSION", "message": "admission payload mismatch"})
		credential = _Admission(
			admission=admission_token,
			request_key=request_key,
			subject=subject,
			admission_id=admission_id,
			expires_at=expires_at_n,
			server_time=server_time_n,
			server_epoch=server_epoch,
			payload=dict(parsed),
			clock_offset_ms=server_time_n - int(time.time() * 1000),
			sequence=0,
		)
		self._admission = credential
		return credential

	def _do_transport(self, method: str, url: str, headers: Mapping[str, str], body: Optional[bytes]) -> RawResponse:
		if self._transport is not None:
			return self._transport(method, url, headers, body)
		return _urllib_transport(method, url, headers, body, self._timeout)


FisProxy = Client


def _new_idempotency_key() -> str:
	return str(uuid.uuid4())


def _with_query(path: str, query: Optional[Mapping[str, Any]]) -> str:
	if not query:
		return path
	pairs = []
	for key, value in query.items():
		if value is None:
			continue
		pairs.append((key, value))
	if not pairs:
		return path
	encoded = urllib.parse.urlencode(pairs, doseq=True, quote_via=urllib.parse.quote)
	return f"{path}?{encoded}"


def _signature_headers(
	admission: _Admission,
	*,
	method: str,
	target: str,
	body: bytes,
	content_type: str,
	idempotency_key: str,
) -> dict[str, str]:
	sequence = format_sequence(admission.sequence)
	admission.sequence += 1
	timestamp = str(round(time.time() * 1000 + admission.clock_offset_ms))
	if len(timestamp) != 13:
		raise AdmissionError(400, {
			"errorCode": "REQUEST_TIMESTAMP_INVALID",
			"message": "signed timestamp must be 13-digit unix milliseconds",
		})
	content_length = str(len(body))
	body_sha256 = sha256_b64url(body)
	canonical = canonical_request(
		aud=str(admission.payload["aud"]),
		subject=str(admission.payload["subject"]),
		credential_id=str(admission.payload["credentialId"]),
		admission_id=str(admission.payload["admissionId"]),
		client_id=str(admission.payload["clientId"]),
		sequence=sequence,
		timestamp=timestamp,
		method=method,
		target=target,
		content_type=content_type,
		content_length=content_length,
		idempotency_key=idempotency_key,
		body_sha256=body_sha256,
	)
	signature = sign_request(admission.request_key, canonical)
	return {
		"X-FP-Admission": admission.admission,
		"X-FP-Subject": admission.subject,
		"X-FP-Timestamp": timestamp,
		"X-FP-Client": str(admission.payload["clientId"]),
		"X-FP-Sequence": sequence,
		"X-FP-Content-Length": content_length,
		"X-FP-Content-SHA256": body_sha256,
		"X-FP-Signature": signature,
	}


def _decode_payload(response: RawResponse) -> Any:
	if not response.body:
		return {}
	text = response.body.decode("utf-8", "replace")
	try:
		return json.loads(text)
	except json.JSONDecodeError:
		return {
			"errorCode": "INVALID_RESPONSE",
			"message": text[:300] if text else f"HTTP {response.status}",
		}


def _as_int(value: object) -> Optional[int]:
	if isinstance(value, bool):
		return None
	if isinstance(value, int):
		return value
	if isinstance(value, float) and value.is_integer():
		return int(value)
	return None


def _is_error_payload(payload: object) -> bool:
	if not isinstance(payload, dict):
		return False
	if payload.get("ok") is True:
		return False
	return payload.get("ok") is False or payload.get("success") is False


def _is_refreshable_admission_failure(status: int, payload: object) -> bool:
	if status not in {401, 403}:
		return False
	return error_code_of(payload) in REFRESHABLE_ADMISSION_CODES


def _operation_from_payload(payload: Mapping[str, Any]) -> Operation:
	operation = payload.get("operation")
	return Operation.from_mapping(operation if operation is not None else payload)


def _error_from_response(status: int, payload: object) -> FisProxyError:
	data = payload if isinstance(payload, dict) else {"message": str(payload)}
	code = error_code_of(data)
	if code in IDENTITY_TERMINATION_CODES or (status == 401 and code in {"", "UNAUTHORIZED"}):
		return AuthError(status, data)
	if code in REFRESHABLE_ADMISSION_CODES or code.startswith("ADMISSION_") or code.startswith("REQUEST_"):
		return AdmissionError(status, data)
	if status == 409 or code == "OPERATION_CONFLICT":
		return ConflictError(status, data)
	return FisProxyError(status, data, error_message_of(data, f"HTTP {status}"))
