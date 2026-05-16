"""Shadow state schema and builder for the model-config Device Shadow.

Defines dataclass models for the `model-config` named shadow reported and desired
state sections, along with builder and validation functions.

Implements Property 1 (Shadow Reported State Schema Invariant) from the design
specification.

Requirements: 1.4, 1.5
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_MODEL_ID_LENGTH = 128
MODEL_ID_PATTERN = re.compile(r"^[a-z0-9_-]{1,128}$")

# ISO 8601 basic validation pattern (accepts common formats)
ISO_8601_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    r"(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?$"
)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ModelStatus(str, Enum):
    """Status of a model in the inventory.

    Values: ready, downloading, failed, deleting
    """

    READY = "ready"
    DOWNLOADING = "downloading"
    FAILED = "failed"
    DELETING = "deleting"


class EngineType(str, Enum):
    """Hardware engine variant for the Inference Snap.

    Values: cpu, gpu, npu
    """

    CPU = "cpu"
    GPU = "gpu"
    NPU = "npu"


# Valid string values for quick membership checks
VALID_STATUSES = frozenset({s.value for s in ModelStatus})
VALID_ENGINES = frozenset({e.value for e in EngineType})


# ---------------------------------------------------------------------------
# Dataclass Models
# ---------------------------------------------------------------------------

@dataclass
class ModelEntry:
    """A single model entry in the inventory map.

    Each model in the reported state `models` map contains these fields
    as specified in Requirement 1.5.
    """

    model_id: str
    model_name: str
    version: str
    local_path: str
    size_bytes: int
    last_updated: str
    status: str
    source: Optional[str] = None
    download_progress: Optional[int] = None
    failure_reason: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary, omitting None optional fields."""
        result = {
            "model_id": self.model_id,
            "model_name": self.model_name,
            "version": self.version,
            "local_path": self.local_path,
            "size_bytes": self.size_bytes,
            "last_updated": self.last_updated,
            "status": self.status,
        }
        if self.source is not None:
            result["source"] = self.source
        if self.download_progress is not None:
            result["download_progress"] = self.download_progress
        if self.failure_reason is not None:
            result["failure_reason"] = self.failure_reason
        return result


@dataclass
class ModelMetadata:
    """Active model metadata auto-populated from manifest.json.

    Reported in the shadow so the InferenceHandler can adapt its gRPC
    request parameters dynamically.
    """

    input_name: str
    output_names: List[str]
    input_shape: List[int]
    labels_file: str

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "input_name": self.input_name,
            "output_names": list(self.output_names),
            "input_shape": list(self.input_shape),
            "labels_file": self.labels_file,
        }


@dataclass
class ReportedState:
    """The model-config shadow reported state.

    Contains the device's current model management state as specified
    in Requirements 1.4 and 1.5.
    """

    active_model: str
    engine: str
    models: Dict[str, ModelEntry]
    storage_available_bytes: Optional[int] = None
    storage_total_bytes: Optional[int] = None
    model_metadata: Optional[ModelMetadata] = None
    storage_critical: Optional[bool] = None

    def to_dict(self) -> dict:
        """Convert to dictionary suitable for shadow update."""
        result: dict = {
            "active_model": self.active_model,
            "engine": self.engine,
            "models": {
                model_id: entry.to_dict()
                for model_id, entry in self.models.items()
            },
        }
        if self.storage_available_bytes is not None:
            result["storage_available_bytes"] = self.storage_available_bytes
        if self.storage_total_bytes is not None:
            result["storage_total_bytes"] = self.storage_total_bytes
        if self.model_metadata is not None:
            result["model_metadata"] = self.model_metadata.to_dict()
        if self.storage_critical is not None:
            result["storage_critical"] = self.storage_critical
        return result


@dataclass
class DesiredState:
    """The model-config shadow desired state.

    Contains operator-requested actions for model management.
    """

    provision_model: Optional[dict] = None
    active_model: Optional[str] = None
    delete_model: Optional[str] = None
    download_custom: Optional[dict] = None

    def to_dict(self) -> dict:
        """Convert to dictionary suitable for shadow update."""
        result: dict = {}
        if self.provision_model is not None:
            result["provision_model"] = self.provision_model
        if self.active_model is not None:
            result["active_model"] = self.active_model
        if self.delete_model is not None:
            result["delete_model"] = self.delete_model
        if self.download_custom is not None:
            result["download_custom"] = self.download_custom
        return result


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class InvalidReportedStateError(Exception):
    """Raised when reported state data fails validation."""

    def __init__(self, errors: List[str]):
        self.errors = errors
        super().__init__(f"Invalid reported state: {'; '.join(errors)}")


