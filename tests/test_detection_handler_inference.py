"""Unit tests for DetectionHandler inference pipeline and result publishing.

Tests the inference flow: image preprocessing, OVMS gRPC call, output parsing,
confidence threshold filtering, label annotation, and detection publishing.

Requirements: 6.2, 6.3
"""

import sys
import os
import json
import importlib
from unittest.mock import MagicMock, patch, call

import numpy as np
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

# Mock ovmsclient
mock_ovmsclient = MagicMock()
sys.modules['ovmsclient'] = mock_ovmsclient

# We need real cv2 for image processing tests. Since test_detection_handler.py
# may have already mocked cv2 in sys.modules, we import the real cv2 that was
# captured by conftest.py before any mocking occurred.
from tests.conftest import real_cv2 as _real_cv2

# Now put real cv2 back in sys.modules and reload detection_handler
sys.modules['cv2'] = _real_cv2
if 'detection_handler' in sys.modules:
    del sys.modules['detection_handler']

import detection_handler
# Ensure the module's cv2 reference is the real one
detection_handler.cv2 = _real_cv2

from detection_handler import DetectionHandler


@pytest.fixture
def mock_ipc_client():
    """Create a mock IPC client."""
    return MagicMock()


@pytest.fixture
def handler(mock_ipc_client):
    """Create a DetectionHandler instance configured for inference testing."""
    mock_clientv2.GreengrassCoreIPCClientV2.return_value = mock_ipc_client

    with patch.dict(os.environ, {
        'AWS_IOT_THING_NAME': 'test-thing',
        'DETECTION_MODEL_ID': 'faster-rcnn',
        'SUB_TOPIC': 'camera/images',
        'PUB_TOPIC': 'camera/detections',
        'MODEL_SERVER_URL': 'localhost:9000',
        'CONFIDENCE_THRESHOLD': '0.5',
    }):
        h = DetectionHandler()
        h.ipc_client = mock_ipc_client

        # Set up model metadata as if _wait_for_model_ready completed
        h.model_metadata = {
            'model_name': 'faster_rcnn',
            'input_name': 'input_tensor',
            'output_names': ['detection_boxes', 'detection_classes',
                            'detection_scores', 'num_detections'],
            'input_shape': [1, 255, 255, 3],
            'labels_file': 'labels.txt',
            'local_path': '/snap/ovms-engine/components/model-faster-rcnn/',
        }
        h.model_name = 'faster_rcnn'
        h.input_name = 'input_tensor'
        h.output_names = ['detection_boxes', 'detection_classes',
                         'detection_scores', 'num_detections']
        h.input_shape = [1, 255, 255, 3]
        h.labels_map = {1: 'person', 2: 'car', 3: 'bicycle'}

        yield h


class TestPreprocessImage:
    """Tests for _preprocess_image resizing according to input_shape.

    Requirement 6.2: Preprocess image according to input_shape from metadata.
    """

    def test_resizes_to_input_shape_dimensions(self, handler):
        """Image is resized to height and width from input_shape [batch, H, W, C]."""
        # Create a 480x640 RGB image
        image_rgb = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)

        # input_shape is [1, 255, 255, 3]
        result = handler._preprocess_image(image_rgb)

        # Should be resized to (255, 255) with batch dimension
        assert result.shape == (1, 255, 255, 3)

    def test_adds_batch_dimension(self, handler):
        """Preprocessed image has batch dimension of 1."""
        image_rgb = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)

        result = handler._preprocess_image(image_rgb)

        assert result.shape[0] == 1

    def test_handles_different_input_shapes(self, handler):
        """Preprocessing adapts to different model input shapes."""
        handler.input_shape = [1, 224, 224, 3]
        image_rgb = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)

        result = handler._preprocess_image(image_rgb)

        assert result.shape == (1, 224, 224, 3)

    def test_preserves_channel_count(self, handler):
        """Preprocessed image retains 3 channels (RGB)."""
        image_rgb = np.random.randint(0, 255, (300, 400, 3), dtype=np.uint8)

        result = handler._preprocess_image(image_rgb)

        assert result.shape[3] == 3

    def test_handles_non_square_input_shape(self, handler):
        """Preprocessing handles non-square target dimensions."""
        handler.input_shape = [1, 300, 512, 3]
        image_rgb = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)

        result = handler._preprocess_image(image_rgb)

        assert result.shape == (1, 300, 512, 3)

    def test_output_dtype_is_uint8(self, handler):
        """Preprocessed image is uint8 dtype."""
        image_rgb = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)

        result = handler._preprocess_image(image_rgb)

        assert result.dtype == np.uint8


