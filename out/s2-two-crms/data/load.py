"""Load the scenario-2 dataset into a live data location, and read back what happened.

    python out/s2-two-crms/data/load.py .env-lab <S2Location> dry
    python out/s2-two-crms/data/load.py .env-lab <S2Location> load
    python out/s2-two-crms/data/load.py .env-lab <S2Location> verify

The single-entity sibling of s4's loader — same three subcommands, same order (dry ->
load -> verify), trimmed to one entity (Customer) because that is all this scenario has.
See out/s4-multi-source-ids/data/load.py for the fuller version and the reasoning behind
each step; only the differences are re-explained here.

  dry     CREATE_LOAD, PERSIST_DATA persistMode=NEVER, CANCEL. Nothing stored. Answers
          "are these attribute names real?" and "what does survivorship make of the
          two rows on the same CustomerNumber?" without spending a batch.
  load    CREATE_LOAD, one PERSIST_DATA per publisher, SUBMIT INTEGRATE_DATA, poll.
          Refuses if Customer already holds records — this is an INSERT dataset.
  verify  Counts against PREDICTIONS.md (GD 4, MD 6), then the golden values, which is
          where the survivorship proof actually lives: counts cannot tell a merge from
          a coincidence, and cannot tell a correct CreditLimit from a wrong one.

NOT YET RUN. s2 has no data location on the lab and no free datasource, so this has
compiled its payloads offline and nothing more. Deployable is not runnable.
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
TERMINAL = {"DONE", "WARNING", "ERROR", "CANCELED", "STOPPED", "SUSPENDED"}


def dataset() -> dict:
    return yaml.safe_load(RECORDS.read_text())


def by_publisher(ds: dict) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for rec in ds["customers"]:
        out.setdefault(rec["publisher"], []).append(dict(rec["values"]))
    return out


def persist_options(publisher: str | None, *, mode: str, probe: bool) -> dict:
    """optionsPerEntity is required even when empty (a 400 otherwise, §s4 loader)."""
    if probe:
        per_entity = {"Customer": {
            "enrichers": "ALL",
            "validations": "JOB_PRE_CONSO",
            "responsePayloadRecordsBaseExpressions": "VIEW_ATTRS",
        }}
    else:
        per_entity = {"Customer": {}}
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
    """R.post raises on 4xx/5xx and truncates at 400 chars; a persist rejection names
    the attribute past that, so re-issue the long way to keep the whole message."""
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
        "programName": "agent.s2.load",
        "loadDescription": description,
    })
    print(f"CREATE_LOAD -> {status} loadId={body.get('loadId')} "
          f"status={body.get('loadStatus')}")
    return body["loadId"]


def _echo(body: dict) -> None:
    for _entity, rows in (body.get("records") or {}).items():
        for row in rows:
            v = row.get("recordValues", {})
            print(f"  Customer {v.get('CustomerNumber')}")
            for k in sorted(v):
                print(f"      {k} = {v[k]!r}")
            for fv in row.get("failedValidations") or []:
                print(f"      !! FAILED {fv}")
    if body.get("persistSummary"):
        print(f"  summary {body['persistSummary']}")


def cmd_dry(t, loc: str) -> None:
    load_id = create_load(t, loc, "s2 dry run — persistMode NEVER")
    try:
        for pub, recs in by_publisher(dataset()).items():
            status, body = _post(t, f"loads/{loc}/{load_id}", {
                "action": "PERSIST_DATA",
                "persistOptions": persist_options(pub, mode="NEVER", probe=True),
                "persistRecords": {"Customer": recs},
            })
            print(f"\n=== {pub}: HTTP {status} status={body.get('status')}")
            _echo(body)
    finally:
        s, b = _post(t, f"loads/{loc}/{load_id}", {"action": "CANCEL"})
        print(f"\nCANCEL -> {s} {b.get('loadStatus')}")


def cmd_load(t, loc: str) -> None:
    for view in ("GD", "MD"):
        n = R.get_json(t, f"count/{loc}/Customer/{view}")["count"]
        if n:
            sys.exit(f"REFUSING: Customer/{view} already holds {n} records. This is an "
                     f"INSERT dataset; re-loading the same CustomerNumbers exercises "
                     f"the update path, a different experiment.")
    load_id = create_load(t, loc, "s2 dataset — 6 Customer masters over two CRMs")
    for pub, recs in by_publisher(dataset()).items():
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
        "action": "SUBMIT", "jobName": "INTEGRATE_DATA"})
    print(f"SUBMIT -> {status} {json.dumps(body)[:400]}")
    poll(t, loc, load_id)


def poll(t, loc: str, load_id: int, *, timeout_s: int = 600) -> dict:
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
            print(f"  terminal={st} duration={job.get('duration')}ms")
            return load
        time.sleep(5)
    print("  TIMED OUT — stale-status pattern if the queue shows nothing running. "
          "Check the execution engine before retrying.")
    return R.get_json(t, f"loads/{loc}/{load_id}")


def q(t, loc: str, view: str, exprs: list[str]) -> list[dict]:
    qs = "&".join(f"$expr={e}" for e in exprs)
    return R.get_json(t, f"query/{loc}/Customer/{view}?{qs}&$limit=100").get(
        "records", [])


def cmd_verify(t, loc: str) -> None:
    expected = {"Customer/GD": 4, "Customer/MD": 6}
    print("counts (predicted -> observed)")
    for k, exp in expected.items():
        v = R.get_json(t, f"count/{loc}/{k}")["count"]
        print(f"  {'ok ' if v == exp else 'XX '}{k:14s} {exp} -> {v}")
    print("\nCustomer GD (check 1001 CreditLimit=90000 with FullName=Isabelle "
          "Laurent, and that 1004 exists)")
    for r in q(t, loc, "GD",
               ["CustomerNumber", "FullName", "Email", "RegionCode", "CreditLimit",
                "UpdatedAt"]):
        print("  " + json.dumps(r, sort_keys=True))


def main(argv: list[str]) -> None:
    if len(argv) != 4:
        sys.exit(__doc__)
    env, loc, cmd = argv[1], argv[2], argv[3]
    t = R.Target.from_env(R.load_env_file(env))
    {"dry": cmd_dry, "load": cmd_load, "verify": cmd_verify}[cmd](t, loc)


if __name__ == "__main__":
    main(sys.argv)
