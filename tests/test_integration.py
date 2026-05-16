"""End-to-end integration test with both models running simultaneously.

Verifies the full flow:
1. ModelManagerCore receives a shadow delta with two models (faster-rcnn + efficientnet)
2. Both models get installed (snap install mocked)
3. OVMS config is generated with both models listed
4. Both handlers (DetectionHandler, ClassificationHandler) read model metadata from shadow
5. Both handlers process an image and produce output to their respective topics

External dependencies (Greengrass IPC, OVMS gRPC, snap commands) are mocked.
Real cv2 is used for image processing.
"""

import sys
import os
import json
from unittest.mock import MagicMock, patch

import pytest
import numpy as np
import cv2

# Add artifact paths for imports
sys.path.insert(0, os.path.join(
    os.path.dirname(__file__), '..', 'greengrass-components', 'artifacts',
    'com.example.ModelManagerCore', '1.0.0'
))
sys.path.insert(0, os.path.join(
    os.path.dirname(__file__), '..', 'greengrass-components', 'artifacts',
    'com.example.DetectionHandler', '1.0.0'
))
sys.path.insert(0, os.path.join(
    os.path.dirname(__file__), '..', 'greengrass-components', 'artifacts',
    'com.example.ClassificationHandler', '1.0.0'
))
sys.path.insert(0, os.path.join(
    os.path.dirname(__file__), '..', 'greengrass-components', 'shared'
))

# Mock external dependencies before importing components
mock_clientv2 = MagicMock()
sys.modules.setdefault('awsiot', MagicMock())
sys.modules.setdefault('awsiot.greengrasscoreipc', MagicMock())
sys.modules.setdefault('awsiot.greengrasscoreipc.clientv2', mock_clientv2)
sys.modules.setdefault('awsiot.greengrasscoreipc.model', MagicMock())
sys.modules.setdefault('ovmsclient', MagicMock())


FASTER_RCNN_MANIFEST = {
    "model_id": "faster-rcnn",
    "model_name": "faster_rcnn",
    "version": "1.0.0",
    "input_name": "input_tensor",
    "output_names": ["detection_boxes", "detection_classes", "detection_scores", "num_detections"],
    "input_shape": [1, 255, 255, 3],
    "labels_file": "labels.txt",
}

EFFICIENTNET_MANIFEST = {
    "model_id": "efficientnet",
    "model_name": "efficientnet",
    "version": "1.0.0",
    "input_name": "input",
    "output_names": ["predictions"],
    "input_shape": [1, 224, 224, 3],
    "labels_file": "labels.txt",
}

DETECTION_LABELS = "person\nbicycle\ncar\nmotorcycle\nairplane\n"
CLASSIFICATION_LABELS = "tench\ngoldfish\ngreat white shark\ntiger shark\nhammerhead\n"


