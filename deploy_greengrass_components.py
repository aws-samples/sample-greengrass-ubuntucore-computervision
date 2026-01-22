#!/usr/bin/env python3
"""
AWS Greengrass Component Deployment Script

This script automates the creation and deployment of Greengrass components
from a local folder structure to AWS IoT Greengrass.

Supports three stages:
- create: Upload artifacts and create components in AWS
- deploy: Create deployment to IoT Thing (components must exist)
- full: Both create and deploy in one operation
"""

import os
import sys
import json
import yaml
import boto3
import argparse
from pathlib import Path
from botocore.exceptions import ClientError
from setup_aws_resources import AWSResourcesSetup

class GreengrassDeployer:
    def __init__(self, s3_bucket, aws_region='us-east-1'):
        self.s3_bucket = s3_bucket
        self.aws_region = aws_region
        
        # Initialize AWS clients
        self.s3_client = boto3.client('s3', region_name=aws_region)
        self.greengrass_client = boto3.client('greengrassv2', region_name=aws_region)
        self.iot_client = boto3.client('iot', region_name=aws_region)
        self.sts_client = boto3.client('sts', region_name=aws_region)
        
        # Get AWS account ID
        self.account_id = self.sts_client.get_caller_identity()['Account']
        
        self.components_dir = Path('greengrass-components')
        self.recipes_dir = self.components_dir / 'recipes'
        self.artifacts_dir = self.components_dir / 'artifacts'

    def validate_structure(self):
        """Validate the expected folder structure exists."""
        if not self.components_dir.exists():
            raise FileNotFoundError(f"Components directory not found: {self.components_dir}")
        if not self.recipes_dir.exists():
            raise FileNotFoundError(f"Recipes directory not found: {self.recipes_dir}")
        if not self.artifacts_dir.exists():
            raise FileNotFoundError(f"Artifacts directory not found: {self.artifacts_dir}")

    def upload_artifacts_to_s3(self, component_name, version):
        """Upload component artifacts to S3."""
        artifact_path = self.artifacts_dir / component_name / version
        if not artifact_path.exists():
            print(f"No artifacts found for {component_name} v{version}")
            return {}

        uploaded_artifacts = {}
        s3_prefix = f"greengrass-components/{component_name}/{version}/"

        for artifact_file in artifact_path.iterdir():
            if artifact_file.is_file():
                s3_key = s3_prefix + artifact_file.name
                
                try:
                    self.s3_client.upload_file(
                        str(artifact_file),
                        self.s3_bucket,
                        s3_key
                    )
                    s3_uri = f"s3://{self.s3_bucket}/{s3_key}"
                    uploaded_artifacts[artifact_file.name] = s3_uri
                    print(f"Uploaded {artifact_file.name} to {s3_uri}")
                except ClientError as e:
                    print(f"Failed to upload {artifact_file.name}: {e}")
                    raise

        return uploaded_artifacts

    def update_recipe_with_s3_uris(self, recipe_data, uploaded_artifacts):
        """Update recipe with S3 URIs for artifacts."""
        if 'Manifests' in recipe_data:
            for manifest in recipe_data['Manifests']:
                if 'Artifacts' in manifest:
                    for artifact in manifest['Artifacts']:
                        artifact_name = artifact['Uri']
                        if artifact_name in uploaded_artifacts:
                            artifact['Uri'] = uploaded_artifacts[artifact_name]
        return recipe_data

    def delete_component_version(self, component_name, component_version):
        """Delete a specific component version."""
        try:
            self.greengrass_client.delete_component(
                arn=f"arn:aws:greengrass:{self.aws_region}:{self.account_id}:components:{component_name}:versions:{component_version}"
            )
            print(f"Deleted component: {component_name} v{component_version}")
            return True
        except ClientError as e:
            if e.response['Error']['Code'] == 'ResourceNotFoundException':
                print(f"Component {component_name} v{component_version} not found")
                return False
            else:
                print(f"Failed to delete component {component_name}: {e}")
                return False

    def cancel_deployment(self, thing_name):
        """Cancel active deployments for a thing."""
        try:
            target_arn = f"arn:aws:iot:{self.aws_region}:{self.account_id}:thing/{thing_name}"
            response = self.greengrass_client.list_deployments(
                targetArn=target_arn,
                maxResults=10
            )
            
            for deployment in response.get('deployments', []):
                deployment_id = deployment['deploymentId']
                status = deployment['deploymentStatus']
                
                if status in ['ACTIVE', 'IN_PROGRESS']:
                    try:
                        self.greengrass_client.cancel_deployment(
                            deploymentId=deployment_id
                        )
                        print(f"Cancelled deployment: {deployment_id}")
                    except ClientError as e:
                        print(f"Could not cancel deployment {deployment_id}: {e}")
        except ClientError as e:
            print(f"Error listing deployments: {e}")

    def create_component(self, recipe_file, force_recreate=False):
        """Create a Greengrass component from a recipe file."""
        with open(recipe_file, 'r', encoding='utf-8') as f:
            recipe_data = yaml.safe_load(f)

        component_name = recipe_data['ComponentName']
        component_version = recipe_data['ComponentVersion']
        
        print(f"Processing component: {component_name} v{component_version}")

        # Upload artifacts to S3
        uploaded_artifacts = self.upload_artifacts_to_s3(component_name, component_version)
        
        # Update recipe with S3 URIs
        recipe_data = self.update_recipe_with_s3_uris(recipe_data, uploaded_artifacts)
        
        # Update S3 bucket configuration for InferenceHandlerCore
        if component_name == 'com.example.InferenceHandlerCore':
            if 'ComponentConfiguration' in recipe_data and 'DefaultConfiguration' in recipe_data['ComponentConfiguration']:
                recipe_data['ComponentConfiguration']['DefaultConfiguration']['S3BucketName'] = self.s3_bucket
                print(f"Updated S3BucketName to: {self.s3_bucket}")

        # Create component
        try:
            response = self.greengrass_client.create_component_version(
                inlineRecipe=yaml.dump(recipe_data).encode('utf-8')
            )
            print(f"Created component: {component_name} v{component_version}")
            return {
                'componentName': component_name,
                'componentVersion': component_version,
                'arn': response['arn']
            }
        except ClientError as e:
            if e.response['Error']['Code'] == 'ConflictException':
                if force_recreate:
                    print(f"Component exists, attempting to delete and recreate...")
                    if self.delete_component_version(component_name, component_version):
                        # Retry creation
                        response = self.greengrass_client.create_component_version(
                            inlineRecipe=yaml.dump(recipe_data).encode('utf-8')
                        )
                        print(f"Recreated component: {component_name} v{component_version}")
                        return {
                            'componentName': component_name,
                            'componentVersion': component_version,
                            'arn': response['arn']
                        }
                else:
                    print(f"Component {component_name} v{component_version} already exists (use --force to recreate)")
                    return {
                        'componentName': component_name,
                        'componentVersion': component_version,
                        'arn': f"arn:aws:greengrass:{self.aws_region}:{self.account_id}:components:{component_name}:versions:{component_version}"
                    }
            else:
                print(f"Failed to create component {component_name}: {e}")
                raise

    def create_all_components(self, force_recreate=False):
        """Create all components from recipe files."""
        components = []
        
        for recipe_file in self.recipes_dir.glob('*.yaml'):
            component = self.create_component(recipe_file, force_recreate)
            components.append(component)
        
        return components

    def create_deployment(self, thing_name, components):
        """Create a Greengrass deployment to the specified IoT Thing."""
        deployment_name = f"deployment-{thing_name}"
        
        # Build component configuration
        component_config = {}
        for component in components:
            config = {
                'componentVersion': component['componentVersion'],
                'configurationUpdate': {
                    'reset': ['']
                }
            }
            
            component_config[component['componentName']] = config

        try:
            response = self.greengrass_client.create_deployment(
                targetArn=f"arn:aws:iot:{self.aws_region}:{self.account_id}:thing/{thing_name}",
                deploymentName=deployment_name,
                components=component_config,
                deploymentPolicies={
                    'failureHandlingPolicy': 'ROLLBACK',
                    'componentUpdatePolicy': {
                        'timeoutInSeconds': 300,
                        'action': 'NOTIFY_COMPONENTS'
                    }
                }
            )
            
            deployment_id = response['deploymentId']
            print(f"Created deployment {deployment_id} for thing {thing_name}")
            return deployment_id
            
        except ClientError as e:
            print(f"Failed to create deployment: {e}")
            raise

    def create_components_only(self, force_recreate=False):
        """Create components without deployment."""
        print(f"Creating Greengrass components...")
        print(f"Using S3 bucket: {self.s3_bucket}")
        print(f"AWS Region: {self.aws_region}")
        
        # Validate structure
        self.validate_structure()
        
        # Create all components
        components = self.create_all_components(force_recreate)
        
        print(f"\nComponents created successfully!")
        print(f"Total components: {len(components)}")
        for component in components:
            print(f"  - {component['componentName']} v{component['componentVersion']}")
        
        return components

    def deploy_to_thing(self, thing_name):
        """Deploy existing components to IoT Thing."""
        print(f"Creating deployment to IoT Thing: {thing_name}")
        print(f"AWS Region: {self.aws_region}")
        
        if self.s3_bucket == 'dummy':
            print("Warning: S3 bucket not specified for deployment. Components may not have correct S3 configuration.")
        
        # Get existing components from recipes
        components = self.get_components_from_recipes()
        
        # Create deployment
        deployment_id = self.create_deployment(thing_name, components)
        
        print(f"\nDeployment created successfully!")
        print(f"Deployment ID: {deployment_id}")
        print(f"Components deployed: {len(components)}")
        for component in components:
            print(f"  - {component['componentName']} v{component['componentVersion']}")
        
        return deployment_id

    def get_components_from_recipes(self):
        """Get component information from recipe files without creating them."""
        components = []
        
        for recipe_file in self.recipes_dir.glob('*.yaml'):
            with open(recipe_file, 'r', encoding='utf-8') as f:
                recipe_data = yaml.safe_load(f)
            
            component_name = recipe_data['ComponentName']
            component_version = recipe_data['ComponentVersion']
            
            components.append({
                'componentName': component_name,
                'componentVersion': component_version,
                'arn': f"arn:aws:greengrass:{self.aws_region}:{self.account_id}:components:{component_name}:versions:{component_version}"
            })
        
        return components

    def deploy_full(self, thing_name, force_recreate=False):
        """Full deployment: create components and deploy to thing."""
        print(f"Starting full deployment to IoT Thing: {thing_name}")
        print(f"Using S3 bucket: {self.s3_bucket}")
        print(f"AWS Region: {self.aws_region}")
        
        # Validate structure
        self.validate_structure()
        
        # Create all components
        components = self.create_all_components(force_recreate)
        
        # Create deployment
        deployment_id = self.create_deployment(thing_name, components)
        
        print(f"\nFull deployment completed successfully!")
        print(f"Deployment ID: {deployment_id}")
        print(f"Components deployed: {len(components)}")
        for component in components:
            print(f"  - {component['componentName']} v{component['componentVersion']}")

