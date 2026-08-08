"""Watch a live model and report what changed. Sprint 08, read-only.

This is the observation half of D8's demonstration-harvest loop. Someone builds a
construct in the UI; this notices, names it, and says whether the compiler can already
express it. Without that last part the loop is just a diff — the point is to learn
which grammar is still missing.

Read-only by construction: it exports and compares. It never writes to the instance.

Object identity is (element type, name, owning entity) rather than internalID, because
a UUID tells you nothing when it appears and everything is new on the first poll. Audit
fields are ignored — internalRevisionID and internalUpdateDate change on every save and
would drown the signal.
"""
from __future__ import annotations

import functools
import time
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

from agent.rest import Target, model_content

# Bumped by the caller when the instance is slow; a big export can outrun the default.
POLL_SECONDS = 60

_AUDIT = ("internalRevisionID", "internalUpdateDate", "internalCreationDate",
          "internalUpdateUser", "internalCreationUser", "internalID",
          "internalBranchID", "internalEditionID")


def _text(el: ET.Element, tag: str) -> str | None:
    c = el.find(tag)
    return None if c is None else c.attrib.get("val", c.text)


def _fingerprint(el: ET.Element) -> str:
    """Everything about an object except its audit block and its children's identity."""
    parts = []
    for c in sorted(el, key=lambda x: x.tag):
        if c.tag in _AUDIT or len(c):
            continue
        v = c.attrib.get("val")
        if v is None and c.attrib.get("null") == "true":
            v = "\x00null"
        elif v is None and "ref" in c.attrib:
            continue                       # refs are UUIDs; unstable across rebuilds
        elif v is None:
            v = (c.text or "")
        parts.append(f"{c.tag}={v}")
    return "|".join(parts)


@dataclass
class Snapshot:
    """Every named object in a model, keyed by what a human would call it."""
    objects: dict[tuple[str, str], str] = field(default_factory=dict)
    raw: bytes = b""

    @classmethod
    def of(cls, xml: bytes) -> "Snapshot":
        root = ET.fromstring(xml)
        out: dict[tuple[str, str], str] = {}
        # Owning entity disambiguates the many objects that share a name across
        # entities — `Default` collections, `Import` actions, `NameRule`s.
        for entity in root.iter("Entity"):
            ename = _text(entity, "name") or "?"
            for el in entity.iter():
                n = _text(el, "name")
                if n and el.tag[:1].isupper():
                    out[(el.tag, f"{ename}.{n}")] = _fingerprint(el)
        for el in root.iter():
            n = _text(el, "name")
            if n and el.tag[:1].isupper() and (el.tag, f"?.{n}") not in out:
                out.setdefault((el.tag, n), _fingerprint(el))
        return cls(objects=out, raw=xml)


@dataclass
class Change:
    kind: str                    # added / removed / modified
    element: str
    name: str

    def __str__(self) -> str:
        return f"{self.kind:8s} {self.element:28s} {self.name}"


def diff(before: Snapshot, after: Snapshot) -> list[Change]:
    b, a = before.objects, after.objects
    out = [Change("added", t, n) for (t, n) in a if (t, n) not in b]
    out += [Change("removed", t, n) for (t, n) in b if (t, n) not in a]
    out += [Change("modified", t, n) for (t, n) in a
            if (t, n) in b and a[(t, n)] != b[(t, n)]]
    return sorted(out, key=lambda c: (c.kind, c.element, c.name))


@functools.lru_cache(maxsize=1)
def emittable() -> frozenset[str]:
    """Element types the compiler can currently produce.

    Derived by compiling EVERY sample, not hand-listed, so it cannot drift from what
    emit.py actually does.

    All of them, because one is not enough: deriving this from gs-productretail alone
    reported SemQLEnricher, SemQLMatchRule, Publisher and ComplexType as "not yet
    emittable" — they are all emittable, that sample just contains no matcher and no
    enricher. Exactly the narrow-base error that put LongInteger in the registry under
    the name Integer.
    """
    from agent.compile.emit import emit
    from agent.compile.extract import extract
    from agent.compile.extract_app import extract_app
    from agent.compile.extract_certify import extract_certify
    tags: set[str] = set()
    for sample in sorted((Path(__file__).resolve().parents[1] / "samples").glob("*.xml")):
        ir, _ = extract(sample)
        xml = emit(ir, platform_version="2025.1.0", repository_version="2025.1.2",
                   certify=extract_certify(sample), app=extract_app(sample))
        tags |= {e.tag for e in ET.fromstring(xml).iter() if e.tag[:1].isupper()}
    return frozenset(tags)