class TestRunInference:
    """Tests for _run_inference calling OVMS gRPC.

    Requirement 6.2: Call OVMS via gRPC using parameters from model_metadata.
    """

    def test_calls_ovms_with_model_name_and_input_name(self, handler, tmp_path):
        """Inference calls OVMS predict with correct model_name and input_name."""
        # Create a test image file
        image_path = str(tmp_path / "test.jpg")
        test_image = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
        _real_cv2.imwrite(image_path, test_image)

        # Mock OVMS client
        mock_client = MagicMock()
        mock_client.predict.return_value = {
            'detection_boxes': np.zeros((1, 5, 4)),
            'detection_classes': np.zeros((1, 5)),
            'detection_scores': np.zeros((1, 5)),
            'num_detections': np.array([0]),
        }
        mock_ovmsclient.make_grpc_client.return_value = mock_client

        handler._run_inference({'image_path': image_path})

        # Verify OVMS was called with correct model name
        mock_client.predict.assert_called_once()
        call_args = mock_client.predict.call_args
        assert call_args[0][1] == 'faster_rcnn'  # model_name
        # Verify input dict uses input_name from metadata
        inputs = call_args[0][0]
        assert 'input_tensor' in inputs

    def test_connects_to_configured_server_url(self, handler, tmp_path):
        """Inference connects to the MODEL_SERVER_URL."""
        image_path = str(tmp_path / "test.jpg")
        test_image = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
        _real_cv2.imwrite(image_path, test_image)

        mock_client = MagicMock()
        mock_client.predict.return_value = {
            'detection_boxes': np.zeros((1, 5, 4)),
            'detection_classes': np.zeros((1, 5)),
            'detection_scores': np.zeros((1, 5)),
            'num_detections': np.array([0]),
        }
        mock_ovmsclient.make_grpc_client.return_value = mock_client

        handler._run_inference({'image_path': image_path})

        mock_ovmsclient.make_grpc_client.assert_called_with('localhost:9000')

    def test_skips_inference_when_no_image_path(self, handler):
        """Inference is skipped when message has no image_path."""
        mock_ovmsclient.make_grpc_client.reset_mock()

        handler._run_inference({'other_field': 'value'})

        mock_ovmsclient.make_grpc_client.assert_not_called()

    def test_skips_inference_when_no_model_metadata(self, handler, tmp_path):
        """Inference is skipped when model_metadata is None."""
        mock_ovmsclient.make_grpc_client.reset_mock()
        handler.model_metadata = None

        handler._run_inference({'image_path': str(tmp_path / "test.jpg")})

        mock_ovmsclient.make_grpc_client.assert_not_called()

    def test_handles_ovms_connection_error(self, handler, tmp_path):
        """Inference handles OVMS connection errors gracefully."""
        image_path = str(tmp_path / "test.jpg")
        test_image = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
        _real_cv2.imwrite(image_path, test_image)

        mock_ovmsclient.make_grpc_client.side_effect = Exception("Connection refused")

        # Should not raise
        handler._run_inference({'image_path': image_path})

    def test_preprocessed_input_has_correct_shape(self, handler, tmp_path):
        """Input tensor sent to OVMS has the shape matching input_shape metadata."""
        image_path = str(tmp_path / "test.jpg")
        test_image = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
        _real_cv2.imwrite(image_path, test_image)

        mock_client = MagicMock()
        mock_client.predict.return_value = {
            'detection_boxes': np.zeros((1, 5, 4)),
            'detection_classes': np.zeros((1, 5)),
            'detection_scores': np.zeros((1, 5)),
            'num_detections': np.array([0]),
        }
        mock_ovmsclient.make_grpc_client.reset_mock(side_effect=True)
        mock_ovmsclient.make_grpc_client.return_value = mock_client

        handler._run_inference({'image_path': image_path})

        call_args = mock_client.predict.call_args
        inputs = call_args[0][0]
        input_tensor = inputs['input_tensor']
        # input_shape is [1, 255, 255, 3]
        assert input_tensor.shape == (1, 255, 255, 3)


