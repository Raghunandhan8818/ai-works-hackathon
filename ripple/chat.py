"""
RIB Chat — query the Ripple Intelligence Backend knowledge graph via natural language.

Usage:
    python -m ripple.chat [--api-url http://localhost:8081]

The LLM never sees raw source code. It only has access to what RIB extracted:
  - field contracts (OpenAPI)
  - semantic profiles (LLM-enriched)
  - consumer beliefs (what each service assumes)
  - disagreements (where assumptions break contract)
  - SCIP symbols (code structure)
  - blast radius (who uses what, where)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap
import urllib.parse
from typing import Any

import anthropic
import requests

# ─── ANSI colours ─────────────────────────────────────────────────────────────

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"


def _c(color: str, text: str) -> str:
    if not sys.stdout.isatty():
        return text
    return f"{color}{text}{RESET}"


# ─── Tool definitions ─────────────────────────────────────────────────────────

TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_services",
        "description": (
            "List all producer services indexed in the knowledge graph, "
            "with field counts. Use this to understand what's been ingested."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "search_fields",
        "description": (
            "Search API contract fields by name keyword or list all fields. "
            "Returns field declarations (type, nullable, constraints) for one "
            "or all producer services. Use this to find a specific field FQN."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Substring to match against field name (case-insensitive). Leave empty to list all.",
                },
                "service": {
                    "type": "string",
                    "description": "Filter to a specific producer service name.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_field_profile",
        "description": (
            "Get the full field declaration AND its LLM-generated semantic profile "
            "(domain, unit, invariants, risk flags, evidence). "
            "Use the exact FQN from search_fields output."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "fqn": {
                    "type": "string",
                    "description": "Exact field FQN, e.g. 'user-service::REST::GET /users/{id}::response.200.rewardPoints'",
                }
            },
            "required": ["fqn"],
        },
    },
    {
        "name": "get_blast_radius",
        "description": (
            "For a given field FQN, show every consumer service that uses it: "
            "usage locations (file, line, SCIP symbol), inferred consumer beliefs, "
            "and any active semantic disagreements. "
            "This is the core cross-repo analysis tool."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "fqn": {
                    "type": "string",
                    "description": "Exact field FQN",
                }
            },
            "required": ["fqn"],
        },
    },
    {
        "name": "list_disagreements",
        "description": (
            "List all active semantic contract disagreements. "
            "Each disagreement captures: which field, which consumer, "
            "the disagreement kind (NULLABLE_CHANGED, TYPE_CHANGED, etc.), "
            "what the producer says vs what the consumer assumes, "
            "severity, and evidence from SCIP."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "field_fqn": {
                    "type": "string",
                    "description": "Optionally filter to a specific field FQN.",
                }
            },
            "required": [],
        },
    },
    {
        "name": "list_beliefs",
        "description": (
            "List consumer beliefs — what each service *assumes* about a field "
            "(assumed_type, assumed_nullable, assumed_unit, assumed_format, confidence). "
            "Beliefs are inferred from SCIP symbol usage and enriched by LLM."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "service": {
                    "type": "string",
                    "description": "Filter to a specific consumer service.",
                },
                "field_fqn": {
                    "type": "string",
                    "description": "Filter to a specific field FQN.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "search_symbols",
        "description": (
            "Search SCIP symbols (code entities) across indexed services. "
            "Symbols are classes, methods, fields extracted from source code. "
            "Use this to understand how a service implements its domain model."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Substring to match against symbol name or SCIP ID.",
                },
                "service": {
                    "type": "string",
                    "description": "Filter to a specific service.",
                },
            },
            "required": [],
        },
    },
]

# ─── Tool executor ─────────────────────────────────────────────────────────────


class RIBClient:
    def __init__(self, base_url: str) -> None:
        self.base = base_url.rstrip("/")

    def _get(self, path: str, params: dict[str, str] | None = None) -> Any:
        url = f"{self.base}{path}"
        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.ConnectionError:
            return {"error": f"Cannot connect to RIB API at {self.base}. Is it running?"}
        except requests.exceptions.HTTPError as e:
            return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}

    def list_services(self) -> Any:
        return self._get("/services")

    def search_fields(self, query: str = "", service: str = "") -> Any:
        params: dict[str, str] = {}
        if service:
            params["service"] = service
        fields = self._get("/fields", params)
        if isinstance(fields, list) and query:
            q = query.lower()
            fields = [f for f in fields if q in f.get("name", "").lower() or q in f.get("fqn", "").lower()]
        if isinstance(fields, list):
            # Return compact view to save tokens
            return [
                {
                    "fqn": f["fqn"],
                    "name": f["name"],
                    "producer_service": f["producer_service"],
                    "declared_type": f["declared_type"],
                    "nullable": f["nullable"],
                    "endpoint": f["endpoint_or_topic"],
                }
                for f in fields
            ]
        return fields

    def get_field_profile(self, fqn: str) -> Any:
        encoded = urllib.parse.quote(fqn, safe="")
        return self._get(f"/fields/{encoded}")

    def get_blast_radius(self, fqn: str) -> Any:
        encoded = urllib.parse.quote(fqn, safe="")
        return self._get(f"/blast-radius/{encoded}")

    def list_disagreements(self, field_fqn: str = "") -> Any:
        params: dict[str, str] = {}
        if field_fqn:
            params["field_fqn"] = field_fqn
        return self._get("/disagreements", params)

    def list_beliefs(self, service: str = "", field_fqn: str = "") -> Any:
        params: dict[str, str] = {}
        if service:
            params["service"] = service
        if field_fqn:
            params["field_fqn"] = field_fqn
        return self._get("/beliefs", params)

    def search_symbols(self, query: str = "", service: str = "") -> Any:
        params: dict[str, str] = {}
        if service:
            params["service"] = service
        if query:
            params["q"] = query
        return self._get("/symbols", params)


def execute_tool(name: str, inputs: dict[str, Any], client: RIBClient) -> str:
    if name == "list_services":
        result = client.list_services()
    elif name == "search_fields":
        result = client.search_fields(inputs.get("query", ""), inputs.get("service", ""))
    elif name == "get_field_profile":
        result = client.get_field_profile(inputs["fqn"])
    elif name == "get_blast_radius":
        result = client.get_blast_radius(inputs["fqn"])
    elif name == "list_disagreements":
        result = client.list_disagreements(inputs.get("field_fqn", ""))
    elif name == "list_beliefs":
        result = client.list_beliefs(inputs.get("service", ""), inputs.get("field_fqn", ""))
    elif name == "search_symbols":
        result = client.search_symbols(inputs.get("query", ""), inputs.get("service", ""))
    else:
        result = {"error": f"Unknown tool: {name}"}
    return json.dumps(result, default=str, indent=2)


# ─── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are RIB Assistant — an AI that answers questions about microservice API contracts \
using the Ripple Intelligence Backend knowledge graph.

You have NO access to raw source code. You work entirely from extracted knowledge:
- **Fields**: API contract fields declared in OpenAPI specs (type, nullable, constraints)
- **Semantic Profiles**: LLM-generated analysis of each field (domain, unit, invariants, risk flags)
- **Consumer Beliefs**: What each consumer service *assumes* about a field (inferred from SCIP code analysis)
- **Disagreements**: Where a consumer's belief contradicts the producer's contract declaration
- **SCIP Symbols**: Code entities (classes, methods) extracted from source code across repos
- **Blast Radius**: Which services use a field and how, with beliefs and disagreements per consumer

When answering:
1. Call tools to fetch the relevant data first — don't guess
2. Reference specific field FQNs, consumer names, and evidence from SCIP
3. Be direct about gaps: if a service has no beliefs (0 usages matched), say so
4. For disagreements, explain the real-world risk (e.g., NullPointerException, data corruption)
5. Format your answers clearly — use bullet points for lists, be concise

You are answering questions that span multiple repos without reading a single line of source code."""


