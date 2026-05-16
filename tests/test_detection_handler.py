"""Unit tests for DetectionHandler shadow reading, subscription, and retry logic.

Tests the startup flow: reading model metadata from the model-config shadow,
subscribing to camera/images, and retry logic when model is not yet ready.

Requirements: 6.1, 6.4
"""

import sys
import os
import json
from unittest.mock import MagicMock, patch, call

import pytest

# Add artifact path for imports
sys.path.insert(0, os.path.join(
    os.path.dirname(__file__), '..', 'greengrass-components', 'artifacts',
    'com.example.DetectionHandler', '1.0.0'
))

# Mock the awsiot module before importing detection_handler
mock_clientv2 = MagicMock()
sys.modules['awsiot'] = MagicMock()
sys.modules['awsiot.greengrasscoreipc'] = MagicMock()
sys.modules['awsiot.greengrasscoreipc.clientv2'] = mock_clientv2
sys.modules['awsiot.greengrasscoreipc.model'] = MagicMock()

# Mock cv2, numpy, and ovmsclient which are used for inference (task 2.3)
sys.modules['cv2'] = MagicMock()
sys.modules['ovmsclient'] = MagicMock()


@pytest.fixture
def mock_ipc_client():
    """Create a mock IPC client."""
    mock = MagicMock()
    return mock


@pytest.fixture
def handler(mock_ipc_client):
    """Create a DetectionHandler instance with mocked IPC."""
    mock_clientv2.GreengrassCoreIPCClientV2.return_value = mock_ipc_client

    with patch.dict(os.environ, {
        'AWS_IOT_THING_NAME': 'test-thing',
        'DETECTION_MODEL_ID': 'faster-rcnn',
        'SUB_TOPIC': 'camera/images',
        'PUB_TOPIC': 'camera/detections',
        'MODEL_SERVER_URL': 'localhost:9000',
        'CONFIDENCE_THRESHOLD': '0.5',
    }):
        from detection_handler import DetectionHandler
        h = DetectionHandler()
        h.ipc_client = mock_ipc_client
        yield h


def _make_shadow_response(models):
    """Helper to create a mock shadow response with given models."""
    shadow_data = {
        'state': {
            'reported': {
                'engine': 'gpu',
                'status': 'ready',
                'models': models,
            }
        }
    }
    mock_response = MagicMock()
    mock_response.payload = json.dumps(shadow_data).encode('utf-8')
    return mock_response


class TestInitialization:
    """Tests for DetectionHandler initialization."""

    def test_initializes_with_environment_variables(self, handler):
        """Handler reads configuration from environment variables."""
        assert handler.thing_name == 'test-thing'
        assert handler.detection_model_id == 'faster-rcnn'
        assert handler.sub_topic == 'camera/images'
        assert handler.pub_topic == 'camera/detections'
        assert handler.model_server_url == 'localhost:9000'
        assert handler.confidence_threshold == 0.5

    def test_initializes_with_no_model_metadata(self, handler):
        """Handler starts with no model metadata loaded."""
        assert handler.model_metadata is None
        assert handler.labels_map is None


