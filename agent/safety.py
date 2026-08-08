"""Preflight before anything destructive. Sprint 09.

D7 accepted that Import-Replace DELETES the existing model edition, on the grounds
that "the local repo will use git, then the versions are snapshotted". That argument
has a stated precondition, in D7's own text:

    Git only protects what has been EXPORTED AND COMMITTED. Work done in the UI and
    not yet exported is invisible to git and is genuinely lost on Import-Replace.
    Therefore preflight MUST re-export the live model, diff it against the last
    commit, and refuse on an uncommitted delta.
    Without this guard the git argument does not actually hold.

This module is that guard. It is the reason a destructive import is defensible rather
than merely fast.

Every check REFUSES rather than warns. A warning on a destructive operation is a
warning nobody reads twice.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from agent.browser.inspect import DataLocation, technology_mismatch
from agent.compile.normalize import normalize
from agent.rest import Target, model_content


class Refused(RuntimeError):
    """Preflight said no. Never caught and downgraded — that is the whole point."""


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str = ""

    def __str__(self) -> str:
        return f"[{'ok ' if self.passed else 'REFUSE'}] {self.name}" + (
            f"\n        {self.detail}" if self.detail else "")


@dataclass
class Preflight:
    checks: list[Check] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.passed for c in self.checks)

    def add(self, name: str, passed: bool, detail: str = "") -> None:
        self.checks.append(Check(name, passed, detail))

    def render(self) -> str:
        head = "PREFLIGHT PASSED" if self.ok else "PREFLIGHT REFUSED"
        return "\n".join([head] + [str(c) for c in self.checks])

    def raise_if_refused(self) -> None:
        if not self.ok:
            raise Refused(self.render())


# --------------------------------------------------------------------------- git
def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(["git", "-C", str(repo), *args],
                         capture_output=True, text=True)
    if out.returncode:
        raise Refused(f"git {' '.join(args)} failed: {out.stderr.strip()[:200]}")
    return out.stdout


def committed_blob(repo: Path, path: Path) -> bytes | None:
    """The file's content AT HEAD, or None when it is not tracked.

    Deliberately HEAD rather than the working tree: a snapshot edited but not
    committed is exactly the state D7 says git does not protect.
    """
    rel = path.resolve().relative_to(repo.resolve())
    out = subprocess.run(["git", "-C", str(repo), "show", f"HEAD:{rel}"],
                         capture_output=True)
    return out.stdout if out.returncode == 0 else None


def uncommitted_paths(repo: Path) -> list[str]:
    lines = _git(repo, "status", "--porcelain").splitlines()
    return [ln[3:] for ln in lines if ln.strip()]


# ------------------------------------------------------------------------ checks
def check_live_matches_snapshot(pre: Preflight, target: Target, model: str,
                                edition: str, snapshot: Path, repo: Path) -> None:
    """THE D7 CHECK. Re-export the live model and compare against what git holds.

    Compared NORMALIZED, because a re-export churns audit stamps and serialization
    order and never reuses UUIDs — a byte diff would refuse every time and the guard
    would be turned off within a day.
    """
    live = model_content(target, model, edition)
    blob = committed_blob(repo, snapshot)
    if blob is None:
        # Nothing committed yet. Not a refusal: this is the first import, and there is
        # no prior work to lose. Recorded so it cannot be mistaken for "verified".
        pre.add("live model is committed", True,
                f"no snapshot at {snapshot} yet — treating as FIRST import. "
                f"Nothing to lose, and nothing verified either.")
        return
    if normalize(live) == normalize(blob):
        pre.add("live model is committed", True,
                f"live export matches {snapshot} at HEAD")
        return
    pre.add("live model is committed", False,
            f"THE LIVE MODEL HAS CHANGED SINCE THE LAST COMMIT. Import-Replace would "
            f"delete work that git does not have. Export it and commit before "
            f"importing:\n"
            f"          python -m agent.rest {snapshot}   # or re-export and diff\n"
            f"        Compared normalized, so this is a REAL semantic difference, not "
            f"audit churn.")


def check_working_tree_clean(pre: Preflight, repo: Path) -> None:
    dirty = uncommitted_paths(repo)
    pre.add("working tree is clean", not dirty,
            "" if not dirty else
            f"{len(dirty)} uncommitted path(s): {', '.join(dirty[:5])}"
            f"{'…' if len(dirty) > 5 else ''}. The IR that produced this XML must be "
            f"committed too, or the build output cannot be traced back to a source.")


def check_target_location(pre: Preflight, loc: DataLocation, model: str,
                          technology: str) -> None:
    """D9: dev-only until the model is refined. Promotion is a separate act."""
    pre.add("target is a DEV location", loc.is_dev,
            "" if loc.is_dev else
            f"{loc.name} is {loc.type}. D9 restricts deployment to DEV until the "
            f"model is refined; promotion goes through a CLOSED edition to a remote "
            f"repository, which is a deliberate separate step.")
    pre.add("target is ready", loc.is_ready,
            "" if loc.is_ready else
            f"{loc.name} status is {loc.status or 'unknown'}, not DL_READY. A location "
            f"in MAINTENANCE usually means a job failed and suspended the queue.")
    mismatch = technology_mismatch(technology, loc)
    pre.add("technology matches", mismatch is None, mismatch or "")
    if loc.deployed and loc.model != model:
        pre.add("target serves this model", False,
                f"{loc.name} currently serves {loc.model} {loc.edition_key}. "
                f"Deploying {model} here would replace a DIFFERENT model.")
    else:
        pre.add("target serves this model", True,
                f"{loc.name} serves {loc.model or 'nothing yet'}")


def check_no_batch_in_progress(pre: Preflight, batches: list[dict]) -> None:
    """OBSERVED 2026-08-03, and absent from the sprint design until it happened.

    A failed job does not clear itself. The queue policy is Suspend on Error, so the
    job hangs on the error point, the location flips to MAINTENANCE, and xDM refuses:
    "The deployed model edition cannot be changed because of 1 integration batch(es)
    in progress." Resuming re-runs the OLD deployed SQL, because job definitions are
    generated at deploy time — so the only exit is to cancel the batch first.

    A failed job is a LOCK, not a transient. Detecting it here turns a confusing
    mid-import refusal into a preflight message that says what to do.

    THIS CHECK COULD NOT FAIL UNTIL 2026-08-05. It read `b["status"]`; `GET loads/{loc}`
    returns **`loadStatus`**. So it read `""` for every row, matched nothing, and passed
    — against a live hub holding 49 non-terminal loads. A check keyed to a field name
    nobody had ever seen returned from the API, sitting in the module whose whole
    purpose is to refuse (LESSONS §3, §4). `tests/fixtures/loads_live.json` is now a
    real load list, so it can fail.

    And the predicate was wrong too, in the expensive direction. Measured on that hub:

      * 48 loads sat in `loadStatus: RUNNING` with `numberOfJobExecutions: 0`, no
        `batchId` and no `integrationJob` — OPEN loads. A UI session creates one when a
        steward opens a merge or authors a record, and abandons it. They are not
        batches, they hold no queue, and a model edition was changed with 46 of them
        outstanding.
      * One sat in `loadStatus: ERROR` WITH a `batchId` and a failed `integrationJob`,
        and the same deploy still succeeded over it.

    So `RUNNING` alone means nothing: it is the status of the LOAD, not of a job. What
    can hold the edition is a SUBMITTED load whose job has started and not finished, so
    that is what this refuses on — `batchId`/`integrationJob` present, `startDate` set,
    `completionDate` absent.

    A failed load is REPORTED and does not refuse, because the direct evidence says it
    does not block. That is deliberately weaker than the 2026-08-03 observation, which
    saw a suspended queue refuse an import — a suspended QUEUE and a failed LOAD are not
    the same object, and only the queue was ever seen to block. If a refusal turns out
    to be needed there, the evidence for it should be a deploy that was actually
    refused, not this docstring.
    """
    def _status(b: dict) -> str:
        return str(b.get("loadStatus") or b.get("status") or "").upper()

    def _job(b: dict) -> dict:
        j = b.get("integrationJob")
        return j if isinstance(j, dict) else {}

    def _submitted(b: dict) -> bool:
        return b.get("batchId") is not None or bool(_job(b))

    TERMINAL = ("CANCELED", "CANCELLED", "DONE", "WARNING")
    # FAILED and IN FLIGHT are disjoint, and the split is the whole point. A job that
    # ERRORed has stopped — it has a startDate and no completionDate exactly like a
    # running one, so keying on the dates alone would refuse on the one state the
    # evidence says does not block.
    failed = [b for b in batches if _submitted(b) and _status(b) == "ERROR"]
    stuck = [b for b in batches
             if _submitted(b) and (
                 # SUSPENDED is the one state DIRECTLY observed to refuse an import
                 # (2026-08-03): the queue policy is Suspend on Error, the location
                 # flips to MAINTENANCE, and xDM names the batch count in its refusal.
                 # Kept as an explicit state rather than inferred from job dates,
                 # because that observation is the reason this check exists.
                 _status(b) == "SUSPENDED"
                 or (_job(b).get("startDate")
                     and not _job(b).get("completionDate")
                     and _status(b) not in TERMINAL + ("ERROR",)))]
    # Reported, never blocking.
    open_loads = [b for b in batches
                  if not _submitted(b) and _status(b) not in TERMINAL]
    if open_loads:
        pre.add("open loads are not batches", True,
                f"{len(open_loads)} load(s) created and never submitted "
                f"(no batchId, no job). These do NOT hold the edition — observed on a "
                f"live hub, where a deploy succeeded over 46 of them. Left alone.")
    if failed:
        pre.add("a submitted load has FAILED", True,
                f"load(s) {', '.join(str(b.get('loadId', '?')) for b in failed)} "
                f"ended in ERROR. Reported, not refused: a failed load has been "
                f"observed NOT to block a deploy. Its records are uncertified.")
    pre.add("no batch in progress", not stuck,
            "" if not stuck else
            f"{len(stuck)} batch(es) not finished: "
            f"{', '.join(str(b.get('batchId', b.get('id', '?'))) for b in stuck[:5])}. "
            f"xDM refuses to change the deployed edition while one is in progress. "
            f"Cancel it in Execution Engine -> <queue> -> Cancel Job, then set the "
            f"location back to Ready. NOTE cancelling ABANDONS that batch's records: "
            f"they stay in source authoring and the next batch does not collect them.")


def check_version_pin(pre: Preflight, emitted_version: str,
                      target_version: str) -> None:
    """Import is refused across product versions, even to a NEWER target
    (docs/Manage/models/move-models-at-design-time.md). Cheaper to catch here."""
    match = emitted_version == target_version
    pre.add("emitter is pinned to the target version", match,
            "" if match else
            f"XML was emitted for {emitted_version!r} but the instance reports "
            f"{target_version!r}. Import is refused across product versions, even to a "
            f"newer target. Re-read the version and recompile.")


# ---------------------------------------------------------------------- the gate
def preflight_import(*, target: Target, model: str, edition: str, snapshot: Path,
                     repo: Path, location: DataLocation, technology: str,
                     emitted_version: str, target_version: str,
                     batches: list[dict] | None = None) -> Preflight:
    """Everything that must be true before an Import-Replace. Refuses, never warns."""
    pre = Preflight()
    check_live_matches_snapshot(pre, target, model, edition, snapshot, repo)
    check_working_tree_clean(pre, repo)
    check_target_location(pre, location, model, technology)
    check_no_batch_in_progress(pre, batches or [])
    check_version_pin(pre, emitted_version, target_version)
    return pre


# ---------------------------------------------------------------- POST-condition
#: Statuses a data location settles into. Anything else is still in flight.
TERMINAL_STATUSES = ("DL_READY", "INSTALL_JOB_FAILED", "BROKEN", "MAINTENANCE")


@dataclass(frozen=True)
class DeployOutcome:
    """What the location actually looked like when polling stopped."""
    location: str
    status: str
    model: str | None
    edition: str | None
    deployment_date: str | None
    settled: bool          # reached a terminal status rather than timing out
    advanced: bool         # deploymentDate moved

    @property
    def ok(self) -> bool:
        return self.settled and self.status == "DL_READY"

    def __str__(self) -> str:
        head = "DEPLOY OK" if self.ok else ("DEPLOY FAILED" if self.settled
                                            else "DEPLOY DID NOT SETTLE")
        return (f"{head}  {self.location}: status={self.status} "
                f"model={self.model} {self.edition} "
                f"deploymentDate={self.deployment_date} "
                f"{'(advanced)' if self.advanced else '(UNCHANGED)'}")


def verify_deploy(target: Target, location: str, *, model: str | None = None,
                  edition: str | None = None, since: str | None = None,
                  timeout_s: int = 1800, interval_s: int = 15,
                  _locations=None, _sleep=None) -> DeployOutcome:
    """Poll a data location until it settles, then report what it actually holds.

    The preflight gates the PREcondition and stops; this closes the loop. Today's
    first deploy was confirmed by hand, by re-reading `deploymentDate` and noticing it
    had moved (sprint 12 §4).

    On timeout this REPORTS the last observed state rather than raising a bare
    TimeoutError — "still DEPLOYING_ME_AND_JOBS after 30 minutes" is actionable and
    "timed out" is not.

    Note `settled` vs `ok`: a location can settle into INSTALL_JOB_FAILED, which is a
    finished deploy and a failed one.
    """
    import time
    from agent.browser.inspect import data_locations as _dl
    get = _locations or (lambda: _dl(target))
    nap = _sleep or time.sleep

    last: dict = {}
    waited = 0
    while True:
        try:
            last = next((d for d in get() if d.get("name") == location), {}) or last
        except Exception:
            pass                      # a transient read must not end the wait
        status = last.get("status", "UNKNOWN")
        if status in TERMINAL_STATUSES or waited >= timeout_s:
            break
        nap(interval_s)
        waited += interval_s

    date = last.get("deploymentDate")
    return DeployOutcome(
        location=location, status=last.get("status", "UNKNOWN"),
        model=last.get("modelName"), edition=last.get("modelEditionKey"),
        deployment_date=date,
        settled=last.get("status") in TERMINAL_STATUSES,
        advanced=bool(date) and date != since,
    )
