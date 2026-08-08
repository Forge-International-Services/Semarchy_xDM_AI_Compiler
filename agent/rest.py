"""The management REST API client. Sprint 08 (read) / sprint 09 (write).

TWO HEADERS, TWO SYSTEMS. This is the single most expensive thing to get wrong here,
so it is encoded once:

    Authorization: Snowflake Token="<PAT>"   -> Snowflake. SPCS gates ingress.
    API-key: <key>                           -> Semarchy. xDM authorizes the caller.

They are not two credentials for one system. The Snowflake header is NOT Bearer and
NOT Basic — docs/Install/snowflake/deploy-in-snowflake.md is explicit that SPCS
endpoints "do not accept the standard Bearer authentication scheme" — and the double
quotes around the token are part of the header value.

Scope, verified against docs/Manage/management-rest-api.md: this API is MODEL-LEVEL.
It imports and exports whole models and manages branches, editions and data locations.
There are NO per-object authoring endpoints — no call creates an entity, an attribute,
a matcher or an enricher. Anything that needs one goes through the UI (D8).
"""
from __future__ import annotations

import os
import pathlib
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

import json

TIMEOUT = 60

# Snowflake's custom scheme, per docs/Install/snowflake/deploy-in-snowflake.md:
#     Authorization: Snowflake Token="<pat>"
# The double quotes are part of the header value, and there is no Bearer variant.
_SNOWFLAKE = re.compile(r'^Snowflake\s+Token\s*=\s*".+"\s*$')


class RestError(RuntimeError):
    """`status` is the HTTP code when there was one, else None.

    Carried as an attribute rather than left in the message text because at least one
    caller has to BRANCH on it — `create_data_location`, where a 5xx may mean the
    write succeeded — and re-parsing a formatted string to recover a number the
    handler already had is how that branch silently stops matching.
    """

    def __init__(self, *args, status: int | None = None):
        super().__init__(*args)
        self.status = status


class TokenExpired(RestError):
    """Auth failed. PAT issuance and expiry are controlled by the Snowflake account, so
    a long refine loop can outlive its token. This is 'ask the human', not a bug.

    IT IS NOT ALWAYS A 401. Verified against the live SPCS deployment 2026-08-03: a
    request with a stale token returns **HTTP 200 and the LoginUi HTML page**. Keying
    this off the status code alone means the handler never fires and the caller gets
    24 kB of HTML where it expected JSON.
    """


class NotConfigured(RestError):
    pass


@dataclass(frozen=True)
class Target:
    url: str
    authorization: str
    api_key: str

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Target":
        """Build a target from the environment.

        AUTH IS DEPLOYMENT-SPECIFIC, and assuming otherwise is what this method got
        wrong first time round:

          SPCS (Snowflake native app)   Authorization: Snowflake Token="<pat>"
                                        API-key: <key>
                                        Two headers, two systems — the PAT gets you
                                        through Snowflake's ingress, the key
                                        authorizes you to xDM behind it.

          Standard xDM deployment       API-key: <key>
                                        No ingress gate, so no Authorization at all.
                                        The training instances are like this.

        So SEMARCHY_AUTHORIZATION is OPTIONAL. Requiring it refused a perfectly valid
        lab configuration.
        """
        e = os.environ if env is None else env
        missing = [k for k in ("SEMARCHY_URL", "SEMARCHY_API_KEY") if not e.get(k)]
        if missing:
            raise NotConfigured(
                f"missing {', '.join(missing)} — see .env.example. Load with "
                f"`set -a && source .env && set +a`.")
        auth = (e.get("SEMARCHY_AUTHORIZATION") or "").strip()
        if auth:
            _check_auth_format(auth)
        return cls(url=e["SEMARCHY_URL"].rstrip("/"),
                   authorization=auth, api_key=e["SEMARCHY_API_KEY"])

    @property
    def is_spcs(self) -> bool:
        return self.authorization.startswith("Snowflake")

    def headers(self) -> dict[str, str]:
        h = {"API-key": self.api_key,
             "Content-Type": "application/json", "Accept": "*/*"}
        # Omitted entirely when absent. Sending an empty Authorization is not the same
        # as not sending one, and some gateways reject the empty form.
        if self.authorization:
            h["Authorization"] = self.authorization
        return h


