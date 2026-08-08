"""Compile a scenario and stand it up on a live instance. Sprint 09, generalised.

Scenario 3 was deployed by hand, one call at a time, and "it works" was therefore a
statement about one afternoon rather than about the compiler. This module is the same
sequence written down once, so that deploying s1, s2 and s4 measures the compiler
instead of re-demonstrating it.

The order is not negotiable and each step exists because skipping it cost a day:

    1. the three OFFLINE checks      shape / values / order — before anything is sent
    2. preflight_import              refuses; never warns
    3. create_model                  201
    4. import_replace                204, octet-stream
    5. create_data_location          creates AND deploys, so it cannot re-point an
                                     existing location onto a different model
    6. verify_deploy                 poll to a TERMINAL status

Steps 1 and 2 are the whole point. A deploy that fails at step 5 with "Unexpected
Error" tells you almost nothing; the offline checks tell you which of the three
questions was answered wrong, and they answer it in milliseconds.

    round-trips != importable != deployable != runnable

This module can carry a scenario to DEPLOYABLE. It says nothing about runnable — no
data is loaded here, and `DL_READY` is not evidence that a job would succeed.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import agent.rest as R
from agent.browser.inspect import read_data_locations, read_target_version
from agent.compile.blocks import check as shape_check
from agent.compile.blocks import render as shape_render
from agent.compile.emit import emit
from agent.ir import decisions, depends
from agent.ir.advise import advise
from agent.ir.schema import IR
from agent.ir.validate import errors, validate
from agent.safety import Refused, preflight_import, verify_deploy

ROOT = Path(__file__).resolve().parents[1]

#: A model whose version is read from the target it is about to be sent to. Any model
#: already on the instance will do — import is refused across product versions, so the
#: number is a property of the INSTANCE, not of the model it was read from.
VERSION_PROBE = ("CustomerTraining", "0.0")


@dataclass
class Result:
    scenario: str
    model: str
    steps: list[tuple[str, bool, str]] = field(default_factory=list)

    def step(self, name: str, ok: bool, detail: str = "") -> bool:
        self.steps.append((name, ok, detail))
        return ok

    @property
    def ok(self) -> bool:
        return all(s[1] for s in self.steps)

    def render(self) -> str:
        out = [f"=== {self.scenario} -> {self.model}"]
        for name, ok, detail in self.steps:
            out.append(f"  [{'ok ' if ok else 'FAIL'}] {name}")
            if detail:
                out += [f"        {ln}" for ln in detail.splitlines()]
        return "\n".join(out)


def _batches(target: R.Target, location: str) -> list[dict]:
    """Loads on a location, for the batch-in-progress check.

    The `data` domain has NO path prefix. Read rather than assumed to be empty: an
    unfinished batch is what makes xDM refuse to change the deployed edition, and
    assuming none is how that refusal arrives mid-import instead of in preflight.
    A read failure yields [] and is NOT treated as "no batches" anywhere that matters —
    the deploy itself still refuses, just less helpfully.
    """
    # PAGED, because the endpoint is: `$limit` defaults to 100 and the listing is
    # newest-first, so a bare GET is "the last 100 loads" silently presented as "the
    # loads". Found on a hub holding 1090 — 901 of them a runaway create-loop burst
    # (52 creates/second for 17 seconds) that a single unpaged read placed entirely
    # out of sight of this check. Same failure class as reading `status` where the
    # API writes `loadStatus`: the check ran, matched nothing it should have, passed.
    out: list[dict] = []
    offset = 0
    try:
        while True:
            rows = json.loads(R.get(
                target, f"loads/{location}?$offset={offset}&$limit=500")[1])
            rows = rows if isinstance(rows, list) else rows.get("loads", [])
            out += rows
            if len(rows) < 500:
                return out
            offset += 500
    except Exception:
        return out


def _model_names(target: R.Target) -> set[str]:
    """Which models the instance already holds. Read, never assumed: whether this run
    CREATES or REPLACES decides whether the D7 snapshot check has anything to say."""
    body = R.get(target, "app-builder/models")[1]
    rows = json.loads(body)
    rows = rows if isinstance(rows, list) else rows.get("models", [])
    return {r.get("name") for r in rows}


# ------------------------------------------------------------------ offline, first
def compile_scenario(ir_dir: Path, *, platform_version: str,
                     repository_version: str) -> tuple[IR, str, Result]:
    """Load, check three ways, emit. Raises on anything blocking.

    The checks run BEFORE the emit that would be sent, and a blocking finding stops
    here rather than at the instance, because the instance's account of the same
    failure is a Java trace in a log file nobody can reach over REST.
    """
    res = Result(ir_dir.parent.name, "?")
    cert, app = ir_dir / "certify.yaml", ir_dir / "app.yaml"
    ir = IR.load(ir_dir / "model.yaml", cert if cert.exists() else None,
                 app if app.exists() else None)
    res.model = ir.model_ir.model.name

    # 1 — are the VALUES justified?
    iss = validate(ir)
    blocking = errors(iss)
    res.step("validate", not blocking,
             "\n".join(i.render() for i in iss) if iss else "0 issues")
    if blocking:
        raise Refused(f"{len(blocking)} blocking IR issue(s):\n"
                      + "\n".join(i.render() for i in blocking))

    gaps = advise(ir)
    # Gaps never block — they are questions. Recorded so that "deployed" is never
    # confused with "designed", and so an unanswered question is visible in the log
    # of the run that shipped it.
    res.step("advise", True, f"{len(gaps)} open question(s): "
             + ", ".join(f"{g.rule}@{g.where}" for g in gaps) if gaps else "0 gaps")

    # 2 — does it RUN in the right order?
    order = depends.order_violations(ir)
    # Only the NULL-hashing ones refuse. An in-place producer leaves the value
    # populated, so a consumer running first reads the raw inbound value — which is
    # what a capture-the-evidence enricher is for. Reported below either way.
    blocking = depends.blocking_violations(ir)
    cyc = depends.cycles(ir)
    miss = depends.missing_prerequisites(ir)
    res.step("depends", not (blocking or cyc),
             f"{len(order)} order violation(s) ({len(blocking)} blocking), "
             f"{len(cyc)} cycle(s), {len(miss)} missing prerequisite(s)\n"
             + depends.render(ir))
    if blocking or cyc:
        raise Refused(depends.render(ir))

    # 3 — is the SHAPE right?
    xml = emit(ir.model_ir, platform_version=platform_version,
               repository_version=repository_version,
               certify=ir.certify, app=ir.app)
    findings = shape_check(xml)
    # `null-ref` joins the blocking kinds on 2026-08-06. A ref slot the product never
    # leaves null, emitted null, is the shape that passes every element-set check,
    # imports at 204, EXPORTS cleanly, and then dies at deploy with a bare "Unexpected
    # Error" — the s3 stepper did exactly that with three of them. Measured before
    # switching it on: 0 findings on s1, s2 and s4, and exactly the three broken slots
    # on s3. A gate that fires only on the thing that was already broken is the kind
    # worth having (LESSONS §3, §4).
    # `duplicate-position` joins them on 2026-08-07. It is the first kind here that
    # does NOT stop a deploy or a job — s4 ran with six of them — so it is a gate on
    # the model being VALID rather than on it working today. The Application Builder's
    # Validation view is the register that says so, and nothing offline could until
    # now (LESSONS §56).
    hard = [f for f in findings
            if f.kind in ("encoding", "unknown", "null-ref", "duplicate-position")]
    res.step("shape", not hard,
             shape_render(findings) if findings else f"{len(xml)} bytes, clean")
    if hard:
        raise Refused(shape_render(hard))

    res.step("decisions", True, decisions.report(ir))
    return ir, xml, res


# -------------------------------------------------------------------- then the wire
def deploy_scenario(target: R.Target, ir_dir: Path, *,
                    location: str | None = None, datasource: str | None = None,
                    snapshot: Path | None = None, repo: Path = ROOT,
                    dry_run: bool = False) -> Result:
    """Carry one scenario from YAML to a deployed data location.

    `location` must NOT already exist. `create_data_location` is used rather than
    `deploy` precisely because it cannot re-point a location that is serving something
    else — the failure mode D7's preflight exists to refuse.

    With no `location`, this stops after Import-Replace. That is a REAL and separate
    bar — the importer parses the whole model and rejects structural errors and
    dangling references — and it is worth reaching on its own when no datasource is
    free, which on a shared instance is the normal case rather than the exception.
    A run that stops there says IMPORTABLE and must not be read as DEPLOYABLE.
    """
    ver = read_target_version(target, *VERSION_PROBE)
    ir, xml, res = compile_scenario(
        ir_dir, platform_version=ver.platform_version,
        repository_version=ver.repository_version)
    model = ir.model_ir.model.name

    existing = {l.name: l for l in read_data_locations(target)}

    # Three cases, and only the third is destructive-of-something-else:
    #   absent            -> create_data_location (creates AND deploys)
    #   serves THIS model -> deploy, i.e. a REDEPLOY. Not destructive of another model,
    #                        and the case the full preflight_import was written for.
    #   serves ANOTHER    -> refuse. `deploy` would silently replace it.
    redeploy = bool(location) and location in existing
    if redeploy and existing[location].model != model:
        res.step("location is usable", False,
                 f"{location} serves {existing[location].model}, not {model}. "
                 f"Deploying here would REPLACE a different model. Pick a new name, or "
                 f"free this one deliberately with "
                 f"rest.delete_data_location(..., drop_schema=True).")
        return res
    res.step("location is usable", True,
             ("no location requested — this run stops at IMPORTABLE" if not location
              else f"{location} already serves {model} — this is a REDEPLOY"
              if redeploy else f"{location} does not exist yet"))

    # The preflight wants a DataLocation to inspect, and there is not one yet. That is
    # the honest state: the D7 checks that speak to an EXISTING target cannot apply to
    # a location being created. The ones that still apply are run explicitly, so this
    # path is gated rather than merely un-gated for want of an object to gate on.
    from agent.safety import (Preflight, check_live_matches_snapshot,
                              check_no_batch_in_progress, check_target_location,
                              check_version_pin, check_working_tree_clean)
    pre = Preflight()
    check_working_tree_clean(pre, repo)
    check_version_pin(pre, ver.platform_version, ver.platform_version)

    # On a REDEPLOY the location exists, so the checks that need one finally apply:
    # DEV-only (D9), DL_READY, technology match, and no batch holding the edition.
    # A suspended batch is a LOCK, not a transient — xDM refuses to change a deployed
    # edition while one is in progress, and the refusal arrives mid-import otherwise.
    if redeploy:
        check_target_location(pre, existing[location], model,
                              ir.model_ir.model.target_technology)
        check_no_batch_in_progress(pre, _batches(target, location))

    # THE D7 CHECK, and it was missing here until a 409 exposed why it matters.
    #
    # Import-Replace DELETES the existing edition. D7 accepts that on the stated
    # precondition that git holds a snapshot to fall back on — so the check belongs on
    # every run where the model ALREADY EXISTS, which is every re-run, and re-running
    # is the normal case rather than the exceptional one. Skipping it because this
    # function usually creates the model would have made the guard fire precisely never.
    #
    # Only meaningful once the model is on the instance; on a genuine first import
    # there is nothing to lose and the check says so out loud rather than passing
    # silently.
    exists = model in _model_names(target)
    if exists:
        snap = snapshot or (ROOT / "live" / f"{model}.xml")
        check_live_matches_snapshot(pre, target, model, "0.0", snap, repo)

    res.step("preflight", pre.ok, pre.render())
    if not pre.ok:
        return res

    if dry_run:
        res.step("dry run", True, "stopped before the first write")
        return res

    # 409 is "already exists", not a failure — Import-Replace is about to overwrite the
    # edition anyway, and the D7 check above is what makes that defensible.
    if exists:
        res.step("create_model", True, f"{model} already exists — skipped")
    else:
        code, body = R.create_model(target, model, ir.model_ir.model.label or model,
                                    f"scenario {ir_dir.parent.name}")
        if not res.step("create_model", code in (200, 201),
                        f"HTTP {code} {body[:200].decode('utf8', 'replace')}"):
            return res

    code, body = R.import_replace(target, model, "0.0", xml.encode())
    if not res.step("import_replace", code in (200, 204),
                    f"HTTP {code} {body[:400].decode('utf8', 'replace')}"):
        return res

    if not location:
        res.step("IMPORTABLE", True,
                 "stopped after Import-Replace: no data location was requested. "
                 "importable != deployable != runnable — nothing below this bar is "
                 "claimed.")
        if snapshot:
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            snapshot.write_text(xml)
            res.step("snapshot written", True, str(snapshot))
        return res

    # A 5xx here does NOT mean nothing happened, and it does NOT mean something did.
    # Both have been observed from this one call:
    #   2026-08-04  500 "Unexpected Error"        location CREATED and deploying
    #   2026-08-05  500 "This datasource already  nothing created
    #                    contains data location tables"
    # So the status code is not the answer and neither is the message. The re-read is,
    # and it is unconditional — including after a 201, because a 201 is a statement
    # about the create and the deploy it triggers is asynchronous.
    if redeploy:
        code, body = R.deploy(target, location, model, "0.0")
        if not res.step("deploy", code in (200, 204),
                        f"HTTP {code} {body[:400].decode('utf8', 'replace')}"):
            return res
    else:
        code, body = R.create_data_location(
            target, location, datasource, model, "0.0",
            label=ir.model_ir.model.label or model,
            description=f"{ir_dir.parent.name} — compiler output")
        detail = f"HTTP {code} {body[:400].decode('utf8', 'replace')}"
        created = location in {l.name for l in read_data_locations(target)}
        if code >= 500:
            detail += (f"\n  re-read after the 5xx: location "
                       f"{'EXISTS — the write landed' if created else 'ABSENT — nothing was created'}"
                       f". NOT retried.")
        if not res.step("create_data_location", created, detail):
            return res

    outcome = verify_deploy(target, location, model=model, edition="0.0")
    res.step("verify_deploy", outcome.ok, str(outcome))

    if snapshot:
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_text(xml)
        res.step("snapshot written", True, str(snapshot))
    return res


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("env", help=".env file naming the target instance")
    p.add_argument("ir_dir", help="scenario ir/ directory")
    p.add_argument("--location", help="omit to stop at IMPORTABLE")
    p.add_argument("--datasource")
    p.add_argument("--snapshot")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args(argv)

    target = R.Target.from_env(R.load_env_file(a.env))
    try:
        res = deploy_scenario(target, Path(a.ir_dir), location=a.location,
                              datasource=a.datasource, dry_run=a.dry_run,
                              snapshot=Path(a.snapshot) if a.snapshot else None)
    except Refused as e:
        print(f"REFUSED\n{e}")
        return 2
    print(res.render())
    return 0 if res.ok else 1


if __name__ == "__main__":
    sys.exit(main())
