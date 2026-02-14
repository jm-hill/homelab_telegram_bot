import logging

import requests

logger = logging.getLogger(__name__)


def _headers(api_key):
    return {"X-API-Key": api_key}


def _raise_for_status(resp):
    """Raise with response body included for easier debugging."""
    try:
        resp.raise_for_status()
    except requests.exceptions.HTTPError:
        logger.error(f"Portainer API error {resp.status_code}: {resp.text[:500]}")
        raise


def get_stacks(base_url, api_key):
    """Get all stacks with their status.

    Returns a list of dicts with keys: id, name, status, endpoint_id.
    """
    resp = requests.get(
        f"{base_url}/api/stacks",
        headers=_headers(api_key),
        timeout=10,
        verify=False,
    )
    _raise_for_status(resp)
    return [
        {
            "id": s["Id"],
            "name": s["Name"],
            "status": s["Status"],
            "endpoint_id": s["EndpointId"],
        }
        for s in resp.json()
    ]


def start_stack(base_url, api_key, stack_id, endpoint_id):
    """Start a stack by ID."""
    resp = requests.post(
        f"{base_url}/api/stacks/{stack_id}/start",
        headers=_headers(api_key),
        params={"endpointId": endpoint_id},
        timeout=30,
        verify=False,
    )
    _raise_for_status(resp)


def stop_stack(base_url, api_key, stack_id, endpoint_id):
    """Stop a stack by ID."""
    resp = requests.post(
        f"{base_url}/api/stacks/{stack_id}/stop",
        headers=_headers(api_key),
        params={"endpointId": endpoint_id},
        timeout=30,
        verify=False,
    )
    _raise_for_status(resp)
