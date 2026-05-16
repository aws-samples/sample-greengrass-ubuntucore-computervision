"""DetectionHandler - Shadow-driven object detection inference handler.

Reads its assigned model configuration from the model-config shadow reported state,
subscribes to camera/images topic, and performs object detection inference via OVMS gRPC.
Replaces the hardcoded InferenceHandlerCore with a dynamic, shadow-configured approach.

Requirements: 6.1, 6.2, 6.3, 6.4
"""

import sys
import os
import time
import traceback
import logging
import json

import cv2
import numpy as np
from ovmsclient import make_grpc_client
import awsiot.greengrasscoreipc.clientv2 as clientv2
from awsiot.greengrasscoreipc.model import SubscriptionResponseMessage

# Configure logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

SHADOW_NAME = "model-config"
MODEL_READY_RETRY_INTERVAL = 10  # seconds between retries when model not ready


class NumpyEncoder(json.JSONEncoder):
    """JSON encoder that handles NumPy types for serialization."""

    def default(self, obj):
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.integer):
            return int(obj)
        return json.JSONEncoder.default(self, obj)


class DetectionHandler:
    """Object detection handler that reads model config from the device shadow."""

    def __init__(self):
        self.thing_name = os.environ.get("AWS_IOT_THING_NAME", "")
        self.detection_model_id = os.environ.get("DETECTION_MODEL_ID", "faster-rcnn")
        self.sub_topic = os.environ.get("SUB_TOPIC", "camera/images")
        self.pub_topic = os.environ.get("PUB_TOPIC", "camera/detections")
        self.model_server_url = os.environ.get(
            "OVMS_GRPC_URL", os.environ.get("MODEL_SERVER_URL", "localhost:9000")
        )
        self.confidence_threshold = float(
            os.environ.get("CONFIDENCE_THRESHOLD", "0.5")
        )

        # Model metadata loaded from shadow
        self.model_metadata = None
        self.labels_map = None

        # Individual model parameters extracted from model_metadata (Requirement 6.1, 6.2)
        self.model_name = None
        self.input_name = None
        self.output_names = None
        self.input_shape = None

        # Initialize Greengrass IPC client
        self.ipc_client = clientv2.GreengrassCoreIPCClientV2()

        logger.info(
            "DetectionHandler initialized: thing_name=%s, detection_model_id=%s, "
            "sub_topic=%s, pub_topic=%s",
            self.thing_name,
            self.detection_model_id,
            self.sub_topic,
            self.pub_topic,
        )

    def run(self):
        """Main entry point: load model metadata, subscribe to images, and block."""
        # Wait for model to be ready in the shadow (Requirement 6.4)
        self._wait_for_model_ready()

        # Subscribe to camera images
        self._subscribe_to_images()

        logger.info("DetectionHandler running, waiting for camera images...")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("DetectionHandler stopped")

    def _wait_for_model_ready(self):
        """Poll the shadow until the assigned model has status 'ready' with metadata.

        Retries every 10 seconds if the model is not yet available (still installing).
        This implements Requirement 6.4.
        """
        while True:
            model_metadata = self._read_model_metadata_from_shadow()
            if model_metadata is not None:
                self.model_metadata = model_metadata
                # Extract individual model parameters (Requirements 6.1, 6.2, 6.3)
                self._extract_model_parameters(model_metadata)
                logger.info(
                    "Model '%s' is ready. model_name=%s, input_name=%s, "
                    "output_names=%s, input_shape=%s",
                    self.detection_model_id,
                    self.model_name,
                    self.input_name,
                    self.output_names,
                    self.input_shape,
                )
                # Load labels once model metadata is available
                self._load_labels()
                return

            logger.info(
                "Model '%s' not yet ready, retrying in %d seconds...",
                self.detection_model_id,
                MODEL_READY_RETRY_INTERVAL,
            )
            time.sleep(MODEL_READY_RETRY_INTERVAL)

    def _extract_model_parameters(self, model_metadata):
        """Extract individual model parameters from model_metadata dict.

        Reads model_name, input_name, output_names, input_shape, and labels_file
        from the shadow model_metadata and stores them as instance attributes for
        use during inference.

        Requirements: 6.1, 6.2, 6.3
        """
        self.model_name = model_metadata.get("model_name", "")
        self.input_name = model_metadata.get("input_name", "")
        self.output_names = model_metadata.get("output_names", [])
        self.input_shape = model_metadata.get("input_shape", [])

        if not self.model_name:
            logger.warning("model_name not found in model_metadata")
        if not self.input_name:
            logger.warning("input_name not found in model_metadata")
        if not self.output_names:
            logger.warning("output_names not found in model_metadata")
        if not self.input_shape:
            logger.warning("input_shape not found in model_metadata")

    def _read_model_metadata_from_shadow(self):
        """Read the model-config shadow to get model_metadata for the assigned model.

        Returns:
            dict with model metadata if the model is ready, None otherwise.
        """
        if not self.thing_name:
            logger.warning("AWS_IOT_THING_NAME not set, cannot read shadow")
            return None

        try:
            response = self.ipc_client.get_thing_shadow(
                thing_name=self.thing_name, shadow_name=SHADOW_NAME
            )
            shadow = json.loads(response.payload)
            reported = shadow.get("state", {}).get("reported", {})
            models = reported.get("models", {})

            model_entry = models.get(self.detection_model_id)
            if model_entry is None:
                logger.debug(
                    "Model '%s' not found in shadow reported state",
                    self.detection_model_id,
                )
                return None

            status = model_entry.get("status")
            if status != "ready":
                logger.debug(
                    "Model '%s' status is '%s', not ready yet",
                    self.detection_model_id,
                    status,
                )
                return None

            model_metadata = model_entry.get("model_metadata")
            if model_metadata is None:
                logger.debug(
                    "Model '%s' is ready but has no model_metadata",
                    self.detection_model_id,
                )
                return None

            return model_metadata

        except Exception as e:
            logger.warning(
                "Failed to read model-config shadow: %s", e
            )
            return None

    def _load_labels(self):
        """Load labels from the model's labels file specified in model_metadata."""
        if self.model_metadata is None:
            logger.warning("Cannot load labels - no model_metadata available")
            return

        local_path = self.model_metadata.get("local_path", "")
        labels_file = self.model_metadata.get("labels_file", "")

        if not local_path or not labels_file:
            logger.warning(
                "Cannot load labels - missing local_path or labels_file in metadata"
            )
            self.labels_map = {}
            return

        labels_path = os.path.join(local_path, labels_file)
        try:
            with open(labels_path, "r", encoding="utf-8") as f:
                labels = f.read().strip().split("\n")
                self.labels_map = dict(enumerate(labels, 1))
            logger.info(
                "Loaded %d labels from %s", len(self.labels_map), labels_path
            )
        except FileNotFoundError:
            logger.error("Labels file not found: %s", labels_path)
            self.labels_map = {}
        except Exception as e:
            logger.error("Failed to load labels from %s: %s", labels_path, e)
            self.labels_map = {}

    def _subscribe_to_images(self):
        """Subscribe to the camera/images topic via Greengrass IPC local pub/sub."""
        try:
            _, operation = self.ipc_client.subscribe_to_topic(
                topic=self.sub_topic,
                on_stream_event=self._on_image_received,
                on_stream_error=self._on_stream_error,
                on_stream_closed=self._on_stream_closed,
            )
            logger.info("Subscribed to topic: %s", self.sub_topic)
        except Exception as e:
            logger.error("Failed to subscribe to topic '%s': %s", self.sub_topic, e)
            raise

    def _on_image_received(self, event: SubscriptionResponseMessage) -> None:
        """Handle incoming camera image messages and run detection inference."""
        try:
            message = event.json_message.message
            topic = event.json_message.context.topic
            logger.info("Received image message on topic %s: %s", topic, message)

            self._run_inference(message)
        except Exception:
            logger.error("Error processing image message")
            traceback.print_exc()

    def _run_inference(self, message):
        """Run object detection inference on the received image.

        Implements the full inference pipeline:
        1. Read and preprocess image according to input_shape from metadata
        2. Call OVMS gRPC with model_name and input_name from metadata
        3. Parse detection outputs using output_names from metadata
        4. Apply confidence threshold, annotate with labels
        5. Publish results to camera/detections

        Requirements: 6.2, 6.3
        """
        if self.model_metadata is None:
            logger.warning("Cannot run inference - no model_metadata available")
            return

        image_path = message.get("image_path", "")
        if not image_path:
            logger.warning("No image_path in message, skipping inference")
            return

        # Step 1: Read and preprocess image according to input_shape
        image = cv2.imread(image_path)
        if image is None:
            logger.error("Failed to read image: %s", image_path)
            return

        image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        preprocessed = self._preprocess_image(image_rgb)

        # Step 2: Call OVMS gRPC with model_name and input_name from metadata
        try:
            client = make_grpc_client(self.model_server_url)
            inputs = {self.input_name: preprocessed}
            logger.info(
                "Calling OVMS: model=%s, input=%s, server=%s",
                self.model_name,
                self.input_name,
                self.model_server_url,
            )
            result = client.predict(inputs, self.model_name)
        except Exception as e:
            logger.error("OVMS inference failed: %s", e)
            return

        # Step 3: Parse detection outputs using output_names from metadata
        detections = self._parse_detection_outputs(result)
        if detections is None:
            return

        # Step 4: Apply confidence threshold and annotate with labels
        detection_results = self._apply_threshold_and_annotate(
            detections, image_rgb
        )

        # Step 5: Publish results to camera/detections
        self._publish_detections(detection_results)

    def _preprocess_image(self, image_rgb):
        """Preprocess image according to input_shape from model metadata.

        Resizes the image to match the model's expected input dimensions
        and expands dimensions to create a batch of 1.

        Args:
            image_rgb: Image in RGB format as numpy array.

        Returns:
            Preprocessed image as numpy array with batch dimension.
        """
        # input_shape is [batch, height, width, channels]
        target_height = self.input_shape[1]
        target_width = self.input_shape[2]

        resized = cv2.resize(image_rgb, (target_width, target_height))
        # Add batch dimension
        return np.expand_dims(resized, axis=0)

    def _parse_detection_outputs(self, result):
        """Parse detection outputs from OVMS inference result.

        Extracts detection_boxes, detection_classes, detection_scores,
        and num_detections from the result using the output_names from metadata.

        Args:
            result: OVMS inference result dictionary.

        Returns:
            Dict with parsed detection arrays, or None if parsing fails.
        """
        try:
            detections = {}
            for name in self.output_names:
                if name in result:
                    detections[name] = result[name]
                else:
                    logger.warning(
                        "Expected output '%s' not found in result", name
                    )

            # Verify minimum required outputs are present
            required = ["detection_boxes", "detection_classes", "detection_scores"]
            for req in required:
                if req not in detections:
                    logger.error(
                        "Missing required output '%s' in inference result", req
                    )
                    return None

            return detections
        except Exception as e:
            logger.error("Failed to parse detection outputs: %s", e)
            return None

    def _apply_threshold_and_annotate(self, detections, image_rgb):
        """Apply confidence threshold and annotate detections with labels.

        Filters detections by confidence_threshold and maps class IDs to
        human-readable labels from the labels_map.

        Args:
            detections: Dict with detection_boxes, detection_classes,
                       detection_scores arrays from OVMS.
            image_rgb: Original image in RGB format for dimension reference.

        Returns:
            List of detection result dicts with label, score, and box info.
        """
        boxes = detections["detection_boxes"]
        classes = detections["detection_classes"]
        scores = detections["detection_scores"]
        num_detections = int(
            detections.get("num_detections", np.array([0]))[0]
        )

        original_height, original_width, _ = image_rgb.shape
        results = []

        # Determine max detections from array shape
        if len(scores.shape) > 1:
            max_detections = min(num_detections, scores.shape[1])
        else:
            max_detections = num_detections

        for i in range(max_detections):
            # Handle both batched [1, N] and flat [N] array shapes
            score = float(scores[0, i]) if len(scores.shape) > 1 else float(scores[i])
            if score < self.confidence_threshold:
                continue

            class_id = int(classes[0, i]) if len(classes.shape) > 1 else int(classes[i])
            label = self.labels_map.get(class_id, "class_%d" % class_id) if self.labels_map else "class_%d" % class_id

            # Get bounding box (normalized coordinates: ymin, xmin, ymax, xmax)
            if len(boxes.shape) > 2:
                box = boxes[0, i]
            else:
                box = boxes[i]

            # Convert normalized box coordinates to pixel coordinates
            ymin = float(box[0]) * original_height
            xmin = float(box[1]) * original_width
            ymax = float(box[2]) * original_height
            xmax = float(box[3]) * original_width

            results.append(
                {
                    "label": label,
                    "score": round(score, 4),
                    "box": {
                        "ymin": round(ymin, 1),
                        "xmin": round(xmin, 1),
                        "ymax": round(ymax, 1),
                        "xmax": round(xmax, 1),
                    },
                }
            )

        logger.info(
            "Detected %d objects above threshold %.2f",
            len(results),
            self.confidence_threshold,
        )
        return results

    def _publish_detections(self, detection_results):
        """Publish detection results to camera/detections topic via IoT Core.

        Args:
            detection_results: List of detection dicts with label, score, box.
        """
        payload = {
            "model": self.detection_model_id,
            "detections": detection_results,
            "count": len(detection_results),
            "threshold": self.confidence_threshold,
        }

        try:
            encoded = json.dumps(payload, cls=NumpyEncoder).encode("utf-8")
            self.ipc_client.publish_to_iot_core(
                topic_name=self.pub_topic, qos="1", payload=encoded
            )
            logger.info(
                "Published %d detections to %s",
                len(detection_results),
                self.pub_topic,
            )
        except Exception as e:
            logger.error("Failed to publish detections: %s", e)
            traceback.print_exc()

    def _on_stream_error(self, error: Exception) -> bool:
        """Handle stream errors."""
        logger.error("Stream error received: %s", error)
        traceback.print_exc()
        return False  # Return False to keep stream open

    def _on_stream_closed(self) -> None:
        """Handle stream closure."""
        logger.info("Subscribe to topic stream closed.")


def main():
    """Main entry point for the DetectionHandler component."""
    try:
        handler = DetectionHandler()
        handler.run()
    except Exception as e:
        logger.error("Error initializing DetectionHandler: %s", e)
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
