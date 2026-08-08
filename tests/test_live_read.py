"""Sprint 08 acceptance: everything that reads the live instance, tested offline.

The REST half is exercised through an injected opener, because the part worth testing
is the HEADER CONTRACT — two headers for two different systems — and that is built
locally. The validation-report half is exercised against synthetic CSVs whose SHAPE is
unknown, which is exactly why the parser is header-driven and refuses what it does not
recognise.

No test here touches a live instance. The live acceptance criteria are the operator's
to run, with the operator present (D12).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent.browser.inspect import (  # noqa: E402
    DataLocation, read_data_locations, read_version, technology_mismatch)
from agent.compile.extract import extract  # noqa: E402
from agent.compile.extract_app import extract_app  # noqa: E402
from agent.compile.extract_certify import extract_certify  # noqa: E402
from agent.ir.schema import IR  # noqa: E402
from agent.rest import NotConfigured, RestError, Target, TokenExpired, get  # noqa: E402
from agent.tools import validation_report as vr  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "samples" / "gs-productretail-2025.1.0.xml"


def witness(path: Path = None) -> Path:
    """A real product export, or a skip naming the file that is not here.

    Two things in this module need one: `read_version`, which reads the stamps off an
    export, and the validation-report index, which needs an IR rich enough to have
    entities, a matcher and an application in it. `samples/` is not in the public
    export, so those skip there; everything that drives the REST client through a fake
    opener keeps running, which is most of the file.
    """
    path = SAMPLE if path is None else path
    if not path.exists():
        pytest.skip(f"{path.relative_to(ROOT)} not present")
    return path

ENV = {"SEMARCHY_URL": "https://example.snowflakecomputing.app/semarchy/api/rest/",
       "SEMARCHY_AUTHORIZATION": 'Snowflake Token="pat123"',
       "SEMARCHY_API_KEY": "k"}


class _Resp:
    def __init__(self, status=200, body=b"{}"):
        self.status, self._body = status, body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _capture(sink, body=b"{}", status=200):
    def opener(req, timeout=None):
        sink.append(req)
        return _Resp(status, body)
    return opener


# ------------------------------------------------------------ the header contract
def test_both_headers_are_sent_and_the_scheme_is_snowflake_not_bearer():
    """Two headers, two systems: Snowflake gates SPCS ingress, xDM authorizes behind
    it. SPCS explicitly rejects Bearer."""
    sent = []
    get(Target.from_env(ENV), "app-builder/data-locations", opener=_capture(sent))
    h = {k.lower(): v for k, v in sent[0].headers.items()}
    assert h["Authorization".lower()] == 'Snowflake Token="pat123"'
    assert h["Api-key".lower()] == "k"
    assert h["Content-type".lower()] == "application/json"
    assert not h["Authorization".lower()].lower().startswith("bearer")


def test_the_quoting_mistake_that_looks_like_a_bad_token_is_named():
    """`source .env` without single quotes truncates the value at the space, leaving
    the literal 'Snowflake'. It surfaces as a 401 that reads like a bad PAT."""
    with pytest.raises(NotConfigured, match="truncates it at the space"):
        Target.from_env({**ENV, "SEMARCHY_AUTHORIZATION": "Snowflake"})


def test_bearer_is_accepted_now_that_not_every_target_is_spcs():
    """This test previously asserted Bearer was REFUSED, because SPCS rejects it. That
    generalised one deployment's rule to all of them. A standard xDM instance behind a
    reverse proxy may legitimately want Bearer, and .env-lab's own comments say so.

    SPCS still rejects it — but that is SPCS's answer to give, at the point of the
    request, not something to pre-empt by refusing a valid config for another target."""
    t = Target.from_env({**ENV, "SEMARCHY_AUTHORIZATION": "Bearer tok"})
    assert not t.is_spcs
    assert t.headers()["Authorization"] == "Bearer tok"


def test_missing_configuration_names_what_is_missing():
    with pytest.raises(NotConfigured, match="SEMARCHY_API_KEY"):
        Target.from_env({**ENV, "SEMARCHY_API_KEY": ""})


def test_a_401_is_reported_as_an_expired_token_not_a_bug():
    """PAT expiry is controlled by the Snowflake account, so a long refine loop can
    outlive its token. That is 'ask the human', not a defect to debug."""
    import urllib.error

    def opener(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 401, "no", {}, None)
    with pytest.raises(TokenExpired, match="expired"):
        get(Target.from_env(ENV), "x", opener=opener)


def test_a_login_page_served_with_http_200_is_treated_as_expired_auth():
    """VERIFIED LIVE 2026-08-03: this SPCS deployment answers a stale credential with
    HTTP 200 and 24 kB of LoginUi HTML, not a 401. Keying TokenExpired off the status
    code alone means the handler never fires."""
    body = b'<!doctype html><html><head><link href="/assets/ui/LoginUi/favicon.png"/>'
    with pytest.raises(TokenExpired, match="LOGIN PAGE with HTTP 200"):
        get(Target.from_env(ENV), "x", opener=_capture([], body))


def test_other_non_json_bodies_still_report_as_non_json():
    from agent.rest import get_json
    with pytest.raises(RestError, match="not JSON"):
        get_json(Target.from_env(ENV), "x", opener=_capture([], b"plain text"))


# ---------------------------------------------------------------- version stamps
def test_version_comes_from_an_export_not_a_page():
    v = read_version(witness().read_bytes())
    assert v.platform_version.startswith("2025.1.0")
    assert v.repository_version == "2025.1.2"


def test_a_document_that_is_not_an_export_is_refused():
    with pytest.raises(RestError, match="not a metaDataExport"):
        read_version(b"<something/>")


# -------------------------------------------------------------- data locations
def test_data_locations_are_discovered_never_hardcoded():
    body = (b'[{"name":"CorpusA_Org_Hub_Dev","type":"DEV","dbType":"SNOWFLAKE",'
            b'"dbName":"HUB_SCHEMA_DEV","dbSchema":"MDM","status":"DL_READY"}]')
    locs = read_data_locations(Target.from_env(ENV), opener=_capture([], body))
    assert [(x.name, x.is_dev) for x in locs] == [("CorpusA_Org_Hub_Dev", True)]


def test_a_technology_mismatch_is_detected_before_deploy():
    pg = DataLocation(name="dl", type="DEV", db_type="POSTGRESQL")
    assert technology_mismatch("snowflake", pg)
    assert "would fail" in technology_mismatch("snowflake", pg)
    sf = DataLocation(name="dl", type="DEV", db_type="SNOWFLAKE")
    assert technology_mismatch("snowflake", sf) is None


def test_an_unknown_model_technology_refuses_to_judge_compatibility():
    sf = DataLocation(name="dl", type="DEV", db_type="SNOWFLAKE")
    assert "refusing to guess" in technology_mismatch("oracle", sf)


# ------------------------------------------------------- the validation report
HEADER = "Severity,Object,Message\n"


def test_a_report_parses_into_structured_issues():
    issues = vr.parse_text(
        HEADER +
        "Error,Product / Matcher,No match rule defined\n"
        "Warning,Product / Name,Attribute is not searchable\n"
        "Information,ProductRetailMDM,Model has no documentation\n")
    assert vr.counts(issues) == {"error": 1, "warning": 1, "information": 1}
    assert issues[0].blocks_deploy and not issues[1].blocks_deploy


def test_an_unrecognised_header_is_refused_rather_than_parsed_positionally():
    """The CSV schema is undocumented and no sample export exists. Guessing columns by
    position yields a report that parses cleanly and means something else."""
    with pytest.raises(vr.ReportFormatError, match="does not name"):
        vr.parse_text("Col1,Col2,Col3\nError,x,y\n")


def test_the_refusal_says_how_to_fix_it():
    with pytest.raises(vr.ReportFormatError) as e:
        vr.parse_text("a,b,c\n")
    assert "ALIASES" in str(e.value)


def test_semicolon_delimited_exports_parse():
    """Excel writes ';' on European locales, and xDM is a European-facing product."""
    issues = vr.parse_text("Severity;Object;Message\nError;Product;broken\n")
    assert len(issues) == 1 and issues[0].object_path == "Product"


def test_a_byte_order_mark_does_not_break_the_header():
    issues = vr.parse_text("﻿" + HEADER + "Error,Product,broken\n")
    assert len(issues) == 1


def test_an_unknown_severity_is_refused():
    with pytest.raises(vr.ReportFormatError, match="unknown severity"):
        vr.parse_text(HEADER + "Catastrophe,Product,broken\n")


def test_a_report_file_on_disk_parses(tmp_path):
    """The file path is how this is actually called — the browser downloads a CSV."""
    f = tmp_path / "report.csv"
    f.write_text("\ufeff" + HEADER + "Error,Product,broken\n", encoding="utf-8")
    assert len(vr.parse(f)) == 1


def test_an_empty_report_is_clean_not_an_error():
    assert vr.parse_text("") == []
    assert vr.render([]) == "validation clean: 0 issues"


# --------------------------------------------------- mapping issues to IR nodes
def _ir():
    src = witness()
    return IR(model_ir=extract(src)[0], certify=extract_certify(src),
              app=extract_app(src))


def test_issues_resolve_to_specific_ir_nodes():
    issues = vr.resolve(vr.parse_text(
        HEADER +
        "Error,Product / Name,x\n"
        "Warning,Product / EditItems,y\n"
        "Information,ProductRetailMDM,z\n"), _ir())
    assert issues[0].ir_node.startswith("model.yaml:entities[")
    assert ".attributes[" in issues[0].ir_node
    assert issues[1].ir_node.startswith("app.yaml:")
    assert issues[2].ir_node == "app.yaml:applications[0]"
    assert vr.coverage(issues) == 1.0


def test_separator_style_does_not_change_the_mapping():
    """xDM's path separator varies by version and view."""
    ir = _ir()
    paths = ["Product / Name", "Product > Name", "Product :: Name", "Product | Name"]
    resolved = {vr.resolve(
        vr.parse_text(HEADER + f"Error,{p},x\n"), ir)[0].ir_node for p in paths}
    assert len(resolved) == 1 and None not in resolved


