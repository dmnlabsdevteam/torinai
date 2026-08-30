#!/usr/bin/env python3
"""Test 11: is the acquired capability carried by the learned substrate state?

The frozen hypothesis:

    The novel capability is causally carried by unified.learned_rules.
    Removing that learned state removes the capability, and restoring the same
    state restores it, with source code, runtime, evaluation inputs and model
    availability unchanged.

Every condition runs against its own cloned database in its own OS process. The
live substrate is never mutated -- an ablation that damaged production would
answer the question and cost the thing it was asking about. Cloning also gives
the SHAM condition something to control for: if clone-and-restore alone changed
a result, every other condition would be uninterpretable.

Interventions delete rows and respect foreign keys. They never drop a table.
The distinction matters: the claim is that Torin lost an acquired competence,
not that Torin was broken. A condition whose parser, inference engine, model
guard or schema is damaged proves nothing about learning.

    python3 experiments/kite_ablation.py
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
RESULTS = Path(__file__).resolve().parent / "results"
PG_BIN = Path("/opt/homebrew/opt/postgresql@16/bin")
SOURCE_DB = os.getenv("POSTGRES_DATABASE", "torinai_db")
PG_USER = os.getenv("POSTGRES_USER", "stefan")

#: EVERY CLI CALL BELOW MUST CARRY THIS. `createdb`, `pg_dump` and `psql`
#: connect to port 5432 when none is given -- the shared instance holding
#: agentso's tenant databases, whose copy of torinai_db is stale. This script
#: clones and ablates whole databases, so running it against the wrong instance
#: both measures the wrong substrate and writes into somebody else's server.
PG_PORT = os.getenv("POSTGRES_PORT", "5433")
PYTHON = ROOT / "venv_torin" / "bin" / "python3"
DOMAIN = "kite17"

#: Each condition names the intervention applied to its own clone. The SQL is
#: recorded verbatim in the manifest so the intervention is auditable rather
#: than described.
CONDITIONS: Dict[str, Dict] = {
    "FULL": {
        "expect": "solves",
        "sql": [],
    },
    "SHAM": {
        "expect": "identical to FULL",
        "note": "cloned and restored, nothing ablated — controls for cloning itself",
        "sql": [],
    },
    "NO_LEARNED_RULES": {
        "expect": "no derivation",
        "sql": [
            "DELETE FROM unified.learned_rule_evidence WHERE rule_id IN"
            " (SELECT rule_id FROM unified.learned_rules WHERE domain_id = '{domain}')",
            "UPDATE unified.learned_rules SET supersedes_rule_id = NULL"
            " WHERE domain_id = '{domain}'",
            "DELETE FROM unified.learned_rules WHERE domain_id = '{domain}'",
        ],
    },
    "RULE_PRESENT_BUT_NOT_VALIDATED": {
        "expect": "no derivation",
        "note": "the rule and its evidence remain; only the execution gate is closed",
        "sql": [
            "UPDATE unified.learned_rules SET epistemic_status = 'supported',"
            " validated_at = NULL WHERE domain_id = '{domain}'",
        ],
    },
    "NO_CONCEPTS": {
        "expect": "solves",
        "note": "negative control — this competence should not need the semantic store",
        "sql": [
            "DELETE FROM unified.concept_evidence",
            "DELETE FROM unified.concept_aliases",
            "DELETE FROM unified.concept_domains",
            "DELETE FROM unified.concept_identity_relations",
            "DELETE FROM unified.concept_mappings",
            "DELETE FROM unified.concept_relations",
            "DELETE FROM unified.concepts",
        ],
    },
    "BLANK": {
        "expect": "no derivation",
        "note": "no acquired substrate state; the architecture is untouched",
        "sql": [
            "DELETE FROM unified.learned_rule_evidence",
            "UPDATE unified.learned_rules SET supersedes_rule_id = NULL",
            "DELETE FROM unified.learned_rules",
            "DELETE FROM unified.concept_evidence",
            "DELETE FROM unified.concept_aliases",
            "DELETE FROM unified.concept_domains",
            "DELETE FROM unified.concept_identity_relations",
            "DELETE FROM unified.concept_mappings",
            "DELETE FROM unified.concept_relations",
            "DELETE FROM unified.concepts",
            "DELETE FROM unified.domain_mappings",
            "DELETE FROM unified.beliefs",
        ],
    },
    "RESTORED": {
        "expect": "solves",
        "note": "ablated exactly as NO_LEARNED_RULES, then the same rows reinstated",
        "sql": [
            "DELETE FROM unified.learned_rule_evidence WHERE rule_id IN"
            " (SELECT rule_id FROM unified.learned_rules WHERE domain_id = '{domain}')",
            "UPDATE unified.learned_rules SET supersedes_rule_id = NULL"
            " WHERE domain_id = '{domain}'",
            "DELETE FROM unified.learned_rules WHERE domain_id = '{domain}'",
        ],
        "restore": True,
    },
}


def pg(tool: str, *args: str, database: Optional[str] = None, stdin=None):
    command = [str(PG_BIN / tool), "-U", PG_USER, "-p", PG_PORT]
    if database:
        command += ["-d", database]
    command += list(args)
    return subprocess.run(command, capture_output=True, text=True, stdin=stdin)


def clone(source: str, target: str) -> str:
    """Copy the substrate into a fresh database via dump/restore.

    CREATE DATABASE ... TEMPLATE would be faster but requires no other session
    on the source, which cannot be guaranteed while Torin may be running.
    """
    pg("dropdb", "--if-exists", target)
    created = pg("createdb", target)
    if created.returncode:
        raise RuntimeError(f"createdb {target}: {created.stderr.strip()}")

    dump = subprocess.run(
        [str(PG_BIN / "pg_dump"), "-U", PG_USER, "-p", PG_PORT,
         "--no-owner", "--no-acl", source],
        capture_output=True, text=True,
    )
    if dump.returncode:
        raise RuntimeError(f"pg_dump {source}: {dump.stderr.strip()[:400]}")

    restore = subprocess.run(
        [str(PG_BIN / "psql"), "-U", PG_USER, "-p", PG_PORT, "-d", target,
         "-v", "ON_ERROR_STOP=0", "-q"],
        input=dump.stdout, capture_output=True, text=True,
    )
    if restore.returncode:
        raise RuntimeError(f"restore into {target}: {restore.stderr.strip()[:400]}")
    return dump.stdout[:0] or "ok"


def apply_sql(database: str, statements: List[str]) -> List[str]:
    applied = []
    for template in statements:
        statement = template.format(domain=DOMAIN)
        result = pg("psql", "-v", "ON_ERROR_STOP=1", "-q", "-c", statement,
                    database=database)
        if result.returncode:
            raise RuntimeError(f"{statement[:80]}: {result.stderr.strip()[:300]}")
        applied.append(statement)
    return applied


def rule_rows(database: str) -> List[Dict]:
    """The exact learned-rule state, for restoration and for the manifest."""
    result = pg(
        "psql", "-t", "-A", "-c",
        "SELECT json_agg(row_to_json(r)) FROM (SELECT * FROM unified.learned_rules"
        f" WHERE domain_id = '{DOMAIN}' ORDER BY rule_id) r",
        database=database,
    )
    payload = result.stdout.strip()
    return json.loads(payload) if payload and payload != "" else []


def evaluate(condition: str, database: str) -> Dict:
    """Run the frozen suite in a fresh OS process against this clone."""
    environment = dict(os.environ)
    environment.update({
        "POSTGRES_DATABASE": database,
        "POSTGRES_USER": PG_USER,
        "POSTGRES_PORT": PG_PORT,
        "TORIN_MODEL_POLICY": "strict_model_free",
        "TORIN_LEARNING_POLICY": "frozen",
    })
    process = subprocess.run(
        [str(PYTHON), str(ROOT / "experiments" / "kite_evaluate.py"),
         "--condition", condition],
        capture_output=True, text=True, env=environment, cwd=str(ROOT),
    )
    report = None
    for line in process.stdout.splitlines():
        if line.startswith("{"):
            report = json.loads(line)
    if report is None:
        raise RuntimeError(
            f"{condition}: evaluator produced no report\n"
            f"stdout: {process.stdout[-800:]}\nstderr: {process.stderr[-800:]}"
        )
    report["returncode"] = process.returncode
    report["stderr_tail"] = process.stderr[-2000:]
    return report


def run_condition(name: str, spec: Dict, snapshot: List[Dict]) -> Dict:
    database = f"torinai_abl_{name.lower()}"
    print(f"\n=== {name} ({spec['expect']}) ===", flush=True)
    clone(SOURCE_DB, database)
    applied = apply_sql(database, spec["sql"])

    restored = []
    if spec.get("restore"):
        for row in snapshot:
            columns = ", ".join(row)
            placeholders = ", ".join(
                "NULL" if value is None
                else ("'" + json.dumps(value).replace("'", "''") + "'"
                      if isinstance(value, (dict, list))
                      else "'" + str(value).replace("'", "''") + "'")
                for value in row.values()
            )
            statement = (f"INSERT INTO unified.learned_rules ({columns})"
                         f" VALUES ({placeholders})")
            result = pg("psql", "-v", "ON_ERROR_STOP=1", "-q", "-c", statement,
                        database=database)
            if result.returncode:
                raise RuntimeError(f"restore row: {result.stderr.strip()[:300]}")
            restored.append(row["rule_id"])

    report = evaluate(name, database)
    report["intervention"] = {
        "database": database, "sql_applied": applied,
        "rows_restored": restored, "note": spec.get("note", ""),
    }

    identity = report["database"]
    if identity["connected"] != database:
        raise RuntimeError(
            f"{name}: evaluated {identity['connected']!r}, not its own clone "
            f"{database!r} — the condition is not isolated"
        )
    print(f"  db:     connected={identity['connected']} "
          f"(source={identity['configuration_source']})")

    loader = report["loader"]
    print(f"  loader: available={loader['rules_available']} "
          f"executable={loader['rules_executable']} loaded={loader['rule_ids_loaded']}")
    print(f"  cases:  {report['passed']}/{report['total']} passed")
    print(f"  model:  attempts={report['model']['attempts']} "
          f"executed={report['model']['executed']}")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep-clones", action="store_true")
    args = parser.parse_args()

    RESULTS.mkdir(parents=True, exist_ok=True)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                            text=True, cwd=str(ROOT)).stdout.strip() or "not_a_git_repo"

    # This tree is not under version control, so a commit hash cannot identify
    # the code that produced the result. Digest the modules the experiment
    # actually depends on instead -- a weaker identifier, but a real one.
    import hashlib
    sources = {}
    for relative in ("core/learning/rule_induction.py", "core/learning/rule_store.py",
                     "core/learning/learning_policy.py", "core/model_policy.py",
                     "core/database/postgres_config.py",
                     "experiments/kite_evaluate.py", "experiments/kite_ablation.py",
                     "experiments/kite_evaluation_suite.json"):
        path = ROOT / relative
        sources[relative] = hashlib.sha256(path.read_bytes()).hexdigest()[:16]

    snapshot = rule_rows(SOURCE_DB)
    print(f"frozen learned-rule state: {len(snapshot)} row(s)")
    for row in snapshot:
        print(f"  {row['rule_id']}  {row['epistemic_status']}  {row['rendered_formula']}")
    if not snapshot:
        print("nothing has been taught; run experiments/kite_teach.py first",
              file=sys.stderr)
        return 1

    reports = {}
    for name, spec in CONDITIONS.items():
        reports[name] = run_condition(name, spec, snapshot)

    manifest = {
        "experiment": "kite17_ablation",
        "hypothesis": (
            "The novel capability is causally carried by unified.learned_rules. "
            "Removing that learned state removes the capability; restoring the "
            "same state restores it, with source code, runtime, evaluation "
            "inputs and model availability unchanged."
        ),
        "run_at": datetime.now(timezone.utc).isoformat(),
        "commit": commit,
        "source_sha256": sources,
        "source_database": SOURCE_DB,
        "frozen_rule_state": snapshot,
        "conditions": reports,
    }
    path = RESULTS / "kite17_ablation.json"
    path.write_text(json.dumps(manifest, indent=2, default=str))

    print("\n" + "=" * 78)
    print(f"{'condition':<34}{'exec':>5}{'passed':>9}{'derives':>9}{'model':>8}")
    print("-" * 78)
    for name, report in reports.items():
        derives = any(
            not case["no_derivation"] for case in report["cases"]
            if case["id"].startswith(("pos_", "transition_single", "transition_two"))
        )
        print(f"{name:<34}{report['loader']['rules_executable']:>5}"
              f"{report['passed']:>4}/{report['total']:<4}"
              f"{('yes' if derives else 'NO'):>9}"
              f"{report['model']['attempts']:>8}")
    print("=" * 78)
    print(f"manifest -> {path}")

    if not args.keep_clones:
        for name in CONDITIONS:
            pg("dropdb", "--if-exists", f"torinai_abl_{name.lower()}")
        print("clones dropped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
