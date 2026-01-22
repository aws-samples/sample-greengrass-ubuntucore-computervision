#!/bin/bash

# Download and prepare OpenVINO model for Greengrass deployment

MODEL_DIR="greengrass-components/artifacts/com.example.OpenVINOModelServerContainerCore/1.0.0"
TEMP_DIR="temp_model"

echo "Downloading Faster R-CNN model from Kaggle..."

# Create directories
mkdir -p "$MODEL_DIR"
mkdir -p "$TEMP_DIR/model/1"

# Download model
curl -L --create-dirs https://www.kaggle.com/api/v1/models/tensorflow/faster-rcnn-resnet-v1/tensorFlow2/faster-rcnn-resnet50-v1-640x640/1/download -o "$TEMP_DIR/model/1/1.tar.gz"

# Extract model
tar xzf "$TEMP_DIR/model/1/1.tar.gz" -C "$TEMP_DIR/model/1"

# Remove the downloaded tar.gz to save space
rm "$TEMP_DIR/model/1/1.tar.gz"

# Create the final archive
echo "Creating object_detection_model.zip..."
cd "$TEMP_DIR"
zip -r "../$MODEL_DIR/object_detection_model.zip" model/

# Clean up
cd ..
rm -rf "$TEMP_DIR"

echo "Model downloaded and prepared successfully!"
echo "File created: $MODEL_DIR/object_detection_model.zip"