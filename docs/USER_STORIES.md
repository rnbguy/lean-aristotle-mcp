# AI User Stories for Aristotle MCP

This document describes the main workflows an MCP client uses with the finalized native `aristotlelib>=2.1.0` surface. Each flow keeps the Project, task, and Event IDs that it receives. There are no legacy `check_*` tools or project-job IDs.

## Story 1: Stuck On A Proof Step

**Scenario:** An assistant can write the theorem statement but needs help with the proof.

**Flow:**

```text
AI: "The statement is clear, but I need a proof for the arithmetic step."

prove(
  code="theorem add_zero (n : Nat) : n + 0 = n := by sorry",
  hint="Use the standard natural-number addition lemma."
)

-> {
     "status": "complete",
     "project_id": "project-123",
     "task_id": "task-456",
     "code": "theorem add_zero (n : Nat) : n + 0 = n := by ...",
     "output_path": null,
     ...
   }
```

**Tool:** `prove(code, context_files=None, hint=None, wait=True)`.

**When to use:** A focused snippet has one or more `sorry` statements and does not need the full Lake project. Add `context_files` when local definitions or imports are needed.

## Story 2: A Lake Project With Multiple Files

**Scenario:** A user wants to prove all `sorry` statements in one file under a Lake project with Mathlib and local definitions.

**Flow:**

```text
AI: "I will submit the nearest Lean project so the theorem file keeps its project context."

prove_file("src/MyProject/Theorems.lean", wait=false)
-> {
     "status": "queued",
     "project_id": "project-123",
     "task_id": "task-456",
     "code": null,
     "output_path": null,
     "message": "Project submitted."
   }

AI: "I can continue with other work while that task runs."

wait_task("task-456", timeout_seconds=60, poll_interval_seconds=5)
-> {
     "outcome": "timed_out",
     "task": {"task_id": "task-456", "status": "in_progress", ...},
     "question": null,
     ...
   }

AI: "It is still running. I retained both IDs and can wait again later."
```

**Tools:** `prove_file`, `wait_task`, `get_task`, `list_task_events`, and `download_project_files`.

**When to use:** The input file belongs to a Lake project. `prove_file` searches upward for the nearest `lakefile.lean`, `lakefile.toml`, or `lean-toolchain`, then submits that directory rather than guessing at the workspace root.

When `wait=true`, `prove_file` writes a matching result to `Theorems_aristotle.lean` by default. It only writes the requested Lean basename when the completed project archive contains it.

## Story 3: Bounded Waiting For A Long-Running Task

**Scenario:** The assistant submits a proof that may take longer than a useful interactive turn.

**Flow:**

```text
prove(code="theorem hard : True := by sorry", wait=false)
-> {"project_id": "project-123", "task_id": "task-456", "status": "queued", ...}

get_task("task-456")
-> {"task_id": "task-456", "status": "in_progress", "percent_complete": 45, ...}

wait_task("task-456", timeout_seconds=120, poll_interval_seconds=10)
-> {"outcome": "terminal", "task": {"status": "complete", ...}, "question": null, ...}
```

**Tools:** `prove`, `get_task`, and `wait_task`.

**When to use:** Work is expected to take longer than one request should block. `wait_task` is not a hidden interactive loop. It returns only `terminal`, `timed_out`, or `waiting_for_answer`, with the latest Task state included in every response.

If the task reaches a terminal status but a workflow has no matching Lean output, read `output_summary` and task Events. Do not infer a proof result from the task status alone.

## Story 4: An Agent Needs An Answer

**Scenario:** The Aristotle agent asks a clarifying question while processing a follow-up.

**Flow:**

```text
ask_project(
  project_id="project-123",
  prompt="Which statement should receive the next proof attempt?"
)
-> {"task_id": "task-789", "status": "queued", ...}

wait_task("task-789", timeout_seconds=60)
-> {
     "outcome": "waiting_for_answer",
     "task": {"task_id": "task-789", "status": "in_progress", ...},
     "question": {
       "event_id": "event-012",
       "event_type": "agent_question",
       "status": "sent",
       "content": "Which theorem should I address first?",
       ...
     }
   }

answer_question("event-012", "Start with the induction lemma.")
-> {"event_id": "event-012", "status": "complete", ...}

wait_task("task-789", timeout_seconds=60)
```

**Tools:** `ask_project`, `wait_task`, `get_event`, `list_task_events`, and `answer_question`.

