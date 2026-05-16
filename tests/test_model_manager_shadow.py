"""Unit tests for ModelManagerCore shadow subscription and reconciliation logic.

Tests the entry point, shadow delta subscription, and model reconciliation
that determines what needs installing/removing based on desired vs reported state.

Requirements: 1.1, 1.2, 1.3
"""

import sys
import os
import json
from unittest.mock import MagicMock, patch, call

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
    # Default: no existing shadow
    mock.get_thing_shadow.side_effect = Exception("ResourceNotFoundException")
    return mock


@pytest.fixture
def manager(mock_ipc_client):
    """Create a ModelManagerCore instance with mocked IPC."""
    mock_clientv2.GreengrassCoreIPCClientV2.return_value = mock_ipc_client

    with patch.dict(os.environ, {
        'AWS_IOT_THING_NAME': 'test-thing',
        'SNAP_COMPONENTS': '/snap/ovms-engine/current/components',
        'SNAP_COMMON': '/var/snap/ovms-engine/common',
        'OVMS_CONFIG_DIR': '/var/snap/ovms-engine/common/config',
    }):
        from model_manager_core import ModelManagerCore
        mgr = ModelManagerCore()
        mgr.ipc_client = mock_ipc_client
        yield mgr


class TestInitialization:
    """Tests for ModelManagerCore initialization."""

    def test_initializes_with_environment_variables(self, manager):
        """Manager reads configuration from environment variables."""
        assert manager.thing_name == 'test-thing'
        assert manager.snap_components_path == '/snap/ovms-engine/current/components'
        assert manager.snap_common_path == '/var/snap/ovms-engine/common'

    def test_initializes_with_empty_reported_models(self, manager):
        """Manager starts with empty reported models when no shadow exists."""
        assert manager.reported_models == {}

    def test_loads_existing_reported_state(self, mock_ipc_client):
        """Manager loads existing reported models from shadow on startup."""
        shadow_data = {
            'state': {
                'reported': {
                    'models': {
                        'faster-rcnn': {
                            'status': 'ready',
                            'model_metadata': {'model_name': 'faster_rcnn'}
                        }
                    }
                }
            }
        }
        mock_response = MagicMock()
        mock_response.payload = json.dumps(shadow_data).encode('utf-8')
        mock_ipc_client.get_thing_shadow.return_value = mock_response
        mock_ipc_client.get_thing_shadow.side_effect = None

        mock_clientv2.GreengrassCoreIPCClientV2.return_value = mock_ipc_client

        with patch.dict(os.environ, {
            'AWS_IOT_THING_NAME': 'test-thing',
            'SNAP_COMPONENTS': '/snap/ovms-engine/current/components',
            'SNAP_COMMON': '/var/snap/ovms-engine/common',
            'OVMS_CONFIG_DIR': '/var/snap/ovms-engine/common/config',
        }):
            from model_manager_core import ModelManagerCore
            mgr = ModelManagerCore()
            mgr.ipc_client = mock_ipc_client
            mgr._load_current_reported_state()

        assert 'faster-rcnn' in mgr.reported_models
        assert mgr.reported_models['faster-rcnn']['status'] == 'ready'


class TestShadowSubscription:
    """Tests for shadow delta subscription."""

    def test_subscribes_to_correct_delta_topic(self, manager, mock_ipc_client):
        """Manager subscribes to the model-config named shadow delta topic."""
        manager._subscribe_to_shadow_delta()

        mock_ipc_client.subscribe_to_iot_core.assert_called_once()
        call_kwargs = mock_ipc_client.subscribe_to_iot_core.call_args.kwargs
        expected_topic = "$aws/things/test-thing/shadow/name/model-config/update/delta"
        assert call_kwargs['topic_name'] == expected_topic
        assert call_kwargs['qos'] == '1'

    def test_does_not_subscribe_without_thing_name(self, mock_ipc_client):
        """Manager does not subscribe if AWS_IOT_THING_NAME is not set."""
        mock_clientv2.GreengrassCoreIPCClientV2.return_value = mock_ipc_client

        with patch.dict(os.environ, {
            'AWS_IOT_THING_NAME': '',
            'SNAP_COMPONENTS': '/snap/ovms-engine/current/components',
            'SNAP_COMMON': '/var/snap/ovms-engine/common',
            'OVMS_CONFIG_DIR': '/var/snap/ovms-engine/common/config',
        }):
            from model_manager_core import ModelManagerCore
            mgr = ModelManagerCore()
            mgr.ipc_client = mock_ipc_client
            mgr._subscribe_to_shadow_delta()

        mock_ipc_client.subscribe_to_iot_core.assert_not_called()


