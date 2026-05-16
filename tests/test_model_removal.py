"""Unit tests for ModelManagerCore model removal logic.

Tests the _handle_model_removal method which removes models from OVMS config,
deletes local files, and updates the shadow reported state.

Requirements: 8.1, 8.2, 8.3
"""

import sys
import os
import json
import tempfile
import shutil
from unittest.mock import MagicMock, patch

import pytest

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


@pytest.fixture
def mock_ipc_client():
    """Create a mock IPC client."""
    mock = MagicMock()
    mock.get_thing_shadow.side_effect = Exception("ResourceNotFoundException")
    return mock


@pytest.fixture
def temp_dirs():
    """Create temporary directories for model files and OVMS config."""
    base = tempfile.mkdtemp()
    snap_components = os.path.join(base, "components")
    snap_common = os.path.join(base, "common")
    config_dir = os.path.join(snap_common, "config")
    os.makedirs(snap_components, exist_ok=True)
    os.makedirs(snap_common, exist_ok=True)
    os.makedirs(config_dir, exist_ok=True)
    yield {
        "base": base,
        "snap_components": snap_components,
        "snap_common": snap_common,
        "config_dir": config_dir,
    }
    shutil.rmtree(base)


@pytest.fixture
def manager(mock_ipc_client, temp_dirs):
    """Create a ModelManagerCore instance with mocked IPC and temp directories."""
    mock_clientv2.GreengrassCoreIPCClientV2.return_value = mock_ipc_client

    with patch.dict(os.environ, {
        'AWS_IOT_THING_NAME': 'test-thing',
        'SNAP_COMPONENTS': temp_dirs['snap_components'],
        'SNAP_COMMON': temp_dirs['snap_common'],
        'OVMS_CONFIG_DIR': temp_dirs['config_dir'],
    }):
        from model_manager_core import ModelManagerCore
        mgr = ModelManagerCore()
        mgr.ipc_client = mock_ipc_client
        yield mgr


