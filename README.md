# Aristotle MCP Server

An MCP (Model Context Protocol) server for [Aristotle](https://aristotle.harmonic.fun/), Harmonic's Lean 4 theorem proving service. It exposes the native `aristotlelib>=2.1.0` Project, AgentTask, and Event API through a small, explicit MCP surface.

Use it when an assistant needs to submit Lean work, follow its progress, answer a question from the Aristotle agent, retrieve project files, fill `sorry` statements, or turn a mathematical description into Lean.

## What Changed In The Native 2.1 API

This server has exactly 16 tools. It no longer exposes legacy project-job tools such as `check_proof`, `check_prove_file`, `check_formalize`, `cancel_project`, `get_solution`, `get_solution_if_complete`, or `get_input`.

The native model has three separate identifiers:

- A **Project** has a `project_id`. It owns the submitted prompt and files. Native project statuses are `idle` and `running`.
- An **AgentTask** has a `task_id` and belongs to a project. It represents one unit of agent work. Its native status is returned directly, for example `queued`, `in_progress`, `complete`, `complete_with_errors`, `out_of_budget`, `failed`, or `canceled`.
- An **Event** has an `event_id` and belongs to a task. Events describe messages, progress, files, and agent questions.

Keep all IDs returned by a submission. A workflow result contains both `project_id` and `task_id`; an agent question is identified by `event_id`.

## Tools Provided

| Tool | Description |
|------|-------------|
| `submit_project` | Create a Project from a directory or tar archive and return the initial task. |
| `list_projects` | List native Projects in newest-first order, with optional native status filters. |
| `get_project` | Refresh and inspect one Project. |
| `continue_project` | Send an `INSTRUCT` follow-up to a Project, optionally uploading files. |
| `ask_project` | Send an `ASK` follow-up that may cause the agent to request an answer. |
| `list_project_tasks` | List the AgentTasks for a Project. |
| `get_task` | Refresh and inspect one AgentTask. |
| `wait_task` | Poll a task with a finite deadline and stop for completion, timeout, or an agent question. |
| `cancel_task` | Cancel a nonterminal AgentTask. |
| `list_task_events` | List the Events emitted by a task. |
| `get_event` | Refresh and inspect one Event. |
| `answer_question` | Answer a pending `sent` `agent_question` Event. |
| `download_project_files` | Atomically download the native project archive. |
| `prove` | Submit an inline Lean proof request, with optional context files and hint. |
| `prove_file` | Submit the nearest Lake project for one Lean file and optionally write its solved file. |
| `formalize` | Submit a natural-language formalization request, optionally with one Lean context file. |

Detailed result schemas and design rationale are in [docs/ARISTOTLE_MCP_DESIGN.md](docs/ARISTOTLE_MCP_DESIGN.md). Worked assistant flows are in [docs/USER_STORIES.md](docs/USER_STORIES.md).

## Installation

### Prerequisites

Install [uv](https://docs.astral.sh/uv/), then obtain an API key from [aristotle.harmonic.fun](https://aristotle.harmonic.fun/).

```bash
# macOS
brew install uv

# macOS or Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

export ARISTOTLE_API_KEY="your-api-key-here"
```

The server depends on `aristotlelib>=2.1.0`, so both real and mock installations use the same public model surface.

### Add To Claude Code

Register directly from the repository:

```bash
claude mcp add aristotle -e ARISTOTLE_API_KEY=$ARISTOTLE_API_KEY -- uvx --from git+https://github.com/septract/lean-aristotle-mcp aristotle-mcp
```

Add `--scope user` to make it available to every local project:

```bash
claude mcp add aristotle --scope user -e ARISTOTLE_API_KEY=$ARISTOTLE_API_KEY -- uvx --from git+https://github.com/septract/lean-aristotle-mcp aristotle-mcp
```

Or add an MCP entry to `~/.claude.json`:

```json
{
  "mcpServers": {
    "aristotle": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--from", "git+https://github.com/septract/lean-aristotle-mcp", "aristotle-mcp"],
      "env": {
        "ARISTOTLE_API_KEY": "${ARISTOTLE_API_KEY}"
      }
    }
  }
}
```

Verify the registration with `claude mcp list` or `claude mcp get aristotle`. In Claude Code, `/mcp` also shows the connection state.

### Add To Claude Desktop

Add the server to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "aristotle": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/septract/lean-aristotle-mcp", "aristotle-mcp"],
      "env": {
        "ARISTOTLE_API_KEY": "your-api-key-here"
      }
    }
  }
}
```

Claude Desktop does not expand shell variables in this configuration, so provide the key through its supported environment configuration.

## Mock Mode

Set `ARISTOTLE_MOCK=true` to use the offline, in-memory implementation:

```bash
claude mcp add aristotle-mock -e ARISTOTLE_MOCK=true -- uvx --from git+https://github.com/septract/lean-aristotle-mcp aristotle-mcp
```

Mock mode registers the same 16 tools and returns the same result shapes without an API key or network request. It stores Projects, AgentTasks, and Events only for the process lifetime. Mock project directories follow the SDK-style ignore and `.gitignore` behavior, so local test submissions behave like real directory collection. It is useful for tool integration, local development, and tests, not for validating a proof against the live service.

## Using The Native Lifecycle

### Submit And Track A Project

Submit a directory or one tar archive, then retain the returned Project and task objects:

```text
submit_project(
  prompt="Prove all sorry statements in this Lean project.",
  project_dir="tests/lean_project"
)
-> {
     "project": {"project_id": "project-...", "status": "running", ...},
     "task": {"task_id": "task-...", "project_id": "project-...", "status": "queued", ...}
   }
