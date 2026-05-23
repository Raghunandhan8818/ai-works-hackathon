# Ripple — Product Design Spec
**Date:** 2026-05-25  
**Hackathon deadline:** June 8, 2026  
**Submission format:** 5-minute demo video (first round)

---

## 1. What Ripple Is

**Hackathon theme: SELF HEALING SYSTEMS**

Ripple is a self-healing system for microservice ecosystems. It detects contract breaks before they reach production, heals consumers automatically, traces production incidents to their root cause across repos, and converts every incident into a regression test — so the same break can never silently happen again.

### The Closed Self-Healing Loop

```
Contract change (PR opened)
  → Ripple detects breaking consumers
  → Mechanical fix: auto-heal silently, raise clean PR
  → Semantic fix: one interrupt question, then auto-heal

Production incident (Jira / PagerDuty / GitHub Issue)
  → Ripple ingests incident, reads error + affected service
  → Traces root cause across repos via knowledge graph
  → Drafts RCA + raises fix PR
  → Converts incident to regression test in consumer's test suite
  → Test merged to CI → this incident can never silently recur
  → Knowledge graph updated with real production belief evidence
```

Every incident makes the system permanently smarter. The test suite grows with real failure cases. The knowledge graph learns what consumers actually assume in production.

### Positioning vs CodeRabbit

| | CodeRabbit | Ripple |
|---|---|---|
| Scope | Single repo code review | Cross-repo self-healing ecosystem |
| Action | Suggests changes in comments | Raises fix PRs, drafts RCAs, adds regression tests |
| Intelligence | Code quality | Semantic contract meaning + incident tracing |
| Learning | None | Every incident becomes a test |
| Enterprise moat | None | Local models, audit trail, schema-agnostic, incident integration |

**Tagline:** *"Ripple doesn't just detect breaks. It heals them, explains them, and makes sure they never happen again."*

---

## 2. The Core Philosophy

Ripple behaves like a senior engineer joining your team:
- **Acts by default** on mechanical, deterministic changes — no approval needed
- **Asks one specific question** only when it hits genuine business ambiguity
- **Never raises a bad PR** — validates the diff before committing

The accuracy guarantee comes from human-in-the-loop for semantic decisions, not from hoping the LLM always gets it right.

---

## 3. Product User Flow

### Full End-to-End

```
1. INSTALL
   Team installs Ripple GitHub App (one click)
   ripple.yaml added to each repo declaring producer/consumer roles

2. INDEX
   Ripple clones repos, builds knowledge graph
   Ecosystem graph appears in dashboard

3. PR OPENED (producer)
   GitHub webhook fires → AnalyzePRWorkflow starts
   Bot comment posted on producer PR within ~30 seconds

4. ROUTING — per affected consumer
   ├── MECHANICAL change → agent auto-heals consumer
   │   → clean fix PR raised silently → graph edge turns green
   └── SEMANTIC change → interrupt card in dashboard
       → one focused question → user answers → agent executes
       → clean fix PR raised → graph edge turns green

5. AUDIT
   Every action logged: who answered what, which PR raised,
   which model used, latency, confidence scores
```

### Three User Personas

**Producer developer** — opens a PR, gets a bot comment listing which consumers will break and what Ripple is doing about it. Minimal friction.

**Consumer team lead** — gets notified when their service is affected. Reviews interrupt cards (semantic decisions only). Approves the approach. PR appears on their repo.

**Platform / Architecture lead** — dashboard overview of entire ecosystem health. Pending interrupt queue. Audit log of all contract changes. Policy settings (e.g., "always deprecate first").

---

## 4. Routing Logic — Mechanical vs Semantic

Every breaking change is classified before the agent acts:

### Mechanical → auto-fix, silent PR

| Change type | Example | Fix strategy |
|---|---|---|
| Field renamed (same semantics) | `phone` → `phoneNumber` | Update all references |
| Type coercion | `int` → `string` | Add `parseInt()` / `toString()` at usage sites |
| New required field | `createdAt` added | Inject sensible default (`now()`) |
| Field made nullable | `String` → `String?` | Add null-safety wrapper |
| Import path changed | Package refactor | Update imports only |

### Semantic → interrupt, human answers one question

