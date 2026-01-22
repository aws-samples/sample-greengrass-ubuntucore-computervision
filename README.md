# Ubuntu Core Greengrass Demo

This demo shows how to deploy AWS IoT Greengrass components for computer vision on Ubuntu Core devices.

## Overview

The demo includes three Greengrass components:
- **CameraHandlerCore**: Captures images from USB webcam
- **InferenceHandlerCore**: Processes images for object detection using AI models
- **OpenVINOModelServerContainerCore**: Runs OpenVINO Model Server in Docker

The demo also includes a React web application that displays the computer vision inference results in real-time, showing detected objects and the latest captured image through a user-friendly dashboard. The dashboard automatically refreshes when new images are uploaded.

## Prerequisites

### 1. AWS IAM User for Greengrass Installation

Create an IAM user with access key and secret access key for Greengrass installation. The minimum required permissions are:

- `iot:CreateThing`, `iot:CreateThingType`, `iot:CreateThingGroup`
`iot:CreatePolicy`, `iot:AttachPolicy`, `iot:AttachThingPrincipal`,
`iot:CreateKeysAndCertificate`, `iot:DescribeEndpoint`, `iot:GetPolicy`,
`iot:DescribeRoleAlias`, `iot:AttachPrincipalPolicy`,
`greengrass:AssociateServiceRoleToAccount`,
`iam:CreateRole`, `iam:AttachRolePolicy`, `iam:PassRole`,
`logs:CreateLogGroup`, `logs:DescribeLogGroups`

**Note**: For simplicity you can use an IAM user with `AWSGreengrassFullAccess` and `AWSIoTFullAccess` policies.

**Important**: Create and download the access keys for this IAM user as you will be prompted to enter them during Greengrass installation.

### 2. AWS IAM User for Deployment and Resource Setup

Create a separate IAM user (or use the same one) with access key and secret access key for deploying components and setting up AWS resources. The minimum required permissions are:

**S3 Permissions:**
- `s3:CreateBucket`, `s3:PutObject`, `s3:GetObject`,
`s3:ListBucket`, `s3:PutBucketCORS`

**Greengrass Permissions:**
- `greengrass:CreateComponentVersion`, `greengrass:DeleteComponent`,
`greengrass:CreateDeployment`, `greengrass:CancelDeployment`, `greengrass:ListDeployments`,
`greengrass:GetComponent`, `greengrass:ListComponents`,
`greengrass:GetDeployment`, `greengrass:GetCoreDevice`, `greengrass:ListCoreDevices`,
`greengrass:ResolveComponentCandidates`

**IoT Permissions:**
- `iot:CreateRoleAlias`, `iot:DescribeRoleAlias`,
`iot:CreatePolicy`, `iot:GetPolicy`,
`iot:DescribeEndpoint`, `iot:DescribeThing`,
`iot:DescribeThing`, `iot:GetThingShadow`, `iot:UpdateThingShadow`,
`iot:ListThingPrincipals`, `iot:GetPolicyVersion`

**Cognito Permissions:**
- `cognito-idp:CreateUserPool`, `cognito-idp:ListUserPools`,
`cognito-idp:CreateUserPoolClient`,
`cognito-idp:AdminCreateUser`, `cognito-idp:AdminSetUserPassword`,
`cognito-identity:CreateIdentityPool`, `cognito-identity:ListIdentityPools`,
`cognito-identity:SetIdentityPoolRoles`

**IAM Permissions:**
- `iam:CreateRole`, `iam:GetRole`,
`iam:PutRolePolicy`, `iam:AttachRolePolicy`,
`iam:PassRole`

**STS Permissions:**
- `sts:GetCallerIdentity`

**Recommended**: It is recommended to use an IAM user with `PowerUserAccess` policy for deployment and setup.

### 3. Device Requirements

- Ubuntu Core device with snap support
- USB webcam connected
- Internet connectivity
- Python 3.10+

### 4. AWS CLI Configuration

- AWS CLI configured with your deployment IAM user credentials