class TestShadowDeltaHandling:
    """Tests for processing shadow delta events."""

    def test_delta_with_new_snap_model_triggers_install(self, manager):
        """Delta containing a new snap model triggers installation."""
        event = MagicMock()
        event.message.payload = json.dumps({
            'state': {
                'models': {
                    'faster-rcnn': {'source': 'snap'}
                }
            }
        }).encode('utf-8')

        with patch.object(manager, '_handle_model_install') as mock_install:
            manager._on_shadow_delta(event)
            mock_install.assert_called_once_with(
                'faster-rcnn', {'source': 'snap'}
            )

    def test_delta_with_new_s3_model_triggers_install(self, manager):
        """Delta containing a new S3 model triggers installation."""
        event = MagicMock()
        event.message.payload = json.dumps({
            'state': {
                'models': {
                    'custom-model': {
                        'source': 's3',
                        's3_uri': 's3://my-bucket/models/custom/1.0/'
                    }
                }
            }
        }).encode('utf-8')

        with patch.object(manager, '_handle_model_install') as mock_install:
            manager._on_shadow_delta(event)
            mock_install.assert_called_once_with(
                'custom-model',
                {'source': 's3', 's3_uri': 's3://my-bucket/models/custom/1.0/'}
            )

    def test_delta_without_models_field_is_ignored(self, manager):
        """Delta that does not contain a models field is ignored."""
        event = MagicMock()
        event.message.payload = json.dumps({
            'state': {
                'some_other_field': 'value'
            }
        }).encode('utf-8')

        with patch.object(manager, '_reconcile_models') as mock_reconcile:
            manager._on_shadow_delta(event)
            mock_reconcile.assert_not_called()

    def test_delta_with_multiple_models(self, manager):
        """Delta with multiple new models triggers install for each."""
        event = MagicMock()
        event.message.payload = json.dumps({
            'state': {
                'models': {
                    'faster-rcnn': {'source': 'snap'},
                    'efficientnet': {'source': 'snap'},
                    'custom-ppe': {'source': 's3', 's3_uri': 's3://bucket/ppe/'}
                }
            }
        }).encode('utf-8')

        with patch.object(manager, '_handle_model_install') as mock_install:
            manager._on_shadow_delta(event)
            assert mock_install.call_count == 3


class TestReconciliation:
    """Tests for model reconciliation logic."""

    def test_new_model_identified_for_install(self, manager):
        """Model in desired but not in reported is identified for installation."""
        manager.reported_models = {}

        with patch.object(manager, '_handle_model_install') as mock_install, \
             patch.object(manager, '_handle_model_removal') as mock_remove:
            manager._reconcile_models({
                'faster-rcnn': {'source': 'snap'}
            })
            mock_install.assert_called_once_with('faster-rcnn', {'source': 'snap'})
            mock_remove.assert_not_called()

    def test_removed_model_identified_for_removal(self, manager):
        """Model in reported but not in desired is identified for removal."""
        manager.reported_models = {
            'old-model': {'status': 'ready'}
        }

        with patch.object(manager, '_handle_model_install') as mock_install, \
             patch.object(manager, '_handle_model_removal') as mock_remove:
            manager._reconcile_models({})
            mock_remove.assert_called_once_with('old-model')
            mock_install.assert_not_called()

    def test_existing_ready_model_not_reinstalled(self, manager):
        """Model already in reported with status ready is not reinstalled."""
        manager.reported_models = {
            'faster-rcnn': {'status': 'ready'}
        }

        with patch.object(manager, '_handle_model_install') as mock_install:
            manager._reconcile_models({
                'faster-rcnn': {'source': 'snap'}
            })
            mock_install.assert_not_called()

    def test_failed_model_retried_on_new_delta(self, manager):
        """Model with status failed is retried when it appears in a new delta."""
        manager.reported_models = {
            'broken-model': {'status': 'failed', 'reason': 'snap install error'}
        }

        with patch.object(manager, '_handle_model_install') as mock_install:
            manager._reconcile_models({
                'broken-model': {'source': 'snap'}
            })
            mock_install.assert_called_once_with('broken-model', {'source': 'snap'})

    def test_mixed_install_and_remove(self, manager):
        """Reconciliation handles both installs and removals in one delta."""
        manager.reported_models = {
            'old-model': {'status': 'ready'},
            'keep-model': {'status': 'ready'},
        }

        with patch.object(manager, '_handle_model_install') as mock_install, \
             patch.object(manager, '_handle_model_removal') as mock_remove:
            manager._reconcile_models({
                'keep-model': {'source': 'snap'},
                'new-model': {'source': 's3', 's3_uri': 's3://bucket/new/'}
            })
            mock_install.assert_called_once_with(
                'new-model', {'source': 's3', 's3_uri': 's3://bucket/new/'}
            )
            mock_remove.assert_called_once_with('old-model')


