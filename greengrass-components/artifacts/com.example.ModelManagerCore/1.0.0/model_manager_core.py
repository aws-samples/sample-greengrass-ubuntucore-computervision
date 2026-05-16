"""ModelManagerCore - Shadow-driven model lifecycle manager for Greengrass edge devices.

Subscribes to the model-config named shadow delta, compares desired models with
current reported models, and orchestrates installation/removal of OpenVINO models
via snap or S3 download. Handles runtime model switching with OVMS gRPC polling
and automatic rollback on failure.
"""

import sys
import os
import time
import traceback
import logging
import json
import shutil
import subprocess
import re

import boto3
import awsiot.greengrasscoreipc.clientv2 as clientv2

# Add shared modules to path (local dev uses relative path; deployed uses artifacts dir)
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', 'shared'))

from ovms_config import write_model_config, write_multi_model_config, read_model_config, get_active_model_from_config
from snapd_client import SnapdClient, SnapdError

# Configure logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

SHADOW_NAME = "model-config"


class ModelManagerCore:
    """Watches the model-config shadow and orchestrates model installation/removal."""

    # Snap name for the inference engine
    SNAP_NAME = "ovms-engine"

    def __init__(self):
        self.thing_name = os.environ.get("AWS_IOT_THING_NAME", "")
        self.snap_components_path = os.environ.get(
            "SNAP_COMPONENTS", "/snap/ovms-engine/components/current"
        )
        self.snap_common_path = os.environ.get(
            "SNAP_COMMON", "/var/snap/ovms-engine/common"
        )
        self.ovms_config_dir = os.environ.get(
            "OVMS_CONFIG_DIR", "/var/snap/ovms-engine/common/config"
        )

        # Track current reported models state locally
        self.reported_models = {}

        # Initialize snapd client for snap management via REST API
        self.snapd = SnapdClient()

        # Initialize Greengrass IPC client
        self.ipc_client = clientv2.GreengrassCoreIPCClientV2()

        logger.info(
            "ModelManagerCore initialized: thing_name=%s, snap_components=%s, snap_common=%s",
            self.thing_name,
            self.snap_components_path,
            self.snap_common_path,
        )

    def run(self):
        """Main entry point: load current state, subscribe to shadow delta, and block."""
        self._load_current_reported_state()
        self._subscribe_to_shadow_delta()

        logger.info("ModelManagerCore running, waiting for shadow delta events...")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("ModelManagerCore stopped")

    def _load_current_reported_state(self):
        """Read the current shadow to populate local reported_models cache."""
        if not self.thing_name:
            logger.warning("AWS_IOT_THING_NAME not set, cannot read shadow")
            return

        try:
            response = self.ipc_client.get_thing_shadow(
                thing_name=self.thing_name, shadow_name=SHADOW_NAME
            )
            shadow = json.loads(response.payload)
            reported = shadow.get("state", {}).get("reported", {})
            self.reported_models = reported.get("models", {})
            logger.info(
                "Loaded current reported models: %s",
                list(self.reported_models.keys()),
            )
        except Exception as e:
            logger.info(
                "No existing model-config shadow found, starting fresh: %s", e
            )
            self.reported_models = {}

    def _subscribe_to_shadow_delta(self):
        """Subscribe to the model-config named shadow delta via IoT Core MQTT."""
        if not self.thing_name:
            logger.error(
                "AWS_IOT_THING_NAME not set, cannot subscribe to shadow delta"
            )
            return

        delta_topic = (
            f"$aws/things/{self.thing_name}/shadow/name/{SHADOW_NAME}/update/delta"
        )
        self.ipc_client.subscribe_to_iot_core(
            topic_name=delta_topic,
            qos="1",
            on_stream_event=self._on_shadow_delta,
            on_stream_error=self._on_stream_error,
            on_stream_closed=self._on_stream_closed,
        )
        logger.info("Subscribed to shadow delta topic: %s", delta_topic)

    def _on_shadow_delta(self, event):
        """Handle shadow delta events to determine model install/remove actions."""
        try:
            payload = event.message.payload
            delta = json.loads(payload)
            logger.info("Shadow delta received: %s", json.dumps(delta, indent=2))

            # The delta contains the desired state fields that differ from reported
            state = delta.get("state", {})

            # Handle active_model switching (Requirements 5.1, 5.6, 5.7)
            if "active_model" in state:
                self._handle_active_model(state["active_model"])
                return

            desired_models = state.get("models", {})

            if not desired_models and "models" not in state:
                logger.debug("Delta does not contain models field, ignoring")
                return

            self._reconcile_models(desired_models)

        except Exception:
            logger.error("Error processing shadow delta")
            traceback.print_exc()

    def _reconcile_models(self, desired_models):
        """Compare desired models with reported models to determine actions.

        Args:
            desired_models: Dict of model_id -> config from the shadow desired state.
                Each value contains 'source' ("snap" or "s3") and optionally 's3_uri'.
        """
        current_model_ids = set(self.reported_models.keys())
        desired_model_ids = set(desired_models.keys())

        # Models to install: in desired but not in reported, or in desired but failed
        models_to_install = {}
        for model_id in desired_model_ids:
            if model_id not in current_model_ids:
                models_to_install[model_id] = desired_models[model_id]
            elif self.reported_models.get(model_id, {}).get("status") == "failed":
                # Retry failed models when they appear in a new delta
                models_to_install[model_id] = desired_models[model_id]

        # Models to remove: in reported but not in desired
        models_to_remove = current_model_ids - desired_model_ids

        logger.info(
            "Reconciliation result: to_install=%s, to_remove=%s",
            list(models_to_install.keys()),
            list(models_to_remove),
        )

        # Process removals
        for model_id in models_to_remove:
            self._handle_model_removal(model_id)

        # Process installations
        for model_id, model_config in models_to_install.items():
            self._handle_model_install(model_id, model_config)

    def _handle_model_install(self, model_id, model_config):
        """Initiate model installation based on source type.

        Args:
            model_id: Unique identifier for the model.
            model_config: Dict with 'source' ("snap" or "s3") and optionally 's3_uri'.
        """
        source = model_config.get("source")
        if source not in ("snap", "s3"):
            logger.error(
                "Invalid source '%s' for model '%s', must be 'snap' or 's3'",
                source,
                model_id,
            )
            self._report_model_status(
                model_id, "failed", reason=f"Invalid source: {source}"
            )
            return

        # Report installing status
        self._report_model_status(model_id, "installing")

        if source == "snap":
            self._install_snap_model(model_id)
        elif source == "s3":
            s3_uri = model_config.get("s3_uri")
            if not s3_uri:
                logger.error("S3 model '%s' missing required 's3_uri' field", model_id)
                self._report_model_status(
                    model_id, "failed", reason="Missing s3_uri field"
                )
                return
            self._install_s3_model(model_id, s3_uri)

    def _install_snap_model(self, model_id):
        """Install a model via snap component and read its manifest.

        Uses the snapd REST API (via /run/snapd.socket) to install the snap
        component of the ovms-engine snap, then reads the manifest.json from
        the installed component path to extract model metadata for OVMS configuration.

        Args:
            model_id: The model identifier (e.g. 'faster-rcnn').
        """
        component_name = f"model-{model_id}"
        logger.info("Installing snap component: %s+%s", self.SNAP_NAME, component_name)

        try:
            self.snapd.install_component(self.SNAP_NAME, component_name, timeout=300)
            logger.info("Snap component '%s+%s' installed successfully", self.SNAP_NAME, component_name)

        except SnapdError as e:
            logger.error("Snap install failed for '%s+%s': %s", self.SNAP_NAME, component_name, e)
            self._report_model_status(
                model_id, "failed", reason=f"snap install failed: {e}"
            )
            return

        # Read manifest.json from the installed component path
        manifest_path = os.path.join(
            self.snap_components_path, f"model-{model_id}", "manifest.json"
        )
        try:
            with open(manifest_path, "r") as f:
                manifest = json.load(f)
        except FileNotFoundError:
            logger.error("Manifest not found at %s", manifest_path)
            self._report_model_status(
                model_id, "failed", reason=f"manifest.json not found at {manifest_path}"
            )
            return
        except json.JSONDecodeError as e:
            logger.error("Invalid JSON in manifest at %s: %s", manifest_path, e)
            self._report_model_status(
                model_id, "failed", reason=f"Invalid manifest.json: {e}"
            )
            return

        # Build model metadata from manifest
        local_path = os.path.join(self.snap_components_path, f"model-{model_id}")
        model_metadata = {
            "model_name": manifest.get("model_name"),
            "version": manifest.get("version"),
            "input_name": manifest.get("input_name"),
            "output_names": manifest.get("output_names"),
            "input_shape": manifest.get("input_shape"),
            "labels_file": manifest.get("labels_file"),
            "local_path": local_path,
        }

        logger.info(
            "Model '%s' ready with metadata: %s",
            model_id,
            json.dumps(model_metadata, indent=2),
        )
        self._report_model_status(model_id, "ready", model_metadata=model_metadata)

    def _install_s3_model(self, model_id, s3_uri):
        """Download a model from S3 and read its manifest.

        Parses the S3 URI to extract bucket and prefix, downloads all objects
        under that prefix to $SNAP_COMMON/models/{model_id}/, then reads
        manifest.json to extract model metadata.

        Args:
            model_id: The model identifier (e.g. 'custom-ppe-detector').
            s3_uri: S3 URI in the format 's3://bucket-name/prefix/path/'.
        """
        logger.info("Downloading S3 model '%s' from '%s'", model_id, s3_uri)

        # Parse the S3 URI into bucket and prefix
        bucket, prefix = self._parse_s3_uri(s3_uri)
        if bucket is None:
            self._report_model_status(
                model_id, "failed", reason=f"Invalid s3_uri format: {s3_uri}"
            )
            return

        # Create local model directory
        local_model_dir = os.path.join(
            self.snap_common_path, "models", model_id
        )
        os.makedirs(local_model_dir, exist_ok=True)

        # Download all objects from the S3 prefix
        try:
            s3_client = boto3.client("s3")
            paginator = s3_client.get_paginator("list_objects_v2")
            page_iterator = paginator.paginate(Bucket=bucket, Prefix=prefix)

            downloaded_count = 0
            for page in page_iterator:
                contents = page.get("Contents", [])
                for obj in contents:
                    key = obj["Key"]
                    # Skip directory markers
                    if key.endswith("/"):
                        continue

                    # Determine relative path from the prefix
                    relative_path = key[len(prefix):]
                    if not relative_path:
                        continue

                    local_file_path = os.path.join(local_model_dir, relative_path)
                    # Create subdirectories if needed
                    os.makedirs(os.path.dirname(local_file_path), exist_ok=True)

                    logger.info("Downloading s3://%s/%s -> %s", bucket, key, local_file_path)
                    s3_client.download_file(bucket, key, local_file_path)
                    downloaded_count += 1

            if downloaded_count == 0:
                logger.error("No objects found at s3://%s/%s", bucket, prefix)
                self._report_model_status(
                    model_id, "failed",
                    reason=f"No objects found at {s3_uri}"
                )
                return

            logger.info(
                "Downloaded %d files for model '%s'", downloaded_count, model_id
            )

        except Exception as e:
            logger.error("S3 download failed for model '%s': %s", model_id, e)
            self._report_model_status(
                model_id, "failed", reason=f"S3 download failed: {e}"
            )
            return

        # Read manifest.json from the downloaded directory
        manifest_path = os.path.join(local_model_dir, "manifest.json")
        try:
            with open(manifest_path, "r") as f:
                manifest = json.load(f)
        except FileNotFoundError:
            logger.error("Manifest not found at %s", manifest_path)
            self._report_model_status(
                model_id, "failed",
                reason=f"manifest.json not found in downloaded model at {manifest_path}"
            )
            return
        except json.JSONDecodeError as e:
            logger.error("Invalid JSON in manifest at %s: %s", manifest_path, e)
            self._report_model_status(
                model_id, "failed", reason=f"Invalid manifest.json: {e}"
            )
            return

        # Build model metadata from manifest
        model_metadata = {
            "model_name": manifest.get("model_name"),
            "version": manifest.get("version"),
            "input_name": manifest.get("input_name"),
            "output_names": manifest.get("output_names"),
            "input_shape": manifest.get("input_shape"),
            "labels_file": manifest.get("labels_file"),
            "local_path": local_model_dir,
        }

        logger.info(
            "S3 model '%s' ready with metadata: %s",
            model_id,
            json.dumps(model_metadata, indent=2),
        )
        self._report_model_status(model_id, "ready", model_metadata=model_metadata)

    @staticmethod
    def _parse_s3_uri(s3_uri):
        """Parse an S3 URI into bucket name and prefix.

        Args:
            s3_uri: URI in the format 's3://bucket-name/prefix/path/'

        Returns:
            Tuple of (bucket, prefix) or (None, None) if the URI is invalid.
            The prefix always ends with '/' to ensure proper prefix listing.
        """
        match = re.match(r"^s3://([^/]+)/(.+)$", s3_uri)
        if not match:
            return None, None

        bucket = match.group(1)
        prefix = match.group(2)

        # Ensure prefix ends with '/' for proper directory listing
        if not prefix.endswith("/"):
            prefix += "/"

        return bucket, prefix

    def _handle_active_model(self, model_id):
        """Handle active_model desired state (Requirements 5.1, 5.6, 5.7).

        Validates the requested model exists in the inventory with status 'ready'.
        Rejects with 'model_not_available' if not found or not ready.
        Treats as no-op if desired equals current reported active_model (idempotent).
        On valid request, initiates model switch via _execute_model_switch.

        Args:
            model_id: The model ID to switch to.
        """
        if not model_id or not isinstance(model_id, str) or not model_id.strip():
            logger.warning("active_model request rejected - empty or invalid model_id")
            self._clear_desired_field('active_model')
            return

        model_id = model_id.strip()

        # Read current shadow to check inventory and current active model
        try:
            response = self.ipc_client.get_thing_shadow(
                thing_name=self.thing_name, shadow_name=SHADOW_NAME
            )
            shadow = json.loads(response.payload)
        except Exception as e:
            logger.error("Cannot process active_model - shadow unavailable: %s", e)
            self._clear_desired_field('active_model')
            return

        state = shadow.get("state", {})
        reported = state.get("reported", {})
        current_active_model = reported.get("active_model", "")
        models = reported.get("models", {})

        # Idempotent case: desired equals current reported (Requirement 5.7)
        if model_id == current_active_model:
            logger.info(
                "active_model '%s' equals current reported - no-op, clearing desired",
                model_id,
            )
            self._clear_desired_field('active_model')
            return

        # Validate model exists in inventory with status 'ready' (Requirement 5.6)
        model_entry = models.get(model_id)

        if model_entry is None:
            error_message = (
                f"Model '{model_id}' not found in the local model inventory"
            )
            logger.warning("active_model rejected - model_not_available: %s", error_message)
            self._publish_error_event('active_model', model_id, 'model_not_available', error_message)
            self._clear_desired_field('active_model')
            return

        model_status = model_entry.get("status", "") if isinstance(model_entry, dict) else ""

        if model_status != "ready":
            error_message = (
                f"Model '{model_id}' is not ready (current status: '{model_status}')"
            )
            logger.warning("active_model rejected - model_not_available: %s", error_message)
            self._publish_error_event('active_model', model_id, 'model_not_available', error_message)
            self._clear_desired_field('active_model')
            return

        # Model is valid and different from current - initiate model switch
        logger.info(
            "Initiating model switch from '%s' to '%s'",
            current_active_model, model_id,
        )
        self._execute_model_switch(model_id, model_entry, reported)

    def _execute_model_switch(self, model_id, model_entry, reported):
        """Execute the model switch by updating OVMS config and polling for load.

        Implements the full model switch flow (Requirements 5.2, 5.3, 5.4):
        1. Save current OVMS config as backup (for rollback)
        2. Write new models_config.json with the target model path
        3. Poll OVMS gRPC ModelStatus API every 2 seconds for up to 60 seconds
        4. On success: read manifest.json for metadata, update reported state with
           new active_model and model_metadata, clear desired field
        5. On timeout/failure: revert OVMS config to previous model, set model status
           to 'failed' with failure_reason, publish error event with model_load_failed

        Args:
            model_id: The target model ID to switch to.
            model_entry: The model's inventory entry (dict).
            reported: The current reported state dictionary.
        """
        # Extract model path from the entry
        model_path = model_entry.get("local_path", "") if isinstance(model_entry, dict) else ""

        if not model_path:
            logger.error(
                "Cannot switch to model '%s' - no local_path in inventory entry",
                model_id,
            )
            self._publish_error_event(
                'active_model', model_id, 'model_not_available',
                f"Model '{model_id}' has no local_path in inventory",
            )
            self._clear_desired_field('active_model')
            return

        # Strip trailing slash for OVMS config base_path
        base_path = model_path.rstrip('/')

        # Step 1: Save current OVMS config as backup for rollback
        backup_config = read_model_config(self.ovms_config_dir)
        logger.info("Saved backup OVMS config for rollback")

        # Step 2: Write new OVMS configuration (Requirement 5.2)
        try:
            write_model_config(
                model_name=model_id,
                base_path=base_path,
                config_dir=self.ovms_config_dir,
            )
            logger.info(
                "OVMS config updated for model switch to '%s' at '%s'",
                model_id, base_path,
            )
        except Exception as e:
            logger.error("Failed to write OVMS config for model switch: %s", e)
            self._publish_error_event(
                'active_model', model_id, 'model_load_failed',
                f"Failed to update OVMS configuration: {e}",
            )
            self._clear_desired_field('active_model')
            return

        # Step 3: Poll OVMS gRPC ModelStatus API (Requirement 5.3)
        model_loaded = self._poll_ovms_model_status(
            model_name=model_id,
            timeout_seconds=60,
            poll_interval=2,
        )

        if model_loaded:
            # Step 4: Success - update reported state
            logger.info("OVMS confirmed model '%s' loaded successfully", model_id)

            # Read model metadata from the target model's manifest
            model_metadata = self._read_model_metadata(base_path)

            # Update reported state with new active_model and model_metadata
            reported["active_model"] = model_id
            if model_metadata:
                reported["model_metadata"] = model_metadata

            self._update_shadow_reported_state(reported)

            # Clear desired state to acknowledge processing (Requirement 1.6)
            self._clear_desired_field('active_model')

            logger.info(
                "Model switch to '%s' completed successfully", model_id
            )
        else:
            # Step 5: Timeout/failure - revert and report error (Requirement 5.4)
            logger.error(
                "OVMS failed to load model '%s' within timeout - reverting config",
                model_id,
            )

            # Revert OVMS config to previous model
            self._revert_ovms_config(backup_config)

            # Set model status to 'failed' with failure_reason
            failure_reason = (
                f"OVMS failed to load model '{model_id}' within 60 seconds"
            )
            models = reported.get("models", {})
            if model_id in models and isinstance(models[model_id], dict):
                models[model_id]["status"] = "failed"
                models[model_id]["failure_reason"] = failure_reason
                reported["models"] = models
                self._update_shadow_reported_state(reported)

            # Publish error event
            self._publish_error_event(
                'active_model', model_id, 'model_load_failed', failure_reason
            )

            # Clear desired state to acknowledge processing
            self._clear_desired_field('active_model')

            logger.info(
                "Model switch to '%s' failed - reverted to previous config",
                model_id,
            )

    def _poll_ovms_model_status(self, model_name, timeout_seconds=60, poll_interval=2):
        """Poll OVMS gRPC ModelStatus API to verify model has loaded.

        Connects to the OVMS gRPC endpoint and checks if the specified model
        is loaded and available for serving. Polls every `poll_interval` seconds
        for up to `timeout_seconds`.

        This method is designed to be easily mockable in tests since the actual
        gRPC libraries may not be available in the test environment.

        Args:
            model_name: The model name to check status for.
            timeout_seconds: Maximum time to wait for model load (default 60s).
            poll_interval: Time between polls in seconds (default 2s).

        Returns:
            True if the model is loaded and available, False if timeout or error.
        """
        start_time = time.time()
        elapsed = 0.0

        logger.info(
            "Polling OVMS model status for '%s' (timeout=%ds, interval=%ds)",
            model_name, timeout_seconds, poll_interval,
        )

        while elapsed < timeout_seconds:
            try:
                is_ready = self._check_ovms_model_ready(model_name)
                if is_ready:
                    logger.info(
                        "OVMS model '%s' is ready after %.1f seconds",
                        model_name, elapsed,
                    )
                    return True
            except Exception as e:
                logger.debug(
                    "OVMS model status check failed for '%s': %s (elapsed=%.1fs)",
                    model_name, e, elapsed,
                )

            time.sleep(poll_interval)
            elapsed = time.time() - start_time

        logger.warning(
            "OVMS model '%s' did not become ready within %d seconds",
            model_name, timeout_seconds,
        )
        return False

    def _check_ovms_model_ready(self, model_name):
        """Check if a model is loaded and ready in OVMS via gRPC.

        Attempts to connect to the OVMS gRPC endpoint (localhost:9000) and
        query the model status. Returns True if the model is in AVAILABLE state.

        This method encapsulates the gRPC call so it can be mocked in tests.

        Args:
            model_name: The model name to check.

        Returns:
            True if the model is loaded and available for inference.

        Raises:
            Exception: If the gRPC connection or status check fails.
        """
        try:
            import grpc
            from tensorflow_serving.apis import model_service_pb2_grpc
            from tensorflow_serving.apis import get_model_status_pb2
            from tensorflow_serving.apis.model_pb2 import ModelSpec

            grpc_url = os.environ.get("OVMS_GRPC_URL", "localhost:9000")
            channel = grpc.insecure_channel(grpc_url)
            stub = model_service_pb2_grpc.ModelServiceStub(channel)

            request = get_model_status_pb2.GetModelStatusRequest()
            request.model_spec.CopyFrom(ModelSpec(name=model_name))

            response = stub.GetModelStatus(request, timeout=5)

            # Check if any version is in AVAILABLE state (state == 2)
            for version_status in response.model_version_status:
                if version_status.state == 2:  # AVAILABLE
                    channel.close()
                    return True

            channel.close()
            return False

        except ImportError:
            # gRPC libraries not available - fall back to socket check
            logger.debug(
                "gRPC libraries not available, falling back to socket check"
            )
            return self._check_ovms_socket_available()
        except Exception as e:
            raise RuntimeError(
                f"Failed to check OVMS model status for '{model_name}': {e}"
            ) from e

    def _check_ovms_socket_available(self):
        """Fallback check: verify OVMS gRPC port is accepting connections.

        Used when gRPC libraries are not available.

        Returns:
            True if the OVMS gRPC port is accepting connections.
        """
        import socket

        grpc_url = os.environ.get("OVMS_GRPC_URL", "localhost:9000")
        try:
            host, port_str = grpc_url.split(':')
            port = int(port_str)
        except (ValueError, AttributeError):
            return False

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex((host, port))
            sock.close()
            return result == 0
        except (socket.error, OSError):
            return False

    def _revert_ovms_config(self, backup_config):
        """Revert OVMS configuration to the backup state.

        Restores the previous OVMS configuration after a failed model switch.
        If no backup exists, writes an empty config.

        Args:
            backup_config: The previously saved OVMS config dict, or None.
        """
        if backup_config is None:
            logger.warning("No backup config available - writing empty config")
            config_path = os.path.join(self.ovms_config_dir, "models_config.json")
            try:
                os.makedirs(self.ovms_config_dir, exist_ok=True)
                with open(config_path, 'w') as f:
                    json.dump({"model_config_list": []}, f, indent=2)
                    f.write("\n")
            except OSError as e:
                logger.error("Failed to write empty OVMS config: %s", e)
            return

        active_model_info = get_active_model_from_config(backup_config)
        if active_model_info:
            try:
                write_model_config(
                    model_name=active_model_info['name'],
                    base_path=active_model_info['base_path'],
                    config_dir=self.ovms_config_dir,
                )
                logger.info(
                    "Reverted OVMS config to previous model '%s' at '%s'",
                    active_model_info['name'], active_model_info['base_path'],
                )
            except Exception as e:
                logger.error("Failed to revert OVMS config: %s", e)
        else:
            logger.warning("Backup config has no valid model - writing empty config")
            config_path = os.path.join(self.ovms_config_dir, "models_config.json")
            try:
                os.makedirs(self.ovms_config_dir, exist_ok=True)
                with open(config_path, 'w') as f:
                    json.dump({"model_config_list": []}, f, indent=2)
                    f.write("\n")
            except OSError as e:
                logger.error("Failed to write empty OVMS config: %s", e)

    def _read_model_metadata(self, model_path):
        """Read model metadata from manifest.json at the given path.

        Args:
            model_path: Directory containing the model and its manifest.json.

        Returns:
            Dict with model metadata fields, or None if manifest is missing/invalid.
        """
        manifest_path = os.path.join(model_path, 'manifest.json')
        try:
            with open(manifest_path, 'r') as f:
                manifest = json.load(f)
            return {
                "input_name": manifest.get("input_name"),
                "output_names": manifest.get("output_names"),
                "input_shape": manifest.get("input_shape"),
                "labels_file": manifest.get("labels_file"),
            }
        except (FileNotFoundError, json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to read model metadata from %s: %s", manifest_path, e)
            return None

    def _clear_desired_field(self, field_name):
        """Clear a processed desired state field by setting it to null."""
        if not self.thing_name:
            return
        try:
            payload = json.dumps({
                "state": {
                    "desired": {
                        field_name: None
                    }
                }
            }).encode('utf-8')
            self.ipc_client.update_thing_shadow(
                thing_name=self.thing_name,
                shadow_name=SHADOW_NAME,
                payload=payload,
            )
            logger.info("Cleared desired state field: %s", field_name)
        except Exception as e:
            logger.error("Failed to clear desired field '%s': %s", field_name, e)

    def _update_shadow_reported_state(self, reported_state):
        """Update the model-config shadow reported state."""
        if not self.thing_name:
            return
        try:
            payload = json.dumps({
                "state": {
                    "reported": reported_state
                }
            }).encode('utf-8')
            self.ipc_client.update_thing_shadow(
                thing_name=self.thing_name,
                shadow_name=SHADOW_NAME,
                payload=payload,
            )
            logger.info("Shadow reported state updated")
        except Exception as e:
            logger.error("Failed to update shadow reported state: %s", e)

    def _publish_error_event(self, operation, model_id, error_code, error_message):
        """Publish a structured error event to model-manager/{thingName}/errors.

        Args:
            operation: The operation that failed (e.g. 'active_model').
            model_id: The model ID involved.
            error_code: Structured error code (e.g. 'model_load_failed').
            error_message: Human-readable error description.
        """
        from datetime import datetime, timezone

        error_event = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "operation": operation,
            "model_id": model_id,
            "error_code": error_code,
            "error_message": error_message,
        }

        topic = f"model-manager/{self.thing_name}/errors"
        try:
            payload = json.dumps(error_event).encode('utf-8')
            self.ipc_client.publish_to_iot_core(
                topic_name=topic,
                qos='1',
                payload=payload,
            )
            logger.info("Published error event to %s: %s", topic, error_code)
        except Exception as e:
            logger.error("Failed to publish error event: %s", e)

    def _handle_model_removal(self, model_id):
        """Remove a model from OVMS config, delete local files, and update reported state.

        Implements Requirements 8.1, 8.2, 8.3:
        - Removes the model from OVMS configuration and deletes local files (8.1)
        - Updates reported state to reflect the model has been removed (8.2)
        - Refuses to remove if it's the last remaining model (8.3)

        Args:
            model_id: The model identifier to remove.
        """
        # Requirement 8.3: Refuse to remove the last remaining model
        ready_models = {
            mid: entry for mid, entry in self.reported_models.items()
            if isinstance(entry, dict) and entry.get("status") == "ready"
        }
        if len(ready_models) <= 1 and model_id in ready_models:
            logger.warning(
                "Cannot remove model '%s' - it is the last remaining active model. "
                "At least one model must remain active.",
                model_id,
            )
            return

        # Get the model's local_path before removing from reported state
        model_entry = self.reported_models.get(model_id, {})
        local_path = None
        if isinstance(model_entry, dict):
            metadata = model_entry.get("model_metadata", {})
            if isinstance(metadata, dict):
                local_path = metadata.get("local_path")

        # Remove the model entry from reported_models (Requirement 8.2)
        if model_id in self.reported_models:
            del self.reported_models[model_id]
            logger.info("Removed model '%s' from reported state", model_id)

        # Delete local model files (Requirement 8.1)
        if local_path and os.path.isdir(local_path):
            try:
                shutil.rmtree(local_path)
                logger.info(
                    "Deleted local model files for '%s' at '%s'", model_id, local_path
                )
            except OSError as e:
                logger.error(
                    "Failed to delete local files for model '%s' at '%s': %s",
                    model_id, local_path, e,
                )
        elif local_path:
            logger.warning(
                "Local path '%s' for model '%s' does not exist or is not a directory",
                local_path, model_id,
            )
        else:
            logger.warning(
                "No local_path found for model '%s', skipping file deletion", model_id
            )

        # Regenerate OVMS config with remaining ready models (Requirement 8.1)
        self._regenerate_ovms_config()

        # Update shadow reported state (Requirement 8.2)
        self._update_shadow_reported()

        logger.info("Model '%s' removal complete", model_id)

    def _regenerate_ovms_config(self):
        """Regenerate the OVMS multi-model config with all ready models.

        Iterates over self.reported_models, filters for models with status 'ready',
        and writes a models_config.json listing each ready model's name and base_path.
        OVMS auto-reloads via --file_system_poll_wait_seconds when the file changes.

        Requirements: 4.1, 4.2, 4.3
        """
        ready_models = []
        for model_id, model_entry in self.reported_models.items():
            if not isinstance(model_entry, dict):
                continue
            if model_entry.get("status") != "ready":
                continue
            metadata = model_entry.get("model_metadata", {})
            if not isinstance(metadata, dict):
                continue
            model_name = metadata.get("model_name")
            local_path = metadata.get("local_path")
            if model_name and local_path:
                ready_models.append({
                    "name": model_name,
                    "base_path": local_path,
                })

        logger.info(
            "Regenerating OVMS config with %d ready model(s): %s",
            len(ready_models),
            [m["name"] for m in ready_models],
        )

        try:
            config_path = write_multi_model_config(
                models=ready_models,
                config_dir=self.ovms_config_dir,
            )
            logger.info("OVMS config written to %s", config_path)
        except Exception as e:
            logger.error("Failed to regenerate OVMS config: %s", e)

    def _report_model_status(self, model_id, status, reason=None, model_metadata=None):
        """Update the shadow reported state for a specific model.

        Args:
            model_id: The model identifier.
            status: One of 'installing', 'ready', or 'failed'.
            reason: Human-readable error string (required when status is 'failed').
            model_metadata: Dict of model metadata (when status is 'ready').
        """
        model_entry = {"status": status}
        if reason:
            model_entry["reason"] = reason
        if model_metadata:
            model_entry["model_metadata"] = model_metadata

        self.reported_models[model_id] = model_entry
        self._update_shadow_reported()

        # Regenerate OVMS config whenever a model reaches ready status
        if status == "ready":
            self._regenerate_ovms_config()

    def _update_shadow_reported(self):
        """Push the full reported state to the shadow."""
        if not self.thing_name:
            logger.warning("Cannot update shadow: AWS_IOT_THING_NAME not set")
            return

        try:
            reported_state = {"models": self.reported_models}
            payload = json.dumps({"state": {"reported": reported_state}}).encode(
                "utf-8"
            )
            self.ipc_client.update_thing_shadow(
                thing_name=self.thing_name,
                shadow_name=SHADOW_NAME,
                payload=payload,
            )
            logger.info(
                "Shadow reported state updated: %s",
                json.dumps(reported_state, indent=2),
            )
        except Exception as e:
            logger.error("Failed to update shadow reported state: %s", e)
            traceback.print_exc()

    def _on_stream_error(self, error):
        """Handle stream errors from IPC subscriptions."""
        logger.error("Stream error: %s", error)
        traceback.print_exc()
        return False

    def _on_stream_closed(self):
        """Handle stream closure."""
        logger.info("Shadow delta subscription stream closed")


def main():
    """Main entry point for ModelManagerCore."""
    try:
        manager = ModelManagerCore()
        manager.run()
    except Exception as e:
        logger.error("Fatal error in ModelManagerCore: %s", e)
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
