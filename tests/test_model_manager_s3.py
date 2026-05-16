"""Unit tests for ModelManagerCore S3 model download functionality.

Tests the S3 URI parsing, file download, manifest reading, and status
reporting for models with source: "s3".

Requirements: 3.1, 3.2, 3.3, 3.4
"""

import sys
import os
import json
from unittest.mock import MagicMock, patch, call

import pytest

# Add artifact path for imports
sys.path.insert(0, os.path.join(
    os.path.dirname(__file__), '..', 'greengrass-components', 'artifacts',
    'com.example.ModelManagerCore', '1.0.0'
))

# Mock the awsiot module before importing model_manager_core
mock_clientv2 = MagicMock()
sys.modules['awsiot'] = MagicMock()
sys.modules['awsiot.greengrasscoreipc'] = MagicMock()
sys.modules['awsiot.greengrasscoreipc.clientv2'] = mock_clientv2


@pytest.fixture
def mock_ipc_client():
    """Create a mock IPC client."""
    mock = MagicMock()
    mock.get_thing_shadow.side_effect = Exception("ResourceNotFoundException")
    return mock


@pytest.fixture
def manager(mock_ipc_client, tmp_path):
    """Create a ModelManagerCore instance with mocked IPC and temp directories."""
    mock_clientv2.GreengrassCoreIPCClientV2.return_value = mock_ipc_client

    with patch.dict(os.environ, {
        'AWS_IOT_THING_NAME': 'test-thing',
        'SNAP_COMPONENTS': '/snap/ovms-engine/current/components',
        'SNAP_COMMON': str(tmp_path),
        'OVMS_CONFIG_DIR': str(tmp_path / 'config'),
    }):
        from model_manager_core import ModelManagerCore
        mgr = ModelManagerCore()
        mgr.ipc_client = mock_ipc_client
        yield mgr


class TestParseS3Uri:
    """Tests for S3 URI parsing."""

    def test_parses_standard_uri_with_trailing_slash(self, manager):
        """Parses s3://bucket/prefix/path/ correctly."""
        bucket, prefix = manager._parse_s3_uri("s3://my-bucket/models/ppe/1.0/")
        assert bucket == "my-bucket"
        assert prefix == "models/ppe/1.0/"

    def test_parses_uri_without_trailing_slash(self, manager):
        """Adds trailing slash to prefix when missing."""
        bucket, prefix = manager._parse_s3_uri("s3://my-bucket/models/ppe/1.0")
        assert bucket == "my-bucket"
        assert prefix == "models/ppe/1.0/"

    def test_parses_uri_with_single_level_prefix(self, manager):
        """Parses URI with a single-level prefix."""
        bucket, prefix = manager._parse_s3_uri("s3://bucket-name/models/")
        assert bucket == "bucket-name"
        assert prefix == "models/"

    def test_returns_none_for_invalid_uri_no_prefix(self, manager):
        """Returns None for URI without a prefix path."""
        bucket, prefix = manager._parse_s3_uri("s3://bucket-only")
        assert bucket is None
        assert prefix is None

    def test_returns_none_for_non_s3_uri(self, manager):
        """Returns None for non-S3 URIs."""
        bucket, prefix = manager._parse_s3_uri("https://bucket/path/")
        assert bucket is None
        assert prefix is None

    def test_returns_none_for_empty_string(self, manager):
        """Returns None for empty string."""
        bucket, prefix = manager._parse_s3_uri("")
        assert bucket is None
        assert prefix is None