def test_an_unmappable_issue_is_reported_as_unmapped_never_mis_mapped():
    """Sending the operator to the wrong YAML line is worse than saying 'unmapped'."""
    issues = vr.resolve(
        vr.parse_text(HEADER + "Error,SomethingThatIsNotInTheIR,x\n"), _ir())
    assert issues[0].ir_node is None
    assert "UNMAPPED" in vr.render(issues)
    assert vr.coverage(issues) == 0.0


def test_the_motivating_example_resolves_to_a_specific_match_rule():
    """The sprint file's own example: "Customer / Matcher / P_PHONETIC_ZIP" must land
    on one match rule, not on the matcher and not on nothing. CORPUS_A is the sample that
    actually has a matcher."""
    CORPUS_A = witness(ROOT / "samples" / "corpus-a-org-mdm-0.1.xml")
    ir = IR(model_ir=extract(CORPUS_A)[0], certify=extract_certify(CORPUS_A),
            app=extract_app(CORPUS_A))
    idx = vr.build_index(ir)
    assert idx.resolve("Organization / Matcher") == "certify.yaml:matchers[0]"
    assert idx.resolve("Organization / Matcher / P_PHONETIC_ZIP") == \
        "certify.yaml:matchers[0].rules[3]"


def test_an_ambiguous_name_resolves_to_nothing_rather_than_the_first_hit():
    """`Import` names an action on many entities. One of them is not an answer."""
    ir = _ir()
    idx = vr.build_index(ir)
    assert idx.resolve("Import") is None


