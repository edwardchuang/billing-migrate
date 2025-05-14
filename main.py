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

def sanitize_label_value(value: str) -> str:
    """
    Sanitizes a string to be a valid GCP label value.
    Label values can only contain lowercase letters, numeric characters,
    underscores, and dashes. They can be at most 63 characters long.
    """
    if not isinstance(value, str):
        return "" # Or raise an error, depending on desired strictness
    # Convert to lowercase
    # get the string truncated by "/" of value
    if "/" in value:
        value = value.split("/")[1]
    # Convert to lowercase
    sanitized = value.lower()
    # Replace characters not allowed in label values (e.g., '/')
    sanitized = sanitized.replace("/", "_")
    # Ensure it only contains allowed characters (more robustly: re.sub(r'[^a-z0-9_-]', '_', sanitized))
    # Truncate to 63 characters
    return sanitized[:63]

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
                print(f"  {project_id}: Label '{label_key}' - REMOVED")
            else:
                print(f"  {project_id}: Label '{label_key}' - NOT FOUND (no action)")
                return
        else:
            labels[label_key] = label_value
            print(f"  {project_id}: Label '{label_key}' -> '{label_value}'")

        update_request = resourcemanager_v3.UpdateProjectRequest(
            project={"name": f"projects/{project_id}", "labels": labels},
            update_mask="labels",
        )
        project_client.update_project(request=update_request)
        print(f"  {project_id}: Labels updated (API)")

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
        logging.error(f"  Project {project_id}: Not found during label update.")
    except Exception as e:
        logging.error(f"  Project {project_id}: Error during label update: {e}")

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
            print(f"BA: {acc_response.name} (Display: {acc_response.display_name}, Open: {acc_response.open})")
            print("-" * 20) # Separator for multiple BAs
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
            print(f"  Project: {proj_response.project_id} (on BA: {billing_account_name})")
            # If you intend to move projects, the logic needs to be more specific.
            # For example, you might want to move projects from a specific source BA to a target BA.
            # move_project_billing_account(billing_client, proj_response.project_id, "billingAccounts/NEW_TARGET_ACCOUNT_ID")
        if not project_found:
            print(f"  No projects on BA: {billing_account_name}")
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
        print(f"  {project_id}: Current BA: {current_info.billing_account_name}.")

        if current_info.billing_account_name == new_billing_account_name:
            print(f"  {project_id}: Already on target BA {new_billing_account_name} (no move).")
            return

        update_request = billing.UpdateProjectBillingInfoRequest(
            name=project_billing_info_name, # Corrected resource name
            project_billing_info={"billing_account_name": new_billing_account_name},
        )
        updated_info = billing_client.update_project_billing_info(request=update_request)
        print(f"  {project_id}: Moved to BA {updated_info.billing_account_name} (API).")

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
        logging.error(f"  Project {project_id}: Or its billing info not found during billing move.")
    except Exception as e:
        logging.error(f"  Project {project_id}: Error during billing move: {e}")
    
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
        print("DRY RUN MODE: Simulating migration. No actual changes will be made.")
    else:
        # operations_log_list will be an empty list if not dry_run, passed from main
        logging.warning("LIVE RUN MODE: Changes will be applied to project billing and labels.")
    print("Initializing billing migration process...")

    potential_moves_count = 0
    processed_projects_count = 0
    moved_projects_count = 0
    try:
        source_billing_accounts_to_process = []
        if source_billing_id_override:
            print(f"Processing specified source billing account: {source_billing_id_override}")
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
            print("Discovering all accessible source billing accounts.")
            source_billing_accounts_request = billing.ListBillingAccountsRequest()
            source_billing_accounts_pager = billing_client.list_billing_accounts(request=source_billing_accounts_request)
            source_billing_accounts_to_process.extend(source_billing_accounts_pager)

        if not source_billing_accounts_to_process:
            print("No source billing accounts found or specified to process.")

        for source_ba in source_billing_accounts_to_process:
            print(f"\n--- Processing Source Billing Account: {source_ba.name} ({source_ba.display_name}) ---")

            if source_ba.name == target_billing_id: # type: ignore
                print(f"  Skipping this BA as it is the target billing account.") # type: ignore
                continue

            projects_request = billing.ListProjectBillingInfoRequest(name=source_ba.name) # type: ignore
            projects_pager = billing_client.list_project_billing_info(request=projects_request)
            
            project_count_in_ba = 0
            for project_info in projects_pager:
                project_count_in_ba +=1
                project_id = project_info.project_id
                original_billing_id = project_info.billing_account_name # This is the current (source) BA
                processed_projects_count += 1
    
                # Detailed operational logging - keep as logging.info
                print(f"  Project: {project_id} (BA: {original_billing_id})")
    
                if original_billing_id == target_billing_id:
                    # This is a decision log, could be print or logging.info. Let's keep it info for now.
                    print(f"    -> Skip: Already on target BA {target_billing_id}.") 
                    continue
    
                if dry_run:
                    print(f"    -> [DRY RUN] Label: '{original_billing_label_key}: {original_billing_id}'.")
                    print(f"    -> [DRY RUN] Move: {original_billing_id} -> {target_billing_id}.")
                    potential_moves_count +=1
                else:
                    sanitized_original_ba_id_for_label = sanitize_label_value(original_billing_id)
                    # Detailed action logging - keep as logging.info
                    print(f"    -> Labeling: '{original_billing_label_key}: {sanitized_original_ba_id_for_label}' (from BA: {original_billing_id}).")
                    update_project_labels(
                        project_client,
                        project_id,
                        original_billing_label_key,
                        sanitized_original_ba_id_for_label, # Use sanitized value for the label
                        operations_recorder=operations_log_list
                    ) # Logging for success/failure is within update_project_labels
                    
                    print(f"    -> Moving to BA: {target_billing_id}.")
                    move_project_billing_account(
                        billing_client,
                        project_id,
                        target_billing_id,
                        operations_recorder=operations_log_list
                    ) # Logging for success/failure is within move_project_billing_account
                    moved_projects_count +=1 # Incremented if no exception from move_project_billing_account
            
            if project_count_in_ba == 0:
                print(f"  No projects on this BA.")

    except Exception as e:
        logging.error(f"An unexpected error occurred during migration orchestration: {e}", exc_info=True)
    finally:
        print("\n--- Migration Orchestration Summary ---")
        print(f"Total projects encountered across all processed source BAs: {processed_projects_count}")
        if dry_run:
            print(f"Projects that would be targeted for labeling and moving: {potential_moves_count}")
        else:
            print(f"Projects for which move was attempted: {moved_projects_count}")
            if operations_log_list is not None:
                 print(f"Number of operations recorded for potential revert: {len(operations_log_list)}")
        print("Migration orchestration finished.")