SCHEMES = ("Snowflake", "Basic", "Bearer")


def _check_auth_format(auth: str) -> None:
    """Validate a PRESENT Authorization value. Absent is legal — see from_env."""
    if _SNOWFLAKE.match(auth):
        return
    if auth.startswith("Snowflake"):
        raise NotConfigured(
            "SEMARCHY_AUTHORIZATION starts with 'Snowflake' but is not in the format "
            "Snowflake Token=\"<pat>\". The DOUBLE quotes are part of the header "
            "value, and the whole thing needs SINGLE quotes in .env or `source` "
            "truncates it at the space:\n"
            "    SEMARCHY_AUTHORIZATION='Snowflake Token=\"<pat>\"'")
    if auth.split(" ", 1)[0] in SCHEMES:
        return                                  # Basic / Bearer, for a non-SPCS target
    raise NotConfigured(
        f"SEMARCHY_AUTHORIZATION has no recognised scheme. Expected one of "
        f"{', '.join(SCHEMES)} — for example 'Snowflake Token=\"<pat>\"' on SPCS, or "
        f"'Basic <base64 user:password>' elsewhere. A BARE token is the common "
        f"mistake: the scheme is what the gateway reads, and without it the request is "
        f"unauthenticated and comes back as a login page with HTTP 200. Leave this "
        f"BLANK for a deployment that needs no ingress credential.")


# The login page is served with HTTP 200, so the body is the only signal. Matched on
# the app bundle name rather than a generic "<html>", which an error page could also be.
_LOGIN_MARKERS = (b"LoginUi", b"/assets/ui/Login")


def _reject_login_page(url: str, body: bytes) -> None:
    if any(m in body[:4096] for m in _LOGIN_MARKERS):
        raise TokenExpired(
            f"{url} returned the LOGIN PAGE with HTTP 200 — this deployment does not "
            f"answer a stale credential with a 401. The Snowflake PAT or the xDM "
            f"API-key is expired or revoked; both are issued outside this agent, so "
            f"ask the operator for fresh values.")


def get(target: Target, path: str, *, opener=None) -> tuple[int, bytes]:
    """One read. Returns (status, body); raises TokenExpired on a 401 OR a login page.

    `opener` exists so tests exercise the header contract without a live instance —
    the headers are the part worth testing, and they are built here.
    """
    url = f"{target.url}/{path.lstrip('/')}"
    req = urllib.request.Request(url, headers=target.headers(), method="GET")
    send = opener or urllib.request.urlopen
    try:
        with send(req, timeout=TIMEOUT) as resp:
            body = resp.read()
        _reject_login_page(url, body)
        return resp.status, body
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise TokenExpired(
                f"401 from {url}. The Snowflake PAT has most likely expired — its "
                f"issuance and renewal are controlled by the Snowflake account, not by "
                f"this agent. Ask the operator for a fresh token.") from None
        raise RestError(f"HTTP {exc.code} from {url}: "
                        f"{exc.read()[:300].decode('utf8', 'replace')}") from None


def get_json(target: Target, path: str, *, opener=None) -> Any:
    status, body = get(target, path, opener=opener)
    if status == 204 or not body:
        return None
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        # The login page is already caught in get(). Anything else non-JSON here is a
        # wrong path or an unexpected content type, not an auth problem.
        raise RestError(
            f"{path} returned {len(body)} bytes that are not JSON: "
            f"{body[:120].decode('utf8', 'replace')!r}") from None


# ------------------------------------------------------------------ read paths
def data_locations(target: Target, *, opener=None) -> list[dict]:
    """Data locations and their immutable type/dbType. Sprint 09 needs both.

    The agent DISCOVERS data locations here; it never hardcodes a name. The one in
    status.yaml is recorded observed environment state, not configuration.
    """
    out = get_json(target, "app-builder/data-locations", opener=opener)
    return out if isinstance(out, list) else out.get("dataLocations", []) if out else []


