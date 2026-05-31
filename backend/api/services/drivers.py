"""
Backward-compatibility shim for driver standings service.
Redirects to the new api.drivers.services module while ensuring that
test patches applied to `api.services.drivers.requests.get` are visible to
the underlying Jolpica client (which performs HTTP calls).
"""
import requests

from api.drivers.services.standings import get_driver_standings  # noqa: F401

# Ensure the Jolpica client uses the same `requests` module object so that
# unit tests patching `api.services.drivers.requests.get` affect calls made
# inside `api.drivers.jolpica_client.fetch_driver_standings`.
try:
	import api.drivers.jolpica_client as _jolpica_client
	_jolpica_client.requests = requests
except Exception:
	# Best-effort; if the jolpica client isn't importable during test
	# environment setup, skip the assignment.
	pass
