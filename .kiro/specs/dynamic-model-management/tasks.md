# Implementation Plan: Dynamic Model Management (Simplified)

## Overview

This plan implements multi-model management for the edge device in a minimal, demo-focused way. The operator declares desired models in the Device Shadow, ModelManagerCore installs them (via snap or S3), configures OVMS to serve them all simultaneously, and separate inference handlers (Detection + Classification) call the appropriate models.

## Tasks

- [x] 1. Implement ModelManagerCore shadow watcher and model installation
  - [x] 1.1 Create ModelManagerCore entry point with shadow subscription
    - Create `greengrass-components/artifacts/com.example.ModelManagerCore/1.0.0/model_manager_core.py` (replace existing)
    - Subscribe to `model-config` named shadow delta via Greengrass IPC
    - On delta: compare desired `models` with current reported `models` to determine what needs installing/removing
    - _Requirements: 1.1, 1.2, 1.3_

  - [x] 1.2 Implement snap model installation
    - When a model with `source: "snap"` is requested, run `snap install cv-inference.model-{model_id}`
    - Read `manifest.json` from the installed component path (`$SNAP_COMPONENTS/model-{model_id}/`)
    - Update reported state with status `installing` then `ready` (or `failed` with reason)
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [x] 1.3 Implement S3 model download
    - When a model with `source: "s3"` is requested, download from `s3_uri` to `$SNAP_COMMON/models/{model_id}/` using boto3
    - Read `manifest.json` from the downloaded directory
    - Update reported state with status `installing` then `ready` (or `failed` with reason)
    - _Requirements: 3.1, 3.2, 3.3, 3.4_

  - [x] 1.4 Implement OVMS multi-model configuration
    - After any model reaches `ready`, regenerate `$SNAP_COMMON/config/models_config.json` listing all ready models
    - Each entry: `{"config": {"name": model_name_from_manifest, "base_path": local_path}}`
    - OVMS auto-reloads via `--file_system_poll_wait_seconds`
    - _Requirements: 4.1, 4.2, 4.3_

  - [x] 1.5 Implement model removal
    - When a model is removed from desired state, remove it from OVMS config and delete local files
    - Update reported state to remove the model entry
    - Refuse to remove if it's the last remaining model
    - _Requirements: 8.1, 8.2, 8.3_

  - [x] 1.6 Write tests for ModelManagerCore
    - Test snap installation flow (mock subprocess)
    - Test S3 download flow (mock boto3)
    - Test OVMS config generation with multiple models
    - Test shadow reported state updates
    - Test model removal logic

- [x] 2. Implement DetectionHandler
  - [x] 2.1 Create DetectionHandler component
    - Create `greengrass-components/artifacts/com.example.DetectionHandler/1.0.0/detection_handler.py`
    - On startup: read `model-config` shadow reported state to find its assigned detection model's metadata
    - Subscribe to `camera/images` topic
    - _Requirements: 6.1, 6.4_

  - [x] 2.2 Implement dynamic model parameter loading
    - Read model_name, input_name, output_names, input_shape, labels_file from shadow model_metadata
    - Load labels from the model's local_path + labels_file
    - If model not yet ready, retry every 10 seconds
    - _Requirements: 6.1, 6.2, 6.3_

  - [x] 2.3 Implement inference and result publishing
    - Preprocess image according to input_shape from metadata
    - Call OVMS gRPC with model_name and input_name from metadata
    - Parse detection outputs (boxes, classes, scores) using output_names from metadata
    - Apply confidence threshold, annotate with labels, publish to `camera/detections`
    - _Requirements: 6.2, 6.3_

  - [x] 2.4 Write tests for DetectionHandler
    - Test model metadata loading from shadow
    - Test image preprocessing with different input shapes
    - Test result parsing and publishing

- [x] 3. Implement ClassificationHandler
  - [x] 3.1 Create ClassificationHandler component
    - Create `greengrass-components/artifacts/com.example.ClassificationHandler/1.0.0/classification_handler.py`
    - Same shadow-reading pattern as DetectionHandler but for classification models
    - Subscribe to `camera/images` topic
    - _Requirements: 7.1, 7.4_

  - [x] 3.2 Implement classification inference
    - Preprocess image according to input_shape
    - Call OVMS gRPC, receive class probability vector
    - Return top-N classifications with confidence scores
    - Publish to `camera/classifications`
    - _Requirements: 7.2, 7.3_

  - [x] 3.3 Write tests for ClassificationHandler
    - Test model metadata loading
    - Test classification output parsing (top-N)
    - Test independent operation from DetectionHandler

