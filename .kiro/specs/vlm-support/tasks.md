# Implementation Plan: VLM Support

## Overview

This plan extends the existing dynamic model management system to support Vision Language Models (VLMs) via OpenVINO Model Server's MediaPipe graph serving with an OpenAI-compatible HTTP chat completions API. VLMs coexist with CV models on the same device: CV models continue using `models_config.json` + gRPC port 9000, while VLMs use per-model `graph.pbtxt` files + HTTP port 8000. The implementation adds VLM manifest validation, graph generation, a new VLMHandler component, engine script updates, NPU queue management, and VLM-specific error reporting.

## Tasks

- [ ] 1. Implement VLM manifest validation module
  - [ ] 1.1 Create VLM manifest validator
    - Create `greengrass-components/artifacts/com.example.ModelManagerCore/1.0.0/vlm_manifest.py`
    - Implement `validate_vlm_manifest(manifest_dict)` that validates all required fields: `model_id` (1-64 chars, alphanumeric+hyphens), `model_name` (1-128 chars), `model_type` (must be "vlm"), `version` (semver), `models_path` (non-empty), `cache_size` (int >= 1), `max_num_batched_tokens` (int >= 1), `device_targets` (non-empty array of "CPU"/"GPU"/"NPU"), `chat_template_file` (non-empty), `tokenizer_config_file` (non-empty)
    - Return list of validation errors (empty list = valid)
    - Apply defaults for optional fields: `max_num_seqs` = 256, `best_of_limit` = 1
    - Implement `check_device_compatibility(manifest, active_engine)` that checks if the active engine (uppercase) is in `device_targets`
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_

  - [ ]* 1.2 Write property test for VLM manifest validation completeness
    - **Property 2: VLM Manifest Validation Completeness**
    - Use hypothesis to generate arbitrary JSON objects and verify the validator accepts if and only if all required fields are present with correct types/constraints
    - **Validates: Requirements 7.1, 7.3, 7.4, 1.5**

  - [ ]* 1.3 Write property test for VLM manifest optional field defaults
    - **Property 3: VLM Manifest Optional Field Defaults**
    - Use hypothesis to generate valid manifests with optional fields omitted, verify defaults are applied
    - **Validates: Requirements 7.2**

  - [ ]* 1.4 Write property test for device compatibility enforcement
    - **Property 4: Device Compatibility Enforcement**
    - Use hypothesis to generate manifests with various `device_targets` arrays and active engines, verify failure when engine not in targets
    - **Validates: Requirements 7.5**

- [ ] 2. Implement ModelManagerCore VLM routing and installation
  - [ ] 2.1 Add VLM routing logic to ModelManagerCore
    - Modify `greengrass-components/artifacts/com.example.ModelManagerCore/1.0.0/model_manager_core.py`
    - In `_handle_model_install`, detect `model_type: "vlm"` in model_config and route to new `_handle_vlm_install` method
    - Validate required VLM desired state fields (`model_type`, `source`, `model_name`); report `failed` with reason if missing
    - _Requirements: 1.1, 1.2, 1.5_

  - [ ] 2.2 Implement VLM snap installation
    - Add `_install_snap_vlm(model_id, model_config)` method to ModelManagerCore
    - Run `snap install cv-inference.vlm-{model_id}` (note `vlm-` prefix instead of `model-`)
    - Read `vlm_manifest.json` from `$SNAP_COMPONENTS/vlm-{model_id}/`
    - Validate manifest using `vlm_manifest.validate_vlm_manifest()`
    - Check device compatibility with active engine
    - Verify required artifacts exist: `openvino_model.bin`, `openvino_model.xml`, `openvino_tokenizer.bin`, `openvino_tokenizer.xml`, `openvino_detokenizer.bin`, `openvino_detokenizer.xml`, `tokenizer_config.json`, `chat_template.jinja`
    - Report `failed` with reason listing each missing artifact if any are absent
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 3.4_

  - [ ] 2.3 Implement VLM S3 installation
    - Add `_install_s3_vlm(model_id, model_config)` method to ModelManagerCore
    - Download from `s3_uri` to `$SNAP_COMMON/models/{model_id}/`
    - Report status `installing` before download begins
    - Read and validate `vlm_manifest.json` from downloaded directory
    - Check device compatibility and verify required artifacts
    - Report `failed` with specific reason on network error, access denied, or invalid URI
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

  - [ ]* 2.4 Write property test for missing artifact reporting
    - **Property 8: Missing Artifact Reporting**
    - Use hypothesis to generate subsets of required artifacts that are absent, verify the failure reason lists each missing artifact by filename
    - **Validates: Requirements 3.4**

