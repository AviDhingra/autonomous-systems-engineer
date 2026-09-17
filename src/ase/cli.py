from dataclasses import asdict
from pathlib import Path
import argparse
import json

from ase.agent.chat_model_agent import ChatModelEngineeringAgent
from ase.agent.scripted import ScriptedEngineeringAgent
from ase.benchmark.runner import run_scenario
from ase.benchmark.scenario import Scenario
from ase.providers.factory import build_chat_model
from ase.providers.settings import ModelSettings


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run a Verified Engineering Agent benchmark scenario."
        )
    )

    parser.add_argument(
        "scenario",
        help=(
            "Scenario directory, for example "
            "scenarios/S01-duplicate-telemetry"
        ),
    )

    parser.add_argument(
        "--agent",
        choices=("scripted", "model"),
        default="scripted",
        help="Agent to use for the evaluation",
    )

    args = parser.parse_args()

    project_root = Path.cwd()

    scenario = Scenario.load(
        project_root / args.scenario
    )

    if args.agent == "scripted":
        agent = ScriptedEngineeringAgent(
            scenario.solution_patch
        )
    else:
        settings = ModelSettings.from_environment()

        model = build_chat_model(
            settings
        )

        agent = ChatModelEngineeringAgent(
            model=model,
            settings=settings,
        )

    report = run_scenario(
        project_root=project_root,
        scenario=scenario,
        agent=agent,
        results_dir=(
            project_root
            / "evals"
            / "results"
        ),
    )

    print(
        json.dumps(
            asdict(report),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()