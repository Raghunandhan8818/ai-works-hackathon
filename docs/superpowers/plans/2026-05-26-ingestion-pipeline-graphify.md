# Ripple — Ingestion Pipeline + Graph Integration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the SCIP-based indexing pipeline with codebase-memory-mcp (graph-based, 155 languages, 99% token reduction), add a LiteLLM abstraction layer, and implement tiered fix execution (Haiku direct API for mechanical fixes, Sonnet for semantic, Claude Code headless only as last resort).

**Architecture:** GraphBuildActivity runs codebase-memory-mcp once per push to build a persistent symbol graph; BeliefExtractorActivity queries the graph for exact file+line locations then sends 15-line snippets to Haiku — 33–50x fewer tokens than current approach. Fix pipeline gains three tiers: Tier 1 direct Haiku API (3–8s), Tier 2 direct Sonnet API (15–30s), Tier 3 Claude Code headless with `--max-turns 5` (fallback only).

**Tech Stack:** Python 3.12, Temporal, FastAPI, PostgreSQL, LiteLLM, `mcp` Python SDK, codebase-memory-mcp (npm), Anthropic SDK (via LiteLLM)

**Deadline:** June 8, 2026 (hackathon demo)

---

## Current Repo Status (as of 2026-05-26)

### What exists and works
| Component | Location | Status |
|---|---|---|
| FastAPI REST backend | `ripple/rib/api/server.py` | Working — fields, blast-radius, disagreements, ingest, analyze, webhooks |
| Temporal worker (4 queues) | `ripple/worker.py` | Working — rib, rib-io, rib-llm, rib-cpu |
| IngestServiceWorkflow | `ripple/workflows/ingest_service.py` | Working but coarse — SCIP → index_producer → index_consumer |
| IngestEcosystemWorkflow | `ripple/workflows/ingest_ecosystem.py` | Working |
| AnalyzePRWorkflow | `ripple/workflows/analyze_pr.py` | Working |
| AutoFixConsumerWorkflow | `ripple/workflows/auto_fix_consumer.py` | Working |
| PostgreSQL knowledge graph | `ripple/rib/graph/postgres_store.py` | Working |
| Schema/models | `ripple/rib/graph/schema.py` | Complete — FieldNode, ConsumerBelief, Disagreement, DisagreementKind, etc. |
| OpenAPI parser | `ripple/rib/indexer/contract_parsers/openapi_parser.py` | Working |
| Field usage finder (grep+tree-sitter) | `ripple/rib/indexer/field_finder.py` | Working |
| Test extractor | `ripple/rib/indexer/test_extractor.py` | Partial |
| Belief enricher (direct Anthropic SDK) | `ripple/rib/enricher/belief_enricher.py` | Working but hardcoded to `claude-3-5-haiku-latest` |
| Fix pipeline (5 activities) | `ripple/activities/fix_activities.py` | Working but `run_claude_code_fix_activity` uses 600s timeout |
| Next.js dashboard | `dashboard/` | Running on localhost:3000, React Flow graph, stats, interrupts page stub |

### Known technical debt (from spec §12)
- `ripple/rib/enricher/belief_enricher.py:43` — hardcoded `claude-3-5-haiku-latest` via direct `anthropic` SDK
- All other LLM calls scattered across enricher files — no unified model abstraction
- `ripple/activities/fix_activities.py:103` — `run_claude_code_fix_activity` runs `claude -p ... --dangerously-skip-permissions` with 600s timeout and no `--max-turns` flag
- `ripple/rib/service_indexer.py` — SCIP calls via `scip_runner.py`; SCIP binary only covers TypeScript, not Java/Go/Python
- No `litellm` in `requirements.txt`
- No interrupt card API endpoints

### What this plan builds
1. **LiteLLMClient** — single wrapper, model injected at activity construction time
2. **GraphBuildActivity** — runs codebase-memory-mcp on `/workspace`, builds persistent symbol graph, returns db path
3. **BeliefExtractorActivity** — queries graph for symbol locations, fetches 15-line snippets, calls Haiku once per field
4. **DisagreementDetectorActivity** — wraps existing `detect_disagreements` + LLM Sonnet for low-confidence cases
5. **SchemaParserActivity** — wraps existing `parse_openapi`, class-based
6. **IndexServiceWorkflowV2** — fine-grained, replaces `IngestServiceWorkflow`, wires new activities
7. **MechanicalFixActivity** — direct Haiku API, single call, replaces Claude Code headless for tier 1
8. **SemanticFixActivity** — direct Sonnet API, single call with human decision attached (tier 2)
9. **Interrupt card API** — `POST /api/interrupts`, `GET /api/interrupts`, `POST /api/interrupts/{id}/answer` + Temporal signal

---

## File Structure

### New files to create
```
ripple/
  llm_client.py                                    # LiteLLM abstraction — single source of truth for model selection
  activities/
    indexing/
      __init__.py
      schema_parser.py                             # SchemaParserActivity — wraps parse_openapi
      graph_build.py                               # GraphBuildActivity — runs codebase-memory-mcp
      belief_extractor.py                          # BeliefExtractorActivity — graph queries + Haiku
      disagreement_detector.py                     # DisagreementDetectorActivity — rules + Sonnet
    fixing/
      __init__.py
      mechanical_fix.py                            # MechanicalFixActivity — Haiku direct API
      semantic_fix.py                              # SemanticFixActivity — Sonnet direct API
  workflows/
    index_service_v2.py                            # IndexServiceWorkflowV2 — fine-grained pipeline
  rib/
    api/
      interrupts.py                                # Interrupt card API routes
    graph/
      interrupt_store.py                           # Interrupt persistence (in-memory + Postgres)
```

### Files to modify
```
requirements.txt                                   # add: litellm>=1.40, mcp>=1.0
ripple/worker.py                                   # register new activities + IndexServiceWorkflowV2
ripple/rib/api/server.py                           # include interrupt router
```

---

## Task 1: Install dependencies

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add litellm and mcp to requirements.txt**

Open `requirements.txt` and add these two lines after the `anthropic` line:

```
litellm>=1.40,<2
mcp>=1.0,<2
```

- [ ] **Step 2: Install**

```bash
pip install litellm mcp
```

Expected: both install without errors. Verify:
```bash
python -c "import litellm; import mcp; print('ok')"
```
Expected output: `ok`

- [ ] **Step 3: Install codebase-memory-mcp**

```bash
npm install -g @deus-data/codebase-memory-mcp
```

Verify:
```bash
codebase-memory-mcp --version
```

> **Note:** If the package name differs from `@deus-data/codebase-memory-mcp`, search npm: `npm search codebase-memory-mcp` and use the correct package. The plan assumes the CLI command is `codebase-memory-mcp`. Adapt if different.

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "chore: add litellm and mcp Python SDK dependencies"
```

---

## Task 2: LiteLLM abstraction layer

**Files:**
- Create: `ripple/llm_client.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_llm_client.py`:

```python
import pytest
from unittest.mock import patch, MagicMock
from ripple.llm_client import LLMClient

def test_complete_returns_string():
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "hello"
    with patch("ripple.llm_client.litellm.acompletion", return_value=mock_response) as mock_call:
        import asyncio
        client = LLMClient(model="claude-haiku-4-5-20251001")
        result = asyncio.run(client.complete("test prompt"))
        assert result == "hello"
        mock_call.assert_called_once()
        call_kwargs = mock_call.call_args[1]
        assert call_kwargs["model"] == "claude-haiku-4-5-20251001"