def get_user_input(prompt, required=True):
    """Get user input with optional validation."""
    while True:
        value = input(prompt).strip()
        if value or not required:
            return value
        print("This field is required. Please enter a value.")

def main():
    parser = argparse.ArgumentParser(description='Deploy Greengrass components to AWS')
    parser.add_argument('--stage', choices=['create', 'deploy', 'full', 'setup'],
                       help='Deployment stage: create (components only), deploy (to thing), full (both), or setup (AWS resources)')
    parser.add_argument('--thing-name', help='IoT Thing name')
    parser.add_argument('--s3-bucket', help='S3 bucket for storing artifacts')
    parser.add_argument('--region', help='AWS region')
    parser.add_argument('--force', action='store_true', help='Force recreate components if they already exist')
    
    args = parser.parse_args()
    
    # Get stage if not provided
    stage = args.stage
    if not stage:
        print("\nSelect deployment stage:")
        print("1) create - Upload artifacts and create components")
        print("2) deploy - Deploy to IoT Thing")
        print("3) full - Both create and deploy")
        print("4) setup - Setup AWS resources for React dashboard")
        choice = get_user_input("Enter choice (1-4): ")
        stage_map = {'1': 'create', '2': 'deploy', '3': 'full', '4': 'setup'}
        stage = stage_map.get(choice)
        if not stage:
            print("Invalid choice")
            sys.exit(1)
    
    # Get required parameters based on stage
    s3_bucket = args.s3_bucket
    thing_name = args.thing_name
    region = args.region or 'us-east-1'
    
    if stage in ['create', 'full'] and not s3_bucket:
        s3_bucket = get_user_input("Enter S3 bucket name: ")
    
    if stage in ['deploy', 'full'] and not thing_name:
        thing_name = get_user_input("Enter IoT Thing name: ")
    
    if not args.region:
        region_input = get_user_input("Enter AWS region [us-east-1]: ", required=False)
        region = region_input or 'us-east-1'
    
    try:
        deployer = GreengrassDeployer(s3_bucket or 'dummy', region)
        
        if stage == 'create':
            deployer.create_components_only(args.force)
        elif stage == 'deploy':
            deployer.deploy_to_thing(thing_name)
        elif stage == 'full':
            deployer.deploy_full(thing_name, args.force)
        elif stage == 'setup':
            setup = AWSResourcesSetup(region, 'ubuntu-core-gg-demo')
            setup.setup_all(s3_bucket)
            
    except Exception as e:
        print(f"Operation failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()