def _create_model_dir(base_path, model_id, is_snap=True, snap_components=None, snap_common=None):
    """Helper to create a model directory with a manifest.json file."""
    if is_snap:
        model_dir = os.path.join(snap_components, f"model-{model_id}")
    else:
        model_dir = os.path.join(snap_common, "models", model_id)

    os.makedirs(model_dir, exist_ok=True)

    manifest = {
        "model_id": model_id,
        "model_name": model_id.replace("-", "_"),
        "version": "1.0.0",
        "input_name": "input_tensor",
        "output_names": ["output"],
        "input_shape": [1, 224, 224, 3],
        "labels_file": "labels.txt",
    }
    with open(os.path.join(model_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f)
    with open(os.path.join(model_dir, "model.bin"), "w") as f:
        f.write("fake model data")

    return model_dir


class TestModelRemovalBasic:
    """Tests for basic model removal functionality (Requirement 8.1, 8.2)."""

    def test_removes_model_from_reported_state(self, manager, mock_ipc_client, temp_dirs):
        """Removing a model removes it from reported_models and updates shadow."""
        model_dir = _create_model_dir(
            None, "old-model", is_snap=True,
            snap_components=temp_dirs['snap_components'],
            snap_common=temp_dirs['snap_common'],
        )
        manager.reported_models = {
            'old-model': {
                'status': 'ready',
                'model_metadata': {
                    'model_name': 'old_model',
                    'local_path': model_dir,
                }
            },
            'keep-model': {
                'status': 'ready',
                'model_metadata': {
                    'model_name': 'keep_model',
                    'local_path': '/some/other/path',
                }
            },
        }

        manager._handle_model_removal('old-model')

        assert 'old-model' not in manager.reported_models
        assert 'keep-model' in manager.reported_models

    def test_updates_shadow_after_removal(self, manager, mock_ipc_client, temp_dirs):
        """Shadow reported state is updated after model removal."""
        model_dir = _create_model_dir(
            None, "remove-me", is_snap=True,
            snap_components=temp_dirs['snap_components'],
            snap_common=temp_dirs['snap_common'],
        )
        manager.reported_models = {
            'remove-me': {
                'status': 'ready',
                'model_metadata': {
                    'model_name': 'remove_me',
                    'local_path': model_dir,
                }
            },
            'stay-model': {
                'status': 'ready',
                'model_metadata': {
                    'model_name': 'stay_model',
                    'local_path': '/other/path',
                }
            },
        }

        manager._handle_model_removal('remove-me')

        # Verify shadow was updated
        mock_ipc_client.update_thing_shadow.assert_called()
        call_kwargs = mock_ipc_client.update_thing_shadow.call_args.kwargs
        payload = json.loads(call_kwargs['payload'])
        models = payload['state']['reported']['models']
        assert 'remove-me' not in models
        assert 'stay-model' in models

    def test_deletes_snap_model_local_files(self, manager, temp_dirs):
        """Snap model local files are deleted on removal."""
        model_dir = _create_model_dir(
            None, "snap-model", is_snap=True,
            snap_components=temp_dirs['snap_components'],
            snap_common=temp_dirs['snap_common'],
        )
        manager.reported_models = {
            'snap-model': {
                'status': 'ready',
                'model_metadata': {
                    'model_name': 'snap_model',
                    'local_path': model_dir,
                }
            },
            'other-model': {
                'status': 'ready',
                'model_metadata': {
                    'model_name': 'other_model',
                    'local_path': '/other/path',
                }
            },
        }

        assert os.path.isdir(model_dir)
        manager._handle_model_removal('snap-model')
        assert not os.path.exists(model_dir)

    def test_deletes_s3_model_local_files(self, manager, temp_dirs):
        """S3 model local files are deleted on removal."""
        model_dir = _create_model_dir(
            None, "s3-model", is_snap=False,
            snap_components=temp_dirs['snap_components'],
            snap_common=temp_dirs['snap_common'],
        )
        manager.reported_models = {
            's3-model': {
                'status': 'ready',
                'model_metadata': {
                    'model_name': 's3_model',
                    'local_path': model_dir,
                }
            },
            'other-model': {
                'status': 'ready',
                'model_metadata': {
                    'model_name': 'other_model',
                    'local_path': '/other/path',
                }
            },
        }

        assert os.path.isdir(model_dir)
        manager._handle_model_removal('s3-model')
        assert not os.path.exists(model_dir)

    def test_regenerates_ovms_config_after_removal(self, manager, temp_dirs):
        """OVMS config is regenerated with remaining models after removal."""
        model_dir = _create_model_dir(
            None, "remove-model", is_snap=True,
            snap_components=temp_dirs['snap_components'],
            snap_common=temp_dirs['snap_common'],
        )
        keep_model_dir = _create_model_dir(
            None, "keep-model", is_snap=True,
            snap_components=temp_dirs['snap_components'],
            snap_common=temp_dirs['snap_common'],
        )
        manager.reported_models = {
            'remove-model': {
                'status': 'ready',
                'model_metadata': {
                    'model_name': 'remove_model',
                    'local_path': model_dir,
                }
            },
            'keep-model': {
                'status': 'ready',
                'model_metadata': {
                    'model_name': 'keep_model',
                    'local_path': keep_model_dir,
                }
            },
        }

        manager._handle_model_removal('remove-model')

        # Verify OVMS config only contains the remaining model
        config_path = os.path.join(temp_dirs['config_dir'], 'models_config.json')
        assert os.path.exists(config_path)
        with open(config_path, 'r') as f:
            config = json.load(f)

        model_names = [
            entry['config']['name'] for entry in config['model_config_list']
        ]
        assert 'keep_model' in model_names
        assert 'remove_model' not in model_names


class TestModelRemovalLastModel:
    """Tests for refusing to remove the last remaining model (Requirement 8.3)."""

    def test_refuses_to_remove_last_ready_model(self, manager, temp_dirs):
        """Cannot remove the only remaining ready model."""
        model_dir = _create_model_dir(
            None, "only-model", is_snap=True,
            snap_components=temp_dirs['snap_components'],
            snap_common=temp_dirs['snap_common'],
        )
        manager.reported_models = {
            'only-model': {
                'status': 'ready',
                'model_metadata': {
                    'model_name': 'only_model',
                    'local_path': model_dir,
                }
            },
        }

        manager._handle_model_removal('only-model')

        # Model should still be in reported_models
        assert 'only-model' in manager.reported_models
        # Local files should still exist
        assert os.path.isdir(model_dir)

    def test_refuses_removal_when_only_one_ready_among_failed(self, manager, temp_dirs):
        """Cannot remove the only ready model even if failed models exist."""
        model_dir = _create_model_dir(
            None, "last-ready", is_snap=True,
            snap_components=temp_dirs['snap_components'],
            snap_common=temp_dirs['snap_common'],
        )
        manager.reported_models = {
            'last-ready': {
                'status': 'ready',
                'model_metadata': {
                    'model_name': 'last_ready',
                    'local_path': model_dir,
                }
            },
            'failed-model': {
                'status': 'failed',
                'reason': 'download error',
            },
        }

        manager._handle_model_removal('last-ready')

        # Model should still be in reported_models
        assert 'last-ready' in manager.reported_models
        assert os.path.isdir(model_dir)

    def test_allows_removal_when_other_ready_models_exist(self, manager, temp_dirs):
        """Can remove a model when other ready models remain."""
        model_dir = _create_model_dir(
            None, "removable", is_snap=True,
            snap_components=temp_dirs['snap_components'],
            snap_common=temp_dirs['snap_common'],
        )
        manager.reported_models = {
            'removable': {
                'status': 'ready',
                'model_metadata': {
                    'model_name': 'removable_model',
                    'local_path': model_dir,
                }
            },
            'other-ready': {
                'status': 'ready',
                'model_metadata': {
                    'model_name': 'other_ready',
                    'local_path': '/other/path',
                }
            },
        }

        manager._handle_model_removal('removable')

        assert 'removable' not in manager.reported_models
        assert 'other-ready' in manager.reported_models

    def test_allows_removal_of_failed_model_even_if_last(self, manager, temp_dirs):
        """Can remove a failed model even if it's the only one (it's not 'ready')."""
        manager.reported_models = {
            'failed-only': {
                'status': 'failed',
                'reason': 'install error',
                'model_metadata': {
                    'model_name': 'failed_only',
                    'local_path': '/nonexistent/path',
                }
            },
        }

        manager._handle_model_removal('failed-only')

        assert 'failed-only' not in manager.reported_models


class TestModelRemovalEdgeCases:
    """Tests for edge cases in model removal."""

    def test_removal_with_no_local_path(self, manager, mock_ipc_client):
        """Removal proceeds even if model has no local_path metadata."""
        manager.reported_models = {
            'no-path-model': {
                'status': 'ready',
                'model_metadata': {
                    'model_name': 'no_path_model',
                }
            },
            'other-model': {
                'status': 'ready',
                'model_metadata': {
                    'model_name': 'other_model',
                    'local_path': '/other/path',
                }
            },
        }

        manager._handle_model_removal('no-path-model')

        assert 'no-path-model' not in manager.reported_models

    def test_removal_with_nonexistent_path(self, manager, mock_ipc_client):
        """Removal proceeds even if local_path does not exist on disk."""
        manager.reported_models = {
            'ghost-model': {
                'status': 'ready',
                'model_metadata': {
                    'model_name': 'ghost_model',
                    'local_path': '/nonexistent/path/model',
                }
            },
            'other-model': {
                'status': 'ready',
                'model_metadata': {
                    'model_name': 'other_model',
                    'local_path': '/other/path',
                }
            },
        }

        manager._handle_model_removal('ghost-model')

        assert 'ghost-model' not in manager.reported_models

    def test_removal_of_model_without_metadata(self, manager, mock_ipc_client):
        """Removal proceeds even if model entry has no model_metadata."""
        manager.reported_models = {
            'bare-model': {
                'status': 'installing',
            },
            'other-model': {
                'status': 'ready',
                'model_metadata': {
                    'model_name': 'other_model',
                    'local_path': '/other/path',
                }
            },
        }

        manager._handle_model_removal('bare-model')

        assert 'bare-model' not in manager.reported_models

    def test_removal_of_model_not_in_reported(self, manager, mock_ipc_client):
        """Removal of a model not in reported_models is a no-op (no crash)."""
        manager.reported_models = {
            'existing-model': {
                'status': 'ready',
                'model_metadata': {
                    'model_name': 'existing_model',
                    'local_path': '/some/path',
                }
            },
        }

        # Should not raise
        manager._handle_model_removal('nonexistent-model')

        # Existing model should be unaffected
        assert 'existing-model' in manager.reported_models


class TestRegenerateOVMSConfig:
    """Tests for the _regenerate_ovms_config helper method."""

    def test_writes_all_ready_models(self, manager, temp_dirs):
        """Config includes all models with status ready."""
        manager.reported_models = {
            'model-a': {
                'status': 'ready',
                'model_metadata': {
                    'model_name': 'model_a',
                    'local_path': '/path/to/model-a',
                }
            },
            'model-b': {
                'status': 'ready',
                'model_metadata': {
                    'model_name': 'model_b',
                    'local_path': '/path/to/model-b/',
                }
            },
        }

        manager._regenerate_ovms_config()

        config_path = os.path.join(temp_dirs['config_dir'], 'models_config.json')
        with open(config_path, 'r') as f:
            config = json.load(f)

        assert len(config['model_config_list']) == 2
        names = {entry['config']['name'] for entry in config['model_config_list']}
        assert names == {'model_a', 'model_b'}

    def test_excludes_non_ready_models(self, manager, temp_dirs):
        """Config excludes models that are not in ready status."""
        manager.reported_models = {
            'ready-model': {
                'status': 'ready',
                'model_metadata': {
                    'model_name': 'ready_model',
                    'local_path': '/path/to/ready',
                }
            },
            'installing-model': {
                'status': 'installing',
                'model_metadata': {
                    'model_name': 'installing_model',
                    'local_path': '/path/to/installing',
                }
            },
            'failed-model': {
                'status': 'failed',
                'reason': 'error',
            },
        }

        manager._regenerate_ovms_config()

        config_path = os.path.join(temp_dirs['config_dir'], 'models_config.json')
        with open(config_path, 'r') as f:
            config = json.load(f)

        assert len(config['model_config_list']) == 1
        assert config['model_config_list'][0]['config']['name'] == 'ready_model'

    def test_writes_empty_config_when_no_ready_models(self, manager, temp_dirs):
        """Config is empty when no models are ready."""
        manager.reported_models = {}

        manager._regenerate_ovms_config()

        config_path = os.path.join(temp_dirs['config_dir'], 'models_config.json')
        with open(config_path, 'r') as f:
            config = json.load(f)

        assert config['model_config_list'] == []

    def test_preserves_local_path_as_base_path(self, manager, temp_dirs):
        """base_path in config matches the local_path from model metadata."""
        manager.reported_models = {
            'model-x': {
                'status': 'ready',
                'model_metadata': {
                    'model_name': 'model_x',
                    'local_path': '/path/to/model-x/',
                }
            },
        }

        manager._regenerate_ovms_config()

        config_path = os.path.join(temp_dirs['config_dir'], 'models_config.json')
        with open(config_path, 'r') as f:
            config = json.load(f)

        assert config['model_config_list'][0]['config']['base_path'] == '/path/to/model-x/'