def test_coverage_on_a_realistic_report_clears_the_ninety_percent_bar():
    """Every object in the sample model, addressed the way xDM addresses it."""
    ir = _ir()
    rows = [f"Error,{e.name} / {e.attributes[0].name},x"
            for e in ir.model_ir.entities if e.attributes]
    rows += [f"Warning,{s.entity} / {s.name},y" for s in ir.app.steppers]
    rows += [f"Warning,{f.entity} / {f.name},y" for f in ir.app.forms]
    rows += [f"Information,{p.name},z" for p in ir.model_ir.publishers]
    issues = vr.resolve(vr.parse_text(HEADER + "\n".join(rows) + "\n"), ir)
    assert len(issues) > 20
    assert vr.coverage(issues) >= 0.90, [
        i.object_path for i in issues if not i.ir_node]


# ----------------------------------------------------------------- doctor
def test_doctor_reports_a_working_target_without_printing_secrets():
    from agent.rest import doctor
    body = (b'[{"name":"Hub_Dev","type":"DEV","dbType":"SNOWFLAKE",'
            b'"status":"DL_READY"}]')
    ok, lines = doctor(ENV, opener=_capture([], body))
    text = "\n".join(lines)
    assert ok and "Hub_Dev" in text
    assert "pat123" not in text and "k" != text        # the secret never appears
    assert "authorization  set, " in text