def handle_revert_operations(
    log_file_path: str,
    billing_client: billing.CloudBillingClient,
    project_client: resourcemanager_v3.ProjectsClient,
    dry_run: bool,
) -> None:
    """Reverts operations recorded in a given log file."""
    if dry_run:
        print(f"DRY RUN REVERT MODE: Simulating revert from log file. No changes will be made.")
    else:
        logging.warning(f"LIVE REVERT MODE: Applying revert operations from {log_file_path}.") # Keep path here for live run emphasis
    print(f"Reading operations log file: {log_file_path}")
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

    print(f"Found {len(operations_to_revert)} operations to revert. Processing in reverse order (last operation first).")

    # Revert operations in reverse order
    reverted_count = 0
    for op_index, op in enumerate(reversed(operations_to_revert), 1):
        op_type = op.get("operation_type")
        project_id = op.get("project_id")
        details = op.get("details")

        if not all([op_type, project_id, details]):
            logging.warning(f"Skipping invalid operation entry: {op}")
            continue

        print(f"\n--- Reverting Operation {op_index}/{len(operations_to_revert)} for Project {project_id} (Type: {op_type}) ---")

        if op_type == "UPDATE_LABEL":
            label_key = details.get("label_key")
            value_to_revert_to = details.get("previous_value") # This can be None
            if label_key is None:
                logging.warning(f"Skipping UPDATE_LABEL revert for {project_id} due to missing 'label_key'. Details: {details}")
                continue
            if dry_run:
                # Detailed dry run action - keep as logging.info
                print(f"    -> [DRY RUN REVERT] Label '{label_key}' -> '{value_to_revert_to}'.")
            else:
                # Detailed action logging - keep as logging.info
                print(f"    -> Revert Label: '{label_key}' -> '{value_to_revert_to}'.")
                update_project_labels(project_client, project_id, label_key, value_to_revert_to, operations_recorder=None) # No recorder for revert
            reverted_count +=1

        elif op_type == "MOVE_BILLING":
            ba_to_revert_to = details.get("previous_billing_account")
            if not ba_to_revert_to: # previous_billing_account should exist
                logging.warning(f"Skipping MOVE_BILLING revert for {project_id} due to missing 'previous_billing_account'. Details: {details}")
                continue
            if dry_run:
                # Detailed dry run action - keep as logging.info
                print(f"    -> [DRY RUN REVERT] Move to BA: {ba_to_revert_to}.")
            else:
                # Detailed action logging - keep as logging.info
                print(f"    -> Revert Move to BA: {ba_to_revert_to}.")
                move_project_billing_account(billing_client, project_id, ba_to_revert_to, operations_recorder=None) # No recorder for revert
            reverted_count +=1
        else:
            logging.warning(f"Unknown operation type '{op_type}' in log for project {project_id}. Skipping.")

    print(f"\n--- Revert Process Summary ---")
    print(f"Revert process from log file '{log_file_path}' finished.")
    if dry_run:
        print(f"{reverted_count}/{len(operations_to_revert)} operations simulated for revert.")
    else:
        print(f"{reverted_count}/{len(operations_to_revert)} operations attempted for revert.")

