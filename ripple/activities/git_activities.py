from __future__ import annotations

import logging
import os
import shutil
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