class TestShadowReading:
    """Tests for reading model metadata from the shadow."""

    def test_reads_model_metadata_when_model_ready(self, handler, mock_ipc_client):
        """Handler reads model_metadata when model status is 'ready'."""
        expected_metadata = {
            'model_name': 'faster_rcnn',
            'input_name': 'input_tensor',
            'output_names': ['detection_boxes', 'detection_classes',
                            'detection_scores', 'num_detections'],
            'input_shape': [1, 255, 255, 3],
            'labels_file': 'labels.txt',
            'local_path': '/snap/ovms-engine/components/model-faster-rcnn/',
        }
        mock_ipc_client.get_thing_shadow.return_value = _make_shadow_response({
            'faster-rcnn': {
                'status': 'ready',
                'model_metadata': expected_metadata,
            }
        })

        result = handler._read_model_metadata_from_shadow()
        assert result == expected_metadata

    def test_returns_none_when_model_not_in_shadow(self, handler, mock_ipc_client):
        """Handler returns None when the assigned model is not in the shadow."""
        mock_ipc_client.get_thing_shadow.return_value = _make_shadow_response({
            'efficientnet': {
                'status': 'ready',
                'model_metadata': {'model_name': 'efficientnet'},
            }
        })

        result = handler._read_model_metadata_from_shadow()
        assert result is None

    def test_returns_none_when_model_still_installing(self, handler, mock_ipc_client):
        """Handler returns None when the model status is 'installing'."""
        mock_ipc_client.get_thing_shadow.return_value = _make_shadow_response({
            'faster-rcnn': {
                'status': 'installing',
            }
        })

        result = handler._read_model_metadata_from_shadow()
        assert result is None

    def test_returns_none_when_model_failed(self, handler, mock_ipc_client):
        """Handler returns None when the model status is 'failed'."""
        mock_ipc_client.get_thing_shadow.return_value = _make_shadow_response({
            'faster-rcnn': {
                'status': 'failed',
                'reason': 'snap install error',
            }
        })

        result = handler._read_model_metadata_from_shadow()
        assert result is None

    def test_returns_none_when_shadow_read_fails(self, handler, mock_ipc_client):
        """Handler returns None when shadow read throws an exception."""
        mock_ipc_client.get_thing_shadow.side_effect = Exception(
            "ResourceNotFoundException"
        )

        result = handler._read_model_metadata_from_shadow()
        assert result is None

    def test_returns_none_when_no_thing_name(self, mock_ipc_client):
        """Handler returns None when AWS_IOT_THING_NAME is not set."""
        mock_clientv2.GreengrassCoreIPCClientV2.return_value = mock_ipc_client

        with patch.dict(os.environ, {
            'AWS_IOT_THING_NAME': '',
            'DETECTION_MODEL_ID': 'faster-rcnn',
        }):
            from detection_handler import DetectionHandler
            h = DetectionHandler()
            h.ipc_client = mock_ipc_client

        result = h._read_model_metadata_from_shadow()
        assert result is None

    def test_returns_none_when_ready_but_no_metadata(self, handler, mock_ipc_client):
        """Handler returns None when model is ready but has no model_metadata field."""
        mock_ipc_client.get_thing_shadow.return_value = _make_shadow_response({
            'faster-rcnn': {
                'status': 'ready',
            }
        })

        result = handler._read_model_metadata_from_shadow()
        assert result is None


class TestRetryLogic:
    """Tests for the retry logic when model is not yet ready (Requirement 6.4)."""

    def test_retries_until_model_ready(self, handler, mock_ipc_client):
        """Handler retries reading shadow until model becomes ready."""
        metadata = {
            'model_name': 'faster_rcnn',
            'input_name': 'input_tensor',
            'output_names': ['detection_boxes'],
            'input_shape': [1, 255, 255, 3],
            'labels_file': 'labels.txt',
            'local_path': '/snap/ovms-engine/components/model-faster-rcnn/',
        }

        # First two calls: model not ready. Third call: model ready.
        mock_ipc_client.get_thing_shadow.side_effect = [
            _make_shadow_response({'faster-rcnn': {'status': 'installing'}}),
            _make_shadow_response({'faster-rcnn': {'status': 'installing'}}),
            _make_shadow_response({
                'faster-rcnn': {
                    'status': 'ready',
                    'model_metadata': metadata,
                }
            }),
        ]

        with patch('detection_handler.time.sleep') as mock_sleep, \
             patch.object(handler, '_load_labels'):
            handler._wait_for_model_ready()

        assert handler.model_metadata == metadata
        # Should have slept twice (once per retry before success)
        assert mock_sleep.call_count == 2
        mock_sleep.assert_called_with(10)

    def test_retries_on_shadow_exception(self, handler, mock_ipc_client):
        """Handler retries when shadow read throws an exception."""
        metadata = {
            'model_name': 'faster_rcnn',
            'input_name': 'input_tensor',
            'output_names': ['detection_boxes'],
            'input_shape': [1, 255, 255, 3],
            'labels_file': 'labels.txt',
            'local_path': '/snap/ovms-engine/components/model-faster-rcnn/',
        }

        # First call: exception. Second call: model ready.
        mock_ipc_client.get_thing_shadow.side_effect = [
            Exception("ResourceNotFoundException"),
            _make_shadow_response({
                'faster-rcnn': {
                    'status': 'ready',
                    'model_metadata': metadata,
                }
            }),
        ]

        with patch('detection_handler.time.sleep') as mock_sleep, \
             patch.object(handler, '_load_labels'):
            handler._wait_for_model_ready()

        assert handler.model_metadata == metadata
        assert mock_sleep.call_count == 1


