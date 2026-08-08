"""Every emitted element must sit in the container xDM actually uses.

This class of bug is INVISIBLE to the round-trip test. extract.py uses .iter(), which
finds an element wherever it sits, so emit could write <references> while xDM expects
<referenceRels> and the two would still agree with each other. Round-trip fidelity is
not correctness — the same lesson the silent String coercion taught.

The samples are the authority here, not the emitter.
"""
from __future__ import annotations

import sys
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent.compile.emit import emit  # noqa: E402
from agent.compile.emit_certify import emit_entity_certification  # noqa: E402  (import guard)
from agent.compile.extract import extract  # noqa: E402
from agent.compile.extract_certify import extract_certify  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = [ROOT / "samples" / n for n in (
    "gs-productretail-2025.1.0.xml",
    "corpus-a-org-mdm-0.1.xml",
    "gs-customerb2c-2025.1.0.xml")]


def containers(xml_or_path) -> dict[str, set[str]]:
    """element tag -> the set of parent tags it is ever found under."""
    root = (ET.parse(xml_or_path).getroot() if isinstance(xml_or_path, Path)
            else ET.fromstring(xml_or_path))
    out: dict[str, set[str]] = {}
    for parent in root.iter():
        for child in parent:
            if child.tag[:1].isupper():
                out.setdefault(child.tag, set()).add(parent.tag)
    return out


def witness(path: Path) -> Path:
    """One product export, or a skip naming the file that is not here."""
    if not path.exists():
        pytest.skip(f"{path.relative_to(ROOT)} not present")
    return path


def every_sample() -> list[Path]:
    """All three product exports, or a skip.

    `samples/` is not in the public export. Both fixtures below merge the container
    map across ALL three, and a map built from a subset is a different measurement
    wearing the same name (LESSONS §13) — so a partial corpus skips rather than
    quietly narrowing the claim. The complex-type and prefix tests further down build
    their input in memory and keep running there.
    """
    absent = [p for p in SAMPLES if not p.exists()]
    if absent:
        pytest.skip(", ".join(str(p.relative_to(ROOT)) for p in absent) + " not present")
    return SAMPLES


@pytest.fixture(scope="module")
def sample_containers():
    merged: dict[str, set[str]] = {}
    for p in every_sample():
        for tag, parents in containers(p).items():
            merged.setdefault(tag, set()).update(parents)
    return merged


@pytest.fixture(scope="module")
def emitted_containers():
    merged: dict[str, set[str]] = {}
    for p in every_sample():
        ir, _ = extract(p)
        xml = emit(ir, platform_version="2025.1.0", repository_version="2025.1.2",
                   certify=extract_certify(p))
        for tag, parents in containers(xml).items():
            merged.setdefault(tag, set()).update(parents)
    return merged


def test_every_emitted_element_uses_a_container_xdm_uses(emitted_containers,
                                                         sample_containers):
    wrong = {
        tag: (sorted(parents), sorted(sample_containers[tag]))
        for tag, parents in emitted_containers.items()
        if tag in sample_containers and not (parents & sample_containers[tag])
    }
    assert not wrong, "emitted under a container xDM never uses: " + repr(wrong)


def test_references_live_in_referencerels(emitted_containers):
    """The specific bug this file was written for."""
    assert emitted_containers["Reference"] == {"referenceRels"}


def test_subject_name_attribute_is_not_emitted_at_entity_level(emitted_containers):
    """It belongs to a ComplexType's name composition, not to an Entity. Emitting it
    under an Entity was wrong in placement AND shape — the real element carries only
    posInName and a ref. An Entity names its records through a display card."""
    assert "SubjectNameAttribute" not in emitted_containers


def test_the_check_can_fail(sample_containers):
    """A container test that cannot fail proves nothing."""
    bogus = "<metaDataExport><Model><references><Reference><name>x</name>" \
            "</Reference></references></Model></metaDataExport>"
    got = containers(bogus)["Reference"]
    assert not (got & sample_containers["Reference"])


