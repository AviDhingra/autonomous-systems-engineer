# Verified Engineering Agent — Minimal v0.1

A small Claude-powered coding agent that investigates a FleetOps bug through bounded read/search tools, proposes one application-file replacement, and accepts the change as verified only when pytest, Ruff, and mypy independently pass.

## Architecture

```text
ticket.md
   ↓
agent.py
   ↓
Anthropic Claude
   ↕
read_file / search_code
   ↓
FixProposal
   ↓
apply_fix.py
   ↓
allowed FleetOps application file
   ↓
verify.py
   ├── pytest
   ├── Ruff
   └── mypy
   ↓
VERIFIED / FAILED
```

## Trust boundary

Claude can search and read FleetOps source/tests, but it does not receive arbitrary filesystem write or shell access.

The model returns one structured `FixProposal`:

- `file_path`
- `explanation`
- `new_content`

Local Python accepts writes only to an existing file under `target/fleetops/app/`.

A repair is `VERIFIED` only when pytest, Ruff, and mypy all return success. There is no automatic repair retry.

## S01 demo — duplicate telemetry retry

The committed FleetOps baseline is healthy. The scenario patch removes the idempotency lookup from `TelemetryService.ingest()` so a retry with the same `device_id` + `request_id` creates another logical telemetry event.

From the repository root:

```powershell
python -m pytest target/fleetops/tests/test_telemetry_service.py::test_retry_is_idempotent -vv

git apply --check scenarios/S01-duplicate-telemetry/bug.patch
git apply scenarios/S01-duplicate-telemetry/bug.patch

python -m pytest target/fleetops/tests/test_telemetry_service.py::test_retry_is_idempotent -vv

python -m ase.main
```

The final command asks Claude to investigate, applies one validated application-file replacement, shows the resulting Git state, and runs pytest + Ruff + mypy.

## Project 2 — governed jobs and the execution console

`src/jev_agent/` runs the pipeline above as a durable, resumable, policy-bounded job (checkpoints, recovery, bounded retries, a JEV judgment, budgets, escalation, execution history). See `specs/` for the design. The execution console is a local, read-mostly web view over the same SQLite store; its one write action is resolving an escalation.

To see it without spending any API credit, seed a demo database with fake steps and open the console:

```powershell
python -m jev_agent.demo_console_seed --database-url sqlite:///./demo_console.db
python -m jev_agent.console --database-url sqlite:///./demo_console.db
```

Then open <http://127.0.0.1:8000>. The seed creates one job per story: interrupt-and-resume, bounded retry, a JEV-informed retry and stop, retry-budget and wall-clock escalations, a resolved escalation, and a failed job. It refuses to write into a database that already has jobs unless you pass `--reset`. The console binds to `127.0.0.1` only and has no authentication. To browse the store real runs write to, launch it with no `--database-url` (it reads `./jev_agent.db`).

## Requirements

- Python environment with the project installed
- `ANTHROPIC_API_KEY` available as an environment variable
- Git
- project dependencies from `pyproject.toml`

## v0.1 limitations

- one scenario
- one proposed file replacement
- existing application files only
- no arbitrary shell tool for Claude
- no automatic retry after failed verification
- no multi-provider abstraction
- no LangChain / LangGraph
- no production sandbox or durable workflow runtime
