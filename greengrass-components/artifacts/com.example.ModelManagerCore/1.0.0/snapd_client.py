"""snapd REST API client for Ubuntu Core snap management.

Communicates with the snapd daemon via its UNIX socket at /run/snapd.socket
to install, remove, and query snap components. This is the correct mechanism
for programmatic snap management on Ubuntu Core when the calling snap has
the snapd-control interface connected.

Reference: https://snapcraft.io/docs/snapd-rest-api
"""

import json
import http.client
import socket
import time
import logging

logger = logging.getLogger(__name__)

SNAPD_SOCKET = "/run/snapd.socket"
SNAPD_API_VERSION = "v2"


class SnapdError(Exception):
    """Raised when a snapd API call fails."""

    def __init__(self, message, status_code=None, kind=None):
        super().__init__(message)
        self.status_code = status_code
        self.kind = kind


class SnapdClient:
    """Client for the snapd REST API via UNIX socket.

    Uses http.client over a UNIX socket connection to communicate with snapd.
    All snap management operations (install, remove, info) are performed through
    this interface rather than shelling out to the snap CLI.
    """

    def __init__(self, socket_path=SNAPD_SOCKET):
        self.socket_path = socket_path

    def _make_connection(self):
        """Create an HTTP connection over the snapd UNIX socket."""
        conn = http.client.HTTPConnection("localhost")
        conn.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        conn.sock.connect(self.socket_path)
        return conn

    def _request(self, method, path, body=None):
        """Make a request to the snapd API and return the parsed response.

        Args:
            method: HTTP method (GET, POST, etc.)
            path: API path (e.g., /v2/snaps)
            body: Optional dict to send as JSON body

        Returns:
            Parsed JSON response dict

        Raises:
            SnapdError: If the API returns an error response
        """
        conn = self._make_connection()
        try:
            headers = {"Content-Type": "application/json"}
            json_body = json.dumps(body) if body else None
            conn.request(method, path, body=json_body, headers=headers)
            response = conn.getresponse()
            data = json.loads(response.read().decode("utf-8"))

            if data.get("type") == "error":
                raise SnapdError(
                    data.get("result", {}).get("message", "Unknown snapd error"),
                    status_code=data.get("status-code"),
                    kind=data.get("result", {}).get("kind"),
                )

            return data
        finally:
            conn.close()

    def _wait_for_change(self, change_id, timeout=300, poll_interval=2):
        """Poll a snapd change until it completes or times out.

        Args:
            change_id: The change ID returned by an async snapd operation
            timeout: Maximum seconds to wait
            poll_interval: Seconds between polls

        Returns:
            The final change status dict

        Raises:
            SnapdError: If the change fails or times out
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            data = self._request("GET", f"/{SNAPD_API_VERSION}/changes/{change_id}")
            result = data.get("result", {})
            status = result.get("status")

            if status == "Done":
                logger.info("Change %s completed successfully", change_id)
                return result
            elif status == "Error":
                err_msg = result.get("err", "Unknown error during snap operation")
                raise SnapdError(f"Snap operation failed: {err_msg}")
            elif status in ("Hold", "Abort"):
                raise SnapdError(f"Snap operation was {status.lower()}ed")

            time.sleep(poll_interval)

        raise SnapdError(
            f"Snap operation timed out after {timeout}s (change {change_id})"
        )

    def install_component(self, snap_name, component_name, timeout=300):
        """Install a component of an already-installed snap.

        Args:
            snap_name: The host snap name (e.g., 'cv-inference')
            component_name: The component to install (e.g., 'model-faster-rcnn')
            timeout: Maximum seconds to wait for installation

        Returns:
            The change result dict on success

        Raises:
            SnapdError: If installation fails
        """
        body = {"action": "install", "components": [component_name]}

        logger.info(
            "Installing component '%s' of snap '%s' via snapd API",
            component_name, snap_name,
        )
        data = self._request(
            "POST", f"/{SNAPD_API_VERSION}/snaps/{snap_name}", body=body
        )

        if data.get("type") == "async":
            change_id = data.get("change")
            return self._wait_for_change(change_id, timeout=timeout)
        else:
            return data.get("result", {})

    def remove_component(self, snap_name, component_name, timeout=300):
        """Remove a component of an installed snap.

        Args:
            snap_name: The host snap name (e.g., 'cv-inference')
            component_name: The component to remove (e.g., 'model-faster-rcnn')
            timeout: Maximum seconds to wait for removal

        Returns:
            The change result dict on success

        Raises:
            SnapdError: If removal fails
        """
        body = {"action": "remove", "components": [component_name]}

        logger.info(
            "Removing component '%s' of snap '%s' via snapd API",
            component_name, snap_name,
        )
        data = self._request(
            "POST", f"/{SNAPD_API_VERSION}/snaps/{snap_name}", body=body
        )

        if data.get("type") == "async":
            change_id = data.get("change")
            return self._wait_for_change(change_id, timeout=timeout)
        else:
            return data.get("result", {})

    def remove(self, snap_name, timeout=300):
        """Remove a snap or snap component.

        Args:
            snap_name: Full snap name to remove
            timeout: Maximum seconds to wait for removal

        Returns:
            The change result dict on success

        Raises:
            SnapdError: If removal fails
        """
        body = {"action": "remove"}

        logger.info("Removing snap via snapd API: %s", snap_name)
        data = self._request(
            "POST", f"/{SNAPD_API_VERSION}/snaps/{snap_name}", body=body
        )

        if data.get("type") == "async":
            change_id = data.get("change")
            return self._wait_for_change(change_id, timeout=timeout)
        else:
            return data.get("result", {})

    def info(self, snap_name):
        """Get information about an installed snap.

        Args:
            snap_name: Snap name to query

        Returns:
            Snap info dict, or None if not installed

        Raises:
            SnapdError: If the API call fails (other than not-found)
        """
        try:
            data = self._request(
                "GET", f"/{SNAPD_API_VERSION}/snaps/{snap_name}"
            )
            return data.get("result")
        except SnapdError as e:
            if e.kind == "snap-not-found":
                return None
            raise

    def is_installed(self, snap_name):
        """Check if a snap is installed.

        Args:
            snap_name: Snap name to check

        Returns:
            True if installed, False otherwise
        """
        return self.info(snap_name) is not None
