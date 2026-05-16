# Requirements Document

## Introduction

VLM Support extends the existing Dynamic Model Management system to handle Vision Language Models (VLMs) alongside traditional computer vision models. VLMs are a distinct servable type in OpenVINO Model Server that use MediaPipe graphs with continuous batching, expose an OpenAI-compatible HTTP chat completions API (rather than gRPC tensor predict), and require additional artifacts (tokenizers, chat templates). This spec covers shadow schema extension, ModelManagerCore updates, a new VLMHandler Greengrass component, Inference Snap updates for VLM graph configuration, and a VLM-specific manifest schema. Both CV models and VLMs coexist on the same device, served by the same OVMS instance.

## Glossary

- **VLM**: Vision Language Model — a model that accepts images and text prompts, producing text responses via an OpenAI-compatible chat completions endpoint
- **Model_Config_Shadow**: The IoT Device Shadow named `model-config` that declares which models should be on the device and reports their status
- **Model_Manager**: The Greengrass component (`com.example.ModelManagerCore`) that watches the shadow and orchestrates model installation and OVMS configuration
- **VLM_Handler**: The Greengrass component (`com.example.VLMHandler`) that sends image+prompt requests to OVMS via the HTTP chat completions API
- **Inference_Snap**: The `cv-inference` Ubuntu Core snap that packages OVMS with hardware-optimised engines and delivers models as snap components
- **OVMS**: OpenVINO Model Server — serves CV models via gRPC and VLMs via HTTP chat completions
- **Graph_Config**: A `graph.pbtxt` MediaPipe graph definition file that configures OVMS to serve a VLM using the LLM calculator with continuous batching
- **VLM_Manifest**: A `vlm_manifest.json` file included with each VLM that describes its serving parameters (cache size, max tokens, device target, chat template)
- **Continuous_Batching**: The OVMS serving pipeline for VLMs on CPU and GPU that supports concurrent requests with KV-cache management
- **Stateful_Pipeline**: The OVMS serving pipeline for VLMs on NPU, limited to single-image requests without tools support
- **Chat_Completions_API**: The OpenAI-compatible `/v3/chat/completions` HTTP endpoint exposed by OVMS for VLM inference

## Requirements

### Requirement 1: Shadow Schema Extension for VLM Declaration

**User Story:** As an operator, I want to declare VLM models in the same Device Shadow used for CV models, so that a single control plane manages all model types on the device.

#### Acceptance Criteria

