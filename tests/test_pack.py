"""The export pack: what it drops, what it keeps, and whether its tripwire can fire.

A check that could not have failed proves nothing (LESSONS §3, §4). The credential
scan in scripts/pack.py returns clean on this repository, and that result is only
worth something if the same scan catches a planted key — so it is planted here, in
each of the three shapes the scanner claims to cover, and the assertion is that all
three are found and that none of them is echoed back.

The other half is the ratchet: the repository's own packable files must scan clean,
every time. A finding here means either a real leak or a scanner that has started
crying wolf, and both want looking at before an artefact goes out.
"""
from __future__ import annotations

import base64
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import pack  # noqa: E402
from agent import corpus  # noqa: E402

in_a_git_repo = pytest.mark.skipif(
    not (ROOT / ".git").exists(),
    reason="no .git — this is an unpacked artefact, and the pack is built from the index")


def _key(n: int = 30) -> str:
    """A credential-shaped string: opaque, mixed case, and different every run."""
    while True:
        k = base64.urlsafe_b64encode(os.urandom(n)).decode().rstrip("=")
        if any(c.islower() for c in k) and any(c.isupper() for c in k) \
                and any(c.isdigit() for c in k) and sum(k.count(c) for c in "_-") <= 2:
            return k


# ------------------------------------------------------------------ file selection
def test_the_corpus_directories_are_dropped():
    for d in corpus.CORPUS_DIRS:
        assert pack.excluded(f"{d}/some/page.md"), f"{d}/ should not pack"


def test_pack_and_the_runtime_agree_on_which_directories_those_are():
    """One tuple, imported twice. Two lists that must agree are a place they stop."""
    assert pack.EXCLUDE_DIRS is corpus.CORPUS_DIRS
    assert pack.EXCEPTIONS is corpus.SHIPPED


def test_the_semql_function_list_is_the_one_exception():
    """It is load-bearing for IR-017: with the file gone, builtins_for() is empty and
    every valid function reads as an invention."""
    assert pack.excluded("docs/SemQL/function-list.md") is None
    assert pack.excluded("docs/SemQL/semql-syntax.md"), "only the ONE file comes back"


@pytest.mark.parametrize("rel", [
    ".env", ".env-lab", ".env.local", "conf/.env-prod",
    "certs/server.pem", "certs/server.key", "deploy/id_rsa", "aws/credentials",
])
def test_credential_files_never_pack(rel):
    assert pack.excluded(rel) == "credential file", rel


def test_the_example_env_does_pack():
    """It documents the contract and carries empty and <angle-bracketed> values."""
    assert pack.excluded(".env.example") is None


# ------------------------------------------------------------- the tripwire fires
@pytest.fixture
def planted(tmp_path):
    """A tree holding one credential, reachable by all three scanner layers."""
    k = _key()
    (tmp_path / ".env").write_text(
        f"SEMARCHY_API_KEY={k}\n"
        "SEMARCHY_URL=http://example.invalid/semarchy/api/rest/\n")
    (tmp_path / "settings.py").write_text(f'SEMARCHY_API_KEY = "{k}"\n')
    (tmp_path / "runbook.md").write_text(f'curl -H "Authorization: Bearer {k}" $URL\n')
    (tmp_path / "values.yaml").write_text(f"opaque: {k}\n")
    return tmp_path, k


@pytest.mark.parametrize("f", ["settings.py", "runbook.md", "values.yaml"])
def test_a_planted_credential_is_found_in_every_shape(planted, f):
    root, _ = planted
    assert pack.scan_for_secrets(root, [f]), f"{f} scanned clean with a key in it"


def test_the_finding_never_quotes_the_credential(planted):
    """The report says which file and which variable. Saying the value would move the
    secret from one file into a terminal, a CI log and a paste to whoever asks."""
    root, k = planted
    report = "\n".join(pack.scan_for_secrets(root, ["settings.py", "runbook.md",
                                                    "values.yaml"]))
    assert report and k not in report


def test_a_value_in_a_local_env_file_is_caught_even_in_an_unfamiliar_shape(planted):
    """Layer 3. The xDM API key's format is not documented anywhere this repo can
    reach, so the scan compares against the key that exists on this machine rather
    than against a guess at its shape."""
    root, k = planted
    (root / "odd.txt").write_text(f"# jotted down here: {k}\n")
    assert any("local env file" in f for f in pack.scan_for_secrets(root, ["odd.txt"]))


@pytest.mark.parametrize("content", [
    "SEMARCHY_API_KEY=\n",
    "SEMARCHY_AUTHORIZATION='Snowflake Token=\"<your_pat>\"'\n",
    "# Authorization -> Snowflake. API-key -> Semarchy.\n",
    "def test_create_data_location_RETURNS_a_5xx_instead_of_raising():\n",
    "Record1.PHONETIC_NAME_TOKEN = Record2.PHONETIC_NAME_TOKEN\n",
    "TYPE = GENERIC_STRING SECRET_STRING = 'SET_ANYTHING_FOR_NOW'\n",
    "url = 'https://personator.example.invalid/v3/WEB/ContactVerify/doContactVerify'\n",
])
def test_the_tripwire_does_not_cry_wolf(tmp_path, content):
    """Every line here is real text from this repository that the first draft of the
    scanner reported as a leak. A tripwire nobody believes is a tripwire nobody reads."""
    (tmp_path / "sample.txt").write_text(content)
    assert pack.scan_for_secrets(tmp_path, ["sample.txt"]) == []


# ------------------------------------------------------------------- the ratchet
@in_a_git_repo
def test_every_packable_file_in_this_repository_scans_clean():
    files = [f for f in pack.tracked_files(ROOT) if pack.excluded(f) is None]
    assert files, "git ls-files returned nothing"
    findings = pack.scan_for_secrets(ROOT, files)
    assert findings == [], "\n".join(findings)


@in_a_git_repo
def test_no_env_file_but_the_example_is_ever_selected():
    packed = [f for f in pack.tracked_files(ROOT) if pack.excluded(f) is None]
    assert [f for f in packed if ".env" in f] == [".env.example"]


@in_a_git_repo
def test_the_documented_exception_is_actually_tracked():
    """If it stops being tracked, the pack silently loses the function table and IR-017
    starts refusing correct models in the recipient's tree."""
    tracked = set(pack.tracked_files(ROOT))
    assert set(pack.EXCEPTIONS) <= tracked


@in_a_git_repo
def test_pack_refuses_a_dirty_tree(tmp_path, monkeypatch):
    """The artefact is built from the index; on a dirty tree the index and what you
    can see are different things, and the zip carries no history to check against."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "a.txt").write_text("uncommitted\n")
    with pytest.raises(SystemExit) as e:
        pack.refuse_if_dirty(tmp_path)
    assert "dirty" in str(e.value).lower() and "a.txt" in str(e.value)
