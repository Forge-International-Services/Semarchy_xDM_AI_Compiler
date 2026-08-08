"""Sprint 09 acceptance: the preflight that makes a destructive import defensible.

Every test here asserts a REFUSAL. That is deliberate: D7's whole argument is that
Import-Replace is safe *because* git holds every version, and the guard is what makes
that true. A guard nobody has watched fail is an assumption with a function signature.

The live export is stubbed at the module boundary, so the semantics are tested without
an instance and without any risk of a real import. The git repo is REAL — a temporary
one — because the check reads HEAD rather than the working tree, and faking that would
test the wrong thing.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent.browser.inspect import DataLocation  # noqa: E402
from agent.rest import Target  # noqa: E402
from agent.safety import (  # noqa: E402
    Preflight, Refused, check_live_matches_snapshot, check_no_batch_in_progress,
    check_target_location, check_version_pin, committed_blob)

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "samples" / "gs-productretail-2025.1.0.xml"


def sample_bytes() -> bytes:
    """A real product export, or a skip. The D7 preflight tests need a model big enough
    to normalize meaningfully, and `samples/` is not in the public export. The twenty-
    one tests below that drive `verify_deploy`, the load parser and the refusals build
    their own input and keep running there."""
    if not SAMPLE.exists():
        pytest.skip(f"{SAMPLE.relative_to(ROOT)} not present")
    return SAMPLE.read_bytes()
ENV = {"SEMARCHY_URL": "http://lab/semarchy/api/rest", "SEMARCHY_API_KEY": "k"}

DEV = DataLocation(name="LocationProbe", type="DEV", db_type="POSTGRESQL",
                   status="DL_READY", model="PartyRoleModels", edition_key="0.0")


def _repo(tmp_path: Path, files: dict[str, bytes]) -> Path:
    """A real git repo, because the check reads HEAD rather than the working tree."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "t"], check=True)
    for name, data in files.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "x"], check=True)
    return tmp_path



def _live(monkeypatch, body: bytes):
    """Serve `body` as the live export. Patching the module-level name is what the
    check actually calls, so this exercises the real code path."""
    import agent.safety as safety
    monkeypatch.setattr(safety, "model_content", lambda *a, **k: body)


# ------------------------------------------------------- THE D7 CHECK
def test_an_uncommitted_live_change_refuses_the_import(tmp_path, monkeypatch):
    """The failure D7 exists to prevent: someone edits in the UI, nobody exports, and
    Import-Replace deletes work git never had."""
    repo = _repo(tmp_path, {"live/M.xml": sample_bytes()})
    drifted = sample_bytes().replace(b"<name>Brand</name>",
                                          b"<name>BrandRenamed</name>", 1)
    assert drifted != sample_bytes()
    _live(monkeypatch, drifted)
    pre = Preflight()
    check_live_matches_snapshot(pre, Target.from_env(ENV), "M", "0.0",
                                repo / "live/M.xml", repo)
    assert not pre.ok
    assert "HAS CHANGED SINCE THE LAST COMMIT" in pre.checks[0].detail
    with pytest.raises(Refused):
        pre.raise_if_refused()


def test_an_unchanged_live_model_passes(tmp_path, monkeypatch):
    repo = _repo(tmp_path, {"live/M.xml": sample_bytes()})
    _live(monkeypatch, sample_bytes())
    pre = Preflight()
    check_live_matches_snapshot(pre, Target.from_env(ENV), "M", "0.0",
                                repo / "live/M.xml", repo)
    assert pre.ok, pre.render()


def test_audit_churn_alone_does_not_refuse(tmp_path, monkeypatch):
    """A re-export never reuses UUIDs and restamps every audit field. Comparing bytes
    would refuse every single time, and a guard that always fires gets switched off."""
    repo = _repo(tmp_path, {"live/M.xml": sample_bytes()})
    churned = sample_bytes().replace(
        b"<internalUpdateUser>hub_admin</internalUpdateUser>",
        b"<internalUpdateUser>someone.else</internalUpdateUser>")
    assert churned != sample_bytes()          # the bytes really did change
    _live(monkeypatch, churned)
    pre = Preflight()
    check_live_matches_snapshot(pre, Target.from_env(ENV), "M", "0.0",
                                repo / "live/M.xml", repo)
    assert pre.ok, pre.render()


