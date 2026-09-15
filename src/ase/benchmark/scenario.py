from dataclasses import dataclass
from pathlib import Path
import json

from pydantic import BaseModel, Field

from ase.verifier.policy import PatchPolicy


class ScenarioConfig(BaseModel):
    scenario_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    category: str = Field(min_length=1)
    allowed_patch_prefixes: list[str] = Field(default_factory=lambda: ["target/fleetops/app/"])
    max_changed_files: int = Field(default=4, ge=1)
    max_changed_lines: int = Field(default=120, ge=1)


@dataclass(frozen=True, slots=True)
class Scenario:
    root: Path
    ticket: str
    bug_patch: str
    solution_patch: str
    config: ScenarioConfig

    @property
    def oracle_tests(self) -> Path:
        return self.root / "oracle_tests"

    @property
    def patch_policy(self) -> PatchPolicy:
        return PatchPolicy(
            allowed_prefixes=tuple(self.config.allowed_patch_prefixes),
            max_changed_files=self.config.max_changed_files,
            max_changed_lines=self.config.max_changed_lines,
        )

    @classmethod
    def load(cls, root: Path) -> "Scenario":
        config_text = (root / "oracle.json").read_text(encoding="utf-8")
        config = ScenarioConfig.model_validate(json.loads(config_text))
        return cls(
            root=root,
            ticket=(root / "ticket.md").read_text(encoding="utf-8"),
            bug_patch=(root / "bug.patch").read_text(encoding="utf-8"),
            solution_patch=(root / "solution.patch").read_text(encoding="utf-8"),
            config=config,
        )