| Change type | Example | Why human needed |
|---|---|---|
| Unit changed | `amount` cents → dollars | Business decision: divide or reformat? |
| Behavioral change | Pagination semantics changed | No mechanical fix possible |
| Enum value removed | `STATUS_PENDING` removed | Consumer may have hardcoded this |
| Constraint tightened | Max length 255 → 50 | Data truncation risk |
| Semantic intent mismatch | Field reused for different domain | Architectural decision needed |

This maps to the existing `DisagreementKind` enum in `ripple/rib/graph/schema.py`.

### The Interrupt Card

Not a list of options — one focused question answerable in seconds:

```
⚠️  Ripple needs your input to fix api-gateway

consultationFee changed units.
Producer: now dollars (decimal). Was: cents (integer).

How should api-gateway handle existing values?
  ○ Divide by 100 at read time
  ○ Update billing to work with dollars directly
  ○ I'll handle this manually

[Answer & let Ripple fix it →]
```

Answer logged to audit trail. Agent executes immediately after.

---

## 5. Clean PR Guarantee

When the agent raises a fix PR, these rules are non-negotiable:

- Touches **only** files identified as using the changed field (via tree-sitter + grep)
- Zero reformatting, zero unrelated refactoring
- Validates the diff compiles before pushing
- If validation fails → PR is not raised, user is notified
- Precise commit title: `fix(contracts): null-safe ownerPhone access for vets-service v2.1`
- PR body links back to the producer PR with full context

---

## 6. GitHub Bot Comment (on producer PR)

Concise, actionable, no wall of text:

```markdown
## Ripple — 2 consumers affected by this PR

| Consumer    | Field impacted          | Status                           |
|-------------|-------------------------|----------------------------------|
| react-ui    | ownerPhone (removed)    | ✅ Auto-healed · fix PR #18      |
| api-gateway | consultationFee (units) | ⚠️ Your input needed → [Review] |

Ripple auto-fixes mechanical changes. Semantic decisions surface in your dashboard.

*[Ripple · vets-service · PR #42]*
```

---

## 7. Dashboard Design

### Layout: Light SaaS Grid

- **Stats row** at top: Services count, Breaking changes, Auto-healed count, Fields indexed
- **Ecosystem graph** below: React Flow, nodes = services, edges = consumer→producer relationships
- **Node colours**: Green (healthy), Yellow (warning), Red (breaking), Amber badge (interrupt pending)
- **Click a node** → bottom expand card slides up, graph stays full width

### Bottom Expand Card (on node click)

Shows:
- Which PR triggered the change
- Which fields changed and how
- Per-consumer status (auto-healed ✓ or interrupt pending ⚠)
- Link to producer PR on GitHub
- Link to fix PRs that were raised

### Dashboard Pages

| Page | Purpose |
|---|---|
| `/` | Ecosystem graph (hero view) |
| `/activity` | PR analysis history + fix PR log (audit trail) |
| `/fields` | Field contract explorer — search, filter by service |
| `/interrupts` | Pending semantic decisions queue |
| `/settings` | Model config, GitHub App, ripple.yaml setup |

### Tech Stack: Next.js + React Flow

---

## 8. Enterprise Pillars

### Four pillars, current state vs roadmap

| Pillar | Hackathon (Jun 8) | Phase 1 (0–3 mo) | Phase 2 (3–9 mo) |
|---|---|---|---|
| **Trust** | GitHub App install, activity feed as audit log, "runs in your network" framing | Self-hosted Docker/K8s, structured audit API | SSO/SAML, RBAC, SOC 2 Type II |
| **All Domains** | REST + OpenAPI (done), Protobuf stub, Python/Go via tree-sitter | Full gRPC/Protobuf, Avro/Kafka schema parser | GraphQL SDL, shared library types |
| **Local Models** | LiteLLM abstraction layer, Ollama config toggle, model shown in dashboard | Azure OpenAI + AWS Bedrock, per-task model routing | Air-gapped deploy mode, private model registry |
| **Scale** | Temporal handles distribution (already), live perf numbers in demo | Incremental tree-sitter indexing, Redis blast-radius cache | Graph DB for 500+ services, multi-region Temporal |

### Supported Model Providers (via LiteLLM)

- Anthropic Claude (Opus, Sonnet, Haiku)
- Google Gemini (Pro, Flash)
- OpenAI (GPT-4o, o1)
- Ollama (local — Llama 3, Mistral, CodeLlama)
- Azure OpenAI
- AWS Bedrock

