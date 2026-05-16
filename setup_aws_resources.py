#!/usr/bin/env python3
"""
AWS Resources Setup Script for Ubuntu Core Greengrass Demo

Creates required AWS resources for the entire project:
- Greengrass Token Exchange Role and Role Alias (for Greengrass components)
- S3 bucket (for component artifacts and processed images)
- Cognito User Pool and Identity Pool (for React dashboard authentication)
- IAM roles for authenticated and unauthenticated users (for React dashboard)
- IoT policy (for React dashboard MQTT access)
"""
import sys
import boto3
import json
import argparse
import re
import getpass
from botocore.exceptions import ClientError

class AWSResourcesSetup:
    def __init__(self, aws_region='us-east-1', project_name='ubuntu-core-gg-demo'):
        self.aws_region = aws_region
        self.project_name = project_name
        
        # Initialize AWS clients
        self.cognito_idp = boto3.client('cognito-idp', region_name=aws_region)
        self.cognito_identity = boto3.client('cognito-identity', region_name=aws_region)
        self.iam = boto3.client('iam', region_name=aws_region)
        self.iot = boto3.client('iot', region_name=aws_region)
        self.sts = boto3.client('sts', region_name=aws_region)
        self.s3 = boto3.client('s3', region_name=aws_region)
        
        self.account_id = self.sts.get_caller_identity()['Account']

    def find_existing_user_pool(self):
        """Find existing User Pool by name."""
        pool_name = f'{self.project_name}-user-pool'
        try:
            paginator = self.cognito_idp.get_paginator('list_user_pools')
            for page in paginator.paginate(MaxResults=60):
                for pool in page['UserPools']:
                    if pool['Name'] == pool_name:
                        return pool['Id']
            return None
        except ClientError:
            return None

    def create_user_pool(self):
        """Create Cognito User Pool or return existing one."""
        # Check for existing pool first
        existing_pool_id = self.find_existing_user_pool()
        if existing_pool_id:
            print(f"Using existing User Pool: {existing_pool_id}")
            return existing_pool_id
            
        try:
            response = self.cognito_idp.create_user_pool(
                PoolName=f'{self.project_name}-user-pool',
                Policies={
                    'PasswordPolicy': {
                        'MinimumLength': 8,
                        'RequireUppercase': True,
                        'RequireLowercase': True,
                        'RequireNumbers': True,
                        'RequireSymbols': True
                    }
                },
                AutoVerifiedAttributes=['email'],
                UsernameAttributes=['email'],
                Schema=[
                    {
                        'Name': 'email',
                        'AttributeDataType': 'String',
                        'Required': True,
                        'Mutable': True
                    }
                ]
            )
            user_pool_id = response['UserPool']['Id']
            print(f"Created User Pool: {user_pool_id}")
            return user_pool_id
        except ClientError as e:
            print(f"Error creating User Pool: {e}")
            raise

    def create_user_pool_client(self, user_pool_id):
        """Create User Pool Client."""
        try:
            response = self.cognito_idp.create_user_pool_client(
                UserPoolId=user_pool_id,
                ClientName=f'{self.project_name}-client',
                GenerateSecret=False,
                ExplicitAuthFlows=['ADMIN_NO_SRP_AUTH', 'USER_PASSWORD_AUTH']
            )
            client_id = response['UserPoolClient']['ClientId']
            print(f"Created User Pool Client: {client_id}")
            return client_id
        except ClientError as e:
            print(f"Error creating User Pool Client: {e}")
            raise

    def find_existing_identity_pool(self):
        """Find existing Identity Pool by name."""
        pool_name = f'{self.project_name}-identity-pool'
        try:
            response = self.cognito_identity.list_identity_pools(MaxResults=60)
            for pool in response['IdentityPools']:
                if pool['IdentityPoolName'] == pool_name:
                    return pool['IdentityPoolId']
            return None
        except ClientError:
            return None

    def create_identity_pool(self, user_pool_id, client_id):
        """Create Cognito Identity Pool or return existing one."""
        # Check for existing pool first
        existing_pool_id = self.find_existing_identity_pool()
        if existing_pool_id:
            print(f"Using existing Identity Pool: {existing_pool_id}")
            # Update existing pool to ensure correct provider configuration
            try:
                self.cognito_identity.update_identity_pool(
                    IdentityPoolId=existing_pool_id,
                    IdentityPoolName=f'{self.project_name}-identity-pool',
                    AllowUnauthenticatedIdentities=True,
                    CognitoIdentityProviders=[
                        {
                            'ProviderName': f'cognito-idp.{self.aws_region}.amazonaws.com/{user_pool_id}',
                            'ClientId': client_id,
                            'ServerSideTokenCheck': False
                        }
                    ]
                )
                print(f"Updated Identity Pool provider configuration")
            except ClientError as e:
                print(f"Warning: Failed to update Identity Pool: {e}")
            return existing_pool_id
            
        try:
            response = self.cognito_identity.create_identity_pool(
                IdentityPoolName=f'{self.project_name}-identity-pool',
                AllowUnauthenticatedIdentities=True,
                CognitoIdentityProviders=[
                    {
                        'ProviderName': f'cognito-idp.{self.aws_region}.amazonaws.com/{user_pool_id}',
                        'ClientId': client_id,
                        'ServerSideTokenCheck': False
                    }
                ]
            )
            identity_pool_id = response['IdentityPoolId']
            print(f"Created Identity Pool: {identity_pool_id}")
            return identity_pool_id
        except ClientError as e:
            print(f"Error creating Identity Pool: {e}")
            raise

    def create_greengrass_token_exchange_role(self, s3_bucket=None):
        """Create IAM role for Greengrass Token Exchange."""
        role_name = 'GreengrassV2TokenExchangeRole'
        trust_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {
                        "Service": "credentials.iot.amazonaws.com"
                    },
                    "Action": "sts:AssumeRole"
                }
            ]
        }
        
        try:
            self.iam.create_role(
                RoleName=role_name,
                AssumeRolePolicyDocument=json.dumps(trust_policy)
            )
            
            self.iam.attach_role_policy(
                RoleName=role_name,
                PolicyArn='arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess'
            )
            
            if s3_bucket:
                put_policy = {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Action": "s3:PutObject",
                            "Resource": f"arn:aws:s3:::{s3_bucket}/*"
                        }
                    ]
                }
                self.iam.put_role_policy(
                    RoleName=role_name,
                    PolicyName='S3PutObjectPolicy',
                    PolicyDocument=json.dumps(put_policy)
                )
            
            role_arn = f"arn:aws:iam::{self.account_id}:role/{role_name}"
            print(f"Created Greengrass Token Exchange Role: {role_arn}")
            return role_arn
        except ClientError as e:
            if e.response['Error']['Code'] in ['EntityAlreadyExists', 'EntityAlreadyExistsException']:
                role_arn = f"arn:aws:iam::{self.account_id}:role/{role_name}"
                print(f"Greengrass Token Exchange Role already exists: {role_arn}")
                
                # Update policies for existing role
                try:
                    self.iam.attach_role_policy(
                        RoleName=role_name,
                        PolicyArn='arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess'
                    )
                except ClientError:
                    pass  # Policy already attached
                
                if s3_bucket:
                    put_policy = {
                        "Version": "2012-10-17",
                        "Statement": [
                            {
                                "Effect": "Allow",
                                "Action": "s3:PutObject",
                                "Resource": f"arn:aws:s3:::{s3_bucket}/*"
                            }
                        ]
                    }
                    self.iam.put_role_policy(
                        RoleName=role_name,
                        PolicyName='S3PutObjectPolicy',
                        PolicyDocument=json.dumps(put_policy)
                    )
                
                return role_arn
            else:
                raise

    def create_greengrass_role_alias(self, role_arn):
        """Create IoT Role Alias for Greengrass."""
        alias_name = 'GreengrassV2TokenExchangeRoleAlias'
        
        try:
            response = self.iot.create_role_alias(
                roleAlias=alias_name,
                roleArn=role_arn
            )
            alias_arn = response['roleAliasArn']
            print(f"Created Greengrass Role Alias: {alias_arn}")
            return alias_arn
        except ClientError as e:
            if e.response['Error']['Code'] == 'ResourceAlreadyExistsException':
                alias_arn = f"arn:aws:iot:{self.aws_region}:{self.account_id}:rolealias/{alias_name}"
                print(f"Greengrass Role Alias already exists: {alias_arn}")
                return alias_arn
            else:
                raise

    def create_iot_policy(self):
        """Create IoT policy for dashboard access."""
        policy_name = f'{self.project_name}-dashboard-policy'
        policy_document = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": [
                        "iot:Connect",
                        "iot:Subscribe",
                        "iot:Receive"
                    ],
                    "Resource": [
                        f"arn:aws:iot:{self.aws_region}:{self.account_id}:client/*",
                        f"arn:aws:iot:{self.aws_region}:{self.account_id}:topicfilter/camera/*",
                        f"arn:aws:iot:{self.aws_region}:{self.account_id}:topic/camera/*"
                    ]
                }
            ]
        }
        
        try:
            self.iot.create_policy(
                policyName=policy_name,
                policyDocument=json.dumps(policy_document)
            )
            print(f"Created IoT Policy: {policy_name}")
            return policy_name
        except ClientError as e:
            if e.response['Error']['Code'] == 'ResourceAlreadyExistsException':
                print(f"IoT Policy already exists: {policy_name}")
                return policy_name
            print(f"Error creating IoT Policy: {e}")
            raise

    def create_iam_roles(self, identity_pool_id, iot_policy_name):
        """Create IAM roles for authenticated and unauthenticated users."""
        # Authenticated role
        auth_role_name = f'{self.project_name}-auth-role'
        auth_trust_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {
                        "Federated": "cognito-identity.amazonaws.com"
                    },
                    "Action": "sts:AssumeRoleWithWebIdentity",
                    "Condition": {
                        "StringEquals": {
                            "cognito-identity.amazonaws.com:aud": identity_pool_id
                        },
                        "ForAnyValue:StringLike": {
                            "cognito-identity.amazonaws.com:amr": "authenticated"
                        }
                    }
                }
            ]
        }
        
        auth_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": [
                        "s3:GetObject",
                        "s3:ListBucket"
                    ],
                    "Resource": "*"
                },
                {
                    "Effect": "Allow",
                    "Action": [
                        "iot:Connect",
                        "iot:Subscribe",
                        "iot:Receive",
                        "iot:AttachPolicy",
                        "iot:DescribeEndpoint"
                    ],
                    "Resource": "*"
                }
            ]
        }
        
        try:
            self.iam.create_role(
                RoleName=auth_role_name,
                AssumeRolePolicyDocument=json.dumps(auth_trust_policy)
            )
            
            self.iam.put_role_policy(
                RoleName=auth_role_name,
                PolicyName=f'{auth_role_name}-policy',
                PolicyDocument=json.dumps(auth_policy)
            )
            
            auth_role_arn = f"arn:aws:iam::{self.account_id}:role/{auth_role_name}"
            print(f"Created authenticated role: {auth_role_arn}")
        except ClientError as e:
            if e.response['Error']['Code'] in ['EntityAlreadyExists', 'EntityAlreadyExistsException']:
                auth_role_arn = f"arn:aws:iam::{self.account_id}:role/{auth_role_name}"
                print(f"Authenticated role already exists: {auth_role_arn}")
            else:
                raise

        # Unauthenticated role
        unauth_role_name = f'{self.project_name}-unauth-role'
        unauth_trust_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {
                        "Federated": "cognito-identity.amazonaws.com"
                    },
                    "Action": "sts:AssumeRoleWithWebIdentity",
                    "Condition": {
                        "StringEquals": {
                            "cognito-identity.amazonaws.com:aud": identity_pool_id
                        },
                        "ForAnyValue:StringLike": {
                            "cognito-identity.amazonaws.com:amr": "unauthenticated"
                        }
                    }
                }
            ]
        }
        
        try:
            self.iam.create_role(
                RoleName=unauth_role_name,
                AssumeRolePolicyDocument=json.dumps(unauth_trust_policy)
            )
            
            unauth_role_arn = f"arn:aws:iam::{self.account_id}:role/{unauth_role_name}"
            print(f"Created unauthenticated role: {unauth_role_arn}")
        except ClientError as e:
            if e.response['Error']['Code'] in ['EntityAlreadyExists', 'EntityAlreadyExistsException']:
                unauth_role_arn = f"arn:aws:iam::{self.account_id}:role/{unauth_role_name}"
                print(f"Unauthenticated role already exists: {unauth_role_arn}")
            else:
                raise

        return auth_role_arn, unauth_role_arn

    def create_s3_bucket(self, bucket_name):
        """Create S3 bucket if it doesn't exist."""
        try:
            if self.aws_region == 'us-east-1':
                self.s3.create_bucket(Bucket=bucket_name)
            else:
                self.s3.create_bucket(
                    Bucket=bucket_name,
                    CreateBucketConfiguration={'LocationConstraint': self.aws_region}
                )
            print(f"Created S3 bucket: {bucket_name}")
        except ClientError as e:
            if e.response['Error']['Code'] in ['BucketAlreadyOwnedByYou', 'BucketAlreadyExists']:
                print(f"S3 bucket already exists: {bucket_name}")
            else:
                print(f"Error creating S3 bucket: {e}")
                raise
        
        # Configure CORS for web dashboard access
        try:
            cors_configuration = {
                'CORSRules': [{
                    'AllowedHeaders': ['*'],
                    'AllowedMethods': ['GET', 'HEAD'],
                    'AllowedOrigins': ['*'],
                    'ExposeHeaders': ['ETag'],
                    'MaxAgeSeconds': 3000
                }]
            }
            self.s3.put_bucket_cors(
                Bucket=bucket_name,
                CORSConfiguration=cors_configuration
            )
            print(f"Configured CORS for S3 bucket: {bucket_name}")
        except ClientError as e:
            print(f"Warning: Failed to configure CORS: {e}")
        
        return bucket_name

    def validate_password(self, password):
        """Validate password against Cognito User Pool password policy."""
        if len(password) < 8:
            return False, "Password must be at least 8 characters long"
        if not re.search(r'[A-Z]', password):
            return False, "Password must contain at least one uppercase letter"
        if not re.search(r'[a-z]', password):
            return False, "Password must contain at least one lowercase letter"
        if not re.search(r'[0-9]', password):
            return False, "Password must contain at least one number"
        if not re.search(r'[^A-Za-z0-9]', password):
            return False, "Password must contain at least one special character"
        return True, "Password is valid"

    def create_demo_user(self, user_pool_id, password):
        """Create a demo user in the User Pool."""
        demo_email = 'demo@example.com'
        
        # Validate password
        is_valid, message = self.validate_password(password)
        if not is_valid:
            raise ValueError(f"Invalid password: {message}")
        
        try:
            self.cognito_idp.admin_create_user(
                UserPoolId=user_pool_id,
                Username=demo_email,
                UserAttributes=[
                    {'Name': 'email', 'Value': demo_email},
                    {'Name': 'email_verified', 'Value': 'true'}
                ],
                TemporaryPassword=password,
                MessageAction='SUPPRESS'
            )
            
            # Set permanent password
            self.cognito_idp.admin_set_user_password(
                UserPoolId=user_pool_id,
                Username=demo_email,
                Password=password,
                Permanent=True
            )
            
            print(f"Created demo user: {demo_email}")
            return demo_email
        except ClientError as e:
            if e.response['Error']['Code'] == 'UsernameExistsException':
                print(f"Demo user already exists: {demo_email}")
                return demo_email
            else:
                print(f"Error creating demo user: {e}")
                raise

    def set_identity_pool_roles(self, identity_pool_id, auth_role_arn, unauth_role_arn):
        """Set roles for Identity Pool."""
        try:
            self.cognito_identity.set_identity_pool_roles(
                IdentityPoolId=identity_pool_id,
                Roles={
                    'authenticated': auth_role_arn,
                    'unauthenticated': unauth_role_arn
                }
            )
            print("Set Identity Pool roles")
        except ClientError as e:
            print(f"Error setting Identity Pool roles: {e}")
            raise

    def create_env_file(self, user_pool_id, client_id, identity_pool_id, iot_policy_name, s3_bucket=None):
        """Create .env file for React app."""
        env_content = f"""# AWS Configuration
REACT_APP_AWS_REGION={self.aws_region}
REACT_APP_COGNITO_USER_POOL_ID={user_pool_id}
REACT_APP_COGNITO_CLIENT_ID={client_id}
REACT_APP_COGNITO_IDENTITY_POOL_ID={identity_pool_id}

# Service Configuration
REACT_APP_S3_BUCKET_NAME={s3_bucket or 'your-s3-bucket-name'}
REACT_APP_MQTT_TOPIC=camera/inference
REACT_APP_IOT_POLICY_NAME={iot_policy_name}
"""
        
        with open('react-web/.env', 'w', encoding='utf-8') as f:
            f.write(env_content)
        print("Created react-web/.env file")

    def setup_all(self, s3_bucket=None, demo_password=None):
        """Setup all AWS resources."""
        print(f"Setting up AWS resources in region: {self.aws_region}")
        
        # Create S3 bucket if provided
        if s3_bucket:
            s3_bucket = self.create_s3_bucket(s3_bucket)
        
        # Create Greengrass Token Exchange Role and Role Alias
        gg_role_arn = self.create_greengrass_token_exchange_role(s3_bucket)
        gg_role_alias_arn = self.create_greengrass_role_alias(gg_role_arn)
        
        # Create Cognito resources
        user_pool_id = self.create_user_pool()
        client_id = self.create_user_pool_client(user_pool_id)
        identity_pool_id = self.create_identity_pool(user_pool_id, client_id)
        
        # Create demo user
        demo_email = self.create_demo_user(user_pool_id, demo_password)
        
        # Create IoT policy
        iot_policy_name = self.create_iot_policy()
        
        # Create IAM roles
        auth_role_arn, unauth_role_arn = self.create_iam_roles(identity_pool_id, iot_policy_name)
        
        # Set Identity Pool roles
        self.set_identity_pool_roles(identity_pool_id, auth_role_arn, unauth_role_arn)
        
        # Create .env file
        self.create_env_file(user_pool_id, client_id, identity_pool_id, iot_policy_name, s3_bucket)
        
        print("\nAWS resources created successfully!")
        print(f"User Pool ID: {user_pool_id}")
        print(f"Client ID: {client_id}")
        print(f"Identity Pool ID: {identity_pool_id}")
        print(f"IoT Policy: {iot_policy_name}")
        print(f"Demo User: {demo_email}")

def main():
    parser = argparse.ArgumentParser(description='Setup AWS resources for Ubuntu Core Greengrass Demo project')
    parser.add_argument('--region', default='eu-west-1', help='AWS region')
    parser.add_argument('--project-name', default='ubuntu-core-gg-demo', help='Project name prefix')
    parser.add_argument('--s3-bucket', help='S3 bucket name for images')
    parser.add_argument('--demo-password', help='Password for demo user (must be 8+ chars with uppercase, lowercase, number, and special character)')
    
    args = parser.parse_args()
    
    # Get password from argument or prompt
    demo_password = args.demo_password
    if not demo_password:
        demo_password = getpass.getpass('Enter password for demo user (demo@example.com): ')
    
    try:
        setup = AWSResourcesSetup(args.region, args.project_name)
        setup.setup_all(args.s3_bucket, demo_password)
    except Exception as e:
        print(f"Setup failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()