def model_content(target: Target, model: str, edition: str, *, opener=None) -> bytes:
    """The full metaDataExport XML for one model edition."""
    _, body = get(target, f"app-builder/models/{model}/editions/{edition}/content",
                  opener=opener)
    return body


# ------------------------------------------------------------------- diagnostics
def doctor(env: dict[str, str] | None = None, *, opener=None) -> tuple[bool, list[str]]:
    """Check a target end to end and say exactly what is wrong. Returns (ok, lines).

    Written because "does this work?" was costing a round of ad-hoc probing every time
    a credential changed, and because the two failure modes here are both misleading:
    a truncated Authorization header looks like a bad token, and a stale credential
    comes back as HTTP 200 with a login page rather than a 401.

    NEVER prints a secret — only whether one is set and how long it is.
    """
    out: list[str] = []
    try:
        target = Target.from_env(env)
    except NotConfigured as exc:
        return False, [f"config: {exc}"]

    out.append(f"url            {target.url}")
    # Report the SHAPE, never any slice of the value. An earlier version printed
    # `authorization.split(" ")[0]` as "the scheme" — on a bare token there is no
    # space, so it printed the entire PAT.
    if target.authorization:
        out.append(f"authorization  set, {len(target.authorization)} chars, "
               f"scheme={target.authorization.split(' ', 1)[0]}")
        if not target.is_spcs:
            out.append("               (not SPCS — no Snowflake ingress gate)")
    else:
        out.append("authorization  ABSENT — correct for a standard xDM deployment; "
                   "required only on SPCS")
    out.append(f"api-key        set, {len(target.api_key)} chars")

    if "/semarchy/api" not in target.url:
        out.append("WARNING: SEMARCHY_URL does not contain /semarchy/api — REST "
                   "endpoints live under https://<xdm_server_url>/semarchy/api/")

    try:
        locations = data_locations(target, opener=opener)
    except TokenExpired as exc:
        return False, out + [f"auth: {exc}"]
    except RestError as exc:
        return False, out + [f"request failed: {exc}"]
    except OSError as exc:
        return False, out + [f"network: cannot reach {target.url} — {exc}"]

    out.append(f"data locations {len(locations)} found")
    for d in locations:
        out.append(f"  - {d.get('name')} type={d.get('type')} "
                   f"dbType={d.get('dbType')} status={d.get('status')} "
                   f"probe={probe_data_location(target, d.get('name', ''), opener=opener)}")
    if not any(str(d.get("type", "")).upper() == "DEV" for d in locations):
        out.append("WARNING: no DEV data location. D9 restricts deployment to dev "
                   "until the model is refined, so there is nowhere safe to import.")
    return True, out


def probe_data_location(target: Target, location: str, *, opener=None) -> str:
    """The platform's own readiness probe for one data location, as a short verdict.

    `GET probes/data-locations/{name}/api` — one of three paths in the `probes`
    OpenAPI domain (read 2026-08-08; the other two are `probes/started` and a
    per-application probe). Measured on the lab: 204 with an empty body on a ready
    location. Sprint 12 wired it into `doctor` because `status=DL_READY` is the
    REPOSITORY's opinion of the location and the probe is the RUNTIME's — §24's
    stale-status lesson is exactly the gap between those two registers.

    Returns 'ready' / 'HTTP <code>' / the error, never raises: the probe decorates
    the doctor report and a probe failure is a finding, not a crash.
    """
    if not location:
        return "unnamed location"
    try:
        status, _ = get(target, f"probes/data-locations/{location}/api",
                        opener=opener)
        return "ready" if status in (200, 204) else f"HTTP {status}"
    except RestError as exc:
        return f"HTTP {exc.status}" if exc.status else str(exc)[:60]
    except OSError as exc:
        return f"unreachable ({exc})"