def test_doctor_names_a_truncated_authorization_rather_than_probing():
    from agent.rest import doctor
    ok, lines = doctor({**ENV, "SEMARCHY_AUTHORIZATION": "Snowflake"})
    assert not ok and "truncates it at the space" in lines[0]


def test_doctor_reports_the_login_page_as_an_auth_failure():
    from agent.rest import doctor
    body = b'<!doctype html><link href="/assets/ui/LoginUi/x.png"/>'
    ok, lines = doctor(ENV, opener=_capture([], body))
    assert not ok and any("LOGIN PAGE" in x for x in lines)


def test_doctor_warns_when_there_is_no_dev_data_location():
    """D9 restricts deployment to dev until the model is refined, so a target with no
    DEV location has nowhere safe to import."""
    from agent.rest import doctor
    body = b'[{"name":"Prod","type":"PROD","dbType":"SNOWFLAKE","status":"DL_READY"}]'
    ok, lines = doctor(ENV, opener=_capture([], body))
    assert ok and any("no DEV data location" in x for x in lines)


def test_a_bare_pat_is_refused_before_any_request_is_made():
    """The live .env carried a bare JWT. SPCS reads the SCHEME, so without it the
    request is unauthenticated and returns a login page with HTTP 200 — a failure that
    reads as an expired token. Caught at construction instead."""
    bare = ("eyJraWQiOiIxIiwiYWxnIjoiRVMyNTYifQ.eyJwIjoiMSJ9.sig")
    with pytest.raises(NotConfigured, match="no recognised scheme"):
        Target.from_env({**ENV, "SEMARCHY_AUTHORIZATION": bare})


def test_the_refusal_shows_the_exact_line_to_write():
    with pytest.raises(NotConfigured) as e:
        Target.from_env({**ENV, "SEMARCHY_AUTHORIZATION": "abc"})
    assert 'Snowflake Token="<pat>"' in str(e.value)
    assert "Leave this BLANK" in str(e.value)      # the non-SPCS way out


def test_doctor_never_prints_any_slice_of_the_token():
    """Regression: doctor reported `authorization.split(" ")[0]` as "the scheme". On a
    bare token there is no space, so it printed the entire PAT to the terminal."""
    from agent.rest import doctor
    secret = "SUPERSECRETTOKENVALUE"
    _, lines = doctor({**ENV, "SEMARCHY_AUTHORIZATION": f'Snowflake Token="{secret}"'},
                      opener=_capture([], b"[]"))
    assert secret not in "\n".join(lines)


# ------------------------------------------------- auth is deployment-specific
def test_authorization_is_optional_because_not_every_target_is_spcs():
    """VERIFIED LIVE 2026-08-03. The lab (<lab-host>) is a standard
    xDM deployment: no Snowflake ingress gate, so no Authorization header at all — just
    the xDM API-key. Requiring it refused a valid configuration."""
    t = Target.from_env({"SEMARCHY_URL": "http://lab/semarchy/api/rest",
                         "SEMARCHY_API_KEY": "k"})
    assert not t.is_spcs
    assert "Authorization" not in t.headers()
    assert t.headers()["API-key"] == "k"


def test_spcs_sends_both_headers():
    t = Target.from_env(ENV)
    assert t.is_spcs and set(t.headers()) == {
        "Authorization", "API-key", "Content-Type", "Accept"}


def test_basic_auth_is_accepted_for_a_non_spcs_target():
    """.env-lab's own comments contemplate Basic or Bearer. Only a value with NO scheme
    is refused."""
    t = Target.from_env({**ENV, "SEMARCHY_AUTHORIZATION": "Basic dXNlcjpwYXNz"})
    assert not t.is_spcs and t.headers()["Authorization"].startswith("Basic ")


def test_load_env_file_strips_shell_quoting_without_sourcing():
    """Sourcing is what mangles Snowflake Token="<pat>" — the shell splits at the space
    unless the whole value is single-quoted. Parsing removes the trap."""
    from agent.rest import load_env_file
    import tempfile, pathlib as _p
    f = _p.Path(tempfile.mkdtemp()) / ".env"
    f.write_text('# c\nSEMARCHY_URL=http://x\n'
                 'SEMARCHY_AUTHORIZATION=\'Snowflake Token="abc"\'\n'
                 'SEMARCHY_API_KEY=k\n')
    env = load_env_file(f)
    assert env["SEMARCHY_AUTHORIZATION"] == 'Snowflake Token="abc"'
    assert Target.from_env(env).is_spcs


