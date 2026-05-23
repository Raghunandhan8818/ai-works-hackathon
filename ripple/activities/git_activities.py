from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

from temporalio import activity

logger = logging.getLogger(__name__)

from ripple.rib.indexer.cloner import cleanup_clone, clone_repo, service_name_from_url


@activity.defn(name="clone_repo")
async def clone_repo_activity(repo_url: str, workflow_run_id: str) -> dict[str, str]:
    root = Path(os.environ.get("RIB_WORKSPACE_ROOT", "/tmp/ripple-workspaces"))
    service_name = service_name_from_url(repo_url)
    workspace = root / workflow_run_id / service_name / uuid4().hex[:8]
    logger.info("activity clone_repo url=%s workspace=%s", repo_url, workspace)
    clone_repo(repo_url, workspace)
    logger.info("activity clone_repo done service=%s", service_name)
    return {"workspace": str(workspace), "service_name": service_name}


@activity.defn(name="cleanup_workspace")
async def cleanup_workspace_activity(workspace: str) -> None:
    logger.info("activity cleanup_workspace path=%s", workspace)
    path = Path(workspace)
    if path.exists():
        cleanup_clone(path)
    parent = path.parent
    if parent.exists() and not any(parent.iterdir()):
        shutil.rmtree(parent, ignore_errors=True)


@activity.defn(name="get_pr_diff")
async def get_pr_diff_activity(
    repo_url: str,
    branch: str,
    base_branch: str,
    pr_number: int,
    workflow_run_id: str,
) -> dict:
    root = Path(os.environ.get("RIB_WORKSPACE_ROOT", "/tmp/ripple-workspaces"))
    workspace = root / workflow_run_id / f"pr-{pr_number}" / uuid4().hex[:8]
    workspace.mkdir(parents=True, exist_ok=True)

    logger.info("activity get_pr_diff repo=%s branch=%s base=%s workspace=%s", repo_url, branch, base_branch, workspace)

    # Clone the repo with full history so we can compute the diff
    clone_cmd = ["git", "clone", repo_url, str(workspace)]
    result = subprocess.run(clone_cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to clone {repo_url}: {result.stderr.strip()}")

    # Fetch the base branch explicitly
    fetch_cmd = ["git", "-C", str(workspace), "fetch", "origin", base_branch]
    subprocess.run(fetch_cmd, capture_output=True, text=True, check=False)

    # Checkout the PR branch
    checkout_cmd = ["git", "-C", str(workspace), "checkout", branch]
    result = subprocess.run(checkout_cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        # branch may already be checked out or needs fetch
        fetch_branch = ["git", "-C", str(workspace), "fetch", "origin", branch]
        subprocess.run(fetch_branch, capture_output=True, text=True, check=False)
        subprocess.run(checkout_cmd, capture_output=True, text=True, check=False)

    # Compute diff between base and PR branch
    diff_cmd = ["git", "-C", str(workspace), "diff", f"origin/{base_branch}...HEAD"]
    diff_result = subprocess.run(diff_cmd, capture_output=True, text=True, check=False)
    diff_content = diff_result.stdout

    diff_path = root / workflow_run_id / f"pr-{pr_number}.diff"
    diff_path.write_text(diff_content, encoding="utf-8")

    lines_changed = len([l for l in diff_content.splitlines() if l.startswith(("+", "-")) and not l.startswith(("+++", "---"))])
    logger.info("activity get_pr_diff done diff_path=%s lines_changed=%d", diff_path, lines_changed)

    # Cap content at 50k chars — Temporal payload limit is ~2MB, this stays well under
    return {
        "workspace": str(workspace),
        "diff_path": str(diff_path),
        "lines_changed": lines_changed,
        "diff_content": diff_content[:50_000],
    }
