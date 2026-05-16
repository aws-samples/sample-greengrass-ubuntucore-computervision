"""Unit tests for ModelManagerCore model switch execution (task 7.2).

Tests the _execute_model_switch method including:
- OVMS config backup and write
- gRPC model status polling
- Success path: update reported state and clear desired
- Failure/timeout path: revert config, set failed status, publish error event

Requirements: 5.2, 5.3, 5.4
"""

import sys
import os
import json
import tempfile
import shutil
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

import pytest

# Add the shared module and artifact paths
sys.path.insert(0, os.path.join(
    os.path.dirname(__file__), '..', 'greengrass-components', 'shared'
))
sys.path.insert(0, os.path.join(
    os.path.dirname(__file__), '..', 'greengrass-components', 'shared', 'models'
))
sys.path.insert(0, os.path.join(
    os.path.dirname(__file__), '..', 'greengrass-components', 'artifacts',
    'com.example.ModelManagerCore', '1.0.0'
))

# Mock the awsiot and boto3 modules before importing model_manager_core
mock_clientv2 = MagicMock()
sys.modules['awsiot'] = MagicMock()
sys.modules['awsiot.greengrasscoreipc'] = MagicMock()
sys.modules['awsiot.greengrasscoreipc.clientv2'] = mock_clientv2
sys.modules['boto3'] = MagicMock()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_dirs():
    """Create temporary directories simulating snap filesystem layout."""
    base_dir = tempfile.mkdtemp()
    snap_common = os.path.join(base_dir, 'snap_common')
    snap_components = os.path.join(base_dir, 'snap_components')
    config_dir = os.path.join(snap_common, 'config')
    custom_models = os.path.join(snap_common, 'models')

    os.makedirs(config_dir)
    os.makedirs(snap_components)
    os.makedirs(custom_models)

    yield {
        'base_dir': base_dir,
        'snap_common': snap_common,
        'snap_components': snap_components,
        'config_dir': config_dir,
        'custom_models': custom_models,
    }

    shutil.rmtree(base_dir)


@pytest.fixture
def model_dirs(temp_dirs):
    """Create model directories with valid model files and manifests."""
    # Create faster_rcnn model (current active)
    faster_rcnn_dir = os.path.join(temp_dirs['snap_components'], 'model-faster-rcnn')
    os.makedirs(faster_rcnn_dir)
    with open(os.path.join(faster_rcnn_dir, 'model.xml'), 'w') as f:
        f.write('<model/>')
    with open(os.path.join(faster_rcnn_dir, 'model.bin'), 'wb') as f:
        f.write(b'\x00' * 100)
    with open(os.path.join(faster_rcnn_dir, 'labels.txt'), 'w') as f:
        f.write('person\ncar\nbicycle\n')
    manifest_rcnn = {
        "model_id": "faster_rcnn",
        "model_name": "Faster R-CNN ResNet50",
        "version": "1.0.0",
        "description": "General-purpose object detection model",
        "input_name": "input_tensor",
        "output_names": ["detection_boxes", "detection_classes",
                         "detection_scores", "num_detections"],
        "input_shape": [1, 255, 255, 3],
        "labels_file": "labels.txt",
        "size_bytes": 134217728,
        "compatible_engines": ["CPU", "GPU", "NPU"]
    }
    with open(os.path.join(faster_rcnn_dir, 'manifest.json'), 'w') as f:
        json.dump(manifest_rcnn, f)

    # Create efficientnet model (target for switch)
    efficientnet_dir = os.path.join(temp_dirs['snap_components'], 'model-efficientnet')
    os.makedirs(efficientnet_dir)
    with open(os.path.join(efficientnet_dir, 'model.xml'), 'w') as f:
        f.write('<model/>')
    with open(os.path.join(efficientnet_dir, 'model.bin'), 'wb') as f:
        f.write(b'\x00' * 50)
    with open(os.path.join(efficientnet_dir, 'labels.txt'), 'w') as f:
        f.write('cat\ndog\nbird\n')
    manifest_eff = {
        "model_id": "efficientnet",
        "model_name": "EfficientNet B0",
        "version": "1.2.0",
        "description": "Image classification model",
        "input_name": "input_image",
        "output_names": ["predictions"],
        "input_shape": [1, 224, 224, 3],
        "labels_file": "labels.txt",
        "size_bytes": 20971520,
        "compatible_engines": ["CPU", "GPU"]
    }
    with open(os.path.join(efficientnet_dir, 'manifest.json'), 'w') as f:
        json.dump(manifest_eff, f)

    return {
        'faster_rcnn': faster_rcnn_dir,
        'efficientnet': efficientnet_dir,
    }