class TestImageSubscription:
    """Tests for subscribing to camera/images topic."""

    def test_subscribes_to_configured_topic(self, handler, mock_ipc_client):
        """Handler subscribes to the configured sub_topic."""
        mock_ipc_client.subscribe_to_topic.return_value = (MagicMock(), MagicMock())

        handler._subscribe_to_images()

        mock_ipc_client.subscribe_to_topic.assert_called_once()
        call_kwargs = mock_ipc_client.subscribe_to_topic.call_args.kwargs
        assert call_kwargs['topic'] == 'camera/images'

    def test_raises_on_subscription_failure(self, handler, mock_ipc_client):
        """Handler raises when subscription fails."""
        mock_ipc_client.subscribe_to_topic.side_effect = Exception(
            "UnauthorizedError"
        )

        with pytest.raises(Exception, match="UnauthorizedError"):
            handler._subscribe_to_images()


class TestLabelLoading:
    """Tests for loading labels from the model's labels file."""

    def test_loads_labels_from_file(self, handler, tmp_path):
        """Handler loads labels from the labels file in model's local_path."""
        labels_file = tmp_path / "labels.txt"
        labels_file.write_text("background\nperson\ncar\nbicycle\n")

        handler.model_metadata = {
            'local_path': str(tmp_path),
            'labels_file': 'labels.txt',
        }

        handler._load_labels()

        assert handler.labels_map == {1: 'background', 2: 'person', 3: 'car', 4: 'bicycle'}

    def test_handles_missing_labels_file(self, handler, tmp_path):
        """Handler handles missing labels file gracefully."""
        handler.model_metadata = {
            'local_path': str(tmp_path),
            'labels_file': 'nonexistent.txt',
        }

        handler._load_labels()

        assert handler.labels_map == {}

    def test_handles_missing_metadata(self, handler):
        """Handler handles missing model_metadata gracefully."""
        handler.model_metadata = None

        handler._load_labels()

        assert handler.labels_map is None


class TestModelParameterExtraction:
    """Tests for extracting individual model parameters from model_metadata.

    Requirements: 6.1, 6.2, 6.3
    """

    def test_extracts_all_parameters(self, handler):
        """Handler extracts model_name, input_name, output_names, input_shape."""
        metadata = {
            'model_name': 'faster_rcnn',
            'input_name': 'input_tensor',
            'output_names': ['detection_boxes', 'detection_classes',
                            'detection_scores', 'num_detections'],
            'input_shape': [1, 255, 255, 3],
            'labels_file': 'labels.txt',
            'local_path': '/snap/ovms-engine/components/model-faster-rcnn/',
        }

        handler._extract_model_parameters(metadata)

        assert handler.model_name == 'faster_rcnn'
        assert handler.input_name == 'input_tensor'
        assert handler.output_names == ['detection_boxes', 'detection_classes',
                                        'detection_scores', 'num_detections']
        assert handler.input_shape == [1, 255, 255, 3]

    def test_defaults_to_empty_when_fields_missing(self, handler):
        """Handler defaults to empty values when metadata fields are missing."""
        metadata = {}

        handler._extract_model_parameters(metadata)

        assert handler.model_name == ''
        assert handler.input_name == ''
        assert handler.output_names == []
        assert handler.input_shape == []

    def test_partial_metadata_extracts_available_fields(self, handler):
        """Handler extracts available fields even when some are missing."""
        metadata = {
            'model_name': 'custom_model',
            'input_name': 'images',
        }

        handler._extract_model_parameters(metadata)

        assert handler.model_name == 'custom_model'
        assert handler.input_name == 'images'
        assert handler.output_names == []
        assert handler.input_shape == []

    def test_wait_for_model_ready_extracts_parameters(self, handler, mock_ipc_client):
        """_wait_for_model_ready extracts individual parameters after loading metadata."""
        metadata = {
            'model_name': 'faster_rcnn',
            'input_name': 'input_tensor',
            'output_names': ['detection_boxes', 'detection_classes',
                            'detection_scores', 'num_detections'],
            'input_shape': [1, 255, 255, 3],
            'labels_file': 'labels.txt',
            'local_path': '/snap/ovms-engine/components/model-faster-rcnn/',
        }

        mock_ipc_client.get_thing_shadow.return_value = _make_shadow_response({
            'faster-rcnn': {
                'status': 'ready',
                'model_metadata': metadata,
            }
        })

        with patch.object(handler, '_load_labels'):
            handler._wait_for_model_ready()

        assert handler.model_name == 'faster_rcnn'
        assert handler.input_name == 'input_tensor'
        assert handler.output_names == ['detection_boxes', 'detection_classes',
                                        'detection_scores', 'num_detections']
        assert handler.input_shape == [1, 255, 255, 3]
