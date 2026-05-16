"""Integration tests for ModelManagerCore full flow.

Tests the end-to-end flow from shadow delta reception through model installation
to OVMS config generation and shadow reported state updates.

Covers:
- Shadow delta -> snap install -> OVMS config update -> reported state
- Shadow delta -> S3 download -> OVMS config update -> reported state
- Multiple model installs in a single delta
- Error recovery (failed model retry on new delta)
- Model removal with OVMS config regeneration
"""

import sys
import os
import json
import tempfile
from unittest.mock import MagicMock, patch, mock_open

import pytest

# Add artifact path for imports
sys.path.insert(0, os.path.join(
    os.path.dirname(__file__), '..', 'greengrass-components', 'artifacts',
    'com.example.ModelManagerCore', '1.0.0'
))

# Add shared modules path
sys.path.insert(0, os.path.join(
    os.path.dirname(__file__), '..', 'greengrass-components', 'shared'
))

# Mock the awsiot module before importing model_manager_core
mock_clientv2 = MagicMock()
sys.modules['awsiot'] = MagicMock()
sys.modules['awsiot.greengrasscoreipc'] = MagicMock()
sys.modules['awsiot.greengrasscoreipc.clientv2'] = mock_clientv2


FASTER_RCNN_MANIFEST = {
    "model_id": "faster-rcnn",
    "model_name": "faster_rcnn",
    "version": "1.0.0",
    "input_name": "input_tensor",
    "output_names": ["detection_boxes", "detection_classes", "detection_scores", "num_detections"],
    "input_shape": [1, 255, 255, 3],
    "labels_file": "labels.txt"
}

EFFICIENTNET_MANIFEST = {
    "model_id": "efficientnet",
    "model_name": "efficientnet",
    "version": "1.0.0",
    "input_name": "input",
    "output_names": ["predictions"],
    "input_shape": [1, 224, 224, 3],
    "labels_file": "labels.txt"
}


@pytest.fixture
def mock_ipc_client():
    """Create a mock IPC client."""
    mock = MagicMock()
    mock.get_thing_shadow.side_effect = Exception("ResourceNotFoundException")
    return mock


@pytest.fixture
def temp_dirs(tmp_path):
    """Create temporary directories simulating the content interface mount point structure.

    With the content interface, the Greengrass snap mounts ovms-engine's directories
    at separate, independent paths:
    - SNAP_COMMON (models mount) -> ovms-engine's $SNAP_COMMON/models/
    - OVMS_CONFIG_DIR (config mount) -> ovms-engine's $SNAP_COMMON/config/
    - SNAP_COMPONENTS (read-only snap components path)

    These are independent mount points, so config_dir is NOT a subdirectory of snap_common.
    """
    snap_components = tmp_path / "snap-components"
    snap_common = tmp_path / "ovms-engine-models"
    config_dir = tmp_path / "ovms-engine-config"
    snap_components.mkdir()
    snap_common.mkdir()
    config_dir.mkdir()
    return {
        "snap_components": str(snap_components),
        "snap_common": str(snap_common),
        "config_dir": str(config_dir),
    }


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
        # Mock the snapd client to avoid real socket connections
        mgr.snapd = MagicMock()
        mgr.snapd.install_component = MagicMock(return_value={})
        mgr.snapd.remove_component = MagicMock(return_value={})
        yield mgr


def _make_delta_event(state_payload):
    """Create a mock shadow delta event with the given state payload."""
    event = MagicMock()
    event.message.payload = json.dumps({"state": state_payload}).encode('utf-8')
    return event


def _get_last_reported_models(mock_ipc_client):
    """Extract the last reported models from shadow update calls."""
    calls = mock_ipc_client.update_thing_shadow.call_args_list
    if not calls:
        return {}
    payload = json.loads(calls[-1].kwargs['payload'])
    return payload.get('state', {}).get('reported', {}).get('models', {})


def _read_ovms_config(config_dir):
    """Read and parse the OVMS config file."""
    config_path = os.path.join(config_dir, "models_config.json")
    if not os.path.exists(config_path):
        return None
    with open(config_path) as f:
        return json.load(f)


