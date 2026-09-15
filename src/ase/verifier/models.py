from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GateResult:
    name: str
    passed: bool
    details: str
    duration_ms: float = 0.0


@dataclass(frozen=True, slots=True)
class VerificationReport:
    gates: tuple[GateResult, ...]

    @property
    def passed(self) -> bool:
        return all(gate.passed for gate in self.gates)
