# Aristotle MCP Server Design Document

## Overview

This MCP server adapts Harmonic's Aristotle service for Lean 4 development through the native `aristotlelib>=2.1.0` public API. It lets an MCP client submit Lean projects or focused workflow requests, observe the resulting work, answer agent questions, and retrieve produced files through distinct native objects.

The server is deliberately thin at the SDK boundary. Production service operations use documented native `Project`, `AgentTask`, and `Event` methods, plus the SDK's `LeanProjectError` local validation exception. It does not use direct HTTP endpoints, `AristotleRequestClient`, private SDK state, or SDK interactive waiting. This keeps the MCP model aligned with the client library that owns the service contract.

## Motivation

Lean development regularly reaches points where automated proving is useful:

- Filling a `sorry` placeholder when the proof shape is clear but a subgoal is difficult.
- Checking a proposed lemma before building other declarations on it.
- Submitting an existing Lake project so the prover sees its imports and local definitions.
- Formalizing a natural-language statement before deciding how to prove it.
- Continuing an existing project with an instruction or answering a question from the Aristotle agent.

The native 2.1 lifecycle is the server's public model. It makes ownership, work state, questions, and files separately addressable instead of reducing every request to a proof-specific status.

## Goals And Non-Goals

### Goals

- Expose the native Project, AgentTask, and Event API through stable MCP result objects.
- Preserve native IDs and status values so a client can make its own scheduling decisions.
- Make waiting finite and noninteractive, including the case where an agent needs an answer.
- Keep Lean convenience workflows small compositions of native operations.
- Treat downloaded archives and local output paths as filesystem trust boundaries.
- Provide an offline mock with the same tool names and result shapes as production.

### Non-Goals

- Reinterpret native task status as proof success, failure, or a local job state.
- Maintain local asynchronous task metadata outside the service's Project and AgentTask records.
- Stream an SDK interactive session through MCP or prompt on standard input.
- Expose direct HTTP requests or private SDK implementation details.
- Extract an entire service archive into a caller-selected directory.

## Architecture

```text
+-----------------+        MCP over stdio        +------------------+
| MCP client      | <--------------------------> | aristotle-mcp    |
| MCP client      |                              | FastMCP server   |
+-----------------+                              +--------+---------+
                                                            |
                                                            | public Python SDK
                                                            v
                                                   +------------------+
                                                   | aristotlelib 2.1 |
                                                   +--------+---------+
                                                            |
                                                            | service request
                                                            v
                                                   +------------------+
                                                   | Aristotle        |
                                                   | Harmonic service |
                                                   +------------------+
```

`server.py` owns MCP registration and the exact public signatures. Domain modules adapt native objects to stable JSON-shaped result dataclasses:

| Module | Responsibility |
|------|----------------|
| `projects.py` | Create, list, refresh, continue, ask, and download Projects. |
| `tasks.py` | List, refresh, wait for, and cancel AgentTasks. |
| `events.py` | List, refresh, and answer Events. |
| `workflows.py` | Compose native submission, bounded waiting, and Lean output retrieval. |
| `files.py` | Stage context, reserve paths, and safely select Lean files from archives. |
| `models.py` | Define the wire result shapes returned by the MCP tools. |
| `mock_*.py` | Provide an in-memory implementation with the same public shapes. |

Expected SDK, filesystem, validation, and archive failures become a structured `ErrorResult`. `LeanProjectError` is a validation error. The server does not expose raw tracebacks as an API contract.

## Native Object Model

### Project

A Project has `project_id`, a native `status`, timestamps, optional description, and flags for input and files. It owns the prompt and files submitted to Aristotle. `list_projects` returns Projects in native newest-first order and accepts native `ProjectStatus` filters, which are `RUNNING` and `IDLE` at the SDK boundary and serialized in lower case.

### AgentTask

An AgentTask has `task_id` and `project_id`. It carries native status, timestamps, completion percentage, optional file name and description, and optional output summary. The server preserves the native status value rather than converting it to `proved`, `partial`, or another workflow-specific state.