def validate_reported_state(data: dict) -> ReportedState:
    """Validate a reported state dictionary and return a ReportedState on success.

    Enforces the schema invariant from Property 1:
    - active_model: string, max 128 chars
    - models: map where each entry has required fields
    - engine: one of "cpu", "gpu", "npu"
    - Each model entry: model_id, model_name, version, local_path,
      size_bytes (positive int), last_updated (ISO 8601), status (valid enum)

    Args:
        data: Dictionary representing the reported state.

    Returns:
        A validated ReportedState instance.

    Raises:
        InvalidReportedStateError: If validation fails.
    """
    if not isinstance(data, dict):
        raise InvalidReportedStateError(
            [f"reported state must be a dict, got {type(data).__name__}"]
        )

    errors: List[str] = []

    # active_model: string, max 128 chars
    active_model = data.get("active_model")
    if active_model is None:
        errors.append("missing required field 'active_model'")
    elif not isinstance(active_model, str):
        errors.append(
            f"active_model must be a string, got {type(active_model).__name__}"
        )
    elif len(active_model) > MAX_MODEL_ID_LENGTH:
        errors.append(
            f"active_model must be at most {MAX_MODEL_ID_LENGTH} characters, "
            f"got {len(active_model)}"
        )

    # engine: one of "cpu", "gpu", "npu"
    engine = data.get("engine")
    if engine is None:
        errors.append("missing required field 'engine'")
    elif not isinstance(engine, str):
        errors.append(f"engine must be a string, got {type(engine).__name__}")
    elif engine not in VALID_ENGINES:
        errors.append(
            f"engine must be one of {sorted(VALID_ENGINES)}, got '{engine}'"
        )

    # models: map of model entries
    models_data = data.get("models")
    if models_data is None:
        errors.append("missing required field 'models'")
    elif not isinstance(models_data, dict):
        errors.append(f"models must be a dict, got {type(models_data).__name__}")
    else:
        for model_key, entry_data in models_data.items():
            prefix = f"models['{model_key}']"
            if not isinstance(entry_data, dict):
                errors.append(
                    f"{prefix} must be a dict, got {type(entry_data).__name__}"
                )
                continue
            errors.extend(_validate_model_entry(entry_data, prefix))

    if errors:
        raise InvalidReportedStateError(errors)

    # Build validated objects
    models: Dict[str, ModelEntry] = {}
    if isinstance(models_data, dict):
        for model_key, entry_data in models_data.items():
            models[model_key] = ModelEntry(
                model_id=entry_data["model_id"],
                model_name=entry_data["model_name"],
                version=entry_data["version"],
                local_path=entry_data["local_path"],
                size_bytes=entry_data["size_bytes"],
                last_updated=entry_data["last_updated"],
                status=entry_data["status"],
                source=entry_data.get("source"),
                download_progress=entry_data.get("download_progress"),
                failure_reason=entry_data.get("failure_reason"),
            )

    model_metadata = None
    if "model_metadata" in data and data["model_metadata"] is not None:
        md = data["model_metadata"]
        if isinstance(md, dict):
            model_metadata = ModelMetadata(
                input_name=md.get("input_name", ""),
                output_names=md.get("output_names", []),
                input_shape=md.get("input_shape", []),
                labels_file=md.get("labels_file", ""),
            )

    return ReportedState(
        active_model=active_model,
        engine=engine,
        models=models,
        storage_available_bytes=data.get("storage_available_bytes"),
        storage_total_bytes=data.get("storage_total_bytes"),
        model_metadata=model_metadata,
        storage_critical=data.get("storage_critical"),
    )


