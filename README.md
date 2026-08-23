# fisproxy

Official Python SDK for the [FisProxy](https://fisproxy.org) user session API.

Create an API token on the signed-in **API** page. The plaintext is shown once. There is no login flow in this client.

Default endpoint: `https://api.fisproxy.org`.

## Install

```bash
pip install git+https://github.com/nyaproxy/python-sdk.git
```

Python 3.9+. No third-party runtime dependencies.

## Quick start

```python
from fisproxy import Client

client = Client.from_env()  # FISPROXY_API_TOKEN
me = client.me()
print(me.balances.service_point)  # decimal string, not float

operation = client.start(wait=True)
status = client.status()
print(status.address)  # {sessionId}.{host}

client.stop()
```

Environment:

| Variable | Meaning |
|---|---|
| `FISPROXY_API_TOKEN` | Bearer token from the API page |
| `FISPROXY_API_BASE` | Override API host. Default `https://api.fisproxy.org` |
| `FISPROXY_CLIENT_ID` | Optional stable process id (`[A-Za-z0-9._~:-]{1,96}`) |

`service_point` and `nfa_coin` are decimal strings. Do not convert them to floats.

## Methods

| Method | Notes |
|---|---|
| `me()` | Profile, bindings, decimal `balances` |
| `services()` | Visible services for `start(service_id=...)` |
| `status()` | `running`, `address`, `entrances` |
| `entrances(service_id=None)` | Host before start; `{sessionId}.{host}` after |
| `start(...)` | Queues a start. `wait=True` (default) polls until success |
| `change_ip(...)` | Queues an IP change. Default wait includes route ACK |
| `stop()` | Stops billing and returns `{duration, deduction}` |
| `get_operation` / `wait_operation` / `cancel_operation` | Follow async start / change-ip |

`start` / `change_ip` send an `Idempotency-Key` automatically. Conflicts raise `ConflictError` with `existing_operation`.

Start fields (all optional): `service_id`, `target`, `auto_nfa`, `nfa_item_id`, `reuse_nfa_item_id`, `nfa_source`, `nfa_sku`, `try_previous_nfa`.

The Minecraft connect string is `status.address` / `status.entrances[].address`. Change-ip rotates the exit; the entrance usually stays.

## Example

See [`examples/session.py`](examples/session.py).

```bash
export FISPROXY_API_TOKEN=...
python examples/session.py
```

## Errors

- `AuthError` — token revoked, banned, or unauthorized
- `AdmissionError` — the API rejected this request; transient cases are retried
- `ConflictError` — another operation is already running (409)
- `OperationFailed` — async start / change-ip ended `failed` or `canceled`
- `OperationTimeout` — polling deadline
- `TransportError` — network failure

## License

MIT