class TestParseDetectionOutputs:
    """Tests for _parse_detection_outputs extracting boxes, classes, scores.

    Requirement 6.2, 6.3: Parse detection outputs using output_names from metadata.
    """

    def test_extracts_all_output_tensors(self, handler):
        """Parser extracts all outputs listed in output_names from metadata."""
        result = {
            'detection_boxes': np.array([[[0.1, 0.2, 0.5, 0.6]]]),
            'detection_classes': np.array([[1.0]]),
            'detection_scores': np.array([[0.9]]),
            'num_detections': np.array([1]),
        }

        detections = handler._parse_detection_outputs(result)

        assert 'detection_boxes' in detections
        assert 'detection_classes' in detections
        assert 'detection_scores' in detections
        assert 'num_detections' in detections

    def test_returns_none_when_required_output_missing(self, handler):
        """Parser returns None when a required output is missing."""
        # Missing detection_scores
        result = {
            'detection_boxes': np.array([[[0.1, 0.2, 0.5, 0.6]]]),
            'detection_classes': np.array([[1.0]]),
            'num_detections': np.array([1]),
        }

        detections = handler._parse_detection_outputs(result)

        assert detections is None

    def test_handles_extra_outputs_gracefully(self, handler):
        """Parser handles extra outputs not in output_names."""
        result = {
            'detection_boxes': np.array([[[0.1, 0.2, 0.5, 0.6]]]),
            'detection_classes': np.array([[1.0]]),
            'detection_scores': np.array([[0.9]]),
            'num_detections': np.array([1]),
            'extra_output': np.array([42]),
        }

        detections = handler._parse_detection_outputs(result)

        assert detections is not None
        assert 'extra_output' not in detections

    def test_returns_none_when_boxes_missing(self, handler):
        """Parser returns None when detection_boxes is missing."""
        result = {
            'detection_classes': np.array([[1.0]]),
            'detection_scores': np.array([[0.9]]),
            'num_detections': np.array([1]),
        }

        detections = handler._parse_detection_outputs(result)

        assert detections is None

    def test_returns_none_when_classes_missing(self, handler):
        """Parser returns None when detection_classes is missing."""
        result = {
            'detection_boxes': np.array([[[0.1, 0.2, 0.5, 0.6]]]),
            'detection_scores': np.array([[0.9]]),
            'num_detections': np.array([1]),
        }

        detections = handler._parse_detection_outputs(result)

        assert detections is None


