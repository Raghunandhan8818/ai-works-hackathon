from __future__ import annotations

import re
import subprocess
from datetime import datetime
from pathlib import Path

from ripple.rib.graph.schema import HistorySignal

RISK_KEYWORDS = [
    "breaking",
    "migrate",
    "deprecat",
    "rename",
    "unit",
    "currency",
    "nullable",
    "required",
    "remove",
    "enum",
]


def analyze_field_history(
    repo_path: str | Path,
    field_name: str,
    field_fqn: str,
    max_commits: int = 50,
) -> list[HistorySignal]:
    path = Path(repo_path)
    if not path.exists():
        return []

    result = subprocess.run(
        [
            "git",
            "-C",
            str(path),
            "log",
            f"-S{field_name}",
            f"-{max_commits}",
            "--pretty=format:%H|%an|%aI|%s",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return []

    signals: list[HistorySignal] = []
    for line in result.stdout.splitlines():
        parts = line.split("|", 3)
        if len(parts) < 4:
            continue
        commit_hash, author, committed_at_raw, message = parts
        signals.append(
            HistorySignal(
                field_fqn=field_fqn,
                commit_hash=commit_hash,
                commit_message=message,
                author=author,
                committed_at=datetime.fromisoformat(
                    committed_at_raw.replace("Z", "+00:00")
                ),
                risk_keywords=_extract_risk_keywords(message),
            )
        )
    return signals


def _extract_risk_keywords(message: str) -> list[str]:
    lowered = message.lower()
    return [kw for kw in RISK_KEYWORDS if re.search(kw, lowered)]
