# Requirements Document

## Introduction

Dynamic Model Management enables operators to request multiple OpenVINO inference models on an edge device via IoT Device Shadow, have those models automatically downloaded and configured for inference, and run multiple models simultaneously for different purposes (e.g. object detection + image classification). The system leverages the Ubuntu Core Inference Snap for model delivery with automatic hardware variant selection, AWS IoT Greengrass for orchestration, and OpenVINO Model Server (OVMS) for multi-model serving.

## Glossary

- **Model_Config_Shadow**: The IoT Device Shadow named `model-config` that declares which models should be on the device and reports their status
- **Inference_Snap**: The `cv-inference` Ubuntu Core snap that packages OVMS with hardware-optimised engines and delivers standard models as snap components
- **Model_Manager**: The Greengrass component (`com.example.ModelManagerCore`) that watches the shadow and orchestrates model installation and OVMS configuration
- **OVMS**: OpenVINO Model Server — serves multiple models simultaneously via gRPC
- **Snap_Model**: A model delivered as a snap component via the Snap Store (primary delivery)
- **Custom_Model**: A model downloaded from S3 (secondary delivery for proprietary models)
- **Handler**: A Greengrass inference component that calls OVMS for a specific model type (e.g. `DetectionHandler`, `ClassificationHandler`)

## Requirements

### Requirement 1: Shadow-Driven Model Declaration

**User Story:** As an operator, I want to declare which models should be on the device by updating the Device Shadow, so that the device automatically provisions and configures them.

#### Acceptance Criteria

1. THE Model_Manager SHALL watch the `model-config` named shadow for desired state changes
2. THE desired state SHALL accept a `models` object where each key is a model_id and the value contains `source` ("snap" or "s3") and optionally `s3_uri` (required when source is "s3")
3. WHEN a new model appears in the desired `models` object, THE Model_Manager SHALL initiate installation of that model
4. THE reported state SHALL reflect the current status of each model: one of `installing`, `ready`, or `failed` (with a `reason` string when failed)
5. WHEN all requested models reach status `ready`, THE Model_Manager SHALL update the OVMS configuration to serve them and report the overall system status as `ready`

### Requirement 2: Snap-Based Model Installation (Primary)

**User Story:** As a platform engineer, I want standard models installed via the Inference Snap, so that hardware variant selection happens automatically without custom logic in Greengrass components.

#### Acceptance Criteria

1. WHEN a model with `source: "snap"` is requested, THE Model_Manager SHALL invoke `snap install` for the corresponding snap component (e.g. `cv-inference.model-faster-rcnn`)
2. THE Inference Snap SHALL handle hardware variant selection automatically — the Model_Manager does not determine which variant to download
3. EACH snap model component SHALL include a `manifest.json` describing its OVMS interface: `model_id`, `model_name`, `version`, `input_name`, `output_names`, `input_shape`, `labels_file`
4. WHEN snap installation completes, THE Model_Manager SHALL read the manifest.json and update the reported state with status `ready` and the model's metadata

### Requirement 3: S3 Model Download (Secondary)

**User Story:** As an operator, I want to deploy custom models from S3 when they are not available in the Snap Store.

#### Acceptance Criteria

1. WHEN a model with `source: "s3"` is requested, THE Model_Manager SHALL download the model artifacts from the provided `s3_uri` to `$SNAP_COMMON/models/{model_id}/` using boto3
2. THE S3 model directory SHALL contain a `manifest.json` with the same schema as snap models
3. WHEN download completes, THE Model_Manager SHALL read the manifest.json and update the reported state with status `ready`
4. IF the download fails, THE Model_Manager SHALL report status `failed` with a `reason` describing the error

### Requirement 4: Multi-Model OVMS Configuration

**User Story:** As a developer, I want OVMS to serve multiple models simultaneously, so that different inference handlers can call different models concurrently.

#### Acceptance Criteria

1. THE Model_Manager SHALL write a `models_config.json` listing all models with status `ready`, each with its `name` and `base_path`
2. OVMS SHALL reload its configuration automatically via `--file_system_poll_wait_seconds` when the config file changes
3. THE Model_Manager SHALL configure OVMS to serve snap models from `$SNAP_COMPONENTS/{component}/` and S3 models from `$SNAP_COMMON/models/{model_id}/`

### Requirement 5: Inference Snap Runtime

**User Story:** As a platform engineer, I want the inference runtime packaged as an Ubuntu Core snap with automatic hardware detection.

#### Acceptance Criteria

1. THE Inference_Snap SHALL package OVMS with engine variants for Intel CPU, GPU, and NPU
2. WHEN installed, THE Inference_Snap SHALL auto-detect hardware and activate the best available engine (NPU > GPU > CPU)
3. THE Inference_Snap SHALL expose OVMS on gRPC port 9000
4. THE Inference_Snap SHALL monitor `$SNAP_COMMON/config/models_config.json` for changes and reload models automatically

### Requirement 6: Detection Inference Handler

**User Story:** As a developer, I want an object detection handler that reads its model configuration from the shadow, so that it works with any compatible detection model without code changes.

#### Acceptance Criteria

1. THE DetectionHandler SHALL read `model_metadata` for its assigned model from the `model-config` shadow reported state to determine: model name, input tensor name, output tensor names, input shape, and labels file path
2. THE DetectionHandler SHALL call OVMS via gRPC using the parameters from model_metadata
3. THE DetectionHandler SHALL load labels from the model's labels file and use them to annotate detections
4. IF model_metadata is not yet available (model still installing), THE DetectionHandler SHALL wait and retry at 10-second intervals until the model becomes available

### Requirement 7: Classification Inference Handler

**User Story:** As a developer, I want an image classification handler that works alongside the detection handler, demonstrating multi-model inference.

#### Acceptance Criteria

1. THE ClassificationHandler SHALL read `model_metadata` for its assigned model from the `model-config` shadow reported state
2. THE ClassificationHandler SHALL call OVMS via gRPC, sending the image and receiving class probabilities
3. THE ClassificationHandler SHALL return the top-N classifications with confidence scores
4. THE ClassificationHandler SHALL operate independently of the DetectionHandler, subscribing to the same camera images but publishing to a different topic

### Requirement 8: Model Removal

**User Story:** As an operator, I want to remove models from the device by updating the shadow.

#### Acceptance Criteria

1. WHEN a model is removed from the desired `models` object, THE Model_Manager SHALL remove it from the OVMS configuration and delete its files from local storage
2. THE Model_Manager SHALL update the reported state to reflect the model has been removed
3. THE Model_Manager SHALL NOT remove a model that is currently the only model being served (at least one model must remain active)

### Requirement 9: Basic Error Reporting

**User Story:** As an operator, I want to see errors in the shadow reported state so I can diagnose issues without device access.

#### Acceptance Criteria

1. IF a model installation fails (snap install error, S3 download error, missing manifest), THE Model_Manager SHALL set that model's status to `failed` with a human-readable `reason` string in the reported state
2. IF OVMS fails to load a model after configuration update, THE Model_Manager SHALL report the model status as `failed` with reason indicating the load error
3. THE reported state SHALL include an `engine` field indicating the active hardware engine (cpu, gpu, or npu)
