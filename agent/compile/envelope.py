"""The metaDataExport envelope: exportInfo, RootModel, Model. Sprint 05.

The version stamps come from the LIVE TARGET, never from a sample and never from a
default: import is refused across product versions, even to a newer target
(docs/Manage/models/move-models-at-design-time.md).
"""
from __future__ import annotations

import json
from xml.etree import ElementTree as ET

from agent.compile.mint import mint

TEMPLATE_ID = "com.semarchy.runtime.templates.defaultRuntimeTemplate"

# The NGModel body, verbatim from live exports. Workflows are D6-out-of-scope, so the
# lists stay empty; a model that HAS workflows would carry them here.
NG_MODEL_BODY = '{"e2eTests":[],"workflowDefinitions":[],"x-spec-version":"1.12"}'

# Audit fields are pinned rather than stamped with wall-clock time, or compiling
# twice would not be byte-identical (RED-TEAM R7). The repository owns these values
# after import anyway.
EPOCH = "2000-01-01T00:00:00.000Z"
USER = "xdm-agent"
BRANCH_ID = "0"
# The FIRST edition of a model is 0, not 1. `create_model` makes edition 0.0, and the
# import target is that edition — declaring editionId=1 in exportInfo while posting to
# .../editions/0.0/content is a contradiction the importer rejects.
EDITION_ID = "0"


XML_DECL = '<?xml version="1.0" encoding="UTF-8"?>'


def audit(parent: ET.Element, internal_id: str, *, branch_edition: bool = True) -> None:
    """The block almost every persisted object carries (authoring guide §2).

    `branch_edition=False` for RootModel, which is the one persisted object that does
    NOT carry internalBranchID/internalEditionID — it sits above the branch/edition
    tree rather than inside it. Emitting them there was one of two reasons the first
    Import-Replace was rejected with "Unable to parse payload".
    """
    pairs = (("internalBranchID", BRANCH_ID), ("internalEditionID", EDITION_ID)) \
        if branch_edition else ()
    for tag, val in pairs + (
        ("internalCreationDate", EPOCH),
        ("internalUpdateDate", EPOCH),
        ("internalRevisionID", "1"),
    ):
        ET.SubElement(parent, tag, val=val)
    for tag in ("internalCreationUser", "internalUpdateUser"):
        ET.SubElement(parent, tag).text = USER
    ET.SubElement(parent, "internalID", val=internal_id)


# xDM's own name for the target technology, from ModelConfiguration.type. Observed
# SNOWFLAKE (CORPUS_A, per D13) and POSTGRESQL (both vendor samples).
TECHNOLOGY = {"snowflake": "SNOWFLAKE", "postgresql": "POSTGRESQL"}