@pytest.fixture
def temp_dirs(tmp_path):
    """Create temporary directories simulating the content interface mount point structure.

    With the content interface, the Greengrass snap mounts ovms-engine's directories
    at separate paths (not nested):
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

    # Create model directories with manifests and labels
    faster_rcnn_dir = snap_components / "model-faster-rcnn"
    faster_rcnn_dir.mkdir()
    (faster_rcnn_dir / "manifest.json").write_text(json.dumps(FASTER_RCNN_MANIFEST))
    (faster_rcnn_dir / "labels.txt").write_text(DETECTION_LABELS)

    efficientnet_dir = snap_components / "model-efficientnet"
    efficientnet_dir.mkdir()
    (efficientnet_dir / "manifest.json").write_text(json.dumps(EFFICIENTNET_MANIFEST))
    (efficientnet_dir / "labels.txt").write_text(CLASSIFICATION_LABELS)

    return {
        "snap_components": str(snap_components),
        "snap_common": str(snap_common),
        "config_dir": str(config_dir),
        "faster_rcnn_dir": str(faster_rcnn_dir),
        "efficientnet_dir": str(efficientnet_dir),
    }


@pytest.fixture
def test_image(tmp_path):
    """Create a real test image using cv2."""
    image = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
    image_path = str(tmp_path / "test_frame.jpg")
    cv2.imwrite(image_path, image)
    return image_path


@pytest.fixture
def mock_ipc():
    """Create a mock IPC client shared across all components."""
    mock = MagicMock()
    mock.get_thing_shadow.side_effect = Exception("ResourceNotFoundException")
    return mock


def _read_ovms_config(config_dir):
    """Read and parse the OVMS config file."""
    config_path = os.path.join(config_dir, "models_config.json")
    if not os.path.exists(config_path):
        return None
    with open(config_path) as f:
        return json.load(f)


def _get_reported_models(mock_ipc):
    """Extract the last reported models from shadow update calls."""
    calls = mock_ipc.update_thing_shadow.call_args_list
    if not calls:
        return {}
    payload = json.loads(calls[-1].kwargs['payload'])
    return payload.get('state', {}).get('reported', {}).get('models', {})


def _make_shadow_response(models_dict):
    """Create a mock shadow response with the given models in reported state."""
    response = MagicMock()
    response.payload = json.dumps({
        "state": {"reported": {"models": models_dict}}
    }).encode('utf-8')
    return response


class TestEndToEndBothModels:
    """End-to-end test: shadow delta with two models through full pipeline."""

    def test_shadow_delta_installs_both_models_and_generates_ovms_config(
        self, temp_dirs, mock_ipc
    ):
        """Shadow update with two models installs both and OVMS config contains both."""
        mock_clientv2.GreengrassCoreIPCClientV2.return_value = mock_ipc

        with patch.dict(os.environ, {
            'AWS_IOT_THING_NAME': 'test-device',
            'SNAP_COMPONENTS': temp_dirs['snap_components'],
            'SNAP_COMMON': temp_dirs['snap_common'],
            'OVMS_CONFIG_DIR': temp_dirs['config_dir'],
        }):
            from model_manager_core import ModelManagerCore
            manager = ModelManagerCore()
            manager.ipc_client = mock_ipc

        # Simulate shadow delta with both models
        manager.snapd = MagicMock()
        manager.snapd.install_component = MagicMock(return_value={})

        delta_event = MagicMock()
        delta_event.message.payload = json.dumps({
            "state": {
                "models": {
                    "faster-rcnn": {"source": "snap"},
                    "efficientnet": {"source": "snap"},
                }
            }
        }).encode('utf-8')

        manager._on_shadow_delta(delta_event)

        # Verify snapd install_component called for both models
        install_calls = manager.snapd.install_component.call_args_list
        called_components = [c[0][1] for c in install_calls]
        assert 'model-faster-rcnn' in called_components
        assert 'model-efficientnet' in called_components

        # Verify OVMS config contains both models
        config = _read_ovms_config(temp_dirs['config_dir'])
        assert config is not None
        assert len(config['model_config_list']) == 2
        model_names = {
            entry['config']['name'] for entry in config['model_config_list']
        }
        assert model_names == {'faster_rcnn', 'efficientnet'}

        # Verify both models reported as ready
        reported = _get_reported_models(mock_ipc)
        assert reported['faster-rcnn']['status'] == 'ready'
        assert reported['efficientnet']['status'] == 'ready'

        # Verify model metadata is correct
        assert reported['faster-rcnn']['model_metadata']['model_name'] == 'faster_rcnn'
        assert reported['faster-rcnn']['model_metadata']['input_name'] == 'input_tensor'
        assert reported['efficientnet']['model_metadata']['model_name'] == 'efficientnet'
        assert reported['efficientnet']['model_metadata']['input_name'] == 'input'

    def test_detection_handler_reads_shadow_and_produces_output(
        self, temp_dirs, test_image, mock_ipc
    ):
        """DetectionHandler reads model metadata from shadow and publishes detections."""
        shadow_response = _make_shadow_response({
            "faster-rcnn": {
                "status": "ready",
                "model_metadata": {
                    "model_name": "faster_rcnn",
                    "input_name": "input_tensor",
                    "output_names": ["detection_boxes", "detection_classes",
                                     "detection_scores", "num_detections"],
                    "input_shape": [1, 255, 255, 3],
                    "labels_file": "labels.txt",
                    "local_path": temp_dirs['faster_rcnn_dir'],
                },
            },
            "efficientnet": {
                "status": "ready",
                "model_metadata": {
                    "model_name": "efficientnet",
                    "input_name": "input",
                    "output_names": ["predictions"],
                    "input_shape": [1, 224, 224, 3],
                    "labels_file": "labels.txt",
                    "local_path": temp_dirs['efficientnet_dir'],
                },
            },
        })
        mock_ipc.get_thing_shadow.side_effect = None
        mock_ipc.get_thing_shadow.return_value = shadow_response
        mock_clientv2.GreengrassCoreIPCClientV2.return_value = mock_ipc

        # Mock OVMS gRPC client to return detection results
        mock_grpc_client = MagicMock()
        mock_grpc_client.predict.return_value = {
            "detection_boxes": np.array([[[0.1, 0.2, 0.5, 0.6],
                                          [0.3, 0.4, 0.7, 0.8],
                                          [0.0, 0.0, 0.0, 0.0]]]),
            "detection_classes": np.array([[1, 3, 0]]),
            "detection_scores": np.array([[0.95, 0.80, 0.1]]),
            "num_detections": np.array([2]),
        }

        with patch.dict(os.environ, {
            'AWS_IOT_THING_NAME': 'test-device',
            'DETECTION_MODEL_ID': 'faster-rcnn',
            'MODEL_SERVER_URL': 'localhost:9000',
        }):
            from detection_handler import DetectionHandler
            handler = DetectionHandler()
            handler.ipc_client = mock_ipc

        # Load model metadata
        handler._wait_for_model_ready()

        assert handler.model_metadata is not None
        assert handler.model_name == 'faster_rcnn'
        assert handler.input_name == 'input_tensor'
        assert handler.labels_map is not None
        assert handler.labels_map[1] == 'person'
        assert handler.labels_map[3] == 'car'

        # Process an image with patched make_grpc_client
        with patch('detection_handler.make_grpc_client', return_value=mock_grpc_client):
            handler._run_inference({"image_path": test_image})

        # Verify OVMS was called with correct model name and input
        mock_grpc_client.predict.assert_called_once()
        predict_args = mock_grpc_client.predict.call_args
        assert predict_args[0][1] == 'faster_rcnn'
        input_data = predict_args[0][0]
        assert 'input_tensor' in input_data
        assert input_data['input_tensor'].shape == (1, 255, 255, 3)

        # Verify detections published to camera/detections
        publish_calls = [
            c for c in mock_ipc.publish_to_iot_core.call_args_list
            if c.kwargs.get('topic_name') == 'camera/detections'
        ]
        assert len(publish_calls) == 1
        published_payload = json.loads(publish_calls[0].kwargs['payload'])
        assert published_payload['model'] == 'faster-rcnn'
        assert len(published_payload['detections']) == 2
        assert published_payload['detections'][0]['label'] == 'person'
        assert published_payload['detections'][0]['score'] == 0.95

    def test_classification_handler_reads_shadow_and_produces_output(
        self, temp_dirs, test_image, mock_ipc
    ):
        """ClassificationHandler reads model metadata from shadow and publishes classifications."""
        shadow_response = _make_shadow_response({
            "faster-rcnn": {
                "status": "ready",
                "model_metadata": {
                    "model_name": "faster_rcnn",
                    "input_name": "input_tensor",
                    "output_names": ["detection_boxes", "detection_classes",
                                     "detection_scores", "num_detections"],
                    "input_shape": [1, 255, 255, 3],
                    "labels_file": "labels.txt",
                    "local_path": temp_dirs['faster_rcnn_dir'],
                },
            },
            "efficientnet": {
                "status": "ready",
                "model_metadata": {
                    "model_name": "efficientnet",
                    "input_name": "input",
                    "output_names": ["predictions"],
                    "input_shape": [1, 224, 224, 3],
                    "labels_file": "labels.txt",
                    "local_path": temp_dirs['efficientnet_dir'],
                },
            },
        })
        mock_ipc.get_thing_shadow.side_effect = None
        mock_ipc.get_thing_shadow.return_value = shadow_response
        mock_clientv2.GreengrassCoreIPCClientV2.return_value = mock_ipc

        # Mock OVMS gRPC client to return classification probabilities
        mock_grpc_client = MagicMock()
        probs = np.array([[0.05, 0.70, 0.10, 0.08, 0.07]])
        mock_grpc_client.predict.return_value = {"predictions": probs}

        with patch.dict(os.environ, {
            'AWS_IOT_THING_NAME': 'test-device',
            'CLASSIFICATION_MODEL_ID': 'efficientnet',
            'MODEL_SERVER_URL': 'localhost:9000',
            'TOP_N': '3',
        }):
            from classification_handler import ClassificationHandler
            handler = ClassificationHandler()
            handler.ipc_client = mock_ipc

        # Load model metadata
        handler._wait_for_model_ready()

        assert handler.model_metadata is not None
        assert handler.model_metadata['model_name'] == 'efficientnet'
        assert handler.model_metadata['input_name'] == 'input'
        assert len(handler.labels) == 5

        # Process an image with patched make_grpc_client
        with patch('classification_handler.make_grpc_client', return_value=mock_grpc_client):
            handler._run_classification({"image_path": test_image})

        # Verify OVMS was called with correct model name and input
        mock_grpc_client.predict.assert_called_once()
        predict_args = mock_grpc_client.predict.call_args
        assert predict_args[0][1] == 'efficientnet'
        input_data = predict_args[0][0]
        assert 'input' in input_data
        assert input_data['input'].shape == (1, 224, 224, 3)

        # Verify classifications published to camera/classifications
        publish_calls = [
            c for c in mock_ipc.publish_to_iot_core.call_args_list
            if c.kwargs.get('topic_name') == 'camera/classifications'
        ]
        assert len(publish_calls) == 1
        published_payload = json.loads(publish_calls[0].kwargs['payload'])
        assert published_payload['model'] == 'efficientnet'
        assert len(published_payload['classifications']) == 3
        # Top classification should be goldfish (index 1, highest prob 0.70)
        assert published_payload['classifications'][0]['label'] == 'goldfish'
        assert published_payload['classifications'][0]['confidence'] == 0.7

    def test_both_handlers_operate_independently_on_same_image(
        self, temp_dirs, test_image, mock_ipc
    ):
        """Both handlers process the same image independently, publishing to different topics."""
        shadow_response = _make_shadow_response({
            "faster-rcnn": {
                "status": "ready",
                "model_metadata": {
                    "model_name": "faster_rcnn",
                    "input_name": "input_tensor",
                    "output_names": ["detection_boxes", "detection_classes",
                                     "detection_scores", "num_detections"],
                    "input_shape": [1, 255, 255, 3],
                    "labels_file": "labels.txt",
                    "local_path": temp_dirs['faster_rcnn_dir'],
                },
            },
            "efficientnet": {
                "status": "ready",
                "model_metadata": {
                    "model_name": "efficientnet",
                    "input_name": "input",
                    "output_names": ["predictions"],
                    "input_shape": [1, 224, 224, 3],
                    "labels_file": "labels.txt",
                    "local_path": temp_dirs['efficientnet_dir'],
                },
            },
        })
        mock_ipc.get_thing_shadow.side_effect = None
        mock_ipc.get_thing_shadow.return_value = shadow_response
        mock_clientv2.GreengrassCoreIPCClientV2.return_value = mock_ipc

        # Create separate mock gRPC clients for each handler
        detection_grpc = MagicMock()
        detection_grpc.predict.return_value = {
            "detection_boxes": np.array([[[0.1, 0.2, 0.5, 0.6]]]),
            "detection_classes": np.array([[1]]),
            "detection_scores": np.array([[0.92]]),
            "num_detections": np.array([1]),
        }

        classification_grpc = MagicMock()
        classification_grpc.predict.return_value = {
            "predictions": np.array([[0.8, 0.1, 0.05, 0.03, 0.02]])
        }

        # Set up detection handler
        with patch.dict(os.environ, {
            'AWS_IOT_THING_NAME': 'test-device',
            'DETECTION_MODEL_ID': 'faster-rcnn',
            'MODEL_SERVER_URL': 'localhost:9000',
        }):
            from detection_handler import DetectionHandler
            det_handler = DetectionHandler()
            det_handler.ipc_client = mock_ipc

        # Set up classification handler
        with patch.dict(os.environ, {
            'AWS_IOT_THING_NAME': 'test-device',
            'CLASSIFICATION_MODEL_ID': 'efficientnet',
            'MODEL_SERVER_URL': 'localhost:9000',
            'TOP_N': '5',
        }):
            from classification_handler import ClassificationHandler
            cls_handler = ClassificationHandler()
            cls_handler.ipc_client = mock_ipc

        # Both handlers load metadata from the same shadow
        det_handler._wait_for_model_ready()
        cls_handler._wait_for_model_ready()

        # Reset publish call tracking
        mock_ipc.publish_to_iot_core.reset_mock()

        # Both handlers process the same image with their respective gRPC clients
        with patch('detection_handler.make_grpc_client', return_value=detection_grpc):
            det_handler._run_inference({"image_path": test_image})

        with patch('classification_handler.make_grpc_client', return_value=classification_grpc):
            cls_handler._run_classification({"image_path": test_image})

        # Verify both published to their respective topics
        publish_calls = mock_ipc.publish_to_iot_core.call_args_list
        topics_published = [c.kwargs['topic_name'] for c in publish_calls]
        assert 'camera/detections' in topics_published
        assert 'camera/classifications' in topics_published

        # Verify detection output
        det_call = next(
            c for c in publish_calls if c.kwargs['topic_name'] == 'camera/detections'
        )
        det_payload = json.loads(det_call.kwargs['payload'])
        assert det_payload['model'] == 'faster-rcnn'
        assert det_payload['detections'][0]['label'] == 'person'
        assert det_payload['detections'][0]['score'] == 0.92

        # Verify classification output
        cls_call = next(
            c for c in publish_calls
            if c.kwargs['topic_name'] == 'camera/classifications'
        )
        cls_payload = json.loads(cls_call.kwargs['payload'])
        assert cls_payload['model'] == 'efficientnet'
        assert cls_payload['classifications'][0]['label'] == 'tench'
        assert cls_payload['classifications'][0]['confidence'] == 0.8

    def test_full_pipeline_shadow_to_inference(self, temp_dirs, test_image, mock_ipc):
        """Full pipeline: shadow delta -> install both -> config generated -> both handlers infer."""
        mock_clientv2.GreengrassCoreIPCClientV2.return_value = mock_ipc

        # Phase 1: ModelManagerCore installs both models from shadow delta
        with patch.dict(os.environ, {
            'AWS_IOT_THING_NAME': 'test-device',
            'SNAP_COMPONENTS': temp_dirs['snap_components'],
            'SNAP_COMMON': temp_dirs['snap_common'],
            'OVMS_CONFIG_DIR': temp_dirs['config_dir'],
        }):
            from model_manager_core import ModelManagerCore
            manager = ModelManagerCore()
            manager.ipc_client = mock_ipc

        manager.snapd = MagicMock()
        manager.snapd.install_component = MagicMock(return_value={})

        delta_event = MagicMock()
        delta_event.message.payload = json.dumps({
            "state": {
                "models": {
                    "faster-rcnn": {"source": "snap"},
                    "efficientnet": {"source": "snap"},
                }
            }
        }).encode('utf-8')
        manager._on_shadow_delta(delta_event)

        # Verify OVMS config has both models
        config = _read_ovms_config(temp_dirs['config_dir'])
        assert len(config['model_config_list']) == 2
        config_names = {e['config']['name'] for e in config['model_config_list']}
        assert config_names == {'faster_rcnn', 'efficientnet'}

        # Phase 2: Set up shadow response as if ModelManager has reported both ready
        shadow_with_both_ready = MagicMock()
        shadow_with_both_ready.payload = json.dumps({
            "state": {"reported": {"models": manager.reported_models}}
        }).encode('utf-8')
        mock_ipc.get_thing_shadow.side_effect = None
        mock_ipc.get_thing_shadow.return_value = shadow_with_both_ready

        # Phase 3: DetectionHandler reads shadow and processes image
        with patch.dict(os.environ, {
            'AWS_IOT_THING_NAME': 'test-device',
            'DETECTION_MODEL_ID': 'faster-rcnn',
            'MODEL_SERVER_URL': 'localhost:9000',
        }):
            from detection_handler import DetectionHandler
            det_handler = DetectionHandler()
            det_handler.ipc_client = mock_ipc

        det_handler._wait_for_model_ready()
        assert det_handler.model_name == 'faster_rcnn'

        # Phase 4: ClassificationHandler reads shadow and processes image
        with patch.dict(os.environ, {
            'AWS_IOT_THING_NAME': 'test-device',
            'CLASSIFICATION_MODEL_ID': 'efficientnet',
            'MODEL_SERVER_URL': 'localhost:9000',
            'TOP_N': '3',
        }):
            from classification_handler import ClassificationHandler
            cls_handler = ClassificationHandler()
            cls_handler.ipc_client = mock_ipc

        cls_handler._wait_for_model_ready()
        assert cls_handler.model_metadata['model_name'] == 'efficientnet'

        # Phase 5: Both handlers run inference on the same image
        mock_ipc.publish_to_iot_core.reset_mock()

        # Detection inference
        det_grpc = MagicMock()
        det_grpc.predict.return_value = {
            "detection_boxes": np.array([[[0.2, 0.3, 0.8, 0.9]]]),
            "detection_classes": np.array([[3]]),
            "detection_scores": np.array([[0.88]]),
            "num_detections": np.array([1]),
        }
        with patch('detection_handler.make_grpc_client', return_value=det_grpc):
            det_handler._run_inference({"image_path": test_image})

        # Classification inference
        cls_grpc = MagicMock()
        cls_grpc.predict.return_value = {
            "predictions": np.array([[0.02, 0.05, 0.85, 0.05, 0.03]])
        }
        with patch('classification_handler.make_grpc_client', return_value=cls_grpc):
            cls_handler._run_classification({"image_path": test_image})

        # Verify both handlers published independently
        publish_calls = mock_ipc.publish_to_iot_core.call_args_list
        topics = [c.kwargs['topic_name'] for c in publish_calls]
        assert 'camera/detections' in topics
        assert 'camera/classifications' in topics

        # Verify detection result
        det_call = next(
            c for c in publish_calls if c.kwargs['topic_name'] == 'camera/detections'
        )
        det_payload = json.loads(det_call.kwargs['payload'])
        assert det_payload['model'] == 'faster-rcnn'
        assert det_payload['detections'][0]['label'] == 'car'
        assert det_payload['detections'][0]['score'] == 0.88

        # Verify classification result
        cls_call = next(
            c for c in publish_calls
            if c.kwargs['topic_name'] == 'camera/classifications'
        )
        cls_payload = json.loads(cls_call.kwargs['payload'])
        assert cls_payload['model'] == 'efficientnet'
        assert cls_payload['classifications'][0]['label'] == 'great white shark'
        assert cls_payload['classifications'][0]['confidence'] == 0.85