Terminal task statuses are `COMPLETE`, `COMPLETE_WITH_ERRORS`, `OUT_OF_BUDGET`, `FAILED`, and `CANCELED`. Nonterminal values such as `QUEUED` and `IN_PROGRESS` remain observable through `get_task`, `list_project_tasks`, and `wait_task`.

### Event

An Event has `event_id` and `task_id`. Its wire shape includes lower-case event type and status, creation time, content, and optional file path, explanation, suggestions, and duration. A pending agent question is an Event with type `AGENT_QUESTION` and status `SENT`. It must be answered with `answer_question(event_id, answer)`.

Three IDs matter throughout the server:

```text
Project     project_id     owns prompt and files
AgentTask   task_id        performs one unit of work in a Project
Event       event_id       records activity or a question for a task
```

### Native Enums And State Transitions

The SDK contract test is the source of truth for enum membership. The server serializes
Project and Event enum names in lower case, and serializes TaskStatus values in lower case.

| Native enum | Current members relevant to this server | MCP representation |
|------|------------------------------------------|--------------------|
| `ProjectStatus` | `UNKNOWN`, `RUNNING`, `IDLE` | `unknown`, `running`, `idle` |
| `TaskStatus` | `UNKNOWN`, `QUEUED`, `IN_PROGRESS`, `COMPLETE`, `COMPLETE_WITH_ERRORS`, `OUT_OF_BUDGET`, `FAILED`, `CANCELED` | lower-case status value |
| `EventStatus` | `UNKNOWN`, `COMPLETE`, `SENT` | `unknown`, `complete`, `sent` |
| `FollowUpMode` | `ASK`, `INSTRUCT` | chosen by `ask_project` or `continue_project` |
| `AgentQuestionsSetting` | `DISABLED`, `TIMEOUT_15_MIN` | accepted by submission and follow-up tools |

The server reports the native Project status without predicting or synthesizing Project
transitions. A task can be observed in a nonterminal state such as `queued` or
`in_progress` and is terminal only at `complete`, `complete_with_errors`, `out_of_budget`,
`failed`, or `canceled`. Terminal status takes precedence over a pending question during a
wait. Workflows retrieve artifacts only for `complete`, `complete_with_errors`, and
`out_of_budget`; `failed`, `canceled`, and nonterminal outcomes have no artifact.

Events are historical records rather than a second task status channel. A pending question
is specifically an `agent_question` Event with `sent` status and no explanation. Once it is
answered, the service updates that Event rather than creating a local answer record.

## MCP Tools

The server registers exactly these 16 tools:

```text
submit_project        list_projects          get_project
continue_project      ask_project            list_project_tasks
get_task              wait_task              cancel_task
list_task_events      get_event              answer_question
download_project_files
prove                 prove_file             formalize
```

### Exact Signatures

The following signatures are the MCP boundary in `server.py`. Optional values use their
shown defaults. Do not widen these signatures without changing both the server registration
and the server-schema tests.

