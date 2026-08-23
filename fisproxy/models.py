from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Optional, Sequence


def decimal_str(value: object) -> str:
	"""Keep service_point / nfa_coin as a decimal string. Never round via float math."""
	if value is None:
		raise TypeError("amount is required")
	if isinstance(value, bool):
		raise TypeError("amount cannot be bool")
	if isinstance(value, int):
		return str(value)
	if isinstance(value, Decimal):
		return format(value, "f")
	if isinstance(value, str):
		text = value.strip()
		if not text:
			raise ValueError("empty amount")
		try:
			Decimal(text)
		except InvalidOperation as exc:
			raise ValueError(f"invalid amount: {value!r}") from exc
		return text
	if isinstance(value, float):
		try:
			return format(Decimal(str(value)), "f")
		except InvalidOperation as exc:
			raise ValueError(f"invalid amount: {value!r}") from exc
	raise TypeError(f"unsupported amount type: {type(value).__name__}")


def optional_decimal_str(value: object) -> Optional[str]:
	if value is None:
		return None
	return decimal_str(value)


@dataclass(frozen=True)
class Balances:
	service_point: str
	nfa_coin: str
	subscription_pass: str

	@classmethod
	def from_mapping(cls, value: object) -> "Balances":
		data = value if isinstance(value, dict) else {}
		return cls(
			service_point=decimal_str(data.get("service_point", "0")),
			nfa_coin=decimal_str(data.get("nfa_coin", "0")),
			subscription_pass=decimal_str(data.get("subscription_pass", "0")),
		)


@dataclass(frozen=True)
class Entrance:
	id: str
	name: str
	host: str
	address: str
	raw: Mapping[str, Any] = field(default_factory=dict)

	@classmethod
	def from_mapping(cls, value: object) -> "Entrance":
		if not isinstance(value, dict):
			raise TypeError("entrance must be an object")
		host = str(value.get("host") or "")
		address = str(value.get("address") or host)
		return cls(
			id=str(value.get("id") or ""),
			name=str(value.get("name") or value.get("id") or ""),
			host=host,
			address=address,
			raw=value,
		)


@dataclass(frozen=True)
class UserProfile:
	id: str
	username: Optional[str]
	balances: Balances
	session: Optional[Mapping[str, Any]]
	raw: Mapping[str, Any]

	@classmethod
	def from_response(cls, payload: Mapping[str, Any]) -> "UserProfile":
		user = payload.get("user")
		if not isinstance(user, dict):
			raise ValueError("missing user object")
		session = user.get("session") or user.get("currentSession")
		return cls(
			id=str(user.get("id") or ""),
			username=str(user["username"]) if isinstance(user.get("username"), str) else None,
			balances=Balances.from_mapping(user.get("balances")),
			session=session if isinstance(session, dict) else None,
			raw=payload,
		)


@dataclass(frozen=True)
class SessionStatus:
	running: bool
	session: Optional[Mapping[str, Any]]
	address: Optional[str]
	entrance: Optional[str]
	entrances: Sequence[Entrance]
	raw: Mapping[str, Any]

	@classmethod
	def from_response(cls, payload: Mapping[str, Any]) -> "SessionStatus":
		session = payload.get("session")
		entrances_raw = payload.get("entrances") or []
		entrances = tuple(Entrance.from_mapping(item) for item in entrances_raw) if isinstance(entrances_raw, list) else ()
		address = payload.get("address") or payload.get("entrance")
		if not isinstance(address, str):
			address = entrances[0].address if entrances else None
		entrance = payload.get("entrance")
		if not isinstance(entrance, str):
			entrance = address
		return cls(
			running=bool(payload.get("running")),
			session=session if isinstance(session, dict) else None,
			address=address,
			entrance=entrance,
			entrances=entrances,
			raw=payload,
		)


@dataclass(frozen=True)
class Operation:
	id: str
	kind: str
	status: str
	progress_phase: str
	result: Mapping[str, Any]
	message: Optional[str]
	error_code: Optional[str]
	raw: Mapping[str, Any]

	@classmethod
	def from_mapping(cls, value: object) -> "Operation":
		if not isinstance(value, dict):
			raise TypeError("operation must be an object")
		result = value.get("result")
		return cls(
			id=str(value.get("id") or ""),
			kind=str(value.get("kind") or ""),
			status=str(value.get("status") or ""),
			progress_phase=str(value.get("progressPhase") or ""),
			result=result if isinstance(result, dict) else {},
			message=str(value["message"]) if isinstance(value.get("message"), str) else None,
			error_code=str(value["errorCode"]) if isinstance(value.get("errorCode"), str) else None,
			raw=value,
		)

	@property
	def terminal(self) -> bool:
		return self.status in {"succeeded", "failed", "canceled"}

	@property
	def succeeded(self) -> bool:
		return self.status == "succeeded"

	@property
	def route_acked(self) -> bool:
		return self.result.get("routeAcked") is True

	@property
	def session_id(self) -> Optional[str]:
		value = self.result.get("sessionId")
		return str(value) if isinstance(value, str) and value else None

	@property
	def entrances(self) -> Sequence[Entrance]:
		raw = self.result.get("entrances")
		if not isinstance(raw, list):
			return ()
		return tuple(Entrance.from_mapping(item) for item in raw)


@dataclass(frozen=True)
class StopResult:
	duration: int
	deduction: str
	session: Optional[Mapping[str, Any]]
	canceled_operations: int
	raw: Mapping[str, Any]

	@classmethod
	def from_response(cls, payload: Mapping[str, Any]) -> "StopResult":
		duration = payload.get("duration") or 0
		session = payload.get("session")
		canceled = payload.get("canceledOperations") or 0
		return cls(
			duration=int(duration),
			deduction=decimal_str(payload.get("deduction", 0)),
			session=session if isinstance(session, dict) else None,
			canceled_operations=int(canceled),
			raw=payload,
		)
