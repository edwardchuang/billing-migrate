#!/usr/bin/env python
# -*- coding: utf-8 -*-
import logging
import argparse

from google.cloud import billing
from google.api_core.exceptions import NotFound, GoogleAPICallError

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def find_projects_with_billing_info_issues(
    billing_client: billing.CloudBillingClient,
    source_billing_id_override: str | None = None,
):
    """
    Scans projects under accessible billing accounts and identifies those for which
    detailed billing information cannot be retrieved.

    Args:
        billing_client: An initialized billing.CloudBillingClient.
        source_billing_id_override: Optional. The full ID of a specific source
                                    billing account to process. If not provided,
                                    all accessible billing accounts will be scanned.
    """
    problematic_projects_found = 0
    processed_projects_count = 0

    try:
        billing_accounts_to_process = []
        if source_billing_id_override:
            try:
                # Ensure the provided source BA exists and is accessible
                source_ba_request = billing.GetBillingAccountRequest(name=source_billing_id_override)
                source_ba_details = billing_client.get_billing_account(request=source_ba_request)
                billing_accounts_to_process.append(source_ba_details)
            except NotFound:
                logging.error(f"Specified source billing account {source_billing_id_override} not found or not accessible. Aborting.")
                return
            except Exception as e:
                logging.error(f"Error fetching specified source billing account {source_billing_id_override}: {e}. Aborting.")
                return
        else:
            print("Discovering all accessible billing accounts.")
            list_ba_request = billing.ListBillingAccountsRequest()
            billing_accounts_to_process.extend(billing_client.list_billing_accounts(request=list_ba_request))

        if not billing_accounts_to_process:
            print("No source billing accounts found or specified to process.")
            return

        for ba in billing_accounts_to_process:
            print(f"\n--- Checking Billing Account: {ba.name} ({ba.display_name}) ---")
            
            # List projects under this billing account
            # This gives us projects that are *linked* to the BA.
            list_projects_request = billing.ListProjectBillingInfoRequest(name=ba.name)
            try:
                projects_pager = billing_client.list_project_billing_info(request=list_projects_request)
            except GoogleAPICallError as e:
                logging.error(f"  Could not list projects for BA {ba.name}: {e}")
                continue # Skip to the next billing account

            project_found_in_ba = False
            for project_billing_entry in projects_pager:
                project_found_in_ba = True
                project_id = project_billing_entry.project_id
                processed_projects_count += 1
                
                # Attempt to get detailed billing info for this specific project.
                # This tests if the 'projects/{project_id}/billingInfo' resource is accessible.
                project_billing_info_resource_name = f"projects/{project_id}"
                get_billing_info_request = billing.GetProjectBillingInfoRequest(name=project_billing_info_resource_name)
                
                try:
                    billing_client.get_project_billing_info(request=get_billing_info_request)
                    # If successful, we don't need to print anything for this script's purpose.
                    # print(f"  Project {project_id}: Billing info accessible.")
                except NotFound:
                    print(f"  Project {project_id}: UNABLE TO GET BILLING INFO (NotFound - project or its billingInfo sub-resource may be missing/inaccessible).")
                    problematic_projects_found += 1
                except Exception as e:
                    print(f"  Project {project_id}: UNABLE TO GET BILLING INFO (Error: {e}).")
                    problematic_projects_found += 1
            
            if not project_found_in_ba:
                print(f"  No projects found linked to this billing account ({ba.name}).")

    except Exception as e:
        logging.error(f"An unexpected error occurred during the scan: {e}", exc_info=True)

def main() -> None:
    parser = argparse.ArgumentParser(description="Scan GCP projects for billing info accessibility issues.")
    parser.add_argument("--source-billing-id", help="Optional. The full ID of a specific source billing account to process (e.g., billingAccounts/0Y0Y0Y-0Y0Y0Y-0Y0Y0Y). If not provided, all accessible billing accounts will be scanned.")

    args = parser.parse_args()

    billing_client = billing.CloudBillingClient()
    find_projects_with_billing_info_issues(
        billing_client,
        source_billing_id_override=args.source_billing_id
    )

if __name__ == '__main__':
    main()