| Tool | Parameters | Result |
|------|------------|--------|
| `submit_project` | `prompt`, `project_dir=None`, `tar_file_path=None`, `public_file_path=None`, `agent_questions_setting=DISABLED` | `{project, task}` |
| `list_projects` | `pagination_key=None`, `limit=30`, `status=None` | `{projects, next_pagination_key}` |
| `get_project` | `project_id` | `ProjectResult` |
| `continue_project` | `project_id`, `prompt`, `files=None`, `agent_questions_setting=DISABLED` | `TaskResult` |
| `ask_project` | `project_id`, `prompt`, `agent_questions_setting=DISABLED` | `TaskResult` |
| `list_project_tasks` | `project_id`, `pagination_key=None`, `limit=10`, `newest_first=true` | `{tasks, next_pagination_key}` |
| `get_task` | `task_id` | `TaskResult` |
| `wait_task` | `task_id`, `timeout_seconds=300.0`, `poll_interval_seconds=5.0` | `WaitTaskResult` |
| `cancel_task` | `task_id` | `TaskResult` |
| `list_task_events` | `task_id`, `pagination_key=None`, `limit=50`, `newest_first=true` | `{events, next_pagination_key}` |
| `get_event` | `event_id` | `EventResult` |
| `answer_question` | `event_id`, `answer` | `EventResult` |
| `download_project_files` | `project_id`, `output_path=None`, `overwrite=false` | `ProjectFilesResult` |
| `prove` | `code`, `context_files=None`, `hint=None`, `wait=true` | `WorkflowResult` |
| `prove_file` | `file_path`, `output_path=None`, `wait=true` | `WorkflowResult` |
| `formalize` | `description`, `prove=false`, `context_file=None`, `wait=true` | `WorkflowResult` |

`prove` accepts plural `context_files`; `formalize` accepts singular `context_file`. This
distinction is part of the tool schema and must remain visible in all user-facing examples.

### Shared Wire Schemas

Project, task, and Event operations are normalized to the complete field sets below. Fields
with a null value remain present rather than being silently omitted.

```json
{
  "project_id": "string",
  "status": "string",
  "created_at": "ISO-8601 string",
  "last_updated": "ISO-8601 string",
  "description": "string or null",
  "has_input": true,
  "has_files": false
}
```

```json
{
  "project_id": "string",
  "task_id": "string",
  "status": "string",
  "created_at": "ISO-8601 string",
  "last_updated_at": "ISO-8601 string",
  "percent_complete": "integer or null",
  "file_name": "string or null",
  "description": "string or null",
  "output_summary": "string or null"
}
```

```json
{
  "event_id": "string",
  "task_id": "string",
  "event_type": "string",
  "status": "string",
  "created_at": "ISO-8601 string",
  "content": "string",
  "file_path": "string or null",
  "explanation": "string or null",
  "suggestions": ["string"],
  "duration_seconds": "number or null"
}
```

List results wrap these objects under `projects`, `tasks`, or `events` with a
`next_pagination_key`. A null next key means no additional page. Pagination keys pass
through from the SDK; the server does not decode or reinterpret them.

### Project Operations

#### `submit_project`

Creates a Project from a prompt and either `project_dir` or `tar_file_path`. It also accepts `public_file_path` and `agent_questions_setting`. Directory and tar inputs are mutually exclusive. The result contains a `project` object and its initial `task`, which can be null only when native submission yields no task.

```json
{
  "project": {
    "project_id": "project-123",
    "status": "running",
    "created_at": "2026-01-01T00:00:00+00:00",
    "last_updated": "2026-01-01T00:00:00+00:00",
    "description": "Prove the supplied theorem.",
    "has_input": true,
    "has_files": true
  },
  "task": {
    "project_id": "project-123",
    "task_id": "task-456",
    "status": "queued",
    "created_at": "2026-01-01T00:00:00+00:00",
    "last_updated_at": "2026-01-01T00:00:00+00:00",
    "percent_complete": 0,
    "file_name": null,
    "description": "Prove the supplied theorem.",
    "output_summary": null
  }
}
```

#### `list_projects` And `get_project`

`list_projects(pagination_key=None, limit=30, status=None)` returns a `projects` array and `next_pagination_key`. `get_project(project_id)` refreshes one Project. These tools operate on native account-visible Projects, so callers should scope their own presentation and access choices appropriately.

#### `continue_project` And `ask_project`

`continue_project(project_id, prompt, files=None, agent_questions_setting=DISABLED)` creates an `INSTRUCT` follow-up. It may upload files, but native Projects accept those files only while idle.

`ask_project(project_id, prompt, agent_questions_setting=DISABLED)` creates an `ASK` follow-up without file input. Both return a `TaskResult`, so callers continue through the returned task ID.