- [ ] 3. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 4. Implement graph.pbtxt generation
  - [ ] 4.1 Create graph generator module
    - Create `greengrass-components/artifacts/com.example.ModelManagerCore/1.0.0/vlm_graph.py`
    - Implement `generate_graph_pbtxt(manifest, active_engine, models_path)` that produces the protobuf text format
    - Use `HttpLLMCalculator` for CPU/GPU engines with `dynamic_split_fuse: true`
    - Use `StatefulLLMCalculator` for NPU engine without `dynamic_split_fuse`, with `max_num_seqs: 1`
    - Map `models_path`, `cache_size`, `max_num_batched_tokens`, `device` (uppercase) from manifest and engine
    - Include `max_num_seqs` and `best_of_limit` from manifest (with defaults applied)
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 10.1_

  - [ ] 4.2 Integrate graph generation into ModelManagerCore
    - After successful VLM manifest validation, call `generate_graph_pbtxt()` and write to `$SNAP_COMMON/config/vlm/{model_id}/graph.pbtxt`
    - Create directory `$SNAP_COMMON/config/vlm/{model_id}/` if it does not exist
    - Report `failed` with reason if filesystem write fails
    - _Requirements: 4.4, 4.7_

  - [ ]* 4.3 Write property test for graph generation correctness
    - **Property 5: Graph Generation Correctness**
    - Use hypothesis to generate valid manifests and engines (CPU, GPU, NPU), verify calculator type, field mapping, and NPU-specific constraints
    - **Validates: Requirements 4.1, 4.2, 4.3, 10.1**

- [ ] 5. Implement graph config registry
  - [ ] 5.1 Create graph config manager
    - Add `update_graph_config(model_id, graph_base_path, config_dir)` and `remove_from_graph_config(model_id, config_dir)` functions to `vlm_graph.py`
    - Write `$SNAP_COMMON/config/graph_config.json` with `mediapipe_config_list` array containing one entry per ready VLM: `{"name": model_id, "base_path": graph_base_path}`
    - Ensure adding/removing VLM entries does NOT modify `models_config.json`
    - _Requirements: 4.5, 4.6_

  - [ ] 5.2 Wire graph config updates into ModelManagerCore VLM flow
    - After writing `graph.pbtxt`, call `update_graph_config()` to register the VLM
    - Update reported state with VLM metadata: `model_name`, `model_type: "vlm"`, `endpoint_port: 8000`, `device`, `cache_size`, `max_num_batched_tokens`, `supported_features`, `pipeline`, `local_path`
    - For NPU: include `pipeline: "stateful"` and `max_concurrent_requests: 1`
    - _Requirements: 1.3, 10.5_

  - [ ]* 5.3 Write property test for CV/VLM configuration isolation
    - **Property 1: CV/VLM Configuration Isolation**
    - Use hypothesis to generate combinations of CV and VLM model operations, verify `models_config.json` is unaffected by VLM changes and `graph_config.json`/`graph.pbtxt` files are unaffected by CV changes
    - **Validates: Requirements 1.2, 1.4, 4.6**

  - [ ]* 5.4 Write property test for graph registry completeness
    - **Property 6: Graph Registry Completeness**
    - Use hypothesis to generate sets of VLM models with various statuses, verify `graph_config.json` contains exactly one entry per ready VLM
    - **Validates: Requirements 4.5**

  - [ ]* 5.5 Write property test for VLM reported state completeness
    - **Property 7: VLM Reported State Completeness**
    - Use hypothesis to generate valid VLM installations with various engines, verify all required metadata fields are present and NPU-specific fields appear when engine is NPU
    - **Validates: Requirements 1.3, 10.5**

- [ ] 6. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 7. Update Inference Snap engine scripts
  - [ ] 7.1 Update CPU engine server script
    - Modify `cv-inference/engines/cpu/server` to add `--rest_port 8000` parameter
    - Add conditional `--graph_path $SNAP_COMMON/config/vlm_graphs/` parameter when `$SNAP_COMMON/config/graph_config.json` exists
    - _Requirements: 8.1, 8.2, 8.6_

  - [ ] 7.2 Update GPU engine server script
    - Modify `cv-inference/engines/gpu/server` to add `--rest_port 8000` parameter
    - Add conditional `--graph_path $SNAP_COMMON/config/vlm_graphs/` parameter when `$SNAP_COMMON/config/graph_config.json` exists
    - _Requirements: 8.1, 8.2, 8.6_

  - [ ] 7.3 Update NPU engine server script
    - Modify `cv-inference/engines/npu/server` to add `--rest_port 8000` parameter
    - Add conditional `--graph_path $SNAP_COMMON/config/vlm_graphs/` parameter when `$SNAP_COMMON/config/graph_config.json` exists
    - Add `--max_concurrent_requests 1` parameter for Stateful VLM pipeline
    - _Requirements: 8.1, 8.2, 8.4, 8.6_

  - [ ] 7.4 Update snapcraft.yaml for VLM support
    - Add `OVMS_REST_PORT: "8000"` to the ovms app environment in `cv-inference/snap/snapcraft.yaml`
    - Add VLM snap component definitions using `vlm-` prefix naming convention (e.g., `vlm-llava`)
    - _Requirements: 5.1, 8.3_

