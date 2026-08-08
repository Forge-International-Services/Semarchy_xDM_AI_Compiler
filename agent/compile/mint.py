"""Deterministic UUID minting. Sprint 05.

A recompile must be diffable, so a UUID is a pure function of the object's logical
path rather than something random. Same IR in, same UUIDs out, forever.

Consequence worth stating: renaming an object changes its UUID, so xDM sees delete
+ create rather than an update. Under D7 the whole model is re-imported each
iteration anyway, so this is harmless in the refine loop — but it means a rename is
never an in-place edit, which matters when reasoning about record lineage.
"""
from __future__ import annotations

import uuid

# Fixed for the life of the project. Changing it re-mints every UUID in every model.
NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def mint(*path: str) -> str:
    """mint("Customer", "attr", "Email") -> a stable UUID for that object."""
    return str(uuid.uuid5(NAMESPACE, "/".join(path)))
