"""Data models and validation for Dynamic Model Management."""

from .error_event import (
    ErrorEvent,
    ErrorEventValidationError,
    build_error_event,
    build_error_event_now,
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
    VALID_ERROR_CODES,
)

__all__ = [
    "ErrorEvent",
    "ErrorEventValidationError",
    "build_error_event",
    "build_error_event_now",
    "MODEL_NOT_FOUND",
    "INVALID_PARAMETERS",
    "INVALID_MANIFEST",
    "DOWNLOAD_FAILED",
    "INSUFFICIENT_STORAGE",
    "STORAGE_CRITICAL",
    "MODEL_NOT_AVAILABLE",
    "MODEL_LOAD_FAILED",
    "CANNOT_DELETE_ACTIVE_MODEL",
    "DELETE_FAILED",
    "SNAP_INSTALL_FAILED",
    "VALID_ERROR_CODES",
]
