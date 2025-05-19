import requests
import base64
import json
import os
import argparse
import time
from urllib.parse import quote
import logging

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
        
        # API version
        self.api_version = "7.1-preview"
        
        # Headers for authentication
        self.source_headers = {
            'Authorization': 'Basic ' + base64.b64encode(f":{self.source_pat}".encode()).decode(),
            'Content-Type': 'application/json'
        }
        
        self.target_headers = {
            'Authorization': 'Basic ' + base64.b64encode(f":{self.target_pat}".encode()).decode(),
            'Content-Type': 'application/json'
        }
        
        # Base URLs
        self.source_base_url = f"https://dev.azure.com/{self.source_org}/{quote(self.source_project)}"
        self.target_base_url = f"https://dev.azure.com/{self.target_org}/{quote(self.target_project)}"
        
        # Create a mapping to track migrated work items
        self.work_item_map = {}
    
    def list_repos(self, is_source=True):
        """List all repositories in the organization/project"""
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
        """Create a new repository in the target project"""
        url = f"{self.target_base_url}/_apis/git/repositories?api-version={self.api_version}"
        
        data = {
            "name": repo_name,
            "project": {
                "id": self.get_project_id(False)
            }
        }
        
        response = requests.post(url, headers=self.target_headers, json=data)
        
        if response.status_code == 201:
            logger.info(f"Created repository: {repo_name}")
            return response.json()
        else:
            logger.error(f"Failed to create repository: {response.status_code} - {response.text}")
            return None
    
    def get_project_id(self, is_source=True):
        """Get the project ID for the specified project"""
        base_url = f"https://dev.azure.com/{self.source_org if is_source else self.target_org}"
        headers = self.source_headers if is_source else self.target_headers
        
        url = f"{base_url}/_apis/projects/{quote(self.source_project if is_source else self.target_project)}?api-version={self.api_version}"
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            return response.json()["id"]
        else:
            logger.error(f"Failed to get project ID: {response.status_code} - {response.text}")
            return None
    
    def clone_repo(self, source_repo, target_repo):
        """Clone repository from source to target"""
        # Step 1: Create a local temp directory
        import tempfile
        import subprocess
        from git import Repo
        
        temp_dir = tempfile.mkdtemp()
        logger.info(f"Created temporary directory: {temp_dir}")
        
        try:
            # Step 2: Clone source repo
            source_url = source_repo["remoteUrl"]
            source_url_with_pat = source_url.replace("https://", f"https://:{self.source_pat}@")
            
            logger.info(f"Cloning source repository: {source_repo['name']}...")
            source_repo_local = Repo.clone_from(source_url_with_pat, temp_dir, mirror=True)
            logger.info(f"Cloned source repository successfully")
            
            # Step 3: Push to target repo
            target_url = target_repo["remoteUrl"]
            target_url_with_pat = target_url.replace("https://", f"https://:{self.target_pat}@")
            
            logger.info(f"Pushing to target repository: {target_repo['name']}...")
            target_remote = source_repo_local.create_remote("target", target_url_with_pat)
            source_repo_local.git.push("target", "--mirror")
            logger.info(f"Pushed to target repository successfully")
            
            return True
            
        except Exception as e:
            logger.error(f"Error cloning repository: {str(e)}")
            return False
        finally:
            # Clean up temporary directory
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)
    
    def list_pull_requests(self, repo_id, is_source=True):
        """List all pull requests in a repository"""
        base_url = self.source_base_url if is_source else self.target_base_url
        headers = self.source_headers if is_source else self.target_headers
        
        url = f"{base_url}/_apis/git/repositories/{repo_id}/pullrequests?api-version={self.api_version}&searchCriteria.status=all"
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            prs = response.json()["value"]
            logger.info(f"Found {len(prs)} pull requests in repository {repo_id}")
            return prs
        else:
            logger.error(f"Failed to list pull requests: {response.status_code} - {response.text}")
            return []
    
    def get_pull_request_details(self, repo_id, pr_id, is_source=True):
        """Get detailed information about a pull request including threads and reviews"""
        base_url = self.source_base_url if is_source else self.target_base_url
        headers = self.source_headers if is_source else self.target_headers
        
        # Get PR details
        url = f"{base_url}/_apis/git/repositories/{repo_id}/pullrequests/{pr_id}?api-version={self.api_version}"
        response = requests.get(url, headers=headers)
        
        if response.status_code != 200:
            logger.error(f"Failed to get PR details: {response.status_code} - {response.text}")
            return None
        
        pr_details = response.json()
        
        # Get PR threads (comments)
        threads_url = f"{base_url}/_apis/git/repositories/{repo_id}/pullrequests/{pr_id}/threads?api-version={self.api_version}"
        threads_response = requests.get(threads_url, headers=headers)
        
        if threads_response.status_code == 200:
            pr_details["threads"] = threads_response.json()["value"]
        else:
            logger.error(f"Failed to get PR threads: {threads_response.status_code} - {threads_response.text}")
            pr_details["threads"] = []
        
        return pr_details
    
    def create_pull_request(self, repo_id, pr_data):
        """Create a pull request in the target repository"""
        url = f"{self.target_base_url}/_apis/git/repositories/{repo_id}/pullrequests?api-version={self.api_version}"
        
        new_pr_data = {
            "sourceRefName": pr_data["sourceRefName"],
            "targetRefName": pr_data["targetRefName"],
            "title": f"[MIGRATED] {pr_data['title']}",
            "description": f"Migrated from {self.source_org}/{self.source_project}\n\n{pr_data['description'] or ''}",
            "status": "active"  # Always create as active, then update status if needed
        }
        
        response = requests.post(url, headers=self.target_headers, json=new_pr_data)
        
        if response.status_code == 201:
            logger.info(f"Created pull request: {new_pr_data['title']}")
            return response.json()
        else:
            logger.error(f"Failed to create pull request: {response.status_code} - {response.text}")
            return None
    
    def add_comments_to_pr(self, repo_id, pr_id, threads):
        """Add comments to a pull request in the target repository"""
        for thread in threads:
            # Create thread
            url = f"{self.target_base_url}/_apis/git/repositories/{repo_id}/pullrequests/{pr_id}/threads?api-version={self.api_version}"
            
            thread_data = {
                "comments": [
                    {
                        "content": comment["content"],
                        "parentCommentId": comment.get("parentCommentId", 0)
                    } for comment in thread["comments"]
                ],
                "status": thread.get("status", "active")
            }
            
            if "threadContext" in thread and thread["threadContext"]:
                thread_data["threadContext"] = thread["threadContext"]
            
            response = requests.post(url, headers=self.target_headers, json=thread_data)
            
            if response.status_code != 200:
                logger.error(f"Failed to add comments to PR: {response.status_code} - {response.text}")
    
    def update_pr_status(self, repo_id, pr_id, status):
        """Update the status of a pull request"""
        url = f"{self.target_base_url}/_apis/git/repositories/{repo_id}/pullrequests/{pr_id}?api-version={self.api_version}"
        
        data = {
            "status": status
        }
        
        response = requests.patch(url, headers=self.target_headers, json=data)
        
        if response.status_code == 200:
            logger.info(f"Updated pull request status to {status}")
            return True
        else:
            logger.error(f"Failed to update pull request status: {response.status_code} - {response.text}")
            return False
    
    def list_work_items(self, is_source=True):
        """List work items in the project"""
        base_url = self.source_base_url if is_source else self.target_base_url
        headers = self.source_headers if is_source else self.target_headers
        
        # Using WIQL (Work Item Query Language) to get work items
        url = f"{base_url}/_apis/wit/wiql?api-version={self.api_version}"
        
        data = {
            "query": f"""
            SELECT [System.Id], [System.WorkItemType], [System.Title], [System.State] 
            FROM workitems 
            WHERE [System.TeamProject] = '{self.source_project if is_source else self.target_project}' 
            AND [System.CreatedDate] >= '2023-01-01T00:00:00Z' AND [System.WorkItemType] IN ('Task', 'Bug', 'User Story')
            ORDER BY [System.Id]
"""

        }
        
        response = requests.post(url, headers=headers, json=data)
        
        if response.status_code == 200:
            work_item_references = response.json()["workItems"]
            logger.info(f"Found {len(work_item_references)} work items in {'source' if is_source else 'target'} project")
            
            # We need to get the detailed work item info
            work_items = []
            for batch in [work_item_references[i:i+100] for i in range(0, len(work_item_references), 100)]:
                ids = ",".join([str(item["id"]) for item in batch])
                
                if not ids:
                    continue
                    
                details_url = f"{'https://dev.azure.com/' + self.source_org if is_source else 'https://dev.azure.com/' + self.target_org}/_apis/wit/workitems?ids={ids}&api-version={self.api_version}&$expand=all"
                details_response = requests.get(details_url, headers=headers)
                
                if details_response.status_code == 200:
                    work_items.extend(details_response.json()["value"])
                else:
                    logger.error(f"Failed to get work item details: {details_response.status_code} - {details_response.text}")
            
            return work_items
        else:
            logger.error(f"Failed to list work items: {response.status_code} - {response.text}")
            return []
    
    def get_work_item_relations(self, work_item_id, is_source=True):
        """Get relations of a work item"""
        base_url = f"https://dev.azure.com/{self.source_org if is_source else self.target_org}"
        headers = self.source_headers if is_source else self.target_headers
        
        url = f"{base_url}/_apis/wit/workitems/{work_item_id}?api-version={self.api_version}&$expand=relations"
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            return response.json().get("relations", [])
        else:
            logger.error(f"Failed to get work item relations: {response.status_code} - {response.text}")
            return []
    
    def create_work_item(self, work_item_data):
        """Create a work item in the target project"""
        work_item_type = work_item_data["fields"]["System.WorkItemType"]
        url = f"{self.target_base_url}/_apis/wit/workitems/${work_item_type}?api-version={self.api_version}"
        
        # Prepare the operations for creating work item
        operations = []
        
        # Add all fields except for system fields that can't be set
        exclude_fields = [
            "System.Id", "System.Rev", "System.CreatedBy", "System.CreatedDate", 
            "System.ChangedBy", "System.ChangedDate", "System.CommentCount",
            "System.TeamProject", "System.AreaPath", "System.IterationPath"
        ]
        
        for field, value in work_item_data["fields"].items():
            if field not in exclude_fields and value is not None:
                operations.append({
                    "op": "add",
                    "path": f"/fields/{field}",
                    "value": value
                })
        
        # Add description with migration notice
        original_description = work_item_data["fields"].get("System.Description", "")
        migration_notice = f"<p><em>Migrated from {self.source_org}/{self.source_project}</em></p>"
        operations.append({
            "op": "add",
            "path": "/fields/System.Description",
            "value": migration_notice + (original_description or "")
        })
        
        # Set area path and iteration path
        operations.append({
            "op": "add",
            "path": "/fields/System.AreaPath",
            "value": self.target_project
        })
        
        operations.append({
            "op": "add",
            "path": "/fields/System.IterationPath",
            "value": self.target_project
        })
        
        # Create the work item
        headers = {**self.target_headers, "Content-Type": "application/json-patch+json"}
        response = requests.post(url, headers=headers, json=operations)
        
        if response.status_code == 200:
            new_work_item = response.json()
            logger.info(f"Created work item: {new_work_item['id']} - {work_item_data['fields'].get('System.Title', 'No Title')}")
            return new_work_item
        else:
            logger.error(f"Failed to create work item: {response.status_code} - {response.text}")
            return None
    
    def update_work_item_relations(self, work_item_id, relations):
        """Update the relations of a work item in the target project"""
        url = f"https://dev.azure.com/{self.target_org}/_apis/wit/workitems/{work_item_id}?api-version={self.api_version}"
        
        operations = []
        for relation in relations:
            # Skip if it's a relation to a work item that wasn't migrated
            if "url" in relation and "/workitems/" in relation["url"]:
                source_id = int(relation["url"].split("/")[-1])
                if source_id in self.work_item_map:
                    target_id = self.work_item_map[source_id]
                    
                    operations.append({
                        "op": "add",
                        "path": "/relations/-",
                        "value": {
                            "rel": relation["rel"],
                            "url": f"https://dev.azure.com/{self.target_org}/_apis/wit/workItems/{target_id}"
                        }
                    })
        
        if operations:
            headers = {**self.target_headers, "Content-Type": "application/json-patch+json"}
            response = requests.patch(url, headers=headers, json=operations)
            
            if response.status_code != 200:
                logger.error(f"Failed to update work item relations: {response.status_code} - {response.text}")
    
    def migrate_repos(self):
        """Migrate all repositories from source to target"""
        source_repos = self.list_repos(True)
        target_repos = self.list_repos(False)
        
        # Create a map of existing target repos by name
        target_repo_map = {repo["name"]: repo for repo in target_repos}
        
        for source_repo in source_repos:
            repo_name = source_repo["name"]
            logger.info(f"Processing repository: {repo_name}")
            
            # Check if repo already exists in target
            if repo_name in target_repo_map:
                logger.info(f"Repository {repo_name} already exists in target. Skipping creation.")
                target_repo = target_repo_map[repo_name]
            else:
                logger.info(f"Creating repository {repo_name} in target...")
                target_repo = self.create_repo(repo_name)
                
                if not target_repo:
                    logger.error(f"Failed to create repository {repo_name}. Skipping.")
                    continue
            
            # Clone the repository
            logger.info(f"Cloning repository {repo_name} to target...")
            success = self.clone_repo(source_repo, target_repo)
            
            if success:
                logger.info(f"Successfully migrated repository: {repo_name}")
            else:
                logger.error(f"Failed to migrate repository: {repo_name}")
    
    def migrate_pull_requests(self):
        """Migrate pull requests from source to target repos"""
        source_repos = self.list_repos(True)
        target_repos = self.list_repos(False)
        
        # Create a map of target repos by name
        target_repo_map = {repo["name"]: repo for repo in target_repos}
        
        for source_repo in source_repos:
            repo_name = source_repo["name"]
            if repo_name not in target_repo_map:
                logger.error(f"Target repository {repo_name} not found. Skipping PR migration.")
                continue
                
            target_repo = target_repo_map[repo_name]
            
            # Get pull requests from source repo
            prs = self.list_pull_requests(source_repo["id"], True)
            
            logger.info(f"Migrating {len(prs)} pull requests for repository {repo_name}...")
            
            for pr in prs:
                # Get detailed PR info including comments
                pr_details = self.get_pull_request_details(source_repo["id"], pr["pullRequestId"], True)
                
                if not pr_details:
                    continue
                
                # Create PR in target
                new_pr = self.create_pull_request(target_repo["id"], pr_details)
                
                if not new_pr:
                    continue
                
                # Add comments if any
                if "threads" in pr_details and pr_details["threads"]:
                    self.add_comments_to_pr(target_repo["id"], new_pr["pullRequestId"], pr_details["threads"])
                
                # Update status if needed
                if pr_details["status"] != "active":
                    self.update_pr_status(target_repo["id"], new_pr["pullRequestId"], pr_details["status"])
    
    def migrate_work_items(self):
        """Migrate work items from source to target project"""
        # Get all work items from source
        source_work_items = self.list_work_items(True)
        
        # First pass: Create all work items
        for work_item in source_work_items:
            new_work_item = self.create_work_item(work_item)
            
            if new_work_item:
                # Store the mapping between source and target work item IDs
                self.work_item_map[work_item["id"]] = new_work_item["id"]
        
        # Second pass: Update relations
        for work_item in source_work_items:
            if work_item["id"] in self.work_item_map:
                target_id = self.work_item_map[work_item["id"]]
                relations = self.get_work_item_relations(work_item["id"], True)
                self.update_work_item_relations(target_id, relations)
    
    def run_migration(self):
        """Run the complete migration process"""
        logger.info("Starting migration process...")
        logger.info(f"Source: {self.source_org}/{self.source_project}")
        logger.info(f"Target: {self.target_org}/{self.target_project}")
        
        # Migrate repositories
        logger.info("Step 1: Migrating repositories...")
        self.migrate_repos()
        
        # Migrate pull requests
        logger.info("Step 2: Migrating pull requests...")
        self.migrate_pull_requests()
        
        # Migrate work items
        logger.info("Step 3: Migrating work items...")
        self.migrate_work_items()
        
        logger.info("Migration completed.")


def main():
    parser = argparse.ArgumentParser(description='Azure DevOps Migration Tool')
    parser.add_argument('--source-org', required=True, help='Source Azure DevOps organization')
    parser.add_argument('--source-project', required=True, help='Source project name')
    parser.add_argument('--target-org', required=True, help='Target Azure DevOps organization')
    parser.add_argument('--target-project', required=True, help='Target project name')
    parser.add_argument('--source-pat', required=True, help='Personal Access Token for source')
    parser.add_argument('--target-pat', required=True, help='Personal Access Token for target')
    
    args = parser.parse_args()
    
    migration_tool = ADOMigrationTool(
        args.source_org,
        args.source_project,
        args.target_org,
        args.target_project,
        args.source_pat,
        args.target_pat
    )
    
    migration_tool.run_migration()


if __name__ == "__main__":
    main()