class TestS3ModelDownload:
    """Tests for the full S3 model download flow."""

    def test_successful_download_reports_ready(self, manager, mock_ipc_client, tmp_path):
        """Successful S3 download reads manifest and reports ready status."""
        mock_s3_client = MagicMock()
        mock_paginator = MagicMock()
        mock_s3_client.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [
            {
                "Contents": [
                    {"Key": "models/ppe/1.0/model.bin"},
                    {"Key": "models/ppe/1.0/model.xml"},
                    {"Key": "models/ppe/1.0/manifest.json"},
                    {"Key": "models/ppe/1.0/labels.txt"},
                ]
            }
        ]

        manifest = {
            "model_id": "custom-ppe",
            "model_name": "ppe_detector",
            "version": "1.0.0",
            "input_name": "input_tensor",
            "output_names": ["detection_boxes", "detection_scores"],
            "input_shape": [1, 300, 300, 3],
            "labels_file": "labels.txt"
        }

        def fake_download(bucket, key, local_path):
            if key.endswith("manifest.json"):
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                with open(local_path, 'w') as f:
                    json.dump(manifest, f)
            else:
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                with open(local_path, 'w') as f:
                    f.write("fake content")

        mock_s3_client.download_file.side_effect = fake_download

        with patch('model_manager_core.boto3') as patched_boto3:
            patched_boto3.client.return_value = mock_s3_client
            manager._install_s3_model("custom-ppe", "s3://my-bucket/models/ppe/1.0/")

        update_calls = mock_ipc_client.update_thing_shadow.call_args_list
        assert len(update_calls) > 0
        payload = json.loads(update_calls[-1].kwargs['payload'])
        model_state = payload['state']['reported']['models']['custom-ppe']
        assert model_state['status'] == 'ready'
        assert model_state['model_metadata']['model_name'] == 'ppe_detector'
        assert model_state['model_metadata']['input_name'] == 'input_tensor'
        assert model_state['model_metadata']['output_names'] == ["detection_boxes", "detection_scores"]
        assert model_state['model_metadata']['input_shape'] == [1, 300, 300, 3]
        assert model_state['model_metadata']['labels_file'] == 'labels.txt'
        assert model_state['model_metadata']['local_path'] == str(tmp_path / "models" / "custom-ppe")

    def test_downloads_all_files_from_prefix(self, manager, mock_ipc_client, tmp_path):
        """All files under the S3 prefix are downloaded to the local directory."""
        mock_s3_client = MagicMock()
        mock_paginator = MagicMock()
        mock_s3_client.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [
            {
                "Contents": [
                    {"Key": "models/ppe/1.0/model.bin"},
                    {"Key": "models/ppe/1.0/model.xml"},
                    {"Key": "models/ppe/1.0/manifest.json"},
                ]
            }
        ]

        def fake_download(bucket, key, local_path):
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            if key.endswith("manifest.json"):
                with open(local_path, 'w') as f:
                    json.dump({"model_name": "test", "version": "1.0"}, f)
            else:
                with open(local_path, 'w') as f:
                    f.write("data")

        mock_s3_client.download_file.side_effect = fake_download

        with patch('model_manager_core.boto3') as patched_boto3:
            patched_boto3.client.return_value = mock_s3_client
            manager._install_s3_model("test-model", "s3://bucket/models/ppe/1.0/")

        assert mock_s3_client.download_file.call_count == 3
        download_calls = mock_s3_client.download_file.call_args_list
        downloaded_keys = [c[0][1] for c in download_calls]
        assert "models/ppe/1.0/model.bin" in downloaded_keys
        assert "models/ppe/1.0/model.xml" in downloaded_keys
        assert "models/ppe/1.0/manifest.json" in downloaded_keys

    def test_skips_directory_markers(self, manager, mock_ipc_client, tmp_path):
        """S3 objects ending with '/' (directory markers) are skipped."""
        mock_s3_client = MagicMock()
        mock_paginator = MagicMock()
        mock_s3_client.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [
            {
                "Contents": [
                    {"Key": "models/ppe/1.0/"},  # directory marker
                    {"Key": "models/ppe/1.0/manifest.json"},
                ]
            }
        ]

        def fake_download(bucket, key, local_path):
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            with open(local_path, 'w') as f:
                json.dump({"model_name": "test", "version": "1.0"}, f)

        mock_s3_client.download_file.side_effect = fake_download

        with patch('model_manager_core.boto3') as patched_boto3:
            patched_boto3.client.return_value = mock_s3_client
            manager._install_s3_model("test-model", "s3://bucket/models/ppe/1.0/")

        assert mock_s3_client.download_file.call_count == 1

    def test_invalid_s3_uri_reports_failed(self, manager, mock_ipc_client):
        """Invalid S3 URI reports failed status with reason."""
        manager._install_s3_model("bad-model", "not-an-s3-uri")

        update_calls = mock_ipc_client.update_thing_shadow.call_args_list
        assert len(update_calls) > 0
        payload = json.loads(update_calls[-1].kwargs['payload'])
        model_state = payload['state']['reported']['models']['bad-model']
        assert model_state['status'] == 'failed'
        assert 'Invalid s3_uri format' in model_state['reason']

    def test_empty_s3_prefix_reports_failed(self, manager, mock_ipc_client, tmp_path):
        """No objects found at S3 prefix reports failed status."""
        mock_s3_client = MagicMock()
        mock_paginator = MagicMock()
        mock_s3_client.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [
            {"Contents": []}
        ]

        with patch('model_manager_core.boto3') as patched_boto3:
            patched_boto3.client.return_value = mock_s3_client
            manager._install_s3_model("empty-model", "s3://bucket/empty/prefix/")

        update_calls = mock_ipc_client.update_thing_shadow.call_args_list
        assert len(update_calls) > 0
        payload = json.loads(update_calls[-1].kwargs['payload'])
        model_state = payload['state']['reported']['models']['empty-model']
        assert model_state['status'] == 'failed'
        assert 'No objects found' in model_state['reason']

    def test_s3_download_error_reports_failed(self, manager, mock_ipc_client, tmp_path):
        """S3 client error during download reports failed status."""
        mock_s3_client = MagicMock()
        mock_paginator = MagicMock()
        mock_s3_client.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [
            {
                "Contents": [
                    {"Key": "models/ppe/1.0/model.bin"},
                ]
            }
        ]
        mock_s3_client.download_file.side_effect = Exception("Access Denied")

        with patch('model_manager_core.boto3') as patched_boto3:
            patched_boto3.client.return_value = mock_s3_client
            manager._install_s3_model("denied-model", "s3://bucket/models/ppe/1.0/")

        update_calls = mock_ipc_client.update_thing_shadow.call_args_list
        assert len(update_calls) > 0
        payload = json.loads(update_calls[-1].kwargs['payload'])
        model_state = payload['state']['reported']['models']['denied-model']
        assert model_state['status'] == 'failed'
        assert 'S3 download failed' in model_state['reason']

    def test_missing_manifest_reports_failed(self, manager, mock_ipc_client, tmp_path):
        """Missing manifest.json after download reports failed status."""
        mock_s3_client = MagicMock()
        mock_paginator = MagicMock()
        mock_s3_client.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [
            {
                "Contents": [
                    {"Key": "models/ppe/1.0/model.bin"},
                ]
            }
        ]

        def fake_download(bucket, key, local_path):
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            with open(local_path, 'w') as f:
                f.write("binary data")

        mock_s3_client.download_file.side_effect = fake_download

        with patch('model_manager_core.boto3') as patched_boto3:
            patched_boto3.client.return_value = mock_s3_client
            manager._install_s3_model("no-manifest", "s3://bucket/models/ppe/1.0/")

        update_calls = mock_ipc_client.update_thing_shadow.call_args_list
        assert len(update_calls) > 0
        payload = json.loads(update_calls[-1].kwargs['payload'])
        model_state = payload['state']['reported']['models']['no-manifest']
        assert model_state['status'] == 'failed'
        assert 'manifest.json not found' in model_state['reason']

    def test_invalid_manifest_json_reports_failed(self, manager, mock_ipc_client, tmp_path):
        """Invalid JSON in manifest.json reports failed status."""
        mock_s3_client = MagicMock()
        mock_paginator = MagicMock()
        mock_s3_client.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [
            {
                "Contents": [
                    {"Key": "models/ppe/1.0/manifest.json"},
                ]
            }
        ]

        def fake_download(bucket, key, local_path):
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            with open(local_path, 'w') as f:
                f.write("not valid json {{{")

        mock_s3_client.download_file.side_effect = fake_download

        with patch('model_manager_core.boto3') as patched_boto3:
            patched_boto3.client.return_value = mock_s3_client
            manager._install_s3_model("bad-json", "s3://bucket/models/ppe/1.0/")

        update_calls = mock_ipc_client.update_thing_shadow.call_args_list
        assert len(update_calls) > 0
        payload = json.loads(update_calls[-1].kwargs['payload'])
        model_state = payload['state']['reported']['models']['bad-json']
        assert model_state['status'] == 'failed'
        assert 'Invalid manifest.json' in model_state['reason']

    def test_paginated_s3_results(self, manager, mock_ipc_client, tmp_path):
        """Handles paginated S3 list results across multiple pages."""
        mock_s3_client = MagicMock()
        mock_paginator = MagicMock()
        mock_s3_client.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [
            {
                "Contents": [
                    {"Key": "models/ppe/1.0/model.bin"},
                ]
            },
            {
                "Contents": [
                    {"Key": "models/ppe/1.0/manifest.json"},
                ]
            }
        ]

        def fake_download(bucket, key, local_path):
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            if key.endswith("manifest.json"):
                with open(local_path, 'w') as f:
                    json.dump({"model_name": "ppe", "version": "1.0"}, f)
            else:
                with open(local_path, 'w') as f:
                    f.write("data")

        mock_s3_client.download_file.side_effect = fake_download

        with patch('model_manager_core.boto3') as patched_boto3:
            patched_boto3.client.return_value = mock_s3_client
            manager._install_s3_model("paginated-model", "s3://bucket/models/ppe/1.0/")

        assert mock_s3_client.download_file.call_count == 2

        update_calls = mock_ipc_client.update_thing_shadow.call_args_list
        payload = json.loads(update_calls[-1].kwargs['payload'])
        model_state = payload['state']['reported']['models']['paginated-model']
        assert model_state['status'] == 'ready'

    def test_model_directory_created_at_correct_path(self, manager, mock_ipc_client, tmp_path):
        """Model files are downloaded to $SNAP_COMMON/models/{model_id}/."""
        mock_s3_client = MagicMock()
        mock_paginator = MagicMock()
        mock_s3_client.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [
            {
                "Contents": [
                    {"Key": "models/ppe/1.0/manifest.json"},
                ]
            }
        ]

        def fake_download(bucket, key, local_path):
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            with open(local_path, 'w') as f:
                json.dump({"model_name": "ppe", "version": "1.0"}, f)

        mock_s3_client.download_file.side_effect = fake_download

        with patch('model_manager_core.boto3') as patched_boto3:
            patched_boto3.client.return_value = mock_s3_client
            manager._install_s3_model("my-model", "s3://bucket/models/ppe/1.0/")

        expected_dir = tmp_path / "models" / "my-model"
        assert expected_dir.exists()
        assert (expected_dir / "manifest.json").exists()
