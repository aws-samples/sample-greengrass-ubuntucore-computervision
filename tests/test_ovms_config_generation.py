"""Unit tests for OVMS multi-model configuration generation.

Tests the _regenerate_ovms_config method in ModelManagerCore and the
write_multi_model_config utility function.

Requirements: 4.1, 4.2, 4.3
"""

import sys
import os
import json
import tempfile
from unittest.mock import MagicMock, patch

import pytest

# Add shared modules path
sys.path.insert(0, os.path.join(
    os.path.dirname(__file__), '..', 'greengrass-components', 'shared'
))

# Add artifact path for imports
sys.path.insert(0, os.path.join(
    os.path.dirname(__file__), '..', 'greengrass-components', 'artifacts',
    'com.example.ModelManagerCore', '1.0.0'
))

# Mock the awsiot module before importing model_manager_core
mock_clientv2 = MagicMock()
sys.modules['awsiot'] = MagicMock()
sys.modules['awsiot.greengrasscoreipc'] = MagicMock()
sys.modules['awsiot.greengrasscoreipc.clientv2'] = mock_clientv2

from ovms_config import write_multi_model_config, OVMSConfigError


@pytest.fixture
def mock_ipc_client():
    """Create a mock IPC client."""
    mock = MagicMock()
    mock.get_thing_shadow.side_effect = Exception("ResourceNotFoundException")
    return mock