def load_env_file(path: str | pathlib.Path) -> dict[str, str]:
    """Read a .env-style file without sourcing it.

    Sourcing is what mangles `Snowflake Token="<pat>"` — the shell splits at the space
    unless the whole value is single-quoted. Parsing it here removes that trap, and
    lets one checkout hold several targets (.env, .env-lab) instead of one.
    """
    out: dict[str, str] = {}
    for line in pathlib.Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, val = line.partition("=")
        if not sep:
            continue
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "'\"":
            val = val[1:-1]                       # strip ONE layer of shell quoting
        out[key.strip()] = val
    return out


if __name__ == "__main__":                                  # python -m agent.rest [file]
    import sys
    env = load_env_file(sys.argv[1]) if len(sys.argv) > 1 else None
    ok, lines = doctor(env)
    print("\n".join(lines))
    print("\nOK" if ok else "\nNOT USABLE — fix the above, then re-run")
    sys.exit(0 if ok else 1)


# ----------------------------------------------------------------- write paths
# EVERY function below MUTATES the target. None of them checks anything: the gate is
# agent/safety.py, and keeping the gate separate from the verb is deliberate — a
# transport function that sometimes refuses is a transport function nobody trusts.
#
# Endpoint contract read from the LIVE OpenAPI spec on 2026-08-03:
#     GET /semarchy/api/rest/api-docs?domain=app_builder&format=JSON
# which is reachable with the same API-key as everything else. Reading the spec
# settled a distinction the design had wrong — see import_replace.

def put(target: Target, path: str, body: bytes | None = None, *,
        content_type: str | None = None, opener=None) -> tuple[int, bytes]:
    """PUT. The app-builder uses it for the settings that hang off a data location —
    continuous loads, notification policies, purge schedules — none of which POST."""
    url = f"{target.url}/{path.lstrip('/')}"
    headers = dict(target.headers())
    if content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(url, data=body or b"", headers=headers, method="PUT")
    send = opener or urllib.request.urlopen
    try:
        with send(req, timeout=TIMEOUT) as resp:
            out = resp.read()
        _reject_login_page(url, out)
        return resp.status, out
    except urllib.error.HTTPError as exc:
        detail = exc.read()[:400].decode("utf8", "replace")
        _reject_login_page(url, detail.encode())
        if exc.code == 401:
            raise TokenExpired(f"401 from {url}. Credentials rejected.") from None
        raise RestError(f"HTTP {exc.code} from PUT {url}: {detail}") from None


def post(target: Target, path: str, body: bytes | None = None, *,
         content_type: str | None = None, opener=None) -> tuple[int, bytes]:
    url = f"{target.url}/{path.lstrip('/')}"
    headers = dict(target.headers())
    if content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(url, data=body or b"", headers=headers, method="POST")
    send = opener or urllib.request.urlopen
    try:
        with send(req, timeout=TIMEOUT) as resp:
            out = resp.read()
        _reject_login_page(url, out)
        return resp.status, out
    except urllib.error.HTTPError as exc:
        detail = exc.read()[:400].decode("utf8", "replace")
        _reject_login_page(url, detail.encode())
        if exc.code == 401:
            raise TokenExpired(f"401 from {url}. Credentials rejected.") from None
        raise RestError(f"HTTP {exc.code} from POST {url}: {detail}",
                        status=exc.code) from None


def create_model(target: Target, name: str, label: str | None = None,
                 description: str | None = None, *, branch: str | None = None,
                 opener=None) -> tuple[int, bytes]:
    """Create a blank model plus edition 0.0. 201 on success, 409 if it exists.

    ALL FOUR FIELDS ARE REQUIRED, and so are all three on the nested branch. A first
    attempt sent only name+label and got a 400 naming exactly what was absent:
    "Missing required properties: description branch". The schema is
    `components/schemas/ModelCreate` in the live OpenAPI — worth reading rather than
    inferring from the UI, where description is optional.

    The branch defaults to `<Model>_Root`, which is the convention every sample uses
    and what agent/compile/envelope.py emits, so a created model and an imported one
    agree on the branch name.
    """
    payload = json.dumps({
        "name": name,
        "label": label or name,
        "description": description or f"{label or name} — created by the xDM agent",
        "branch": {
            "name": branch or f"{name}_Root",
            "label": f"{label or name} Root branch",
            "description": f"The root branch for {label or name}",
        },
    }).encode()
    return post(target, "app-builder/models", payload,
                content_type="application/json", opener=opener)