def _validate_model_entry(entry_data: dict, prefix: str) -> List[str]:
    """Validate a single model entry within the models map.

    Args:
        entry_data: Dictionary for one model entry.
        prefix: String prefix for error messages (e.g. "models['faster_rcnn']").

    Returns:
        List of validation error messages.
    """
    errors: List[str] = []

    # model_id: required string
    model_id = entry_data.get("model_id")
    if model_id is None:
        errors.append(f"{prefix} missing required field 'model_id'")
    elif not isinstance(model_id, str):
        errors.append(
            f"{prefix}.model_id must be a string, got {type(model_id).__name__}"
        )

    # model_name: required string
    model_name = entry_data.get("model_name")
    if model_name is None:
        errors.append(f"{prefix} missing required field 'model_name'")
    elif not isinstance(model_name, str):
        errors.append(
            f"{prefix}.model_name must be a string, got {type(model_name).__name__}"
        )

    # version: required string
    version = entry_data.get("version")
    if version is None:
        errors.append(f"{prefix} missing required field 'version'")
    elif not isinstance(version, str):
        errors.append(
            f"{prefix}.version must be a string, got {type(version).__name__}"
        )

    # local_path: required string
    local_path = entry_data.get("local_path")
    if local_path is None:
        errors.append(f"{prefix} missing required field 'local_path'")
    elif not isinstance(local_path, str):
        errors.append(
            f"{prefix}.local_path must be a string, got {type(local_path).__name__}"
        )

    # size_bytes: required positive integer
    size_bytes = entry_data.get("size_bytes")
    if size_bytes is None:
        errors.append(f"{prefix} missing required field 'size_bytes'")
    elif not isinstance(size_bytes, int) or isinstance(size_bytes, bool):
        errors.append(
            f"{prefix}.size_bytes must be an integer, got {type(size_bytes).__name__}"
        )
    elif size_bytes <= 0:
        errors.append(f"{prefix}.size_bytes must be positive, got {size_bytes}")

    # last_updated: required ISO 8601 string
    last_updated = entry_data.get("last_updated")
    if last_updated is None:
        errors.append(f"{prefix} missing required field 'last_updated'")
    elif not isinstance(last_updated, str):
        errors.append(
            f"{prefix}.last_updated must be a string, "
            f"got {type(last_updated).__name__}"
        )
    elif not ISO_8601_PATTERN.match(last_updated):
        errors.append(
            f"{prefix}.last_updated must be ISO 8601 format, got '{last_updated}'"
        )

    # status: required, one of valid statuses
    status = entry_data.get("status")
    if status is None:
        errors.append(f"{prefix} missing required field 'status'")
    elif not isinstance(status, str):
        errors.append(
            f"{prefix}.status must be a string, got {type(status).__name__}"
        )
    elif status not in VALID_STATUSES:
        errors.append(
            f"{prefix}.status must be one of {sorted(VALID_STATUSES)}, "
            f"got '{status}'"
        )

    return errors


# ---------------------------------------------------------------------------
# Builder Functions
# ---------------------------------------------------------------------------

def build_reported_state(
    active_model: str,
    engine: str,
    models: Dict[str, ModelEntry],
    storage_available_bytes: Optional[int] = None,
    storage_total_bytes: Optional[int] = None,
    model_metadata: Optional[ModelMetadata] = None,
    storage_critical: Optional[bool] = None,
) -> ReportedState:
    """Build a validated ReportedState instance.

    Constructs the reported state and validates it against the schema invariant
    before returning. This ensures any state built through this function
    conforms to the shadow contract.

    Args:
        active_model: The currently active model ID (max 128 chars).
        engine: The active engine variant ("cpu", "gpu", or "npu").
        models: Map of model_id to ModelEntry for the inventory.
        storage_available_bytes: Available storage in bytes (optional).
        storage_total_bytes: Total storage in bytes (optional).
        model_metadata: Active model metadata from manifest (optional).
        storage_critical: Whether storage is critically low (optional).

    Returns:
        A validated ReportedState instance.

    Raises:
        InvalidReportedStateError: If the constructed state fails validation.
    """
    state = ReportedState(
        active_model=active_model,
        engine=engine,
        models=models,
        storage_available_bytes=storage_available_bytes,
        storage_total_bytes=storage_total_bytes,
        model_metadata=model_metadata,
        storage_critical=storage_critical,
    )

    # Validate by round-tripping through the validator
    validate_reported_state(state.to_dict())

    return state
