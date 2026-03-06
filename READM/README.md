# Orchestrator Agent

An intelligent routing agent built with **LangGraph** and **FastAPI** that analyzes user queries, selects the most appropriate backend tool, and returns structured responses. Uses AWS Bedrock for LLM-powered intent analysis with confidence-based guard rails.

## Architecture

```
POST /invocations
       │
       ▼
┌──────────────────┐
│ Guardrail Check  │ ── BLOCKED ──────────────────────────► END
└────────┬─────────┘ ── PII_MASKED → redact query, continue
         │ NONE / PII_MASKED
         ▼
┌─────────────────────┐
│  Intent Analyzer    │  LLM selects tool + extracts parameters
└──────────┬──────────┘
           │
           ▼
┌────────────────────────┐
│  Confidence Router     │  confidence ≥ 7.0 → tool node
└──┬─────────────────────┘  confidence < 7.0 / NO_TOOL → fallback
   │                  │
   ▼                  ▼
[IBTAgent]      [Other Tools]  ← dynamically registered from tools.yaml
   │                  │
   └────────┬──────────┘
            ▼
   ┌─────────────────┐
   │ post_tool_router│  tool failed → fallback
   └──┬──────────────┘  tool success → END
      │           │
      ▼           ▼
  [fallback]    END
      │
      ▼
     END
```

**Key design decision:** Uses a single LangGraph with per-tool nodes.

## Prerequisites

- Python 3.10+
- AWS account with Bedrock access
- IAM credentials with `bedrock:InvokeModel` permission

## Installation

```bash
# Clone and enter the project
cd orchestratoragent

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

```

## Quick Start

After installation and configuration (see below), start the application:

```bash
# Using uvicorn directly (development — auto-reload)
uvicorn src.main:app --reload --port 8000

or
# Using Python (runs uvicorn via __main__ block)
python -m src.main
```

Verify the service is running:

```bash
curl http://localhost:8000/ping
# → {"status": "ok"}
```

### Sending Requests

Pre-built HTTP requests are available in `scripts/requests.http`. To use them:

1. Install the **REST Client** extension in VS Code:
   - Open Extensions (`Ctrl+Shift+X`), search for **REST Client** 
2. Open `scripts/requests.http` in VS Code
3. Click **Send Request** above any request block to execute it

## Configuration

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

### Required Environment Variables

| Variable | Description | Default |
|---|---|---|
| `AWS_ACCESS_KEY_ID` | AWS access key | — |
| `AWS_SECRET_ACCESS_KEY` | AWS secret key | — |
| `AWS_REGION` | AWS region | `us-east-1` |
| `BEDROCK_MODEL_ID` | Bedrock model ID | `us.anthropic.claude-haiku-4-5-20251001-v1:0` |

### Optional Environment Variables

| Variable | Description | Default |
|---|---|---|
| `BEDROCK_TEMPERATURE` | LLM temperature (0 = deterministic) | `0.0` |
| `BEDROCK_MAX_TOKENS` | Max tokens per LLM response | `1024` |
| `CONFIDENCE_THRESHOLD_HIGH` | Min confidence to execute a tool | `7.0` |
| `CONFIDENCE_THRESHOLD_LOW` | Below this triggers fallback | `5.0` |
| `TOOL_TIMEOUT` | Tool HTTP call timeout (seconds) | `30` |
| `LOG_LEVEL` | Logging level | `INFO` |
| `AWS_BEDROCK_GUARDRAIL_ID` | Bedrock Guardrail ID — omit to skip guardrail check | — |
| `BEDROCK_GUARDRAIL_VERSION` | Version of the guardrail to apply | `1` |
| `USE_REFORMULATED_QUERY` | Send LLM-cleaned query to tools instead of raw input | `true` |

---

### `AWS_BEDROCK_GUARDRAIL_ID`

When set, the **guardrail check runs as the first node** in the graph — before intent analysis — and inspects the raw user query against the configured AWS Bedrock Guardrail policy.

There are three possible outcomes:

| Guardrail Action | What Happens |
|---|---|
| `NONE` | Query passes through unchanged, continues to intent analyzer |
| `BLOCKED` | Hard content policy violation — request ends immediately with a policy message, tool is never called |
| `PII_MASKED` | PII (names, emails, SSNs, etc.) is redacted in the query — processing continues with the redacted version |

```env
AWS_BEDROCK_GUARDRAIL_ID=abc123xyz
BEDROCK_GUARDRAIL_VERSION=1
```

If `AWS_BEDROCK_GUARDRAIL_ID` is not set, the guardrail node is a no-op pass-through.

---

### `USE_REFORMULATED_QUERY`