def report(changes: list[Change], known: frozenset[str] | set[str]) -> str:
    if not changes:
        return "no change"
    lines = [str(c) for c in changes]
    # The harvest signal: something was built that the compiler cannot yet emit.
    novel = sorted({c.element for c in changes if c.element not in known})
    if novel:
        lines.append("")
        lines.append(f"NOT YET EMITTABLE — harvest candidates: {', '.join(novel)}")
    return "\n".join(lines)


def watch(target: Target, model: str, edition: str, *, out_dir: Path,
          seconds: int = POLL_SECONDS, rounds: int | None = None) -> None:
    """Poll until interrupted, appending a running log of what changed."""
    out_dir.mkdir(parents=True, exist_ok=True)
    log = out_dir / f"{model}.watch.log"
    known = emittable()
    prev: Snapshot | None = None
    n = 0
    while rounds is None or n < rounds:
        n += 1
        stamp = time.strftime("%H:%M:%S")
        try:
            xml = model_content(target, model, edition)
        except Exception as exc:                      # a slow export is not a failure
            with log.open("a") as f:
                f.write(f"[{stamp}] poll {n}: {type(exc).__name__}: "
                        f"{str(exc)[:120]}\n")
            time.sleep(seconds)
            continue
        snap = Snapshot.of(xml)
        if prev is None:
            (out_dir / f"{model}.baseline.xml").write_bytes(xml)
            with log.open("a") as f:
                f.write(f"[{stamp}] baseline: {len(snap.objects)} named objects, "
                        f"{len(xml)/1024:.0f} kB\n")
        else:
            changes = diff(prev, snap)
            if changes:
                (out_dir / f"{model}.latest.xml").write_bytes(xml)
                with log.open("a") as f:
                    f.write(f"\n[{stamp}] poll {n}: {len(changes)} change(s)\n")
                    f.write(report(changes, known) + "\n")
        prev = snap
        time.sleep(seconds)


def check(target: Target, model: str, edition: str) -> str:
    """One-shot: export a live model and report what the compiler does with it.

    The question this answers is not "does it round-trip" — that is necessary and
    nowhere near sufficient, as four separate bugs have now shown. It is "what does
    the product contain that we cannot reproduce", which is the only question whose
    answer shrinks over time.
    """
    import tempfile
    from collections import Counter
    from agent.compile.emit import emit
    from agent.compile.extract import extract
    from agent.compile.extract_app import extract_app
    from agent.compile.extract_certify import extract_certify
    from agent.browser.inspect import read_version
    from agent.ir.advise import advise
    from agent.ir.schema import IR
    from agent.ir.validate import validate

    raw = model_content(target, model, edition)
    src = Path(tempfile.mkdtemp()) / f"{model}.xml"
    src.write_bytes(raw)
    v = read_version(raw)

    ir, unresolved = extract(src)
    cert, app = extract_certify(src), extract_app(src)
    out = Path(tempfile.mkdtemp()) / "rt.xml"
    xml = emit(ir, platform_version=v.platform_version,
               repository_version=v.repository_version, certify=cert, app=app)
    out.write_text(xml)

    seen = Counter(e.tag for e in ET.fromstring(raw).iter() if e.tag[:1].isupper())
    made = {e.tag for e in ET.fromstring(xml).iter() if e.tag[:1].isupper()}
    missing = sorted(set(seen) - made, key=lambda t: -seen[t])

    lines = [f"{model} edition {edition} @ {v.platform_version}",
             f"  export {len(raw)/1024:.0f} kB -> emit {len(xml)/1024:.0f} kB",
             f"  round-trip  model={extract(out)[0].model_dump() == ir.model_dump()}"
             f"  certify={extract_certify(out).model_dump() == cert.model_dump()}"
             f"  app={extract_app(out).model_dump() == app.model_dump()}",
             f"  elements    {len(set(seen) & made)}/{len(seen)} emitted"]
    if unresolved:
        lines.append(f"  UNRESOLVED DATATYPES: {unresolved}")
    for t in missing:
        lines.append(f"    not emitted  {t:34s} x{seen[t]}")
    full = IR(model_ir=ir, certify=cert, app=app)
    issues = validate(full)
    lines.append(f"  ir_validate {[f'{i.rule}:{i.where}' for i in issues] or 'clean'}")
    lines.append(f"  advise      {[g.key for g in advise(full)] or 'none'}")
    return "\n".join(lines)


def _cli() -> None:                                     # python -m agent.watch
    import sys
    from agent.rest import Target as _T, load_env_file
    args = sys.argv[1:]
    if not args:
        print("usage: python -m agent.watch <env-file> <model> [edition]")
        raise SystemExit(2)
    env, model = args[0], args[1]
    edition = args[2] if len(args) > 2 else "0.0"
    print(check(_T.from_env(load_env_file(env)), model, edition))


if __name__ == "__main__":
    _cli()