# ─── Chat REPL ────────────────────────────────────────────────────────────────


def _wrap(text: str, width: int = 80, indent: str = "") -> str:
    lines = []
    for line in text.splitlines():
        if line.strip() == "":
            lines.append("")
        else:
            lines.extend(textwrap.wrap(line, width, subsequent_indent=indent))
    return "\n".join(lines)


def chat(api_url: str) -> None:
    api_key = ""
    if not api_key:
        print(_c(RED, "Error: ANTHROPIC_API_KEY not set. Source your .env first."))
        sys.exit(1)

    rib = RIBClient(api_url)
    llm = anthropic.Anthropic(api_key=api_key)

    # Verify API is reachable
    try:
        resp = requests.get(f"{api_url}/health", timeout=5)
        health = resp.json()
        db_status = health.get("database", "unknown")
    except Exception:
        print(_c(RED, f"Warning: RIB API not reachable at {api_url}. Tool calls will fail."))
        db_status = "unreachable"

    print()
    print(_c(BOLD + CYAN, "  RIB Chat"))
    print(_c(DIM, f"  Knowledge graph · {api_url} · {db_status}"))
    print(_c(DIM, "  Type your question, or 'exit' to quit."))
    print()

    # Try readline for history (optional)
    try:
        import readline  # noqa: F401
    except ImportError:
        pass

    conversation: list[dict[str, Any]] = []

    while True:
        try:
            user_input = input(_c(BOLD + GREEN, "You: ")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit", "q"):
            break

        conversation.append({"role": "user", "content": user_input})

        # Agentic loop — keep calling until stop_reason != tool_use
        while True:
            response = llm.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=2048,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=conversation,
            )

            # Collect assistant message content
            assistant_content: list[dict[str, Any]] = []
            tool_results: list[dict[str, Any]] = []

            for block in response.content:
                if block.type == "text":
                    assistant_content.append({"type": "text", "text": block.text})
                elif block.type == "tool_use":
                    tool_name = block.name
                    tool_input = block.input or {}
                    tool_id = block.id

                    # Show tool call
                    args_str = ", ".join(f"{k}={repr(v)}" for k, v in tool_input.items()) if tool_input else ""
                    print(_c(DIM, f"  [{tool_name}({args_str})]"))

                    result_str = execute_tool(tool_name, tool_input, rib)

                    assistant_content.append({
                        "type": "tool_use",
                        "id": tool_id,
                        "name": tool_name,
                        "input": tool_input,
                    })
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": result_str,
                    })

            conversation.append({"role": "assistant", "content": assistant_content})

            if response.stop_reason == "tool_use":
                conversation.append({"role": "user", "content": tool_results})
                continue

            # Final text response
            final_text = " ".join(
                b["text"] for b in assistant_content if b.get("type") == "text"
            ).strip()
            if final_text:
                print()
                print(_c(BOLD + BLUE, "RIB: "), end="")
                print(_wrap(final_text, indent="     "))
            print()
            break


# ─── Entry point ──────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="RIB Chat — query your knowledge graph via natural language"
    )
    parser.add_argument(
        "--api-url",
        default=os.environ.get("RIB_API_BASE", "http://localhost:8081"),
        help="RIB API base URL (default: http://localhost:8081)",
    )
    args = parser.parse_args()
    chat(args.api_url)


if __name__ == "__main__":
    main()