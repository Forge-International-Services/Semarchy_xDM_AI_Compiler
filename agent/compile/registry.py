"""Platform datatype UUIDs — the refs that resolve outside the export file.

Sprint 05. `abstractAtomicType` points at a built-in type the repository owns and
does not serialize. Everything else an attribute can point at (LOV types, user-
defined types) IS defined in the file and resolves locally.

Measured across both samples: CORPUS_A carries 5 external refs, gs-productretail 2,
and gs's are a strict subset of corpus model A's. Small and closed-form — but see the caveat
below before trusting it.
"""
from __future__ import annotations

import collections
from pathlib import Path
from xml.etree import ElementTree as ET

# OBSERVED, not inferred. All twelve read off a live instance on 2026-08-03 by the
# bootstrap below: a scratch entity with one attribute per built-in type, exported and
# harvested. Platform 2025.1.8.20251031-a7af69c, repository 2025.1.2.
#
# THE BOOTSTRAP EARNED ITS KEEP IMMEDIATELY. The previous six entries were inferred by
# correlating UUIDs with the attributes that used them across four sample models. Five
# were right. ONE WAS NOT:
#
#     2651ea73  registry said Integer      really LongInteger
#     af1d41f3  registry said "unknown"    really Integer
#
# So every model the compiler emitted with `type: Integer` produced a LongInteger
# column, and the real Integer was being reported as an unharvested type. Both are
# integral so nothing crashed — it was silently the wrong column type, which is the
# most expensive kind of wrong this compiler can be.
#
# The lesson generalises past datatypes: inference from samples is a HYPOTHESIS, and
# five-out-of-six looks exactly like six-out-of-six until something checks.
PLATFORM_TYPES: dict[str, str] = {
    "fc23292f-5d70-4034-a036-4f793797ff90": "String",
    "59c7c2e5-eb4c-43c8-a05c-387068204ff7": "Boolean",
    "de671443-9434-4fa4-afdf-ae3e4b3a20b2": "Date",
    "1ee2a456-c81d-48b5-8f03-5ae3eecdc451": "UUID",
    "2723f319-ee11-4d0d-8c03-0f9d9c2b4f7e": "Decimal",
    "af1d41f3-b76c-4bb9-85bb-81d730622f25": "Integer",       # precision 10
    "2651ea73-ce56-4754-9f55-7eccc02ccb92": "LongInteger",    # precision 38
    "c0f966b7-b83d-48f4-b5f6-dc2ee971f152": "ShortInteger",   # precision 5
    "de35a802-d9f9-4a6c-a614-41dc5eff6a42": "ByteInteger",    # precision 3
    "fa963117-443e-4a9a-a2a3-73ae1c7d17d4": "Timestamp",      # precision 3 (frac. sec)
    "a6934a93-4578-4efa-bd6f-c4bca87b66f9": "LongText",
    "dfebbb0e-68a2-4d77-8975-a3297327deac": "Binary",
}

# The per-type precision defaults the UI applies, which is how the integral types tell
# themselves apart in an export. Recorded because it is the evidence that identified
# the mis-registration above before the harvest confirmed it.
PRECISION_DEFAULTS = {"ByteInteger": 3, "ShortInteger": 5, "Integer": 10,
                      "LongInteger": 38, "Timestamp": 3}

# Nothing left unidentified: all twelve documented built-ins are now mapped.
UNIDENTIFIED: dict[str, str] = {}

class UnknownPlatformType(KeyError):
    """The name is not an xDM datatype at all. A real modelling error."""


class UnharvestedType(KeyError):
    """A DOCUMENTED built-in whose UUID has not been read off this instance yet.

    Not a limitation of xDM and not a modelling error — a missing lookup. The
    distinction matters: "Decimal is unsupported" is false and would push a designer
    to model a price as a String, which is exactly the silent mis-type the sentinel
    in extract.py exists to prevent.

    All twelve are mapped as of the 2026-08-03 harvest, so this should now fire only
    against a platform version whose UUIDs have not been re-harvested.
    """


def type_uuid(name: str) -> str:
    """xDM type name -> platform UUID, or an error that says which kind of gap it is."""
    from agent.tools.schema_ingest import XDM_TYPES
    for uuid, n in PLATFORM_TYPES.items():
        if n == name:
            return uuid
    if name in XDM_TYPES:
        raise UnharvestedType(
            f"{name!r} IS a documented xDM built-in type "
            f"(docs/Design/logical-model/built-in-datatypes.md), but its platform UUID "
            f"has not been harvested from THIS instance. Known: "
            f"{len(PLATFORM_TYPES)}/{len(XDM_TYPES)}. Re-run the BOOTSTRAP below "
            f"against the target — a one-time lookup per platform version.")
    raise UnknownPlatformType(
        f"{name!r} is not an xDM datatype. The built-ins are: {sorted(XDM_TYPES)}")


# BOOTSTRAP — how to close the gap, once per platform version
# ----------------------------------------------------------
# There is no API that lists datatypes (checked against the live instance: neither the
# ADMIN nor APP_BUILDER OpenAPI domain exposes one), and a UUID cannot be derived, only
# observed. There is also a chicken-and-egg: emitting a model that uses Decimal needs
# Decimal's UUID.
#
# Break it in the UI, once:
#   1. create a scratch model with one entity carrying one attribute per built-in type
#   2. export it   GET /app-builder/models/{name}/editions/{key}/content
#   3. run harvest() over the export and paste the result into PLATFORM_TYPES
#
# The lab instance (.env-lab) is the place to do this: it is a training environment,
# it needs no Snowflake PAT, and its one data location is DEV. Note it runs
# POSTGRESQL, so a model built there must set target_technology: postgresql.
#
# This is D8's demonstration-harvest loop applied to datatypes. RUN 2026-08-03 against
# the lab instance; all twelve are now mapped and no model is blocked on a type again.
#
# Two things worth knowing before running it on another platform version:
#   - the Finish button in the attribute dialog needs a DOUBLE click; a single click
#     only focuses it, and the next thing typed lands in the still-open dialog
#   - a Sequence-generated PK is forced to LongInteger, so the PK alone yields one type
#
# UUIDs are per-platform-version until proven otherwise. R8 stands: every sample shares
# repositoryVersion 2025.1.2, so nothing here is demonstrated ACROSS versions. Re-run
# the harvest against a new target before trusting these.


def resolve(uuid: str) -> str:
    if uuid in PLATFORM_TYPES:
        return PLATFORM_TYPES[uuid]
    hint = UNIDENTIFIED.get(uuid)
    raise UnknownPlatformType(
        f"{uuid} is not a known platform datatype"
        + (f" ({hint})" if hint else "")
        + ". Harvest the registry from a target export rather than guessing.")


def harvest(*export_paths: str | Path) -> dict[str, list[str]]:
    """Report every externally-referenced datatype UUID and what uses it.

    This is the `--harvest-registry` step: run it against an export from the TARGET
    instance and confirm every UUID matches, rather than assuming ours transfer.
    """
    usage: dict[str, list[str]] = collections.defaultdict(list)
    for path in export_paths:
        root = ET.parse(path).getroot()
        local = {e.attrib.get("val") for e in root.iter("internalID")}
        for attr in root.iter():
            t = attr.find("abstractAtomicType")
            if t is None:
                continue
            ref = t.attrib.get("ref")
            if ref and ref not in local:
                usage[ref].append(attr.findtext("name") or "?")
    return dict(usage)