- [ ] 8. Implement VLMHandler component
  - [ ] 8.1 Create VLMHandler entry point
    - Create `greengrass-components/artifacts/com.example.VLMHandler/1.0.0/vlm_handler.py`
    - Read VLM model_metadata from `model-config` shadow reported state (model_name, endpoint_port, supported_features, device, pipeline)
    - If VLM model not yet ready, retry every 10 seconds
    - Subscribe to `camera/images` topic
    - Read `VLM_PROMPT` from environment (default: "Describe this image")
    - Read `VLM_MODEL_ID` from component configuration
    - _Requirements: 6.1, 6.5_

  - [ ] 8.2 Implement chat completion request construction
    - Read image from path received in `camera/images` message
    - Base64-encode the image with `data:image/jpeg;base64,` prefix
    - Construct OpenAI-compatible chat completion request with `messages` array containing text prompt and image_url content
    - Set `model` field to the model_name from metadata
    - Set `stream: false` for non-streaming responses
    - _Requirements: 6.2, 5.2_

  - [ ] 8.3 Implement HTTP client and response publishing
    - POST request to `http://localhost:{endpoint_port}/v3/chat/completions` with 30-second timeout
    - Parse JSON response to extract generated text from `choices[0].message.content`
    - Publish to `camera/vlm-responses` topic with: `model_name`, `prompt`, `response_text`, `source_image_path`, `timestamp`
    - On HTTP 4xx/5xx or connection/timeout error: log error, continue processing next image
    - _Requirements: 6.3, 6.4, 6.6_

  - [ ]* 8.4 Write property test for chat request construction
    - **Property 9: Chat Request Construction**
    - Use hypothesis to generate arbitrary image byte sequences and prompt strings, verify base64 encoding correctness and request structure
    - **Validates: Requirements 6.2**

  - [ ]* 8.5 Write property test for VLM response publishing completeness
    - **Property 10: VLM Response Publishing Completeness**
    - Use hypothesis to generate OVMS responses, verify published message contains response text, source image path, and prompt
    - **Validates: Requirements 6.4**

- [ ] 9. Implement NPU request queue management
  - [ ] 9.1 Add NPU queue to VLMHandler
    - In `vlm_handler.py`, implement request queue (max 10 items) activated when `pipeline == "stateful"` or `device == "npu"`
    - Process requests sequentially (one at a time) when NPU is active
    - Reject new requests with capacity error when queue has 10 items
    - Reject queued requests with timeout error after 30 seconds waiting
    - Reject requests containing more than one image with NPU single-image error
    - _Requirements: 10.2, 10.3, 10.4, 10.6_

  - [ ]* 9.2 Write property test for NPU queue management
    - **Property 11: NPU Queue Management**
    - Use hypothesis to generate sequences of incoming requests with timing, verify: max 1 processing, max 10 queued, 30s timeout rejection, capacity rejection
    - **Validates: Requirements 10.2, 10.3, 10.4**

  - [ ]* 9.3 Write property test for NPU single-image enforcement
    - **Property 12: NPU Single-Image Enforcement**
    - Use hypothesis to generate chat requests with varying numbers of images, verify rejection when more than one image on NPU
    - **Validates: Requirements 10.6**

- [ ] 10. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 11. Implement VLM removal with in-flight protection
  - [ ] 11.1 Add VLM removal to ModelManagerCore
    - In `_handle_model_removal`, detect VLM models (check `model_type` in reported metadata) and route to `_handle_vlm_removal`
    - Check if VLMHandler has an in-flight request (via shared state file or IPC)
    - If in-flight: wait up to 120 seconds for completion
    - If timeout: force removal, briefly report `failed` with timeout reason
    - Remove `graph.pbtxt` from `$SNAP_COMMON/config/vlm/{model_id}/`
    - Remove entry from `graph_config.json`
    - Delete local model artifacts
    - Remove model key from reported state
    - _Requirements: 9.1, 9.2, 9.3, 9.4_

  - [ ]* 11.2 Write property test for in-flight removal protection
    - **Property 14: In-Flight Removal Protection**
    - Use hypothesis to generate removal scenarios with active/inactive requests and varying elapsed times, verify removal waits or times out at 120s
    - **Validates: Requirements 9.3**