def test_a_first_import_passes_but_says_nothing_was_verified(tmp_path, monkeypatch):
    repo = _repo(tmp_path, {"README.md": b"x"})
    _live(monkeypatch, sample_bytes())
    pre = Preflight()
    check_live_matches_snapshot(pre, Target.from_env(ENV), "M", "0.0",
                                repo / "live/M.xml", repo)
    assert pre.ok
    assert "FIRST import" in pre.checks[0].detail
    assert "nothing verified" in pre.checks[0].detail


def test_committed_blob_reads_HEAD_not_the_working_tree(tmp_path):
    """A snapshot edited but never committed is exactly the state D7 says git does not
    protect, so the comparison must not read it from disk."""
    repo = _repo(tmp_path, {"live/M.xml": b"committed"})
    (repo / "live/M.xml").write_bytes(b"edited but not committed")
    assert committed_blob(repo, repo / "live/M.xml") == b"committed"


# ------------------------------------------------------------- location gates
def test_a_production_location_is_refused_by_d9():
    pre = Preflight()
    prod = DataLocation(name="Prod", type="PROD", db_type="POSTGRESQL",
                        status="DL_READY")
    check_target_location(pre, prod, "M", "postgresql")
    assert not pre.ok
    assert "D9 restricts deployment to DEV" in pre.checks[0].detail


def test_a_location_in_maintenance_is_refused():
    pre = Preflight()
    loc = DataLocation(name="L", type="DEV", db_type="POSTGRESQL",
                       status="MAINTENANCE")
    check_target_location(pre, loc, "M", "postgresql")
    assert not pre.ok
    assert any("not DL_READY" in c.detail for c in pre.checks)


def test_deploying_over_a_different_model_is_refused():
    pre = Preflight()
    check_target_location(pre, DEV, "SomeOtherModel", "postgresql")
    assert not pre.ok
    assert any("a DIFFERENT model" in c.detail for c in pre.checks)


def test_a_snowflake_model_is_refused_on_a_postgres_location():
    """D13 targets Snowflake; the lab is POSTGRESQL. Caught before the attempt."""
    pre = Preflight()
    check_target_location(pre, DEV, "PartyRoleModels", "snowflake")
    assert not pre.ok


# --------------------------------------------------- the lock nobody designed for
def test_a_suspended_batch_refuses_the_import():
    """OBSERVED LIVE 2026-08-03. A failed job suspends the queue and xDM then refuses
    to change the deployed edition.

    The BEHAVIOUR was observed; the record SHAPE in this test was not — it was written
    as `{"status": ...}` when the API returns `loadStatus`, which is how the check came
    to read a key that never arrives and pass on everything. Field name corrected here;
    the assertion it makes is unchanged, because the observation still stands.
    """
    pre = Preflight()
    check_no_batch_in_progress(pre, [{"loadId": 51, "batchId": 51,
                                      "loadStatus": "SUSPENDED"}])
    assert not pre.ok
    d = [c for c in pre.checks if not c.passed][0].detail
    assert "Cancel Job" in d
    assert "ABANDONS that batch's records" in d      # the consequence, not just the fix


def test_finished_batches_do_not_block():
    pre = Preflight()
    check_no_batch_in_progress(pre, [{"loadId": 52, "batchId": 52,
                                      "loadStatus": "DONE"}])
    assert pre.ok


# --------------------------------------------------------------- version pinning
def test_a_version_mismatch_is_refused():
    """Import is refused across product versions, even to a NEWER target. Cheaper to
    catch in preflight than as an opaque import failure."""
    pre = Preflight()
    check_version_pin(pre, "2025.1.0", "2025.1.8.20251031-a7af69c")
    assert not pre.ok
    assert "even to a newer target" in pre.checks[0].detail


def test_a_matching_version_passes():
    pre = Preflight()
    check_version_pin(pre, "2025.1.8", "2025.1.8")
    assert pre.ok


# ------------------------------------------------------------------- the report
def test_the_refusal_names_every_failed_check():
    pre = Preflight()
    check_target_location(pre, DataLocation(name="P", type="PROD", db_type="X",
                                            status="BROKEN"), "M", "oracle")
    text = pre.render()
    assert text.startswith("PREFLIGHT REFUSED")
    assert text.count("[REFUSE]") >= 3


# ------------------------------------------------------- the POST-condition (sp12)
from agent.safety import verify_deploy  # noqa: E402


def _poller(*states):
    """Serve one status per poll, then repeat the last one forever."""
    seq = list(states)
    def get():
        s = seq.pop(0) if len(seq) > 1 else seq[0]
        return [{"name": "L", "status": s, "modelName": "M",
                 "modelEditionKey": "0.0", "deploymentDate": "2026-08-04T10:00:00Z"}]
    return get


