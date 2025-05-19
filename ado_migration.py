def migrate_repos(self):
        """Migrate all repositories from source to target"""
        source_repos = self.list_repos(True)
        target_repos = self.list_repos(False)

        # Map of existing target repos by name
        target_repo_map = {repo["name"]: repo for repo in target_repos}

        for source_repo in source_repos:
            repo_name = source_repo["name"]
            logger.info(f"Processing repository: {repo_name}")

            # Create target repo if missing
            if repo_name in target_repo_map:
                logger.info(f"Repository {repo_name} already exists in target. Skipping creation.")
                target_repo = target_repo_map[repo_name]
            else:
                logger.info(f"Creating repository {repo_name} in target...")
                target_repo = self.create_repo(repo_name)
                if not target_repo:
                    logger.error(f"Failed to create repository {repo_name}. Skipping.")
                    continue
                target_repo_map[repo_name] = target_repo  # Add to map

            # Clone source to target
            success = self.clone_repo(source_repo, target_repo)
            if success:
                logger.info(f"Successfully migrated repository: {repo_name}")
            else:
                logger.error(f"Failed to migrate repository: {repo_name}")

    def migrate_pull_requests(self):
        """Migrate pull requests from source to target repos"""
        source_repos = self.list_repos(True)
        target_repos = self.list_repos(False)

        target_repo_map = {repo["name"]: repo for repo in target_repos}

        for source_repo in source_repos:
            repo_name = source_repo["name"]

            # Create target repo if missing
            if repo_name not in target_repo_map:
                logger.warning(f"Target repository {repo_name} not found. Attempting to create it...")
                target_repo = self.create_repo(repo_name)
                if not target_repo:
                    logger.error(f"Failed to create target repo {repo_name}. Skipping PR migration.")
                    continue
                target_repo_map[repo_name] = target_repo
            else:
                target_repo = target_repo_map[repo_name]

            prs = self.list_pull_requests(source_repo["id"], True)
            logger.info(f"Migrating {len(prs)} pull requests for repository {repo_name}...")

            for pr in prs:
                pr_details = self.get_pull_request_details(source_repo["id"], pr["pullRequestId"], True)
                if not pr_details:
                    continue

                new_pr = self.create_pull_request(target_repo["id"], pr_details)
                if not new_pr:
                    continue

                if "threads" in pr_details and pr_details["threads"]:
                    self.add_comments_to_pr(target_repo["id"], new_pr["pullRequestId"], pr_details["threads"])

                if pr_details["status"] != "active":
                    self.update_pr_status(target_repo["id"], new_pr["pullRequestId"], pr_details["status"])
