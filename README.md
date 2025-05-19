# Azure DevOps Repo & PR Migration Automation

This repository contains a GitHub Actions-based automation to migrate:

- Repositories
- Pull Requests (PRs)
- Work Items (optional)

From a **source Azure DevOps project** to a **target project**, including comments and metadata.

---

## What It Does

- Clones all repositories from your source project
- Recreates them in the target project (if they don't exist)
- Pushes code and history
- Re-creates Pull Requests with titles, branches, descriptions, and comments
- (Optionally) Migrates Work Items with relationships

---

## How to Use

You must have **Contributor** or **Project Administrator** access in the target project.

### Step 1: Add GitHub Secrets

Go to your repo → **Settings → Secrets and Variables → Actions**, and add:

| Name               | Description                            |
|--------------------|----------------------------------------|
| `SOURCE_PAT`       | PAT with access to source ADO project  |
| `TARGET_PAT`       | PAT with repo creation access in target |
| `SOURCE_ORG`       | Source Azure DevOps organization name  |
| `SOURCE_PROJECT`   | Source project name                    |
| `TARGET_ORG`       | Target Azure DevOps organization name  |
| `TARGET_PROJECT`   | Target project name                    |

> PATs must have:
> - `Code (Read & Write)`
> - `Project and Team (Read & Write)`  
> for both source and target.

---

### Step 2: Trigger Migration

1. Go to the **Actions** tab
2. Click the `Azure DevOps Migration` workflow
3. Hit the **"Run workflow"** button
4. Confirm execution and watch the logs live

Once done, check the target DevOps project:
- Under **Repos**, all source repos should be recreated
- Under **Pull Requests**, PRs with `[MIGRATED]` should appear

---

##  Run Locally (Optional)

Clone this repo and run manually if needed:

# Run script
python ado_migration.py \
  --source-org "source-org-name" \
  --source-project "source-project" \
  --target-org "target-org-name" \
  --target-project "target-project" \
  --source-pat "your-source-pat" \
  --target-pat "your-target-pat"