# -------------------------------------------------- what is deployed where
LOCS = (b'[{"id":"1","name":"CustomerTrainingApp","type":"DEV","label":"CTA",'
        b'"dataSource":"DATA_LOCATION_1","dbType":"POSTGRESQL","dbName":"postgres",'
        b'"dbSchema":"semarchy_dloc1","modelName":"CustomerTraining",'
        b'"modelEditionKey":"0.0","deploymentDate":"2026-07-20T12:16:23.044Z",'
        b'"status":"DL_READY"},'
        b'{"id":"2","name":"LocationProbe","type":"DEV","label":"LP",'
        b'"dataSource":"SEMARCHY_STG","dbType":"POSTGRESQL","dbName":"postgres",'
        b'"dbSchema":"semarchy_stg","modelName":"PartyRoleModels",'
        b'"modelEditionKey":"0.0","deploymentDate":"2026-08-04T02:27:04.132Z",'
        b'"status":"DL_READY"}]')


def test_a_location_reports_what_is_deployed_to_it():
    """An earlier version of DataLocation dropped these fields, so a preflight could
    not tell whether it was about to replace the edition it thought it was. The keys
    were also GUESSED once as `dataSourceName` and `model`, which returned None and
    read as "the API does not return this" when it plainly does."""
    locs = read_data_locations(Target.from_env(ENV), opener=_capture([], LOCS))
    lp = next(d for d in locs if d.name == "LocationProbe")
    assert lp.describes("PartyRoleModels", "0.0")
    assert lp.data_source == "SEMARCHY_STG" and lp.db_schema == "semarchy_stg"
    assert lp.is_dev and lp.is_ready and lp.deployed


def test_deploying_over_a_different_model_is_excluded_not_warned():
    from agent.browser.inspect import deployment_targets
    locs = read_data_locations(Target.from_env(ENV), opener=_capture([], LOCS))
    ok, why = deployment_targets(locs, "PartyRoleModels", "postgresql")
    assert [d.name for d in ok] == ["LocationProbe"]
    assert any("already serves CustomerTraining" in w for w in why)


def test_a_snowflake_model_has_no_target_on_a_postgres_instance():
    """D13 targets Snowflake; the lab is POSTGRESQL. The mismatch is caught before a
    deploy is attempted, not after it fails."""
    from agent.browser.inspect import deployment_targets
    locs = read_data_locations(Target.from_env(ENV), opener=_capture([], LOCS))
    ok, why = deployment_targets(locs, "PartyRoleModels", "snowflake")
    assert ok == [] and len(why) == 2


def test_a_non_dev_location_is_excluded_by_d9():
    from agent.browser.inspect import DataLocation, deployment_targets
    prod = DataLocation(name="Prod", type="PROD", db_type="POSTGRESQL",
                        status="DL_READY")
    ok, why = deployment_targets([prod], "M", "postgresql")
    assert ok == [] and "D9 restricts deployment to DEV" in why[0]


# ------------------------------------------------------------------ write paths
def _capture_post(sink, status=204, body=b""):
    def opener(req, timeout=None):
        sink.append(req)
        return _Resp(status, body)
    return opener


def test_import_replace_posts_to_the_export_path_not_model_imports():
    """The correction the live OpenAPI spec forced. This project assumed
    POST /app-builder/model-imports was the way in; the spec says that endpoint "is
    intended to import to a DEPLOYMENT repository a CLOSED model edition" — D9's
    promotion path. For a DESIGN repository it is Import-Replace, which is the EXPORT
    path with POST instead of GET."""
    from agent.rest import import_replace
    sent = []
    import_replace(Target.from_env(ENV), "M", "0.0", b"<metaDataExport/>",
                   opener=_capture_post(sent))
    assert sent[0].full_url.endswith("/app-builder/models/M/editions/0.0/content")
    assert sent[0].get_method() == "POST"
    assert sent[0].data == b"<metaDataExport/>"
    h = {k.lower(): v for k, v in sent[0].headers.items()}
    # application/octet-stream, NOT application/xml. The requestBody is a binary
    # string — the export is uploaded as a FILE. application/xml gets a bare HTTP 415
    # naming no expected type.
    assert h["content-type"] == "application/octet-stream"
    assert h["api-key"] == "k"


