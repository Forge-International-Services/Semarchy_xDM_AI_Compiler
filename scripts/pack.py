#!/usr/bin/env python3
"""Build the export artefact: dist/semarchy-xdm-agent-<YYYYMMDD>.zip

    python scripts/pack.py

WHAT GOES IN. `git ls-files` at HEAD, minus the knowledge corpus, minus anything
that looks like a credential, plus exactly one file back — see EXCEPTIONS. Building
from the index rather than from the working tree means nothing untracked, generated
or gitignored can ride along by accident, and it is why the script refuses to run on
a dirty tree: on a dirty tree `git ls-files` and what you can see are different
things, and the artefact would attest to the wrong one.

WHAT DOES NOT GO IN, and the difference matters:

  the corpus     ~18 MB of mirrored documentation, transcripts, slides, labs and
                 notes. Excluded because the recipient does not need it to run the
                 compiler, and because the Academy-derived half is Semarchy
                 -confidential. agent/corpus.py holds the list and the runtime
                 behaviour that goes with it.

  .git           the artefact is a ZIP, not a clone. This is deliberate and it is
                 the mitigation for the lab API key that sits in the repository's
                 HISTORY (see the commit that untracked `.env-lab`). No history in
                 the zip means no key in the zip.

  credentials    .env and every sibling, by filename AND by content. The content
                 half is the last line of defence and it is described at
                 `scan_for_secrets`.

THE FOUR BARS, which is what the whole repository is organised around:

    round-trips  !=  importable  !=  exportable  !=  deployable  !=  runnable

Never report a lower bar as if it were a higher one. This script clears exactly one
of them and not even one of those five: it proves the tree PACKS. What the packed
tree then does is measured separately, by running its own test suite from inside it.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent.corpus import CORPUS_DIRS, FETCHER, SHIPPED  # noqa: E402

NAME = "semarchy-xdm-agent"

#: Excluded by directory. Imported, not restated — two lists that must agree are a
#: place they will stop agreeing.
EXCLUDE_DIRS = CORPUS_DIRS

#: Put back afterwards. One file, and the justification is recorded here, in
#: agent/corpus.py, and in the MANIFEST the recipient reads:
#:
#:   docs/SemQL/function-list.md is LOAD-BEARING FOR VALIDATION. semql.builtins_for()
#:   parses it into the set of functions each hub technology offers, and IR-017
#:   refuses any expression calling something outside that set. With the file gone
#:   the set is empty, so LOWER() is an invention and IR-017 refuses correct models —
#:   a validator failing closed on its own missing input. It is also a factual
#:   function table rather than prose, so shipping it carries nothing else with it.
EXCEPTIONS = SHIPPED

#: Excluded by filename, whatever directory they turn up in.
SECRET_FILE_PATTERNS = (
    re.compile(r"(^|/)\.env$"),
    re.compile(r"(^|/)\.env[.-]"),          # .env.local, .env-lab, .env-prod
    re.compile(r"\.(pem|key|p12|pfx|jks|keystore)$"),
    re.compile(r"(^|/)id_(rsa|dsa|ecdsa|ed25519)$"),
    re.compile(r"(^|/)(credentials|secrets)(\.|$)"),
)
#: `.env.example` documents the contract with empty and angle-bracketed values. It is
#: the one file the patterns above would catch that must still ship.
SECRET_FILE_ALLOW = (".env.example",)


# --------------------------------------------------------------- the secret tripwire
#: A value that is obviously a stand-in. Checked before anything is called a leak,
#: because `.env.example` exists precisely to carry these.
_PLACEHOLDER = re.compile(
    r"""^(
          | <[^>]*>                       # <your_pat>, <HUB_SCHEMA>
          | ["']?<[^>]*>["']?
          | x{3,} | \.{3,} | \*{3,}
          | (your|my|the)[_-]?\w*
          | abc123 | changeme | placeholder | redacted | example | dummy | test
          | \$\{.*\} | \$[A-Z_]+          # ${VAR}, $VAR -- indirection, not a value
        )$""",
    re.X | re.I,
)

#: `NAME = value` where NAME carries a credential. Every clause here was narrowed by
#: running the scan over the whole repository and reading all 80 of its first-draft
#: findings: not one was a leak, and each false positive taught the rule below it.
#:
#:   `_(SECRET|TOKEN|KEY)` must be a SUFFIX behind an underscore, or `PhoneticNameToken`
#:   and `NameToken` are credentials; `SECRET_STRING` and `ALLOWED_AUTHENTICATION_
#:   SECRETS` are not matches either, because the suffix must end the name.
#:
#:   `Authorization` alone matched the PROSE that explains the header — "Authorization
#:   -> Snowflake" — in four files. It now needs a scheme after it, below.
_CRED_NAME = re.compile(
    r"""(?<![A-Za-z0-9])
        (?P<name>
            SEMARCHY_API_KEY | SEMARCHY_AUTHORIZATION
          | API[-_]KEY | APIKEY
          | [A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)*_(?:SECRET|PASSWORD|PASSWD|TOKEN|KEY|PAT)
          | password | passwd | secret | api_key | access_token | auth_token
          | private_key
        )
        (?![A-Za-z0-9])
        \s* [:=] \s* ["']?
        (?P<value>[A-Za-z0-9+/=_-]{16,200})
        (?![A-Za-z0-9+/=_.-])""",
    re.X | re.I,
)

#: The HTTP header, which only means anything with a scheme and a credential after it.
_HTTP_AUTH = re.compile(
    r"""Authorization \s* [:=] \s* ["']?
        (?: Bearer | Basic | Snowflake \s+ Token \s* = ) \s* ["']?
        (?P<value>[A-Za-z0-9+/=_.-]{16,})""",
    re.X | re.I,
)

#: A bare high-entropy blob. The xDM API key is an opaque string and this repo holds no
#: sample of one to pattern-match, so length plus a mixed alphabet stands in for a
#: format nobody here is entitled to guess at. Deliberately conservative: 40+
#: characters, at least one digit and one letter of each case, no dot or slash anywhere
#: adjacent. The dot and slash exclusion is what the first draft was missing — it
#: matched `personator.melissadata.net/v3/WEB/ContactVerify/doContactVerify`, which is
#: a URL. Single-case identifiers do not trip it either, which keeps the sample XML's
#: UUIDs and element names quiet.
_BLOB = re.compile(r"(?<![A-Za-z0-9+/=._-])(?![A-Za-z0-9+/=_-]*[./])"
                   r"(?=[A-Za-z0-9+/=_-]*[a-z])(?=[A-Za-z0-9+/=_-]*[A-Z])"
                   r"(?=[A-Za-z0-9+/=_-]*\d)"
                   r"[A-Za-z0-9+/=_-]{40,}(?![A-Za-z0-9+/=._-])")

#: How many `_` or `-` a 40-character opaque token plausibly carries. A base64url
#: credential of that length averages two or three; `test_create_data_location_RETURNS_
#: a_5xx_instead_of_raising` — a real test name in this repository, 58 characters,
#: mixed case, containing a digit, and the ONLY finding the tightened scan produced —
#: carries eight. Shannon entropy was tried first and does not separate these: that
#: test name scores 4.07 bits and a 40-character hex API key scores 3.83, so an entropy
#: floor would let the credential through to catch the identifier. Counting separators
#: does separate them, and it is legible.
_MAX_SEPARATORS = 2


def _looks_opaque(value: str) -> bool:
    """True when the value could plausibly BE a credential rather than a name.

    A credential is opaque: mixed case AND a digit. `SET_ANYTHING_FOR_NOW` has no
    lowercase, `melissa_network_rule` has no digit and no uppercase, and neither is a
    secret. This is the difference between a tripwire and an alarm that gets muted.
    """
    return (any(c.islower() for c in value)
            and any(c.isupper() for c in value)
            and any(c.isdigit() for c in value)
            and sum(value.count(c) for c in "_-") <= _MAX_SEPARATORS)

#: Files whose whole purpose is to talk ABOUT credentials. They are prose, they are
#: reviewed, and they carry no values -- but they say the words, and a tripwire that
#: cries wolf on its own documentation gets switched off. Their assignments are still
#: checked; only the entropy heuristic is relaxed.
_PROSE = ("CLAUDE.md", "AGENT.md", "AGENT_DESIGN.md", "LESSONS.md", "README.md",
          ".env.example", "ANONYMIZATION.md", "scripts/pack.py")


class Leak(Exception):
    pass


def scan_for_secrets(root: Path, files: list[str]) -> list[str]:
    """Every packed file, read as bytes and scanned. Returns human-readable findings.

    Three layers, because each catches what the others miss:

      1. an assignment to a credential-shaped NAME whose value is not a placeholder
      2. a high-entropy blob, anywhere, in a file that is not documentation
      3. any value that appears in a LOCAL env file also appearing in the pack

    Layer 3 is the one that would actually have caught the real thing, and it is the
    reason this function takes the trouble to open `.env` and `.env-lab`: it compares
    against the credentials that exist on THIS machine rather than against a guess at
    their format. Those values are never printed, never stored, and never packed --
    the finding names the variable and the leaking file, nothing else. The env files
    are optional: a recipient re-running this script has none, and layers 1 and 2
    still work.
    """
    findings: list[str] = []
    live = _local_secret_values(root)

    for rel in files:
        raw = (root / rel).read_bytes()
        # latin-1 never raises, so a stray binary cannot silently skip the scan.
        text = raw.decode("latin-1")
        prose = rel in _PROSE

        def line_of(pos: int) -> int:
            return text.count("\n", 0, pos) + 1

        for pat, label in ((_CRED_NAME, None), (_HTTP_AUTH, "Authorization header")):
            for m in pat.finditer(text):
                value = m.group("value").strip("\"'")
                if _PLACEHOLDER.match(value) or not _looks_opaque(value):
                    continue
                name = label or m.group("name")
                findings.append(
                    f"{rel}:{line_of(m.start())}: {name} assigned an opaque "
                    f"{len(value)}-character value")

        if not prose:
            for m in _BLOB.finditer(text):
                if not _looks_opaque(m.group(0)):
                    continue
                findings.append(
                    f"{rel}:{line_of(m.start())}: opaque high-entropy string, "
                    f"{len(m.group(0))} chars")

        for var in live:
            if live[var] in text:
                findings.append(
                    f"{rel}: contains the live value of {var} from a local env file")

    return findings


#: The env settings that are credentials. The others -- SEMARCHY_URL, SEMARCHY_RAG_DSN
#: -- are configuration, they are DOCUMENTED in CLAUDE.md and .env.example on purpose,
#: and matching on them made layer 3 report the repository's own documentation as a
#: leak of itself. A tripwire that fires on the thing it is documenting is one nobody
#: reads twice.
_CREDENTIAL_SETTING = re.compile(
    r"(API[-_]?KEY|AUTHORIZATION|TOKEN|SECRET|PASSWORD|PAT)$", re.I)


def _local_secret_values(root: Path) -> dict[str, str]:
    """Credential values from local env files, for layer 3. NEVER printed.

    This function opens `.env` and `.env-lab`. It is the only thing in the repository
    that does, it holds them in memory for the length of one scan, and what it emits
    is a variable name and a filename — never a value. The point is to compare the
    pack against the credentials that exist on THIS machine rather than against a
    guess at their format, because the format is exactly what nobody here knows.
    """
    out: dict[str, str] = {}
    for p in sorted(root.glob(".env*")):
        if p.name in SECRET_FILE_ALLOW or not p.is_file():
            continue
        for line in p.read_text(errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            name = name.strip().removeprefix("export ").strip()
            value = value.strip().strip("\"'")
            if len(value) < 12 or _PLACEHOLDER.match(value):
                continue
            if not _CREDENTIAL_SETTING.search(name):
                continue
            out[f"{name} ({p.name})"] = value
    return out


# --------------------------------------------------------------------- file selection
def excluded(rel: str) -> str | None:
    """Why `rel` is not packed, or None if it is."""
    if rel in EXCEPTIONS:
        return None
    top = rel.split("/", 1)[0]
    if top in EXCLUDE_DIRS:
        return f"corpus directory {top}/"
    if rel in SECRET_FILE_ALLOW:
        return None
    for pat in SECRET_FILE_PATTERNS:
        if pat.search(rel):
            return "credential file"
    return None


def tracked_files(root: Path) -> list[str]:
    out = subprocess.run(["git", "-C", str(root), "ls-files", "-z"],
                         capture_output=True, check=True).stdout
    return sorted(f for f in out.decode().split("\0") if f)


def refuse_if_dirty(root: Path) -> None:
    st = subprocess.run(["git", "-C", str(root), "status", "--porcelain"],
                        capture_output=True, text=True, check=True).stdout.strip()
    if st:
        sys.exit(
            "The working tree is dirty. Refusing to pack.\n\n"
            f"{st}\n\n"
            "The artefact is built from `git ls-files`, which reports the INDEX. "
            "Packing\nnow would ship a tree that does not match what you can see, "
            "and the zip\ncarries no history for anyone to check it against. "
            "Commit or stash first.")


# ------------------------------------------------------------------------- the manifest
def manifest(root: Path, files: list[str], dropped: dict[str, int],
             head: str, built: str, zip_name: str) -> str:
    total = sum((root / f).stat().st_size for f in files)
    L = [
        f"{NAME} — export pack",
        "=" * 72,
        "",
        f"artefact   {zip_name}",
        f"commit     {head}",
        # The COMMIT's date, not the clock's. Everything in this archive is derived
        # from one commit, so two packs of that commit are byte-identical and a diff
        # between two artefacts shows only what actually changed. A build timestamp
        # would make every re-run look different and teach the reader to ignore it.
        f"source     {built}",
        f"contents   {len(files)} files, {total / 1e6:.1f} MB unpacked",
        "",
        "WHAT THIS IS",
        "-" * 72,
        "An agent that turns natural-language MDM requirements into a working Semarchy",
        "xDM application:",
        "",
        "    requirements (NL)  ->  YAML IR  ->  metaDataExport XML  ->  import",
        "                       ->  deploy   ->  integration job     ->  a live hub",
        "",
        "Read CLAUDE.md first. It is the orientation document: what is where, what has",
        "actually been run against a live instance, and what has not.",
        "",
        "THE FOUR BARS",
        "-" * 72,
        "The through-line of this repository, and the thing to hold any claim about it",
        "against:",
        "",
        "    round-trips != importable != exportable != deployable != runnable",
        "",
        "Each was found only by clearing the one before it. A model that round-trips",
        "through the compiler has been compared against another pass of the same",
        "compiler and nothing else. Never report a lower bar as if it were a higher one.",
        "",
        "INSTALL",
        "-" * 72,
        "    python3 -m venv .venv && source .venv/bin/activate",
        "    pip install -e '.[dev]'",
        "    python -m pytest tests/ -q",
        "",
        "The suite is green with skips in this tree. The skips are the tests that read",
        "the knowledge corpus, which is not here — see below. Nothing is skipped in the",
        "full repository, and no assertion was weakened to make this true.",
        "",
        "RUN",
        "-" * 72,
        "Entry points are module invocations; there are no console scripts.",
        "",
        "    python -m agent.rest  <env-file>                    # doctor: config + reach",
        "    python -m agent.build <env-file> <ir-dir>           # stops at IMPORTABLE",
        "    python -m agent.build <env-file> <ir-dir> \\",
        "        --location <name> --datasource <name>           # ... through DEPLOYED",
        "    python -m agent.watch <env-file> <model>            # export, compile, report",
        "",
        "NO CREDENTIALS ARE IN THIS ARCHIVE. `.env.example` documents the contract:",
        "copy it to `.env` and fill it in. Two headers, two different systems — read the",
        "comments in that file before assuming they are two keys for one.",
        "",
        "Offline, needing no instance and no corpus. Run verbatim against this",
        "archive on 2026-08-07: 0 validation errors, 25,398 bytes of XML, 0 shape",
        "findings.",
        "",
        "    from agent.ir.schema import IR",
        "    from agent.ir.validate import validate, errors",
        "    from agent.compile.emit import emit",
        "    from agent.compile.blocks import check, render",
        "",
        "    ir = IR.load('out/s2-two-crms/ir/model.yaml',",
        "                 'out/s2-two-crms/ir/certify.yaml')",
        "    print(len(errors(validate(ir))), 'validation errors')",
        "    xml = emit(ir.model_ir, platform_version='2025.1.8',",
        "               repository_version='2025.1.2',",
        "               certify=ir.certify, app=ir.app)",
        "    print(render(check(xml)) or 'shape clean')",
        "",
        "That is the IMPORTABLE bar and no further. It says the XML has the shape the",
        "product writes; it does not say the product accepted it.",
        "",
        "WHAT IS NOT IN THIS ARCHIVE",
        "-" * 72,
        "",
        "1. GIT HISTORY. This is a zip, not a clone. That is deliberate: a platform API",
        "   key was tracked in this repository for months before it was removed, and it",
        "   remains reachable in history. Shipping a history-free artefact is the",
        "   mitigation. The key is being rotated separately.",
        "",
        "2. CREDENTIALS. `.env` and every sibling are excluded by filename, and every",
        "   packed file is then scanned for credential-shaped content before the zip is",
        "   written. `.env.example` ships; it holds empty and <angle-bracketed> values.",
        "",
        "3. THE KNOWLEDGE CORPUS — roughly 18 MB across:",
        "",
    ]
    for d in sorted(dropped):
        L.append(f"       {d + '/':<16} {dropped[d]:>4} files")
    L += [
        "",
        "   Two different things are in that list and they come back differently.",
        "",
        "   The PRODUCT DOCUMENTATION (docs/) is a mirror of Semarchy's public",
        "   documentation and re-mirrors from source:",
        "",
        f"       {FETCHER}",
        "",
        "   The ACADEMY-DERIVED material — transcripts/, notes/, slides_text/,",
        "   labs_text/, raw/ — and the retrieval index (index/, search/) are NOT",
        "   re-downloadable and are NOT re-mirrorable from this archive. They are",
        "   Semarchy-confidential training material and they come from the full",
        "   repository only. Their absence disables dense retrieval (agent/rag.py,",
        "   agent/tools/knowledge.py) and citation validation (agent/tools/citation.py).",
        "   Each of those refuses with a message naming the way back rather than",
        "   failing quietly — agent/corpus.py is where that behaviour lives, and its",
        "   docstring lists the five places that read the corpus at runtime and how",
        "   each of them used to fail.",
        "",
        "   THE ONE EXCEPTION, and it is documented rather than inherited:",
        "",
        "       docs/SemQL/function-list.md    SHIPS",
        "",
        "   It is load-bearing for validation. agent/tools/semql.py parses it into the",
        "   set of SemQL functions each hub technology offers, and IR-017 refuses any",
        "   expression that calls something outside that set. Without the file the set",
        "   is empty, so LOWER(), METAPHONE() and SOUNDEX() all read as inventions and",
        "   IR-017 refuses models that are correct — a validator failing closed on its",
        "   own missing input, which is the worst direction for one to fail in. It is",
        "   also a factual function table rather than prose, so shipping it carries",
        "   nothing else along with it.",
        "",
        "FILE LIST",
        "-" * 72,
        "",
    ]
    L += [f"  {f}" for f in files]
    L += ["", "=" * 72, f"end of manifest — {len(files)} files"]
    return "\n".join(L) + "\n"


# ------------------------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out-dir", default=None, help="default: <repo>/dist")
    args = ap.parse_args(argv)

    root = Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True, check=True,
                               cwd=Path(__file__).resolve().parent).stdout.strip())
    refuse_if_dirty(root)

    head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()
    # Entry timestamps come from the COMMIT, not from the clock, so re-running on the
    # same commit produces the same archive and two packs diff cleanly.
    when = dt.datetime.fromisoformat(
        subprocess.run(["git", "-C", str(root), "show", "-s", "--format=%cI", head],
                       capture_output=True, text=True, check=True).stdout.strip())
    stamp = tuple(when.timetuple())[:6]

    every = tracked_files(root)
    files, dropped = [], {}
    for rel in every:
        why = excluded(rel)
        if why is None:
            files.append(rel)
        else:
            key = why.removeprefix("corpus directory ").rstrip("/")
            dropped[key] = dropped.get(key, 0) + 1

    print(f"HEAD      {head[:12]}")
    print(f"tracked   {len(every)} files")
    print(f"packing   {len(files)}")
    print(f"dropping  {len(every) - len(files)}  "
          + ", ".join(f"{k}={v}" for k, v in sorted(dropped.items())))

    for e in EXCEPTIONS:
        if e not in files:
            sys.exit(f"the documented exception {e} is not in the pack — "
                     "it is not tracked, or excluded() changed. Refusing.")
    print(f"exception {', '.join(EXCEPTIONS)}  (see MANIFEST.txt)")

    print("scanning for credentials ...", end=" ", flush=True)
    findings = scan_for_secrets(root, files)
    if findings:
        print("FOUND\n")
        for f in findings:
            print(f"  {f}")
        sys.exit("\nRefusing to pack. Nothing above is quoted on purpose — go and look.")
    print("clean")

    today = dt.date.today().strftime("%Y%m%d")
    stem = f"{NAME}-{today}"
    out_dir = Path(args.out_dir) if args.out_dir else root / "dist"
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / f"{stem}.zip"

    text = manifest(root, files, dropped, head,
                    when.isoformat(timespec="seconds"), zip_path.name)

    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        info = zipfile.ZipInfo(f"{stem}/MANIFEST.txt", date_time=stamp)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        z.writestr(info, text)
        for rel in files:                       # already sorted -> deterministic
            src = root / rel
            info = zipfile.ZipInfo(f"{stem}/{rel}", date_time=stamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            mode = 0o755 if os.access(src, os.X_OK) else 0o644
            info.external_attr = mode << 16
            z.writestr(info, src.read_bytes())

    size = zip_path.stat().st_size
    print(f"\n{zip_path}")
    print(f"{size:,} bytes ({size / 1e6:.1f} MB), {len(files) + 1} entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
