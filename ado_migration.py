import requests
import base64
import json
import os
import argparse
import time
from urllib.parse import quote
import logging
import tempfile
import subprocess
import shutil
from git import Repo

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("migration.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("ado-migration")

class ADOMigrationTool:
    def __init__(self, source_org, source_project, target_org, target_project, source_pat, target_pat):
        self.source_org = source_org
        self.source_project = source_project
        self.target_org = target_org
        self.target_project = target_project
        self.source_pat = source_pat
        self.target_pat = target_pat
        self.api_version = "7.1-preview"

        self.source_headers = {
            'Authorization': 'Basic ' + base64.b64encode(f":{self.source_pat}".encode()).decode(),
            'Content-Type': 'application/json'
        }
        self.target_headers = {
            'Authorization': 'Basic ' + base64.b64encode(f":{self.target_pat}".encode()).decode(),
            'Content-Type': 'application/json'
        }

        self.source_base_url = f"https://dev.azure.com/{self.source_org}/{quote(self.source_project)}"
        self.target_base_url = f"https://dev.azure.com/{self.target_org}/{quote(self.target_project)}"
        self.work_item_map = {}

    def list_repos(self, is_source=True):
        base_url = self.source_base_url if is_source else self.target_base_url
        headers = self.source_headers if is_source else self.target_headers
        url = f"{base_url}/_apis/git/repositories?api-version={self.api_version}"
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            repos = response.json()["value"]
            logger.info(f"Found {len(repos)} repositories in {'source' if is_source else 'target'} project")
            return repos
        else:
            logger.error(f"Failed to list repositories: {response.status_code} - {response.text}")
            return []

    def create_repo(self, repo_name):
        url = f"{self.target_base_url}/_apis/git/repositories?api-version={self.api_version}"
        data = {"name": repo_name}
        response = requests.post(url, headers=self.target_headers, json=data)
        if response.status_code == 201:
            logger.info(f"Created repository: {repo_name}")
            return response.json()
        else:
            logger.error(f"Failed to create repository: {response.status_code} - {response.text}")
            return None

    def clone_repo(self, source_repo, target_repo):
        temp_dir = tempfile.mkdtemp()
        logger.info(f"Cloning repo {source_repo['name']} into {temp_dir}")
        try:
            source_url = source_repo["remoteUrl"].replace("https://", f"https://:{self.source_pat}@")
            target_url = target_repo["remoteUrl"].replace("https://", f"https://:{self.target_pat}@")
            repo = Repo.clone_from(source_url, temp_dir, mirror=True)
            repo.create_remote("target", target_url)
            repo.git.push("target", "--mirror")
            logger.info(f"Repo {source_repo['name']} mirrored successfully")
            return True
        except Exception as e:
            logger.error(f"Error cloning repo {source_repo['name']}: {str(e)}")
            return False
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def migrate_repos(self):
        source_repos = self.list_repos(True)
        target_repos = self.list_repos(False)
        target_repo_map = {repo["name"]: repo for repo in target_repos}

        for source_repo in source_repos:
            name = source_repo["name"]
            if name in target_repo_map:
                logger.info(f"Repo {name} already exists in target.")
                target_repo = target_repo_map[name]
            else:
                logger.info(f"Creating missing repo {name} in target.")
                target_repo = self.create_repo(name)
                if not target_repo:
                    continue
                target_repo_map[name] = target_repo

            if not self.clone_repo(source_repo, target_repo):
                logger.error(f"Failed to migrate {name}")

    def list_pull_requests(self, repo_id, is_source=True):
        base_url = self.source_base_url if is_source else self.target_base_url
        headers = self.source_headers if is_source else self.target_headers
        url = f"{base_url}/_apis/git/repositories/{repo_id}/pullrequests?searchCriteria.status=all&api-version={self.api_version}"
        res = requests.get(url, headers=headers)
        if res.status_code == 200:
            return res.json().get("value", [])
        else:
            logger.error(f"Failed to list PRs: {res.status_code} - {res.text}")
            return []

    def get_pull_request_details(self, repo_id, pr_id, is_source=True):
        base_url = self.source_base_url if is_source else self.target_base_url
        headers = self.source_headers if is_source else self.target_headers
        pr_url = f"{base_url}/_apis/git/repositories/{repo_id}/pullrequests/{pr_id}?api-version={self.api_version}"
        res = requests.get(pr_url, headers=headers)
        if res.status_code != 200:
            return None
        pr = res.json()
        threads_url = f"{pr_url}/threads?api-version={self.api_version}"
        threads_res = requests.get(threads_url, headers=headers)
        pr["threads"] = threads_res.json()["value"] if threads_res.status_code == 200 else []
        return pr

    def create_pull_request(self, repo_id, pr):
        url = f"{self.target_base_url}/_apis/git/repositories/{repo_id}/pullrequests?api-version={self.api_version}"
        data = {
            "sourceRefName": pr["sourceRefName"],
            "targetRefName": pr["targetRefName"],
            "title": f"[MIGRATED] {pr['title']}",
            "description": pr.get("description", ""),
            "status": "active"
        }
        res = requests.post(url, headers=self.target_headers, json=data)
        return res.json() if res.status_code == 201 else None

    def add_comments_to_pr(self, repo_id, pr_id, threads):
        for thread in threads:
            comments = thread.get("comments", [])
            if not comments:
                continue
            url = f"{self.target_base_url}/_apis/git/repositories/{repo_id}/pullrequests/{pr_id}/threads?api-version={self.api_version}"
            thread_data = {
                "comments": [{"content": c["content"], "parentCommentId": c.get("parentCommentId", 0)} for c in comments],
                "status": thread.get("status", "active")
            }
            requests.post(url, headers=self.target_headers, json=thread_data)

    def update_pr_status(self, repo_id, pr_id, status):
        url = f"{self.target_base_url}/_apis/git/repositories/{repo_id}/pullrequests/{pr_id}?api-version={self.api_version}"
        data = {"status": status}
        requests.patch(url, headers=self.target_headers, json=data)

    def migrate_pull_requests(self):
        source_repos = self.list_repos(True)
        target_repos = self.list_repos(False)
        target_repo_map = {r["name"]: r for r in target_repos}

        for source_repo in source_repos:
            name = source_repo["name"]
            if name not in target_repo_map:
                logger.warning(f"{name} missing in target. Creating it.")
                target_repo = self.create_repo(name)
                if not target_repo:
                    continue
                target_repo_map[name] = target_repo
            else:
                target_repo = target_repo_map[name]

            prs = self.list_pull_requests(source_repo["id"], True)
            for pr in prs:
                full = self.get_pull_request_details(source_repo["id"], pr["pullRequestId"], True)
                if not full:
                    continue
                new_pr = self.create_pull_request(target_repo["id"], full)
                if new_pr and "threads" in full:
                    self.add_comments_to_pr(target_repo["id"], new_pr["pullRequestId"], full["threads"])
                    if full["status"] != "active":
                        self.update_pr_status(target_repo["id"], new_pr["pullRequestId"], full["status"])

    def run_migration(self):
        logger.info("Azure DevOps Migration Started")
        self.migrate_repos()
        self.migrate_pull_requests()
        logger.info("Migration completed.")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-org', required=True)
    parser.add_argument('--source-project', required=True)
    parser.add_argument('--target-org', required=True)
    parser.add_argument('--target-project', required=True)
    parser.add_argument('--source-pat', required=True)
    parser.add_argument('--target-pat', required=True)
    args = parser.parse_args()

    tool = ADOMigrationTool(
        args.source_org,
        args.source_project,
        args.target_org,
        args.target_project,
        args.source_pat,
        args.target_pat
    )
    tool.run_migration()

if __name__ == "__main__":
    main()
