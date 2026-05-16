"""Unit tests for ClassificationHandler inference logic.

Tests image preprocessing, OVMS gRPC call, top-N extraction, publishing,
model metadata loading from shadow, and independent operation from DetectionHandler.

Requirements: 7.1, 7.2, 7.3, 7.4
"""

import sys
import os
import json
from unittest.mock import MagicMock, patch, call

import pytest
import numpy as np

# Add artifact path for imports
sys.path.insert(0, os.path.join(
    os.path.dirname(__file__), '..', 'greengrass-components', 'artifacts',
    'com.example.ClassificationHandler', '1.0.0'
))

# Mock the awsiot module before importing classification_handler
mock_clientv2 = MagicMock()
sys.modules['awsiot'] = MagicMock()
sys.modules['awsiot.greengrasscoreipc'] = MagicMock()
sys.modules['awsiot.greengrasscoreipc.clientv2'] = mock_clientv2
sys.modules['awsiot.greengrasscoreipc.model'] = MagicMock()

# Mock ovmsclient
mock_ovmsclient = MagicMock()
sys.modules['ovmsclient'] = mock_ovmsclient

# We need real cv2 and numpy for preprocessing tests
import cv2


@pytest.fixture
def mock_ipc_client():
    """Create a mock IPC client."""
    return MagicMock()


@pytest.fixture
def handler(mock_ipc_client):
    """Create a ClassificationHandler instance with mocked IPC."""
    mock_clientv2.GreengrassCoreIPCClientV2.return_value = mock_ipc_client

    with patch.dict(os.environ, {
        'AWS_IOT_THING_NAME': 'test-thing',
        'CLASSIFICATION_MODEL_ID': 'efficientnet',
        'MODEL_SERVER_URL': 'localhost:9000',
        'TOP_N': '5',
    }):
        from classification_handler import ClassificationHandler
        h = ClassificationHandler()
        h.ipc_client = mock_ipc_client
        h.model_metadata = {
            'model_name': 'efficientnet',
            'input_name': 'input',
            'output_names': ['predictions'],
            'input_shape': [1, 224, 224, 3],
            'labels_file': 'labels.txt',
            'local_path': '/snap/ovms-engine/components/model-efficientnet/',
        }
        h.labels = ['tench', 'goldfish', 'great white shark', 'tiger shark',
                    'hammerhead', 'electric ray', 'stingray', 'cock', 'hen', 'ostrich']
        yield h


class TestPreprocessImage:
    """Tests for image preprocessing according to input_shape."""

    def test_resizes_image_to_input_shape(self, handler, tmp_path):
        """Image is resized to match model's input_shape dimensions."""
        # Create a test image (100x150 RGB)
        test_image = np.random.randint(0, 255, (100, 150, 3), dtype=np.uint8)
        image_path = str(tmp_path / "test.jpg")
        cv2.imwrite(image_path, test_image)

        result = handler._preprocess_image(image_path)

        assert result is not None
        # input_shape is [1, 224, 224, 3] -> result should be (1, 224, 224, 3)
        assert result.shape == (1, 224, 224, 3)

    def test_normalizes_pixel_values(self, handler, tmp_path):
        """Pixel values are normalized to [0, 1] range."""
        # Create a white image (all 255)
        test_image = np.ones((50, 50, 3), dtype=np.uint8) * 255
        image_path = str(tmp_path / "white.jpg")
        cv2.imwrite(image_path, test_image)

        result = handler._preprocess_image(image_path)

        assert result is not None
        # After normalization, max value should be close to 1.0
        # (JPEG compression may slightly alter values)
        assert result.max() <= 1.0
        assert result.min() >= 0.0
        assert result.max() > 0.9  # Should be close to 1.0 for white image

    def test_output_dtype_is_float32(self, handler, tmp_path):
        """Output tensor has float32 dtype for model compatibility."""
        test_image = np.random.randint(0, 255, (80, 80, 3), dtype=np.uint8)
        image_path = str(tmp_path / "test.jpg")
        cv2.imwrite(image_path, test_image)

        result = handler._preprocess_image(image_path)

        assert result is not None
        assert result.dtype == np.float32

    def test_respects_custom_input_shape(self, handler, tmp_path):
        """Preprocessing uses the input_shape from model_metadata."""
        handler.model_metadata['input_shape'] = [1, 128, 128, 3]

        test_image = np.random.randint(0, 255, (200, 300, 3), dtype=np.uint8)
        image_path = str(tmp_path / "test.jpg")
        cv2.imwrite(image_path, test_image)

        result = handler._preprocess_image(image_path)

        assert result is not None
        assert result.shape == (1, 128, 128, 3)

    def test_returns_none_for_missing_image(self, handler):
        """Returns None when image file does not exist."""
        result = handler._preprocess_image("/nonexistent/path/image.jpg")
        assert result is None

    def test_adds_batch_dimension(self, handler, tmp_path):
        """Output has batch dimension as first axis."""
        test_image = np.random.randint(0, 255, (50, 50, 3), dtype=np.uint8)
        image_path = str(tmp_path / "test.jpg")
        cv2.imwrite(image_path, test_image)

        result = handler._preprocess_image(image_path)

        assert result is not None
        assert result.ndim == 4
        assert result.shape[0] == 1


