#!/usr/bin/env python
# -*- coding: utf-8 -*-
import argparse
import logging
from typing import Dict, Any, List, Optional

from google.cloud import resourcemanager_v3
from google.cloud import iam_admin_v1
from google.iam.v1 import iam_policy_pb2  # type: ignore

from google.api_core.exceptions import NotFound, GoogleAPICallError

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_project_details(
    project_client: resourcemanager_v3.ProjectsClient,
    project_id: str
) -> Optional[Dict[str, Any]]:
    """
    Retrieves details for a specific project, including its display name,
    state, labels, and principals with the 'roles/owner' IAM role.

    Args:
        project_client: An initialized resourcemanager_v3.ProjectsClient.
        project_id: The ID of the project.

    Returns:
        A dictionary containing project details, or None if an error occurs.
    """
    project_info: Dict[str, Any] = {}
    project_name_full = f"projects/{project_id}"

    try:
        # 1. Get project basic info (display name, state, labels)
        logging.info(f"Fetching basic details for project: {project_id}")
        project_resource = project_client.get_project(name=project_name_full)
        project_info["project_id"] = project_resource.project_id
        project_info["display_name"] = project_resource.display_name
        project_info["state"] = project_resource.state.name
        project_info["labels"] = dict(project_resource.labels) # Convert to a standard dict

        # 2. Get IAM policy to find owners
        logging.info(f"Fetching IAM policy for project: {project_id}")
        iam_policy_request = iam_policy_pb2.GetIamPolicyRequest(resource=project_name_full) # Use the imported GetIamPolicyRequest
        iam_policy = project_client.get_iam_policy(request=iam_policy_request)
        
        owners: List[str] = []
        for binding in iam_policy.bindings:
            if binding.role == "roles/owner":
                owners.extend(binding.members)
        project_info["owners"] = owners

        return project_info

    except NotFound:
        logging.error(f"Project {project_id} not found or access denied.")
        return None
    except GoogleAPICallError as e:
        logging.error(f"API call error while fetching details for project {project_id}: {e}")
        return None
    except Exception as e:
        logging.error(f"An unexpected error occurred for project {project_id}: {e}", exc_info=True)
        return None

def print_project_details(details: Dict[str, Any]) -> None:
    """Prints project details in a readable format."""
    print(f"  ------------------------------------")
    print(f"  Project ID:     {details.get('project_id')}")
    print(f"  Display Name:   {details.get('display_name')}")
    print(f"  State:          {details.get('state')}")
    
    print(f"  Owners (principals with 'roles/owner'):")
    owners = details.get('owners')
    if owners:
        for owner in owners:
            print(f"    - {owner}")
    else:
        print(f"    - No principals found with the 'roles/owner' role.")
        
    print(f"  Labels:")
    labels = details.get('labels')
    if labels:
        for key, value in labels.items():
            print(f"    - {key}: {value}")
    else:
        print(f"    - No labels found.")
    print(f"  ------------------------------------")


def process_folder(
    project_client: resourcemanager_v3.ProjectsClient,
    folder_id: str
) -> None:
    """
    Processes all projects within a given folder and prints their details.

    Args:
        project_client: An initialized resourcemanager_v3.ProjectsClient.
        folder_id: The ID of the folder (e.g., "123456789012").
    """
    parent_resource = f"folders/{folder_id}"
    logging.info(f"--- Processing Folder: {parent_resource} ---")
    
    try:
        list_projects_request = resourcemanager_v3.ListProjectsRequest(parent=parent_resource)
        project_pager = project_client.list_projects(request=list_projects_request)
        
        project_found = False
        for project in project_pager:
            project_found = True
            print(f"\nFetching details for Project ID: {project.project_id} (Parent: {project.parent})")
            details = get_project_details(project_client, project.project_id)
            if details:
                print_project_details(details)
        
        if not project_found:
            logging.info(f"No projects found in folder {folder_id}.")

    except NotFound: # This might occur if the folder itself is not found or accessible
        logging.error(f"Folder {folder_id} not found or access denied.")
    except GoogleAPICallError as e:
        logging.error(f"API call error while listing projects in folder {folder_id}: {e}")
    except Exception as e:
        logging.error(f"An unexpected error occurred while processing folder {folder_id}: {e}", exc_info=True)

def main() -> None:
    """Main function to parse arguments and orchestrate project info retrieval."""
    parser = argparse.ArgumentParser(
        description="Retrieve GCP project information (owners, labels) for a specific project or all projects in a folder."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--project-id",
        help="The ID of the GCP project (e.g., 'my-gcp-project')."
    )
    group.add_argument(
        "--folder-id",
        help="The ID of the GCP folder (e.g., '123456789012')."
    )

    args = parser.parse_args()

    try:
        project_client = resourcemanager_v3.ProjectsClient()
    except Exception as e:
        logging.error(f"Failed to initialize Google Cloud Projects client: {e}", exc_info=True)
        return

    if args.project_id:
        print(f"--- Fetching details for Project ID: {args.project_id} ---")
        details = get_project_details(project_client, args.project_id)
        if details:
            print_project_details(details)
        else:
            print(f"Could not retrieve details for project {args.project_id}.")
    elif args.folder_id:
        process_folder(project_client, args.folder_id)

if __name__ == '__main__':
    main()
