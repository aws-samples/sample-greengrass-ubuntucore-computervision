import sys
import os
import time
import traceback
import logging
import json
from ovmsclient import make_grpc_client
import cv2
import boto3
import random
import numpy as np
import awsiot.greengrasscoreipc.clientv2 as clientv2
from awsiot.greengrasscoreipc.model import (
    SubscriptionResponseMessage,
    UnauthorizedError
)

# Configure logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Default configuration
DEFAULT_CONFIG = {
    "sub_topic": "camera/images",
    "pub_topic": "camera/inference",
    "model_server_url": "localhost:9000",  # gRPC port
    "model_name": "faster_rcnn",
    "model_version": 1,
    "model_input_name": "input_tensor",
    "model_output_name": "detection_boxes,detection_classes,detection_scores,num_detections",
    "labels_file": "label_map.txt",
    "detections_limit": 10,
    "s3_bucket_name": "",
    "output_directory": os.environ.get('SNAP_USER_DATA', '/tmp'),
}

class NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.integer):
            return int(obj)
        return json.JSONEncoder.default(self, obj)

class InferenceHandler():
    def __init__(self):
        """Initialize the inference handler with configuration."""
        self.config = DEFAULT_CONFIG.copy()
        self.load_config()
        
        # Initialize IPC client
        self.ipc_client = clientv2.GreengrassCoreIPCClientV2()
        
        logger.info("Inference handler initialized with config: %s", self.config)

        # load and enumerate labels
        artifact_path = os.environ.get("ARTIFACT_PATH")
        with open(os.path.join(artifact_path,self.config['labels_file']), "r", encoding='utf-8') as file:
            labels = file.read().strip().split("\n")
            self.labels_map = dict(enumerate(labels, 1))

    def load_config(self):
        """Load configuration from environment variables."""
        if os.environ.get("SUB_TOPIC"):
            self.config["sub_topic"] = os.environ.get("SUB_TOPIC")
        if os.environ.get("PUB_TOPIC"):
            self.config["pub_topic"] = os.environ.get("PUB_TOPIC")
        if os.environ.get("MODEL_SERVER_URL"):
            self.config["model_server_url"] = os.environ.get("MODEL_SERVER_URL")
        if os.environ.get("MODEL_NAME"):
            self.config["model_name"] = os.environ.get("MODEL_NAME")
        if os.environ.get("S3_BUCKET_NAME"):
            self.config["s3_bucket_name"] = os.environ.get("S3_BUCKET_NAME")

    def run(self):
        """Main loop to subscribe to MQTT topic and publish inference results."""
        logger.info("Starting inference handler loop")
        try:
            # Subscription operations return a tuple with the response and the operation.
            _, operation = self.ipc_client.subscribe_to_topic(topic=self.config['sub_topic'], on_stream_event=self.on_stream_event,
                                                        on_stream_error=self.on_stream_error, on_stream_closed=self.on_stream_closed)
            logger.info('Successfully subscribed to topic: ' + self.config['sub_topic'])
            while True:
                pass
        except KeyboardInterrupt:
            logger.info("Inference handler stopped")
        except Exception as e:
            logger.error("Error in inference handler: %s", str(e))

    def publish_results(self,meta_data):
        try:
            payload = json.dumps(meta_data, cls=NumpyEncoder).encode('utf-8')
            result = self.ipc_client.publish_to_iot_core(topic_name=self.config['pub_topic'], qos='1', payload=payload)
            logger.info('Successfully published message on topic: ' + self.config['pub_topic'])
        except Exception:
            logger.error('Exception occurred when publishing')
            traceback.print_exc()
            sys.exit(1)

    def on_stream_event(self,event: SubscriptionResponseMessage) -> None:
        try:
            message = event.json_message.message
            topic = event.json_message.context.topic
            logger.info('Received new message on topic %s: %s' % (topic, message))
            self.run_inference(message)
        except:
            traceback.print_exc()

    def on_stream_error(self,error: Exception) -> bool:
        logger.error('Received a stream error.')
        traceback.print_exc()
        return False  # Return True to close stream, False to keep stream open.

    def on_stream_closed(self) -> None:
        logger.info('Subscribe to topic stream closed.')

    def run_inference(self, message):
        """Read image from the message and run inference."""
        image_path = json.dumps(message['image_path'])
        logger.info("Running inference on image: %s", image_path)
        image_path = image_path.replace('"', '')
        image = cv2.imread(filename=str(image_path))
        image = cv2.cvtColor(image, code=cv2.COLOR_BGR2RGB)
        resized_image = cv2.resize(src=image, dsize=(255, 255))
        network_input_image = np.expand_dims(resized_image, 0)

        try:
            client = make_grpc_client(self.config['model_server_url'])
            inputs = {
                self.config['model_input_name']: network_input_image
            }
            logger.info(f"Connecting to model server: {self.config['model_server_url']}")
            logger.info(f"Using model: {self.config['model_name']} version {self.config['model_version']}")
            inference_result = client.predict(inputs, self.config['model_name'], self.config['model_version'])
        except Exception as e:
            logger.error(f"Inference failed: {e}")
            logger.error(f"Model server URL: {self.config['model_server_url']}")
            logger.error(f"Model name: {self.config['model_name']}")
            raise

        detection_boxes: np.ndarray = inference_result["detection_boxes"]
        detection_classes: np.ndarray = inference_result["detection_classes"]
        detection_scores: np.ndarray = inference_result["detection_scores"]
        num_detections: np.ndarray = inference_result["num_detections"]

        json_result = {}

        # Normalize detection boxes coordinates to original image size
        original_image_height, original_image_width, _ = image.shape
        normalized_detection_boxes = detection_boxes[::] * [
            original_image_height,
            original_image_width,
            original_image_height,
            original_image_width,
        ]

        image_with_detection_boxes = np.copy(image)

        for i in range(self.config['detections_limit']):
            detected_class_name = self.labels_map[int(detection_classes[0, i])]
            score = detection_scores[0, i]
            label = f"{detected_class_name} {score:.2f}"
            self.add_detection_box(
                box=normalized_detection_boxes[0, i],
                image=image_with_detection_boxes,
                label=label,
            )
            # add as new dictionary item to json_result dictionary
            json_result[i] = {
                "detection_classes": detected_class_name,
                "detection_scores": score,
                "num_detections": num_detections[0]
            }

        img = cv2.cvtColor(image_with_detection_boxes, code=cv2.COLOR_BGR2RGB)
        annotated_img_path = self.config['output_directory'] + "/annotated_" +  image_path.split('/')[-1]
        cv2.imwrite(annotated_img_path,img)

        logger.info("Inference result: %s", json_result)
        self.publish_results(json_result)
        self.upload_to_s3(annotated_img_path)
        self.delete_src_picture(image_path, annotated_img_path)

    def add_detection_box(self, box, image, label):
        """
        Helper function for adding single bounding box to the image

        Parameters
        ----------
        box : np.ndarray
            Bounding box coordinates in format [ymin, xmin, ymax, xmax]
        image : np.ndarray
            The image to which detection box is added
        label : str, optional
            Detection box label string, if not provided will not be added to result image (default is None)

        Returns
        -------
        np.ndarray
            NumPy array including both image and detection box

        """
        ymin, xmin, ymax, xmax = box
        point1, point2 = (int(xmin), int(ymin)), (int(xmax), int(ymax))
        box_color = [random.randint(0, 255) for _ in range(3)] # nosec
        line_thickness = round(0.002 * (image.shape[0] + image.shape[1]) / 2) + 1

        cv2.rectangle(img=image, pt1=point1, pt2=point2, color=box_color, thickness=line_thickness, lineType=cv2.LINE_AA)

        if label:
            font_thickness = max(line_thickness - 1, 1)
            font_face = 0
            font_scale = line_thickness / 3
            font_color = (255, 255, 255)
            text_size = cv2.getTextSize(text=label, fontFace=font_face, fontScale=font_scale, thickness=font_thickness)[0]
            # Calculate rectangle coordinates
            rectangle_point1 = point1
            rectangle_point2 = (point1[0] + text_size[0], point1[1] - text_size[1] - 3)
            # Add filled rectangle
            cv2.rectangle(img=image, pt1=rectangle_point1, pt2=rectangle_point2, color=box_color, thickness=-1, lineType=cv2.LINE_AA)
            # Calculate text position
            text_position = point1[0], point1[1] - 3
            # Add text with label to filled rectangle
            cv2.putText(img=image, text=label, org=text_position, fontFace=font_face, fontScale=font_scale, color=font_color, thickness=font_thickness, lineType=cv2.LINE_AA)
        return image

    def upload_to_s3(self, image_path):
        """Upload the image to S3 bucket with fixed filename."""
        try:
            s3 = boto3.client('s3')
            bucket_name = self.config['s3_bucket_name']
            s3_key = 'camera/latest-inference.jpg'
            s3.upload_file(image_path, bucket_name, s3_key)
            logger.info("Image uploaded to S3: s3://%s/%s", bucket_name, s3_key)
        except Exception as e:
            logger.error("Error uploading image to S3: %s", str(e))

    def delete_src_picture(self, image_path, annotated_img):
        """Delete the image from the local storage."""
        try:
            os.remove(image_path)
            os.remove(annotated_img)
            logger.info("Image deleted: %s", image_path)
            logger.info("Image deleted: %s", annotated_img)
        except Exception as e:
            logger.error("Error deleting image: %s", str(e))

def main():
    """Main entry point for the inference handler."""
    try:
        handler = InferenceHandler()
        handler.run()
    except Exception as e:
        logger.error("Error initializing inference handler: %s", str(e))

if __name__ == '__main__':
    main()