class TestApplyThresholdAndAnnotate:
    """Tests for _apply_threshold_and_annotate filtering and labeling.

    Requirement 6.3: Apply confidence threshold, annotate with labels.
    """

    def test_filters_below_confidence_threshold(self, handler):
        """Detections below confidence_threshold are filtered out."""
        detections = {
            'detection_boxes': np.array([[[0.1, 0.2, 0.5, 0.6],
                                          [0.3, 0.4, 0.7, 0.8]]]),
            'detection_classes': np.array([[1.0, 2.0]]),
            'detection_scores': np.array([[0.9, 0.3]]),  # 0.3 < 0.5 threshold
            'num_detections': np.array([2]),
        }
        image_rgb = np.zeros((480, 640, 3), dtype=np.uint8)

        results = handler._apply_threshold_and_annotate(detections, image_rgb)

        assert len(results) == 1
        assert results[0]['score'] == 0.9

    def test_maps_class_ids_to_labels(self, handler):
        """Class IDs are mapped to human-readable labels from labels_map."""
        detections = {
            'detection_boxes': np.array([[[0.1, 0.2, 0.5, 0.6]]]),
            'detection_classes': np.array([[1.0]]),  # class 1 = 'person'
            'detection_scores': np.array([[0.85]]),
            'num_detections': np.array([1]),
        }
        image_rgb = np.zeros((480, 640, 3), dtype=np.uint8)

        results = handler._apply_threshold_and_annotate(detections, image_rgb)

        assert results[0]['label'] == 'person'

    def test_uses_fallback_label_for_unknown_class(self, handler):
        """Unknown class IDs get a fallback label like 'class_99'."""
        detections = {
            'detection_boxes': np.array([[[0.1, 0.2, 0.5, 0.6]]]),
            'detection_classes': np.array([[99.0]]),  # Not in labels_map
            'detection_scores': np.array([[0.85]]),
            'num_detections': np.array([1]),
        }
        image_rgb = np.zeros((480, 640, 3), dtype=np.uint8)

        results = handler._apply_threshold_and_annotate(detections, image_rgb)

        assert results[0]['label'] == 'class_99'

    def test_converts_normalized_boxes_to_pixel_coordinates(self, handler):
        """Normalized box coordinates are converted to pixel coordinates."""
        detections = {
            'detection_boxes': np.array([[[0.1, 0.2, 0.5, 0.6]]]),
            'detection_classes': np.array([[1.0]]),
            'detection_scores': np.array([[0.9]]),
            'num_detections': np.array([1]),
        }
        # 480x640 image
        image_rgb = np.zeros((480, 640, 3), dtype=np.uint8)

        results = handler._apply_threshold_and_annotate(detections, image_rgb)

        box = results[0]['box']
        # ymin = 0.1 * 480 = 48.0, xmin = 0.2 * 640 = 128.0
        # ymax = 0.5 * 480 = 240.0, xmax = 0.6 * 640 = 384.0
        assert box['ymin'] == 48.0
        assert box['xmin'] == 128.0
        assert box['ymax'] == 240.0
        assert box['xmax'] == 384.0

    def test_returns_empty_list_when_all_below_threshold(self, handler):
        """Returns empty list when no detections exceed threshold."""
        detections = {
            'detection_boxes': np.array([[[0.1, 0.2, 0.5, 0.6]]]),
            'detection_classes': np.array([[1.0]]),
            'detection_scores': np.array([[0.2]]),  # Below 0.5 threshold
            'num_detections': np.array([1]),
        }
        image_rgb = np.zeros((480, 640, 3), dtype=np.uint8)

        results = handler._apply_threshold_and_annotate(detections, image_rgb)

        assert results == []

    def test_handles_multiple_detections(self, handler):
        """Multiple detections above threshold are all returned."""
        detections = {
            'detection_boxes': np.array([[[0.1, 0.2, 0.5, 0.6],
                                          [0.2, 0.3, 0.6, 0.7],
                                          [0.3, 0.4, 0.7, 0.8]]]),
            'detection_classes': np.array([[1.0, 2.0, 3.0]]),
            'detection_scores': np.array([[0.9, 0.8, 0.7]]),
            'num_detections': np.array([3]),
        }
        image_rgb = np.zeros((480, 640, 3), dtype=np.uint8)

        results = handler._apply_threshold_and_annotate(detections, image_rgb)

        assert len(results) == 3
        assert results[0]['label'] == 'person'
        assert results[1]['label'] == 'car'
        assert results[2]['label'] == 'bicycle'

    def test_handles_no_labels_map(self, handler):
        """When labels_map is None, uses fallback class_N labels."""
        handler.labels_map = None
        detections = {
            'detection_boxes': np.array([[[0.1, 0.2, 0.5, 0.6]]]),
            'detection_classes': np.array([[1.0]]),
            'detection_scores': np.array([[0.9]]),
            'num_detections': np.array([1]),
        }
        image_rgb = np.zeros((480, 640, 3), dtype=np.uint8)

        results = handler._apply_threshold_and_annotate(detections, image_rgb)

        assert results[0]['label'] == 'class_1'