@pytest.fixture
def manager(temp_dirs, model_dirs):
    """Create a ModelManagerCore instance with mocked IPC client."""
    with patch.dict(os.environ, {
        'AWS_IOT_THING_NAME': 'test-thing',
        'SNAP_COMPONENTS': temp_dirs['snap_components'],
        'SNAP_COMMON': temp_dirs['snap_common'],
        'OVMS_CONFIG_DIR': temp_dirs['config_dir'],
        'OVMS_GRPC_URL': 'localhost:9000',
    }):
        # Force reimport to pick up the latest code
        if 'model_manager_core' in sys.modules:
            del sys.modules['model_manager_core']
        mock_clientv2.GreengrassCoreIPCClientV2 = MagicMock
        from model_manager_core import ModelManagerCore
        mgr = ModelManagerCore()
        mgr.ipc_client = MagicMock()
        return mgr


@pytest.fixture
def reported_state(model_dirs):
    """Build a typical reported state with faster_rcnn as active model."""
    return {
        'active_model': 'faster_rcnn',
        'engine': 'gpu',
        'models': {
            'faster_rcnn': {
                'model_id': 'faster_rcnn',
                'model_name': 'Faster R-CNN ResNet50',
                'version': '1.0.0',
                'local_path': model_dirs['faster_rcnn'] + '/',
                'size_bytes': 134217728,
                'last_updated': '2025-01-15T08:00:00Z',
                'status': 'ready',
                'source': 'snap',
            },
            'efficientnet': {
                'model_id': 'efficientnet',
                'model_name': 'EfficientNet B0',
                'version': '1.2.0',
                'local_path': model_dirs['efficientnet'] + '/',
                'size_bytes': 20971520,
                'last_updated': '2025-01-15T09:30:00Z',
                'status': 'ready',
                'source': 'snap',
            },
        },
        'model_metadata': {
            'input_name': 'input_tensor',
            'output_names': ['detection_boxes', 'detection_classes',
                             'detection_scores', 'num_detections'],
            'input_shape': [1, 255, 255, 3],
            'labels_file': 'labels.txt',
        },
    }


# ---------------------------------------------------------------------------
# Tests: Successful model switch
# ---------------------------------------------------------------------------