The intent analyzer (LLM) produces two outputs: the original user query and a **reformulated query** — a cleaned, domain-focused restatement of the user's intent (e.g., correcting typos, stripping filler words, normalising to domain keywords).

This flag controls which version is forwarded to the tool:

| Value | Behaviour |
|---|---|
| `true` (default) | Sends the LLM-reformulated query to the tool. Improves accuracy when user input has typos or ambiguous phrasing |
| `false` | Sends the original raw user input to the tool. Use this if tools expect verbatim user text |

**Example:**

```
User input:        "wat r my dental benifits for this yeer?"
Reformulated:      "dental benefits coverage current year"

USE_REFORMULATED_QUERY=true  → tool receives: "dental benefits coverage current year"
USE_REFORMULATED_QUERY=false → tool receives: "wat r my dental benifits for this yeer?"
```

---

## API Reference

### POST `/orchestratoragent/v2/invocations`

Routes a user query to the appropriate backend tool.

**Request:**

```json
{
  "userPrompt": "What are my dental benefits?",
  "sessionId": "sess-abc123",
  "context": {
    "userName": "john_doe",
    "userType": "member",
    "source": "IBTPage",
    "productId": "plan-001"
  }
}
```

| Field | Required | Description |
|---|---|---|
| `userPrompt` | Yes | The user's question |
| `sessionId` | Yes | Unique session identifier |
| `context.userName` | Yes | Authenticated user name |
| `context.userType` | Yes | `member` \| `provider` \| `admin` \| `csr` |
| `context.source` | Yes | Page/source that triggered the call |
| `context.productId` | Yes | Product/plan identifier |
| `context.promptId` | No | Optional prompt tracking ID |

**Response:**

```json
{
  "success": true,
  "timestamp": "2026-03-05T10:30:00.000Z",
  "execution_time_ms": 1250.5,
  "sessionId": "sess-abc123",
  "responseText": "Your dental benefits include...",
  "metadata": [
    {
      "agent": "orchestrator",
      "data": [
        {"key": "selectedTool", "value": "IBTAgent"},
        {"key": "confidence", "value": 8.5},
        {"key": "reasoning", "value": "User is asking about dental coverage"},
        {"key": "parameters", "value": {"userPrompt": "What are my dental benefits?", "userName": "john_doe"}}
      ]
    }
  ]
}
```

**Error Response (validation failure or low confidence):**

```json
{
  "success": false,
  "message": "'context.userName' is required.",
  "timestamp": "2026-03-05T10:30:00.000Z",
  "execution_time_ms": 5.2,
  "sessionId": "",
  "responseText": "",
  "metadata": []
}
```


## Tool Configuration

Tools are defined in `src/tools/definitions/tools.yaml`. No code changes are required to add a new tool — the graph dynamically registers a node for each entry.

```yaml
tools:
  - name: IBTAgent
    description: Handles insurance benefit and coverage inquiries
    endpoint: http://localhost:8001/invocations
    capabilities:
      - benefit inquiries
      - coverage questions
      - policy information
    parameters:
      required:
        - userPrompt
        - userName
      optional:
        - policyNumber
    examples:
      - prompt: "What are my dental benefits?"
        reasoning: "User asking about specific benefit coverage"
```

### Adding a New Tool

1. Add an entry to `src/tools/definitions/tools.yaml`
2. Restart the service — the new tool node is registered automatically
3. Test with a relevant query via `/invocations`

### `tools.yaml` Field Reference

Each tool entry has the following fields:

| Field | Required | Description |
|---|---|---|
| `name` | Yes | Unique tool identifier — becomes the graph node name (e.g., `IBTAgent`) |
| `description` | Yes | Natural language description used by the LLM to match user intent |
| `endpoint` | Yes | HTTP URL the tool node will call (must be a valid URL) |
| `capabilities` | Yes | List of topics/actions this tool handles — helps LLM routing |
| `parameters.required` | Yes | Parameter names that must be extracted and sent to the tool |
| `parameters.optional` | No | Parameter names extracted if present in the query |
| `examples` | No | Sample prompts with reasoning — improves LLM tool selection accuracy |

**Example entry:**

```yaml
tools:
  - name: ClaimsAgent
    description: Handles insurance claims status and history inquiries
    endpoint: http://localhost:8002/invocations
    capabilities:
      - claims status
      - claim history
      - reimbursement inquiries
    parameters:
      required:
        - userPrompt
        - userName
      optional:
        - claimId
        - dateRange
    examples:
      - prompt: "What is the status of my claim?"
        reasoning: "User asking about an existing claim"
```

## Testing