class TestFullSnapInstallFlow:
    """Integration: shadow delta -> snap install -> OVMS config -> reported state."""

    def test_snap_delta_to_ready_state(self, manager, mock_ipc_client, temp_dirs):
        """Full flow: delta with snap model -> install -> config written -> ready reported."""
        # Create the manifest file that snap install would produce
        model_dir = os.path.join(temp_dirs['snap_components'], 'model-faster-rcnn')
        os.makedirs(model_dir)
        with open(os.path.join(model_dir, 'manifest.json'), 'w') as f:
            json.dump(FASTER_RCNN_MANIFEST, f)

        event = _make_delta_event({
            'models': {'faster-rcnn': {'source': 'snap'}}
        })
        manager._on_shadow_delta(event)

        # Verify snapd install_component was called
        manager.snapd.install_component.assert_called_once_with(
            'ovms-engine', 'model-faster-rcnn', timeout=300,
        )

        # Verify OVMS config was written with the model
        config = _read_ovms_config(temp_dirs['config_dir'])
        assert config is not None
        assert len(config['model_config_list']) == 1
        assert config['model_config_list'][0]['config']['name'] == 'faster_rcnn'
        assert config['model_config_list'][0]['config']['base_path'] == model_dir

        # Verify reported state shows model as ready with metadata
        models = _get_last_reported_models(mock_ipc_client)
        assert models['faster-rcnn']['status'] == 'ready'
        assert models['faster-rcnn']['model_metadata']['model_name'] == 'faster_rcnn'
        assert models['faster-rcnn']['model_metadata']['local_path'] == model_dir

    def test_snap_install_failure_does_not_write_config(self, manager, mock_ipc_client, temp_dirs):
        """Failed snap install does not produce OVMS config entry."""
        from snapd_client import SnapdError
        manager.snapd.install_component.side_effect = SnapdError("snap not found")

        event = _make_delta_event({
            'models': {'bad-model': {'source': 'snap'}}
        })
        manager._on_shadow_delta(event)

        # OVMS config should not exist (no ready models)
        config = _read_ovms_config(temp_dirs['config_dir'])
        assert config is None

        # Reported state should show failed
        models = _get_last_reported_models(mock_ipc_client)
        assert models['bad-model']['status'] == 'failed'
        assert 'snap install failed' in models['bad-model']['reason']


class TestFullS3DownloadFlow:
    """Integration: shadow delta -> S3 download -> OVMS config -> reported state."""

    def test_s3_delta_to_ready_state(self, manager, mock_ipc_client, temp_dirs):
        """Full flow: delta with S3 model -> download -> config written -> ready reported."""
        mock_s3_client = MagicMock()
        mock_paginator = MagicMock()
        mock_s3_client.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [
            {
                "Contents": [
                    {"Key": "models/custom/1.0/model.bin"},
                    {"Key": "models/custom/1.0/manifest.json"},
                ]
            }
        ]

        custom_manifest = {
            "model_id": "custom-detector",
            "model_name": "custom_det",
            "version": "1.0.0",
            "input_name": "images",
            "output_names": ["boxes", "scores"],
            "input_shape": [1, 416, 416, 3],
            "labels_file": "labels.txt"
        }

        def fake_download(bucket, key, local_path):
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            if key.endswith("manifest.json"):
                with open(local_path, 'w') as f:
                    json.dump(custom_manifest, f)
            else:
                with open(local_path, 'w') as f:
                    f.write("model binary data")

        mock_s3_client.download_file.side_effect = fake_download

        with patch('model_manager_core.boto3') as patched_boto3:
            patched_boto3.client.return_value = mock_s3_client

            event = _make_delta_event({
                'models': {
                    'custom-detector': {
                        'source': 's3',
                        's3_uri': 's3://my-bucket/models/custom/1.0/'
                    }
                }
            })
            manager._on_shadow_delta(event)

        # Verify OVMS config was written
        config = _read_ovms_config(temp_dirs['config_dir'])
        assert config is not None
        assert len(config['model_config_list']) == 1
        assert config['model_config_list'][0]['config']['name'] == 'custom_det'

        # Verify reported state
        models = _get_last_reported_models(mock_ipc_client)
        assert models['custom-detector']['status'] == 'ready'
        assert models['custom-detector']['model_metadata']['model_name'] == 'custom_det'
        expected_path = os.path.join(temp_dirs['snap_common'], 'models', 'custom-detector')
        assert models['custom-detector']['model_metadata']['local_path'] == expected_path


