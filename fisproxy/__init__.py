"""Official Python SDK for the FisProxy user session API.

Authenticate with a user API token from the signed-in API page.
"""

from ._version import __version__
from .client import Client, FisProxy
from .errors import (
	AdmissionError,
	AuthError,
	ConflictError,
	FisProxyError,
	OperationFailed,
	OperationTimeout,
	TransportError,
)
from .models import Balances, Entrance, Operation, SessionStatus, StopResult, UserProfile

__all__ = [
	"AdmissionError",
	"AuthError",
	"Balances",
	"Client",
	"ConflictError",
	"Entrance",
	"FisProxy",
	"FisProxyError",
	"Operation",
	"OperationFailed",
	"OperationTimeout",
	"SessionStatus",
	"StopResult",
	"TransportError",
	"UserProfile",
	"__version__",
]