## Step-by-Step Setup

### Step 1: Install Greengrass on Device

Install and configure AWS IoT Greengrass Core on your Ubuntu Core device:

```bash
sudo snap install aws-iot-greengrass
sudo aws-iot-greengrass.configure

sudo snap connect aws-iot-greengrass:docker docker:docker-daemon
sudo snap connect aws-iot-greengrass:docker-executables docker:docker-executables
sudo snap connect aws-iot-greengrass:camera
```

During configuration, you will be prompted to enter your IAM user's access key and secret access key.

### Step 2: Prepare Development Environment

1. **Download the Computer Vision model from Kaggle using the following script:**:
   ```bash
   ./download_model.sh
   ```

2. **Setup Python environment**:
   ```bash
   python3 -m venv greengrass-deploy
   source greengrass-deploy/bin/activate  # On Windows: greengrass-deploy\Scripts\activate
   pip install -r requirements-deploy.txt
   ```

### Step 3: Setup AWS Resources

Before deploying components, create the required AWS resources:

```bash
python3 setup_aws_resources.py --s3-bucket your-bucket-name --region us-east-1
```

You will be prompted to enter a password for the demo user (`demo@example.com`). The password must meet these requirements:
- At least 8 characters long
- Contains at least one uppercase letter
- Contains at least one lowercase letter
- Contains at least one number
- Contains at least one special character

Alternatively, provide the password via command line:
```bash
python3 setup_aws_resources.py --s3-bucket your-bucket-name --region us-east-1 --demo-password "YourSecure123!"
```

This creates:
- Greengrass Token Exchange Role and Role Alias (required for Greengrass components to access AWS services)
- S3 bucket (for component artifacts and the latest processed image)
- Cognito resources (for React dashboard authentication)
- Demo user with your specified password
- IoT policies and IAM roles

**Note**: The InferenceHandlerCore component uploads each processed image to the same S3 location (`camera/latest-inference.jpg`), overwriting the previous image. This keeps storage minimal and simplifies the dashboard.

### Step 4: Deploy Components

You can deploy using either interactive mode (recommended) or command line mode.

#### Option A: Interactive Mode (Recommended)

Simply run the script and follow the prompts:

```bash
python3 deploy_greengrass_components.py
```

#### Option B: Command Line Mode

**Full deployment (creates components and deploys to device):**
```bash
python3 deploy_greengrass_components.py --stage full --thing-name "YourDevice" --s3-bucket "your-bucket" --region us-east-1
```

**Two-stage deployment (for multiple devices):**
```bash
# Stage 1: Create components (run once) - creates S3 bucket if needed
python3 deploy_greengrass_components.py --stage create --s3-bucket "your-bucket" --region us-east-1

# Stage 2: Deploy to devices (run for each device)
python3 deploy_greengrass_components.py --stage deploy --thing-name "Device1" --region us-east-1
python3 deploy_greengrass_components.py --stage deploy --thing-name "Device2" --region us-east-1
```



## Deployment Stages Explained

The deployment script supports three stages:

- **create**: Uploads component artifacts to S3 and creates Greengrass components in AWS
- **deploy**: Creates a deployment targeting your IoT Thing/Greengrass Core Device
- **full**: Runs both create and deploy stages in sequence



## Folder Structure

The project expects this structure:

```
greengrass-components/
├── recipes/
│   ├── com.example.CameraHandlerCore-1.0.0.yaml
│   ├── com.example.InferenceHandlerCore-1.0.0.yaml
│   └── com.example.OpenVINOModelServerContainerCore-1.0.0.yaml
└── artifacts/
    ├── com.example.CameraHandlerCore/
    │   └── 1.0.0/
    │       ├── camera_handler_core.py
    │       └── requirements.txt
    ├── com.example.InferenceHandlerCore/
    │   └── 1.0.0/
    │       ├── inference_handler_core.py
    │       └── label_map.txt
    └── com.example.OpenVINOModelServerContainerCore/
        └── 1.0.0/
```