def test_the_export_and_import_paths_are_the_same_url():
    """Same resource, different verb. Worth pinning, because reading it as two
    different endpoints is what caused the original mistake."""
    from agent.rest import import_replace, model_content
    a, b = [], []
    model_content(Target.from_env(ENV), "M", "0.0", opener=_capture_post(a, 200, b"<x/>"))
    import_replace(Target.from_env(ENV), "M", "0.0", b"<x/>", opener=_capture_post(b))
    assert a[0].full_url == b[0].full_url
    assert a[0].get_method() == "GET" and b[0].get_method() == "POST"


def test_deploy_is_scriptable_and_carries_the_model_and_edition():
    """Sprint 08 assumed deploy was browser-only. The spec says otherwise."""
    import json as _json
    from agent.rest import deploy
    sent = []
    deploy(Target.from_env(ENV), "LocationProbe", "M", "0.0",
           opener=_capture_post(sent))
    assert sent[0].full_url.endswith("/app-builder/data-locations/LocationProbe/deploy")
    assert _json.loads(sent[0].data) == {"modelName": "M", "modelEditionKey": "0.0"}


def test_set_status_is_scriptable():
    """The Ready/Maintenance toggle done by hand after the failed job."""
    import json as _json
    from agent.rest import set_status
    sent = []
    set_status(Target.from_env(ENV), "L", "DL_READY", opener=_capture_post(sent))
    assert _json.loads(sent[0].data) == {"status": "DL_READY"}


def test_a_write_that_fails_reports_the_body_not_just_the_code():
    """An import rejected for a grammar error puts the reason in the body. Losing it
    would make the refine loop guess."""
    import urllib.error
    from agent.rest import RestError, import_replace

    def opener(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 400, "Bad Request", {},
                                     __import__("io").BytesIO(b"unknown element Foo"))
    with pytest.raises(RestError, match="unknown element Foo"):
        import_replace(Target.from_env(ENV), "M", "0.0", b"<x/>", opener=opener)


def test_a_login_page_on_a_write_is_still_expired_auth():
    from agent.rest import import_replace
    body = b'<!doctype html><link href="/assets/ui/LoginUi/x.png"/>'
    with pytest.raises(TokenExpired):
        import_replace(Target.from_env(ENV), "M", "0.0", b"<x/>",
                       opener=_capture_post([], 200, body))


# ---------------------------------------------- the 5xx that may mean it worked (§17)
def _raiser(code, body=b'{"error":{"errorMessage":"Unexpected Error"}}'):
    import io
    import urllib.error

    def opener(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, code, "err", {}, io.BytesIO(body))
    return opener


def test_a_rest_error_carries_its_status_code():
    """Recovered by re-parsing the message before this existed, which is how a branch
    on the code stops matching the day the message is reworded."""
    from agent.rest import post
    try:
        post(Target.from_env(ENV), "x", opener=_raiser(503))
    except RestError as e:
        assert e.status == 503
    else:
        raise AssertionError("expected RestError")


def test_create_data_location_RETURNS_a_5xx_instead_of_raising():
    """LESSONS §17, made actionable rather than merely documented.

    The docstring told callers never to retry a 5xx and to re-read instead — advice
    they could not take, because `post` raised and a 5xx never reached the documented
    return. An exception at that point is indistinguishable from "the request never
    happened", which is the exact confusion §17 is about. OBSERVED 2026-08-05: a deploy
    run died on the traceback instead of recording the step and re-reading.
    """
    from agent.rest import create_data_location
    code, body = create_data_location(
        Target.from_env(ENV), "L", "DS", "M", "0.0", opener=_raiser(500))
    assert code == 500
    assert b"Unexpected Error" in body


def test_every_other_caller_still_raises_on_a_5xx():
    """The catch is per-endpoint, not global. For everyone else a 5xx really is a
    failure, and swallowing it would turn a loud stop into a silent wrong answer."""
    from agent.rest import deploy, import_replace
    for call in (lambda t: deploy(t, "L", "M", "0.0", opener=_raiser(500)),
                 lambda t: import_replace(t, "M", "0.0", b"<x/>", opener=_raiser(500))):
        with pytest.raises(RestError):
            call(Target.from_env(ENV))