class TestCallOvms:
    """Tests for OVMS gRPC call."""

    def test_calls_ovms_with_correct_parameters(self, handler):
        """OVMS is called with model_name and input_name from metadata."""
        mock_client = MagicMock()
        mock_predictions = np.array([[0.1, 0.8, 0.05, 0.03, 0.02]])
        mock_client.predict.return_value = {'predictions': mock_predictions}
        mock_ovmsclient.make_grpc_client.return_value = mock_client

        input_tensor = np.zeros((1, 224, 224, 3), dtype=np.float32)
        result = handler._call_ovms(input_tensor)

        mock_ovmsclient.make_grpc_client.assert_called_with('localhost:9000')
        mock_client.predict.assert_called_once()
        call_args = mock_client.predict.call_args
        assert call_args[0][1] == 'efficientnet'  # model_name
        assert 'input' in call_args[0][0]  # input_name as key

    def test_returns_predictions_from_named_output(self, handler):
        """Returns predictions using the output_name from metadata."""
        mock_client = MagicMock()
        expected = np.array([[0.1, 0.8, 0.05, 0.03, 0.02]])
        mock_client.predict.return_value = {'predictions': expected}
        mock_ovmsclient.make_grpc_client.return_value = mock_client

        input_tensor = np.zeros((1, 224, 224, 3), dtype=np.float32)
        result = handler._call_ovms(input_tensor)

        np.testing.assert_array_equal(result, expected)

    def test_returns_none_on_grpc_error(self, handler):
        """Returns None when gRPC call fails."""
        mock_client = MagicMock()
        mock_client.predict.side_effect = Exception("Connection refused")
        mock_ovmsclient.make_grpc_client.return_value = mock_client

        input_tensor = np.zeros((1, 224, 224, 3), dtype=np.float32)
        result = handler._call_ovms(input_tensor)

        assert result is None

    def test_returns_none_when_model_name_missing(self, handler):
        """Returns None when model_name is not in metadata."""
        handler.model_metadata['model_name'] = ''

        input_tensor = np.zeros((1, 224, 224, 3), dtype=np.float32)
        result = handler._call_ovms(input_tensor)

        assert result is None

    def test_returns_none_when_input_name_missing(self, handler):
        """Returns None when input_name is not in metadata."""
        handler.model_metadata['input_name'] = ''

        input_tensor = np.zeros((1, 224, 224, 3), dtype=np.float32)
        result = handler._call_ovms(input_tensor)

        assert result is None

    def test_fallback_to_first_result_key_when_no_output_names(self, handler):
        """Falls back to first result key when output_names is empty."""
        handler.model_metadata['output_names'] = []

        mock_client = MagicMock()
        expected = np.array([[0.5, 0.3, 0.2]])
        mock_client.predict.return_value = {'some_output': expected}
        mock_ovmsclient.make_grpc_client.return_value = mock_client

        input_tensor = np.zeros((1, 224, 224, 3), dtype=np.float32)
        result = handler._call_ovms(input_tensor)

        np.testing.assert_array_equal(result, expected)


