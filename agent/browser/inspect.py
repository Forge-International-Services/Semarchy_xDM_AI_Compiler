"""Read the live instance. Sprint 08, read-only.

No browser here. The sprint-08 rescope moved the two things this module reads —
version stamps and data locations — onto the management REST API, which is scriptable
and live-verified. Only validation still needs a browser.

The version stamps come from an EXPORT's `exportInfo`, not from any page. A page is a
version-fragile thing to scrape; an export is the same artifact the compiler has to
match, which is the point: emit refuses to compile without them, because import is
refused across product versions even to a NEWER target
(docs/Manage/models/move-models-at-design-time.md).
"""
from __future__ import annotations

from dataclasses import dataclass
from xml.etree import ElementTree as ET

from agent.rest import RestError, Target, data_locations, model_content

# ModelConfiguration.type -> the dbType a data location reports. A model built for one
# technology cannot deploy onto another, and the failure is worth catching before the
# deploy rather than during it.
TECHNOLOGY_DBTYPE = {"SNOWFLAKE": "SNOWFLAKE", "POSTGRESQL": "POSTGRESQL"}


@dataclass(frozen=True)
class TargetVersion:
    platform_version: str
    repository_version: str
    model_uuid: str

    def as_status_yaml(self) -> dict:
        return {"platform_version": self.platform_version,
                "repository_version": self.repository_version}


def read_version(xml: bytes) -> TargetVersion:
    """Pull the stamps out of an export. Works on a file or a REST response body."""
    root = ET.fromstring(xml)
    info = root.find("exportInfo")
    if info is None:
        raise RestError(
            "export has no <exportInfo>; this is not a metaDataExport document")
    for key in ("platformVersion", "repositoryVersion"):
        if not info.attrib.get(key):
            raise RestError(f"export's exportInfo carries no {key}")
    return TargetVersion(platform_version=info.attrib["platformVersion"],
                         repository_version=info.attrib["repositoryVersion"],
                         model_uuid=info.attrib.get("modelUUID", ""))


def read_target_version(target: Target, model: str, edition: str,
                        *, opener=None) -> TargetVersion:
    return read_version(model_content(target, model, edition, opener=opener))


@dataclass(frozen=True)
class DataLocation:
    """A deployment target, and WHAT IS CURRENTLY DEPLOYED TO IT.

    The second half is the part sprint 09 needs and an earlier version of this class
    dropped. `modelName` + `modelEditionKey` say which edition a location is serving;
    without them a preflight cannot tell whether it is about to replace the edition it
    thinks it is. Read off the live response — an earlier probe guessed the key names
    `dataSourceName` and `model` and got None for both, which read as "the API does not
    return this" when it plainly does.
    """
    name: str
    type: str                    # DEV / TEST / PROD
    db_type: str                 # SNOWFLAKE / POSTGRESQL / …
    db_name: str = ""
    db_schema: str = ""
    status: str = ""
    label: str = ""
    data_source: str = ""        # the JEE datasource the location binds
    model: str = ""              # deployed model, "" if nothing is deployed
    edition_key: str = ""        # e.g. "0.0"
    deployed_at: str = ""
    id: str = ""

    @property
    def is_dev(self) -> bool:
        return self.type.upper() == "DEV"

    @property
    def is_ready(self) -> bool:
        return self.status.upper() == "DL_READY"

    @property
    def deployed(self) -> bool:
        return bool(self.model)

    def describes(self, model: str, edition: str) -> bool:
        """True when this location currently serves exactly that model edition."""
        return self.model == model and self.edition_key == edition


def read_data_locations(target: Target, *, opener=None) -> list[DataLocation]:
    return [DataLocation(name=d.get("name", ""), type=d.get("type", ""),
                         db_type=d.get("dbType", ""), db_name=d.get("dbName", ""),
                         db_schema=d.get("dbSchema", ""), status=d.get("status", ""),
                         label=d.get("label", ""), data_source=d.get("dataSource", ""),
                         model=d.get("modelName") or "",
                         edition_key=d.get("modelEditionKey") or "",
                         deployed_at=d.get("deploymentDate") or "",
                         id=d.get("id", ""))
            for d in data_locations(target, opener=opener)]


def deployment_targets(locations: list[DataLocation], model: str,
                       technology: str) -> tuple[list[DataLocation], list[str]]:
    """Split locations into (safe to deploy this model, reasons the rest are not).

    D9 restricts deployment to DEV until a model is refined, so a non-dev location is
    excluded here rather than merely warned about — the gate to production is a
    separate, deliberate act (a CLOSED edition promoted to a remote repository).
    """
    ok, why = [], []
    for d in locations:
        if not d.is_dev:
            why.append(f"{d.name}: type is {d.type}, and D9 restricts deployment to DEV")
            continue
        if not d.is_ready:
            why.append(f"{d.name}: status is {d.status or 'unknown'}, not DL_READY")
            continue
        mismatch = technology_mismatch(technology, d)
        if mismatch:
            why.append(f"{d.name}: {mismatch}")
            continue
        if d.deployed and d.model != model:
            why.append(f"{d.name}: already serves {d.model} {d.edition_key} — "
                       f"deploying {model} here would replace a different model")
            continue
        ok.append(d)
    return ok, why


def technology_mismatch(model_technology: str, location: DataLocation) -> str | None:
    """None if the model can deploy here, otherwise why not.

    `model_technology` is the IR's `model.target_technology` — the same value that
    reaches ModelConfiguration.type in the XML.
    """
    want = TECHNOLOGY_DBTYPE.get(model_technology.upper())
    if want is None:
        return (f"model targets {model_technology!r}, which is not a technology any "
                f"sample or this agent knows; refusing to guess whether "
                f"{location.name!r} ({location.db_type}) is compatible")
    if location.db_type.upper() != want:
        return (f"model targets {want} but data location {location.name!r} is "
                f"{location.db_type or 'unknown'} — deployment would fail")
    return None
