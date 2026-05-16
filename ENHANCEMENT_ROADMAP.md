# Improvement Recommendations

This document captures prioritised improvement ideas for the Ubuntu Core / AWS Greengrass / Intel OpenVINO computer vision edge demo. All recommendations retain the core technology stack.

---

## Priority Recommendations

| Priority | Improvement | Theme |
|---|---|---|
| 1 | [Confidence Threshold Filtering](#1-confidence-threshold-filtering) ✓ | Inference quality |
| 2 | [IoT Device Shadow for Runtime Configuration](#3-iot-device-shadow-for-runtime-configuration) | Cloud-to-edge control |
| 3 | [Model Delivery via Ubuntu Inference Snaps](#7-model-delivery-via-ubuntu-inference-snaps) | Model lifecycle management |
| 4 | [Event-Driven Alerting on Specific Detections](#4-event-driven-alerting-on-specific-detections) | Real-world applicability |
| 5 | [Motion-Triggered Inference](#2-motion-triggered-inference) | Edge intelligence |
| 6 | [Dashboard Bounding Box Overlay as Interactive Data](#5-dashboard-bounding-box-overlay-as-interactive-data) | Visualisation |
| 7 | [Multi-Model Support via OpenVINO Model Server](#6-multi-model-support-via-openvino-model-server) | AI capability breadth |

---

## 1. Confidence Threshold Filtering

> **Status: Complete** — confidence threshold filtering is implemented, tested, and working. Runtime threshold updates from the React dashboard are applied immediately via the IoT Device Shadow delta mechanism. The fix addresses the original shadow delta nesting level bug, switches the subscription to cloud MQTT (`subscribe_to_iot_core`), and includes property-based tests validating both the fix and preservation of existing behavior.

### Problem

The `InferenceHandlerCore` currently renders the top 10 detections unconditionally — a bounding box with a confidence score of 0.01 is drawn identically to one scored 0.99. This produces visually noisy output and undermines confidence in the AI results.

### Solution

Add a configurable `confidence_threshold` parameter to the `InferenceHandlerCore` component. Only detections above this threshold are annotated on the image and included in the published MQTT payload.

Rather than making the threshold purely a static deployment-time setting, the implementation combines the recipe configuration with an AWS IoT Device Shadow (`inference-config`) so the threshold can be adjusted at runtime from the React dashboard without any redeployment.

### Implementation

**Recipe (`com.example.InferenceHandlerCore-1.0.0.yaml`):**

- `ConfidenceThreshold: "0.5"` added to `DefaultConfiguration`, passed as `CONFIDENCE_THRESHOLD` env var to the component
- `aws.greengrass.ShadowManager` added as a component dependency
- IPC access granted for `GetThingShadow` and `UpdateThingShadow` on the `inference-config` named shadow, and `SubscribeToTopic` on the shadow delta topic:

```yaml
aws.greengrass.ShadowManager:
  com.example.InferenceHandlerCore:shadow:3:
    policyDescription: 'Allows read and write access to the inference-config named shadow'
    operations:
      - 'aws.greengrass#GetThingShadow'
      - 'aws.greengrass#UpdateThingShadow'
    resources:
      - '$aws/things/*/shadow/name/inference-config'
```

**`inference_handler_core.py` — three-phase shadow integration:**

1. **Startup restore** — `load_shadow_config()` reads the `reported.confidence_threshold` from the shadow so the last operator-set value is applied immediately on component restart, taking precedence over the recipe default:

```python
response = self.ipc_client.get_thing_shadow(
    thing_name=self.thing_name, shadow_name='inference-config'
)
shadow = json.loads(response.payload)
reported = shadow.get('state', {}).get('reported', {})
if 'confidence_threshold' in reported:
    self.config['confidence_threshold'] = float(reported['confidence_threshold'])
```

2. **Runtime delta subscription** — `run()` subscribes to the shadow delta topic so updates from the dashboard take effect immediately without restarting the component:

```python
delta_topic = f"$aws/things/{self.thing_name}/shadow/name/inference-config/update/delta"
self.ipc_client.subscribe_to_iot_core(
    topic_name=delta_topic,
    qos='1',
    on_stream_event=self.on_shadow_delta,
    ...
)
```

3. **Reported state sync** — after applying a delta (or on startup), `update_shadow_reported()` writes the active threshold back to `reported` so the shadow stays consistent and the dashboard always reflects the live device value.

**Detection loop filter** in `run_inference()`:

```python
threshold = self.config['confidence_threshold']
for i in range(self.config['detections_limit']):
    score = detection_scores[0, i]
    if score < threshold:
        continue
    # draw box and add to json_result
```

**React dashboard (`ConfidenceThresholdControl.tsx` + `iotShadowService.ts`):**

A slider control reads the current threshold from the `inference-config` named shadow on load (via `GetThingShadow`) and writes a `desired` state update (via `UpdateThingShadow`) when the operator clicks Apply. The IoT shadow service uses `IoTDataPlaneClient` with the Cognito-authenticated user credentials:

```ts
// Read current threshold
const shadow = await client.send(new GetThingShadowCommand({ thingName, shadowName: 'inference-config' }));

// Write new threshold
await client.send(new UpdateThingShadowCommand({
    thingName, shadowName: 'inference-config',
    payload: JSON.stringify({ state: { desired: { confidence_threshold: threshold } } })
}));
```

The component requires the operator to enter the IoT Thing Name in the dashboard — a `ThingNameInput` component was added alongside the threshold control.

### Value

- Immediate improvement to visual output quality with minimal code change
- Threshold is tuneable live from the dashboard without any redeployment or device access — the delta is applied to the next inference frame
- The `reported` state in the shadow means the dashboard always shows the threshold the device is actually using, not just what was last requested
- Cleaner MQTT payloads reduce downstream noise in the dashboard message feed
- Demonstrates the cloud-to-edge control pattern from recommendation 3, scoped to a single, immediately visible parameter

---

## 2. Motion-Triggered Inference

### Problem

The camera captures and submits an image to the inference pipeline every 30 seconds regardless of whether anything has changed in the scene. This wastes inference compute on the OpenVINO Model Server, generates unnecessary S3 uploads, and produces a flat, uninteresting stream of nearly identical images.

### Solution

Replace the fixed-interval capture loop with a continuous low-FPS capture loop that applies on-device motion detection (frame differencing or background subtraction) before triggering inference. Inference is only invoked when meaningful motion is detected.

### Implementation

- In `camera_handler_core.py`, replace the `time.sleep` loop with a persistent `cv2.VideoCapture` session
- Apply OpenCV background subtraction between frames using `cv2.createBackgroundSubtractorMOG2()`
- Count the number of changed pixels in the foreground mask against a configurable `motion_threshold`
- Only publish the image path to the `camera/images` MQTT topic when the threshold is exceeded
- Add `MotionThreshold` and `FrameInterval` to the recipe configuration

```python
cap = cv2.VideoCapture(self.config['camera_index'])  # persistent session, opened once
fgbg = cv2.createBackgroundSubtractorMOG2()
while True:
    ret, frame = cap.read()
    if not ret:
        continue  # skip failed reads rather than passing None to fgbg.apply()
    fgmask = fgbg.apply(frame)
    motion_area = cv2.countNonZero(fgmask)
    if motion_area > self.config['motion_threshold']:
        image_path = self.save_image(frame)
        self.publish_image_event(image_path)
    time.sleep(self.config['frame_interval'])
```

### Value

- Demonstrates genuine edge intelligence: the device makes a local decision before invoking the AI pipeline
- Reduces inference calls, S3 writes, and IoT Core message volume — quantifiably demonstrable during a demo
- Realistic pattern for security camera and industrial monitoring use cases
- Keeps inference results meaningful — when something is detected, something actually happened

---

## 3. IoT Device Shadow for Runtime Configuration

### Problem

Changing any configuration parameter (capture interval, confidence threshold, model name) currently requires a full Greengrass component redeployment, which takes several minutes and requires cloud connectivity to the Greengrass service. There is no way to adjust device behaviour in real time.

### Solution

Integrate AWS IoT Device Shadow with both Greengrass components so that configuration can be updated from the cloud and applied without redeployment. Each component subscribes to its shadow's `delta` document via Greengrass IPC and reconfigures itself when a change is received.

### Implementation

- Add `aws.greengrass.ShadowManager` as a dependency in both component recipes
- Grant each component IPC access to read and update the local device shadow
- In each component's main loop, subscribe to shadow delta events via the MQTT delta topic using `subscribe_to_topic` (the same pattern used in item 1's implemented `InferenceHandlerCore`):

```python
thing_name = os.environ.get('AWS_IOT_THING_NAME')
delta_topic = f"$aws/things/{thing_name}/shadow/name/camera-config/update/delta"
self.ipc_client.subscribe_to_topic(
    topic=delta_topic,
    on_stream_event=self.on_shadow_delta,
    on_stream_error=self.on_stream_error,
    on_stream_closed=self.on_stream_closed
)
```

- On delta receipt, update the in-memory config dict and apply changes (e.g., adjust the motion threshold, swap the active model name, change the capture interval)
- Report the accepted state back to the shadow to confirm

### Configurable Parameters via Shadow

| Parameter | Component | Effect |
|---|---|---|
| `capture_interval` | CameraHandlerCore | Change frame rate |
| `motion_threshold` | CameraHandlerCore | Sensitivity of motion trigger |
| `confidence_threshold` | InferenceHandlerCore | Filter detection noise |
| `model_name` | InferenceHandlerCore | Switch active OVMS model |
| `detections_limit` | InferenceHandlerCore | Cap number of drawn boxes |

### Value

- Enables live demo adjustment: increase sensitivity, switch models, tune confidence — all from the AWS Console or CLI with immediate effect on the device
- Tells a compelling story about cloud-to-edge control without requiring physical access to the device
- Realistic operational pattern — field technicians can tune devices remotely

---

## 4. Event-Driven Alerting on Specific Detections

### Problem

All inference results are published to a single `camera/inference` MQTT topic as raw JSON and displayed in the dashboard message feed. There is no distinction between a routine background frame and a significant detection event (e.g., a person entering a restricted area). Consumers of the data must filter all messages themselves.

### Solution

Add a configurable alert rules system to `InferenceHandlerCore`. When a detection matches a configured class above a configured threshold, publish an enriched alert message to a dedicated `camera/alerts` IoT Core topic. Wire this downstream to SNS for email/SMS notification.

### Implementation

**Recipe configuration additions:**

```yaml
AlertRules:
  - class: "person"
    threshold: 0.7
  - class: "vehicle"
    threshold: 0.6
AlertTopic: "camera/alerts"
```

**In `inference_handler_core.py`:**

```python
def check_alerts(self, detections):
    for rule in self.config['alert_rules']:
        for detection in detections.values():
            if (detection['detection_classes'] == rule['class'] and
                    detection['detection_scores'] >= rule['threshold']):
                self.publish_alert(detection, rule)

def publish_alert(self, detection, rule):
    alert = {
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "triggered_class": detection['detection_classes'],
        "score": float(detection['detection_scores']),
        "rule": rule,
        "image_s3_key": "camera/latest-inference.jpg"
    }
    self.ipc_client.publish_to_iot_core(
        topic_name=self.config['alert_topic'],
        qos='1',
        payload=json.dumps(alert).encode('utf-8')
    )
```

**Recipe access control — two additions required:**

1. Add `camera/alerts` to the `mqttproxy` permitted resources. Without this, the Greengrass IPC broker will reject the `publish_to_iot_core` call with an authorization error:

```yaml
aws.greengrass.ipc.mqttproxy:
  com.example.InferenceHandlerCore:mqttproxy:2:
    operations:
      - 'aws.greengrass#PublishToIoTCore'
    resources:
      - 'camera/inference'
      - 'camera/alerts'   # ADD this line
```

2. `AlertRules` is a YAML list-of-objects and cannot be passed as an environment variable string. Read the full component configuration via the Greengrass IPC configuration service instead of env vars:

```python
response = self.ipc_client.get_configuration(key_path=[])
self.config['alert_rules'] = response.value.get('AlertRules', [])
self.config['alert_topic'] = response.value.get('AlertTopic', 'camera/alerts')
```

**AWS-side:**
- Create an IoT Core Rule that forwards `camera/alerts` messages to an SNS topic
- SNS delivers email/SMS notifications to subscribed endpoints
- Alert rules are updatable at runtime via Device Shadow (see recommendation 3)

### Value

- Highest demo impact: audience can see a real-world detection trigger a cloud notification in real time
- Directly applicable to security, safety, and industrial inspection use cases
- Demonstrates the full edge-to-cloud event pipeline without any server-side infrastructure (IoT Rules + SNS is fully managed)
- Alert rules configured via Device Shadow make the system tuneable without redeployment

---

## 5. Dashboard Bounding Box Overlay as Interactive Data

### Problem

The React dashboard displays the inference result as a JPEG with bounding boxes baked into the pixels by the `InferenceHandlerCore`. The detection metadata (class names, confidence scores, box coordinates) is published separately as JSON on the `camera/inference` MQTT topic and currently displayed only as raw JSON text in the message feed. The two data streams are not connected in the UI.

### Solution

Separate the visualisation from the edge processing. Upload the **raw** (unannotated) image to S3, and render bounding boxes in the browser using the detection JSON from MQTT. This makes the overlay interactive and decouples the UI presentation from the edge component.

### Implementation

**Edge changes (`inference_handler_core.py`):**
- Upload the original (pre-annotation) image to S3 instead of the annotated version
- Include normalised bounding box coordinates in the MQTT JSON payload:

```python
# detection_boxes[0, i] contains raw model output in 0-1 normalised form [ymin, xmin, ymax, xmax]
# Do NOT use normalized_detection_boxes[0, i] here — despite its name that variable is
# pixel-scaled (multiplied by image height/width) and will break the React scaleBox calculation.
raw_box = detection_boxes[0, i]
json_result[i] = {
    "detection_classes": detected_class_name,
    "detection_scores": float(score),
    "box": {
        "ymin": float(raw_box[0]), "xmin": float(raw_box[1]),
        "ymax": float(raw_box[2]), "xmax": float(raw_box[3])
    },
    "num_detections": int(num_detections[0])
}
```

**Dashboard changes (`ImageGallery.tsx` / new `DetectionOverlay.tsx`):**
- Render the S3 image in an `<img>` element inside a relatively-positioned container
- Overlay an `<svg>` or `<canvas>` element at the same dimensions
- Draw bounding boxes from the latest MQTT message using the normalised coordinates
- On hover over a bounding box, show a tooltip with class name and confidence score
- Colour-code boxes by class (consistent colour per class name using a hash)

```tsx
// Scale normalised coords to rendered image dimensions
const scaleBox = (box, imgWidth, imgHeight) => ({
  x: box.xmin * imgWidth,
  y: box.ymin * imgHeight,
  width: (box.xmax - box.xmin) * imgWidth,
  height: (box.ymax - box.ymin) * imgHeight,
});
```

### Value

- Transforms the dashboard from a passive image viewer into an interactive AI results display
- Demonstrates that the edge and cloud components are genuinely connected — new detections update the overlay in real time via MQTT
- Removes bounding box rendering from the constrained edge device, reducing CPU load
- Opens the door to dashboard-side filtering: users can toggle visibility of specific classes, set their own confidence threshold in the UI, and see the effect instantly without any device changes

---

## 6. Multi-Model Support via OpenVINO Model Server

### Problem

The current solution is locked to a single Faster R-CNN object detection model. Whilst effective for demonstrating detection, a single model type limits the range of AI use cases the demo can represent and does not showcase the full capability of OpenVINO Model Server, which is designed to serve multiple models simultaneously.

### Solution

Configure OVMS to serve multiple models concurrently and introduce a model pipeline concept within `InferenceHandlerCore`. Different models run in sequence or in parallel on the same frame, with each result enriching the final output. The active pipeline is selectable at runtime via Device Shadow (see recommendation 3).

### Models to Add

| Model Type | Example Model | Use Case | OpenVINO Support |
|---|---|---|---|
| Object detection | Faster R-CNN (existing) | Locate and classify objects | Native |
| Image classification | EfficientNet / MobileNet | Scene-level "what is this?" | Native |
| Anomaly detection | PADIM / PatchCore | Industrial defect detection | Intel AI Reference Models |
| Semantic segmentation | DeepLab v3 | Pixel-level scene understanding | Native |

### Implementation

**`OpenVINOModelServerContainerCore` recipe changes:**

Replace the single `--model_name` / `--model_path` Docker flags with a multi-model config file mounted into the container:

```yaml
# models_config.json (added as an artifact)
{
  "model_config_list": [
    { "config": { "name": "faster_rcnn",    "base_path": "/models/faster_rcnn" } },
    { "config": { "name": "efficientnet",   "base_path": "/models/efficientnet" } },
    { "config": { "name": "anomaly_detect", "base_path": "/models/anomaly_detect" } }
  ]
}
```

```bash
# Updated Docker run command in recipe
docker run -u 0 -d \
  -v {artifacts:decompressedPath}/models:/models \
  -v {artifacts:path}/models_config.json:/config/models_config.json \
  -p 9000:9000 \
  openvino/model_server:latest \
  --config_path /config/models_config.json \
  --port 9000
```

> **Ubuntu Core note:** The `{artifacts:decompressedPath}` path resolves to a Greengrass-managed artifact store, which is accessible on Ubuntu Core. This is appropriate for the bundled-artifact approach shown here. When integrating with the S3Downloader component (see recommendation 7), the models directory must be writable — switch the Docker mount to `{work:path}/models` instead, which is a Greengrass-managed writable directory scoped to this component and works on both Ubuntu Core and standard Linux.

**`InferenceHandlerCore` changes:**

Introduce a pipeline concept where multiple model calls are chained per frame:

```python
PIPELINES = {
    "detection_only": ["faster_rcnn"],
    "detection_and_classify": ["faster_rcnn", "efficientnet"],
    "anomaly": ["anomaly_detect"],
    "full": ["faster_rcnn", "efficientnet", "anomaly_detect"],
}

def run_inference(self, message):
    image = self.load_image(message['image_path'])
    pipeline = PIPELINES.get(self.config['active_pipeline'], ["faster_rcnn"])
    combined_result = {}

    for model_name in pipeline:
        result = self.run_model(image, model_name)
        combined_result[model_name] = result

    self.publish_results(combined_result)
    self.upload_to_s3(image)
```

Each model's results are published as a named key in the MQTT payload, so the dashboard can render them distinctly. The `active_pipeline` config key is switchable at runtime via Device Shadow.

**New Greengrass component for model management:**

A lightweight `com.example.ModelManagerCore` component could be added to handle downloading new model versions from S3 and notifying the inference handler to reload — decoupling model lifecycle from component deployment.

### Value

- Dramatically expands the range of AI scenarios the demo can represent from a single edge device
- OVMS multi-model serving is a key differentiator of the Intel OpenVINO stack — this directly showcases it
- Anomaly detection is a particularly compelling addition for industrial and manufacturing audiences: no labelled training data is needed for many use cases
- Pipeline switching via Device Shadow (recommendation 3) means the audience can see the device switch from object detection to anomaly detection mode live, without any redeployment
- Sets up the architecture for the OTA model update pipeline (backlog item)

---

## 7. Model Delivery via Ubuntu Inference Snaps

### Problem

The current solution bundles the AI model as a ZIP artifact inside the `OpenVINOModelServerContainerCore` Greengrass component. This approach has several hard limitations:

- Greengrass component artifacts have a **5 GB size ceiling**, which is already constraining for Faster R-CNN and becomes a blocker as larger or multiple models are added (see recommendation 6)
- Every model update requires a full component redeployment, which re-uploads the entire artifact to S3 and re-pushes it to the device
- There is no visibility into download progress or the ability to pause, resume, or cancel a transfer
- The device has no registry of which models are available locally, making dynamic model switching (recommendation 3) fragile
- The Docker-based OVMS container adds operational overhead on Ubuntu Core: image pulls, storage driver configuration, and privilege escalation via `requiresPrivilege: true`

### Assessment: Ubuntu Inference Snaps

[Ubuntu Inference Snaps](https://documentation.ubuntu.com/inference-snaps/) are Canonical's mechanism for packaging and distributing AI models as first-class snap packages on Ubuntu. Each inference snap maps to a single fine-tuned model and bundles multiple inference engines optimised for different silicon. During installation, the snap automatically detects the underlying hardware (CPU, GPU, NPU) and selects the best-matching engine, runtime, and quantised model weights without manual configuration.

**Architecture overview:**

An inference snap contains:

- **Engine manifests** describing hardware requirements (architecture, memory, GPU/NPU type) for each optimisation variant
- **Engine manager** that matches engines to detected hardware, installs the selected engine, and manages lifecycle
- **Inference engine** (only one active at a time) comprising a runtime (e.g., llama.cpp HTTP server, OpenVINO Model Server) and the model weights
- **CLI** (`modelctl`) for engine selection, configuration, and status reporting

Each engine and model weights set is packaged as a snap **component** — an independently installable part of the snap. Only the components matching the detected hardware are downloaded, reducing transfer size and disk usage.

Once installed, the snap exposes an OpenAI-compatible HTTP API (e.g., `http://localhost:9090/v1`) that any local process can call for inference.

**Current snap catalogue (as of April 2026):**

| Snap | Model Type | Intel CPU | Intel GPU | Intel NPU | NVIDIA GPU | ARM64 |
|---|---|---|---|---|---|---|
| DeepSeek R1 | Reasoning LLM | Yes | Yes | Yes | Yes | Ampere |
| Gemma 3 | Vision-Language LLM | Yes | Yes | - | Yes | Yes |
| Nemotron 3 Nano | General LLM | Yes (generic) | - | - | Yes | Yes |
| Qwen VL | Vision-Language Model | Yes | Yes | Yes | Yes | Ampere |

**Relevance to this solution:**

The existing catalogue targets generative AI (LLMs and VLMs), not the computer vision object detection models (Faster R-CNN, EfficientNet, PADIM) used in this demo. However, the inference snap framework is model-agnostic — Canonical's [tutorial for creating custom inference snaps](https://documentation.ubuntu.com/inference-snaps/tutorial/create-inference-snap) demonstrates packaging arbitrary models with custom runtimes. OpenVINO Model Server is explicitly listed as a supported runtime for Intel GPU/NPU engines.

This means the solution can package its own computer vision models as custom inference snaps, gaining automatic hardware detection, silicon-optimised engine selection, and snap-based lifecycle management — while retaining the OpenVINO runtime already in use.

### Solution

Replace the Docker-based `OpenVINOModelServerContainerCore` Greengrass component with a custom Ubuntu Inference Snap that packages the computer vision models with OpenVINO Model Server as the runtime. Use the S3Downloader component from [aws-samples/sample-model-downloader-greengrass-component](https://github.com/aws-samples/sample-model-downloader-greengrass-component) to deliver model weight updates to the snap's writable storage, decoupling model updates from both snap refreshes and Greengrass redeployments.

This hybrid approach uses inference snaps for the runtime and initial model delivery, and S3Downloader for cloud-triggered model updates via MQTT.

### How It Works

**Custom inference snap: `cv-inference`**

A custom inference snap is built following the [Canonical inference snap framework](https://documentation.ubuntu.com/inference-snaps/tutorial/create-inference-snap). The snap packages:

1. **Engine manifests** for each target hardware configuration:

```yaml
# engines/intel-gpu/engine.yaml
name: intel-gpu
description: OpenVINO Model Server optimised for Intel integrated and discrete GPUs
vendor: Demo Project
grade: stable
devices:
  anyof:
    - type: gpu
      vendor: intel
      architecture: amd64
memory: 4G
disk-space: 2G
components:
  - ovms-intel-gpu
  - model-faster-rcnn
```

```yaml
# engines/generic-cpu/engine.yaml
name: generic-cpu
description: OpenVINO Model Server on CPU (fallback)
vendor: Demo Project
grade: stable
devices:
  anyof:
    - type: cpu
      architecture: amd64
memory: 4G
disk-space: 2G
components:
  - ovms-cpu
  - model-faster-rcnn
```

2. **Snap components** for runtimes and model weights:

| Component | Contents | Purpose |
|---|---|---|
| `ovms-intel-gpu` | OpenVINO Model Server built with GPU plugin | Intel GPU-optimised inference runtime |
| `ovms-cpu` | OpenVINO Model Server CPU-only build | Fallback runtime for any amd64 CPU |
| `model-faster-rcnn` | Faster R-CNN IR model files | Default object detection model |
| `model-efficientnet` | EfficientNet IR model files | Classification model (recommendation 6) |

3. **Server wrapper** that starts OVMS with the selected engine's configuration:

```bash
# engines/intel-gpu/server
#!/bin/bash -eux
port="$(modelctl get http.port)"
exec ovms --config_path "$SNAP_COMPONENTS/ovms-intel-gpu/models_config.json" \
     --port "$port" \
     --file_system_poll_wait_seconds 5
```

4. **Install hook** for automatic hardware detection and engine selection:

```bash
# snap/hooks/install
#!/bin/bash -eu
modelctl set --package http.port="9000"
if snapctl is-connected hardware-observe; then
    modelctl use-engine --auto --assume-yes
fi
```

**On installation**, the snap detects whether the device has an Intel GPU, NPU, or only a CPU, and installs only the matching runtime component and model weights. The inference server starts automatically as a `systemd` service managed by `snapd`, exposing the gRPC endpoint on port 9000 — the same interface the existing `InferenceHandlerCore` already uses.

**S3Downloader for cloud-triggered model updates**

The [aws-samples/sample-model-downloader-greengrass-component](https://github.com/aws-samples/sample-model-downloader-greengrass-component) (`aws.samples.S3Downloader`) runs alongside the snap as a Greengrass component. It exposes a three-topic MQTT interface:

| Topic | Direction | Purpose |
|---|---|---|
| `s3downloader/{thingName}/commands` | Cloud to Device | Trigger download, pause, resume, cancel, list |
| `s3downloader/{thingName}/responses` | Device to Cloud | Command acknowledgement with `downloadId` |
| `s3downloader/{thingName}/status` | Device to Cloud | Real-time progress updates |

Downloads use **s5cmd** for concurrent S3 transfers with configurable parallelism and exponential backoff retry (up to 10 attempts).

When a download completes, the model is registered in a named IoT Device Shadow called `models`:

```json
{
  "state": {
    "reported": {
      "models": {
        "faster_rcnn": {
          "model_id": "faster_rcnn",
          "model_name": "Faster R-CNN",
          "model_version": "2.0",
          "local_path": "/var/snap/cv-inference/common/models/faster_rcnn",
          "last_updated": 1710000000
        }
      }
    }
  }
}
```

### Ubuntu Core Compatibility

Ubuntu Core uses a read-only root filesystem. Inference snaps are fully compatible with Ubuntu Core because `snapd` manages all writable paths.

**Snap writable paths**

| Path | Purpose | Persistence |
|---|---|---|
| `$SNAP_COMMON` (`/var/snap/cv-inference/common/`) | Shared writable storage across snap revisions — used for downloaded model weights | Survives snap refreshes |
| `$SNAP_DATA` (`/var/snap/cv-inference/current/`) | Per-revision writable storage — used for runtime configuration | Reset on snap refresh |

The S3Downloader writes model files to `$SNAP_COMMON/models/`, which persists across snap refreshes and is accessible to the OVMS process running inside the snap. The OVMS `--config_path` references this directory.

**No Docker dependency**

The inference snap replaces the Docker container entirely. OVMS runs as a native process within the snap's confinement, eliminating the need for `requiresPrivilege: true`, Docker image pulls, and Docker storage driver configuration on Ubuntu Core.

**`s5cmd` binary availability**

On Ubuntu Core, `apt install` is not available. The `s5cmd` binary must be bundled as an artifact within the S3Downloader Greengrass component. Verify that the [aws-samples component](https://github.com/aws-samples/sample-model-downloader-greengrass-component) bundles a pre-compiled `s5cmd` binary matching the device architecture (`amd64` or `arm64`). If not, add a compiled binary as a component artifact.

---

### Integration with This Solution

**Step 1 — Build and publish the `cv-inference` snap.** Follow the [Canonical inference snap tutorial](https://documentation.ubuntu.com/inference-snaps/tutorial/create-inference-snap) to create the snap with OpenVINO Model Server as the runtime and Faster R-CNN as the initial model. Define engine manifests for Intel GPU and CPU fallback. Publish to a private snap store channel or install locally via `--dangerous` during development.

**Step 2 — Install the snap on the Ubuntu Core device.** On Ubuntu Core, install the snap and connect the required interfaces:

```bash
sudo snap install cv-inference --channel=edge
sudo snap connect cv-inference:hardware-observe
```

The install hook auto-detects hardware and selects the optimal engine. OVMS starts on port 9000 as a `systemd` service.

**Step 3 — Deploy the S3Downloader Greengrass component** alongside the existing `CameraHandlerCore` and `InferenceHandlerCore` components. Add it to `deploy_greengrass_components.py` and grant the Greengrass Token Exchange Role `s3:GetObject` and `s3:ListBucket` on the model S3 bucket. Configure the download destination to the snap's common writable path:

```json
{
  "command": "download",
  "bucket": "your-model-bucket",
  "key": "models/faster_rcnn/",
  "destination": "/var/snap/cv-inference/common/models/faster_rcnn",
  "model_meta": {
    "model_id": "faster_rcnn",
    "model_name": "Faster R-CNN",
    "model_version": "2.0"
  }
}
```

**Step 4 — Remove the `OpenVINOModelServerContainerCore` Greengrass component.** The inference snap replaces it entirely. Remove the component from `deploy_greengrass_components.py` and delete the recipe and Docker-related artifacts.

**Step 5 — Update `InferenceHandlerCore`** to connect to the snap's OVMS endpoint at `localhost:9000` (unchanged from the current Docker setup). Discover available models from the `models` Device Shadow rather than relying on a hardcoded `MODEL_NAME` environment variable.

> **Recipe change required:** Add the `models` shadow to the InferenceHandlerCore's ShadowManager access control:
>
> ```yaml
> aws.greengrass.ShadowManager:
>   com.example.InferenceHandlerCore:shadow:3:
>     operations:
>       - 'aws.greengrass#GetThingShadow'
>       - 'aws.greengrass#UpdateThingShadow'
>     resources:
>       - '$aws/things/*/shadow/name/inference-config'
>       - '$aws/things/*/shadow/name/models'
> ```

**Step 6 — Model updates without redeployment.** To push a new model version, upload the model files to S3 and publish a download command via MQTT. The S3Downloader handles the transfer, updates the shadow, and OVMS picks up the new model via filesystem polling. No Greengrass deployment or snap refresh required.

### New Deployment Flow

```
Build cv-inference snap with OVMS + initial model weights
       |
       v
Install snap on Ubuntu Core device (auto hardware detection)
       |
       v
OVMS starts as systemd service on port 9000
       |
       v
S3Downloader Greengrass component deployed alongside
       |
       v
Cloud publishes download command to s3downloader/{thingName}/commands
       |
       v
S3Downloader pulls model to /var/snap/cv-inference/common/models/
       |
       v
Model registered in "models" Device Shadow
       |
       v
OVMS picks up new model via filesystem polling
       |
       v
InferenceHandlerCore reads shadow, switches active model
```

### Value

- Eliminates Docker from the edge device — OVMS runs as a native snap-confined process, reducing operational complexity and removing the `requiresPrivilege: true` requirement
- Automatic hardware detection selects the optimal OpenVINO runtime (GPU, NPU, or CPU) at install time without manual configuration
- Snap-based delivery integrates natively with Ubuntu Core's update and confinement model — `snapd` handles rollback, delta updates, and transactional refreshes
- Model updates via S3Downloader remain decoupled from both snap refreshes and Greengrass redeployments — a lightweight S3 upload + MQTT command delivers new model versions with real-time progress tracking
- The `models` Device Shadow gives the cloud a live inventory of which model versions are present on every device in the fleet
- Directly enables the multi-model pipeline in recommendation 6 — each model can be delivered as a snap component or downloaded independently via S3
- Demonstrates the convergence of Canonical's inference snap ecosystem with AWS IoT Greengrass for edge AI — a compelling story for audiences interested in Ubuntu Core + AWS edge deployments
- Positions the solution to adopt future Canonical inference snap catalogue models (vision-language models, anomaly detection) as they become available with Intel-optimised engines

### Reference

- Inference Snaps documentation: [documentation.ubuntu.com/inference-snaps](https://documentation.ubuntu.com/inference-snaps/)
- Inference Snaps source: [github.com/canonical/inference-snaps](https://github.com/canonical/inference-snaps)
- Custom snap tutorial: [Create your first inference snap](https://documentation.ubuntu.com/inference-snaps/tutorial/create-inference-snap)
- S3Downloader component: [aws-samples/sample-model-downloader-greengrass-component](https://github.com/aws-samples/sample-model-downloader-greengrass-component)

---

## Additional Recommendations (Backlog)

The following improvements were identified but are lower priority for the initial demo enhancement:

| Improvement | Description |
|---|---|
| **Greengrass Stream Manager** | Replace direct S3 uploads with Greengrass Stream Manager for reliable buffering, automatic retry, and bandwidth throttling during poor connectivity |
| **Image history archiving** | Write timestamped images to `camera/history/YYYYMMDD_HHMMSS.jpg` alongside `latest-inference.jpg` with S3 Lifecycle Rules for automatic expiry |
| **Inference metrics to CloudWatch** | Time each inference call; publish latency, detections-per-frame, and error rate via Greengrass telemetry to CloudWatch for fleet monitoring |
| **Multi-device fleet dashboard** | Add a device selector to the React dashboard; namespace MQTT topics and S3 prefixes per `thingName` to support monitoring multiple edge devices from one UI |
| **OTA model update pipeline** | CodePipeline + Lambda that watches an S3 model staging bucket, packages a new model as a Greengrass component version, and triggers a fleet deployment automatically |

---

*Document created: 2026-03-19*
