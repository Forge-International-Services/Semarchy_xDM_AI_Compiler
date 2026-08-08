"""Check the artifacts the advisory phases produce. Sprint 03.

Phases 3 and 4 emit IR alongside their narrative, so most of sprint 03's acceptance
criteria stop being reading tasks and become runs of machinery that already exists:

    scenario 3 bins every probabilistic rule   -> IR-010
    PRE_CONSO / POST_CONSO correct             -> IR-009
    fuzzy entity has a matcher                 -> IR-001
    ID-matched entity has a single PK          -> IR-003
    publisher codes uppercase                  -> IR-006
    citations resolve                          -> citation.validate
    >=90% of claims cited                      -> citation.coverage

The narrative still matters — it is what a human reviews and what explains *why* — but
it is no longer the only place a design decision is recorded. Emitting IR also removes
a translation step: sprint 05 compiles the artifact the user approved at G4, rather
than re-deriving it from prose.

A project directory looks like:

    out/<project>/
        01-intake.md  02-certification.md  03-model-plan.md  04-app-plan.md
        ir/model.yaml  ir/certify.yaml
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from agent import corpus
from agent.ir.advise import Gap, advise
from agent.ir.schema import IR
from agent.ir.validate import Issue, errors, validate
from agent.tools import citation

NARRATIVE = ("01-intake.md", "02-certification.md", "03-model-plan.md", "04-app-plan.md")
CITATION_COVERAGE_MIN = 0.90
CORPUS_FETCHER = corpus.FETCHER


@dataclass
class Report:
    project: str
    missing: list[str] = field(default_factory=list)
    fabricated: list[citation.Problem] = field(default_factory=list)
    coverage: float = 0.0
    ir_issues: list[Issue] = field(default_factory=list)
    gaps: list[Gap] = field(default_factory=list)
    unexplained: list[str] = field(default_factory=list)
    #: True in an export pack: the corpus is absent, so the two citation criteria were
    #: not run at all. Distinct from "they ran and passed" and from "they ran and
    #: failed" — reporting either of those here would be reporting a lower bar as a
    #: higher one.
    corpus_absent: bool = False

    @property
    def ok(self) -> bool:
        """Everything a machine can decide. Gaps are deliberately NOT here: an open
        design question is not a failing build, and treating it as one would train the
        reader to suppress the questions instead of answering them.

        `corpus_absent` IS here, and it makes ok False. Not because anything failed,
        but because two of the criteria were never evaluated, and a green verdict over
        an unevaluated criterion is the exact reporting error this repo is built to
        avoid. render() says which of the two it is."""
        return (not self.missing
                and not self.corpus_absent
                and not self.fabricated
                and self.coverage >= CITATION_COVERAGE_MIN
                and not errors(self.ir_issues)
                and not self.unexplained)

    def render(self) -> str:
        lines = [f"# {self.project}", ""]
        verdict = "INCOMPLETE" if self.corpus_absent else ("PASS" if self.ok else "FAIL")
        lines.append(f"automated checks: **{verdict}**")
        lines.append("")
        if self.missing:
            lines.append(f"- missing artifacts: {', '.join(self.missing)}")
        if self.corpus_absent:
            lines.append("- fabricated citations: NOT CHECKED — the knowledge corpus is "
                         "not in this tree")
            lines.append("- citation coverage: NOT CHECKED — same reason")
            lines.append(f"    - restore it with `{CORPUS_FETCHER}`, then re-run")
        else:
            lines.append(f"- fabricated citations: {len(self.fabricated)} (must be 0)")
            for p in self.fabricated[:5]:
                lines.append(f"    - {p.citation} — {p.reason}")
            lines.append(f"- citation coverage: {self.coverage:.0%} "
                         f"(min {CITATION_COVERAGE_MIN:.0%})")
        errs = errors(self.ir_issues)
        lines.append(f"- ir_validate: {len(errs)} errors, "
                     f"{len(self.ir_issues) - len(errs)} warnings")
        for i in self.ir_issues[:8]:
            lines.append(f"    - {i.render().splitlines()[0]}")
        if self.unexplained:
            lines.append(f"- IR objects the narrative never mentions: "
                         f"{', '.join(self.unexplained)}")
        if self.gaps:
            lines += ["", f"## Open design questions ({len(self.gaps)})", ""]
            for g in self.gaps:
                lines.append("- " + g.render().replace("\n    ", "\n  "))
        lines += ["", "Still needs a human:",
                  "- is the reasoning correct?",
                  '- "I would build from this"?']
        return "\n".join(lines)


def check(project_dir: str | Path) -> Report:
    """Run every automated criterion over one scenario's artifacts."""
    d = Path(project_dir)
    rep = Report(project=d.name)

    rep.missing = [n for n in NARRATIVE if not (d / n).is_file()]
    prose = "\n".join((d / n).read_text() for n in NARRATIVE if (d / n).is_file())
    if prose:
        try:
            rep.fabricated = citation.validate(prose)
        except corpus.CorpusMissing:
            # Not a failure of the scenario. The two citation criteria simply cannot
            # be evaluated here, and `ok` reports that as INCOMPLETE rather than
            # either PASS or FAIL.
            rep.corpus_absent = True
        else:
            cited, uncited = citation.coverage(prose)
            total = cited + uncited
            # No claims at all is not 100% — it means the phase produced nothing
            # checkable.
            rep.coverage = cited / total if total else 0.0

    model, certify = d / "ir" / "model.yaml", d / "ir" / "certify.yaml"
    if model.is_file():
        ir = IR.load(model, certify if certify.is_file() else None)
        rep.ir_issues = validate(ir)
        rep.gaps = advise(ir)
        rep.unexplained = unexplained_objects(ir, prose)
    else:
        rep.missing.append("ir/model.yaml")
    return rep


def check_all(root: str | Path) -> list[Report]:
    return [check(p) for p in sorted(Path(root).iterdir()) if p.is_dir()]


def unexplained_objects(ir: IR, prose: str) -> list[str]:
    """Named objects that exist in the IR but appear nowhere in the narrative.

    The gate approves the narrative; the compiler builds the IR. Anything present in
    one and not the other was never really approved. This catches the additions —
    something in the build nobody signed off. The reverse case (designed in prose,
    dropped from the IR) is what the CA rules catch by absence, and what the reviewer
    rubric checks by hand, because prose cannot be diffed reliably.
    """
    names: list[str] = []
    m, c = ir.model_ir, ir.certify
    names += [e.name for e in m.entities] + [p.name for p in m.publishers]
    names += [l.name for l in m.lov_types] + [t.name for t in m.complex_types]
    names += [r.name for r in m.references]
    names += [e.name for e in c.enrichers] + [v.name for v in c.validations]
    names += [s.name for s in c.survivorship]
    names += [r.name for x in c.matchers for r in x.rules]
    return sorted({n for n in names if n and n not in prose})
