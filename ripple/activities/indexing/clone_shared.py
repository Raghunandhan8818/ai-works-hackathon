from __future__ import annotations

import logging
import shutil
from pathlib import Path

from temporalio import activity

from ripple.rib.indexer.cloner import clone_repo, service_name_from_url

logger = logging.getLogger(__name__)


@activity.defn(name="clone_to_shared_workspace")
async def clone_to_shared_workspace_activity(
    repo_url: str,
    shared_root: str,
    service_name: str,
) -> dict:
    """Clone a repo into {shared_root}/{service_name}/ — siblings share the same parent."""
    dest = Path(shared_root) / service_name
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)

    logger.info("clone_to_shared url=%s dest=%s", repo_url, dest)
    clone_repo(repo_url, dest)
    logger.info("clone_to_shared done service=%s", service_name)

    return {"workspace": str(dest), "service_name": service_name}
