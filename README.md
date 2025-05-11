# GCP Project Billing Migration and Labeling Script

## Overview

This Python script automates the process of migrating Google Cloud Platform (GCP) projects from their current billing accounts to a specified target billing account. As part of the migration, it also labels each moved project with its original billing account ID, providing a clear audit trail.

The script is designed with safety in mind and operates in **dry-run mode by default**. This allows you to see what actions would be performed without making any actual changes to your GCP environment. To execute the changes, you must explicitly use the `--no-dry-run` flag.

## Features

*   **Billing Account Migration**: Moves projects to a new target billing account.
*   **Original Billing ID Labeling**: Tags projects with a label indicating their original billing account.
*   **Dry-Run Mode**: By default, shows intended actions without execution.
*   **Comprehensive Logging**: Provides detailed logs of its operations.
*   **Command-Line Interface**: Easy to use with clear arguments.

## Prerequisites

1.  **Python**: Python 3.8 or higher is recommended.
2.  **Pip**: Python package installer.
3.  **Google Cloud SDK**: Ensure `gcloud` is installed and configured.
4.  **Dependencies**: Install the required Python libraries:
    ```bash
    pip install google-cloud-billing google-cloud-resource-manager
    ```
    Alternatively, if you have a `requirements.txt` file with these dependencies:
    ```
    google-cloud-billing
    google-cloud-resource-manager
    ```
    You can install them using:
    ```bash
    pip install -r requirements.txt
    ```
5.  **Authentication**: Authenticate with GCP. The script uses Application Default Credentials (ADC). The easiest way for local development is to run:
    ```bash
    gcloud auth application-default login
    ```
    If running in a GCP environment (e.g., Compute Engine, Cloud Functions), ensure the service account has the necessary permissions.

6.  **IAM Permissions**: The authenticated user or service account running the script needs the following IAM roles/permissions on the relevant organization or billing accounts:
    *   `roles/billing.admin` or a custom role with:
        *   `billing.accounts.list` (to list source billing accounts)
        *   `billing.accounts.get` (implicitly used)
        *   `billing.projects.list` (to list projects under a billing account)
        *   `billing.projects.updateBillingInfo` (to change a project's billing account)
        *   `billing.projects.getBillingInfo` (to check a project's current billing account)
    *   `roles/resourcemanager.projectIamAdmin` or `roles/owner` on the projects being modified, or a custom role with:
        *   `resourcemanager.projects.get` (to get project details for labels)
        *   `resourcemanager.projects.update` (to update project labels)

    Grant these permissions at the appropriate level (e.g., organization, folder, or individual project/billing account) depending on the scope of your migration.

## Usage

The script is executed from the command line.

### Command-Line Arguments

*   `--target-billing-id` (Required): The full ID of the target billing account where projects should be moved (e.g., `billingAccounts/0X0X0X-0X0X0X-0X0X0X`).
*   `--original-billing-id-label-key` (Optional): The label key to use for storing the original billing ID. Defaults to `original-billing-account-id`.
*   `--no-dry-run` (Optional Flag): If present, the script will perform actual changes. **If omitted, the script runs in dry-run mode.**

### Examples

1.  **Dry Run (Recommended First Step)**:
    This command will simulate the migration, showing which projects would be labeled and moved, without making any actual changes.

    ```bash
    python main.py --target-billing-id "billingAccounts/YOUR-TARGET-BILLING-ACCOUNT-ID"
    ```

    You can also specify a custom label key for the original billing ID:
    ```bash
    python main.py --target-billing-id "billingAccounts/YOUR-TARGET-BILLING-ACCOUNT-ID" --original-billing-id-label-key "legacy-billing-acc"
    ```

2.  **Live Run (Perform Actual Migration)**:
    **Use with caution!** This command will perform the actual labeling and billing account moves.

    ```bash
    python main.py --target-billing-id "billingAccounts/YOUR-TARGET-BILLING-ACCOUNT-ID" --no-dry-run
    ```

    Replace `"billingAccounts/YOUR-TARGET-BILLING-ACCOUNT-ID"` with the actual ID of your target billing account.

## Important Notes

*   **Test Thoroughly**: Always run the script in **dry-run mode first** to review the intended changes before executing a live run.
*   **Permissions**: Double-check that the authenticated identity has sufficient IAM permissions. Insufficient permissions can lead to partial failures or errors.
*   **Quotas**: For very large numbers of projects, be mindful of GCP API quotas. The script iterates through projects and makes API calls for each.
*   **Backup/Rollback**: While the script labels projects with their original billing ID, consider your organization's backup and rollback procedures for any critical infrastructure changes.

## This is not an official Google product
