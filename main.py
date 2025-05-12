#!/usr/bin/env python
# -*- coding: utf-8 -*-
import argparse
import json
import logging
import os
from datetime import datetime
from typing import List, Dict, Any, Optional

from google.cloud import billing
from google.cloud import resourcemanager_v3
# from google.cloud.billing_v1.types import BillingAccount # Not directly used, can be removed if not needed elsewhere
from google.api_core.exceptions import NotFound

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

LOG_FILE_TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"
OPERATIONS_LOG_DIR = "migration_logs"

# update a label to a project, with a given billing account id
def update_project_labels(
    project_client: resourcemanager_v3.ProjectsClient,
    project_id: str,
    label_key: str,
    label_value: str | None,
    operations_recorder: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """Updates or removes a label on a GCP project.

    Args:
        project_client: An initialized resourcemanager_v3.ProjectsClient.
        project_id: The ID of the project to update.
        label_key: The key of the label to update/remove.
        label_value: The value for the label. If None, the label is removed.
        operations_recorder: Optional list to record the operation details for revert.
    """
    try:
        request = resourcemanager_v3.GetProjectRequest(name=f"projects/{project_id}")
        project = project_client.get_project(request=request)
        labels = project.labels
        original_label_value = labels.get(label_key) # Capture state before change

        if label_value is None:
            if label_key in labels:
                del labels[label_key]
                logging.info(f"Label '{label_key}' removed from project {project_id}.")
            else:
                logging.info(f"Label '{label_key}' not found on project {project_id}, no action taken.")
                return
        else:
            labels[label_key] = label_value
            logging.info(f"Label '{label_key}' set to '{label_value}' for project {project_id}.")

        update_request = resourcemanager_v3.UpdateProjectRequest(
            project={"name": f"projects/{project_id}", "labels": labels},
            update_mask="labels",
        )
        project_client.update_project(request=update_request)
        logging.info(f"Successfully updated labels for project {project_id}.")

        if operations_recorder is not None:
            operations_recorder.append({
                "operation_type": "UPDATE_LABEL",
                "project_id": project_id,
                "details": {
                    "label_key": label_key,
                    "previous_value": original_label_value,
                    "new_value": label_value
                }
            })
    except NotFound:
        logging.error(f"Project {project_id} not found during label update.")
    except Exception as e:
        logging.error(f"An error occurred while updating labels for {project_id}: {e}")

# (This function might be less directly used or adapted if orchestration handles iteration)
def list_billing_accounts(
    billing_client: billing.CloudBillingClient,
    # project_client: resourcemanager_v3.ProjectsClient # No longer needed here
) -> None:
    """Lists all accessible billing accounts and projects under them."""
    try:
        request = billing.ListBillingAccountsRequest()
        page_result = billing_client.list_billing_accounts(request=request)
        for acc_response in page_result:
            logging.info(f"Billing Account Name: {acc_response.name}")
            logging.info(f"Billing Account Display Name: {acc_response.display_name}")
            logging.info(f"Billing Account Open: {acc_response.open}")
            logging.info("-" * 20)
            # list_project_billing_info(billing_client, acc_response.name) # Call handled by orchestrator
            logging.info("-" * 20)
    except Exception as e:
        logging.error(f"An error occurred while listing billing accounts: {e}")

def list_project_billing_info(
    # This function might be less directly used if orchestration handles iteration
    billing_client: billing.CloudBillingClient,
    billing_account_name: str
) -> None:
    """Lists projects associated with a specific billing account."""
    try:
        request = billing.ListProjectBillingInfoRequest(name=billing_account_name)
        page_result = billing_client.list_project_billing_info(request=request)
        project_found = False
        for proj_response in page_result:
            project_found = True
            logging.info(f"  Project ID: {proj_response.project_id} (under {billing_account_name})")
            # If you intend to move projects, the logic needs to be more specific.
            # For example, you might want to move projects from a specific source BA to a target BA.
            # move_project_billing_account(billing_client, proj_response.project_id, "billingAccounts/NEW_TARGET_ACCOUNT_ID")
        if not project_found:
            logging.info(f"  No projects found under billing account {billing_account_name}")
    except NotFound: # This might not be hit if billing_account_name is valid but has no projects
        logging.warning(f"Billing account {billing_account_name} not found or no project billing info accessible.")
    except Exception as e:
        logging.error(f"An error occurred while listing projects for {billing_account_name}: {e}")

def move_project_billing_account(
    billing_client: billing.CloudBillingClient,
    project_id: str,
    new_billing_account_name: str,
    operations_recorder: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """Moves a project to a new billing account.

    Args:
        operations_recorder: Optional list to record the operation details for revert.
    """

    try:
        project_billing_info_name = f"projects/{project_id}/billingInfo" # Corrected resource name
        current_info_request = billing.GetProjectBillingInfoRequest(name=project_billing_info_name)
        current_info = billing_client.get_project_billing_info(request=current_info_request)
        logging.info(f"Project {project_id} - Current Billing Account: {current_info.billing_account_name}")

        if current_info.billing_account_name == new_billing_account_name:
            logging.info(f"Project {project_id} is already associated with {new_billing_account_name}. No action taken.")
            return

        update_request = billing.UpdateProjectBillingInfoRequest(
            name=project_billing_info_name, # Corrected resource name
            project_billing_info={"billing_account_name": new_billing_account_name},
        )
        updated_info = billing_client.update_project_billing_info(request=update_request)
        logging.info(f"Project {project_id} - Successfully moved to Billing Account: {updated_info.billing_account_name}")

        if operations_recorder is not None:
            operations_recorder.append({
                "operation_type": "MOVE_BILLING",
                "project_id": project_id,
                "details": {
                    "previous_billing_account": current_info.billing_account_name, # BA before this operation
                    "new_billing_account": new_billing_account_name # BA set by this operation
                }
            })
    except NotFound:
        logging.error(f"Project {project_id} or its billing info not found during billing move.")
    except Exception as e:
        logging.error(f"An error occurred while moving billing for project {project_id}: {e}")
    
def orchestrate_billing_migration(
    billing_client: billing.CloudBillingClient,
    project_client: resourcemanager_v3.ProjectsClient,
    target_billing_id: str,
    original_billing_label_key: str,
    dry_run: bool,
    source_billing_id_override: str | None = None,
    operations_log_list: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """
    Orchestrates the migration of projects to a target billing account,
    labeling them with their original billing ID.
    """
    if dry_run:
        logging.info("DRY RUN MODE: No actual changes will be made.")
    else:
        # operations_log_list will be an empty list if not dry_run, passed from main
        logging.warning("LIVE RUN MODE: Changes will be applied to project billing and labels.")

    processed_projects_count = 0
    moved_projects_count = 0

    try:
        source_billing_accounts_to_process = []
        if source_billing_id_override:
            logging.info(f"Processing specified source billing account: {source_billing_id_override}")
            try:
                # Ensure the provided source BA exists and is accessible
                source_ba_request = billing.GetBillingAccountRequest(name=source_billing_id_override)
                source_ba_details = billing_client.get_billing_account(request=source_ba_request)
                source_billing_accounts_to_process.append(source_ba_details)
            except NotFound:
                logging.error(f"Specified source billing account {source_billing_id_override} not found or not accessible. Aborting.")
                return
            except Exception as e:
                logging.error(f"Error fetching specified source billing account {source_billing_id_override}: {e}. Aborting.")
                return
        else:
            logging.info("Discovering all accessible source billing accounts.")
            source_billing_accounts_request = billing.ListBillingAccountsRequest()
            source_billing_accounts_pager = billing_client.list_billing_accounts(request=source_billing_accounts_request)
            source_billing_accounts_to_process.extend(source_billing_accounts_pager)

        for source_ba in source_billing_accounts_to_process:
            logging.info(f"Processing source billing account: {source_ba.name} ({source_ba.display_name})")

            if source_ba.name == target_billing_id: # type: ignore
                logging.info(f"Source billing account {source_ba.name} is the target billing account. Skipping projects under it for migration source.") # type: ignore
                continue

            projects_request = billing.ListProjectBillingInfoRequest(name=source_ba.name) # type: ignore
            projects_pager = billing_client.list_project_billing_info(request=projects_request)

            for project_info in projects_pager:
                project_id = project_info.project_id
                original_billing_id = project_info.billing_account_name # This is the current (source) BA
                processed_projects_count += 1
    
                logging.info(f"Processing project: {project_id} (currently on BA: {original_billing_id})")
    
                if original_billing_id == target_billing_id:
                    logging.info(f"Project {project_id} is already on the target billing account {target_billing_id}. Skipping.")
                    continue
    
                if dry_run:
                    logging.info(f"[DRY RUN] Would label project {project_id} with '{original_billing_label_key}: {original_billing_id}'.")
                    logging.info(f"[DRY RUN] Would move project {project_id} from {original_billing_id} to {target_billing_id}.")
                else:
                    logging.info(f"Attempting to label project {project_id} with '{original_billing_label_key}: {original_billing_id}'.")
                    update_project_labels(
                        project_client,
                        project_id,
                        original_billing_label_key,
                        original_billing_id,
                        operations_recorder=operations_log_list
                    )
                    
                    logging.info(f"Attempting to move project {project_id} to billing account {target_billing_id}.")
                    move_project_billing_account(
                        billing_client,
                        project_id,
                        target_billing_id,
                        operations_recorder=operations_log_list
                    )
                    moved_projects_count +=1 # Increment if move_project_billing_account implies success or add better success check
    
    except Exception as e:
        logging.error(f"An unexpected error occurred during migration orchestration: {e}", exc_info=True)
    finally:
        logging.info(f"Migration process finished. Processed {processed_projects_count} projects.")
        if not dry_run and operations_log_list is not None: # Check operations_log_list specifically
            logging.info(f"Successfully initiated moves for {moved_projects_count} projects.")

def handle_revert_operations(
    log_file_path: str,
    billing_client: billing.CloudBillingClient,
    project_client: resourcemanager_v3.ProjectsClient,
    dry_run: bool,
) -> None:
    """Reverts operations recorded in a given log file."""
    if dry_run:
        logging.info(f"DRY RUN REVERT MODE: Reading log file {log_file_path} but no changes will be made.")
    else:
        logging.warning(f"LIVE REVERT MODE: Applying revert operations from {log_file_path}.")

    try:
        with open(log_file_path, 'r') as f:
            operations_to_revert = json.load(f)
    except FileNotFoundError:
        logging.error(f"Log file not found: {log_file_path}")
        return
    except json.JSONDecodeError:
        logging.error(f"Error decoding JSON from log file: {log_file_path}")
        return
    except Exception as e:
        logging.error(f"Error reading log file {log_file_path}: {e}")
        return

    if not isinstance(operations_to_revert, list):
        logging.error(f"Log file {log_file_path} does not contain a list of operations.")
        return

    logging.info(f"Found {len(operations_to_revert)} operations to revert from {log_file_path}.")

    # Revert operations in reverse order
    for op in reversed(operations_to_revert):
        op_type = op.get("operation_type")
        project_id = op.get("project_id")
        details = op.get("details")

        if not all([op_type, project_id, details]):
            logging.warning(f"Skipping invalid operation entry: {op}")
            continue

        logging.info(f"Reverting operation: {op_type} for project {project_id}")

        if op_type == "UPDATE_LABEL":
            label_key = details.get("label_key")
            value_to_revert_to = details.get("previous_value") # This can be None
            if label_key is None:
                logging.warning(f"Skipping UPDATE_LABEL revert for {project_id} due to missing 'label_key'. Details: {details}")
                continue
            if dry_run:
                logging.info(f"[DRY RUN REVERT] Would update label '{label_key}' on project {project_id} to value: '{value_to_revert_to}'.")
            else:
                update_project_labels(project_client, project_id, label_key, value_to_revert_to, operations_recorder=None) # No recorder for revert

        elif op_type == "MOVE_BILLING":
            ba_to_revert_to = details.get("previous_billing_account")
            if not ba_to_revert_to: # previous_billing_account should exist
                logging.warning(f"Skipping MOVE_BILLING revert for {project_id} due to missing 'previous_billing_account'. Details: {details}")
                continue
            if dry_run:
                logging.info(f"[DRY RUN REVERT] Would move project {project_id} to billing account: {ba_to_revert_to}.")
            else:
                move_project_billing_account(billing_client, project_id, ba_to_revert_to, operations_recorder=None) # No recorder for revert
        else:
            logging.warning(f"Unknown operation type '{op_type}' in log for project {project_id}. Skipping.")

    logging.info(f"Revert process from {log_file_path} finished.")

def main() -> None:
    """Main function to orchestrate GCP operations."""
    parser = argparse.ArgumentParser(description="Migrate GCP projects to a target billing account and label with original billing ID.")
    parser.add_argument("--target-billing-id", required=True, help="The full ID of the target billing account (e.g., billingAccounts/0X0X0X-0X0X0X-0X0X0X).")
    parser.add_argument("--original-billing-id-label-key", default="original-billing-account-id", help="Label key for storing the original billing ID (default: original-billing-account-id).")
    parser.add_argument("--source-billing-id", help="Optional. The full ID of a specific source billing account to process (e.g., billingAccounts/0Y0Y0Y-0Y0Y0Y-0Y0Y0Y). If not provided, all accessible billing accounts (excluding the target) will be considered as sources.")
    parser.add_argument("--no-dry-run", action="store_true", help="If set, perform actual changes (applies to both migration and revert). Defaults to dry-run mode.")

    # Add a mutually exclusive group for migration vs revert
    action_group = parser.add_mutually_exclusive_group(required=True)
    action_group.add_argument("--migrate", action="store_true", help="Perform billing migration. Requires --target-billing-id.")
    action_group.add_argument("--revert", metavar="LOG_FILE_PATH", help="Path to a JSON log file to revert operations.")

    args = parser.parse_args() # Parse first to decide action

    billing_client = billing.CloudBillingClient()
    project_client = resourcemanager_v3.ProjectsClient()
    is_dry_run = not args.no_dry_run

    if args.revert:
        if args.target_billing_id or \
           args.original_billing_id_label_key != parser.get_default("original_billing_id_label_key") or \
           args.source_billing_id:
            parser.error("--revert option cannot be used with migration-specific options like --target-billing-id, --original-billing-id-label-key, or --source-billing-id.")
        handle_revert_operations(args.revert, billing_client, project_client, is_dry_run)
    elif args.migrate:
        if not args.target_billing_id:
            parser.error("--migrate action requires --target-billing-id to be specified.")

        operations_to_log: Optional[List[Dict[str, Any]]] = None
        if not is_dry_run:
            operations_to_log = [] # Initialize for logging only if not dry_run
            if not os.path.exists(OPERATIONS_LOG_DIR):
                try:
                    os.makedirs(OPERATIONS_LOG_DIR)
                    logging.info(f"Created log directory: {OPERATIONS_LOG_DIR}")
                except OSError as e:
                    logging.error(f"Could not create log directory {OPERATIONS_LOG_DIR}: {e}. Operations will not be logged.")
                    operations_to_log = None # Prevent attempting to log if dir creation fails

        orchestrate_billing_migration(
            billing_client,
            project_client,
            args.target_billing_id,
            args.original_billing_id_label_key,
            is_dry_run,
            args.source_billing_id,
            operations_log_list=operations_to_log # Pass the list (or None if dry_run/dir error)
        )

        if operations_to_log is not None and operations_to_log: # Check if list exists and is not empty
            timestamp = datetime.now().strftime(LOG_FILE_TIMESTAMP_FORMAT)
            log_file_name = f"migration_operations_{timestamp}.json"
            log_file_path = os.path.join(OPERATIONS_LOG_DIR, log_file_name)
            try:
                with open(log_file_path, 'w') as f:
                    json.dump(operations_to_log, f, indent=2)
                logging.info(f"Operations log saved to: {log_file_path}")
            except IOError as e:
                logging.error(f"Could not write log file to {log_file_path}: {e}")
        elif not is_dry_run and operations_to_log is not None: # operations_to_log is []
            logging.info("No operations were performed or recorded during the migration.")
    else:
        # This case should not be reached due to the mutually exclusive group being required.
        # If it were, parser.print_help() would be appropriate.
        logging.error("No action specified. This should not happen with current argument setup.")

if __name__ == '__main__':
    main()