```bash
# Run all tests
pytest tests/ -v

# With coverage report
pytest tests/ --cov=src --cov-report=term-missing

# Unit tests only
pytest tests/unit/

# Integration tests only
pytest tests/integration/

# Filter by name
pytest tests/ -k "test_intent"
```

### Manual API Testing

HTTP request examples are in `scripts/requests.http` (compatible with VS Code REST Client and IntelliJ HTTP Client).

## Project Structure

```
src/
├── api/                    # FastAPI routes and middleware
│   ├── app.py              # App factory with lifespan
│   ├── dependencies.py     # Singleton orchestrator injection
│   ├── error_handlers.py   # Exception → response mapping
│   └── routes/
│       ├── health.py       # GET /ping
│       └── invocations.py  # POST /invocations
├── graph/                  # LangGraph workflow
│   ├── workflow.py         # Graph construction
│   ├── orchestrator.py     # Invocation handler, response builder
│   └── nodes/
│       ├── intent_analyzer.py    # LLM-based tool selection
│       ├── confidence_router.py  # Guard rails routing
│       ├── guardrail_node.py     # AWS Bedrock Guardrails
│       ├── fallback.py           # Low-confidence fallback
│       └── tool_node_factory.py  # Dynamic tool node factory
├── llm/
│   ├── client.py           # AWS Bedrock client wrapper
│   └── prompts/
│       └── intent_analyzer.py  # Tool selection prompts
├── tools/
│   ├── registry.py                 # YAML tool loader
│   └── definitions/tools.yaml     # Tool definitions
├── schemas/                # Pydantic models
│   ├── api.py              # Request/response schemas
│   ├── state.py            # OrchestratorState
│   ├── tools.py            # SelectedTool, ToolResult
│   ├── llm.py              # ToolSelectionOutput
│   └── registry.py         # ToolDefinition
├── config/settings.py      # Pydantic-settings with .env support
├── exceptions.py           # Exception hierarchy
└── utils/logging.py        # Centralized logging

tests/
├── unit/                   # Fast, isolated tests
└── integration/            # End-to-end API tests

## Code Switches

Two areas of the codebase have blocks that need to be manually commented/uncommented depending on the active configuration.

---

### 1. Switching LLM Model — Claude ↔ Llama

**File:** `src/graph/nodes/intent_analyzer.py`

The intent analyzer ships with a **Llama block active** and a **Claude block commented out**. To switch models, swap the comments as described below and update `BEDROCK_MODEL_ID` in `.env`.

**To switch to Claude:**

```python
# 1. At the top of create_intent_node(), uncomment the Claude structured_llm setup:
structured_llm = llm.with_structured_output(ToolSelectionOutput, method="json_mode")

# 2. Comment out the entire LLAMA block (parser, _build_llama_messages,
#    _unwrap_llama_output, llama_chain).

# 3. Inside intent_node(), uncomment the Claude invocation:
messages = [
    SystemMessage(content=system_prompt),
    HumanMessage(content=user_query)
]
parsed: ToolSelectionOutput = structured_llm.invoke(messages)

# 4. Comment out the Llama invocation:
# parsed: ToolSelectionOutput = llama_chain.invoke({"query": user_query})
```

Also update `.env`:
```env
BEDROCK_MODEL_ID=us.anthropic.claude-haiku-4-5-20251001-v1:0
```

**To switch back to Llama:**

Reverse the above — comment out the Claude block, uncomment the Llama block, and update:
```env
BEDROCK_MODEL_ID=us.meta.llama3-3-70b-instruct-v1:0
```

---

### 2. Switching Tool Calls — Mock ↔ Real HTTP

**File:** `src/graph/nodes/tool_node_factory.py`

Tools currently return **hardcoded mock responses**. To enable real HTTP calls to tool endpoints:

**Step 1** — Uncomment the `httpx` import at the top of the file:
```python
import httpx
```

**Step 2** — Inside `tool_node()`, swap the active call:
```python
# Comment out the mock call:
# response_text, agent_metadata = _call_tool_mock(tool_name, effective_query)

# Uncomment the HTTP call:
response_text, agent_metadata = _call_tool_api(tool_name, endpoint, state, effective_query)
```

**Step 3** — Uncomment the entire `_call_tool_api()` function (currently commented out below the `_call_tool_mock` function).

**Step 4** — Ensure tool `endpoint` URLs in `tools.yaml` are reachable.

> The `TOOL_TIMEOUT` env var controls the HTTP client timeout (default: `30` seconds).

---

## CI/CD

### Continuous Integration

[View CI Pipeline](<INSERT_CI_LINK_HERE>)

### Continuous Deployment

[View CD Pipeline](<INSERT_CD_LINK_HERE>)
