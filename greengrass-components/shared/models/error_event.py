"""
Error event schema for Dynamic Model Management.

Defines the structured error event published to `model-manager/{thingName}/errors`
and provides a factory function for constructing validated error events.

Requirements: 10.6
"""

from dataclasses import dataclass, asdict
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Structured Error Codes (from design specification)
# ---------------------------------------------------------------------------

MODEL_NOT_FOUND = "model_not_found"
"""Model not in snap registry and no s3_uri provided."""

INVALID_PARAMETERS = "invalid_parameters"
"""model_id or version format invalid."""

INVALID_MANIFEST = "invalid_manifest"
"""manifest.json missing or unparseable."""

DOWNLOAD_FAILED = "download_failed"
"""S3 download failed after retries."""

INSUFFICIENT_STORAGE = "insufficient_storage"
"""Not enough disk space for download."""

STORAGE_CRITICAL = "storage_critical"
"""Device below 200 MB available space."""

MODEL_NOT_AVAILABLE = "model_not_available"
"""Model not in inventory or not ready."""

MODEL_LOAD_FAILED = "model_load_failed"
"""OVMS failed to load model within 60s."""

CANNOT_DELETE_ACTIVE_MODEL = "cannot_delete_active_model"
"""Attempted to delete the active model."""

DELETE_FAILED = "delete_failed"
"""Filesystem error during deletion."""

SNAP_INSTALL_FAILED = "snap_install_failed"
"""Snap install/refresh failed."""

# Complete set of valid error codes for validation
VALID_ERROR_CODES = frozenset({
    MODEL_NOT_FOUND,
    INVALID_PARAMETERS,
    INVALID_MANIFEST,
    DOWNLOAD_FAILED,
    INSUFFICIENT_STORAGE,
    STORAGE_CRITICAL,
    MODEL_NOT_AVAILABLE,
    MODEL_LOAD_FAILED,
    CANNOT_DELETE_ACTIVE_MODEL,
    DELETE_FAILED,
    SNAP_INSTALL_FAILED,
})


# ---------------------------------------------------------------------------
# Error Event Dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ErrorEvent:
    """Structured error event published to model-manager/{thingName}/errors.

    All fields are required and must be non-empty strings.

    Attributes:
        timestamp: ISO 8601 formatted timestamp of when the error occurred.
        operation: The operation that produced the error (e.g. "provision_model").
        model_id: The model ID associated with the error.
        error_code: A structured error code from the defined set.
        error_message: Human-readable description of the error.
    """

    timestamp: str
    operation: str
    model_id: str
    error_code: str
    error_message: str

    def to_dict(self) -> dict:
        """Convert the error event to a dictionary suitable for JSON serialization."""
        return asdict(self)


# ---------------------------------------------------------------------------
# Factory Function
# ---------------------------------------------------------------------------

class ErrorEventValidationError(Exception):
    """Raised when error event fields fail validation."""
    pass


def build_error_event(
    timestamp: str,
    operation: str,
    model_id: str,
    error_code: str,
    error_message: str,
) -> ErrorEvent:
    """Build a validated ErrorEvent instance.

    Args:
        timestamp: ISO 8601 formatted timestamp string (must be non-empty).
        operation: The operation that triggered the error (must be non-empty).
        model_id: The model ID related to the error (must be non-empty).
        error_code: Structured error code (must be non-empty).
        error_message: Human-readable error description (must be non-empty).

    Returns:
        A validated ErrorEvent instance.

    Raises:
        ErrorEventValidationError: If any required field is missing or invalid.
    """
    errors = []

    if not isinstance(timestamp, str) or not timestamp.strip():
        errors.append("timestamp must be a non-empty ISO 8601 string")

    if not isinstance(operation, str) or not operation.strip():
        errors.append("operation must be a non-empty string")

    if not isinstance(model_id, str) or not model_id.strip():
        errors.append("model_id must be a non-empty string")

    if not isinstance(error_code, str) or not error_code.strip():
        errors.append("error_code must be a non-empty string")

    if not isinstance(error_message, str) or not error_message.strip():
        errors.append("error_message must be a non-empty string")

    if errors:
        raise ErrorEventValidationError(
            f"Invalid error event fields: {'; '.join(errors)}"
        )

    return ErrorEvent(
        timestamp=timestamp,
        operation=operation,
        model_id=model_id,
        error_code=error_code,
        error_message=error_message,
    )


def build_error_event_now(
    operation: str,
    model_id: str,
    error_code: str,
    error_message: str,
) -> ErrorEvent:
    """Build an ErrorEvent with the current UTC timestamp.

    Convenience wrapper around build_error_event that auto-generates
    the timestamp as the current time in ISO 8601 format.

    Args:
        operation: The operation that triggered the error.
        model_id: The model ID related to the error.
        error_code: Structured error code.
        error_message: Human-readable error description.

    Returns:
        A validated ErrorEvent instance with current UTC timestamp.

    Raises:
        ErrorEventValidationError: If any required field is missing or invalid.
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return build_error_event(timestamp, operation, model_id, error_code, error_message)