class TestMultiModelInstallFlow:
    """Integration: multiple models installed from a single delta."""

    def test_two_snap_models_in_one_delta(self, manager, mock_ipc_client, temp_dirs):
        """Two snap models in one delta both get installed and appear in OVMS config."""
        # Create manifest files for both models
        for model_id, manifest in [('faster-rcnn', FASTER_RCNN_MANIFEST),
                                    ('efficientnet', EFFICIENTNET_MANIFEST)]:
            model_dir = os.path.join(temp_dirs['snap_components'], f'model-{model_id}')
            os.makedirs(model_dir)
            with open(os.path.join(model_dir, 'manifest.json'), 'w') as f:
                json.dump(manifest, f)

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout='', stderr='')

            event = _make_delta_event({
                'models': {
                    'faster-rcnn': {'source': 'snap'},
                    'efficientnet': {'source': 'snap'},
                }
            })
            manager._on_shadow_delta(event)

        # Both models should be in OVMS config
        config = _read_ovms_config(temp_dirs['config_dir'])
        assert config is not None
        assert len(config['model_config_list']) == 2
        names = {entry['config']['name'] for entry in config['model_config_list']}
        assert names == {'faster_rcnn', 'efficientnet'}

        # Both models should be reported as ready
        models = _get_last_reported_models(mock_ipc_client)
        assert models['faster-rcnn']['status'] == 'ready'
        assert models['efficientnet']['status'] == 'ready'

    def test_mixed_snap_and_s3_models(self, manager, mock_ipc_client, temp_dirs):
        """One snap model and one S3 model in the same delta both install correctly."""
        # Set up snap model
        snap_dir = os.path.join(temp_dirs['snap_components'], 'model-faster-rcnn')
        os.makedirs(snap_dir)
        with open(os.path.join(snap_dir, 'manifest.json'), 'w') as f:
            json.dump(FASTER_RCNN_MANIFEST, f)

        # Set up S3 mock
        mock_s3_client = MagicMock()
        mock_paginator = MagicMock()
        mock_s3_client.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [
            {"Contents": [{"Key": "models/ppe/1.0/manifest.json"}]}
        ]

        s3_manifest = {
            "model_id": "custom-ppe",
            "model_name": "ppe_detector",
            "version": "1.0.0",
            "input_name": "input",
            "output_names": ["detections"],
            "input_shape": [1, 300, 300, 3],
            "labels_file": "labels.txt"
        }

        def fake_download(bucket, key, local_path):
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            with open(local_path, 'w') as f:
                json.dump(s3_manifest, f)

        mock_s3_client.download_file.side_effect = fake_download

        with patch('subprocess.run') as mock_run, \
             patch('model_manager_core.boto3') as patched_boto3:
            mock_run.return_value = MagicMock(returncode=0, stdout='', stderr='')
            patched_boto3.client.return_value = mock_s3_client

            event = _make_delta_event({
                'models': {
                    'faster-rcnn': {'source': 'snap'},
                    'custom-ppe': {'source': 's3', 's3_uri': 's3://bucket/models/ppe/1.0/'},
                }
            })
            manager._on_shadow_delta(event)

        # Both models in OVMS config
        config = _read_ovms_config(temp_dirs['config_dir'])
        assert len(config['model_config_list']) == 2
        names = {entry['config']['name'] for entry in config['model_config_list']}
        assert 'faster_rcnn' in names
        assert 'ppe_detector' in names

    def test_partial_failure_only_ready_models_in_config(self, manager, mock_ipc_client, temp_dirs):
        """When one model fails and another succeeds, only the successful one is in config."""
        # Set up successful snap model
        snap_dir = os.path.join(temp_dirs['snap_components'], 'model-efficientnet')
        os.makedirs(snap_dir)
        with open(os.path.join(snap_dir, 'manifest.json'), 'w') as f:
            json.dump(EFFICIENTNET_MANIFEST, f)

        call_count = [0]

        def mock_subprocess_run(cmd, **kwargs):
            call_count[0] += 1
            result = MagicMock()
            if 'model-bad' in cmd[2]:
                result.returncode = 1
                result.stdout = ''
                result.stderr = 'snap not found'
            else:
                result.returncode = 0
                result.stdout = ''
                result.stderr = ''
            return result

        with patch('subprocess.run', side_effect=mock_subprocess_run):
            event = _make_delta_event({
                'models': {
                    'bad': {'source': 'snap'},
                    'efficientnet': {'source': 'snap'},
                }
            })
            manager._on_shadow_delta(event)

        # Only efficientnet should be in OVMS config
        config = _read_ovms_config(temp_dirs['config_dir'])
        assert len(config['model_config_list']) == 1
        assert config['model_config_list'][0]['config']['name'] == 'efficientnet'

        # Reported state should show both models with correct statuses
        models = _get_last_reported_models(mock_ipc_client)
        assert models['efficientnet']['status'] == 'ready'
        assert models['bad']['status'] == 'failed'