1. THE Model_Config_Shadow desired state SHALL accept model entries with `model_type: "vlm"` in addition to the existing CV model entries (which have no `model_type` field or `model_type: "cv"`), where each VLM entry includes at minimum: `model_type`, `source`, and `model_name`
2. WHEN a model entry includes `model_type: "vlm"`, THE Model_Manager SHALL configure it via a graph descriptor file (written to the model's local directory) rather than adding it to the OVMS `models_config.json`
3. THE Model_Config_Shadow reported state for VLM models SHALL include: status (one of `installing`, `ready`, or `failed` with a `reason` string when failed), model_metadata (model_name, endpoint_port as an integer in the range 9001-65535, device as one of `cpu`/`gpu`/`npu`, cache_size in bytes, max_num_batched_tokens as a positive integer, supported_features as a list of zero or more string identifiers), and local_path
4. WHEN both CV and VLM models are declared in the same shadow document, THE Model_Manager SHALL process each model type using its respective configuration mechanism (models_config.json for CV, graph descriptor for VLM) and SHALL NOT modify one type's configuration when adding or removing the other type
5. IF a model entry includes `model_type: "vlm"` but is missing required fields, THEN THE Model_Manager SHALL set that model's status to `failed` with a `reason` indicating the missing fields

### Requirement 2: VLM Model Installation via Snap

**User Story:** As a platform engineer, I want VLM models delivered as snap components, so that the same delivery mechanism used for CV models applies to VLMs with automatic hardware variant selection.

#### Acceptance Criteria

1. WHEN a model with `model_type: "vlm"` and `source: "snap"` is requested, THE Model_Manager SHALL invoke `snap install` for the corresponding snap component using the naming convention `cv-inference.vlm-{model_id}` (e.g. `cv-inference.vlm-llava`)
2. EACH VLM snap component SHALL include a VLM_Manifest file (`vlm_manifest.json`) describing its serving parameters: `model_id` (string), `model_name` (string), `model_type` (string, value "vlm"), `version` (string, semver), `models_path` (string, relative path to model artifacts), `cache_size` (integer, number of KV cache blocks), `max_num_batched_tokens` (integer, maximum tokens per batch), `device_targets` (array of strings from: "CPU", "GPU", "NPU"), `chat_template_file` (string, filename), and `tokenizer_config_file` (string, filename)
3. EACH VLM snap component SHALL include the required model artifacts: `openvino_model.bin`, `openvino_model.xml`, `openvino_tokenizer.bin`, `openvino_tokenizer.xml`, `openvino_detokenizer.bin`, `openvino_detokenizer.xml`, `tokenizer_config.json`, and `chat_template.jinja`
4. WHEN snap installation completes successfully, THE Model_Manager SHALL read the `vlm_manifest.json` and update the reported state with status `ready` and the VLM model metadata including: `model_name`, `model_type`, `version`, `models_path`, `cache_size`, `max_num_batched_tokens`, `device_targets`, `chat_template_file`, `tokenizer_config_file`, and `local_path`
5. IF VLM snap installation fails or the installed component does not contain a valid `vlm_manifest.json`, THEN THE Model_Manager SHALL set that model's status to `failed` with a `reason` string describing the error in the reported state

### Requirement 3: VLM Model Installation via S3

**User Story:** As an operator, I want to deploy custom VLM models from S3 when they are not available in the Snap Store.

#### Acceptance Criteria

1. WHEN a model with `model_type: "vlm"` and `source: "s3"` is requested, THE Model_Manager SHALL download the model artifacts from the provided `s3_uri` to `$SNAP_COMMON/models/{model_id}/` and SHALL report the model status as `installing` in the reported state before the download begins
2. THE S3 VLM model directory SHALL contain a `vlm_manifest.json` with the same schema as snap-delivered VLMs
3. THE S3 VLM model directory SHALL contain all required VLM artifacts: OpenVINO model files (`.xml` and `.bin`), tokenizer, detokenizer, tokenizer configuration, and chat template
4. IF any required artifact is missing from the downloaded directory, THEN THE Model_Manager SHALL report status `failed` with a `reason` string listing each missing artifact by name
5. IF the S3 download fails due to network error, access denied, or invalid `s3_uri`, THEN THE Model_Manager SHALL report status `failed` with a `reason` string indicating the failure cause
6. WHEN the download completes and all required artifacts are present, THE Model_Manager SHALL read the `vlm_manifest.json`, update the reported state with status `ready` and the model's `model_metadata`, and proceed to graph configuration

### Requirement 4: OVMS Graph Configuration for VLM Serving

**User Story:** As a platform engineer, I want OVMS configured to serve VLMs using MediaPipe graph definitions, so that VLMs use the correct continuous batching pipeline.

#### Acceptance Criteria

1. WHEN a VLM model reaches status `ready`, THE Model_Manager SHALL generate a `graph.pbtxt` file for that model containing the HttpLLMCalculator node configuration
2. THE generated Graph_Config SHALL include: `models_path` pointing to the VLM artifacts directory, `cache_size` from the VLM_Manifest, `max_num_batched_tokens` from the VLM_Manifest, and `device` set to the uppercase device string of the active hardware engine (one of "CPU", "GPU", or "NPU")
3. IF the active engine is NPU, THEN THE Graph_Config SHALL set the node `type` to "StatefulLLMCalculator" to use the Stateful pipeline; otherwise THE Graph_Config SHALL set the node `type` to "HttpLLMCalculator" to use Continuous Batching
4. THE Model_Manager SHALL write the Graph_Config to `$SNAP_COMMON/config/vlm/{model_id}/graph.pbtxt`
5. THE Model_Manager SHALL configure OVMS to load the VLM graph by writing the graph service path (`$SNAP_COMMON/config/vlm/{model_id}/`) to the OVMS graph configuration file at `$SNAP_COMMON/config/graph_config.json` and triggering an OVMS reload
6. THE Graph_Config generation SHALL NOT modify the existing `models_config.json` used for CV models — OVMS SHALL continue serving all previously loaded CV models after a VLM graph is added
7. IF the Model_Manager cannot write the Graph_Config file due to a filesystem error or missing VLM_Manifest fields required for generation, THEN THE Model_Manager SHALL set the VLM model status to `failed` with a reason describing the graph generation error

### Requirement 5: VLM HTTP Endpoint Exposure

**User Story:** As a developer, I want OVMS to expose an HTTP endpoint for VLM chat completions, so that the VLMHandler can send image+text requests and receive text responses.

#### Acceptance Criteria

1. THE Inference_Snap SHALL expose OVMS HTTP port 8000 for the OpenAI-compatible chat completions API in addition to the existing gRPC port 9000
2. THE Chat_Completions_API SHALL accept POST requests at `/v3/chat/completions` with a JSON body containing a `messages` array where each message may include text content and image content (base64-encoded with a `data:image/*;base64,` prefix, or an image URL), with a maximum image payload size of 20 MB per image
3. THE Chat_Completions_API SHALL support both streaming (`"stream": true` in the request body, returning server-sent events) and non-streaming (`"stream": false` or field omitted, returning a single JSON response) response modes
4. WHILE a VLM is loaded and status is `ready`, THE Chat_Completions_API SHALL respond to requests within the timeout period specified in the model's manifest `timeout_seconds` field (default: 30 seconds if not specified, maximum: 120 seconds)
5. IF a request is received when no VLM is loaded or the VLM status is not `ready`, THEN THE Chat_Completions_API SHALL return an HTTP 503 response with an error message indicating the model is not available
6. IF a request payload exceeds 20 MB per image or contains an invalid message format, THEN THE Chat_Completions_API SHALL return an HTTP 400 response with an error message indicating the validation failure

### Requirement 6: VLM Inference Handler

**User Story:** As a developer, I want a VLMHandler component that sends image+prompt requests to the VLM and publishes text responses, so that edge applications can use vision-language understanding.

#### Acceptance Criteria

1. THE VLM_Handler SHALL read VLM model_metadata from the `model-config` shadow reported state to determine: model_name, endpoint_port, and supported_features
2. THE VLM_Handler SHALL subscribe to `camera/images` and construct chat completion requests containing the image (base64-encoded) and a text prompt read from the component configuration (environment variable `VLM_PROMPT`), defaulting to "Describe this image" if not set
3. THE VLM_Handler SHALL call OVMS via HTTP POST to the Chat_Completions_API at `http://localhost:{endpoint_port}/v3/chat/completions` with the constructed request, using a request timeout of 30 seconds
4. THE VLM_Handler SHALL publish VLM responses to `camera/vlm-responses` topic including the model response text, the source image path as received from the `camera/images` message, and the prompt used
5. IF the VLM model is not yet available (status not `ready`), THE VLM_Handler SHALL wait and retry at 10-second intervals until the model becomes available
6. IF the Chat_Completions_API returns an HTTP error status (4xx or 5xx) or the request fails due to a connection or timeout error, THE VLM_Handler SHALL log the error details and continue processing subsequent images without crashing

### Requirement 7: VLM Manifest Schema

**User Story:** As a platform engineer, I want a well-defined manifest schema for VLM models that captures all parameters needed for graph configuration and serving.

#### Acceptance Criteria

1. THE VLM_Manifest SHALL include the following required fields with their specified types: `model_id` (string, 1-64 characters, alphanumeric and hyphens only), `model_name` (string, 1-128 characters), `model_type` (string, value: "vlm"), `version` (string, semantic version format "MAJOR.MINOR.PATCH"), `models_path` (string, relative path to model artifacts directory), `cache_size` (integer, minimum 1), `max_num_batched_tokens` (integer, minimum 1), `device_targets` (array of one or more strings from: "cpu", "gpu", "npu"), `chat_template_file` (string, filename of the Jinja2 chat template), and `tokenizer_config_file` (string, filename of the tokenizer configuration)
2. THE VLM_Manifest SHALL include optional fields: `max_num_seqs` (integer, minimum 1, default 256 — maximum concurrent sequences), `best_of_limit` (integer, minimum 1, default 1 — maximum number of candidate sequences generated per request for best-of-N selection), `default_prompt` (string, maximum 1024 characters — default text prompt for image analysis)
3. WHEN the Model_Manager reads a VLM_Manifest during model installation, THE Model_Manager SHALL validate that all required fields are present and conform to their specified types and constraints
4. IF any required field is missing, has an incorrect type, or violates its constraints (e.g., `device_targets` is empty, `model_type` is not "vlm", `model_id` contains invalid characters), THEN THE Model_Manager SHALL report status `failed` with a reason describing each validation error encountered
5. IF the active hardware engine is not listed in the VLM_Manifest `device_targets` array, THEN THE Model_Manager SHALL report status `failed` with a reason indicating that the model does not support the active device

### Requirement 8: Inference Snap VLM Serving Support

**User Story:** As a platform engineer, I want the Inference Snap updated to support VLM serving alongside CV model serving.

#### Acceptance Criteria

1. THE Inference_Snap SHALL configure OVMS with both `--config_path` (pointing to the CV models configuration at `$SNAP_COMMON/config/models_config.json`) and `--graph_path` (pointing to the VLM graph definition directory at `$SNAP_COMMON/config/vlm_graphs/`) startup parameters when at least one VLM component is installed
2. THE Inference_Snap SHALL expose HTTP port 8000 with `--rest_port 8000` in addition to the existing gRPC port 9000
3. WHEN a VLM snap component is installed, THE Inference_Snap SHALL register the component's graph definition with OVMS, where the VLM component contains model weights, tokenizer configuration, and chat template files
4. WHILE the active engine is NPU, THE Inference_Snap SHALL configure OVMS with `--max_concurrent_requests 1` and exclude MediaPipe graph nodes that invoke tool-calling endpoints for the Stateful VLM pipeline
5. IF a VLM snap component is missing any required artifact (model weights, tokenizer configuration, or chat template), THEN THE Inference_Snap SHALL reject the component installation, log an error message indicating which artifact is missing, and leave the existing OVMS configuration unchanged
6. IF no VLM snap component is installed, THEN THE Inference_Snap SHALL omit the `--graph_path` parameter and start OVMS with only `--config_path` for CV model serving

### Requirement 9: VLM Model Removal

**User Story:** As an operator, I want to remove VLM models from the device by updating the shadow, using the same mechanism as CV model removal.

#### Acceptance Criteria

1. WHEN a VLM model is removed from the desired `models` object, THE Model_Manager SHALL remove its Graph_Config file from `$SNAP_COMMON/config/vlm/{model_id}/`, remove the model from the OVMS graph service configuration, and delete its local artifacts from the model directory
2. WHEN VLM model removal completes, THE Model_Manager SHALL remove that model's key from the reported state `models` object
3. WHILE the VLM_Handler is actively processing a request for a VLM model (between request receipt and response delivery), THE Model_Manager SHALL NOT remove that model — removal SHALL wait until the current request completes or until a 120-second timeout elapses
4. IF the 120-second removal wait timeout elapses while the VLM_Handler is still processing, THE Model_Manager SHALL proceed with removal and report the model status as `failed` with a reason indicating the removal was forced due to timeout before removing the model key from reported state

### Requirement 10: NPU-Specific VLM Constraints

**User Story:** As a platform engineer, I want the system to enforce NPU limitations for VLMs, so that operators receive clear feedback when NPU constraints apply.

#### Acceptance Criteria

1. WHILE the active engine is NPU, THE Model_Manager SHALL configure the VLM with the Stateful pipeline and limit concurrent requests to one
2. WHILE the active engine is NPU, THE VLM_Handler SHALL process requests sequentially (one at a time) and queue additional requests up to a maximum of 10 queued requests
3. WHILE the active engine is NPU, IF a request has been queued for more than 30 seconds without beginning processing, THEN THE VLM_Handler SHALL reject that request and return an error indicating a queue timeout
4. WHILE the active engine is NPU, IF the request queue is full (10 requests queued), THEN THE VLM_Handler SHALL reject new incoming requests and return an error indicating the queue is at capacity
5. WHILE the active engine is NPU, THE reported state for a VLM SHALL include `"pipeline": "stateful"` and `"max_concurrent_requests": 1` in the model_metadata to inform operators of the constraint
6. WHILE the active engine is NPU, THE VLM_Handler SHALL reject requests containing more than one image and return an error indicating NPU single-image limitation

### Requirement 11: VLM Error Reporting

**User Story:** As an operator, I want VLM-specific errors reported in the shadow, so that VLM issues can be diagnosed without device access.

#### Acceptance Criteria

1. IF VLM graph configuration generation fails, THEN THE Model_Manager SHALL set the VLM model status to `failed` with a `reason` string (maximum 512 characters) describing the graph generation error and SHALL update the shadow reported state within 30 seconds of the failure occurring
2. IF OVMS fails to load a VLM graph, THEN THE Model_Manager SHALL report the model status as `failed` with a `reason` string indicating the graph load error returned by OVMS
3. IF the VLM model artifacts fail validation (missing tokenizer file, chat template that cannot be parsed, or model format not supported by the installed OVMS version), THEN THE Model_Manager SHALL report status `failed` with a `reason` string listing each specific validation failure encountered
4. THE reported state for VLM models SHALL include a `last_error` object containing `timestamp` (ISO 8601 UTC), `error_type` (one of `graph_generation`, `graph_load`, or `validation`), and `message` (maximum 512 characters) that persists the most recent error even after the model recovers to `ready` status
5. WHEN a VLM model transitions from `failed` to `ready` status, THE Model_Manager SHALL retain the `last_error` field from the previous failure and SHALL NOT clear it automatically