class TestModelInstallDispatch:
    """Tests for model install dispatch based on source type."""

    def test_snap_source_calls_snap_install(self, manager):
        """Model with source 'snap' dispatches to snap installation."""
        with patch.object(manager, '_install_snap_model') as mock_snap, \
             patch.object(manager, '_report_model_status'):
            manager._handle_model_install('faster-rcnn', {'source': 'snap'})
            mock_snap.assert_called_once_with('faster-rcnn')

    def test_s3_source_calls_s3_install(self, manager):
        """Model with source 's3' dispatches to S3 download."""
        with patch.object(manager, '_install_s3_model') as mock_s3, \
             patch.object(manager, '_report_model_status'):
            manager._handle_model_install(
                'custom-model',
                {'source': 's3', 's3_uri': 's3://bucket/model/'}
            )
            mock_s3.assert_called_once_with('custom-model', 's3://bucket/model/')

    def test_invalid_source_reports_failed(self, manager, mock_ipc_client):
        """Model with invalid source reports failed status."""
        manager._handle_model_install('bad-model', {'source': 'invalid'})

        # Verify shadow was updated with failed status
        update_calls = mock_ipc_client.update_thing_shadow.call_args_list
        assert len(update_calls) > 0
        payload = json.loads(update_calls[-1].kwargs['payload'])
        models = payload['state']['reported']['models']
        assert models['bad-model']['status'] == 'failed'
        assert 'Invalid source' in models['bad-model']['reason']

    def test_s3_source_without_uri_reports_failed(self, manager, mock_ipc_client):
        """S3 model without s3_uri reports failed status."""
        manager._handle_model_install('no-uri-model', {'source': 's3'})

        update_calls = mock_ipc_client.update_thing_shadow.call_args_list
        assert len(update_calls) > 0
        payload = json.loads(update_calls[-1].kwargs['payload'])
        models = payload['state']['reported']['models']
        assert models['no-uri-model']['status'] == 'failed'
        assert 's3_uri' in models['no-uri-model']['reason']

    def test_installing_status_reported_before_install(self, manager, mock_ipc_client):
        """Status 'installing' is reported before actual installation begins."""
        call_order = []

        def track_report(*args, **kwargs):
            call_order.append('report')

        def track_snap(*args, **kwargs):
            call_order.append('snap')

        with patch.object(manager, '_report_model_status', side_effect=track_report), \
             patch.object(manager, '_install_snap_model', side_effect=track_snap):
            manager._handle_model_install('test-model', {'source': 'snap'})

        assert call_order == ['report', 'snap']


class TestShadowReporting:
    """Tests for shadow reported state updates."""

    def test_report_model_status_updates_shadow(self, manager, mock_ipc_client):
        """Reporting model status updates the shadow with correct payload."""
        manager._report_model_status('faster-rcnn', 'installing')

        mock_ipc_client.update_thing_shadow.assert_called_once()
        call_kwargs = mock_ipc_client.update_thing_shadow.call_args.kwargs
        assert call_kwargs['thing_name'] == 'test-thing'
        assert call_kwargs['shadow_name'] == 'model-config'

        payload = json.loads(call_kwargs['payload'])
        models = payload['state']['reported']['models']
        assert models['faster-rcnn']['status'] == 'installing'

    def test_report_failed_includes_reason(self, manager, mock_ipc_client):
        """Failed status includes a reason string."""
        manager._report_model_status(
            'broken-model', 'failed', reason='snap install returned exit code 1'
        )

        call_kwargs = mock_ipc_client.update_thing_shadow.call_args.kwargs
        payload = json.loads(call_kwargs['payload'])
        models = payload['state']['reported']['models']
        assert models['broken-model']['status'] == 'failed'
        assert models['broken-model']['reason'] == 'snap install returned exit code 1'

    def test_report_ready_includes_metadata(self, manager, mock_ipc_client):
        """Ready status includes model metadata."""
        metadata = {
            'model_name': 'faster_rcnn',
            'input_name': 'input_tensor',
            'output_names': ['detection_boxes', 'detection_scores'],
            'input_shape': [1, 255, 255, 3],
            'labels_file': 'labels.txt',
        }
        manager._report_model_status(
            'faster-rcnn', 'ready', model_metadata=metadata
        )

        call_kwargs = mock_ipc_client.update_thing_shadow.call_args.kwargs
        payload = json.loads(call_kwargs['payload'])
        models = payload['state']['reported']['models']
        assert models['faster-rcnn']['status'] == 'ready'
        assert models['faster-rcnn']['model_metadata'] == metadata

    def test_reported_state_accumulates_models(self, manager, mock_ipc_client):
        """Multiple model status reports accumulate in the reported state."""
        manager._report_model_status('model-a', 'installing')
        manager._report_model_status('model-b', 'ready')

        # Last call should contain both models
        call_kwargs = mock_ipc_client.update_thing_shadow.call_args.kwargs
        payload = json.loads(call_kwargs['payload'])
        models = payload['state']['reported']['models']
        assert 'model-a' in models
        assert 'model-b' in models