class TestErrorRecoveryFlow:
    """Integration: error recovery and retry behavior."""

    def test_failed_model_retried_on_new_delta(self, manager, mock_ipc_client, temp_dirs):
        """A previously failed model is retried when it appears in a new delta."""
        # First attempt: snap install fails
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1, stdout='', stderr='network error'
            )
            event = _make_delta_event({
                'models': {'faster-rcnn': {'source': 'snap'}}
            })
            manager._on_shadow_delta(event)

        assert manager.reported_models['faster-rcnn']['status'] == 'failed'

        # Second attempt: snap install succeeds
        snap_dir = os.path.join(temp_dirs['snap_components'], 'model-faster-rcnn')
        os.makedirs(snap_dir)
        with open(os.path.join(snap_dir, 'manifest.json'), 'w') as f:
            json.dump(FASTER_RCNN_MANIFEST, f)

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout='', stderr='')
            event = _make_delta_event({
                'models': {'faster-rcnn': {'source': 'snap'}}
            })
            manager._on_shadow_delta(event)

        assert manager.reported_models['faster-rcnn']['status'] == 'ready'

        # OVMS config should now have the model
        config = _read_ovms_config(temp_dirs['config_dir'])
        assert len(config['model_config_list']) == 1
        assert config['model_config_list'][0]['config']['name'] == 'faster_rcnn'

    def test_ready_model_not_reinstalled_on_repeat_delta(self, manager, mock_ipc_client, temp_dirs):
        """A model already in ready state is not reinstalled on a repeat delta."""
        # Set up model as already ready
        snap_dir = os.path.join(temp_dirs['snap_components'], 'model-faster-rcnn')
        os.makedirs(snap_dir)
        manager.reported_models = {
            'faster-rcnn': {
                'status': 'ready',
                'model_metadata': {
                    'model_name': 'faster_rcnn',
                    'local_path': snap_dir,
                }
            }
        }

        with patch('subprocess.run') as mock_run:
            event = _make_delta_event({
                'models': {'faster-rcnn': {'source': 'snap'}}
            })
            manager._on_shadow_delta(event)

            # snap install should NOT be called
            mock_run.assert_not_called()