class TestExtractTopN:
    """Tests for extracting top-N classifications from predictions."""

    def test_returns_top_5_by_default(self, handler):
        """Returns top-5 classifications sorted by confidence."""
        # 10 classes, indices 0-9
        probs = np.array([[0.01, 0.02, 0.5, 0.03, 0.04, 0.3, 0.05, 0.02, 0.02, 0.01]])

        result = handler._extract_top_n(probs)

        assert len(result) == 5
        # Top class should be index 2 (0.5)
        assert result[0]['class_index'] == 2
        assert result[0]['label'] == 'great white shark'
        assert result[0]['confidence'] == 0.5
        # Second should be index 5 (0.3)
        assert result[1]['class_index'] == 5
        assert result[1]['label'] == 'electric ray'
        assert result[1]['confidence'] == 0.3

    def test_results_sorted_by_confidence_descending(self, handler):
        """Results are sorted from highest to lowest confidence."""
        probs = np.array([[0.1, 0.4, 0.2, 0.15, 0.05, 0.03, 0.02, 0.02, 0.02, 0.01]])

        result = handler._extract_top_n(probs)

        confidences = [r['confidence'] for r in result]
        assert confidences == sorted(confidences, reverse=True)

    def test_maps_indices_to_labels(self, handler):
        """Class indices are correctly mapped to label strings."""
        probs = np.array([[0.9, 0.05, 0.03, 0.01, 0.005, 0.003, 0.001, 0.0005, 0.0003, 0.0002]])

        result = handler._extract_top_n(probs)

        assert result[0]['label'] == 'tench'  # index 0
        assert result[0]['class_index'] == 0

    def test_handles_index_beyond_labels(self, handler):
        """Uses fallback label when class index exceeds labels list."""
        # Only 10 labels loaded, but predictions have 15 classes
        probs = np.zeros(15)
        probs[12] = 0.9  # Index 12 has no label

        result = handler._extract_top_n(probs)

        assert result[0]['label'] == 'class_12'
        assert result[0]['class_index'] == 12

    def test_handles_1d_predictions(self, handler):
        """Works with 1D prediction array (no batch dimension)."""
        probs = np.array([0.1, 0.8, 0.05, 0.03, 0.02, 0.0, 0.0, 0.0, 0.0, 0.0])

        result = handler._extract_top_n(probs)

        assert len(result) == 5
        assert result[0]['class_index'] == 1
        assert result[0]['label'] == 'goldfish'

    def test_respects_top_n_setting(self, handler):
        """Returns only top_n results."""
        handler.top_n = 3
        probs = np.array([[0.1, 0.2, 0.3, 0.15, 0.05, 0.05, 0.05, 0.05, 0.03, 0.02]])

        result = handler._extract_top_n(probs)

        assert len(result) == 3

    def test_handles_fewer_classes_than_top_n(self, handler):
        """Handles case where number of classes is less than top_n."""
        handler.top_n = 10
        probs = np.array([[0.6, 0.3, 0.1]])
        handler.labels = ['cat', 'dog', 'bird']

        result = handler._extract_top_n(probs)

        assert len(result) == 3