class TestModelSwitchSuccess:
    """Tests for successful model switch flow."""

    def test_successful_switch_updates_ovms_config(
        self, manager, reported_state, model_dirs, temp_dirs
    ):
        """On successful switch, OVMS config should contain the new model."""
        model_entry = reported_state['models']['efficientnet']

        manager._poll_ovms_model_status = MagicMock(return_value=True)

        manager._execute_model_switch('efficientnet', model_entry, reported_state)

        # Verify OVMS config was written with the new model
        config_path = os.path.join(temp_dirs['config_dir'], 'models_config.json')
        with open(config_path, 'r') as f:
            config = json.load(f)

        assert config['model_config_list'][0]['config']['name'] == 'efficientnet'
        assert config['model_config_list'][0]['config']['base_path'] == \
            model_dirs['efficientnet']

    def test_successful_switch_updates_reported_state(
        self, manager, reported_state, model_dirs
    ):
        """On successful switch, reported state should have new active_model."""
        model_entry = reported_state['models']['efficientnet']

        manager._poll_ovms_model_status = MagicMock(return_value=True)

        manager._execute_model_switch('efficientnet', model_entry, reported_state)

        # Verify update_thing_shadow was called with reported state
        calls = manager.ipc_client.update_thing_shadow.call_args_list
        # Find the reported state update (not the desired clear)
        found_reported_update = False
        for c in calls:
            payload = json.loads(c.kwargs['payload'])
            if 'reported' in payload.get('state', {}):
                assert payload['state']['reported']['active_model'] == 'efficientnet'
                found_reported_update = True
                break
        assert found_reported_update

    def test_successful_switch_updates_model_metadata(
        self, manager, reported_state, model_dirs
    ):
        """On successful switch, model_metadata should reflect new model's manifest."""
        model_entry = reported_state['models']['efficientnet']

        manager._poll_ovms_model_status = MagicMock(return_value=True)

        manager._execute_model_switch('efficientnet', model_entry, reported_state)

        # Verify model_metadata was updated from efficientnet's manifest
        calls = manager.ipc_client.update_thing_shadow.call_args_list
        for c in calls:
            payload = json.loads(c.kwargs['payload'])
            if 'reported' in payload.get('state', {}):
                metadata = payload['state']['reported'].get('model_metadata', {})
                assert metadata['input_name'] == 'input_image'
                assert metadata['output_names'] == ['predictions']
                assert metadata['input_shape'] == [1, 224, 224, 3]
                assert metadata['labels_file'] == 'labels.txt'
                break

    def test_successful_switch_clears_desired_field(
        self, manager, reported_state, model_dirs
    ):
        """On successful switch, the active_model desired field should be cleared."""
        model_entry = reported_state['models']['efficientnet']

        manager._poll_ovms_model_status = MagicMock(return_value=True)

        manager._execute_model_switch('efficientnet', model_entry, reported_state)

        # Verify desired field was cleared
        calls = manager.ipc_client.update_thing_shadow.call_args_list
        desired_cleared = False
        for c in calls:
            payload = json.loads(c.kwargs['payload'])
            desired = payload.get('state', {}).get('desired', {})
            if 'active_model' in desired and desired['active_model'] is None:
                desired_cleared = True
                break
        assert desired_cleared

    def test_successful_switch_polls_ovms(
        self, manager, reported_state, model_dirs
    ):
        """On switch, _poll_ovms_model_status should be called with correct params."""
        model_entry = reported_state['models']['efficientnet']

        manager._poll_ovms_model_status = MagicMock(return_value=True)

        manager._execute_model_switch('efficientnet', model_entry, reported_state)

        manager._poll_ovms_model_status.assert_called_once_with(
            model_name='efficientnet',
            timeout_seconds=60,
            poll_interval=2,
        )


# ---------------------------------------------------------------------------
# Tests: Failed model switch (timeout/error)
# ---------------------------------------------------------------------------

class TestModelSwitchFailure:
    """Tests for model switch failure/timeout flow."""

    def test_timeout_reverts_ovms_config(
        self, manager, reported_state, model_dirs, temp_dirs
    ):
        """On timeout, OVMS config should be reverted to the previous model."""
        model_entry = reported_state['models']['efficientnet']

        # Write initial config for faster_rcnn (the backup)
        from ovms_config import write_model_config as _write
        _write('faster_rcnn', model_dirs['faster_rcnn'], temp_dirs['config_dir'])

        # Mock polling to return failure (timeout)
        manager._poll_ovms_model_status = MagicMock(return_value=False)

        manager._execute_model_switch('efficientnet', model_entry, reported_state)

        # Verify OVMS config was reverted to faster_rcnn
        config_path = os.path.join(temp_dirs['config_dir'], 'models_config.json')
        with open(config_path, 'r') as f:
            config = json.load(f)

        assert config['model_config_list'][0]['config']['name'] == 'faster_rcnn'
        assert config['model_config_list'][0]['config']['base_path'] == \
            model_dirs['faster_rcnn']

    def test_timeout_sets_model_failed_status(
        self, manager, reported_state, model_dirs
    ):
        """On timeout, the target model status should be set to 'failed'."""
        model_entry = reported_state['models']['efficientnet']

        manager._poll_ovms_model_status = MagicMock(return_value=False)

        manager._execute_model_switch('efficientnet', model_entry, reported_state)

        # Verify shadow update sets model to failed
        calls = manager.ipc_client.update_thing_shadow.call_args_list
        found_failed = False
        for c in calls:
            payload = json.loads(c.kwargs['payload'])
            reported = payload.get('state', {}).get('reported', {})
            models = reported.get('models', {})
            if 'efficientnet' in models and \
               models['efficientnet'].get('status') == 'failed':
                found_failed = True
                assert 'failure_reason' in models['efficientnet']
                break
        assert found_failed, "Expected model status to be set to 'failed'"

    def test_timeout_publishes_error_event(
        self, manager, reported_state, model_dirs
    ):
        """On timeout, an error event should be published with model_load_failed."""
        model_entry = reported_state['models']['efficientnet']

        manager._poll_ovms_model_status = MagicMock(return_value=False)

        manager._execute_model_switch('efficientnet', model_entry, reported_state)

        # Verify publish_to_iot_core was called with error event
        publish_calls = manager.ipc_client.publish_to_iot_core.call_args_list
        error_published = False
        for c in publish_calls:
            topic = c.kwargs.get('topic_name', '')
            if 'errors' in topic:
                payload = json.loads(c.kwargs['payload'])
                assert payload['error_code'] == 'model_load_failed'
                assert payload['model_id'] == 'efficientnet'
                assert payload['operation'] == 'active_model'
                assert 'timestamp' in payload
                assert 'error_message' in payload
                error_published = True
                break
        assert error_published, "Expected error event to be published"

    def test_timeout_clears_desired_field(
        self, manager, reported_state, model_dirs
    ):
        """On timeout, the active_model desired field should still be cleared."""
        model_entry = reported_state['models']['efficientnet']

        manager._poll_ovms_model_status = MagicMock(return_value=False)

        manager._execute_model_switch('efficientnet', model_entry, reported_state)

        # Verify desired field was cleared
        calls = manager.ipc_client.update_thing_shadow.call_args_list
        desired_cleared = False
        for c in calls:
            payload = json.loads(c.kwargs['payload'])
            desired = payload.get('state', {}).get('desired', {})
            if 'active_model' in desired and desired['active_model'] is None:
                desired_cleared = True
                break
        assert desired_cleared


