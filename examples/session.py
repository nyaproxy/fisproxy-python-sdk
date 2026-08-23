#!/usr/bin/env python3
"""Start a session, print the connect address, then stop.

  FISPROXY_API_TOKEN   required
  FISPROXY_API_BASE    default https://api.fisproxy.org
"""

from __future__ import annotations

from fisproxy import Client


def main() -> None:
	with Client.from_env() as client:
		me = client.me()
		print("user", me.id, "service_point", me.balances.service_point)

		operation = client.start(wait=True)
		print("start", operation.status, "session", operation.session_id)

		status = client.status()
		print("running", status.running, "address", status.address)
		for entrance in status.entrances:
			print("entrance", entrance.name, entrance.address)

		stopped = client.stop()
		print("stop duration", stopped.duration, "deduction", stopped.deduction)


if __name__ == "__main__":
	main()