class TestPublishClassifications:
    """Tests for publishing classification results to IoT Core."""

    def test_publishes_to_correct_topic(self, handler, mock_ipc_client):
        """Results are published to camera/classifications via IoT Core."""
        classifications = [
            {'label': 'goldfish', 'confidence': 0.85, 'class_index': 1},
            {'label': 'tench', 'confidence': 0.10, 'class_index': 0},
        ]

        handler._publish_classifications(classifications)

        mock_ipc_client.publish_to_iot_core.assert_called_once()
        call_kwargs = mock_ipc_client.publish_to_iot_core.call_args.kwargs
        assert call_kwargs['topic_name'] == 'camera/classifications'
        assert call_kwargs['qos'] == '1'

    def test_payload_contains_model_and_classifications(self, handler, mock_ipc_client):
        """Published payload includes model name, classifications, and timestamp."""
        classifications = [
            {'label': 'goldfish', 'confidence': 0.85, 'class_index': 1},
        ]

        handler._publish_classifications(classifications)

        call_kwargs = mock_ipc_client.publish_to_iot_core.call_args.kwargs
        payload = json.loads(call_kwargs['payload'])
        assert payload['model'] == 'efficientnet'
        assert payload['classifications'] == classifications
        assert 'timestamp' in payload

    def test_handles_publish_failure(self, handler, mock_ipc_client):
        """Handler does not crash when publish fails."""
        mock_ipc_client.publish_to_iot_core.side_effect = Exception("Publish failed")

        classifications = [
            {'label': 'goldfish', 'confidence': 0.85, 'class_index': 1},
        ]

        # Should not raise
        handler._publish_classifications(classifications)


class TestRunClassification:
    """Tests for the end-to-end classification flow."""

    def test_skips_when_no_model_metadata(self, handler):
        """Skips classification when model_metadata is not loaded."""
        handler.model_metadata = None

        # Should not raise
        handler._run_classification({'image_path': '/some/image.jpg'})

    def test_skips_when_no_image_path(self, handler):
        """Skips classification when message has no image_path."""
        handler._run_classification({})

    def test_full_pipeline(self, handler, mock_ipc_client, tmp_path):
        """End-to-end: preprocess -> OVMS call -> extract top-N -> publish."""
        # Create a test image
        test_image = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)
        image_path = str(tmp_path / "test.jpg")
        cv2.imwrite(image_path, test_image)

        # Mock OVMS response
        mock_client = MagicMock()
        predictions = np.zeros((1, 10))
        predictions[0, 1] = 0.85  # goldfish
        predictions[0, 0] = 0.10  # tench
        predictions[0, 3] = 0.03  # tiger shark
        predictions[0, 2] = 0.01  # great white shark
        predictions[0, 4] = 0.005  # hammerhead
        mock_client.predict.return_value = {'predictions': predictions}
        mock_ovmsclient.make_grpc_client.return_value = mock_client

        handler._run_classification({'image_path': image_path})

        # Verify publish was called
        mock_ipc_client.publish_to_iot_core.assert_called_once()
        call_kwargs = mock_ipc_client.publish_to_iot_core.call_args.kwargs
        payload = json.loads(call_kwargs['payload'])

        assert payload['model'] == 'efficientnet'
        assert len(payload['classifications']) == 5
        assert payload['classifications'][0]['label'] == 'goldfish'
        assert payload['classifications'][0]['confidence'] == 0.85