- [x] 4. Update cv-inference snap for multi-model support
  - [x] 4.1 Verify snap structure supports multiple model components
    - Confirm `cv-inference/components/model-faster-rcnn/` and `cv-inference/components/model-efficientnet/` both have valid manifest.json
    - Confirm OVMS `--file_system_poll_wait_seconds 5` is configured in snap service
    - Confirm models_config.json path is `$SNAP_COMMON/config/models_config.json`
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

  - [x] 4.2 Create/verify model manifests
    - Ensure `manifest.json` exists for faster-rcnn with correct input/output tensor names
    - Ensure `manifest.json` exists for efficientnet with correct input/output tensor names
    - _Requirements: 2.3_

- [x] 5. Create component recipes
  - [x] 5.1 Update ModelManagerCore recipe
    - Update `greengrass-components/recipes/com.example.ModelManagerCore-1.0.0.yaml`
    - IPC permissions: shadow get/update for `model-config`, IoT Core publish for status
    - _Requirements: 1.1_

  - [x] 5.2 Create DetectionHandler recipe
    - Create `greengrass-components/recipes/com.example.DetectionHandler-1.0.0.yaml`
    - IPC permissions: shadow get for `model-config`, subscribe to `camera/images`, publish to `camera/detections`
    - Configuration: `detection_model_id` (which model from the shadow to use)
    - _Requirements: 6.1_

  - [x] 5.3 Create ClassificationHandler recipe
    - Create `greengrass-components/recipes/com.example.ClassificationHandler-1.0.0.yaml`
    - IPC permissions: shadow get for `model-config`, subscribe to `camera/images`, publish to `camera/classifications`
    - Configuration: `classification_model_id` (which model from the shadow to use)
    - _Requirements: 7.1_

- [x] 6. Integration test
  - [x] 6.1 End-to-end test with both models
    - Verify: shadow update with two models → both install → OVMS serves both → both handlers produce output
    - Test with faster-rcnn (detection) and efficientnet (classification) simultaneously

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "4.1", "4.2"] },
    { "id": 1, "tasks": ["1.2", "1.3"] },
    { "id": 2, "tasks": ["1.4", "1.5"] },
    { "id": 3, "tasks": ["1.6", "5.1"] },
    { "id": 4, "tasks": ["2.1", "3.1", "5.2", "5.3"] },
    { "id": 5, "tasks": ["2.2", "2.3", "3.2"] },
    { "id": 6, "tasks": ["2.4", "3.3"] },
    { "id": 7, "tasks": ["6.1"] },
    { "id": 8, "tasks": ["7.1", "7.2"] },
    { "id": 9, "tasks": ["7.3"] }
  ]
}
```

- [x] 7. Ubuntu Core snap confinement: content interface setup
  - [x] 7.1 Add content interface slots to cv-inference snapcraft.yaml
    - Add `inference-config` slot: `interface: content`, `content: inference-config`, `write: [$SNAP_COMMON/config]`
    - Add `inference-models` slot: `interface: content`, `content: inference-models`, `write: [$SNAP_COMMON/models]`
    - This exposes the config and models directories for cross-snap write access from the Greengrass snap

  - [x] 7.2 Update ModelManagerCore recipe environment variables
    - Update `greengrass-components/recipes/com.example.ModelManagerCore-1.0.0.yaml`
    - Set `OVMS_CONFIG_DIR` to the content interface mount path (e.g., `{kernel:rootPath}/cv-inference-config`)
    - Set `SNAP_COMMON` to the content interface mount path for models (e.g., `{kernel:rootPath}/cv-inference-models`)
    - Document that the Greengrass snap must declare content plugs for `inference-config` and `inference-models`

  - [x] 7.3 Update tests to use content interface path resolution
    - Update test fixtures to simulate the content interface mount point structure
    - Verify ModelManagerCore writes to the correct paths when environment variables point to content interface mounts
    - Verify OVMS config file is written to the shared config directory

## Notes

- Total: 22 sub-tasks (19 original + 3 for snap confinement)
- No dashboard UI tasks — shadow manipulation via AWS Console is sufficient
- No separate S3ModelDownloader — boto3 in ModelManagerCore is simpler
- No property-based testing — standard unit/integration tests suffice for a demo
- The existing InferenceHandlerCore is replaced by DetectionHandler (same purpose, configurable)
- ClassificationHandler demonstrates multi-model capability
- Architecture is extensible: adding a SegmentationHandler or PoseHandler later follows the same pattern
- **Ubuntu Core confinement**: Cross-snap filesystem access uses Canonical's content interface. The existing code already uses environment variables for path resolution, so the change is primarily in snap definitions and recipe configuration.
