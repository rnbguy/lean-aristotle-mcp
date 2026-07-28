# AGENTS.md

This file provides working guidance for contributors and coding agents, including Codex,
OpenCode, Claude Code, and other repository-aware tools.

## Project Overview

This MCP server adapts the native `aristotlelib>=2.1.0` public API for Lean 4 work. It exposes exactly 16 tools across Projects, AgentTasks, Events, project-file downloads, and three Lean workflows.

The current model is:

- A `Project` owns a prompt and optional submitted files, identified by `project_id`.
- An `AgentTask` performs work within a Project, identified by `task_id`.
- An `Event` records task activity or an agent question, identified by `event_id`.

`continue_project` creates an `INSTRUCT` follow-up. `ask_project` creates an `ASK` follow-up. A pending `SENT` `AGENT_QUESTION` Event is answered with `answer_question`.

Native task statuses are preserved in lower case. Terminal statuses are `complete`,
`complete_with_errors`, `out_of_budget`, `failed`, and `canceled`. Do not turn these into
proof-specific status values. `wait_task` reports its own outcome separately from the task:
`terminal`, `timed_out`, or `waiting_for_answer`.

## Tool Surface

The server registers only these tools:

```text
submit_project        list_projects          get_project
continue_project      ask_project            list_project_tasks
get_task              wait_task              cancel_task
list_task_events      get_event              answer_question
download_project_files
prove                 prove_file             formalize
```

Keep `server.py` signatures exact. In particular, `prove` accepts plural `context_files`, while `formalize` accepts singular `context_file`. Workflows return both `project_id` and `task_id`; they do not invent proof-specific statuses.

## Architecture

```text
src/aristotle_mcp/
|-- server.py          MCP registration and exact public tool signatures
|-- projects.py        Native Project creation, listing, follow-ups, downloads
|-- tasks.py           Native AgentTask listing, refresh, bounded waits, cancellation
|-- events.py          Native Event listing, refresh, question answers
|-- workflows.py       prove, prove_file, and formalize composition
|-- files.py            Output reservation, safe archive handling, context staging
|-- models.py           Wire result dataclasses
|-- config.py           SDK configuration and mock-mode selection
|-- errors.py           Expected error conversion
`-- mock_*.py          Matching in-memory offline operations
```

`server.py` registers FastMCP tools and delegates to domain modules. Production service operations use documented native `Project`, `AgentTask`, and `Event` methods and may catch the SDK's `LeanProjectError` local validation exception. Do not use `AristotleRequestClient`, direct HTTP, private SDK state, SDK interactive waiting, or `input()`.

`wait_task` has a finite deadline covering lookup, refresh, event paging, and polling. A successful wait returns `terminal`, `timed_out`, or `waiting_for_answer`; a lookup that expires before a task snapshot returns a structured `ErrorResult` because no `TaskResult` exists yet.

`prove_file` discovers the nearest ancestor containing `lakefile.lean`, `lakefile.toml`, or `lean-toolchain`. `prove` stages `proof.lean`; `formalize` stages `description.txt` and requests `formalize.lean`. Solution archives are validated before extraction, and file writes reserve their outputs first.

### Contributor Invariants

- Keep every public MCP signature in `server.py` synchronized with `tests/test_server.py`.
- Preserve `project_id`, `task_id`, and `event_id` in all corresponding wire results.
- Use documented native `Project`, `AgentTask`, and `Event` methods plus `LeanProjectError` for local validation at the production boundary.
- Keep `wait_task` finite and noninteractive. Do not use `AgentTask.wait_for_completion` or `input()`.
- Route SDK, `LeanProjectError` validation, filesystem, and archive failures through `ErrorResult`.
- Preserve archive traversal and link checks before reading any solution archive.
- Do not reserve or write workflow output when `wait=false`.
- Keep `formalize` singular `context_file` and `prove` plural `context_files`.

## Result Shapes

`ProjectResult` contains the ID, native status, timestamps, description, `has_input`, and
`has_files`. `TaskResult` contains both project and task IDs, native status, timestamps,
completion percentage, file name, description, and output summary. `EventResult` contains
event and task IDs, type, status, content, and optional file metadata.

List tools return their object array plus `next_pagination_key`. Workflow tools always return
`status`, `project_id`, `task_id`, `code`, `output_path`, `output_summary`, and `message`.
The `status` is the native task status; code and output paths are optional retrieved artifacts.

## Environment And Mock Mode

- `ARISTOTLE_API_KEY` enables live SDK operations.
- `ARISTOTLE_MOCK=true` routes all domain operations to the native-shaped in-memory mock.

Mock mode needs no API key and no network. It is the default test path, but it is not evidence that a proof succeeds on the live service.

The mock keeps native-shaped Projects, AgentTasks, and Events in memory for the process
lifetime. It exercises pagination, bounded waiting, questions, output collisions, and safe
workflow staging without calling the service. Keep mock behavior aligned with public result
shapes and contracts, not with private production implementation details.

## Build System

The Makefile auto-detects `.venv`. Run `make help` for all targets.

```bash
uv sync --all-extras
make check          # Ruff and strict mypy
make test           # Offline native mock suite
make test-lean      # Cache-first Lean build for tests/lean_project
make verify         # Offline quality, tests, and Lean build
make build          # Build the wheel
make run            # Start the live MCP server
make run-mock       # Start the offline MCP server
```

`make test-api` is opt-in. It requires `ARISTOTLE_API_KEY`, has a bounded timeout, and creates test-owned live Projects. Do not run it without an explicit request, and never claim it ran when only offline tests ran.

`make test-lean` first runs `lake exe cache get` and then `lake build` from
`tests/lean_project`. Keep this cache-first sequence: it avoids compiling Lean dependencies
from scratch and verifies the fixture project used by file-oriented workflows.

## Type Checking And Tests

The project uses strict mypy and keeps SDK boundary declarations in `stubs/aristotlelib/`. The `.pyi` stub exists because the runtime SDK does not expose every type detail required by this strict configuration. Keep the stub aligned with the verified SDK public contract, not with guesses about private SDK implementation.

Tests are organized by native domain: `test_projects.py`, `test_tasks.py`, `test_events.py`, `test_files.py`, `test_workflows.py`, `test_server.py`, and `test_sdk_contract.py`. `test_live_api.py` is excluded from ordinary pytest runs and is reached only by `make test-api`.

The test pyramid is intentional:

- Unit tests cover wire models, archive helpers, and local validation.
- Offline integration tests exercise the mock Project, task, Event, and workflow domains.
- Server tests assert registered tool names and exact JSON schemas.
- SDK contract tests pin the verified public enums, Pydantic fields, signatures, and dependencies.
- The opt-in live test is the only integration evidence against the paid service.

## Code Quality Rules

Never hide linting or type errors with `# noqa`, `# type: ignore`, ignored configuration, or disabled checks. Fix the structure instead.

Keep external failures at the boundary as structured `ErrorResult` values. Preserve native status values and IDs.

## Dependency And Documentation Policy

Keep `aristotlelib>=2.1.0` as the authoritative SDK dependency. Before changing it, update
the runtime contract test and the local stub from verified public SDK behavior. Do not infer
new enums, fields, or methods from an older document or private source.

README documents onboarding and user workflows. `docs/ARISTOTLE_MCP_DESIGN.md` owns detailed schemas, call flows, safety rules, and rationale. `docs/USER_STORIES.md` owns practical MCP client examples. Keep all three consistent with `server.py`, `models.py`, and the tests.
