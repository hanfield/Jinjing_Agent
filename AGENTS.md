# 金枢 2.0 (Jin-Shu OS) - Agent Guide & Development Standards

This file is the root instruction set for AI code agents and human developers working in the JinShu OS repository. Prefer these conventions and architectural guidelines over generic Python/Agent framework advice.

## Project Shape & Boundaries

- **Primary Language & Runtime**: Python `>= 3.10`.
- **Core Engine (`engine/`)**: Contains the proprietary JinShu Multi-Agent star-topology orchestrator and global blackboard.
- **Enterprise Harness (`harness/`)**: The industrial-grade automated evaluation dashboard.
  - `harness/tasks/`: Test suite registry and data hydration logic.
  - `harness/environments/`: Transparent sandbox proxy, API interception, and chaos engineering injection.
  - `harness/evaluators/`: Dual-core metrics engine (Engineering + LLM Judge) and SQLite Data Flywheel.
  - `harness/adapters/`: `BaseAgentAdapter` implementations for specific frameworks (JinShu, LangChain, etc.).
- **Data Flywheel (`finetune/`)**: Destination for generated SFT and DPO training data, driven by the Harness SQLite exporter.

## Enterprise Harness Engineering Conventions

When modifying or extending the `harness/` directory, adhere strictly to the following enterprise production standards:

### 1. Data Hydration over Static Mocks
- **DO NOT** hardcode static environmental states (e.g., `mock_env_state: {"temp": 25}`) in test suite definitions.
- **DO** use `snapshot_uri` to dynamically load ("hydrate") real production snapshots or simulated time-series data. The Harness must reflect the complexity of a real data center.

### 2. Sandbox Interception & Chaos Engineering
- **DO NOT** let the Agent make direct destructive calls to external environments during evaluation.
- **DO** route all external MCP/HTTP calls through `SandboxProxyHarness`.
- The Sandbox must support **Chaos Injection**: gracefully handle configurations like `failure_rate: 0.2` or latency jitters to validate the Agent's retry and fault-tolerance logic.
- Enforce strict Schema Validation on tool arguments intercepted in the Sandbox.

### 3. Structural Data Flywheel (SQLite)
- **DO NOT** append evaluation results to raw `.jsonl` files natively.
- **DO** persist all Run IDs, task scores, TTFT (Time To First Token), and tool execution traces into an embedded SQLite database (`flywheel.db`).
- Raw `.jsonl` for SFT/DPO should be deterministically exported/queried from this SQLite source, ensuring data consistency for BI dashboards.

### 4. Transparent Adapter Pattern
- The Harness core must remain completely agnostic to the underlying Agent framework.
- Any new Agent integration must implement `BaseAgentAdapter.run_task` and return the standardized Telemetry Schema (including `ttft_ms`, `span_traces`, `executed_tools`, etc.).

## General Coding Conventions

- **Async First**: All IO operations, tool executions, and LLM API calls MUST use `asyncio` and `async/await`. Avoid blocking synchronous requests.
- **Type Hinting**: Enforce strict Python typing (`typing.Dict`, `typing.List`, `typing.Optional`, or modern `dict`, `list` syntax where supported) on all function signatures.
- **LLM Independence**: Do not hardcode specific LLM models (e.g., "gpt-4") deep in the logic. Rely on configuration or environment variables (`LLM_MODEL`, `OPENAI_BASE_URL`).
- **Granular Tracing**: For Multi-Agent workflows, capture `span_traces` (expert invoked, timestamp, duration) rather than flat flat event arrays.

## Verification Expectations

- Before declaring a Harness feature complete, verify it by running the CLI evaluator: `python -m harness.cli --config harness/configs/default_eval.json`.
- Ensure that modifying the evaluator does not break backwards compatibility with existing Adapter interfaces.
- If schema changes are made to the Flywheel DB, ensure migration logic or clear table resets are documented.