class TestModelMetadataFromShadow:
    """Tests for loading model metadata from the device shadow.

    Validates Requirement 7.1: ClassificationHandler reads model_metadata
    from the model-config shadow reported state.
    """

    def test_reads_metadata_from_shadow_reported_state(self, handler, mock_ipc_client):
        """Successfully reads model_metadata when model status is 'ready'."""
        shadow_payload = json.dumps({
            "state": {
                "reported": {
                    "models": {
                        "efficientnet": {
                            "status": "ready",
                            "model_metadata": {
                                "model_name": "efficientnet",
                                "input_name": "input",
                                "output_names": ["predictions"],
                                "input_shape": [1, 224, 224, 3],
                                "labels_file": "labels.txt",
                                "local_path": "/snap/ovms-engine/components/model-efficientnet/",
                            }
                        }
                    }
                }
            }
        }).encode("utf-8")

        mock_response = MagicMock()
        mock_response.payload = shadow_payload
        mock_ipc_client.get_thing_shadow.return_value = mock_response

        result = handler._read_model_metadata_from_shadow()

        assert result is not None
        assert result["model_name"] == "efficientnet"
        assert result["input_name"] == "input"
        assert result["output_names"] == ["predictions"]
        assert result["input_shape"] == [1, 224, 224, 3]
        mock_ipc_client.get_thing_shadow.assert_called_with(
            thing_name="test-thing", shadow_name="model-config"
        )

    def test_returns_none_when_model_not_in_shadow(self, handler, mock_ipc_client):
        """Returns None when the assigned model is not in the shadow."""
        shadow_payload = json.dumps({
            "state": {
                "reported": {
                    "models": {
                        "other-model": {
                            "status": "ready",
                            "model_metadata": {"model_name": "other"}
                        }
                    }
                }
            }
        }).encode("utf-8")

        mock_response = MagicMock()
        mock_response.payload = shadow_payload
        mock_ipc_client.get_thing_shadow.return_value = mock_response

        result = handler._read_model_metadata_from_shadow()
        assert result is None

    def test_returns_none_when_model_status_not_ready(self, handler, mock_ipc_client):
        """Returns None when model status is 'installing' (not yet ready)."""
        shadow_payload = json.dumps({
            "state": {
                "reported": {
                    "models": {
                        "efficientnet": {
                            "status": "installing",
                            "model_metadata": None
                        }
                    }
                }
            }
        }).encode("utf-8")

        mock_response = MagicMock()
        mock_response.payload = shadow_payload
        mock_ipc_client.get_thing_shadow.return_value = mock_response

        result = handler._read_model_metadata_from_shadow()
        assert result is None

    def test_returns_none_when_shadow_read_fails(self, handler, mock_ipc_client):
        """Returns None gracefully when shadow IPC call fails."""
        mock_ipc_client.get_thing_shadow.side_effect = Exception("IPC timeout")

        result = handler._read_model_metadata_from_shadow()
        assert result is None

    def test_returns_none_when_thing_name_not_set(self, mock_ipc_client):
        """Returns None when AWS_IOT_THING_NAME is not set."""
        mock_clientv2.GreengrassCoreIPCClientV2.return_value = mock_ipc_client

        with patch.dict(os.environ, {
            'AWS_IOT_THING_NAME': '',
            'CLASSIFICATION_MODEL_ID': 'efficientnet',
            'MODEL_SERVER_URL': 'localhost:9000',
            'TOP_N': '5',
        }):
            from classification_handler import ClassificationHandler
            h = ClassificationHandler()
            h.ipc_client = mock_ipc_client

            result = h._read_model_metadata_from_shadow()
            assert result is None
            mock_ipc_client.get_thing_shadow.assert_not_called()

    def test_returns_none_when_model_ready_but_no_metadata(self, handler, mock_ipc_client):
        """Returns None when model is ready but model_metadata field is missing."""
        shadow_payload = json.dumps({
            "state": {
                "reported": {
                    "models": {
                        "efficientnet": {
                            "status": "ready"
                            # model_metadata key is absent
                        }
                    }
                }
            }
        }).encode("utf-8")

        mock_response = MagicMock()
        mock_response.payload = shadow_payload
        mock_ipc_client.get_thing_shadow.return_value = mock_response

        result = handler._read_model_metadata_from_shadow()
        assert result is None

    def test_loads_labels_after_metadata(self, handler, mock_ipc_client, tmp_path):
        """Labels are loaded from the path specified in model_metadata."""
        labels_dir = tmp_path / "model"
        labels_dir.mkdir()
        labels_file = labels_dir / "labels.txt"
        labels_file.write_text("cat\ndog\nbird\n")

        handler.model_metadata = {
            "model_name": "efficientnet",
            "input_name": "input",
            "output_names": ["predictions"],
            "input_shape": [1, 224, 224, 3],
            "labels_file": "labels.txt",
            "local_path": str(labels_dir),
        }

        handler._load_labels()

        assert handler.labels == ["cat", "dog", "bird"]

    def test_labels_empty_when_file_not_found(self, handler):
        """Labels list is empty when labels file does not exist."""
        handler.model_metadata = {
            "model_name": "efficientnet",
            "input_name": "input",
            "output_names": ["predictions"],
            "input_shape": [1, 224, 224, 3],
            "labels_file": "labels.txt",
            "local_path": "/nonexistent/path/",
        }

        handler._load_labels()

        assert handler.labels == []


