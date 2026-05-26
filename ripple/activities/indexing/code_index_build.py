from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path

from temporalio import activity

logger = logging.getLogger(__name__)

# Switch via env var. codebase-memory-mcp has 155-language support.
# codegraph-mcp has multi-workspace support with semantic embeddings.
_TOOL = os.environ.get("RIPPLE_GRAPH_TOOL", "codebase-memory-mcp")


@activity.defn(name="code_index_build")
async def code_index_build_activity(shared_root: str) -> dict:
    """
    Index the shared workspace so Claude Code's MCP tools can query it.

    codebase-memory-mcp: calls `index_repository` on the shared root.
      Tools available to Claude: search_code, query_graph, get_code_snippet,
      trace_path, get_architecture.

    codegraph-mcp: starts with --workspace pointing at shared root.
      No pre-build needed — server indexes on startup.
    """
    root = Path(shared_root)
    logger.info("code_index_build tool=%s root=%s", _TOOL, root)

    if _TOOL == "codegraph":
        return _prepare_codegraph(root)
    else:
        return _run_codebase_memory_mcp_index(root)


def _run_codebase_memory_mcp_index(root: Path) -> dict:
    """
    Index the shared root with codebase-memory-mcp.
    Project name = path with / replaced by -, e.g.
      /tmp/ripple-workspaces/abc123  →  tmp-ripple-workspaces-abc123
    """
    cmd = [
        "codebase-memory-mcp", "cli", "index_repository",
        json.dumps({"repo_path": str(root), "mode": "fast"}),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

    try:
        out = json.loads(result.stdout.splitlines()[-1]) if result.stdout else {}
    except (json.JSONDecodeError, IndexError):
        out = {}

    project_name = out.get("project", _path_to_project_name(root))
    success = out.get("status") in ("indexed", "up_to_date") or result.returncode == 0

    if not success:
        logger.warning(
            "codebase-memory-mcp index failed root=%s stderr=%s",
            root, result.stderr[:300],
        )

    logger.info(
        "codebase-memory-mcp index done project=%s nodes=%s edges=%s success=%s",
        project_name, out.get("nodes", "?"), out.get("edges", "?"), success,
    )
    return {
        "success": success,
        "tool": "codebase-memory-mcp",
        "project_name": project_name,
        "shared_root": str(root),
        "nodes": out.get("nodes", 0),
        "edges": out.get("edges", 0),
    }


def _prepare_codegraph(root: Path) -> dict:
    """
    codegraph-mcp indexes on server startup (no pre-build step).
    Just validate the tool is available and return the workspace path.
    The MCP config written by cross_repo_graph_builder passes --workspace to the server.
    """
    result = subprocess.run(["codegraph-mcp", "--info"], capture_output=True, text=True, timeout=10)
    available = result.returncode == 0
    if not available:
        logger.warning("codegraph-mcp not found or failed: %s", result.stderr[:200])
    return {
        "success": available,
        "tool": "codegraph-mcp",
        "project_name": "",
        "shared_root": str(root),
    }


def _path_to_project_name(path: Path) -> str:
    """Derive the project name codebase-memory-mcp assigns from a path."""
    return str(path).lstrip("/").replace("/", "-")