def test_verify_deploy_waits_out_the_in_flight_statuses():
    out = verify_deploy(None, "L", since="2026-08-04T09:00:00Z",
                        _locations=_poller("DEPLOYING_ME_AND_JOBS",
                                           "DEPLOYING_ME_AND_JOBS", "DL_READY"),
                        _sleep=lambda s: None)
    assert out.ok and out.settled and out.advanced


def test_a_failed_install_job_is_settled_but_NOT_ok():
    """The distinction that matters: the deploy finished, and it finished badly."""
    out = verify_deploy(None, "L", _locations=_poller("INSTALL_JOB_FAILED"),
                        _sleep=lambda s: None)
    assert out.settled and not out.ok
    assert "DEPLOY FAILED" in str(out)


def test_a_timeout_reports_the_last_state_rather_than_raising():
    """OBSERVED LIVE: a create+deploy sat in DEPLOYING_ME_AND_JOBS for minutes. A bare
    TimeoutError would have thrown that information away."""
    out = verify_deploy(None, "L", timeout_s=30, interval_s=15,
                        _locations=_poller("DEPLOYING_ME_AND_JOBS"),
                        _sleep=lambda s: None)
    assert not out.settled and not out.ok
    assert "DID NOT SETTLE" in str(out)
    assert "DEPLOYING_ME_AND_JOBS" in str(out)


def test_an_unchanged_deployment_date_is_reported_as_such():
    out = verify_deploy(None, "L", since="2026-08-04T10:00:00Z",
                        _locations=_poller("DL_READY"), _sleep=lambda s: None)
    assert not out.advanced
    assert "UNCHANGED" in str(out)


def test_a_transient_read_error_does_not_end_the_wait():
    calls = {"n": 0}
    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("reset")
        return [{"name": "L", "status": "DL_READY", "modelName": "M",
                 "modelEditionKey": "0.0", "deploymentDate": "2026-08-04T10:00:00Z"}]
    out = verify_deploy(None, "L", _locations=flaky, _sleep=lambda s: None)
    assert out.ok


# ------------------------------- the check that could not fail (LESSONS §3, §4, §48)
#
# These run against tests/fixtures/loads_live.json — the SHAPE of a real
# `GET loads/{loc}` response, taken from a live hub and hand-abstracted. Before it
# existed, this check read `b["status"]` while the API returns `loadStatus`, so it
# matched nothing and passed against 49 non-terminal loads.
import json  # noqa: E402

LOADS = json.loads((ROOT / "tests/fixtures/loads_live.json").read_text())


def test_the_field_name_is_the_one_the_api_actually_returns():
    """The bug, pinned by its cause rather than its symptom. If someone reverts to
    `status`, every assertion below still passes on a hand-made dict that happens to
    carry both keys — so this asserts the FIXTURE has only the real key."""
    assert any("loadStatus" in r for r in LOADS)
    assert not any("status" in r for r in LOADS), \
        "the live API returns loadStatus, never status — do not add it to the fixture"


def test_an_in_flight_batch_refuses():
    pre = Preflight()
    check_no_batch_in_progress(pre, LOADS)
    assert not pre.ok
    assert "35" in pre.render(), "the blocking batchId must be named"


def test_open_loads_alone_do_NOT_refuse():
    """THE FALSE POSITIVE THAT MATTERED. 48 abandoned UI loads sat on a live hub in
    loadStatus RUNNING with no batch, and a deploy succeeded over 46 of them. Refusing
    on those would have blocked every deploy on that instance forever."""
    pre = Preflight()
    check_no_batch_in_progress(pre, [r for r in LOADS if r["loadId"] != 120])
    assert pre.ok, pre.render()
    assert "created and never submitted" in pre.render(), \
        "they must still be REPORTED — invisible is not the same as harmless"


def test_a_failed_load_is_reported_but_does_not_refuse():
    """A job that ERRORed has a startDate and no completionDate, exactly like a running
    one. Keying on the dates alone would refuse on the one state directly observed NOT
    to block a deploy."""
    pre = Preflight()
    check_no_batch_in_progress(pre, [r for r in LOADS if r["loadId"] in (108,)])
    assert pre.ok, pre.render()
    assert "108" in pre.render() and "ERROR" in pre.render()


def test_a_completed_load_is_silent():
    pre = Preflight()
    check_no_batch_in_progress(pre, [r for r in LOADS if r["loadId"] == 66])
    assert pre.ok
    assert "not finished" not in pre.render()


def test_an_empty_list_still_passes():
    pre = Preflight()
    check_no_batch_in_progress(pre, [])
    assert pre.ok
