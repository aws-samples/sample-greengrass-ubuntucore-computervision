#!/usr/bin/env python3
"""
AWS Greengrass component on Ubuntu Core for capturing images from a USB webcam.
"""
import os
import time
import datetime
import logging
import json
import cv2
import awsiot.greengrasscoreipc.clientv2 as clientv2
from awsiot.greengrasscoreipc.model import (
    PublishMessage,
    JsonMessage
)

# Configure logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Default configuration
DEFAULT_CONFIG = {
    "camera_index": "/dev/video0",
    "capture_interval": 10,  # seconds
    "image_width": 640,
    "image_height": 480,
    "output_directory": os.environ.get('SNAP_USER_DATA'),
    "topic": "camera/images",
    "qos": 1
}

TIMEOUT = 10

class CameraHandler:
    def __init__(self):
        """Initialize the camera handler with configuration."""
        self.config = DEFAULT_CONFIG.copy()
        self.load_config()
        
        # Create output directory if it doesn't exist
        os.makedirs(self.config["output_directory"], exist_ok=True)
        
        # Initialize IPC client
        self.ipc_client = clientv2.GreengrassCoreIPCClientV2()
        
        logger.info("Camera handler initialized with config: %s", self.config)

    def load_config(self):
        """Load configuration from environment variables."""
        # Override defaults with environment variables if present
        if os.environ.get("CAMERA_INDEX"):
            camera_index = os.environ.get("CAMERA_INDEX")
            # Check if it's a device path
            if camera_index.startswith("/dev/"):
                self.config["camera_index"] = camera_index
            else:
                try:
                    self.config["camera_index"] = int(camera_index)
                except ValueError:
                    logger.error("Invalid camera index: %s. Using default: %s", 
                                camera_index, self.config["camera_index"])
        if os.environ.get("CAPTURE_INTERVAL"):
            self.config["capture_interval"] = int(os.environ.get("CAPTURE_INTERVAL"))
        if os.environ.get("IMAGE_WIDTH"):
            self.config["image_width"] = int(os.environ.get("IMAGE_WIDTH"))
        if os.environ.get("IMAGE_HEIGHT"):
            self.config["image_height"] = int(os.environ.get("IMAGE_HEIGHT"))
        if os.environ.get("OUTPUT_DIRECTORY"):
            self.config["output_directory"] = os.environ.get("OUTPUT_DIRECTORY")
        if os.environ.get("TOPIC"):
            self.config["topic"] = os.environ.get("TOPIC")

    def capture_image(self):
        """Capture an image from the webcam."""
        try:
            # Check if camera_index is a string path (like /dev/video0)
            if isinstance(self.config["camera_index"], str) and self.config["camera_index"].startswith("/dev/"):
                cap = cv2.VideoCapture(self.config["camera_index"])
                
            if not cap.isOpened():
                logger.error("Failed to open camera at %s", self.config["camera_index"])
                return None
            
            # Set resolution
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.config["image_width"])
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config["image_height"])
            
            # Capture frame
            ret, frame = cap.read()
            if not ret:
                logger.error("Failed to capture image")
                cap.release()
                return None
            
            # Release the camera
            cap.release()
            
            return frame
        except Exception as e:
            logger.error("Error capturing image: %s", str(e))
            return None

    def save_image(self, frame):
        """Save the captured image to the output directory."""
        try:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"image_{timestamp}.jpg"
            filepath = os.path.join(self.config["output_directory"], filename)
            
            cv2.imwrite(filepath, frame)
            logger.info("Image saved to %s", filepath)
            return filepath
        except Exception as e:
            logger.error("Error saving image: %s", str(e))
            return None

    def publish_image_event(self, image_path):
        """Publish the image path to the local MQTT topic."""
        try:
            if not image_path:
                return
            
            json_message = JsonMessage(message={
                "image_path": image_path,
                "timestamp": datetime.datetime.now().isoformat()
            })
            
            publish_message = PublishMessage(json_message=json_message)

            request = self.ipc_client.publish_to_topic(
                topic=self.config['topic'],
                publish_message=publish_message
            )

            logger.info("Published image path to topic: %s", self.config["topic"])
        except Exception as e:
            logger.error("Error publishing message: %s", str(e))

    def run(self):
        """Main loop to capture images at the specified interval."""
        logger.info("Starting camera capture loop")
        try:
            while True:
                # Capture image
                frame = self.capture_image()
                if frame is not None:
                    # Save image
                    image_path = self.save_image(frame)
                    
                    # Publish event to trigger inference
                    self.publish_image_event(image_path)
                
                # Wait for next capture
                time.sleep(self.config["capture_interval"])
        except KeyboardInterrupt:
            logger.info("Camera handler stopped")
        except Exception as e:
            logger.error("Error in camera handler: %s", str(e))

def main():
    """Main entry point for the camera handler."""
    try:
        handler = CameraHandler()
        handler.run()
    except Exception as e:
        logger.error("Error initializing camera handler: %s", str(e))

if __name__ == "__main__":
    main()