def build(model_name: str, label: str | None, *,
          platform_version: str, repository_version: str,
          technology: str = "snowflake",
          workflows=()) -> tuple[ET.Element, ET.Element]:
    """Return (root, model_el) with the envelope in place.

    The envelope is not decoration. A real export carries a RootModel branch/edition
    tree, a ModelConfiguration naming the target technology, a RetentionPolicy and an
    NGModel sibling. Emitting a bare RootModel + Model round-tripped perfectly — the
    extractor only ever reads Model content — while producing a file no live instance
    has been asked to accept. Whether import REQUIRES these is a sprint-09 question;
    reproducing what every sample contains is the cheap side of that bet.
    """
    if not platform_version or not repository_version:
        raise ValueError(
            "platform_version and repository_version must be read from the target "
            "instance — import is refused across product versions")

    model_uuid = mint("model", model_name)
    root = ET.Element("metaDataExport")
    ET.SubElement(root, "exportInfo", modelUUID=model_uuid, branchId=BRANCH_ID,
                  editionId=EDITION_ID, platformVersion=platform_version,
                  repositoryVersion=repository_version)

    root_model = ET.SubElement(root, "RootModel")
    audit(root_model, model_uuid, branch_edition=False)
    ET.SubElement(root_model, "description", null="true")
    ET.SubElement(root_model, "name").text = model_name
    ET.SubElement(root_model, "label").text = label or model_name
    ET.SubElement(root_model, "templateID").text = TEMPLATE_ID

    branch_uuid = mint("model", model_name, "branch")
    ET.SubElement(root_model, "rootModelBranch", ref=branch_uuid)
    branches = ET.SubElement(root_model, "modelBranches")
    branch = ET.SubElement(branches, "ModelBranch")
    audit(branch, branch_uuid, branch_edition=False)
    ET.SubElement(branch, "description").text = f"The root branch for {label or model_name}"
    ET.SubElement(branch, "name").text = f"{model_name}_Root"
    ET.SubElement(branch, "label").text = f"{label or model_name} Root branch"
    ET.SubElement(branch, "branchID", val=BRANCH_ID)
    ET.SubElement(branch, "parentModelEdition", null="true")
    editions = ET.SubElement(branch, "modelEditions")
    edition = ET.SubElement(editions, "ModelEdition")
    # Keyed WITHOUT EDITION_ID: including it made the edition UUID collide with
    # another mint the moment EDITION_ID changed from "1" to "0".
    audit(edition, mint("model", model_name, "modelEdition"),
          branch_edition=False)
    ET.SubElement(edition, "description", null="true")
    ET.SubElement(edition, "editionID", val=EDITION_ID)
    # OPEN, not CLOSED: the model is still being refined (D9 keeps it in dev until it
    # is). Closing an edition is what promotion to a remote repository needs, and that
    # is a deliberate, later act.
    ET.SubElement(edition, "status", val="OPEN")
    ET.SubElement(edition, "lockUUID", null="true")

    # THE MODEL ELEMENT NEEDS ITS OWN IDENTITY. Emitting a bare <Model> and filling
    # only its children produced a document the importer rejected outright with
    # "Unable to parse payload". Every round-trip passed anyway, because extract reads
    # the model name from RootModel and only ever reads Model's CHILDREN — it never
    # looked at Model's own name or internalID, so neither pass missed what neither
    # pass wrote. Fifth instance of that failure mode.
    #
    # Model DOES carry internalBranchID/internalEditionID, unlike RootModel: it is the
    # content of one branch and edition, where RootModel sits above both.
    model = ET.SubElement(root, "Model")
    audit(model, model_uuid)
    ET.SubElement(model, "description", null="true")
    ET.SubElement(model, "name").text = model_name
    ET.SubElement(model, "label").text = label or model_name
    # NGModel IS NOT EMPTY. It carries a JSON document as its text body, and the
    # importer parses it — an empty <NGModel/> is what produced "Unable to parse
    # payload" on every attempt. The error names the JSON payload, not the XML.
    #
    # Observed identically in every export from platform 2025.1.8. `x-spec-version`
    # is the NG (next-gen) spec version and is NOT the product version — it is
    # emitted verbatim rather than derived, because nothing observed says how the two
    # relate.
    #
    # BUILT FROM THE IR since 2026-08-06. The constant below is what an empty
    # `workflows:` produces, byte for byte, so a model without workflows is unchanged
    # and the change cannot regress the four scenarios that already deploy.
    from agent.compile.emit_workflow import ng_model
    ET.SubElement(root, "NGModel").text = json.dumps(
        ng_model(workflows), separators=(",", ":"))
    return root, model


def model_config(model_el: ET.Element, model_name: str, technology: str) -> None:
    """ModelConfiguration and RetentionPolicy, emitted after the model's content.

    ModelConfiguration.type is where the IR's `target_technology` (D13) finally lands.
    Until this existed, a model built for Snowflake said so nowhere in its XML.
    """
    if technology not in TECHNOLOGY:
        from agent.compile.emit import EmitError
        raise EmitError(
            f"target technology {technology!r} is not one observed in any sample; "
            f"known: {sorted(TECHNOLOGY)}")
    holder = ET.SubElement(model_el, "modelConfiguration")
    cfg = ET.SubElement(holder, "ModelConfiguration")
    audit(cfg, mint("model", model_name, "configuration"))
    ET.SubElement(cfg, "type", val=TECHNOLOGY[technology])

    holder = ET.SubElement(model_el, "retentionPolicy")
    rp = ET.SubElement(holder, "RetentionPolicy")
    audit(rp, mint("model", model_name, "retentionPolicy"))
    # FOREVER on all four axes — what all three samples carry. Retention is a policy
    # decision nobody has made yet, and "keep everything" is the only safe default.
    for axis in ("history", "deletions", "sourceData", "sourceErrors"):
        ET.SubElement(rp, f"{axis}Type", val="FOREVER")
        ET.SubElement(rp, f"{axis}Duration", null="true")
        ET.SubElement(rp, f"{axis}Unit", null="true")
    ET.SubElement(rp, "description", null="true")
