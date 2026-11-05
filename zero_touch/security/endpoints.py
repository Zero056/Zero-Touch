"""Endpoint policy for external and local providers (SSRF guard, literal-address part).

DNS resolution and re-checks at call time are added with the provider calls in Phase 2.
No Frappe imports.
"""

import ipaddress
from urllib.parse import urlsplit

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


class EndpointPolicyError(ValueError):
	pass


def check_endpoint_url(url: str, *, local_provider: bool) -> None:
	if not url:
		return
	parts = urlsplit(url)
	host = (parts.hostname or "").lower()
	if not host:
		raise EndpointPolicyError("Endpoint must include a host")
	if parts.username or parts.password:
		raise EndpointPolicyError("Endpoint must not include credentials")

	is_loopback_host = host in LOCAL_HOSTS
	if local_provider and is_loopback_host:
		if parts.scheme not in ("http", "https"):
			raise EndpointPolicyError("Endpoint scheme must be http or https")
		return

	if parts.scheme != "https":
		raise EndpointPolicyError("External endpoints must use https")

	try:
		address = ipaddress.ip_address(host)
	except ValueError:
		return  # hostname: resolved and re-checked at call time (Phase 2)

	if (
		address.is_private
		or address.is_loopback
		or address.is_link_local
		or address.is_multicast
		or address.is_reserved
		or address.is_unspecified
	):
		raise EndpointPolicyError("Endpoint address is not allowed")