def test_default_model_is_haiku():
    client = LLMClient()
    assert "haiku" in client.model.lower()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /path/to/ai-works-hackathon
python -m pytest tests/test_llm_client.py -v
```

Expected: `ImportError: No module named 'ripple.llm_client'`

- [ ] **Step 3: Implement LLMClient**

Create `ripple/llm_client.py`:

```python
from __future__ import annotations

import os
import litellm

_DEFAULT_MODEL = os.environ.get("RIPPLE_DEFAULT_MODEL", "claude-haiku-4-5-20251001")


class LLMClient:
    def __init__(self, model: str = _DEFAULT_MODEL):
        self.model = model

    async def complete(self, prompt: str, max_tokens: int = 1000, system: str = "") -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        response = await litellm.acompletion(
            model=self.model,
            messages=messages,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content or ""

    async def complete_json(self, prompt: str, system: str = "", max_tokens: int = 1000) -> str:
        """Like complete() but hints to the model to return JSON only."""
        json_hint = "\n\nReturn ONLY valid JSON. No explanation, no markdown fences."
        return await self.complete(prompt + json_hint, max_tokens=max_tokens, system=system)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/test_llm_client.py -v
```

Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add ripple/llm_client.py tests/test_llm_client.py
git commit -m "feat: add LiteLLM abstraction layer (LLMClient)"
```

---

## Task 3: GraphBuildActivity — codebase-memory-mcp integration

**Files:**
- Create: `ripple/activities/indexing/__init__.py`
- Create: `ripple/activities/indexing/graph_build.py`

- [ ] **Step 1: Write the failing test**

Create `tests/activities/indexing/test_graph_build.py`:

```python
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

def test_graph_build_activity_returns_db_path(tmp_path):
    from ripple.activities.indexing.graph_build import GraphBuildActivity

    activity = GraphBuildActivity()
    fake_db_path = str(tmp_path / ".graph" / "index.db")

    with patch("ripple.activities.indexing.graph_build.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        # Simulate db file being created
        Path(fake_db_path).parent.mkdir(parents=True)
        Path(fake_db_path).touch()

        import asyncio
        result = asyncio.run(activity.execute(str(tmp_path)))

    assert "graph_db_path" in result
    assert result["success"] is True
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/activities/indexing/test_graph_build.py -v
```

Expected: `ModuleNotFoundError: No module named 'ripple.activities.indexing'`

- [ ] **Step 3: Create the package init files**

Create `ripple/activities/indexing/__init__.py`:
```python
```
(empty file)

- [ ] **Step 4: Implement GraphBuildActivity**

Create `ripple/activities/indexing/graph_build.py`:

```python
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from temporalio import activity

logger = logging.getLogger(__name__)

_GRAPH_DIR = ".ripple-graph"


class GraphBuildActivity:
    """
    Runs codebase-memory-mcp to build a persistent symbol graph for the workspace.
    Replaces SCIP — works for 155 languages including Java, TypeScript, Go, Python, Kotlin.
    """

    @activity.defn(name="graph_build")
    async def execute(self, workspace: str) -> dict:
        workspace_path = Path(workspace)
        graph_dir = workspace_path / _GRAPH_DIR
        graph_dir.mkdir(exist_ok=True)
        db_path = graph_dir / "index.db"

        logger.info("graph_build start workspace=%s", workspace)

        # Build the persistent symbol graph
        result = subprocess.run(
            ["codebase-memory-mcp", "build", str(workspace_path), "--output", str(db_path)],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=workspace,
        )

        if result.returncode != 0:
            # Fallback: try alternate CLI flag pattern
            result = subprocess.run(
                ["codebase-memory-mcp", "--workspace", str(workspace_path), "--db", str(db_path), "index"],
                capture_output=True,
                text=True,
                timeout=300,
                cwd=workspace,
            )

        success = result.returncode == 0 and db_path.exists()
        if not success:
            logger.warning(
                "graph_build failed or db not created workspace=%s stderr=%s",
                workspace, result.stderr[:300],
            )

        logger.info("graph_build done workspace=%s success=%s db=%s", workspace, success, db_path)
        return {
            "success": success,
            "graph_db_path": str(db_path) if success else "",
            "workspace": workspace,
        }
```

> **Important:** The exact CLI flags for `codebase-memory-mcp build` may differ from what's shown. Run `codebase-memory-mcp --help` after installing to verify the build command and output flag. Adjust `subprocess.run` args accordingly. The activity's interface (returns `graph_db_path`) must stay stable.

- [ ] **Step 5: Run test to verify it passes**

```bash
python -m pytest tests/activities/indexing/test_graph_build.py -v
```

Expected: `PASSED`

- [ ] **Step 6: Commit**

```bash
git add ripple/activities/indexing/__init__.py ripple/activities/indexing/graph_build.py tests/activities/indexing/test_graph_build.py
git commit -m "feat: add GraphBuildActivity (codebase-memory-mcp integration)"
```

---

## Task 4: GraphClient — MCP query wrapper

**Files:**
- Create: `ripple/graph_client.py`

This is the interface between Temporal activities and the codebase-memory-mcp MCP server. Activities call `GraphClient.find_symbol()`, `GraphClient.get_context()`, etc. without knowing the MCP protocol.

- [ ] **Step 1: Write the failing test**

Create `tests/test_graph_client.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

def test_graph_client_find_symbol():
    from ripple.graph_client import GraphClient
    import asyncio

    client = GraphClient(db_path="/tmp/fake.db")

    fake_mcp_result = MagicMock()
    fake_mcp_result.content = [MagicMock(text='[{"file": "src/PetCard.tsx", "line": 42, "snippet": "ownerPhone = owner.phone"}]')]

    with patch.object(client, "_call_tool", new_callable=AsyncMock, return_value=fake_mcp_result):
        results = asyncio.run(client.find_symbol("ownerPhone"))

    assert len(results) == 1
    assert results[0]["file"] == "src/PetCard.tsx"
    assert results[0]["line"] == 42

def test_graph_client_get_context_returns_string():
    from ripple.graph_client import GraphClient
    import asyncio

    client = GraphClient(db_path="/tmp/fake.db")
    fake_result = MagicMock()
    fake_result.content = [MagicMock(text="line 41: ...\nline 42: ownerPhone\nline 43: ...")]

    with patch.object(client, "_call_tool", new_callable=AsyncMock, return_value=fake_result):
        snippet = asyncio.run(client.get_context("src/PetCard.tsx", 42, 15))

    assert "ownerPhone" in snippet
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_graph_client.py -v
```

Expected: `ModuleNotFoundError: No module named 'ripple.graph_client'`

- [ ] **Step 3: Implement GraphClient**

Create `ripple/graph_client.py`:

```python
from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

logger = logging.getLogger(__name__)


class GraphClient:
    """
    Thin async wrapper around the codebase-memory-mcp MCP server.
    Connects via stdio subprocess transport using the mcp Python SDK.
    """

    def __init__(self, db_path: str):
        self._db_path = db_path

    @asynccontextmanager
    async def _session(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command="codebase-memory-mcp",
            args=["serve", "--db", self._db_path],
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session

    async def _call_tool(self, tool_name: str, arguments: dict):
        async with self._session() as session:
            return await session.call_tool(tool_name, arguments)

    async def find_symbol(self, name: str, repo: str = "") -> list[dict]:
        """Returns list of {file, line, snippet} dicts."""
        args = {"name": name}
        if repo:
            args["repo"] = repo
        try:
            result = await self._call_tool("find_symbol", args)
            raw = result.content[0].text if result.content else "[]"
            data = json.loads(raw) if isinstance(raw, str) else raw
            return data if isinstance(data, list) else []
        except Exception as e:
            logger.warning("graph_client find_symbol error name=%s err=%s", name, e)
            return []

    async def get_context(self, file_path: str, line: int, n: int = 15) -> str:
        """Returns n lines of source context around the given line."""
        try:
            result = await self._call_tool("get_context", {"file": file_path, "line": line, "n": n})
            return result.content[0].text if result.content else ""
        except Exception as e:
            logger.warning("graph_client get_context error file=%s line=%d err=%s", file_path, line, e)
            return ""

    async def get_test_assertions(self, field_name: str) -> list[dict]:
        """Returns list of {file, line, assertion_code} from test files asserting on this field."""
        try:
            result = await self._call_tool("get_test_assertions", {"field": field_name})
            raw = result.content[0].text if result.content else "[]"
            data = json.loads(raw) if isinstance(raw, str) else raw
            return data if isinstance(data, list) else []
        except Exception as e:
            logger.warning("graph_client get_test_assertions error field=%s err=%s", field_name, e)
            return []

    async def get_neighbors(self, symbol: str) -> list[dict]:
        """Returns related symbols (imports, callers, type relationships)."""
        try:
            result = await self._call_tool("get_neighbors", {"symbol": symbol})
            raw = result.content[0].text if result.content else "[]"
            data = json.loads(raw) if isinstance(raw, str) else raw
            return data if isinstance(data, list) else []
        except Exception as e:
            logger.warning("graph_client get_neighbors error symbol=%s err=%s", symbol, e)
            return []
```

> **Note on MCP tool names:** The tool names (`find_symbol`, `get_context`, `get_test_assertions`, `get_neighbors`) may differ in the actual codebase-memory-mcp package. After installing, run `codebase-memory-mcp serve --db /tmp/test.db` and inspect the MCP manifest (`tools/list` call) to get actual tool names. Update the `_call_tool` arguments accordingly.

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/test_graph_client.py -v
```

Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add ripple/graph_client.py tests/test_graph_client.py
git commit -m "feat: add GraphClient MCP wrapper for codebase-memory-mcp"
```

---

## Task 5: BeliefExtractorActivity — graph queries + targeted Haiku

**Files:**
- Create: `ripple/activities/indexing/belief_extractor.py`

This replaces the current combined `index_consumer_activity` belief extraction. Instead of reading whole files, it queries the graph for exact locations and sends only 15-line snippets to Haiku.

- [ ] **Step 1: Write the failing test**

Create `tests/activities/indexing/test_belief_extractor.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

def test_belief_extractor_returns_consumer_beliefs():
    from ripple.activities.indexing.belief_extractor import BeliefExtractorActivity
    from ripple.rib.graph.schema import FieldNode, TransportKind
    import asyncio

    field = FieldNode(
        fqn="vets-service.ownerPhone",
        name="ownerPhone",
        producer_service="vets-service",
        transport=TransportKind.REST,
        endpoint_or_topic="/api/vets",
        field_path="owner.phone",
        declared_type="string",
        nullable=False,
    )

    mock_graph = AsyncMock()
    mock_graph.find_symbol.return_value = [{"file": "src/PetCard.tsx", "line": 42, "snippet": "owner.ownerPhone"}]
    mock_graph.get_context.return_value = "const phone = owner.ownerPhone;\nif (!phone) return null;"
    mock_graph.get_test_assertions.return_value = []

    mock_llm = AsyncMock()
    mock_llm.complete_json.return_value = '{"assumed_unit": null, "assumed_type": "string", "assumed_nullable": true, "assumed_format": null, "inferred_constraints": [], "confidence": 0.85}'

    activity = BeliefExtractorActivity(graph=mock_graph, llm=mock_llm)

    result = asyncio.run(activity.execute({
        "fields": [field.model_dump()],
        "consumer_service": "react-frontend",
        "graph_db_path": "/tmp/fake.db",
    }))

    assert result["beliefs_extracted"] == 1
    assert result["beliefs"][0]["consumer_service"] == "react-frontend"
    assert result["beliefs"][0]["confidence"] == 0.85
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/activities/indexing/test_belief_extractor.py -v
```

Expected: `ModuleNotFoundError: No module named 'ripple.activities.indexing.belief_extractor'`

- [ ] **Step 3: Implement BeliefExtractorActivity**

Create `ripple/activities/indexing/belief_extractor.py`:

```python
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from temporalio import activity

from ripple.graph_client import GraphClient
from ripple.llm_client import LLMClient
from ripple.rib.graph.schema import ConsumerBelief, FieldNode

logger = logging.getLogger(__name__)

_BELIEF_SYSTEM = """You infer how a consumer service uses an API field from exact code snippets and test assertions.
Return JSON: {"assumed_unit": string|null, "assumed_type": string|null, "assumed_nullable": bool|null, "assumed_format": string|null, "inferred_constraints": [string], "confidence": float}
Base answers only on what the snippets show. Use null when unknown. confidence 0.0-1.0."""

_LLM_CONCURRENCY = 10


class BeliefExtractorActivity:
    def __init__(
        self,
        graph: Optional[GraphClient] = None,
        llm: Optional[LLMClient] = None,
    ):
        self._graph = graph
        self._llm = llm or LLMClient(model="claude-haiku-4-5-20251001")

    @activity.defn(name="belief_extractor")
    async def execute(self, payload: dict) -> dict:
        fields_raw: list[dict] = payload["fields"]
        consumer_service: str = payload["consumer_service"]
        graph_db_path: str = payload["graph_db_path"]

        fields = [FieldNode.model_validate(f) for f in fields_raw]
        graph = self._graph or GraphClient(db_path=graph_db_path)

        logger.info(
            "belief_extractor start consumer=%s fields=%d",
            consumer_service, len(fields),
        )

        sem = asyncio.Semaphore(_LLM_CONCURRENCY)

        async def extract_one(field: FieldNode) -> Optional[ConsumerBelief]:
            async with sem:
                return await self._extract_belief_for_field(field, consumer_service, graph)

        beliefs = await asyncio.gather(*[extract_one(f) for f in fields])
        valid = [b for b in beliefs if b is not None]

        logger.info(
            "belief_extractor done consumer=%s beliefs=%d",
            consumer_service, len(valid),
        )
        return {
            "beliefs_extracted": len(valid),
            "beliefs": [b.model_dump(mode="json") for b in valid],
        }

    async def _extract_belief_for_field(
        self, field: FieldNode, consumer_service: str, graph: GraphClient
    ) -> Optional[ConsumerBelief]:
        # Step 1: Graph queries — zero LLM tokens
        locations = await graph.find_symbol(field.name)
        if not locations:
            return None

        # Step 2: Gather 15-line snippets — zero LLM tokens
        snippets = []
        for loc in locations[:10]:  # cap at 10 locations per field
            snippet = await graph.get_context(loc["file"], loc["line"], 15)
            if snippet:
                snippets.append(f"# {loc['file']}:{loc['line']}\n{snippet}")

        # Step 3: Test assertions — zero LLM tokens
        test_assertions = await graph.get_test_assertions(field.name)
        test_lines = [a.get("assertion_code", "") for a in test_assertions[:5]]

        if not snippets and not test_lines:
            return None

        # Step 4: Single Haiku call on targeted snippets — ~200 tokens vs 3000 for whole file
        prompt = f"""Field: {field.fqn}
Declared type: {field.declared_type}, nullable: {field.nullable}

Code snippets using this field in consumer {consumer_service}:
{chr(10).join(snippets[:5])}

Test assertions about this field:
{chr(10).join(test_lines)}

What does this consumer assume about the field?"""

        try:
            raw = await self._llm.complete_json(prompt, system=_BELIEF_SYSTEM, max_tokens=384)
            parsed = json.loads(raw)
        except Exception as e:
            logger.warning("belief_extractor llm parse error field=%s err=%s", field.fqn, e)
            parsed = {}

        return ConsumerBelief(
            consumer_service=consumer_service,
            field_fqn=field.fqn,
            assumed_unit=parsed.get("assumed_unit"),
            assumed_type=parsed.get("assumed_type", field.declared_type),
            assumed_nullable=parsed.get("assumed_nullable", field.nullable),
            assumed_format=parsed.get("assumed_format"),
            inferred_constraints=parsed.get("inferred_constraints", []),
            usage_expressions=[loc.get("snippet", "") for loc in locations[:5]],
            confidence=float(parsed.get("confidence", 0.5)),
            extracted_at=datetime.now(timezone.utc),
        )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/activities/indexing/test_belief_extractor.py -v
```

Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add ripple/activities/indexing/belief_extractor.py tests/activities/indexing/test_belief_extractor.py
git commit -m "feat: add BeliefExtractorActivity using graph queries + targeted Haiku"
```

---

## Task 6: SchemaParserActivity — class-based wrapper

**Files:**
- Create: `ripple/activities/indexing/schema_parser.py`

- [ ] **Step 1: Write the failing test**

Create `tests/activities/indexing/test_schema_parser.py`:

```python
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

def test_schema_parser_activity_calls_parse_openapi(tmp_path):
    from ripple.activities.indexing.schema_parser import SchemaParserActivity
    from ripple.rib.graph.schema import FieldNode, TransportKind
    import asyncio

    mock_field = FieldNode(
        fqn="svc.field",
        name="field",
        producer_service="svc",
        transport=TransportKind.REST,
        endpoint_or_topic="/api",
        field_path="field",
        declared_type="string",
        nullable=False,
    )

    fake_openapi = tmp_path / "openapi.yaml"
    fake_openapi.write_text("openapi: '3.0.0'")

    with patch("ripple.activities.indexing.schema_parser.parse_openapi", return_value=[mock_field]):
        activity = SchemaParserActivity()
        result = asyncio.run(activity.execute({
            "workspace": str(tmp_path),
            "service_name": "svc",
            "openapi_path": "openapi.yaml",
        }))

    assert result["fields_count"] == 1
    assert result["fields"][0]["name"] == "field"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/activities/indexing/test_schema_parser.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement SchemaParserActivity**

Create `ripple/activities/indexing/schema_parser.py`:

```python
from __future__ import annotations

import logging
from pathlib import Path

from temporalio import activity

from ripple.rib.indexer.contract_parsers.openapi_parser import parse_openapi

logger = logging.getLogger(__name__)


class SchemaParserActivity:
    @activity.defn(name="schema_parser")
    async def execute(self, payload: dict) -> dict:
        workspace = Path(payload["workspace"])
        service_name: str = payload["service_name"]
        openapi_path: str = payload.get("openapi_path", "openapi.yaml")

        spec_file = workspace / openapi_path
        logger.info("schema_parser start service=%s spec=%s", service_name, spec_file)

        if not spec_file.exists():
            logger.warning("schema_parser spec missing service=%s path=%s", service_name, spec_file)
            return {"fields_count": 0, "fields": [], "service_name": service_name}

        fields = parse_openapi(spec_file, service_name)
        logger.info("schema_parser done service=%s fields=%d", service_name, len(fields))

        return {
            "fields_count": len(fields),
            "fields": [f.model_dump() for f in fields],
            "service_name": service_name,
        }
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/activities/indexing/test_schema_parser.py -v
```

Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add ripple/activities/indexing/schema_parser.py tests/activities/indexing/test_schema_parser.py
git commit -m "feat: add SchemaParserActivity (class-based OpenAPI parser)"
```

---

## Task 7: DisagreementDetectorActivity — class-based, Sonnet for low-confidence

**Files:**
- Create: `ripple/activities/indexing/disagreement_detector.py`

- [ ] **Step 1: Write the failing test**

Create `tests/activities/indexing/test_disagreement_detector.py`:

```python
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

def test_disagreement_detector_detects_type_mismatch():
    from ripple.activities.indexing.disagreement_detector import DisagreementDetectorActivity
    from ripple.rib.graph.schema import (
        FieldNode, TransportKind, ConsumerBelief, DisagreementKind
    )
    import asyncio

    field = FieldNode(
        fqn="svc.amount",
        name="amount",
        producer_service="svc",
        transport=TransportKind.REST,
        endpoint_or_topic="/api",
        field_path="amount",
        declared_type="integer",
        nullable=False,
    )
    belief = ConsumerBelief(
        consumer_service="consumer",
        field_fqn="svc.amount",
        assumed_unit="dollars",
        assumed_type="string",
        assumed_nullable=False,
        assumed_format=None,
        inferred_constraints=[],
        usage_expressions=["String.valueOf(amount)"],
        confidence=0.9,
        extracted_at=datetime.now(timezone.utc),
    )

    activity = DisagreementDetectorActivity()
    result = asyncio.run(activity.execute({
        "field": field.model_dump(),
        "belief": belief.model_dump(mode="json"),
    }))

    assert result["disagreements_count"] >= 1
    kinds = [d["kind"] for d in result["disagreements"]]
    assert "TYPE_CHANGED" in kinds
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/activities/indexing/test_disagreement_detector.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement DisagreementDetectorActivity**

Create `ripple/activities/indexing/disagreement_detector.py`:

```python
from __future__ import annotations

import logging

from temporalio import activity

from ripple.llm_client import LLMClient
from ripple.rib.enricher.disagreement_detector import detect_disagreements
from ripple.rib.graph.schema import ConsumerBelief, Disagreement, FieldNode

logger = logging.getLogger(__name__)

_CONFIDENCE_THRESHOLD = 0.7


class DisagreementDetectorActivity:
    def __init__(self, llm: LLMClient | None = None):
        self._llm = llm or LLMClient(model="claude-sonnet-4-6")

    @activity.defn(name="disagreement_detector")
    async def execute(self, payload: dict) -> dict:
        field = FieldNode.model_validate(payload["field"])
        belief = ConsumerBelief.model_validate(payload["belief"])

        logger.info(
            "disagreement_detector start field=%s consumer=%s belief_confidence=%.2f",
            field.fqn, belief.consumer_service, belief.confidence,
        )

        # Layer 1: fast rules-based detection (no LLM)
        disagreements: list[Disagreement] = detect_disagreements(field, None, belief)

        # Layer 2: if belief confidence is low, use Sonnet for deep analysis
        if belief.confidence < _CONFIDENCE_THRESHOLD and belief.usage_expressions:
            llm_disagreements = await self._llm_detect(field, belief)
            existing_kinds = {d.kind for d in disagreements}
            for d in llm_disagreements:
                if d.kind not in existing_kinds:
                    disagreements.append(d)

        logger.info(
            "disagreement_detector done field=%s consumer=%s disagreements=%d",
            field.fqn, belief.consumer_service, len(disagreements),
        )

        return {
            "disagreements_count": len(disagreements),
            "disagreements": [d.model_dump(mode="json") for d in disagreements],
        }

    async def _llm_detect(self, field: FieldNode, belief: ConsumerBelief) -> list[Disagreement]:
        from datetime import datetime, timezone
        from ripple.rib.graph.schema import DisagreementKind, Severity, DisagreementSource
        import json

        prompt = f"""Analyze this API field contract vs consumer usage.
Field: {field.fqn}
Declared: type={field.declared_type}, nullable={field.nullable}, constraints={[c.model_dump() for c in field.constraints]}
Consumer assumes: type={belief.assumed_type}, unit={belief.assumed_unit}, nullable={belief.assumed_nullable}
Consumer code: {', '.join(belief.usage_expressions[:3])}

List disagreements as JSON array: [{{"kind": "TYPE_CHANGED|UNIT_MISMATCH|NULLABLE_CHANGED|BEHAVIORAL_CHANGE|...", "producer_says": "...", "consumer_assumes": "...", "severity": "CRITICAL|HIGH|MEDIUM|LOW", "explanation": "..."}}]
Return [] if no disagreements."""

        try:
            raw = await self._llm.complete_json(prompt, max_tokens=500)
            items = json.loads(raw)
            now = datetime.now(timezone.utc)
            result = []
            for item in (items if isinstance(items, list) else []):
                try:
                    result.append(Disagreement(
                        field_fqn=field.fqn,
                        consumer_service=belief.consumer_service,
                        kind=DisagreementKind(item["kind"]),
                        producer_says=item.get("producer_says", ""),
                        consumer_assumes=item.get("consumer_assumes", ""),
                        severity=Severity(item.get("severity", "MEDIUM")),
                        explanation=item.get("explanation", ""),
                        detected_at=now,
                        source=DisagreementSource.LLM,
                    ))
                except Exception:
                    continue
            return result
        except Exception as e:
            logger.warning("disagreement_detector llm failed field=%s err=%s", field.fqn, e)
            return []
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/activities/indexing/test_disagreement_detector.py -v
```

Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add ripple/activities/indexing/disagreement_detector.py tests/activities/indexing/test_disagreement_detector.py
git commit -m "feat: add DisagreementDetectorActivity (rules + Sonnet for low-confidence)"
```

---

## Task 8: IndexServiceWorkflowV2 — fine-grained pipeline

**Files:**
- Create: `ripple/workflows/index_service_v2.py`

This replaces `IngestServiceWorkflow`. Activities run in the right order: SchemaParser → GraphBuild (parallel) → BeliefExtractor (per consumer, parallel) → DisagreementDetector (per field+consumer, parallel).

- [ ] **Step 1: Write the failing test**

Create `tests/workflows/test_index_service_v2.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch

def test_index_service_workflow_v2_imports():
    from ripple.workflows.index_service_v2 import IndexServiceWorkflowV2
    assert IndexServiceWorkflowV2 is not None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/workflows/test_index_service_v2.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement IndexServiceWorkflowV2**

Create `ripple/workflows/index_service_v2.py`:

```python
from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from ripple.activities.git_activities import cleanup_workspace_activity, clone_repo_activity
    from ripple.activities.indexing.schema_parser import SchemaParserActivity
    from ripple.activities.indexing.graph_build import GraphBuildActivity
    from ripple.activities.indexing.belief_extractor import BeliefExtractorActivity
    from ripple.activities.indexing.disagreement_detector import DisagreementDetectorActivity
    from ripple.rib.graph.schema import ServiceRole, ServiceSpec

IO_RETRY = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=2))
LLM_RETRY = RetryPolicy(maximum_attempts=2, initial_interval=timedelta(seconds=10))


@workflow.defn(name="IndexServiceWorkflowV2")
class IndexServiceWorkflowV2:
    """
    Fine-grained indexing pipeline (replaces IngestServiceWorkflow):
    1. Clone repo
    2. SchemaParserActivity — parse OpenAPI, extract FieldNodes (no LLM)
    3. GraphBuildActivity — run codebase-memory-mcp, build symbol graph (no LLM)
    4. BeliefExtractorActivity — graph queries + Haiku per field (parallel, cheap)
    5. DisagreementDetectorActivity — rules + Sonnet for low-confidence (parallel)
    """

    @workflow.run
    async def run(self, service: dict, workflow_run_id: str) -> dict:
        spec = ServiceSpec.model_validate(service)
        service_name = spec.service_name or _name_from_url(spec.repo_url)
        roles = {role.value for role in spec.roles}
        counts: dict = {}

        # Activity 1: Clone
        clone_result = await workflow.execute_activity(
            clone_repo_activity,
            args=[spec.repo_url, workflow_run_id],
            task_queue="rib-io",
            start_to_close_timeout=timedelta(minutes=15),
            retry_policy=IO_RETRY,
        )
        workspace = clone_result["workspace"]

        try:
            is_producer = ServiceRole.PRODUCER.value in roles
            is_consumer = ServiceRole.CONSUMER.value in roles

            if is_producer:
                # Activity 2a: Parse OpenAPI schema (no LLM, fast)
                schema_result = await workflow.execute_activity(
                    SchemaParserActivity.execute,
                    args=[{
                        "workspace": workspace,
                        "service_name": service_name,
                        "openapi_path": spec.openapi_path,
                    }],
                    task_queue="rib-cpu",
                    start_to_close_timeout=timedelta(minutes=5),
                    retry_policy=IO_RETRY,
                )
                counts["fields"] = schema_result["fields_count"]

            # Activity 3: Build symbol graph (no LLM, runs for all roles)
            graph_result = await workflow.execute_activity(
                GraphBuildActivity.execute,
                args=[{"workspace": workspace}],
                task_queue="rib-cpu",
                start_to_close_timeout=timedelta(minutes=10),
                retry_policy=IO_RETRY,
            )
            graph_db_path = graph_result.get("graph_db_path", "")
            counts["graph_built"] = int(graph_result.get("success", False))

            if is_consumer and graph_db_path:
                # Activity 4: Extract beliefs using graph (Haiku, parallel per field)
                # Fields come from the store (already persisted by producer indexing)
                belief_result = await workflow.execute_activity(
                    BeliefExtractorActivity.execute,
                    args=[{
                        "fields": schema_result.get("fields", []) if is_producer else [],
                        "consumer_service": service_name,
                        "graph_db_path": graph_db_path,
                    }],
                    task_queue="rib-llm",
                    start_to_close_timeout=timedelta(minutes=20),
                    retry_policy=LLM_RETRY,
                )
                counts["beliefs"] = belief_result["beliefs_extracted"]

                # Activity 5: Detect disagreements (rules + Sonnet for low-confidence)
                disagreement_count = 0
                for belief_dict in belief_result.get("beliefs", []):
                    # Run DisagreementDetectorActivity for each belief in parallel would be
                    # a child workflow pattern for large sets — for now sequential is fine for demo
                    field_fqn = belief_dict["field_fqn"]
                    # Get field from schema result
                    field_dict = next(
                        (f for f in schema_result.get("fields", []) if f["fqn"] == field_fqn),
                        None,
                    )
                    if not field_dict:
                        continue
                    d_result = await workflow.execute_activity(
                        DisagreementDetectorActivity.execute,
                        args=[{"field": field_dict, "belief": belief_dict}],
                        task_queue="rib-llm",
                        start_to_close_timeout=timedelta(minutes=5),
                        retry_policy=LLM_RETRY,
                    )
                    disagreement_count += d_result["disagreements_count"]
                counts["disagreements"] = disagreement_count

        finally:
            await workflow.execute_activity(
                cleanup_workspace_activity,
                args=[workspace],
                task_queue="rib-io",
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=IO_RETRY,
            )

        return {"service_name": service_name, "counts": counts}


def _name_from_url(repo_url: str) -> str:
    name = repo_url.rstrip("/").rsplit("/", 1)[-1]
    return name[:-4] if name.endswith(".git") else name
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/workflows/test_index_service_v2.py -v
```

Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add ripple/workflows/index_service_v2.py tests/workflows/test_index_service_v2.py
git commit -m "feat: add IndexServiceWorkflowV2 (fine-grained graph-based pipeline)"
```

---

## Task 9: MechanicalFixActivity — Haiku direct API (Tier 1)

**Files:**
- Create: `ripple/activities/fixing/__init__.py`
- Create: `ripple/activities/fixing/mechanical_fix.py`

Replaces `run_claude_code_fix_activity` for mechanical changes. Single Haiku call on the exact snippet from the graph. Target latency: 3–8 seconds vs 2–10 minutes.

- [ ] **Step 1: Write the failing test**

Create `tests/activities/fixing/test_mechanical_fix.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch

def test_mechanical_fix_activity_returns_fixed_code():
    from ripple.activities.fixing.mechanical_fix import MechanicalFixActivity
    import asyncio

    mock_llm = AsyncMock()
    mock_llm.complete.return_value = "const phone = owner.ownerContact.phone;\nif (!phone) return null;"

    activity = MechanicalFixActivity(llm=mock_llm)
    result = asyncio.run(activity.execute({
        "field_change": {
            "field_name": "ownerPhone",
            "change_type": "FIELD_RENAMED",
            "old_description": "direct phone field",
            "new_description": "nested in ownerContact.phone",
        },
        "location": {"file": "src/PetCard.tsx", "line": 42},
        "snippet": "const phone = owner.ownerPhone;\nif (!phone) return null;",
    }))

    assert result["success"] is True
    assert "ownerContact.phone" in result["fixed_code"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/activities/fixing/test_mechanical_fix.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Create the fixing package**

Create `ripple/activities/fixing/__init__.py`:
```python
```
(empty file)

- [ ] **Step 4: Implement MechanicalFixActivity**

Create `ripple/activities/fixing/mechanical_fix.py`:

```python
from __future__ import annotations

import logging
from typing import Optional

from temporalio import activity

from ripple.llm_client import LLMClient

logger = logging.getLogger(__name__)


class MechanicalFixActivity:
    """
    Tier 1 fix: single Haiku API call on the exact snippet from the graph.
    Use when: graph provides exact file + line + snippet, change is mechanical.
    Latency: 3–8 seconds.
    """

    def __init__(self, llm: Optional[LLMClient] = None):
        self._llm = llm or LLMClient(model="claude-haiku-4-5-20251001")

    @activity.defn(name="mechanical_fix")
    async def execute(self, payload: dict) -> dict:
        field_change: dict = payload["field_change"]
        location: dict = payload["location"]
        snippet: str = payload["snippet"]

        field_name = field_change.get("field_name", "")
        change_type = field_change.get("change_type", "")
        old_desc = field_change.get("old_description", "")
        new_desc = field_change.get("new_description", "")

        logger.info(
            "mechanical_fix start field=%s change=%s file=%s line=%d",
            field_name, change_type, location.get("file"), location.get("line"),
        )

        prompt = f"""Fix this exact code snippet. Minimal change only.

Breaking change: {field_name} — {change_type}
Was: {old_desc}
Now: {new_desc}

Code at {location.get('file')}:{location.get('line')}:
{snippet}

Return ONLY the fixed code block. No explanation. No markdown fences. Touch only what's broken."""

        try:
            fixed_code = await self._llm.complete(prompt, max_tokens=1000)
            success = bool(fixed_code.strip())
        except Exception as e:
            logger.error("mechanical_fix llm error field=%s err=%s", field_name, e)
            return {"success": False, "fixed_code": "", "error": str(e)}

        logger.info("mechanical_fix done field=%s success=%s", field_name, success)
        return {
            "success": success,
            "fixed_code": fixed_code.strip(),
            "file": location.get("file"),
            "line": location.get("line"),
        }
```

- [ ] **Step 5: Run test to verify it passes**

```bash
python -m pytest tests/activities/fixing/test_mechanical_fix.py -v
```

Expected: `PASSED`

- [ ] **Step 6: Commit**

```bash
git add ripple/activities/fixing/__init__.py ripple/activities/fixing/mechanical_fix.py tests/activities/fixing/test_mechanical_fix.py
git commit -m "feat: add MechanicalFixActivity (Tier 1 — Haiku direct API, 3-8s latency)"
```

---

## Task 10: SemanticFixActivity — Sonnet direct API with human decision (Tier 2)

**Files:**
- Create: `ripple/activities/fixing/semantic_fix.py`

- [ ] **Step 1: Write the failing test**

Create `tests/activities/fixing/test_semantic_fix.py`:

```python
import pytest
from unittest.mock import AsyncMock

def test_semantic_fix_applies_human_decision():
    from ripple.activities.fixing.semantic_fix import SemanticFixActivity
    import asyncio

    mock_llm = AsyncMock()
    mock_llm.complete.return_value = "const fee = consultationFee / 100;"

    activity = SemanticFixActivity(llm=mock_llm)
    result = asyncio.run(activity.execute({
        "field_change": {
            "field_name": "consultationFee",
            "change_type": "UNIT_MISMATCH",
            "old_description": "cents (integer)",
            "new_description": "dollars (decimal)",
        },
        "location": {"file": "src/billing.js", "line": 88},
        "snippet": "const fee = consultationFee;",
        "human_decision": "Divide by 100 at read time",
    }))

    assert result["success"] is True
    assert "100" in result["fixed_code"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/activities/fixing/test_semantic_fix.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement SemanticFixActivity**

Create `ripple/activities/fixing/semantic_fix.py`:

```python
from __future__ import annotations

import logging
from typing import Optional

from temporalio import activity

from ripple.llm_client import LLMClient

logger = logging.getLogger(__name__)


class SemanticFixActivity:
    """
    Tier 2 fix: single Sonnet API call with the human's interrupt decision as a hard constraint.
    Use when: change requires semantic judgment, human has answered the interrupt card.
    Latency: 15–30 seconds.
    """

    def __init__(self, llm: Optional[LLMClient] = None):
        self._llm = llm or LLMClient(model="claude-sonnet-4-6")

    @activity.defn(name="semantic_fix")
    async def execute(self, payload: dict) -> dict:
        field_change: dict = payload["field_change"]
        location: dict = payload["location"]
        snippet: str = payload["snippet"]
        human_decision: str = payload["human_decision"]

        field_name = field_change.get("field_name", "")
        change_type = field_change.get("change_type", "")
        old_desc = field_change.get("old_description", "")
        new_desc = field_change.get("new_description", "")

        logger.info(
            "semantic_fix start field=%s change=%s decision=%s",
            field_name, change_type, human_decision[:50],
        )

        prompt = f"""Fix this code. The human has decided: {human_decision}

Breaking change: {field_name} — {change_type}
Was: {old_desc}
Now: {new_desc}

Code at {location.get('file')}:{location.get('line')}:
{snippet}

Apply exactly the decision above. Minimal change only. Return ONLY the fixed code. No markdown fences."""

        try:
            fixed_code = await self._llm.complete(prompt, max_tokens=2000)
            success = bool(fixed_code.strip())
        except Exception as e:
            logger.error("semantic_fix llm error field=%s err=%s", field_name, e)
            return {"success": False, "fixed_code": "", "error": str(e)}

        logger.info("semantic_fix done field=%s success=%s", field_name, success)
        return {
            "success": success,
            "fixed_code": fixed_code.strip(),
            "file": location.get("file"),
            "line": location.get("line"),
            "human_decision": human_decision,
        }
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/activities/fixing/test_semantic_fix.py -v
```

Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add ripple/activities/fixing/semantic_fix.py tests/activities/fixing/test_semantic_fix.py
git commit -m "feat: add SemanticFixActivity (Tier 2 — Sonnet with human decision, 15-30s)"
```

---

## Task 11: Interrupt card API — POST/GET interrupts + Temporal signal

**Files:**
- Create: `ripple/rib/api/interrupts.py`
- Modify: `ripple/rib/api/server.py`
- Modify: `ripple/rib/graph/schema.py` (add InterruptCard model)

- [ ] **Step 1: Add InterruptCard model to schema.py**

Open `ripple/rib/graph/schema.py` and append these models at the end:

```python
class InterruptStatus(str, Enum):
    PENDING = "PENDING"
    ANSWERED = "ANSWERED"
    EXPIRED = "EXPIRED"


class InterruptCard(BaseModel):
    id: str
    workflow_id: str
    consumer_service: str
    field_fqn: str
    change_summary: str          # e.g. "consultationFee changed units: cents → dollars"
    question: str                # the focused single question shown on the interrupt card
    options: list[str]           # 2-4 option strings
    status: InterruptStatus = InterruptStatus.PENDING
    answer: Optional[str] = None
    created_at: datetime
    answered_at: Optional[datetime] = None


class InterruptAnswer(BaseModel):
    answer: str
```

- [ ] **Step 2: Write the failing test**

Create `tests/api/test_interrupts.py`:

```python
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

def test_list_interrupts_returns_empty_initially():
    # Temporarily import with mocked store
    with patch("ripple.rib.api.interrupts._interrupt_store", {}):
        from ripple.rib.api.interrupts import router
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)
        response = client.get("/api/interrupts")
        assert response.status_code == 200
        assert response.json() == []

def test_post_interrupt_creates_card():
    from ripple.rib.api.interrupts import router, _interrupt_store
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    response = client.post("/api/interrupts", json={
        "id": "int-001",
        "workflow_id": "wf-123",
        "consumer_service": "api-gateway",
        "field_fqn": "vets-service.consultationFee",
        "change_summary": "consultationFee changed units: cents → dollars",
        "question": "How should api-gateway handle existing values?",
        "options": ["Divide by 100 at read time", "Update billing to work with dollars", "I'll handle this manually"],
        "created_at": "2026-05-26T12:00:00Z",
    })
    assert response.status_code == 200
    assert response.json()["id"] == "int-001"
```

- [ ] **Step 3: Run test to verify it fails**

```bash
python -m pytest tests/api/test_interrupts.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 4: Implement interrupt router**

Create `ripple/rib/api/interrupts.py`:

```python
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException

from ripple.rib.graph.schema import InterruptAnswer, InterruptCard, InterruptStatus

logger = logging.getLogger(__name__)
router = APIRouter()

# In-memory store — persists within a worker process, fine for hackathon demo.
# Replace with Postgres table (interrupt_cards) post-hackathon.
_interrupt_store: dict[str, InterruptCard] = {}


@router.get("/api/interrupts", response_model=list[InterruptCard])
def list_interrupts(status: Optional[str] = None) -> list[InterruptCard]:
    cards = list(_interrupt_store.values())
    if status:
        cards = [c for c in cards if c.status.value == status.upper()]
    cards.sort(key=lambda c: c.created_at, reverse=True)
    return cards


@router.post("/api/interrupts", response_model=InterruptCard)
def create_interrupt(card: InterruptCard) -> InterruptCard:
    _interrupt_store[card.id] = card
    logger.info("interrupt created id=%s consumer=%s", card.id, card.consumer_service)
    return card


@router.get("/api/interrupts/{interrupt_id}", response_model=InterruptCard)
def get_interrupt(interrupt_id: str) -> InterruptCard:
    card = _interrupt_store.get(interrupt_id)
    if not card:
        raise HTTPException(status_code=404, detail=f"Interrupt {interrupt_id} not found")
    return card


@router.post("/api/interrupts/{interrupt_id}/answer", response_model=InterruptCard)
async def answer_interrupt(interrupt_id: str, body: InterruptAnswer) -> InterruptCard:
    card = _interrupt_store.get(interrupt_id)
    if not card:
        raise HTTPException(status_code=404, detail=f"Interrupt {interrupt_id} not found")
    if card.status != InterruptStatus.PENDING:
        raise HTTPException(status_code=409, detail=f"Interrupt already {card.status.value}")

    card.answer = body.answer
    card.answered_at = datetime.now(timezone.utc)
    card.status = InterruptStatus.ANSWERED
    _interrupt_store[interrupt_id] = card

    # Signal the waiting Temporal workflow to unblock
    await _signal_workflow(card.workflow_id, body.answer)

    logger.info("interrupt answered id=%s answer=%s", interrupt_id, body.answer[:50])
    return card


async def _signal_workflow(workflow_id: str, answer: str) -> None:
    from ripple.temporal_client import get_temporal_client
    try:
        client = await get_temporal_client()
        handle = client.get_workflow_handle(workflow_id)
        await handle.signal("interrupt_answered", answer)
        logger.info("temporal signal sent workflow_id=%s", workflow_id)
    except Exception as e:
        logger.error("temporal signal failed workflow_id=%s err=%s", workflow_id, e)
```

- [ ] **Step 5: Wire router into server.py**

Open `ripple/rib/api/server.py` and add after the existing imports (around line 15):

```python
from ripple.rib.api.interrupts import router as interrupts_router
```

And after `app = FastAPI(...)` (around line 30):

```python
app.include_router(interrupts_router)
```

- [ ] **Step 6: Run test to verify it passes**

```bash
python -m pytest tests/api/test_interrupts.py -v
```

Expected: `PASSED`

- [ ] **Step 7: Commit**

```bash
git add ripple/rib/api/interrupts.py ripple/rib/api/server.py ripple/rib/graph/schema.py tests/api/test_interrupts.py
git commit -m "feat: add interrupt card API (POST/GET /api/interrupts, /answer with Temporal signal)"
```

---

## Task 12: Wire worker.py to new activities + workflows

**Files:**
- Modify: `ripple/worker.py`

- [ ] **Step 1: Update worker.py imports and registrations**

Open `ripple/worker.py` and make these changes:

Add these imports after the existing activity imports:

```python
from ripple.activities.indexing.schema_parser import SchemaParserActivity
from ripple.activities.indexing.graph_build import GraphBuildActivity
from ripple.activities.indexing.belief_extractor import BeliefExtractorActivity
from ripple.activities.indexing.disagreement_detector import DisagreementDetectorActivity
from ripple.activities.fixing.mechanical_fix import MechanicalFixActivity
from ripple.activities.fixing.semantic_fix import SemanticFixActivity
from ripple.workflows.index_service_v2 import IndexServiceWorkflowV2
```

Add `IndexServiceWorkflowV2` to the workflows list in the `worker` (rib queue):

```python
workflows=[IngestEcosystemWorkflow, IngestServiceWorkflow, IndexServiceWorkflowV2, AnalyzePRWorkflow, AutoFixConsumerWorkflow],
```

Add new activities to the `llm_worker` (rib-llm queue):

```python
activities=[
    index_producer_activity,
    parse_pr_diff_activity,
    assess_consumer_impact_activity,
    BeliefExtractorActivity().execute,
    DisagreementDetectorActivity().execute,
    SemanticFixActivity().execute,
],
```

Add new activities to the `cpu_worker` (rib-cpu queue):

```python
activities=[
    index_consumer_activity,
    run_claude_code_fix_activity,
    SchemaParserActivity().execute,
    GraphBuildActivity().execute,
    MechanicalFixActivity().execute,
],
```

- [ ] **Step 2: Verify worker starts without errors**

```bash
cd /path/to/ai-works-hackathon
python -c "import ripple.worker; print('imports ok')"
```

Expected: `imports ok`

- [ ] **Step 3: Commit**

```bash
git add ripple/worker.py
git commit -m "feat: register new indexing + fixing activities in Temporal worker"
```

---

## Task 13: End-to-end smoke test

This verifies the full pipeline works before the demo.

- [ ] **Step 1: Start all services**

In separate terminals (or tmux panes):

```bash
# Terminal 1: Temporal dev server
temporal server start-dev

# Terminal 2: Backend API
cd ripple && uvicorn ripple.rib.api.server:app --reload --port 8000

# Terminal 3: Temporal worker
cd ripple && python -m ripple.worker

# Terminal 4: Next.js dashboard
cd dashboard && nvm use 20.19.0 && npm run dev
```

- [ ] **Step 2: Trigger IndexServiceWorkflowV2 with a test repo**

```bash
curl -X POST http://localhost:8000/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "services": [{
      "repo_url": "https://github.com/spring-petclinic/spring-petclinic-microservices",
      "service_name": "petclinic-demo",
      "roles": ["producer", "consumer"],
      "openapi_path": "spring-petclinic-api-gateway/src/main/resources/static/swagger-ui/vets-service.yaml"
    }],
    "tenant_id": "demo"
  }'