class TestIndependentFromDetectionHandler:
    """Tests that ClassificationHandler operates independently from DetectionHandler.

    Validates Requirement 7.4: ClassificationHandler operates independently,
    subscribing to the same camera images but publishing to a different topic.
    """

    def test_publishes_to_classifications_topic_not_detections(self, handler):
        """ClassificationHandler publishes to camera/classifications, not camera/detections."""
        assert handler.pub_topic == "camera/classifications"
        assert handler.pub_topic != "camera/detections"

    def test_subscribes_to_same_camera_images_topic(self, handler):
        """ClassificationHandler subscribes to camera/images (same as DetectionHandler)."""
        assert handler.sub_topic == "camera/images"

    def test_uses_classification_model_id_not_detection(self, handler):
        """ClassificationHandler uses CLASSIFICATION_MODEL_ID, not DETECTION_MODEL_ID."""
        assert handler.classification_model_id == "efficientnet"
        # Verify it reads from a different env var than DetectionHandler
        assert hasattr(handler, 'classification_model_id')
        assert not hasattr(handler, 'detection_model_id')

    def test_separate_model_metadata_from_shadow(self, handler, mock_ipc_client):
        """ClassificationHandler reads its own model's metadata from shadow independently."""
        shadow_payload = json.dumps({
            "state": {
                "reported": {
                    "models": {
                        "faster-rcnn": {
                            "status": "ready",
                            "model_metadata": {
                                "model_name": "faster_rcnn",
                                "input_name": "input_tensor",
                                "output_names": ["detection_boxes", "detection_classes",
                                                 "detection_scores", "num_detections"],
                                "input_shape": [1, 255, 255, 3],
                                "labels_file": "labels.txt",
                                "local_path": "/snap/ovms-engine/components/model-faster-rcnn/",
                            }
                        },
                        "efficientnet": {
                            "status": "ready",
                            "model_metadata": {
                                "model_name": "efficientnet",
                                "input_name": "input",
                                "output_names": ["predictions"],
                                "input_shape": [1, 224, 224, 3],
                                "labels_file": "labels.txt",
                                "local_path": "/snap/ovms-engine/components/model-efficientnet/",
                            }
                        }
                    }
                }
            }
        }).encode("utf-8")

        mock_response = MagicMock()
        mock_response.payload = shadow_payload
        mock_ipc_client.get_thing_shadow.return_value = mock_response

        # ClassificationHandler should only read its own model (efficientnet)
        result = handler._read_model_metadata_from_shadow()

        assert result is not None
        assert result["model_name"] == "efficientnet"
        assert result["output_names"] == ["predictions"]
        # It should NOT return the detection model's metadata
        assert "detection_boxes" not in result.get("output_names", [])

    def test_classification_output_format_differs_from_detection(self, handler, mock_ipc_client):
        """Classification output is top-N labels with confidence, not bounding boxes."""
        classifications = [
            {'label': 'goldfish', 'confidence': 0.85, 'class_index': 1},
            {'label': 'tench', 'confidence': 0.10, 'class_index': 0},
        ]

        handler._publish_classifications(classifications)

        call_kwargs = mock_ipc_client.publish_to_iot_core.call_args.kwargs
        payload = json.loads(call_kwargs['payload'])

        # Classification output has 'classifications' key, not 'detections'
        assert 'classifications' in payload
        assert 'detections' not in payload
        # Each classification has label + confidence, not bounding boxes
        assert 'label' in payload['classifications'][0]
        assert 'confidence' in payload['classifications'][0]
        assert 'box' not in payload['classifications'][0]
