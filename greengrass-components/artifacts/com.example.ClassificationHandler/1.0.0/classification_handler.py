"""ClassificationHandler - Image classification inference component for Greengrass.

Reads model configuration from the model-config named shadow reported state,
subscribes to camera/images topic, and publishes classification results to
camera/classifications. Retries model metadata loading every 10 seconds if
the model is not yet ready.

Requirements: 7.1, 7.2, 7.3, 7.4
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
MODEL_RETRY_INTERVAL = 10  # seconds between retries when model not ready
DEFAULT_TOP_N = 5  # Number of top classifications to return
DEFAULT_MODEL_SERVER_URL = "localhost:9000"


class NumpyEncoder(json.JSONEncoder):
    """JSON encoder that handles NumPy types."""

    def default(self, obj):
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.integer):
            return int(obj)
        return json.JSONEncoder.default(self, obj)


class ClassificationHandler:
    """Handles image classification inference using model config from device shadow."""

    def __init__(self):
        self.thing_name = os.environ.get("AWS_IOT_THING_NAME", "")
        self.classification_model_id = os.environ.get(
            "CLASSIFICATION_MODEL_ID", "efficientnet"
        )
        self.pub_topic = "camera/classifications"
        self.sub_topic = "camera/images"
        self.model_server_url = os.environ.get(
            "OVMS_GRPC_URL", os.environ.get("MODEL_SERVER_URL", DEFAULT_MODEL_SERVER_URL)
        )
        self.top_n = int(os.environ.get("TOP_N", str(DEFAULT_TOP_N)))

        # Model metadata loaded from shadow
        self.model_metadata = None
        self.labels = []

        # Initialize Greengrass IPC client
        self.ipc_client = clientv2.GreengrassCoreIPCClientV2()

        logger.info(
            "ClassificationHandler initialized: thing_name=%s, model_id=%s, "
            "model_server_url=%s, top_n=%d",
            self.thing_name,
            self.classification_model_id,
            self.model_server_url,
            self.top_n,
        )

    def run(self):
        """Main entry point: load model metadata, subscribe to images, and block."""
        # Wait for model to be ready in the shadow
        self._wait_for_model_ready()

        # Subscribe to camera images
        self._subscribe_to_images()

        logger.info("ClassificationHandler running, waiting for image events...")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("ClassificationHandler stopped")

    def _wait_for_model_ready(self):
        """Poll the shadow until the assigned model has status 'ready'.

        Reads the model-config shadow reported state and checks if the
        classification model has model_metadata available. Retries every
        MODEL_RETRY_INTERVAL seconds until the model becomes available.
        """
        while True:
            metadata = self._read_model_metadata_from_shadow()
            if metadata is not None:
                self.model_metadata = metadata
                logger.info(
                    "Model '%s' metadata loaded: %s",
                    self.classification_model_id,
                    json.dumps(metadata, indent=2),
                )
                self._load_labels()
                return

            logger.info(
                "Model '%s' not yet ready, retrying in %d seconds...",
                self.classification_model_id,
                MODEL_RETRY_INTERVAL,
            )
            time.sleep(MODEL_RETRY_INTERVAL)

    def _read_model_metadata_from_shadow(self):
        """Read model_metadata for the assigned model from the shadow reported state.

        Returns:
            Dict with model metadata if the model is ready, None otherwise.
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

            model_entry = models.get(self.classification_model_id)
            if model_entry is None:
                logger.debug(
                    "Model '%s' not found in shadow reported state",
                    self.classification_model_id,
                )
                return None

            status = model_entry.get("status")
            if status != "ready":
                logger.debug(
                    "Model '%s' status is '%s', not ready yet",
                    self.classification_model_id,
                    status,
                )
                return None

            metadata = model_entry.get("model_metadata")
            if metadata is None:
                logger.debug(
                    "Model '%s' is ready but has no model_metadata",
                    self.classification_model_id,
                )
                return None

            return metadata

        except Exception as e:
            logger.warning(
                "Failed to read model-config shadow: %s", e
            )
            return None

    def _load_labels(self):
        """Load classification labels from the model's labels file."""
        if not self.model_metadata:
            return

        labels_file = self.model_metadata.get("labels_file", "")
        local_path = self.model_metadata.get("local_path", "")

        if not labels_file or not local_path:
            logger.warning("No labels_file or local_path in model metadata")
            self.labels = []
            return

        labels_path = os.path.join(local_path, labels_file)
        try:
            with open(labels_path, "r", encoding="utf-8") as f:
                self.labels = [line.strip() for line in f.readlines() if line.strip()]
            logger.info(
                "Loaded %d labels from %s", len(self.labels), labels_path
            )
        except FileNotFoundError:
            logger.warning("Labels file not found: %s", labels_path)
            self.labels = []
        except Exception as e:
            logger.error("Error loading labels from %s: %s", labels_path, e)
            self.labels = []

    def _subscribe_to_images(self):
        """Subscribe to the camera/images topic via Greengrass IPC pub/sub."""
        try:
            self.ipc_client.subscribe_to_topic(
                topic=self.sub_topic,
                on_stream_event=self._on_image_event,
                on_stream_error=self._on_stream_error,
                on_stream_closed=self._on_stream_closed,
            )
            logger.info("Subscribed to topic: %s", self.sub_topic)
        except Exception as e:
            logger.error("Failed to subscribe to %s: %s", self.sub_topic, e)
            raise

    def _on_image_event(self, event: SubscriptionResponseMessage) -> None:
        """Handle incoming image messages from camera/images topic.

        Extracts the image path from the message and runs classification inference.
        """
        try:
            message = event.json_message.message
            topic = event.json_message.context.topic
            logger.info("Received image on topic %s: %s", topic, message)

            self._run_classification(message)

        except Exception:
            logger.error("Error processing image event")
            traceback.print_exc()

    def _run_classification(self, message):
        """Run classification inference on the received image.

        Implements Requirements 7.2 and 7.3:
        - Preprocesses image according to input_shape from model_metadata
        - Calls OVMS gRPC with model_name and input_name
        - Parses class probability vector
        - Returns top-N classifications with confidence scores
        - Publishes results to camera/classifications
        """
        if not self.model_metadata:
            logger.warning("No model metadata available, skipping classification")
            return

        # Extract image path from message
        image_path = message.get("image_path", "")
        if not image_path:
            logger.warning("No image_path in message, skipping")
            return

        # Read and preprocess image
        input_tensor = self._preprocess_image(image_path)
        if input_tensor is None:
            return

        # Call OVMS gRPC for inference
        predictions = self._call_ovms(input_tensor)
        if predictions is None:
            return

        # Extract top-N classifications
        classifications = self._extract_top_n(predictions)

        # Publish results
        self._publish_classifications(classifications)

    def _preprocess_image(self, image_path):
        """Preprocess image according to input_shape from model_metadata.

        Resizes the image to match the model's expected input dimensions and
        normalizes pixel values to [0, 1] range (EfficientNet convention).

        Args:
            image_path: Path to the image file on disk.

        Returns:
            NumPy array with shape matching input_shape, or None on error.
        """
        try:
            image = cv2.imread(str(image_path))
            if image is None:
                logger.error("Failed to read image: %s", image_path)
                return None

            # Convert BGR to RGB
            image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

            # Get target dimensions from input_shape [batch, height, width, channels]
            input_shape = self.model_metadata.get("input_shape", [1, 224, 224, 3])
            target_height = input_shape[1]
            target_width = input_shape[2]

            # Resize to model's expected input dimensions
            resized = cv2.resize(image, (target_width, target_height))

            # Normalize pixel values to [0, 1] for EfficientNet
            normalized = resized.astype(np.float32) / 255.0

            # Add batch dimension: (H, W, C) -> (1, H, W, C)
            input_tensor = np.expand_dims(normalized, axis=0)

            logger.debug(
                "Preprocessed image %s to shape %s", image_path, input_tensor.shape
            )
            return input_tensor

        except Exception as e:
            logger.error("Error preprocessing image %s: %s", image_path, e)
            traceback.print_exc()
            return None

    def _call_ovms(self, input_tensor):
        """Call OVMS via gRPC to get classification predictions.

        Args:
            input_tensor: Preprocessed image as NumPy array with batch dimension.

        Returns:
            Prediction array (class probabilities), or None on error.
        """
        model_name = self.model_metadata.get("model_name", "")
        input_name = self.model_metadata.get("input_name", "")

        if not model_name or not input_name:
            logger.error(
                "Missing model_name or input_name in metadata: model_name=%s, input_name=%s",
                model_name,
                input_name,
            )
            return None

        try:
            client = make_grpc_client(self.model_server_url)
            inputs = {input_name: input_tensor}

            logger.info(
                "Calling OVMS: model=%s, input=%s, server=%s",
                model_name,
                input_name,
                self.model_server_url,
            )

            result = client.predict(inputs, model_name)

            # Get the output - use the first output_name from metadata
            output_names = self.model_metadata.get("output_names", [])
            if output_names:
                predictions = result[output_names[0]]
            else:
                # Fallback: use the first key in the result
                predictions = next(iter(result.values()))

            logger.info(
                "OVMS prediction received, output shape: %s", predictions.shape
            )
            return predictions

        except Exception as e:
            logger.error(
                "OVMS gRPC call failed for model '%s': %s", model_name, e
            )
            traceback.print_exc()
            return None

    def _extract_top_n(self, predictions):
        """Extract top-N classifications with confidence scores from predictions.

        Args:
            predictions: NumPy array of class probabilities from OVMS.

        Returns:
            List of dicts with 'label', 'confidence', and 'class_index' keys,
            sorted by confidence descending.
        """
        # Flatten predictions if batched (remove batch dimension)
        if predictions.ndim > 1:
            probs = predictions[0]
        else:
            probs = predictions

        # Get indices of top-N highest probabilities
        num_classes = len(probs)
        top_n = min(self.top_n, num_classes)
        top_indices = np.argsort(probs)[::-1][:top_n]

        classifications = []
        for idx in top_indices:
            confidence = float(probs[idx])
            # Map index to label (0-indexed for classification models)
            if idx < len(self.labels):
                label = self.labels[idx]
            else:
                label = f"class_{idx}"

            classifications.append(
                {
                    "label": label,
                    "confidence": round(confidence, 6),
                    "class_index": int(idx),
                }
            )

        logger.info(
            "Top-%d classifications: %s",
            top_n,
            [(c["label"], c["confidence"]) for c in classifications],
        )
        return classifications

    def _publish_classifications(self, classifications):
        """Publish classification results to camera/classifications topic via IoT Core.

        Args:
            classifications: List of dicts with 'label', 'confidence', and 'class_index' keys.
        """
        try:
            payload = json.dumps(
                {
                    "model": self.model_metadata.get("model_name", "unknown"),
                    "classifications": classifications,
                    "timestamp": time.time(),
                },
                cls=NumpyEncoder,
            ).encode("utf-8")
            self.ipc_client.publish_to_iot_core(
                topic_name=self.pub_topic, qos="1", payload=payload
            )
            logger.info("Published classifications to %s", self.pub_topic)
        except Exception as e:
            logger.error("Failed to publish classifications: %s", e)
            traceback.print_exc()

    def _on_stream_error(self, error: Exception) -> bool:
        """Handle stream errors."""
        logger.error("Stream error: %s", error)
        traceback.print_exc()
        return False  # Keep stream open

    def _on_stream_closed(self) -> None:
        """Handle stream closure."""
        logger.info("Subscribe to topic stream closed.")


def main():
    """Main entry point for the ClassificationHandler component."""
    try:
        handler = ClassificationHandler()
        handler.run()
    except Exception as e:
        logger.error("Error initializing ClassificationHandler: %s", e)
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