@pytest.fixture
def temp_config_dir():
    """Create a temporary directory for OVMS config output."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def manager(mock_ipc_client, temp_config_dir):
    """Create a ModelManagerCore instance with mocked IPC and temp config dir."""
    mock_clientv2.GreengrassCoreIPCClientV2.return_value = mock_ipc_client

    with patch.dict(os.environ, {
        'AWS_IOT_THING_NAME': 'test-thing',
        'SNAP_COMPONENTS': '/snap/ovms-engine/current/components',
        'SNAP_COMMON': '/var/snap/ovms-engine/common',
        'OVMS_CONFIG_DIR': temp_config_dir,
    }):
        from model_manager_core import ModelManagerCore
        mgr = ModelManagerCore()
        mgr.ipc_client = mock_ipc_client
        yield mgr


class TestWriteMultiModelConfig:
    """Tests for the write_multi_model_config shared utility."""

    def test_writes_single_model(self, temp_config_dir):
        """Writes config with a single model entry."""
        models = [{"name": "faster_rcnn", "base_path": "/snap/ovms-engine/components/model-faster-rcnn"}]
        config_path = write_multi_model_config(models=models, config_dir=temp_config_dir)

        with open(config_path) as f:
            config = json.load(f)

        assert config == {
            "model_config_list": [
                {"config": {"name": "faster_rcnn", "base_path": "/snap/ovms-engine/components/model-faster-rcnn"}}
            ]
        }

    def test_writes_multiple_models(self, temp_config_dir):
        """Writes config with multiple model entries."""
        models = [
            {"name": "faster_rcnn", "base_path": "/snap/ovms-engine/components/model-faster-rcnn"},
            {"name": "efficientnet", "base_path": "/snap/ovms-engine/components/model-efficientnet"},
        ]
        config_path = write_multi_model_config(models=models, config_dir=temp_config_dir)

        with open(config_path) as f:
            config = json.load(f)

        assert len(config["model_config_list"]) == 2
        assert config["model_config_list"][0]["config"]["name"] == "faster_rcnn"
        assert config["model_config_list"][1]["config"]["name"] == "efficientnet"

    def test_writes_empty_model_list(self, temp_config_dir):
        """Writes config with empty model_config_list when no models provided."""
        config_path = write_multi_model_config(models=[], config_dir=temp_config_dir)

        with open(config_path) as f:
            config = json.load(f)

        assert config == {"model_config_list": []}

    def test_raises_on_missing_name(self, temp_config_dir):
        """Raises OVMSConfigError when a model entry is missing 'name'."""
        models = [{"base_path": "/some/path"}]
        with pytest.raises(OVMSConfigError):
            write_multi_model_config(models=models, config_dir=temp_config_dir)

    def test_raises_on_missing_base_path(self, temp_config_dir):
        """Raises OVMSConfigError when a model entry is missing 'base_path'."""
        models = [{"name": "my_model"}]
        with pytest.raises(OVMSConfigError):
            write_multi_model_config(models=models, config_dir=temp_config_dir)

    def test_raises_on_empty_config_dir(self):
        """Raises OVMSConfigError when config_dir is empty."""
        with pytest.raises(OVMSConfigError):
            write_multi_model_config(models=[], config_dir="")


class TestRegenerateOvmsConfig:
    """Tests for ModelManagerCore._regenerate_ovms_config integration."""

    def test_generates_config_for_ready_models(self, manager, temp_config_dir):
        """Generates config listing only models with status 'ready'."""
        manager.reported_models = {
            "faster-rcnn": {
                "status": "ready",
                "model_metadata": {
                    "model_name": "faster_rcnn",
                    "local_path": "/snap/ovms-engine/components/model-faster-rcnn",
                }
            },
            "efficientnet": {
                "status": "ready",
                "model_metadata": {
                    "model_name": "efficientnet",
                    "local_path": "/snap/ovms-engine/components/model-efficientnet",
                }
            },
        }

        manager._regenerate_ovms_config()

        config_path = os.path.join(temp_config_dir, "models_config.json")
        with open(config_path) as f:
            config = json.load(f)

        assert len(config["model_config_list"]) == 2
        names = [entry["config"]["name"] for entry in config["model_config_list"]]
        assert "faster_rcnn" in names
        assert "efficientnet" in names

    def test_excludes_installing_models(self, manager, temp_config_dir):
        """Does not include models with status 'installing' in the config."""
        manager.reported_models = {
            "faster-rcnn": {
                "status": "ready",
                "model_metadata": {
                    "model_name": "faster_rcnn",
                    "local_path": "/snap/ovms-engine/components/model-faster-rcnn",
                }
            },
            "new-model": {
                "status": "installing",
            },
        }

        manager._regenerate_ovms_config()

        config_path = os.path.join(temp_config_dir, "models_config.json")
        with open(config_path) as f:
            config = json.load(f)

        assert len(config["model_config_list"]) == 1
        assert config["model_config_list"][0]["config"]["name"] == "faster_rcnn"

    def test_excludes_failed_models(self, manager, temp_config_dir):
        """Does not include models with status 'failed' in the config."""
        manager.reported_models = {
            "faster-rcnn": {
                "status": "ready",
                "model_metadata": {
                    "model_name": "faster_rcnn",
                    "local_path": "/snap/ovms-engine/components/model-faster-rcnn",
                }
            },
            "broken-model": {
                "status": "failed",
                "reason": "snap install failed",
            },
        }

        manager._regenerate_ovms_config()

        config_path = os.path.join(temp_config_dir, "models_config.json")
        with open(config_path) as f:
            config = json.load(f)

        assert len(config["model_config_list"]) == 1
        assert config["model_config_list"][0]["config"]["name"] == "faster_rcnn"

    def test_skips_models_without_metadata(self, manager, temp_config_dir):
        """Skips ready models that lack model_metadata."""
        manager.reported_models = {
            "faster-rcnn": {
                "status": "ready",
                "model_metadata": {
                    "model_name": "faster_rcnn",
                    "local_path": "/snap/ovms-engine/components/model-faster-rcnn",
                }
            },
            "incomplete": {
                "status": "ready",
                # No model_metadata
            },
        }

        manager._regenerate_ovms_config()

        config_path = os.path.join(temp_config_dir, "models_config.json")
        with open(config_path) as f:
            config = json.load(f)

        assert len(config["model_config_list"]) == 1

    def test_writes_empty_config_when_no_ready_models(self, manager, temp_config_dir):
        """Writes empty model_config_list when no models are ready."""
        manager.reported_models = {
            "installing-model": {"status": "installing"},
        }

        manager._regenerate_ovms_config()

        config_path = os.path.join(temp_config_dir, "models_config.json")
        with open(config_path) as f:
            config = json.load(f)

        assert config == {"model_config_list": []}

    def test_triggered_on_model_ready(self, manager, temp_config_dir):
        """_regenerate_ovms_config is called when _report_model_status sets ready."""
        model_metadata = {
            "model_name": "faster_rcnn",
            "local_path": "/snap/ovms-engine/components/model-faster-rcnn",
            "input_name": "input_tensor",
            "output_names": ["detection_boxes"],
            "input_shape": [1, 255, 255, 3],
            "labels_file": "labels.txt",
        }

        manager._report_model_status("faster-rcnn", "ready", model_metadata=model_metadata)

        config_path = os.path.join(temp_config_dir, "models_config.json")
        assert os.path.exists(config_path)

        with open(config_path) as f:
            config = json.load(f)

        assert len(config["model_config_list"]) == 1
        assert config["model_config_list"][0]["config"]["name"] == "faster_rcnn"
        assert config["model_config_list"][0]["config"]["base_path"] == "/snap/ovms-engine/components/model-faster-rcnn"

    def test_not_triggered_on_installing_status(self, manager, temp_config_dir):
        """_regenerate_ovms_config is NOT called when status is 'installing'."""
        manager._report_model_status("faster-rcnn", "installing")

        config_path = os.path.join(temp_config_dir, "models_config.json")
        assert not os.path.exists(config_path)

    def test_config_uses_model_name_from_metadata(self, manager, temp_config_dir):
        """Config uses model_name from model_metadata, not the model_id."""
        manager.reported_models = {
            "my-custom-model": {
                "status": "ready",
                "model_metadata": {
                    "model_name": "custom_detector_v2",
                    "local_path": "/var/snap/ovms-engine/common/models/my-custom-model",
                }
            },
        }

        manager._regenerate_ovms_config()

        config_path = os.path.join(temp_config_dir, "models_config.json")
        with open(config_path) as f:
            config = json.load(f)

        assert config["model_config_list"][0]["config"]["name"] == "custom_detector_v2"
        assert config["model_config_list"][0]["config"]["base_path"] == "/var/snap/ovms-engine/common/models/my-custom-model"
