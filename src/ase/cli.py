from dataclasses import asdict
from pathlib import Path
import argparse
import json

from ase.agent.scripted import ScriptedEngineeringAgent
from ase.benchmark.runner import run_scenario
from ase.benchmark.scenario import Scenario


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a Checkpoint 2 scenario with the deterministic scripted agent."
    )
    parser.add_argument(
        "scenario",
        help="Scenario directory, for example scenarios/S01-duplicate-telemetry",
    )
    args = parser.parse_args()

    project_root = Path.cwd()
    scenario = Scenario.load(project_root / args.scenario)
    agent = ScriptedEngineeringAgent(scenario.solution_patch)
    report = run_scenario(
        project_root=project_root,
        scenario=scenario,
        agent=agent,
        results_dir=project_root / "evals" / "results",
    )
    print(json.dumps(asdict(report), indent=2))


if __name__ == "__main__":
    main()
