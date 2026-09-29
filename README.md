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

`src/jev_agent/` runs the pipeline above as a durable, resumable, policy-bounded job (checkpoints, recovery, bounded retries, a JEV judgment, budgets, escalation, execution history). See `specs/` for the design.

### The execution console

A local web app that shows what the system is for and lets you watch it work. The frontier model proposes; deterministic Python policy decides.

```powershell
$env:TYPESAFE_API_KEY = "..."   # optional: live JEV judgments (without it, policy's fixed rule applies)
python -m jev_agent.console --database-url sqlite:///./demo_console.db
```

Open <http://127.0.0.1:8000>:

- **Overview**: what the system does, headline numbers, recent jobs.
- **How it works**: a diagram of the governed loop and who holds authority at each step.
- **Tour**: six reliability patterns, each with a story to run.
- **Run a scenario** (any page): pick a story and watch the job move through Propose → Apply → Verify live, with each JEV judgment and policy decision shown as it happens.
  - Stories: happy path, crash and resume, retry then pass, JEV says stop, retry budget runs out, time budget runs out, a step raises.
- **Jobs / Escalations**: filter jobs; resolve escalations with a note.

Simulated runs use the real runner, checkpoints, retries, rollback, budgets and escalation. Propose, Apply and Verify are simulated, so no Anthropic credit is spent and `target/fleetops` is never touched. The JEV judgment is the live TypeSafe API: one call per failed Verify. Only one simulated run runs at a time. The crash-and-resume story stops as **Interrupted** until you click **Resume**, which runs the real recovery path.

The console never starts a real run. The console binds to `127.0.0.1` only and has no authentication. To browse the store real runs write to, launch it with no `--database-url` (it reads `./jev_agent.db`).

To fill a database with one finished job per story in one go (a few TypeSafe calls if the key is set):

```powershell
python -m jev_agent.demo_console_seed --database-url sqlite:///./demo_console.db --reset
```

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