```

`project_dir` and `tar_file_path` are alternatives, not a pair. `public_file_path` and `agent_questions_setting` are passed to the native SDK. List operations accept a pagination key returned by the preceding page.

Use `get_task` for one refresh, or `wait_task` when a bounded wait is appropriate:

```text
wait_task(task_id="task-...", timeout_seconds=300, poll_interval_seconds=5)
-> {"outcome": "terminal", "task": {"status": "complete", ...}, "question": null, ...}
```

`wait_task` never calls `AgentTask.wait_for_completion` or `input()`. Its finite deadline covers initial lookup, refreshes, event paging, and polling. A successful wait has outcome `terminal`, `timed_out`, or `waiting_for_answer`; terminal status takes precedence over a pending question. If lookup expires before a task snapshot exists, it returns a structured API error because no `TaskResult` can be returned.

### Answer Agent Questions

An `ASK` follow-up asks the agent a question about a Project. An `INSTRUCT` follow-up continues work with instructions and may upload files. Use `continue_project` for `INSTRUCT`; uploaded files are accepted only while the native Project is `idle`.

```text
ask_project(
  project_id="project-...",
  prompt="Which theorem should I prove next?",
  agent_questions_setting=2  # AgentQuestionsSetting.TIMEOUT_15_MIN
)
-> {"task_id": "task-...", "status": "queued", ...}

wait_task(task_id="task-...", timeout_seconds=60)
-> {
     "outcome": "waiting_for_answer",
     "question": {"event_id": "event-...", "event_type": "agent_question", "status": "sent", ...}
   }

answer_question(event_id="event-...", answer="Prove the induction lemma first.")
```

Set `agent_questions_setting=2` (`AgentQuestionsSetting.TIMEOUT_15_MIN`) when creating an `ASK` follow-up that should permit agent questions. The default is `DISABLED`. `answer_question` accepts only a pending `sent` agent-question event. Use `list_task_events` or `get_event` when the question needs more context. Events include content plus optional file path, explanation, suggestions, and duration.

### Retrieve Files Safely

`download_project_files` saves the native project archive, typically to a `.tar.gz` destination. It reserves the destination first and writes through a temporary path. Existing paths are never replaced unless `overwrite=true` is explicit.

The Lean workflows apply the same care when reading solution archives. They accept only regular files and directories, rejecting absolute paths, parent traversal, symbolic links, hard links, FIFOs, devices, and all other member kinds before extracting a matching Lean file.

## Lean Workflows

The three workflow tools create native Projects and return `project_id` plus `task_id`, even when `wait=false`.

### Prove An Inline Snippet

`prove(code, context_files=None, hint=None, wait=True)` stages `proof.lean` with the supplied code. It can stage several context files, and the optional hint is written into the staged proof request.

```text
prove(
  code="theorem add_zero (n : Nat) : n + 0 = n := by sorry",
  hint="Use Nat.add_zero",
  wait=false
)
-> {"project_id": "project-...", "task_id": "task-...", "status": "queued", ...}
```

With `wait=true`, the workflow waits through `wait_task` and returns the contents of `proof.lean` only for `complete`, `complete_with_errors`, or `out_of_budget`, when the archive contains an exact matching file. `failed`, `canceled`, and nonterminal outcomes have no artifact. A matching file may still be absent, which is reported in `message` rather than invented as a proof result.

### Prove A File In Its Lake Project

`prove_file(file_path, output_path=None, wait=True)` locates the nearest ancestor with `lakefile.lean`, `lakefile.toml`, or `lean-toolchain`. That nearest Lake root, rather than the whole workspace, becomes the submitted project directory.

```text
prove_file("tests/lean_project/TestProject/Basic.lean")
-> {
     "project_id": "project-...",
     "task_id": "task-...",
     "status": "complete",
     "output_path": ".../Basic_aristotle.lean",
     ...
   }