# ---------------------------------------------------------------------------
# Tests: Edge cases
# ---------------------------------------------------------------------------

class TestModelSwitchEdgeCases:
    """Tests for edge cases in model switch execution."""

    def test_no_local_path_publishes_error(self, manager, reported_state):
        """If model entry has no local_path, error should be published."""
        model_entry = {
            'model_id': 'efficientnet',
            'model_name': 'EfficientNet B0',
            'version': '1.2.0',
            'local_path': '',
            'size_bytes': 20971520,
            'last_updated': '2025-01-15T09:30:00Z',
            'status': 'ready',
        }

        manager._execute_model_switch('efficientnet', model_entry, reported_state)

        publish_calls = manager.ipc_client.publish_to_iot_core.call_args_list
        assert len(publish_calls) > 0
        error_payload = json.loads(publish_calls[0].kwargs['payload'])
        assert error_payload['error_code'] == 'model_not_available'

    def test_ovms_config_write_failure_publishes_error(
        self, manager, reported_state, model_dirs
    ):
        """If OVMS config write fails, error should be published."""
        model_entry = reported_state['models']['efficientnet']

        # Point config dir to nonexistent path to cause write failure
        manager.ovms_config_dir = '/nonexistent/path/that/does/not/exist'

        manager._execute_model_switch('efficientnet', model_entry, reported_state)

        publish_calls = manager.ipc_client.publish_to_iot_core.call_args_list
        assert len(publish_calls) > 0
        error_payload = json.loads(publish_calls[0].kwargs['payload'])
        assert error_payload['error_code'] == 'model_load_failed'

    def test_revert_with_no_backup_writes_empty_config(self, manager, temp_dirs):
        """If no backup config exists, revert should write empty config."""
        manager._revert_ovms_config(None)

        config_path = os.path.join(temp_dirs['config_dir'], 'models_config.json')
        with open(config_path, 'r') as f:
            config = json.load(f)
        assert config == {"model_config_list": []}

    def test_revert_with_valid_backup_restores_previous(
        self, manager, temp_dirs, model_dirs
    ):
        """If backup config exists, revert should restore it."""
        backup = {
            "model_config_list": [{
                "config": {
                    "name": "faster_rcnn",
                    "base_path": model_dirs['faster_rcnn']
                }
            }]
        }

        manager._revert_ovms_config(backup)

        config_path = os.path.join(temp_dirs['config_dir'], 'models_config.json')
        with open(config_path, 'r') as f:
            config = json.load(f)
        assert config['model_config_list'][0]['config']['name'] == 'faster_rcnn'


# ---------------------------------------------------------------------------
# Tests: Polling logic
# ---------------------------------------------------------------------------

