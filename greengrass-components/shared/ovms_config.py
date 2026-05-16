"""OVMS configuration manager utility for Dynamic Model Management.

Provides functions to read and write the OVMS multi-model configuration file
(`models_config.json`) used by OpenVINO Model Server within the cv-inference snap.

Supports both single-model configuration (for active model switching) and
multi-model configuration (for serving all ready models simultaneously).
OVMS reloads via `file_system_poll_wait_seconds` when the config file changes.

Requirements: 4.1, 4.2, 4.3, 5.2, 6.5
"""

import json
import os
import tempfile
from typing import Optional


# Default config filename
CONFIG_FILENAME = "models_config.json"


class OVMSConfigError(Exception):
    """Raised when an OVMS configuration operation fails."""
    pass


def write_model_config(model_name: str, base_path: str, config_dir: str) -> str:
    """Write the OVMS multi-model configuration file with a single active model.

    Writes the configuration atomically (write to temp file, then rename) to
    prevent OVMS from reading a partially-written file during reload.

    The resulting config follows the OVMS multi-model format:
    {
        "model_config_list": [
            {
                "config": {
                    "name": "<model_name>",
                    "base_path": "<base_path>"
                }
            }
        ]
    }

    Args:
        model_name: The model name used by OVMS for gRPC requests.
        base_path: The filesystem path where the model files are located.
        config_dir: The directory where models_config.json will be written.

    Returns:
        The full path to the written configuration file.

    Raises:
        OVMSConfigError: If the write operation fails due to filesystem errors.
    """
    if not model_name:
        raise OVMSConfigError("model_name must not be empty")
    if not base_path:
        raise OVMSConfigError("base_path must not be empty")
    if not config_dir:
        raise OVMSConfigError("config_dir must not be empty")

    config = {
        "model_config_list": [
            {
                "config": {
                    "name": model_name,
                    "base_path": base_path,
                }
            }
        ]
    }

    config_path = os.path.join(config_dir, CONFIG_FILENAME)

    try:
        os.makedirs(config_dir, exist_ok=True)

        fd, tmp_path = tempfile.mkstemp(
            suffix=".tmp",
            prefix="models_config_",
            dir=config_dir,
        )
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(config, f, indent=2)
                f.write("\n")
            os.replace(tmp_path, config_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except OVMSConfigError:
        raise
    except OSError as e:
        raise OVMSConfigError(f"Failed to write OVMS config to '{config_path}': {e}")

    return config_path


def write_multi_model_config(models: list, config_dir: str) -> str:
    """Write the OVMS multi-model configuration file with multiple models.

    Writes the configuration atomically (write to temp file, then rename) to
    prevent OVMS from reading a partially-written file during reload.

    The resulting config follows the OVMS multi-model format:
    {
        "model_config_list": [
            {
                "config": {
                    "name": "<model_name>",
                    "base_path": "<base_path>"
                }
            },
            ...
        ]
    }

    Args:
        models: A list of dicts, each with 'name' and 'base_path' keys.
        config_dir: The directory where models_config.json will be written.

    Returns:
        The full path to the written configuration file.

    Raises:
        OVMSConfigError: If the write operation fails due to filesystem errors
            or invalid input.
    """
    if not isinstance(models, list):
        raise OVMSConfigError("models must be a list")
    if not config_dir:
        raise OVMSConfigError("config_dir must not be empty")

    model_config_list = []
    for model in models:
        if not isinstance(model, dict):
            raise OVMSConfigError("Each model entry must be a dict")
        name = model.get("name")
        base_path = model.get("base_path")
        if not name or not base_path:
            raise OVMSConfigError(
                f"Each model entry must have 'name' and 'base_path', got: {model}"
            )
        model_config_list.append({
            "config": {
                "name": name,
                "base_path": base_path,
            }
        })

    config = {"model_config_list": model_config_list}
    config_path = os.path.join(config_dir, CONFIG_FILENAME)

    try:
        os.makedirs(config_dir, exist_ok=True)

        fd, tmp_path = tempfile.mkstemp(
            suffix=".tmp",
            prefix="models_config_",
            dir=config_dir,
        )
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(config, f, indent=2)
                f.write("\n")
            os.replace(tmp_path, config_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except OVMSConfigError:
        raise
    except OSError as e:
        raise OVMSConfigError(f"Failed to write OVMS config to '{config_path}': {e}")

    return config_path


def read_model_config(config_dir: str) -> Optional[dict]:
    """Read the current OVMS multi-model configuration.

    Args:
        config_dir: The directory containing models_config.json.

    Returns:
        The parsed configuration dictionary, or None if the file does not exist.

    Raises:
        OVMSConfigError: If the file exists but cannot be read or parsed.
    """
    if not config_dir:
        raise OVMSConfigError("config_dir must not be empty")

    config_path = os.path.join(config_dir, CONFIG_FILENAME)

    if not os.path.exists(config_path):
        return None

    try:
        with open(config_path, "r") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise OVMSConfigError(
            f"Failed to parse OVMS config at '{config_path}': {e}"
        )
    except OSError as e:
        raise OVMSConfigError(
            f"Failed to read OVMS config at '{config_path}': {e}"
        )

    return data


def get_active_model_from_config(config: dict) -> Optional[dict]:
    """Extract the active model entry from an OVMS configuration.

    Args:
        config: The parsed OVMS configuration dictionary.

    Returns:
        A dictionary with 'name' and 'base_path' keys for the active model,
        or None if the config is empty or malformed.
    """
    if not isinstance(config, dict):
        return None

    model_config_list = config.get("model_config_list")
    if not isinstance(model_config_list, list) or len(model_config_list) == 0:
        return None

    first_entry = model_config_list[0]
    if not isinstance(first_entry, dict):
        return None

    model_config = first_entry.get("config")
    if not isinstance(model_config, dict):
        return None

    name = model_config.get("name")
    base_path = model_config.get("base_path")

    if not name or not base_path:
        return None

    return {"name": name, "base_path": base_path}
