"""Unit tests for ModelManagerCore snap model installation.

Tests the _install_snap_model method which runs snap install, reads the
manifest.json, and reports model status via the shadow.

Requirements: 2.1, 2.2, 2.3, 2.4
"""

import sys
import os
import json
import subprocess
from unittest.mock import MagicMock, patch, mock_open

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
def manager(mock_ipc_client):
    """Create a ModelManagerCore instance with mocked IPC."""
    mock_clientv2.GreengrassCoreIPCClientV2.return_value = mock_ipc_client

    with patch.dict(os.environ, {
        'AWS_IOT_THING_NAME': 'test-thing',
        'SNAP_COMPONENTS': '/snap/ovms-engine/components/current',
        'SNAP_COMMON': '/var/snap/ovms-engine/common',
        'OVMS_CONFIG_DIR': '/var/snap/ovms-engine/common/config',
    }):
        from model_manager_core import ModelManagerCore
        mgr = ModelManagerCore()
        mgr.ipc_client = mock_ipc_client
        # Mock the snapd client to avoid real socket connections
        mgr.snapd = MagicMock()
        mgr.snapd.install_component = MagicMock(return_value={})
        mgr.snapd.remove_component = MagicMock(return_value={})
        yield mgr


SAMPLE_MANIFEST = {
    "model_id": "faster-rcnn",
    "model_name": "faster_rcnn",
    "version": "1.0.0",
    "input_name": "input_tensor",
    "output_names": ["detection_boxes", "detection_classes", "detection_scores", "num_detections"],
    "input_shape": [1, 255, 255, 3],
    "labels_file": "labels.txt"
}


class TestSnapInstallCommand:
    """Tests for the snapd REST API snap component installation."""

    def test_runs_snap_install_with_correct_component_name(self, manager):
        """Snapd install_component is called with ovms-engine and model-{model_id}."""
        with patch('builtins.open', mock_open(read_data=json.dumps(SAMPLE_MANIFEST))):
            manager._install_snap_model('faster-rcnn')

            manager.snapd.install_component.assert_called_once_with(
                'ovms-engine', 'model-faster-rcnn', timeout=300,
            )

    def test_reports_failed_on_snapd_error(self, manager, mock_ipc_client):
        """Reports failed status when snapd install_component raises SnapdError."""
        from snapd_client import SnapdError
        manager.snapd.install_component.side_effect = SnapdError(
            'snap "ovms-engine+model-bad" not found'
        )
        manager._install_snap_model('bad')

        update_calls = mock_ipc_client.update_thing_shadow.call_args_list
        payload = json.loads(update_calls[-1].kwargs['payload'])
        models = payload['state']['reported']['models']
        assert models['bad']['status'] == 'failed'
        assert 'snap install failed' in models['bad']['reason']
        assert 'not found' in models['bad']['reason']

    def test_reports_failed_on_timeout(self, manager, mock_ipc_client):
        """Reports failed status when snapd operation times out."""
        from snapd_client import SnapdError
        manager.snapd.install_component.side_effect = SnapdError(
            'Snap operation timed out after 300s (change 123)'
        )
        manager._install_snap_model('slow-model')

        update_calls = mock_ipc_client.update_thing_shadow.call_args_list
        payload = json.loads(update_calls[-1].kwargs['payload'])
        models = payload['state']['reported']['models']
        assert models['slow-model']['status'] == 'failed'
        assert 'snap install failed' in models['slow-model']['reason']

    def test_reports_failed_on_connection_error(self, manager, mock_ipc_client):
        """Reports failed status when snapd socket is unavailable."""
        from snapd_client import SnapdError
        manager.snapd.install_component.side_effect = SnapdError(
            "No such file or directory: '/run/snapd.socket'"
        )
        manager._install_snap_model('no-snap')

        update_calls = mock_ipc_client.update_thing_shadow.call_args_list
        payload = json.loads(update_calls[-1].kwargs['payload'])
        models = payload['state']['reported']['models']
        assert models['no-snap']['status'] == 'failed'
        assert 'snap install failed' in models['no-snap']['reason']

    def test_error_message_includes_snapd_error_detail(self, manager, mock_ipc_client):
        """Error reason includes the specific SnapdError message."""
        from snapd_client import SnapdError
        manager.snapd.install_component.side_effect = SnapdError(
            'specific error from snapd'
        )
        manager._install_snap_model('err-model')

        update_calls = mock_ipc_client.update_thing_shadow.call_args_list
        payload = json.loads(update_calls[-1].kwargs['payload'])
        models = payload['state']['reported']['models']
        assert 'specific error from snapd' in models['err-model']['reason']


