# TODO

Ideas and follow-ups for the native Aristotle 2.1 MCP surface.

## Completed In The Native Migration

- The legacy project-job model, `check_*` polling tools, and separate solution/input download tools were replaced by native Project, AgentTask, and Event operations.
- Project listing is now available through `list_projects`, using native pagination and status filters.
- Bounded `wait_task` polling replaces interactive waiting and stops for a terminal task, timeout, or pending agent question.
- Lean workflows submit Projects and return both project and task IDs. `prove_file` writes a matching Lean output only while waiting.
- Archive handling now reserves output paths and rejects unsafe solution archive members before extraction.

## Maintenance

### Keep The SDK Contract Current

Keep `tests/test_sdk_contract.py` aligned with the installed `aristotlelib>=2.1.0` public models, enums, and signatures. In particular, verify native Project, AgentTask, and Event fields before documenting a dependency upgrade.

The local `.pyi` stub exists because this project runs mypy in strict mode with `disallow_any_unimported` and the SDK's runtime package does not provide every type detail needed by that check. It is a type-checking boundary, not a second implementation of the SDK. Update it only alongside a verified public SDK contract change.

### Live Service Checks

Run `make test-api` only when a real integration check is needed. It requires an API key, is bounded, and creates test-owned live Projects. Do not make it part of the default offline suite and do not describe it as having run unless it actually did.

## Possible Future Work

### Declaration-Level Requests

`prove` is useful for a focused snippet and `prove_file` submits the nearest Lake project. Before adding any declaration-level workflow, establish whether the SDK already supports that request shape.

If it does not, a parser would need to preserve imports, namespaces, local notation, and dependent declarations. That would be a separate feature, not a wrapper around the current file workflow.

### Project And Task Presentation

The MCP intentionally passes native statuses through rather than translating them into made-up proof states. If clients need a higher-level presentation, add it as documentation or client behavior first. Do not add another server-side job state machine unless native status information becomes insufficient.

### Configuration

Environment variables remain the supported configuration surface:

- `ARISTOTLE_API_KEY` configures the live SDK.
- `ARISTOTLE_MOCK=true` enables the offline in-memory implementation.

Avoid interactive setup. MCP servers run over stdio and `wait_task` is intentionally noninteractive, so configuration should be supplied by the MCP host.
