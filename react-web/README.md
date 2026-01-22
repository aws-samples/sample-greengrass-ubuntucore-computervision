# React Cognito Dashboard Application

A React web application that provides secure authentication through Amazon Cognito and displays a real-time dashboard with S3 images and IoT Core MQTT messages.

## Features

- **Secure Authentication**: Amazon Cognito integration with automatic password reset support
- **Image Gallery**: Real-time display of the latest inference image with automatic refresh
- **Live Messaging**: AWS IoT Core MQTT real-time message feed
- **Responsive Design**: Works on desktop and mobile devices
- **Auto-Discovery**: Automatically discovers AWS service endpoints

## Quick Start

### 1. Environment Setup

**Automatic Setup (Recommended):**

The `.env` file is automatically created and populated when you run the AWS resources setup script from the project root:

```bash
# From project root directory
python3 deploy_greengrass_components.py --stage setup --s3-bucket your-bucket-name --region us-east-1
```

This will create all required AWS resources and generate the `.env` file with the correct configuration.

**Manual Setup (Alternative):**

If you prefer to configure manually, copy the example file:

```bash
cp .env.example .env
```

Then edit `.env` with your AWS Cognito configuration.

### 2. Install Dependencies

```bash
npm install
```

### 3. Start Development Server

```bash
npm start
```

Open [http://localhost:3000](http://localhost:3000) to view the application.

## Configuration

### Required Environment Variables

- `REACT_APP_AWS_REGION`: AWS region (e.g., eu-west-1)
- `REACT_APP_COGNITO_USER_POOL_ID`: Cognito User Pool ID
- `REACT_APP_COGNITO_CLIENT_ID`: Cognito App Client ID
- `REACT_APP_COGNITO_IDENTITY_POOL_ID`: Cognito Identity Pool ID

### Optional Environment Variables

- `REACT_APP_S3_BUCKET_NAME`: S3 bucket name for the latest inference image
- `REACT_APP_MQTT_TOPIC`: MQTT topic name (default: camera/inference)
- `REACT_APP_IOT_POLICY_NAME`: IoT policy name for MQTT access

### Image Display Behavior

The dashboard displays the latest inference image from S3:
- **Location**: `camera/latest-inference.jpg` in the configured S3 bucket
- **Auto-refresh**: Polls S3 metadata every 5 seconds to detect new images
- **Efficient**: Only downloads the image when it changes (ETag-based detection)
- **No history**: Only the most recent inference result is displayed

This approach minimizes S3 storage costs and provides a simple, efficient real-time view.

## AWS Setup Requirements

### Cognito Configuration

**Automatic Setup (Recommended):**

All Cognito resources and IAM roles are automatically created by the setup script. No manual configuration required.

**Manual Setup (Alternative):**

1. Create a Cognito User Pool
2. Create a Cognito Identity Pool
3. Configure the Identity Pool to allow authenticated users
4. Set up appropriate IAM roles for authenticated users

### Required IAM Permissions

The authenticated user role (automatically created by the setup script) includes the following permissions:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "iot:DescribeEndpoint",
        "iot:Connect",
        "iot:Subscribe",
        "iot:Receive"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:HeadObject"
      ],
      "Resource": [
        "arn:aws:s3:::your-bucket-name/camera/latest-inference.jpg"
      ]
    }
  ]
}
```

## Available Scripts

In the project directory, you can run:

### `npm start`

Runs the app in the development mode.\
Open [http://localhost:3000](http://localhost:3000) to view it in the browser.

The page will reload if you make edits.\
You will also see any lint errors in the console.

### `npm test`

Launches the test runner in the interactive watch mode.\
See the section about [running tests](https://facebook.github.io/create-react-app/docs/running-tests) for more information.

### `npm run build`

Builds the app for production to the `build` folder.\
It correctly bundles React in production mode and optimizes the build for the best performance.

The build is minified and the filenames include the hashes.\
Your app is ready to be deployed!

See the section about [deployment](https://facebook.github.io/create-react-app/docs/deployment) for more information.

### `npm run eject`

**Note: this is a one-way operation. Once you `eject`, you can’t go back!**

If you aren’t satisfied with the build tool and configuration choices, you can `eject` at any time. This command will remove the single build dependency from your project.

Instead, it will copy all the configuration files and the transitive dependencies (webpack, Babel, ESLint, etc) right into your project so you have full control over them. All of the commands except `eject` will still work, but they will point to the copied scripts so you can tweak them. At this point you’re on your own.

You don’t have to ever use `eject`. The curated feature set is suitable for small and middle deployments, and you shouldn’t feel obligated to use this feature. However we understand that this tool wouldn’t be useful if you couldn’t customize it when you are ready for it.

## Learn More

You can learn more in the [Create React App documentation](https://facebook.github.io/create-react-app/docs/getting-started).

To learn React, check out the [React documentation](https://reactjs.org/).