## Re-running Deployments and Force Updates

### When to Use Force Redeployment

Use the `--force` flag when:
- Component configuration needs to be updated (e.g., S3 bucket name changed)
- Component code has been modified
- Previous deployment had incorrect settings
- You need to reset component configuration to recipe defaults

### Force Redeployment Commands

```bash
# Recreate components with corrected configuration
python3 deploy_greengrass_components.py --stage create --s3-bucket correct-bucket --region us-east-1 --force

# Or full redeployment (recommended)
python3 deploy_greengrass_components.py --stage full --thing-name "YourDevice" --s3-bucket correct-bucket --region us-east-1 --force
```

### What the `--force` Flag Does

1. **Deletes existing component versions** from AWS Greengrass
2. **Re-uploads artifacts to S3** with updated configuration
3. **Creates new component versions** with corrected settings
4. **Resets deployment configuration** to use recipe defaults (prevents old config overrides from persisting)
5. **Deploys to the device** with fresh configuration

### Configuration Reset Behavior

The deployment script automatically resets component configuration to use recipe defaults. This prevents old deployment configuration overrides from carrying over. If you previously deployed with incorrect settings (e.g., wrong S3 bucket), the new deployment will use the updated recipe defaults instead of merging with old values.

### Without `--force` Flag

Without `--force`, the script:
- Reuses existing components (faster for minor changes)
- Only creates a new deployment
- Still resets configuration to recipe defaults

## Troubleshooting

### Common Issues and Solutions

- **S3 Access Denied**: Ensure your AWS credentials have S3 permissions for the specified bucket. Check that the Greengrass Token Exchange Role has S3 access.

- **Component Already Exists**: Use `--force` flag to recreate components, or the script will reuse existing ones.

- **Wrong S3 Bucket Name in Logs**: The component is using an old configuration. Run with `--force` to recreate components with the correct bucket name:
  ```bash
  python3 deploy_greengrass_components.py --stage full --thing-name "YourDevice" --s3-bucket correct-bucket --region us-east-1 --force
  ```

- **Configuration Not Updating**: Old deployment configuration may be overriding recipe defaults. The deployment script now automatically resets configuration, but if you have an existing deployment with overrides, use `--force` to create a fresh deployment.

- **Thing Not Found**: Ensure the IoT Thing exists and is registered as a Greengrass Core Device.

- **Region Mismatch**: Ensure all resources (S3 bucket, IoT Thing) are in the same region.

- **Deployment Failed**: Check device logs at `/greengrass/v2/logs/` and re-run with `--force` if configuration needs updating.

- **Greengrass Installation Issues**: Verify IAM user has correct permissions and access keys are valid.

- **CORS Errors in Dashboard**: Run the setup script to configure CORS on your S3 bucket:
  ```bash
  python3 setup_aws_resources.py --s3-bucket your-bucket-name --region us-east-1
  ```

## React Dashboard

The React dashboard is located in the `react-web/` directory. After running the setup stage, the `.env` file will be automatically created with the correct AWS configuration. See `react-web/README.md` for details on running the dashboard locally.

### How the Dashboard Works

- The dashboard displays the latest inference image from S3 (`camera/latest-inference.jpg`)
- Automatically polls S3 metadata every 5 seconds to detect new images
- Only downloads the image when it changes (efficient ETag-based detection)
- No image history is stored - only the most recent inference result is shown

### Dashboard CORS Configuration

The S3 bucket must have CORS configured to allow the web dashboard to access images. The setup script automatically configures CORS when creating the bucket. However, if you experience CORS errors:

1. Run the setup script to configure CORS:
   ```bash
   python3 setup_aws_resources.py --s3-bucket your-bucket-name --region us-east-1
   ```

2. Or manually configure CORS in the AWS S3 console with these settings:
   - Allowed origins: `*` (or your specific domain)
   - Allowed methods: `GET`, `HEAD`
   - Allowed headers: `*`
   - Expose headers: `ETag`