Model selection per task type:
- **Haiku / Flash** — semantic profiling, belief extraction (cheap, parallel)
- **Sonnet / GPT-4o** — disagreement detection, fix strategy generation (accurate)
- **Opus** — complex semantic interrupt questions (highest accuracy)

---

## 9. Multi-Repo Knowledge Graph Architecture

### Why Not SCIP

SCIP is accurate for symbol location but blind to semantics:
- Tells you a field is *referenced* but not what the consumer *believes* about it
- Language support is narrow (~10 languages vs 155 for codebase-memory-mcp)
- Requires binary setup per language — complex CI integration
- Misses dynamic patterns: Jackson `@JsonProperty`, JPA projections, map-based access

### The Core Insight — Two Distinct Jobs

Indexing has two jobs that require completely different tools:

```
Job 1: WHERE is this field used? (structural)
  → Pre-built code graph: deterministic, instant, zero LLM tokens
  → query_graph("ownerPhone") → [file, line, symbol] in milliseconds

Job 2: WHAT does the consumer assume about it? (semantic)
  → LLM reads only the 15-line snippet at that location
  → ~200 tokens per usage vs ~3000 tokens reading the whole file
```

The graph handles expensive search. LLM handles only targeted semantic interpretation.

### The Indexing Strategy — codebase-memory-mcp + Targeted LLM

**Step 1: Build the graph** (once per push, zero LLM cost)