The two follow-ups deliberately preserve the native distinction. Use `INSTRUCT` to request
additional work, including optional file input. Use `ASK` to ask the agent a question about
the Project. In both cases, the service creates an AgentTask that has its own task ID and
Events. A caller that needs to continue observing work must use that new task ID.

The default `agent_questions_setting` is `DISABLED`. To permit a question, pass
`AgentQuestionsSetting.TIMEOUT_15_MIN`, whose MCP wire value is `2`.

### Project Call Flow

```text
submit_project(prompt, project_dir or tar_file_path)
  -> Project.create_from_directory(...) or Project.create(...)
  -> Project.get_tasks(limit=1, newest_first=true)
  -> {project, initial task}

continue_project(project_id, prompt, files)
  -> Project.from_id(project_id)
  -> Project.ask(prompt, INSTRUCT, files, agent_questions_setting)
  -> TaskResult

ask_project(project_id, prompt)
  -> Project.from_id(project_id)
  -> Project.ask(prompt, ASK, None, agent_questions_setting)
  -> TaskResult
```

`submit_project` validates that a directory exists and that a tar input is actually a tar
archive before calling the SDK. It accepts one source form at a time. Follow-up file paths
are passed to the SDK only for `continue_project`; no separate local file-upload mechanism
exists in the server.

### Task Operations

#### `list_project_tasks`, `get_task`, And `cancel_task`

`list_project_tasks(project_id, pagination_key=None, limit=10, newest_first=True)` preserves native task ordering. `get_task(task_id)` refreshes one task. `cancel_task(task_id)` calls the native cancellation operation and returns the updated task status.

#### `wait_task`

`wait_task(task_id, timeout_seconds=300.0, poll_interval_seconds=5.0)` is the server's only waiting primitive. Both bounds must be finite and positive. Its finite deadline covers the initial task lookup, refreshes, unanswered-question scans, and sleeps. If lookup exhausts that deadline before a task snapshot exists, it returns a structured API `ErrorResult`; otherwise, it refreshes the task, looks for an unanswered question, sleeps no longer than the requested interval, and stops at the deadline.

It does not use the SDK's interactive waiting API and never reads from standard input. Its result is:

```json
{
  "outcome": "terminal | timed_out | waiting_for_answer",
  "task": {"task_id": "task-456", "status": "in_progress", "...": "..."},
  "question": null,
  "message": "Task did not reach a terminal state before the timeout."
}
```

For `waiting_for_answer`, `question` is the newest pending agent-question Event. For `terminal`, it is null and `task.status` is one of the native terminal statuses. Terminal status is checked before pending questions. A timeout is an outcome, not a fabricated task status.

### Bounded Waiting Call Flow

```text
deadline -> bounded AgentTask.from_id(task_id)
  -> return API ErrorResult if lookup expires before a TaskResult exists
  -> refresh task before each observation
  -> return terminal if TaskStatus is terminal
  -> page task Events newest first and locate a pending AGENT_QUESTION
  -> return waiting_for_answer with that Event when present
  -> sleep for min(poll_interval_seconds, remaining deadline)
  -> return timed_out when the deadline expires
```

The refresh and Event scan are each bounded by the same monotonic deadline. This prevents a
slow request from extending the public timeout. Non-finite and non-positive timeout or polling
values are validation errors. A client can therefore safely use `wait_task` in an automation
loop without risking hidden input or an unbounded service wait.

### Event Operations

`list_task_events(task_id, pagination_key=None, limit=50, newest_first=True)` returns Event objects and a next pagination key. `get_event(event_id)` refreshes a single Event. `answer_question(event_id, answer)` rejects empty answers and asks the native Event to accept the answer. Answered or expired questions are rejected by the native contract.

### Question Call Flow

```text
wait_task(task_id)
  -> outcome: waiting_for_answer
  -> question.event_id
  -> answer_question(event_id, answer)
  -> EventResult
  -> wait_task(task_id) or get_task(task_id)
```