class TestModelRemovalIntegration:
    """Integration: model removal with OVMS config update."""

    def test_remove_model_updates_config_and_state(self, manager, mock_ipc_client, temp_dirs):
        """Removing a model from desired state removes it from config and reported state."""
        # Set up two ready models
        for model_id, manifest in [('faster-rcnn', FASTER_RCNN_MANIFEST),
                                    ('efficientnet', EFFICIENTNET_MANIFEST)]:
            model_dir = os.path.join(temp_dirs['snap_components'], f'model-{model_id}')
            os.makedirs(model_dir)
            with open(os.path.join(model_dir, 'manifest.json'), 'w') as f:
                json.dump(manifest, f)

        manager.reported_models = {
            'faster-rcnn': {
                'status': 'ready',
                'model_metadata': {
                    'model_name': 'faster_rcnn',
                    'local_path': os.path.join(temp_dirs['snap_components'], 'model-faster-rcnn'),
                }
            },
            'efficientnet': {
                'status': 'ready',
                'model_metadata': {
                    'model_name': 'efficientnet',
                    'local_path': os.path.join(temp_dirs['snap_components'], 'model-efficientnet'),
                }
            },
        }

        # Delta with only efficientnet means faster-rcnn should be removed
        event = _make_delta_event({
            'models': {'efficientnet': {'source': 'snap'}}
        })
        manager._on_shadow_delta(event)

        # OVMS config should only have efficientnet
        config = _read_ovms_config(temp_dirs['config_dir'])
        assert len(config['model_config_list']) == 1
        assert config['model_config_list'][0]['config']['name'] == 'efficientnet'

        # Reported state should only have efficientnet
        assert 'faster-rcnn' not in manager.reported_models
        assert 'efficientnet' in manager.reported_models

        # Local files for faster-rcnn should be deleted
        removed_dir = os.path.join(temp_dirs['snap_components'], 'model-faster-rcnn')
        assert not os.path.exists(removed_dir)

    def test_cannot_remove_last_model(self, manager, mock_ipc_client, temp_dirs):
        """Attempting to remove the last ready model is refused."""
        model_dir = os.path.join(temp_dirs['snap_components'], 'model-faster-rcnn')
        os.makedirs(model_dir)
        with open(os.path.join(model_dir, 'manifest.json'), 'w') as f:
            json.dump(FASTER_RCNN_MANIFEST, f)

        manager.reported_models = {
            'faster-rcnn': {
                'status': 'ready',
                'model_metadata': {
                    'model_name': 'faster_rcnn',
                    'local_path': model_dir,
                }
            },
        }

        # Delta with empty models means remove faster-rcnn
        event = _make_delta_event({'models': {}})
        manager._on_shadow_delta(event)

        # Model should still be present (removal refused)
        assert 'faster-rcnn' in manager.reported_models
        assert os.path.exists(model_dir)

    def test_add_and_remove_in_same_delta_with_two_existing(self, manager, mock_ipc_client, temp_dirs):
        """A delta that adds one model and removes another handles both correctly."""
        # Set up two existing models (so removal is allowed per Req 8.3)
        old_dir = os.path.join(temp_dirs['snap_components'], 'model-old-model')
        os.makedirs(old_dir)
        with open(os.path.join(old_dir, 'manifest.json'), 'w') as f:
            json.dump({"model_name": "old_model"}, f)

        keep_dir = os.path.join(temp_dirs['snap_components'], 'model-keep-model')
        os.makedirs(keep_dir)

        # Set up new model manifest
        new_dir = os.path.join(temp_dirs['snap_components'], 'model-new-model')
        os.makedirs(new_dir)
        with open(os.path.join(new_dir, 'manifest.json'), 'w') as f:
            json.dump(EFFICIENTNET_MANIFEST, f)

        manager.reported_models = {
            'old-model': {
                'status': 'ready',
                'model_metadata': {
                    'model_name': 'old_model',
                    'local_path': old_dir,
                }
            },
            'keep-model': {
                'status': 'ready',
                'model_metadata': {
                    'model_name': 'keep_model',
                    'local_path': keep_dir,
                }
            },
        }

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout='', stderr='')

            # Delta: keep keep-model, add new-model, remove old-model
            event = _make_delta_event({
                'models': {
                    'keep-model': {'source': 'snap'},
                    'new-model': {'source': 'snap'},
                }
            })
            manager._on_shadow_delta(event)

        # old-model removed, new-model added, keep-model stays
        assert 'old-model' not in manager.reported_models
        assert 'new-model' in manager.reported_models
        assert 'keep-model' in manager.reported_models
        assert manager.reported_models['new-model']['status'] == 'ready'

        # OVMS config should have keep-model and new-model
        config = _read_ovms_config(temp_dirs['config_dir'])
        assert len(config['model_config_list']) == 2
        names = {entry['config']['name'] for entry in config['model_config_list']}
        assert 'keep_model' in names
        assert 'efficientnet' in names

    def test_last_model_protected_during_replacement(self, manager, mock_ipc_client, temp_dirs):
        """When replacing the only model, removal is refused (Req 8.3) but new model installs."""
        # Set up existing model as the only one
        old_dir = os.path.join(temp_dirs['snap_components'], 'model-old-model')
        os.makedirs(old_dir)

        new_dir = os.path.join(temp_dirs['snap_components'], 'model-new-model')
        os.makedirs(new_dir)
        with open(os.path.join(new_dir, 'manifest.json'), 'w') as f:
            json.dump(EFFICIENTNET_MANIFEST, f)

        manager.reported_models = {
            'old-model': {
                'status': 'ready',
                'model_metadata': {
                    'model_name': 'old_model',
                    'local_path': old_dir,
                }
            },
        }

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout='', stderr='')

            event = _make_delta_event({
                'models': {'new-model': {'source': 'snap'}}
            })
            manager._on_shadow_delta(event)

        # old-model is protected (last model rule), new-model is added
        assert 'old-model' in manager.reported_models
        assert 'new-model' in manager.reported_models
        assert manager.reported_models['new-model']['status'] == 'ready'