class TestManifestReading:
    """Tests for reading manifest.json after successful snap install."""

    def test_reads_manifest_from_correct_path(self, manager):
        """Reads manifest.json from $SNAP_COMPONENTS/model-{model_id}/manifest.json."""
        with patch('builtins.open', mock_open(read_data=json.dumps(SAMPLE_MANIFEST))) as m_open:
            manager._install_snap_model('faster-rcnn')

            m_open.assert_called_once_with(
                '/snap/ovms-engine/components/current/model-faster-rcnn/manifest.json',
                'r'
            )

    def test_reports_failed_when_manifest_not_found(self, manager, mock_ipc_client):
        """Reports failed status when manifest.json does not exist."""
        with patch('builtins.open', side_effect=FileNotFoundError("No such file")):
            manager._install_snap_model('no-manifest')

        update_calls = mock_ipc_client.update_thing_shadow.call_args_list
        payload = json.loads(update_calls[-1].kwargs['payload'])
        models = payload['state']['reported']['models']
        assert models['no-manifest']['status'] == 'failed'
        assert 'manifest.json not found' in models['no-manifest']['reason']

    def test_reports_failed_when_manifest_invalid_json(self, manager, mock_ipc_client):
        """Reports failed status when manifest.json contains invalid JSON."""
        with patch('builtins.open', mock_open(read_data='not valid json {')):
            manager._install_snap_model('bad-json')

        update_calls = mock_ipc_client.update_thing_shadow.call_args_list
        payload = json.loads(update_calls[-1].kwargs['payload'])
        models = payload['state']['reported']['models']
        assert models['bad-json']['status'] == 'failed'
        assert 'Invalid manifest.json' in models['bad-json']['reason']


class TestSuccessfulInstallation:
    """Tests for successful snap model installation and status reporting."""

    def test_reports_ready_with_metadata_on_success(self, manager, mock_ipc_client):
        """Reports ready status with model metadata from manifest on success."""
        with patch('builtins.open', mock_open(read_data=json.dumps(SAMPLE_MANIFEST))):
            manager._install_snap_model('faster-rcnn')

        update_calls = mock_ipc_client.update_thing_shadow.call_args_list
        payload = json.loads(update_calls[-1].kwargs['payload'])
        models = payload['state']['reported']['models']
        assert models['faster-rcnn']['status'] == 'ready'

        metadata = models['faster-rcnn']['model_metadata']
        assert metadata['model_name'] == 'faster_rcnn'
        assert metadata['input_name'] == 'input_tensor'
        assert metadata['output_names'] == [
            'detection_boxes', 'detection_classes', 'detection_scores', 'num_detections'
        ]
        assert metadata['input_shape'] == [1, 255, 255, 3]
        assert metadata['labels_file'] == 'labels.txt'

    def test_metadata_includes_local_path(self, manager, mock_ipc_client):
        """Model metadata includes the local_path to the installed component."""
        with patch('builtins.open', mock_open(read_data=json.dumps(SAMPLE_MANIFEST))):
            manager._install_snap_model('faster-rcnn')

        update_calls = mock_ipc_client.update_thing_shadow.call_args_list
        payload = json.loads(update_calls[-1].kwargs['payload'])
        metadata = payload['state']['reported']['models']['faster-rcnn']['model_metadata']
        assert metadata['local_path'] == '/snap/ovms-engine/components/current/model-faster-rcnn'

    def test_metadata_includes_version(self, manager, mock_ipc_client):
        """Model metadata includes the version from manifest."""
        with patch('builtins.open', mock_open(read_data=json.dumps(SAMPLE_MANIFEST))):
            manager._install_snap_model('faster-rcnn')

        update_calls = mock_ipc_client.update_thing_shadow.call_args_list
        payload = json.loads(update_calls[-1].kwargs['payload'])
        metadata = payload['state']['reported']['models']['faster-rcnn']['model_metadata']
        assert metadata['version'] == '1.0.0'

    def test_works_with_efficientnet_manifest(self, manager, mock_ipc_client):
        """Correctly handles efficientnet model manifest."""
        efficientnet_manifest = {
            "model_id": "efficientnet",
            "model_name": "efficientnet",
            "version": "1.0.0",
            "input_name": "input",
            "output_names": ["predictions"],
            "input_shape": [1, 224, 224, 3],
            "labels_file": "labels.txt"
        }

        with patch('builtins.open', mock_open(read_data=json.dumps(efficientnet_manifest))):
            manager._install_snap_model('efficientnet')

        update_calls = mock_ipc_client.update_thing_shadow.call_args_list
        payload = json.loads(update_calls[-1].kwargs['payload'])
        metadata = payload['state']['reported']['models']['efficientnet']['model_metadata']
        assert metadata['model_name'] == 'efficientnet'
        assert metadata['input_name'] == 'input'
        assert metadata['output_names'] == ['predictions']
        assert metadata['input_shape'] == [1, 224, 224, 3]
        assert metadata['local_path'] == '/snap/ovms-engine/components/current/model-efficientnet'