```

Expected: JSON response with `workflow_id`. Copy the `workflow_id`.

- [ ] **Step 3: Check workflow status**

```bash
curl http://localhost:8000/ingest/<workflow_id>
```

Expected: `status: RUNNING` then `status: COMPLETED` with non-zero counts.

- [ ] **Step 4: Verify fields were indexed**

```bash
curl http://localhost:8000/fields | python3 -m json.tool | head -50
```

Expected: JSON array of FieldNode objects with field names from the OpenAPI spec.

- [ ] **Step 5: Verify interrupt card API works**

```bash
# Create a test interrupt card
curl -X POST http://localhost:8000/api/interrupts \
  -H "Content-Type: application/json" \
  -d '{
    "id": "test-001",
    "workflow_id": "fake-wf",
    "consumer_service": "api-gateway",
    "field_fqn": "vets-service.consultationFee",
    "change_summary": "consultationFee changed units",
    "question": "How should api-gateway handle existing values?",
    "options": ["Divide by 100 at read time", "Update billing", "Manual"],
    "created_at": "2026-05-26T12:00:00Z"
  }'

# Verify it appears
curl http://localhost:8000/api/interrupts
```

Expected: interrupt card JSON with `status: PENDING`.

- [ ] **Step 6: Check dashboard shows data**

Open http://localhost:3000. Verify:
- Stats row shows non-zero field/service counts
- Ecosystem graph shows at least one node

- [ ] **Step 7: Commit smoke test notes**

```bash
git commit --allow-empty -m "chore: smoke test passed — graph pipeline + interrupt API working"
```

---

## Summary — What each task delivers

| Task | Delivers | Latency impact |
|---|---|---|
| 1 | litellm + mcp installed | Foundation |
| 2 | LLMClient — single model abstraction | Enables task routing |
| 3 | GraphBuildActivity — codebase-memory-mcp index | Replaces SCIP, 155 languages |
| 4 | GraphClient — MCP query wrapper | Enables graph-based lookup |
| 5 | BeliefExtractorActivity | 33–50x token reduction |
| 6 | SchemaParserActivity (class-based) | Clean activity boundary |
| 7 | DisagreementDetectorActivity | Low-confidence Sonnet escalation |
| 8 | IndexServiceWorkflowV2 | Fine-grained, auditable pipeline |
| 9 | MechanicalFixActivity (Haiku) | 3–8s vs 2–10min (Tier 1) |
| 10 | SemanticFixActivity (Sonnet) | 15–30s with human constraint (Tier 2) |
| 11 | Interrupt card API + Temporal signal | Dashboard ↔ workflow integration |
| 12 | Worker registration | All activities online |
| 13 | Smoke test | Demo readiness check |

**Estimated time: 3–4 days parallel, 5–6 days solo.**

---

## Environment Setup (for a fresh machine)

```bash
# Python
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Node (for codebase-memory-mcp)
nvm use 20.19.0
npm install -g @deus-data/codebase-memory-mcp

# Postgres (via Docker)
docker run -d --name ripple-pg \
  -e POSTGRES_PASSWORD=ripple \
  -e POSTGRES_DB=ripple \
  -p 5432:5432 postgres:16

# Temporal dev server
brew install temporal
temporal server start-dev   # in its own terminal

# Environment variables
export RIB_DATABASE_URL="postgresql+psycopg://postgres:ripple@localhost:5432/ripple"
export ANTHROPIC_API_KEY="<your key>"
export RIPPLE_GITHUB_TOKEN="<github token with repo read+write>"
export GITHUB_WEBHOOK_SECRET="<optional>"

# Run migrations
cd ripple && python -m ripple.rib.graph.postgres_store  # or however migrations are run

# Start backend
uvicorn ripple.rib.api.server:app --reload --port 8000

# Start worker
python -m ripple.worker

# Start dashboard
cd dashboard && npm run dev   # runs at localhost:3000
```