def import_replace(target: Target, model: str, edition: str, xml: bytes,
                   *, opener=None) -> tuple[int, bytes]:
    """Replace a model edition's ENTIRE content. 204 on success.

    DESTRUCTIVE. This is D7's Import-Replace, and it deletes what was there.

    NOTE THE PATH: it is the export path with POST instead of GET. Reading the spec
    corrected an assumption this project carried for several sprints — that
    `POST /app-builder/model-imports` was the way in. It is not. That endpoint
    "is intended to import to a DEPLOYMENT repository a CLOSED model edition", i.e.
    it is D9's promotion path, and it returns 303 rather than 204.

    For a DESIGN repository the spec is explicit: "use the Create model operation to
    create a blank model and then use the Import-Replace model edition operation to
    replace this blank model by the content of the model export file."
    """
    # application/octet-stream, NOT application/xml. The requestBody is
    # `components/requestBodies/ModelEdition`, a binary string — the export is
    # uploaded as a FILE, not as a typed XML document. Sending application/xml gets a
    # bare "HTTP 415 Unsupported Media Type" with nothing naming the expected type,
    # so this is only findable by resolving the $ref in the spec.
    return post(target, f"app-builder/models/{model}/editions/{edition}/content",
                xml, content_type="application/octet-stream", opener=opener)


def create_data_location(target: Target, name: str, datasource: str, model: str,
                         edition: str, *, label: str | None = None,
                         description: str | None = None, type_: str = "DEV",
                         opener=None) -> tuple[int, bytes]:
    """Create a data location AND deploy a model edition into it. 201 on success.

    This is the non-destructive way to stand a model up: `deploy` re-points an
    EXISTING location, which replaces whatever it was serving. Creating one against a
    free datasource touches nothing. D9 still applies — only DEV.

    `datasource` must already exist (`GET admin/datasources`); this does not provision
    a schema.

    **A 500 here does not mean nothing happened.** OBSERVED 2026-08-04: this call
    returned `500 Unexpected Error` and the data location HAD been created and was
    already in DEPLOYING_ME_AND_JOBS. The create is synchronous, the deploy it triggers
    is not, and the error covers only the latter. NEVER retry this call on a 5xx —
    re-read `GET app-builder/data-locations` first, or you will either duplicate the
    location or mask a deploy that is merely slow.

    That paragraph was advice the caller could not take. `post` RAISES on any HTTPError,
    so a 5xx never reached the documented `tuple[int, bytes]` return and every caller
    got an exception instead — which at this point is indistinguishable from "the
    request never happened", the exact confusion the paragraph warns about. OBSERVED
    2026-08-05: a deploy run died on the traceback rather than recording the step and
    re-reading.

    So the 5xx is CAUGHT and RETURNED here, and only here. `post` keeps raising for
    every other caller, because for them a 5xx really is a failure; this endpoint is
    the one where the status code and the outcome are known to disagree.

    And the code cannot tell you WHICH disagreement it is. OBSERVED 2026-08-05: a
    datasource that already holds data location tables is refused with `500` and
    `"This datasource already contains data location tables"` — nothing created —
    while the 2026-08-04 case was `500 Unexpected Error` with the location created and
    deploying. Same class, opposite outcomes. There is therefore no status code, and no
    message match, that substitutes for re-reading `GET app-builder/data-locations`.
    Returning the pair is what makes that re-read possible; it is not what makes it
    unnecessary.
    """
    if type_ != "DEV":
        raise ValueError(
            f"D9 restricts deployment to DEV locations; refusing type_={type_!r}. "
            "Deploy to production from the product's own UI, not from this agent.")
    payload = json.dumps({
        "name": name, "type": type_, "label": label or name,
        "description": description or "", "dataSource": datasource,
        "modelName": model, "modelEditionKey": edition}).encode()
    try:
        return post(target, "app-builder/data-locations", payload,
                    content_type="application/json", opener=opener)
    except RestError as exc:
        if exc.status is not None and 500 <= exc.status < 600:
            return exc.status, str(exc).encode()
        raise