def test_a_4xx_still_raises_from_create_data_location():
    """Only the 5xx band is ambiguous. A 404 datasource is a refusal, full stop."""
    from agent.rest import create_data_location
    with pytest.raises(RestError):
        create_data_location(Target.from_env(ENV), "L", "DS", "M", "0.0",
                             opener=_raiser(404))


# ---------------------------------------- the first REAL export (2026-08-08, §57)
REAL_REPORT = ROOT / "out/s4-multi-source-ids/06-validation-report-first-run.csv"


def test_the_first_real_export_parses_and_fully_resolves():
    """Sprint 08's missing witness. The builder's actual header is
    `Severity, Type, Object, Description` — which refuted the guessed alias
    `type -> severity` (the parser refused the file rather than misreading it, as
    designed). 67 errors + 10 warnings, and every row resolves to a YAML line, which
    is the half of this module that is actually valuable."""
    if not REAL_REPORT.exists():
        pytest.skip("real export not present")
    from agent.ir.schema import IR
    issues = vr.parse(REAL_REPORT)
    assert vr.counts(issues) == {"error": 67, "warning": 10, "information": 0}
    d = ROOT / "out/s4-multi-source-ids/ir"
    resolved = vr.resolve(issues, IR.load(d / "model.yaml", d / "certify.yaml",
                                          d / "app.yaml"))
    assert vr.coverage(resolved) == 1.0, [
        (i.object_type, i.object_path) for i in resolved if not i.ir_node]
    by = {(i.object_type, i.object_path): i.ir_node for i in resolved}
    # The two headline defects of the run, each on ITS OWN YAML line:
    assert by[("Form Field", "BillingKey")] == "app.yaml:forms[0].fields[2]"
    assert by[("Business Entity", "CustomerNode")] == \
        "app.yaml:business_views[0].nodes[0]"
    assert by[("SemQL Enricher", "NormalizeAddress")].startswith(
        "certify.yaml:enrichers[")


def test_the_object_type_breaks_the_short_name_tie():
    """`BillingKey` names an attribute in model.yaml AND the form field displaying it
    in app.yaml. The report's Object column is the short name, so without the Type
    column the mapping is ambiguous — and ambiguity must resolve to None, never to a
    nearest guess. With the Type it resolves to the FIELD, which is where the 6
    dataType errors actually lived."""
    from agent.ir.schema import IR
    d = ROOT / "out/s4-multi-source-ids/ir"
    if not (d / "app.yaml").exists():
        pytest.skip("no authored app layer")
    idx = vr.build_index(IR.load(d / "model.yaml", d / "certify.yaml",
                                 d / "app.yaml"))
    assert idx.resolve("BillingKey", "Form Field") == "app.yaml:forms[0].fields[2]"
    assert idx.resolve("BillingKey") is None
    # The two-segment path form still resolves the ATTRIBUTE, type-free.
    assert idx.resolve("Customer / BillingKey").startswith(
        "model.yaml:entities[0].attributes[")


# ----------------------------------------------------------------- probes (sprint 12)
def test_doctor_reports_the_runtime_probe_beside_the_repository_status():
    """`status=DL_READY` is the REPOSITORY's opinion; the probe endpoint is the
    RUNTIME's. §24's stale-status lesson is the gap between the two registers, so the
    doctor reports both on one line."""
    from agent.rest import doctor
    body = (b'[{"name":"Hub_Dev","type":"DEV","dbType":"SNOWFLAKE",'
            b'"status":"DL_READY"}]')
    ok, lines = doctor(ENV, opener=_capture([], body))
    row = next(x for x in lines if "Hub_Dev" in x)
    assert ok and "probe=ready" in row


def test_the_probe_is_a_verdict_never_an_exception():
    """The probe decorates the doctor report; a failing probe is a finding. The path
    (probes/data-locations/{name}/api) was read from the probes OpenAPI domain on
    2026-08-08 and measured 204-empty-body on all four lab locations."""
    from agent.rest import Target, probe_data_location
    t = Target.from_env(ENV)
    sent = []
    assert probe_data_location(t, "L", opener=_capture(sent, b"", 204)) == "ready"
    assert sent[0].full_url.endswith("probes/data-locations/L/api")

    def boom(req, timeout=None):
        raise OSError("connection refused")
    assert probe_data_location(t, "L", opener=boom).startswith("unreachable")