class TestPollOvmsModelStatus:
    """Tests for the _poll_ovms_model_status method."""

    def test_returns_true_when_model_ready_immediately(self, manager):
        """If model is ready on first check, should return True quickly."""
        manager._check_ovms_model_ready = MagicMock(return_value=True)

        result = manager._poll_ovms_model_status(
            'test_model', timeout_seconds=10, poll_interval=1
        )

        assert result is True
        assert manager._check_ovms_model_ready.call_count == 1

    def test_returns_true_after_multiple_polls(self, manager):
        """If model becomes ready after a few polls, should return True."""
        manager._check_ovms_model_ready = MagicMock(
            side_effect=[False, False, True]
        )

        result = manager._poll_ovms_model_status(
            'test_model', timeout_seconds=10, poll_interval=0.1
        )

        assert result is True
        assert manager._check_ovms_model_ready.call_count == 3

    def test_returns_false_on_timeout(self, manager):
        """If model never becomes ready, should return False after timeout."""
        manager._check_ovms_model_ready = MagicMock(return_value=False)

        result = manager._poll_ovms_model_status(
            'test_model', timeout_seconds=0.5, poll_interval=0.1
        )

        assert result is False

    def test_handles_exceptions_during_polling(self, manager):
        """If check raises exception, should continue polling."""
        manager._check_ovms_model_ready = MagicMock(
            side_effect=[
                RuntimeError("connection refused"),
                RuntimeError("timeout"),
                True,
            ]
        )

        result = manager._poll_ovms_model_status(
            'test_model', timeout_seconds=10, poll_interval=0.1
        )

        assert result is True
        assert manager._check_ovms_model_ready.call_count == 3

    def test_exception_then_timeout(self, manager):
        """If check always raises, should return False after timeout."""
        manager._check_ovms_model_ready = MagicMock(
            side_effect=RuntimeError("connection refused")
        )

        result = manager._poll_ovms_model_status(
            'test_model', timeout_seconds=0.5, poll_interval=0.1
        )

        assert result is False


# ---------------------------------------------------------------------------
# Tests: _handle_active_model integration
# ---------------------------------------------------------------------------

class TestHandleActiveModel:
    """Tests for the _handle_active_model method (task 7.1 + 7.2 integration)."""

    def test_idempotent_switch_clears_desired(self, manager, reported_state):
        """If desired active_model equals current, should clear desired and no-op."""
        # Mock shadow read to return current state
        shadow_response = MagicMock()
        shadow_response.payload = json.dumps({
            'state': {'reported': reported_state}
        }).encode('utf-8')
        manager.ipc_client.get_thing_shadow.return_value = shadow_response

        manager._handle_active_model('faster_rcnn')

        # Should clear desired but not write new config
        calls = manager.ipc_client.update_thing_shadow.call_args_list
        assert len(calls) == 1  # Only the desired clear
        payload = json.loads(calls[0].kwargs['payload'])
        assert payload['state']['desired']['active_model'] is None

    def test_rejects_unavailable_model(self, manager, reported_state):
        """If model not in inventory, should reject with error."""
        shadow_response = MagicMock()
        shadow_response.payload = json.dumps({
            'state': {'reported': reported_state}
        }).encode('utf-8')
        manager.ipc_client.get_thing_shadow.return_value = shadow_response

        manager._handle_active_model('nonexistent_model')

        # Should publish error event
        publish_calls = manager.ipc_client.publish_to_iot_core.call_args_list
        assert len(publish_calls) > 0
        error_payload = json.loads(publish_calls[0].kwargs['payload'])
        assert error_payload['error_code'] == 'model_not_available'

    def test_rejects_model_not_ready(self, manager, reported_state):
        """If model exists but status is not 'ready', should reject."""
        reported_state['models']['efficientnet']['status'] = 'downloading'

        shadow_response = MagicMock()
        shadow_response.payload = json.dumps({
            'state': {'reported': reported_state}
        }).encode('utf-8')
        manager.ipc_client.get_thing_shadow.return_value = shadow_response

        manager._handle_active_model('efficientnet')

        publish_calls = manager.ipc_client.publish_to_iot_core.call_args_list
        assert len(publish_calls) > 0
        error_payload = json.loads(publish_calls[0].kwargs['payload'])
        assert error_payload['error_code'] == 'model_not_available'
