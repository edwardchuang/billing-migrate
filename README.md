# GCP Project Billing Migration and Labeling Script

## Overview

This Python script automates the process of migrating Google Cloud Platform (GCP) projects from one or more source billing accounts to a specified target billing account. As part of the migration, it labels each moved project with its original billing account ID.

Crucially, when performing a live migration, the script records all operations (label updates and billing moves) into a timestamped JSON log file. This log file can then be used with the script's `--revert` functionality to undo the performed operations if necessary.

The script is designed with safety in mind and operates in **dry-run mode by default**. This allows you to see what actions would be performed without making any actual changes to your GCP environment. To execute the changes, you must explicitly use the `--no-dry-run` flag.

## Features

*   **Billing Account Migration**: Moves projects to a new target billing account.
*   **Source Billing Account Specification**: Option to migrate from a specific source billing account or all accessible ones.
*   **Original Billing ID Labeling**: Tags projects with a label indicating their original billing account.
*   **Operation Logging**: Records all migration actions (labeling, billing moves) to a timestamped JSON file when not in dry-run mode.
*   **Revert Functionality**: Can read a previously generated operations log file to revert the migration actions.
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
    *   `roles/resourcemanager.projectAdmin` (or a custom role with equivalent permissions) on the projects being modified, or at a higher level in the hierarchy (folder/organization):
        *   `resourcemanager.projects.get` (to get project details for labels)
        *   `resourcemanager.projects.update` (to update project labels)

    Grant these permissions at the appropriate level (e.g., organization, folder, or individual project/billing account) depending on the scope of your migration.

## Usage

The script is executed from the command line.

### Command-Line Arguments

The script uses mutually exclusive arguments for actions: `--migrate` or `--revert`.

**Common Arguments:**
*   `--no-dry-run` (Optional Flag): If present, the script will perform actual changes (applies to both migration and revert). **If omitted, the script runs in dry-run mode.**

**Migration Specific Arguments (used with `--migrate`):**
*   `--migrate` (Action Flag): Specifies that a billing migration should be performed.
*   `--target-billing-id` (Required with `--migrate`): The full ID of the target billing account where projects should be moved (e.g., `billingAccounts/0X0X0X-0X0X0X-0X0X0X`).
*   `--original-billing-id-label-key` (Optional): The label key to use for storing the original billing ID. Defaults to `original-billing-account-id`.
*   `--source-billing-id` (Optional): The full ID of a specific source billing account to process (e.g., `billingAccounts/0Y0Y0Y-0Y0Y0Y-0Y0Y0Y`). If not provided, all accessible billing accounts (excluding the target) will be considered as sources.

**Revert Specific Arguments (used with `--revert`):**
*   `--revert LOG_FILE_PATH` (Action Flag & Value): Specifies that operations from the given log file should be reverted. `LOG_FILE_PATH` is the path to the JSON log file generated during a previous migration.

### Examples

#### Migration Examples

1.  **Dry Run Migration (Recommended First Step)**:
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
