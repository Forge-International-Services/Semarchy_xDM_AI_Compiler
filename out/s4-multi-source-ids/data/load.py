"""Load the scenario-4 dataset into a live data location, and read back what happened.

    python -m out.s4-multi-source-ids.data.load   # not importable, the dir has dashes
    python out/s4-multi-source-ids/data/load.py .env-lab S4AccountLocation dry
    python out/s4-multi-source-ids/data/load.py .env-lab S4AccountLocation load
    python out/s4-multi-source-ids/data/load.py .env-lab S4AccountLocation verify

Three subcommands, in the order that works:

  dry     CREATE_LOAD, PERSIST_DATA with persistMode=NEVER, CANCEL. Nothing is stored.
          This is the cheap register: it answers "are these attribute names real?" and
          "what do the enrichers make of these values?" without spending a batch. A
          400 here is a payload defect; a 400 after submitting is a payload defect you
          now have to clean up.

  load    CREATE_LOAD, one PERSIST_DATA per publisher, SUBMIT, then poll the load until
          it reaches a terminal status. Refuses to run if the entity already holds
          records, because a second load of the same source ids is the UPDATE path and
          this dataset was designed for the INSERT path.

  verify  Reads the predictions in PREDICTIONS.md back off the live instance. Counts
          first, then the records themselves — counts cannot tell a merge from a
          coincidence.

The publisher split is why this is not one CREATE_LOAD_AND_SUBMIT: `defaultPublisherId`
is a property of a persist CALL, and this dataset spans three publishers. Whether a
record may carry its own `PublisherID` is not something the OpenAPI spec says — the
Persistable_Entity_ schema is an open map of strings — so the dry run asks the server
instead of the payload guessing.
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import agent.rest as R  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
RECORDS = HERE / "records.yaml"

# Terminal for our purposes. SUSPENDED is terminal too but it means "an administrator
# has to intervene", which is a report, not a result.
TERMINAL = {"DONE", "WARNING", "ERROR", "CANCELED", "STOPPED", "SUSPENDED"}


def dataset() -> dict:
    return yaml.safe_load(RECORDS.read_text())


def by_publisher(ds: dict) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for rec in ds["customers"]:
        out.setdefault(rec["publisher"], []).append(dict(rec["values"]))
    return out


def opportunities(ds: dict) -> list[dict]:
    return [dict(r["values"]) for r in ds["opportunities"]]


def persist_options(publisher: str | None, *, mode: str, probe: bool) -> dict:
    """`optionsPerEntity` is REQUIRED even when it asks for nothing.

    The three required keys are missingIdBehavior, persistMode and optionsPerEntity;
    omitting the third is a 400 that reads like a schema error rather than a missing
    default.
    """
    per_entity: dict[str, dict] = {}
    if probe:
        # Probe only: run the enrichers and the matcher so the response ECHOES what
        # they made of the raw values, and ask for the built-ins so the echo shows
        # SourceID/PublisherID as the server understood them.
        per_entity = {
            "Customer": {
                "enrichers": "ALL",
                "validations": "JOB_PRE_CONSO",
                "queryPotentialMatchesRules": "ALL",
                "queryPotentialMatchesHighestScoreOnly": False,
                "queryPotentialMatchesBaseExpressions": "ID",
                "responsePayloadRecordsBaseExpressions": "VIEW_ATTRS",
            },
            "Opportunity": {
                "validations": "JOB_PRE_CONSO",
                "responsePayloadRecordsBaseExpressions": "VIEW_ATTRS",
            },
        }
    else:
        per_entity = {"Customer": {}, "Opportunity": {}}
    opts = {
        "missingIdBehavior": "FAIL",
        "persistMode": mode,
        "responsePayload": "SUMMARY_AND_RECORDS" if probe else "SUMMARY",
        "optionsPerEntity": per_entity,
    }
    if publisher:
        opts["defaultPublisherId"] = publisher
    return opts


def _post(t, path: str, payload: dict):
    """`R.post` RAISES on 4xx/5xx and truncates the body at 400 chars.

    That truncation is fine for a management call whose failures are one line, and
    wrong here: a persist rejection names the attribute it did not recognise, and the
    name is usually past character 400. So this re-issues the request the long way when
    it fails, purely to keep the whole message.
    """
    body = json.dumps(payload).encode()
    try:
        status, raw = R.post(t, path, body)
    except R.RestError as exc:
        import urllib.error
        import urllib.request
        req = urllib.request.Request(f"{t.url}/{path.lstrip('/')}", data=body,
                                     headers=t.headers(), method="POST")
        try:
            urllib.request.urlopen(req, timeout=R.TIMEOUT)
        except urllib.error.HTTPError as full:
            detail = full.read().decode("utf8", "replace")
            print(f"  HTTP {full.code} from POST {path}:\n{detail[:4000]}")
            return full.code, {"_error": detail}
        raise exc
    text = raw.decode() if isinstance(raw, (bytes, bytearray)) else str(raw)
    try:
        return status, json.loads(text) if text.strip() else {}
    except json.JSONDecodeError:
        return status, {"_raw": text[:2000]}


def create_load(t, loc: str, description: str) -> int:
    status, body = _post(t, f"loads/{loc}", {
        "action": "CREATE_LOAD",
        "programName": "agent.s4.load",
        "loadDescription": description,
    })
    print(f"CREATE_LOAD -> {status} loadId={body.get('loadId')} "
          f"status={body.get('loadStatus')}")
    return body["loadId"]


def cmd_dry(t, loc: str) -> None:
    ds = dataset()
    load_id = create_load(t, loc, "s4 dry run — persistMode NEVER")
    try:
        for pub, recs in by_publisher(ds).items():
            status, body = _post(t, f"loads/{loc}/{load_id}", {
                "action": "PERSIST_DATA",
                "persistOptions": persist_options(pub, mode="NEVER", probe=True),
                "persistRecords": {"Customer": recs},
            })
            print(f"\n=== {pub}: HTTP {status} status={body.get('status')}")
            _echo(body)
        status, body = _post(t, f"loads/{loc}/{load_id}", {
            "action": "PERSIST_DATA",
            "persistOptions": persist_options(None, mode="NEVER", probe=True),
            "persistRecords": {"Opportunity": opportunities(ds)},
        })
        print(f"\n=== Opportunity: HTTP {status} status={body.get('status')}")
        _echo(body)
    finally:
        s, b = _post(t, f"loads/{loc}/{load_id}", {"action": "CANCEL"})
        print(f"\nCANCEL -> {s} {b.get('loadStatus')}")


def _echo(body: dict) -> None:
    for entity, rows in (body.get("records") or {}).items():
        for row in rows:
            v = row.get("recordValues", {})
            ident = v.get("SourceID") or v.get("OpportunityId")
            print(f"  {entity} {ident}")
            for k in sorted(v):
                print(f"      {k} = {v[k]!r}")
            for fv in row.get("failedValidations") or []:
                print(f"      !! FAILED {fv}")
            for pm in row.get("potentialMatches") or []:
                print(f"      ~~ MATCH {pm.get('matchRuleName')} "
                      f"score={pm.get('matchScore')} "
                      f"loc={pm.get('matchedRecordLocation')} "
                      f"id={pm.get('matchedRecordId')}")
    if body.get("persistSummary"):
        print(f"  summary {body['persistSummary']}")


def cmd_load(t, loc: str) -> None:
    for entity in ("Customer", "Opportunity"):
        for view in ("GD", "MD") if entity == "Customer" else ("GD",):
            n = R.get_json(t, f"count/{loc}/{entity}/{view}")["count"]
            if n:
                sys.exit(f"REFUSING: {entity}/{view} already holds {n} records. This "
                         f"dataset is an INSERT dataset; re-loading the same source "
                         f"ids exercises the update path instead, which is a "
                         f"different experiment.")
    ds = dataset()
    load_id = create_load(t, loc, "s4 dataset — 8 Customer masters, 4 Opportunities")
    for pub, recs in by_publisher(ds).items():
        status, body = _post(t, f"loads/{loc}/{load_id}", {
            "action": "PERSIST_DATA",
            "persistOptions": persist_options(pub, mode="ALWAYS", probe=False),
            "persistRecords": {"Customer": recs},
        })
        print(f"PERSIST {pub:8s} -> {status} {body.get('status')} "
              f"{body.get('persistSummary')}")
        if status >= 300 or body.get("status") != "PERSISTED":
            sys.exit(f"persist did not report PERSISTED: {json.dumps(body)[:2000]}")
    status, body = _post(t, f"loads/{loc}/{load_id}", {
        "action": "PERSIST_DATA",
        "persistOptions": persist_options(None, mode="ALWAYS", probe=False),
        "persistRecords": {"Opportunity": opportunities(ds)},
    })
    print(f"PERSIST Opportunity -> {status} {body.get('status')} "
          f"{body.get('persistSummary')}")
    if status >= 300 or body.get("status") != "PERSISTED":
        sys.exit(f"persist did not report PERSISTED: {json.dumps(body)[:2000]}")

    status, body = _post(t, f"loads/{loc}/{load_id}", {
        "action": "SUBMIT", "jobName": "INTEGRATE_DATA"})
    print(f"SUBMIT -> {status} {json.dumps(body)[:400]}")
    poll(t, loc, load_id)


def poll(t, loc: str, load_id: int, *, timeout_s: int = 600) -> dict:
    """A 204/200 on SUBMIT says the batch was accepted, not that it ran (§52.1)."""
    started, last = time.time(), None
    while time.time() - started < timeout_s:
        load = R.get_json(t, f"loads/{loc}/{load_id}")
        st = load.get("loadStatus")
        task = ((load.get("integrationJob") or {}).get("currentTask") or {}).get("name")
        if (st, task) != last:
            print(f"  [{int(time.time()-started):4d}s] {st:10s} {task or ''}")
            last = (st, task)
        if st in TERMINAL:
            job = load.get("integrationJob") or {}
            if job.get("errorMessage"):
                print(f"  ERROR MESSAGE: {job['errorMessage']}")
            print(f"  terminal={st} duration={job.get('duration')}ms "
                  f"executions={load.get('numberOfJobExecutions')}")
            return load
        time.sleep(5)
    print("  TIMED OUT — this is the stale-status pattern if the queue shows nothing "
          "running. Check the execution engine before retrying anything.")
    return R.get_json(t, f"loads/{loc}/{load_id}")


def q(t, loc: str, entity: str, view: str, exprs: list[str]) -> list[dict]:
    """`$expr` repeats; the reference and built-in attributes are not in USER_ATTRS."""
    qs = "&".join(f"$expr={e}" for e in exprs)
    return R.get_json(t, f"query/{loc}/{entity}/{view}?{qs}&$limit=100").get(
        "records", [])


def cmd_verify(t, loc: str) -> None:
    counts = {
        "Customer/GD": R.get_json(t, f"count/{loc}/Customer/GD")["count"],
        "Customer/MD": R.get_json(t, f"count/{loc}/Customer/MD")["count"],
        "Opportunity/GD": R.get_json(t, f"count/{loc}/Opportunity/GD")["count"],
    }
    expected = {"Customer/GD": 6, "Customer/MD": 8, "Opportunity/GD": 4}
    print("counts (predicted -> observed)")
    for k, v in counts.items():
        flag = "ok " if v == expected[k] else "XX "
        print(f"  {flag}{k:16s} {expected[k]} -> {v}")

    print("\nCustomer GD")
    for r in q(t, loc, "Customer", "GD",
               ["CustomerGoldenId", "Name", "NormalizedName", "ErpKey", "ErpKeyNorm",
                "BillingKey", "BillingKeyNorm", "SfdcKey", "Address.StateCode",
                "Address.StateCodeNorm", "Address.Zip", "Address.Zip5", "FID_Parent"]):
        print("  " + json.dumps(r, sort_keys=True))

    print("\nCustomer MD")
    for r in q(t, loc, "Customer", "MD",
               ["PublisherID", "SourceID", "Gold_CustomerGoldenId", "Name",
                "NormalizedName", "ErpKey", "ErpKeyNorm", "BillingKey",
                "BillingKeyNorm", "Address.Zip", "Address.Zip5",
                "PublisherID_Parent", "SourceID_Parent", "FID_Parent"]):
        print("  " + json.dumps(r, sort_keys=True))

    print("\nOpportunity GD")
    for r in q(t, loc, "Opportunity", "GD",
               ["OpportunityId", "Name", "Amount", "FID_Customer",
                "PublisherID_Customer", "SourceID_Customer"]):
        print("  " + json.dumps(r, sort_keys=True))


def main(argv: list[str]) -> None:
    if len(argv) != 4:
        sys.exit(__doc__)
    env, loc, cmd = argv[1], argv[2], argv[3]
    t = R.Target.from_env(R.load_env_file(env))
    {"dry": cmd_dry, "load": cmd_load, "verify": cmd_verify}[cmd](t, loc)


if __name__ == "__main__":
    main(sys.argv)
