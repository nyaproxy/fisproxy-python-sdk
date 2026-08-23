from __future__ import annotations

from ._version import __version__


def main() -> None:
	print(f"fisproxy {__version__}")
	print("User session SDK. Create a token on the API page, then:")
	print("  from fisproxy import Client")
	print("  client = Client.from_env()  # FISPROXY_API_TOKEN")


if __name__ == "__main__":
	main()