Clone all repos into a shared workspace and run [codebase-memory-mcp](https://github.com/DeusData/codebase-memory-mcp):

```
/workspace
  vets-service/       ← producer
  api-gateway/        ← consumer
  react-frontend/     ← consumer
```

codebase-memory-mcp parses 155 languages, builds a persistent symbol + relationship graph in milliseconds, exposes it as MCP tools.

**Step 2: Claude queries the graph** (targeted, cheap)

Claude agent uses MCP tools — no raw file reading:

```
find_symbol(name, repo)      → exact file + line locations across all repos
get_neighbors(symbol)        → what imports, calls, or uses this symbol
get_context(file, line, n)   → n-line snippet at that location only
get_test_assertions(field)   → test files that assert on this field
```

**Token math:**
| Approach | Tokens to index 5 repos |
|---|---|
| Read all files raw | ~800K–1M tokens |
| All-in-one Claude in context | ~300K–500K tokens |
| **Graph queries + targeted snippets** | **~15K–25K tokens (33–50x reduction)** |

### The Accuracy Stack

Graph gives precise locations. LLM interprets meaning. Confidence scoring decides when to escalate.

```
Layer 1 — Schema files (100% accurate, no LLM)
  OpenAPI / Protobuf / GraphQL SDL parsed deterministically
  Ground truth — the producer's declared contract

Layer 2 — Consumer tests (~90% accurate for beliefs)
  graph.get_test_assertions(field) → test files asserting on this field
  LLM reads assertions: what does the test expect?
  Tests reveal assumptions in structured, verifiable form
  Already partially in ripple/rib/indexer/test_extractor.py

Layer 3 — Direct code usages via graph + LLM (~85% accurate)
  graph.find_symbol(field) → exact locations, no grepping
  LLM reads 15-line snippet per location → what does consumer assume?
  Graph catches DTO chains, import edges, type relationships

Layer 4 — Agentic deep search (on-demand, for low confidence)
  Triggered when confidence score below threshold
  Agent uses get_neighbors() to trace DTO chains, mapper classes
  Targeted and cheap — graph traversal, not file reading
```

**Confidence scoring is non-negotiable.** Low confidence → flag for human review, not a silent guess.

### The Indexing Pipeline (Temporal + Graph + LLM)

```
Temporal: IndexServiceWorkflow
  │
  ├─ Activity 1: SchemaParserActivity (no LLM, fast)
  │   Parse OpenAPI / Protobuf / GraphQL → FieldNode contracts
  │
  ├─ Activity 2: GraphBuildActivity (no LLM, milliseconds)
  │   Run codebase-memory-mcp on /workspace
  │   155 languages · builds symbol + relationship graph
  │   Persistent — incremental update on push (git diff aware)
  │
  ├─ Activity 3: BeliefExtractorActivity (LLM: Haiku, parallel per field)
  │   For each field:
  │     locations = graph.find_symbol(field.name)        ← zero LLM
  │     snippets  = graph.get_context(each loc, 15)      ← zero LLM
  │     tests     = graph.get_test_assertions(field)     ← zero LLM
  │     beliefs   = llm.extract_beliefs(field, snippets, tests)  ← Haiku
  │   Output: ConsumerBelief[] with confidence scores
  │
  └─ Activity 4: DisagreementDetectorActivity (LLM: Sonnet)
      Compare producer contract vs consumer beliefs
      UNIT_MISMATCH / BEHAVIORAL_CHANGE → semantic (interrupt)
      TYPE_CHANGED / NULLABLE_CHANGED → mechanical (auto-fix)
      Low confidence → Layer 4 deep graph traversal before deciding
```

### Why Tests Are the Best Source of Consumer Beliefs

- Tests explicitly assert expected values: `assertEquals("cents", fee.getUnit())`
- Written by developers who understand the business contract
- More stable than production code — tests rarely change without intent
- Reveal assumptions in structured, verifiable form
- Already partially implemented in `ripple/rib/indexer/test_extractor.py`

### Tools Comparison

| Tool | Languages | Token reduction | Notes |
|---|---|---|---|
| [codebase-memory-mcp](https://github.com/DeusData/codebase-memory-mcp) | 155 | 99% | Single binary, sub-ms queries, recommended |
| [graphify](https://github.com/safishamsi/graphify) | 31 | 79x | Multi-modal: code + docs + schemas |
| [codegraph](https://github.com/colbymchenry/codegraph) | 30+ | 49x | Claude Code native, fully local |

**Use codebase-memory-mcp** — 155 languages covers every enterprise stack (Java, TypeScript, Go, Python, Kotlin, C#), zero dependencies, sub-millisecond queries, incremental update support.

---

## 10. Fix Execution Strategy — Speed & Accuracy

The current `run_claude_code_fix_activity` runs `claude -p <prompt> --dangerously-skip-permissions` with a 600-second timeout and no turn limit. Claude Code explores the whole repo before acting — slow, unpredictable, and wasteful when the graph already knows the exact file and line.

### Three Tiers by Fix Complexity

**Tier 1 — Mechanical fix** (graph provides exact file + line + snippet)

No agent loop needed. A single Haiku API call is faster, cheaper, and more predictable:

```python
async def apply_mechanical_fix(field_change: dict, location: dict, snippet: str) -> str:
    response = await anthropic.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1000,
        messages=[{
            "role": "user",
            "content": f"""Fix this exact code snippet. Minimal change only.

Breaking change: {field_change['field_name']} — {field_change['change_type']}
{field_change['old_description']} → {field_change['new_description']}

Code at {location['file']}:{location['line']}:
{snippet}

Return ONLY the fixed code block. No explanation. Touch only what's broken."""
        }]
    )
    return response.content[0].text
```

**Tier 2 — Semantic fix** (after human answers the interrupt card)

Single Sonnet API call with full context from the graph + the human's answer as a constraint:

```python
async def apply_semantic_fix(field_change, location, snippet, human_decision: str) -> str:
    response = await anthropic.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        messages=[{
            "role": "user",
            "content": f"""Fix this code. The human has decided: {human_decision}

{field_change_context}
{snippet}

Apply exactly the decision above. Minimal change. Return fixed code only."""
        }]
    )
    return response.content[0].text
```

**Tier 3 — Complex multi-file refactor** (fallback only)

Claude Code headless with hard constraints — only when multiple files need coordinated changes that the graph can't pre-locate:

```bash
claude -p "<prompt>" \
  --dangerously-skip-permissions \
  --max-turns 5 \
  --model claude-haiku-4-5-20251001 \
  --output-format stream-json
```

`--max-turns 5` is the critical flag — forces Claude Code to act fast rather than explore. Drop timeout from 600s to 120s.

### Latency Comparison

| Method | Typical latency | Use when |
|---|---|---|
| Claude Code headless, no limits (current) | 2–10 minutes | Never |
| Claude Code + `--max-turns 5` + Haiku | 30–90 seconds | Multi-file, complex refactor |
| Aider headless + Haiku | 15–45 seconds | Single-file targeted edit |
| **Direct Haiku API, single turn** | **3–8 seconds** | Mechanical fix (known location) |
| **Direct Sonnet API, single turn** | **15–30 seconds** | Semantic fix (post-interrupt) |

### Alternative Tool: Aider

[Aider](https://github.com/paul-gauthier/aider) — open source coding agent with excellent headless mode. Only reads files you explicitly give it, no codebase exploration:

```bash
aider \
  --message "Fix ownerPhone → ownerContact.phone at line 142. Null-safe only." \
  --model claude/claude-haiku-4-5-20251001 \
  --yes-always \
  --no-git \
  src/components/PetCard.tsx
```

Faster than Claude Code for targeted single-file edits. Good fallback for Tier 3.

### Why the Graph Makes Tier 1 Possible

Without codebase-memory-mcp, you'd need the agent to find which file and line to change — hence the exploration overhead. With the graph:

```
graph.find_symbol("ownerPhone") → [{file: "PetCard.tsx", line: 142, snippet: "..."}]
```

The agent's discovery job is already done. The LLM only needs to rewrite 15 lines.

---

## 11. The 5-Minute Demo Video Script  

**Repo:** Spring PetClinic Microservices (well-known, enterprise Java, multiple Spring Boot services)

```
0:00–0:30  PROBLEM
  "In enterprise software, one API change silently breaks 5 other teams.
   Nobody knows until prod. Ripple fixes this."

0:30–1:00  ECOSYSTEM GRAPH
  Show dashboard: healthy green ecosystem, 6 Spring PetClinic services
  "Ripple indexes your entire ecosystem — every field contract,
   every consumer assumption, every dependency."

1:00–2:00  THE BREAKING CHANGE
  Developer opens PR on vets-service: removes ownerPhone field
  Ripple bot comments on the PR within 30 seconds:
  "2 consumers affected. react-frontend: auto-healing. api-gateway: needs your input."

2:00–2:45  AUTO-HEAL
  Show react-frontend fix PR raised automatically — clean diff, 3 lines
  Graph edge turns green. Zero human involvement.
  "Mechanical changes are handled silently. Engineers aren't interrupted."

2:45–3:30  THE INTERRUPT
  Dashboard: amber badge on api-gateway node
  Interrupt card: "consultationFee changed units — divide by 100 or update billing?"
  User clicks an answer. Fix PR raised immediately.
  "Semantic decisions need context only a human has. Ripple asks once."

3:30–4:15  ENTERPRISE PITCH
  Show model config: swap to Ollama (local Llama 3) — "your code never leaves your network"
  Show audit log: every decision, every PR, every model call — timestamped
  "Built for regulated industries. Runs in your infrastructure."

4:15–5:00  VISION + CALL TO ACTION
  "Ripple is to cross-repo contracts what CodeRabbit is to single-repo code review —
   except Ripple actually fixes the problem, not just flags it."
```

---

## 12. What Exists vs What to Build

### Already Built

- FastAPI REST backend with field, blast-radius, disagreement, beliefs endpoints
- `AnalyzePRWorkflow` — PR diff → field change detection → consumer impact assessment
- `AutoFixConsumerWorkflow` — clone consumer, run Claude Code, push fix PR
- GitHub webhook handling (pull_request, push events)
- PostgreSQL knowledge graph store (fields, beliefs, disagreements, symbols)
- Temporal worker with task queue separation (rib-io, rib-llm, rib-cpu)
- CLI chat interface against the knowledge graph

### To Build for June 8th

| Component | Effort | Priority |
|---|---|---|
| Next.js dashboard (ecosystem graph + stats + activity feed) | 5–6 days | Critical |
| GitHub App registration + install flow | 0.5 days | Critical |
| LiteLLM abstraction layer (replace hardcoded Anthropic calls) | 1 day | Critical |
| Interrupt card UI + API (`/interrupts` endpoint, Temporal signal) | 2 days | Critical |
| codebase-memory-mcp integration (replace SCIP, wrap in Temporal activity) | 1 day | Critical |
| Belief extractor using graph tools + targeted LLM snippets | 1.5 days | Critical |
| Test belief extractor (already partial in test_extractor.py) | 1 day | High |
| Demo repo setup (Spring PetClinic indexed, breaking change scripted) | 1 day | Critical |
| Protobuf parser stub (show in demo graph) | 0.5 days | Medium |

**Total estimated: 13–14 days. Tight but achievable by June 8th with parallel work.**

### Known Technical Debt to Address

- `chat.py` line 222: `api_key = ""` — hardcoded empty string, silent failure
- All LLM calls hardcoded to `claude-sonnet-4-5` — needs LiteLLM abstraction
- `service_indexer.py` SCIP calls — replace with codebase-memory-mcp GraphBuildActivity
- No incremental re-index — codebase-memory-mcp's git-diff-aware updates solve this

---

## 13. Cascade Propagation — Services That Are Both Producer and Consumer

A service can be a producer toward some services and a consumer from others. When a contract break ripples through a transit service, it can trigger a second wave of breaks downstream.

### How It Works

```
payments-service  →  billing-api  →  invoice-ui
                          ↑
                    (transit node)
```

If `payments-service` changes `amount` field semantics, `billing-api` breaks as a consumer. If Ripple auto-fixes `billing-api` — and `billing-api` happens to re-expose `amount` in its own API — `invoice-ui` may also be affected.

### Handling Strategy

The knowledge graph's `ServiceRole` enum already supports `PRODUCER`, `CONSUMER`, and both. The cascade is handled naturally:

1. `AnalyzePRWorkflow` detects consumers of the changed producer
2. For each broken consumer, a fix PR is raised (or an interrupt is queued)
3. On **fix PR merge**, GitHub webhook fires → `IndexServiceWorkflow` re-runs for the fixed consumer
4. Re-indexing rebuilds its consumer beliefs and re-runs `DisagreementDetectorActivity`
5. If new downstream breaks surface → new `AnalyzePRWorkflow` starts for that service

This is Temporal's natural retry + child workflow model — no special cascade code needed. The re-index-on-merge loop is the cascade mechanism.

### Dashboard Representation

The ecosystem graph shows cascade chains visually:
- First-wave breaks: red edges from producer
- Second-wave (cascading): orange dashed edges
- A "cascade depth" counter on the expand card: "This break propagates 2 levels deep"

Cascade depth is capped at 3 for safety — anything deeper is a systemic architecture issue that needs human review, not automated healing.

---

## 14. Incident Integration — Jira / PagerDuty / GitHub Issues

The second self-healing loop: production incidents feed back into the knowledge graph.

### Flow

```
1. INCIDENT INGESTION
   Jira webhook / PagerDuty webhook / GitHub Issue created
   → IncidentIngestActivity receives: title, description, affected service, error logs

2. ROOT CAUSE TRACING
   RootCauseTracerActivity
   → Parse error: extract field names, service names, error codes from logs
   → graph.find_symbol(field) → which producers expose this field
   → graph.get_neighbors(symbol) → trace dependency chain
   → DisagreementDetectorActivity: does a known disagreement explain this incident?
   → Output: RCA candidate with confidence score

3. DRAFT RCA
   If confidence > 0.8 → Sonnet drafts structured RCA:
     - Root cause: field X changed from Y to Z in producer PR #N (link)
     - Affected path: producer → consumer.class:line
     - Why not caught: [Ripple wasn't indexing at time / disagreement was below threshold]
     - Fix: [link to fix PR if already raised]
   RCA posted as Jira comment / GitHub Issue comment

4. FIX PR
   If a known mechanical fix applies → raise it immediately
   If semantic ambiguity → interrupt card linked in Jira/GitHub comment
   If unknown → flag for human investigation with full graph context

5. INCIDENT AS TEST
   Once fix PR is merged:
   IncidentToTestActivity generates a regression test in the consumer repo:
     - Test asserts the exact contract assumption that was violated
     - Named clearly: `testOwnerPhone_notNullAfterVetsServiceV2` 
     - Linked back to Jira ticket in test comment
     - Raised as a separate PR to consumer's test suite
   On merge, CI will catch this break on every future PR.
```

### Why This Matters for the Hackathon

The incident loop is the most compelling demo moment:
- "Here's a production incident in Jira. Ripple traced it to a contract break 3 services deep, drafted the RCA, raised the fix PR, and added a regression test — in under 2 minutes."
- Every incident makes the system permanently smarter — the knowledge graph gains real production evidence, not just declared contracts.

### Incident Ingestion API

```
POST /api/incidents
{
  "source": "jira" | "pagerduty" | "github_issue",
  "id": "PROJ-1234",
  "title": "NullPointerException in VetController billing flow",
  "description": "...",
  "affected_service": "api-gateway",
  "error_logs": "...",
  "severity": "P1" | "P2" | "P3"
}
```

Temporal starts `IncidentResolutionWorkflow` — a new top-level workflow alongside `AnalyzePRWorkflow` and `AutoFixConsumerWorkflow`.

### Knowledge Graph Update

Post-resolution, the incident enriches the knowledge graph:
- Consumer belief gets a `HistorySignal` with kind `INCIDENT` and the incident ID
- Confidence score for that belief increases (real production evidence > static analysis)
- Disagreement that caused the incident is marked `CONFIRMED_BY_INCIDENT`

---

## 15. Code Quality Direction

The current codebase uses procedural activity functions. For a hackathon demo that is also a serious product, the architecture needs to signal engineering quality.

### Direction: Class-Based Activities

Each Temporal activity becomes a class with a single `execute()` method:

```python
# Before (current)
@activity.defn
async def run_schema_parser_activity(service_url: str) -> list[FieldNode]:
    ...

# After (target)
class SchemaParserActivity:
    def __init__(self, db: AsyncSession, http: AsyncClient):
        self._db = db
        self._http = http

    @activity.defn
    async def execute(self, service_url: str) -> list[FieldNode]:
        ...
```

Benefits: injectable dependencies, testable in isolation, single responsibility, no global state.

### Fine-Grained Temporal Activities

Split any activity doing more than one logical unit of work:

| Current (coarse) | Target (fine-grained) |
|---|---|
| `run_claude_code_fix_activity` | `MechanicalFixActivity`, `SemanticFixActivity`, `ValidateDiffActivity`, `PushFixBranchActivity` |
| `index_service_activity` | `SchemaParserActivity`, `GraphBuildActivity`, `BeliefExtractorActivity`, `DisagreementDetectorActivity` |
| `analyze_pr_activity` | `ParseFieldChangesActivity`, `AssessConsumerImpactActivity`, `ClassifyDisagreementActivity` |
| `create_pr_activity` | `CreateBranchActivity`, `CommitChangesActivity`, `OpenPullRequestActivity` |

Fine-grained activities give:
- Exact retry scope (retry only the failed step, not the whole chain)
- Clear audit trail (each activity logged by Temporal with input/output)
- Parallel execution where independent (e.g., assess all consumers in parallel)

### Module Structure (Target)

```
ripple/
  activities/
    indexing/
      schema_parser.py      # SchemaParserActivity
      graph_build.py        # GraphBuildActivity
      belief_extractor.py   # BeliefExtractorActivity
      disagreement_detector.py  # DisagreementDetectorActivity
    fixing/
      mechanical_fix.py     # MechanicalFixActivity
      semantic_fix.py       # SemanticFixActivity
      validate_diff.py      # ValidateDiffActivity
      push_branch.py        # PushFixBranchActivity
      open_pr.py            # OpenPullRequestActivity
    incidents/
      ingest.py             # IncidentIngestActivity
      root_cause_tracer.py  # RootCauseTracerActivity
      rca_drafter.py        # RcaDrafterActivity
      incident_to_test.py   # IncidentToTestActivity
  workflows/
    index_service.py        # IndexServiceWorkflow
    analyze_pr.py           # AnalyzePRWorkflow
    auto_fix_consumer.py    # AutoFixConsumerWorkflow
    incident_resolution.py  # IncidentResolutionWorkflow (new)
  rib/
    graph/                  # Knowledge graph store (unchanged structure)
    enricher/               # Belief enricher, drift detector
    api/                    # FastAPI server
```

### LLM Abstraction — No Hardcoded Model Strings

All LLM calls go through a single `LLMClient` backed by LiteLLM:

```python
class LLMClient:
    def __init__(self, model: str = settings.DEFAULT_MODEL):
        self._model = model

    async def complete(self, prompt: str, max_tokens: int = 1000) -> str:
        response = await litellm.acompletion(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content
```

Model selection injected at activity construction time — swappable per task type, configurable from dashboard settings. No `claude-sonnet-4-5` strings scattered through activity files.