```

When waiting, the default output filename is the input basename with `_aristotle.lean` inserted before the extension. The requested-file identity and archive match use the path relative to the submitted Lake root, such as `TestProject/Basic.lean`, not just its basename. Artifacts are retrieved only for `complete`, `complete_with_errors`, or `out_of_budget`; `failed`, `canceled`, and nonterminal outcomes have no artifact, and a matching file may still be absent. With `wait=false`, no output path is reserved or written; retain both IDs and later use `wait_task`, task events, and project downloads.

### Formalize Natural Language

`formalize(description, prove=False, context_file=None, wait=True)` stages the description as `description.txt` and asks Aristotle to save its Lean result as `formalize.lean`.

```text
formalize(
  description="The sum of two even natural numbers is even.",
  prove=true,
  context_file="src/Definitions.lean",
  wait=false
)
```

`context_file` is singular. This is the exact server signature and differs deliberately from `prove`, which accepts the plural `context_files`. With `wait=true`, the result returns matching `formalize.lean` contents when available.

## Local Development

Clone the repository, then install the full development environment:

```bash
git clone https://github.com/septract/lean-aristotle-mcp.git
cd lean-aristotle-mcp
uv sync --all-extras
```

The Makefile also supports the existing virtual environment flow:

```bash
make venv
make install-dev
make run
make run-mock
```

Common checks are:

```bash
make check       # Ruff and mypy
make test        # Offline mock suite
make test-lean   # Fetch Lean cache, then build the test Lake project
make verify      # Offline checks, tests, and Lean build
make build       # Build the wheel
```

`make test-api` is deliberately separate. It requires `ARISTOTLE_API_KEY`, uses a 60-second test timeout, and creates test-owned live Projects. It is an opt-in, paid integration check, not part of `make test`, `make test-all`, or `make verify`.

## Troubleshooting

### `spawn uvx ENOENT`

The MCP host cannot find `uvx`. Restart the host after installing uv, check `which uvx` in a terminal, or configure the full path to `uvx` when a GUI application has a different `PATH`.

### `ARISTOTLE_API_KEY not set`

Export the key in the environment that launches the MCP host, not only in an unrelated shell. Check the configured MCP entry, restart the host after changing its environment, or use `ARISTOTLE_MOCK=true` for offline work.

### A Task Did Not Finish

Do not use a removed `check_*` tool. Call `get_task` for one state refresh or `wait_task` with explicit finite timeout and polling values. If its outcome is `waiting_for_answer`, inspect the returned Event and call `answer_question` before waiting again.

### A Workflow Did Not Return Lean Code

Terminal task statuses are `complete`, `complete_with_errors`, `out_of_budget`, `failed`, and `canceled`. Workflows retrieve artifacts only for the first three. Read `status`, `output_summary`, and `message`; inspect task events; then use `download_project_files` if the whole project archive is needed. `prove_file` writes only an exact Lake-relative match when it is present.

## License And Links

MIT, see [LICENSE](LICENSE).

- [Aristotle API](https://aristotle.harmonic.fun/)
- [Harmonic](https://harmonic.fun/)
- [aristotlelib on PyPI](https://pypi.org/project/aristotlelib/)
- [Model Context Protocol](https://modelcontextprotocol.io/)
