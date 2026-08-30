"""Which database a process connects to must be decided by one authority.

The defect these pin: the database class called
`load_dotenv(".env.postgres", override=True)` in its constructor and then read
`os.getenv('POSTGRES_DATABASE')` on the next line. The file rewrote the process
environment, so a subprocess launched with an explicit database connected to
the default one and reported nothing unusual.

It surfaced as an ablation in which every condition -- including those whose
learned rules had been deleted -- loaded identical rules and passed
identically. A silent configuration failure is indistinguishable from "the
intervention had no effect", which is the one conclusion an ablation must never
reach by accident.
"""
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from core.database.postgres_config import (
    DEFAULT_ENV_FILES, DatabaseIdentityError, PostgresConfig,
)

ROOT = Path(__file__).resolve().parent.parent
PG_BIN = Path("/opt/homebrew/opt/postgresql@16/bin")


@pytest.fixture
def env_file(tmp_path):
    path = tmp_path / ".env.postgres"
    path.write_text(
        "POSTGRES_HOST=file_host\n"
        "POSTGRES_DATABASE=torinai_db\n"
        "POSTGRES_USER=file_user\n"
    )
    return path


def test_the_process_environment_beats_the_env_file(env_file):
    """The defect, stated directly."""
    resolved = PostgresConfig.resolve(
        env={"POSTGRES_DATABASE": "sentinel_external"}, env_files=[env_file],
    )
    assert resolved.database == "sentinel_external"
    assert resolved.provenance["database"] == "environment"


def test_the_env_file_fills_values_the_environment_does_not_supply(env_file):
    resolved = PostgresConfig.resolve(env={}, env_files=[env_file])
    assert resolved.database == "torinai_db"
    assert resolved.host == "file_host"
    assert resolved.provenance["database"] == "dotenv:.env.postgres"


def test_an_explicit_argument_beats_both(env_file):
    resolved = PostgresConfig.resolve(
        database="explicit_db", env={"POSTGRES_DATABASE": "env_db"}, env_files=[env_file],
    )
    assert resolved.database == "explicit_db"
    assert resolved.provenance["database"] == "explicit"


def test_a_coded_default_applies_only_when_nothing_else_does():
    resolved = PostgresConfig.resolve(env={}, env_files=[])
    assert resolved.database == "torinai_db"
    assert resolved.provenance["database"] == "default"


def test_resolution_does_not_mutate_the_process_environment(env_file):
    """A database implementation consumes configuration; it must not rewrite
    the process, or every later reader observes something it did not set."""
    sentinel = f"sentinel_{uuid.uuid4().hex[:8]}"
    os.environ["POSTGRES_DATABASE"] = sentinel
    before = dict(os.environ)
    try:
        PostgresConfig.resolve(env_files=[env_file])
        assert os.environ["POSTGRES_DATABASE"] == sentinel
        assert dict(os.environ) == before
    finally:
        del os.environ["POSTGRES_DATABASE"]


def test_the_password_is_never_in_a_representation():
    resolved = PostgresConfig.resolve(
        password="hunter2", env={}, env_files=[],
    )
    assert "hunter2" not in repr(resolved)
    assert "password" not in resolved.describe()


def test_provenance_is_reported_for_every_field(env_file):
    resolved = PostgresConfig.resolve(
        database="explicit_db", env={"POSTGRES_USER": "env_user"}, env_files=[env_file],
    )
    described = resolved.describe()["configuration_source"]
    assert described["database"] == "explicit"
    assert described["user"] == "environment"
    assert described["host"] == "dotenv:.env.postgres"
    assert described["port"] == "default"


def test_the_shipped_env_file_is_the_one_resolution_consults():
    """Guards against the fallback list drifting away from what is deployed."""
    assert any(path.exists() for path in DEFAULT_ENV_FILES), (
        f"none of {[p.name for p in DEFAULT_ENV_FILES]} exists; resolution would "
        f"silently fall through to coded defaults"
    )


# ------------------------------------------------------------------ integration

def test_a_subprocess_connects_to_the_database_it_was_given():
    """The check that would have caught the invalid ablation.

    Asks the server, not the configuration: `SELECT current_database()` in a
    fresh process launched with an explicit POSTGRES_DATABASE.
    """
    if not (PG_BIN / "createdb").exists():
        pytest.skip("postgresql client tools not present")

    name = f"torinai_cfgtest_{uuid.uuid4().hex[:10]}"
    user = os.getenv("POSTGRES_USER") or "stefan"
    # SAME SERVER THE CODE CONNECTS TO. TorinAI runs its own instance on 5433;
    # createdb without -h/-p goes to the default 5432 socket, so the database
    # was created on a different server and the subprocess then reported
    # `database "..." does not exist` -- a test that could only ever fail while
    # looking like a configuration defect in the code it was checking.
    # Resolved through PostgresConfig, the same authority the code uses.
    # os.getenv() alone returns None here because the settings live in
    # .env.postgres and are deliberately never exported into the process
    # environment -- so the port silently fell back to 5432.
    from core.database.postgres_config import PostgresConfig

    resolved = PostgresConfig.resolve()
    server = ["-h", resolved.host, "-p", str(resolved.port), "-U", user]
    created = subprocess.run([str(PG_BIN / "createdb"), *server, name],
                             capture_output=True, text=True)
    if created.returncode:
        pytest.skip(f"cannot create test database: {created.stderr.strip()[:200]}")

    try:
        script = (
            "import asyncio, os, sys;"
            "sys.path.insert(0, %r);"
            "from core.database.unified_database_postgres import TorinUnifiedDatabasePostgres as D;"
            "d = D(database=os.environ['POSTGRES_DATABASE']);"
            "print('IDENTITY', asyncio.run(d.assert_database_identity(os.environ['POSTGRES_DATABASE'])))"
            % str(ROOT)
        )
        environment = dict(os.environ)
        environment["POSTGRES_DATABASE"] = name
        environment["POSTGRES_USER"] = user
        environment["POSTGRES_HOST"] = resolved.host
        environment["POSTGRES_PORT"] = str(resolved.port)
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, env=environment, cwd=str(ROOT),
        )
        assert f"IDENTITY {name}" in result.stdout, (
            f"subprocess did not reach {name}\n"
            f"stdout: {result.stdout[-600:]}\nstderr: {result.stderr[-600:]}"
        )
    finally:
        subprocess.run([str(PG_BIN / "dropdb"), "--if-exists", *server, name],
                       capture_output=True, text=True)


def test_identity_mismatch_is_a_hard_failure():
    """Refusing to proceed is the point; a warning would be read past."""
    import asyncio

    from core.database.unified_database_postgres import TorinUnifiedDatabasePostgres

    db = TorinUnifiedDatabasePostgres()
    with pytest.raises(DatabaseIdentityError):
        asyncio.run(db.assert_database_identity("a_database_that_is_not_connected"))