- [ ] 12. Implement VLM error reporting
  - [ ] 12.1 Add last_error persistence to ModelManagerCore
    - When reporting VLM model failure, include `last_error` object with: `timestamp` (ISO 8601 UTC), `error_type` (one of `graph_generation`, `graph_load`, `validation`), `message` (max 512 chars)
    - When model transitions from `failed` to `ready`, retain `last_error` from previous failure
    - Integrate error reporting into all VLM failure paths (manifest validation, graph generation, graph load, artifact validation)
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5_

  - [ ]* 12.2 Write property test for error object persistence
    - **Property 13: Error Object Persistence**
    - Use hypothesis to generate error events and recovery sequences, verify `last_error` structure and persistence across failed-to-ready transitions
    - **Validates: Requirements 11.4, 11.5**

- [ ] 13. Create component recipes
  - [ ] 13.1 Create VLMHandler recipe
    - Create `greengrass-components/recipes/com.example.VLMHandler-1.0.0.yaml`
    - IPC permissions: shadow get for `model-config`, subscribe to `camera/images`, publish to `camera/vlm-responses`
    - Configuration: `VLM_MODEL_ID` (which VLM from shadow to use), `VLM_PROMPT` (default prompt)
    - Dependencies: `com.example.ModelManagerCore` (soft dependency)
    - _Requirements: 6.1_

  - [ ] 13.2 Update ModelManagerCore recipe for VLM support
    - Update `greengrass-components/recipes/com.example.ModelManagerCore-1.0.0.yaml`
    - Add `requests` and `hypothesis` to requirements.txt if not present (for HTTP client in tests)
    - Ensure IPC permissions cover VLM-related shadow updates
    - _Requirements: 1.1_

- [ ] 14. Integration tests
  - [ ]* 14.1 Write integration test for VLM installation flow
    - Test: shadow delta with VLM model (snap source) -> install -> manifest validation -> graph generation -> graph_config update -> reported state ready
    - Mock subprocess (snap install) and filesystem
    - Verify complete flow from delta to reported state
    - _Requirements: 1.1, 2.1, 4.1, 4.5_

  - [ ]* 14.2 Write integration test for mixed CV + VLM coexistence
    - Test: shadow with both CV model (faster-rcnn) and VLM model (llava) -> both configured independently
    - Verify `models_config.json` contains only CV model, `graph_config.json` contains only VLM
    - _Requirements: 1.4, 4.6_

  - [ ]* 14.3 Write integration test for VLMHandler request flow
    - Test: VLMHandler receives image -> constructs request -> calls mock OVMS HTTP -> publishes response
    - Mock HTTP endpoint returning valid chat completion response
    - Verify published message structure on `camera/vlm-responses`
    - _Requirements: 6.2, 6.3, 6.4_

  - [ ]* 14.4 Write integration test for VLM removal
    - Test: VLM model removal -> graph cleanup -> graph_config update -> reported state updated
    - Verify all three locations cleaned (graph file, graph_config entry, artifacts)
    - _Requirements: 9.1, 9.2_

- [ ] 15. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document using `hypothesis`
- Unit tests validate specific examples and edge cases
- The existing ModelManagerCore is extended (not replaced) - new VLM methods are added alongside existing CV model logic
- All 14 correctness properties from the design document are covered by property test sub-tasks
- Python is used throughout (matching existing codebase)
- Tests go in `tests/` directory at the project root

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "7.1", "7.2", "7.3", "7.4"] },
    { "id": 1, "tasks": ["1.2", "1.3", "1.4", "2.1"] },
    { "id": 2, "tasks": ["2.2", "2.3"] },
    { "id": 3, "tasks": ["2.4", "4.1"] },
    { "id": 4, "tasks": ["4.2", "4.3"] },
    { "id": 5, "tasks": ["5.1"] },
    { "id": 6, "tasks": ["5.2", "5.3", "5.4", "5.5"] },
    { "id": 7, "tasks": ["8.1"] },
    { "id": 8, "tasks": ["8.2", "8.3"] },
    { "id": 9, "tasks": ["8.4", "8.5", "9.1"] },
    { "id": 10, "tasks": ["9.2", "9.3", "11.1"] },
    { "id": 11, "tasks": ["11.2", "12.1"] },
    { "id": 12, "tasks": ["12.2", "13.1", "13.2"] },
    { "id": 13, "tasks": ["14.1", "14.2", "14.3", "14.4"] }
  ]
}
```