**When to use:** `wait_task` returns `waiting_for_answer` or task Events show a `sent` `agent_question`. Keep the `event_id`; `project_id` and `task_id` cannot substitute for it.

## Story 5: Continue A Project With Instructions And Files

**Scenario:** The user wants to change the direction of work after a Project becomes idle.

**Flow:**

```text
get_project("project-123")
-> {"project_id": "project-123", "status": "idle", ...}

continue_project(
  project_id="project-123",
  prompt="Use this supporting lemma and prove the remaining statements.",
  files=["src/MyProject/Supporting.lean"]
)
-> {"project_id": "project-123", "task_id": "task-999", "status": "queued", ...}
```

**Tools:** `get_project`, `continue_project`, and `wait_task`.

**When to use:** The follow-up is an instruction, not a question. `continue_project` uses native `INSTRUCT`; `ask_project` uses native `ASK`. Optional files are accepted only while the native Project is idle, so refresh the Project first when this matters.

## Story 6: Inspect Project History Without Guessing IDs

**Scenario:** An assistant has a Project ID from a previous operation and needs to inspect its tasks and events.

**Flow:**

```text
get_project("project-123")
-> {"project_id": "project-123", "status": "running", ...}

list_project_tasks("project-123", newest_first=true)
-> {
     "tasks": [
       {"task_id": "task-999", "status": "in_progress", ...},
       {"task_id": "task-456", "status": "complete", ...}
     ],
     "next_pagination_key": null
   }

list_task_events("task-999", newest_first=true)
-> {"events": [{"event_id": "event-012", "event_type": "message", ...}], ...}
```

**Tools:** `get_project`, `list_projects`, `list_project_tasks`, `get_task`, `list_task_events`, and `get_event`.

**When to use:** Inspect state rather than re-submitting a request. Native pagination keys are passed to the next list call unchanged. `list_projects` is part of the final API and returns native account-visible Project records.

## Story 7: Cancel The Correct Unit Of Work

**Scenario:** A new AgentTask was submitted with the wrong instruction, but the Project is still valuable.

**Flow:**

```text
get_task("task-999")
-> {"task_id": "task-999", "project_id": "project-123", "status": "queued", ...}

cancel_task("task-999")
-> {"task_id": "task-999", "project_id": "project-123", "status": "canceled", ...}
```

**Tool:** `cancel_task(task_id)`.

**When to use:** Cancel the AgentTask, not an invented project job. The Project and its earlier task history remain addressable by `project_id`.

## Story 8: Retrieve A Project Archive Safely

**Scenario:** The assistant needs the full archive after a task finishes, perhaps because the result includes more than one file.

**Flow:**

```text
download_project_files(
  project_id="project-123",
  output_path="artifacts/project-123.tar.gz"
)
-> {
     "status": "complete",
     "project_id": "project-123",
     "output_path": "/workspace/artifacts/project-123.tar.gz",
     "message": "Project files downloaded"
   }
```

**Tool:** `download_project_files(project_id, output_path=None, overwrite=False)`.

**When to use:** A caller wants the native archive. The destination is reserved and written atomically. A pre-existing destination is rejected unless `overwrite=true` is explicit.

## Story 9: Formalize A Natural-Language Statement

**Scenario:** A user has a mathematical claim and a local Lean definition that supplies context.

**Flow:**

```text
formalize(
  description="The sum of two even natural numbers is even.",
  prove=true,
  context_file="src/MyProject/Definitions.lean",
  wait=false
)
-> {
     "project_id": "project-321",
     "task_id": "task-654",
     "status": "queued",
     "code": null,
     ...
   }

wait_task("task-654", timeout_seconds=300)
```

**Tools:** `formalize` and `wait_task`.

**When to use:** Convert prose to Lean, optionally requesting a proof. `formalize` accepts exactly one optional `context_file`, while `prove` accepts a list named `context_files`. The workflow stages `description.txt` and asks for `formalize.lean`.

## Mock Mode For Local Workflows

**Scenario:** A contributor wants to test tool integration without an API key or a network request.

**Flow:**

```text
ARISTOTLE_MOCK=true make run-mock

submit_project(prompt="Prove the theorem", project_dir="tests/lean_project")
-> native-shaped Project and AgentTask results from the in-memory mock
```

**When to use:** Offline tests, MCP setup checks, and workflow development. Mock mode mirrors the server's public objects and question flow, but it is not proof evidence from the live Aristotle service. Use the opt-in `make test-api` only when a paid live integration check is explicitly required.