class TestContentInterfacePathSeparation:
    """Verify that OVMS_CONFIG_DIR and SNAP_COMMON are independent mount points.

    With the content interface, the Greengrass snap mounts ovms-engine's directories
    at separate paths:
    - OVMS_CONFIG_DIR = /var/snap/aws-iot-greengrass/current/ovms-engine-config
    - SNAP_COMMON = /var/snap/aws-iot-greengrass/current/ovms-engine-models

    These are NOT nested — config is not a subdirectory of SNAP_COMMON.
    This test class verifies that ModelManagerCore correctly writes to each
    independent path without assuming any parent-child relationship between them.
    """

    def test_config_and_models_written_to_separate_directories(
        self, mock_ipc_client, tmp_path
    ):
        """OVMS config and S3 model files are written to independent directories."""
        # Simulate content interface mount points as completely separate paths
        models_mount = tmp_path / "var" / "snap" / "aws-iot-greengrass" / "current" / "ovms-engine-models"
        config_mount = tmp_path / "var" / "snap" / "aws-iot-greengrass" / "current" / "ovms-engine-config"
        snap_components = tmp_path / "snap" / "ovms-engine" / "current" / "components"
        models_mount.mkdir(parents=True)
        config_mount.mkdir(parents=True)
        snap_components.mkdir(parents=True)

        mock_clientv2.GreengrassCoreIPCClientV2.return_value = mock_ipc_client

        with patch.dict(os.environ, {
            'AWS_IOT_THING_NAME': 'test-thing',
            'SNAP_COMPONENTS': str(snap_components),
            'SNAP_COMMON': str(models_mount),
            'OVMS_CONFIG_DIR': str(config_mount),
        }):
            from model_manager_core import ModelManagerCore
            mgr = ModelManagerCore()
            mgr.ipc_client = mock_ipc_client

        # Verify the paths are truly independent (no parent-child relationship)
        assert not str(config_mount).startswith(str(models_mount))
        assert not str(models_mount).startswith(str(config_mount))

        # Set up S3 mock to download a model to SNAP_COMMON/models/
        mock_s3_client = MagicMock()
        mock_paginator = MagicMock()
        mock_s3_client.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [
            {"Contents": [
                {"Key": "models/custom/1.0/manifest.json"},
                {"Key": "models/custom/1.0/model.bin"},
            ]}
        ]

        custom_manifest = {
            "model_id": "custom-model",
            "model_name": "custom_model",
            "version": "1.0.0",
            "input_name": "input",
            "output_names": ["output"],
            "input_shape": [1, 224, 224, 3],
            "labels_file": "labels.txt"
        }

        def fake_download(bucket, key, local_path):
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            if key.endswith("manifest.json"):
                with open(local_path, 'w') as f:
                    json.dump(custom_manifest, f)
            else:
                with open(local_path, 'w') as f:
                    f.write("fake model binary")

        mock_s3_client.download_file.side_effect = fake_download

        with patch('model_manager_core.boto3') as patched_boto3:
            patched_boto3.client.return_value = mock_s3_client

            event = _make_delta_event({
                'models': {
                    'custom-model': {
                        'source': 's3',
                        's3_uri': 's3://my-bucket/models/custom/1.0/'
                    }
                }
            })
            mgr._on_shadow_delta(event)

        # Verify model files were written under SNAP_COMMON (models mount)
        model_dir = models_mount / "models" / "custom-model"
        assert model_dir.exists()
        assert (model_dir / "manifest.json").exists()
        assert (model_dir / "model.bin").exists()

        # Verify OVMS config was written to OVMS_CONFIG_DIR (config mount)
        config_file = config_mount / "models_config.json"
        assert config_file.exists()

        # Verify config file is NOT inside the models mount
        assert not str(config_file).startswith(str(models_mount))

        # Verify model files are NOT inside the config mount
        assert not str(model_dir).startswith(str(config_mount))

        # Verify the config content references the correct model path
        with open(config_file) as f:
            config = json.load(f)
        assert len(config['model_config_list']) == 1
        assert config['model_config_list'][0]['config']['name'] == 'custom_model'
        assert config['model_config_list'][0]['config']['base_path'] == str(model_dir)

    def test_snap_model_config_written_to_separate_config_mount(
        self, mock_ipc_client, tmp_path
    ):
        """Snap model install writes OVMS config to config mount, not models mount."""
        # Simulate content interface mount points
        models_mount = tmp_path / "ovms-engine-models"
        config_mount = tmp_path / "ovms-engine-config"
        snap_components = tmp_path / "snap-components"
        models_mount.mkdir()
        config_mount.mkdir()
        snap_components.mkdir()

        # Create snap model manifest
        model_dir = snap_components / "model-faster-rcnn"
        model_dir.mkdir()
        with open(model_dir / "manifest.json", 'w') as f:
            json.dump(FASTER_RCNN_MANIFEST, f)

        mock_clientv2.GreengrassCoreIPCClientV2.return_value = mock_ipc_client

        with patch.dict(os.environ, {
            'AWS_IOT_THING_NAME': 'test-thing',
            'SNAP_COMPONENTS': str(snap_components),
            'SNAP_COMMON': str(models_mount),
            'OVMS_CONFIG_DIR': str(config_mount),
        }):
            from model_manager_core import ModelManagerCore
            mgr = ModelManagerCore()
            mgr.ipc_client = mock_ipc_client

        mgr.snapd = MagicMock()
        mgr.snapd.install_component = MagicMock(return_value={})

        event = _make_delta_event({
            'models': {'faster-rcnn': {'source': 'snap'}}
        })
        mgr._on_shadow_delta(event)

        # OVMS config must be in the config mount
        config_file = config_mount / "models_config.json"
        assert config_file.exists()

        # Config must NOT be in the models mount
        models_config_wrong_path = models_mount / "models_config.json"
        assert not models_config_wrong_path.exists()
        models_config_nested = models_mount / "config" / "models_config.json"
        assert not models_config_nested.exists()

        # Verify config content
        with open(config_file) as f:
            config = json.load(f)
        assert len(config['model_config_list']) == 1
        assert config['model_config_list'][0]['config']['name'] == 'faster_rcnn'

    def test_environment_variables_resolve_to_independent_paths(
        self, mock_ipc_client, tmp_path
    ):
        """ModelManagerCore correctly reads SNAP_COMMON and OVMS_CONFIG_DIR as independent paths."""
        models_mount = tmp_path / "mount-a"
        config_mount = tmp_path / "mount-b"
        snap_components = tmp_path / "components"
        models_mount.mkdir()
        config_mount.mkdir()
        snap_components.mkdir()

        mock_clientv2.GreengrassCoreIPCClientV2.return_value = mock_ipc_client

        with patch.dict(os.environ, {
            'AWS_IOT_THING_NAME': 'test-thing',
            'SNAP_COMPONENTS': str(snap_components),
            'SNAP_COMMON': str(models_mount),
            'OVMS_CONFIG_DIR': str(config_mount),
        }):
            from model_manager_core import ModelManagerCore
            mgr = ModelManagerCore()
            mgr.ipc_client = mock_ipc_client

        # Verify the manager resolved paths independently
        assert mgr.snap_common_path == str(models_mount)
        assert mgr.ovms_config_dir == str(config_mount)
        assert mgr.snap_components_path == str(snap_components)

        # Verify no path is a prefix of another
        assert not mgr.ovms_config_dir.startswith(mgr.snap_common_path)
        assert not mgr.snap_common_path.startswith(mgr.ovms_config_dir)