The question Event is the answer target. A Project ID identifies the surrounding work and a
task ID identifies the active work item, but neither can answer a question. Use `get_event`
or `list_task_events` when a client needs its content, suggestions, file path, or explanation
before responding.

### Project File Download

`download_project_files(project_id, output_path=None, overwrite=False)` writes the archive returned by native `Project.get_files`. A chosen destination is reserved before the download begins. The download writes to a temporary file and atomically replaces the reserved destination. Existing paths are rejected unless `overwrite=true` is explicit.

Its result shape is:

```json
{
  "status": "complete",
  "project_id": "project-123",
  "output_path": "/workspace/project-123.tar.gz",
  "message": "Project files downloaded"
}
```

When `output_path` is omitted, the server derives a safe archive filename from the project
ID and reserves a unique local path. When a caller supplies a path with `overwrite=false`,
exclusive creation prevents accidental replacement. When overwrite is explicit, the download
still writes through a temporary sibling path before replacing the destination.

## Lean Workflows

The workflow tools compose native Project submission with the same bounded wait semantics. They return this shared result shape:

```json
{
  "status": "complete",
  "project_id": "project-123",
  "task_id": "task-456",
  "code": "string or null",
  "output_path": "string or null",
  "output_summary": "string or null",
  "message": "Project submitted."
}
```

The status is the native task status. `code` and `output_path` are transport results, not new proof-status fields.

### `prove`

`prove(code, context_files=None, hint=None, wait=True)` writes the supplied Lean source to `proof.lean` in a temporary directory. An optional hint becomes a Lean comment at the start of that staged file. The plural `context_files` list is copied into the staging directory after path checks, and no staged context may collide with `proof.lean`.

The prompt requests that Aristotle prove all `sorry` statements. With `wait=false`, the result immediately contains the Project and task IDs. With `wait=true`, the workflow calls bounded `wait_task` and downloads the project archive only for `complete`, `complete_with_errors`, or `out_of_budget`, then reads the exact matching `proof.lean` when present. `failed`, `canceled`, and nonterminal outcomes have no artifact; a matching file may still be absent.

### `prove_file`

`prove_file(file_path, output_path=None, wait=True)` requires an existing file. It searches upward from that file for the nearest `lakefile.lean`, `lakefile.toml`, or `lean-toolchain`, then submits that directory. If no marker is found, it submits the file's containing directory.

The workflow asks to prove the file's path relative to the submitted Lake root. When waiting, its default output is the canonical input path with `_aristotle.lean` appended before the extension. It reserves this output before submission, selects an exact match for that Lake-relative path from the result archive, validates the archive, and writes the file atomically. Artifacts are retrieved only for `complete`, `complete_with_errors`, or `out_of_budget`; `failed`, `canceled`, and nonterminal outcomes have no artifact, and a matching file may still be absent. With `wait=false`, it neither reserves nor writes a local output.

### `formalize`

`formalize(description, prove=False, context_file=None, wait=True)` writes the source text to `description.txt`, stages at most one optional context file, and requests a result named `formalize.lean`. If `prove=true`, the native prompt asks Aristotle to prove the formalization too.

The singular `context_file` is intentional and is part of the exact public server signature. Do not document or implement plural context files for `formalize`.

### Workflow Call Flow

```text
prove
  -> temporary directory with proof.lean and optional context files
  -> submit_project("Please prove all sorry statements.")

prove_file
  -> canonicalize file path and discover nearest Lake root
  -> submit_project(root, prompt naming the Lake-relative requested file)

formalize
  -> temporary directory with description.txt and optional context file
  -> submit_project(prompt requesting formalize.lean)

all workflows
  -> return Project and task IDs immediately when wait=false
  -> otherwise call wait_task(task_id)
  -> for complete, complete_with_errors, or out_of_budget, read or copy an exact matching Lean file from the archive when present
```

