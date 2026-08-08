"""Approval gates G1-G8: the agent proposes, the user disposes.

Sprint 03 owns G1-G4. The rule that makes gates worth having is the CASCADE:
re-opening a gate invalidates every gate after it. Changing an entity type at G1
invalidates the certification design, the model plan and the application plan,
because matching and survivorship are meaningless under a different entity type.
Without the cascade a gate is just a checkbox someone ticked once.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from enum import IntEnum
from hashlib import sha256
from pathlib import Path


class Gate(IntEnum):
    G1_INTAKE = 1
    G2_CERTIFICATION = 2
    G3_MODEL_PLAN = 3
    G4_APPLICATION_PLAN = 4
    G5_SCAFFOLD = 5
    G6_IMPORT_REFINE = 6
    G7_DEPLOY_CONFIGURE = 7
    G8_ENHANCEMENT = 8


@dataclass(frozen=True)
class Approval:
    gate: int
    artifact: str          # path of what was approved
    digest: str            # sha256 of its content at approval time
    approved_at: str       # caller-supplied timestamp; no wall-clock in here


class GateError(RuntimeError):
    pass


class Gates:
    """Approval state for one project. Persisted as JSON beside the artifacts."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._approvals: dict[int, Approval] = {}
        if self.path.exists():
            for row in json.loads(self.path.read_text()):
                self._approvals[row["gate"]] = Approval(**row)

    # ---------------------------------------------------------------- queries
    def is_approved(self, gate: Gate) -> bool:
        return gate in self._approvals

    def approved_digest(self, gate: Gate) -> str | None:
        a = self._approvals.get(gate)
        return a.digest if a else None

    def require(self, gate: Gate) -> None:
        """Guard the entry to a phase. Raises rather than proceeding unapproved."""
        missing = [g for g in Gate if g < gate and g not in self._approvals]
        if missing:
            raise GateError(
                f"{gate.name} needs {', '.join(g.name for g in missing)} approved first")

    def stale(self, gate: Gate, artifact: str | Path) -> bool:
        """True when the artifact changed since it was approved."""
        a = self._approvals.get(gate)
        return a is not None and a.digest != digest(artifact)

    # ---------------------------------------------------------------- updates
    def approve(self, gate: Gate, artifact: str | Path, at: str) -> None:
        """Record approval. Every LATER gate is invalidated by construction."""
        self._approvals = {g: a for g, a in self._approvals.items() if g <= gate}
        self._approvals[int(gate)] = Approval(
            gate=int(gate), artifact=str(artifact), digest=digest(artifact), approved_at=at)
        self._save()

    def reopen(self, gate: Gate) -> list[Gate]:
        """Withdraw a gate and everything downstream. Returns what was invalidated."""
        lost = sorted(Gate(g) for g in self._approvals if g >= gate)
        self._approvals = {g: a for g, a in self._approvals.items() if g < gate}
        self._save()
        return lost

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        rows = [asdict(a) for _, a in sorted(self._approvals.items())]
        self.path.write_text(json.dumps(rows, indent=1))


def digest(artifact: str | Path) -> str:
    return sha256(Path(artifact).read_bytes()).hexdigest()