def deploy(target: Target, location: str, model: str, edition: str,
           *, opener=None) -> tuple[int, bytes]:
    """Deploy a model edition to a data location. 204 on success.

    Scriptable after all — sprint 08 assumed deploy was browser-only. If the location
    is in INSTALL_JOB_FAILED the request restarts the installation job.
    """
    payload = json.dumps({"modelName": model, "modelEditionKey": edition}).encode()
    return post(target, f"app-builder/data-locations/{location}/deploy", payload,
                content_type="application/json", opener=opener)


def set_status(target: Target, location: str, status: str,
               *, opener=None) -> tuple[int, bytes]:
    """Set a data location's status, e.g. back to ready after a failed job. 204."""
    payload = json.dumps({"status": status}).encode()
    return post(target, f"app-builder/data-locations/{location}/set-status", payload,
                content_type="application/json", opener=opener)


def delete_data_location(target: Target, location: str, *, drop_schema: bool = False,
                         opener=None) -> tuple[int, bytes]:
    """DESTRUCTIVE. Delete a data location. 204 on success.

    `POST .../delete` — the data-location idiom, NOT `DELETE` on the resource, which is
    the model idiom. The two are adjacent in the spec and easy to conflate.

    `drop_schema=True` sends `{"dropSchema": "DROP"}` and, in the API's own words,
    "deletes all the data stored in this schema". THAT IS THE WHOLE SCHEMA, not merely
    this location's tables, and the operation cannot be undone.

    It is nevertheless the only way to make a datasource reusable: a schema that still
    holds data location tables is refused by `create_data_location` with "This
    datasource already contains data location tables" (OBSERVED 2026-08-05 on the
    B2C demo schema). So dropping is not an optimisation, it is the precondition — and
    the caller has to be sure the schema holds nothing but what it is willing to lose.

    Defaults to False. A destructive default is a destructive default even when every
    current caller passes True.
    """
    payload = json.dumps({"dropSchema": "DROP"} if drop_schema else {}).encode()
    return post(target, f"app-builder/data-locations/{location}/delete", payload,
                content_type="application/json", opener=opener)


def delete_model(target: Target, model: str, *, opener=None) -> tuple[int, bytes]:
    """DESTRUCTIVE. Delete a model and every edition of it. 204 on success.

    DELETE on the model resource — NOT `POST .../delete`, which is the data-location
    idiom. The two are adjacent in the spec and easy to conflate.
    """
    url = f"{target.url}/app-builder/models/{model}"
    req = urllib.request.Request(url, headers=target.headers(), method="DELETE")
    send = opener or urllib.request.urlopen
    try:
        with send(req, timeout=TIMEOUT) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        raise RestError(f"HTTP {exc.code} from DELETE {url}: "
                        f"{exc.read()[:200].decode('utf8','replace')}") from None


def close_edition(target: Target, model: str, edition: str,
                  *, opener=None) -> tuple[int, bytes]:
    """Close a model edition — the prerequisite for promoting it (D9)."""
    return post(target, f"app-builder/models/{model}/editions/{edition}/close",
                opener=opener)


def openapi(target: Target, domain: str = "app_builder", *, opener=None) -> dict:
    """The live endpoint contract. Reading this beats guessing paths, which is how
    `model-imports` was nearly used for the wrong purpose."""
    return get_json(target, f"api-docs?domain={domain}&format=JSON", opener=opener)