For `wait=false`, no workflow reserves or writes a local Lean output. The caller retains the
returned IDs and can inspect native state later. For `wait=true`, `failed`, `canceled`, and
nonterminal outcomes return no artifact. Even an artifact-producing status can have no exact
matching file, so the workflow reports that condition without inventing code or an output path.

## File Safety

Workflow output is treated as an untrusted archive. The archive reader rejects absolute paths, parent traversal, and links before selecting a Lean file. This avoids extracting a service-returned archive into arbitrary local paths.

Output paths are canonicalized and reserved before work begins. A failed workflow removes its reservation, while a successful write uses an atomic replacement. These rules prevent accidental overwrites and partial output files.

## Mock Mode

`ARISTOTLE_MOCK=true` routes every domain operation through matching in-memory modules. It needs neither API key nor network access. Its purpose is repeatable MCP and workflow testing, not a claim that the live prover will solve the same request.

Mock Projects, tasks, and events follow the native-shaped IDs, statuses, result fields, pagination, question flow, file collision behavior, and output reservation rules. Mock directory collection follows the SDK-like ignore and `.gitignore` behavior through `pathspec`.

## Runtime Configuration

The server loads `.env` once when configuration is first accessed. `ARISTOTLE_API_KEY` is
passed to the SDK through `set_api_key` when present. `ARISTOTLE_MOCK` enables mock mode for
the values `true`, `1`, or `yes`, case-insensitively. The `aristotle://status` resource
reports `mock_mode`, `api_key_configured`, and `ready`; ready is true when either mock mode
is enabled or an API key is configured.

The production entry point configures the SDK before starting FastMCP on stdio. Configuration
belongs to the MCP host environment. The server does not prompt for credentials, persist keys,
or require a network connection while mock mode is active.

## Verification Strategy

`make check` runs Ruff and strict mypy. `make test` runs the offline native mock suite, and
`make test-lean` first runs `lake exe cache get` then `lake build` in `tests/lean_project`.
The cache-first Lean command avoids a dependency rebuild and verifies the fixture used by
file-oriented workflows. `make verify` combines the offline quality, test, and Lean checks.

The test layout separates wire-model and archive-helper units from mock-domain integration,
server-schema assertions, and SDK public-contract assertions. `make test-api` is separate: it
requires `ARISTOTLE_API_KEY`, sets the explicit live-test flag, has a bounded timeout, and
creates test-owned live Projects. It is the only paid-service integration evidence and is not
part of the ordinary offline commands.

## Dependencies And Type Checking

The package requires Python 3.11 and includes `aristotlelib>=2.1.0`, `mcp`, `anyio`, `python-dotenv`, and `pathspec`. The server uses `anyio` for cancellable bounded waits and `pathspec` for project file selection.

Mypy runs with strict settings. `stubs/aristotlelib/` contains a `.pyi` declaration because the runtime SDK does not expose all type information needed by this project's strict checks. The stub must mirror verified public SDK behavior, not private implementation details.

## Error Handling And Security

API, validation, filesystem, and archive errors return:

```json
{
  "status": "error",
  "error_type": "validation | api | filesystem | archive",
  "message": "human-readable explanation"
}
```

Validation covers missing required text, invalid wait bounds, incompatible submission inputs,
missing local files, and context filename collisions. Filesystem errors cover output
reservation, temporary download, copying, and replacement failures. Archive errors cover
unsafe members or links. SDK and service failures remain API errors. These categories let an
MCP client distinguish caller input, local I/O, archive safety, and remote-service failures.

The API key is read from the environment and should never be logged. The MCP server does not execute arbitrary local Lean code. It submits files to the native service contract, validates local paths and archives at its boundary, and uses explicit finite waits so a service request cannot create an interactive or unbounded local process.

## References

- [Aristotle API](https://aristotle.harmonic.fun/)
- [aristotlelib on PyPI](https://pypi.org/project/aristotlelib/)
- [Model Context Protocol](https://modelcontextprotocol.io/)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