def main() -> None:
    """Main function to orchestrate GCP operations."""
    # Argument parsing (no changes to logging here, it's standard)
    parser = argparse.ArgumentParser(description="Migrate GCP projects to a target billing account and label with original billing ID.")
    parser.add_argument("--target-billing-id", required=True, help="The full ID of the target billing account (e.g., billingAccounts/0X0X0X-0X0X0X-0X0X0X).")
    parser.add_argument("--original-billing-id-label-key", default="orig-billing", help="Label key for storing the original billing ID (default: orig-billing).")
    parser.add_argument("--source-billing-id", help="Optional. The full ID of a specific source billing account to process (e.g., billingAccounts/0Y0Y0Y-0Y0Y0Y-0Y0Y0Y). If not provided, all accessible billing accounts (excluding the target) will be considered as sources.")
    parser.add_argument("--no-dry-run", action="store_true", help="If set, perform actual changes (applies to both migration and revert). Defaults to dry-run mode.")

    # Add a mutually exclusive group for migration vs revert
    action_group = parser.add_mutually_exclusive_group(required=True)
    action_group.add_argument("--migrate", action="store_true", help="Perform billing migration. Requires --target-billing-id.")
    action_group.add_argument("--revert", metavar="LOG_FILE_PATH", help="Path to a JSON log file to revert operations.")

    args = parser.parse_args()

    billing_client = billing.CloudBillingClient()
    project_client = resourcemanager_v3.ProjectsClient()
    is_dry_run = not args.no_dry_run

    if args.revert:
        if args.target_billing_id or \
           args.original_billing_id_label_key != parser.get_default("original_billing_id_label_key") or \
           args.source_billing_id:
            parser.error("--revert option cannot be used with migration-specific options like --target-billing-id, --original-billing-id-label-key, or --source-billing-id.")
        print(f"Starting revert process using log file: {args.revert}")
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
                    print(f"Created log directory: {OPERATIONS_LOG_DIR}")
                except OSError as e:
                    logging.error(f"Could not create log directory {OPERATIONS_LOG_DIR}: {e}. Operations will not be logged.")
                    operations_to_log = None # Prevent attempting to log if dir creation fails
        print(f"Starting billing migration to target BA: {args.target_billing_id}")

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
                print(f"Operations log saved to: {log_file_path}")
            except IOError as e:
                logging.error(f"Could not write log file to {log_file_path}: {e}")
        elif not is_dry_run and operations_to_log is not None: # operations_to_log is []
            print("No operations were performed or recorded during the migration.")
    else:
        # This case should not be reached due to the mutually exclusive group being required.
        # If it were, parser.print_help() would be appropriate.
        logging.error("No action specified. This should not happen with current argument setup.")

if __name__ == '__main__':
    main()
