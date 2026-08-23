from __future__ import annotations

from typing import Any, Mapping, Optional


def error_code_of(payload: object) -> str:
	if not isinstance(payload, dict):
		return ""
	code = payload.get("errorCode")
	if isinstance(code, str) and code:
		return code
	code = payload.get("code")
	if isinstance(code, str) and code:
		return code
	nested = payload.get("error")
	if isinstance(nested, dict):
		inner = nested.get("code")
		if isinstance(inner, str) and inner:
			return inner
	return ""


def error_message_of(payload: object, fallback: str) -> str:
	if not isinstance(payload, dict):
		return fallback
	for key in ("message", "msg", "error"):
		value = payload.get(key)
		if isinstance(value, str) and value:
			return value
	return fallback


class FisProxyError(Exception):
	def __init__(self, status: int, payload: Optional[Mapping[str, Any]] = None, message: Optional[str] = None):
		self.status = status
		self.payload = dict(payload) if payload else {}
		self.error_code = error_code_of(self.payload)
		self.message = message or error_message_of(self.payload, f"HTTP {status}")
		super().__init__(f"{self.error_code}: {self.message}" if self.error_code else self.message)


class TransportError(FisProxyError):
	"""Network or HTTP transport failure before a JSON API error was returned."""


class AdmissionError(FisProxyError):
	"""The API rejected this request. Transient cases are retried automatically."""


class AuthError(FisProxyError):
	"""User token is missing, revoked, banned, or otherwise rejected."""


class ConflictError(FisProxyError):
	def __init__(self, status: int, payload: Optional[Mapping[str, Any]] = None):
		super().__init__(status, payload)
		existing = self.payload.get("existingOperation")
		self.existing_operation = existing if isinstance(existing, dict) else None


class OperationFailed(FisProxyError):
	def __init__(self, operation: Any):
		payload = {
			"errorCode": getattr(operation, "error_code", None) or "OPERATION_FAILED",
			"message": getattr(operation, "message", None) or f"operation {getattr(operation, 'id', '?')} {getattr(operation, 'status', 'failed')}",
			"operation": getattr(operation, "raw", None),
		}
		super().__init__(400, payload)
		self.operation = operation


class OperationTimeout(FisProxyError):
	def __init__(self, operation_id: str, last: Any = None):
		super().__init__(408, {
			"errorCode": "OPERATION_TIMEOUT",
			"message": f"operation {operation_id} did not finish in time",
		})
		self.operation_id = operation_id
		self.last = last