class TestPublishDetections:
    """Tests for _publish_detections publishing to camera/detections via IoT Core.

    Requirement 6.2, 6.3: Publish detection results to camera/detections.
    """

    def test_publishes_to_configured_topic(self, handler, mock_ipc_client):
        """Detections are published to the configured pub_topic."""
        detection_results = [
            {'label': 'person', 'score': 0.9, 'box': {'ymin': 48.0, 'xmin': 128.0, 'ymax': 240.0, 'xmax': 384.0}},
        ]

        handler._publish_detections(detection_results)

        mock_ipc_client.publish_to_iot_core.assert_called_once()
        call_kwargs = mock_ipc_client.publish_to_iot_core.call_args.kwargs
        assert call_kwargs['topic_name'] == 'camera/detections'
        assert call_kwargs['qos'] == '1'

    def test_payload_contains_model_and_detections(self, handler, mock_ipc_client):
        """Published payload includes model ID, detections list, count, and threshold."""
        detection_results = [
            {'label': 'person', 'score': 0.9, 'box': {'ymin': 48.0, 'xmin': 128.0, 'ymax': 240.0, 'xmax': 384.0}},
            {'label': 'car', 'score': 0.7, 'box': {'ymin': 96.0, 'xmin': 192.0, 'ymax': 336.0, 'xmax': 448.0}},
        ]

        handler._publish_detections(detection_results)

        call_kwargs = mock_ipc_client.publish_to_iot_core.call_args.kwargs
        payload = json.loads(call_kwargs['payload'].decode('utf-8'))
        assert payload['model'] == 'faster-rcnn'
        assert payload['count'] == 2
        assert payload['threshold'] == 0.5
        assert len(payload['detections']) == 2
        assert payload['detections'][0]['label'] == 'person'

    def test_publishes_empty_detections(self, handler, mock_ipc_client):
        """Empty detection list is still published (count=0)."""
        handler._publish_detections([])

        mock_ipc_client.publish_to_iot_core.assert_called_once()
        call_kwargs = mock_ipc_client.publish_to_iot_core.call_args.kwargs
        payload = json.loads(call_kwargs['payload'].decode('utf-8'))
        assert payload['count'] == 0
        assert payload['detections'] == []

    def test_handles_publish_failure_gracefully(self, handler, mock_ipc_client):
        """Publishing failure is handled without raising."""
        mock_ipc_client.publish_to_iot_core.side_effect = Exception("Publish failed")

        # Should not raise
        handler._publish_detections([{'label': 'person', 'score': 0.9, 'box': {}}])

    def test_payload_serializes_numpy_types(self, handler, mock_ipc_client):
        """Payload correctly serializes numpy float/int types via NumpyEncoder."""
        detection_results = [
            {
                'label': 'person',
                'score': np.float32(0.9),
                'box': {
                    'ymin': np.float64(48.0),
                    'xmin': np.float64(128.0),
                    'ymax': np.float64(240.0),
                    'xmax': np.float64(384.0),
                },
            },
        ]

        handler._publish_detections(detection_results)

        call_kwargs = mock_ipc_client.publish_to_iot_core.call_args.kwargs
        # Should not raise - numpy types are serialized
        payload = json.loads(call_kwargs['payload'].decode('utf-8'))
        assert payload['detections'][0]['score'] == pytest.approx(0.9, abs=0.01)