def test_complex_type_members_are_DefinitionAttribute_not_AtomicAttribute():
    """The fourth instance of "round-trip fidelity is not correctness".

    extract looked for AtomicAttribute inside a ComplexType and found none, so every
    complex type extracted with ZERO members and emitted as an empty shell — an
    AddressType with no street, city or postcode. Both passes agreed on the same wrong
    element name, so the round-trip stayed green throughout.

    Caught by watching a live model: the operator built a ComplexType in the UI and the
    watcher flagged DefinitionAttribute as a type the compiler could not emit.
    """
    from agent.compile.extract import extract
    for name in ("corpus-a-org-mdm-0.1", "gs-customerb2c-2025.1.0"):
        ir, _ = extract(witness(ROOT / "samples" / f"{name}.xml"))
        ct = ir.complex_types[0]
        assert ct.members, f"{name}: complex type {ct.name} extracted with no members"
        assert all(m.type and m.name for m in ct.members)


def test_the_emitted_complex_type_uses_the_container_the_product_uses():
    from xml.etree import ElementTree as ET
    from agent.compile.emit import emit
    from agent.compile.extract import extract
    ir, _ = extract(witness(ROOT / "samples" / "corpus-a-org-mdm-0.1.xml"))
    root = ET.fromstring(emit(ir, platform_version="2025.1.0",
                              repository_version="2025.1.2"))
    ct = root.find(".//ComplexType")
    assert ct.find("definitionAttributes") is not None
    assert ct.find("atomicAttributes") is None
    assert len(ct.find("definitionAttributes")) == 8
    assert {c.tag for c in ct.find("definitionAttributes")} == {"DefinitionAttribute"}


def test_two_complex_attributes_never_share_a_physical_prefix():
    """xDM expands a complex attribute into one physical column per member, all sharing
    a 3-char prefix, so two of them cannot share one — `Address` and `AddressBilling`
    both want ADD and the model fails validation.

    INVISIBLE FROM THE CORPUS: every sample and every live model has exactly one complex
    attribute per entity, always `Address`, always `ADD`. Reported by the operator from
    using the product; the UI's convention on collision is ADD then AD2.
    """
    from agent.compile.emit import complex_prefixes
    from agent.ir.schema import ComplexAttribute
    attrs = [ComplexAttribute(name=n, type="T") for n in
             ("Address", "AddressBilling", "AddressShipping", "Contact")]
    got = complex_prefixes(attrs)
    assert got["Address"] == "ADD" and got["AddressBilling"] == "AD2"
    assert len(set(got.values())) == len(got), got


def test_the_derivation_matches_what_the_product_actually_assigns():
    """Verified against a live instance on 2026-08-03. The operator created a second
    complex attribute on a fuzzy entity — Address then AddressStandardized — and xDM
    assigned ADD then AD2. The derivation reproduces it exactly.

    This is the only observation of a prefix COLLISION in existence: every sample and
    every other live model has one complex attribute per entity."""
    from agent.compile.emit import complex_prefixes
    from agent.ir.schema import ComplexAttribute
    got = complex_prefixes([ComplexAttribute(name="Address", type="T"),
                            ComplexAttribute(name="AddressStandardized", type="T")])
    assert got == {"Address": "ADD", "AddressStandardized": "AD2"}


def test_an_author_pinned_prefix_is_respected_and_reserved():
    from agent.compile.emit import complex_prefixes
    from agent.ir.schema import ComplexAttribute
    got = complex_prefixes([ComplexAttribute(name="Address", type="T",
                                             physical_prefix="XYZ"),
                            ComplexAttribute(name="AddressBilling", type="T")])
    assert got == {"Address": "XYZ", "AddressBilling": "ADD"}


def test_a_hand_pinned_prefix_collision_is_an_ir_error():
    from agent.compile.extract import extract
    from agent.ir.schema import IR, ComplexAttribute
    from agent.ir.validate import validate
    ir, _ = extract(witness(ROOT / "samples" / "corpus-a-org-mdm-0.1.xml"))
    e = next(x for x in ir.entities if x.complex_attributes)
    e.complex_attributes[0].physical_prefix = "ADD"
    e.complex_attributes.append(ComplexAttribute(
        name="AddressBilling", type=e.complex_attributes[0].type,
        physical_prefix="ADD"))
    hit = [i for i in validate(IR(model_ir=ir)) if i.rule == "IR-018"]
    assert hit and "already used by" in hit[0].message
