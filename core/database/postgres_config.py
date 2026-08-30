#!/usr/bin/env python3
"""Where PostgreSQL connection settings come from, and in what order.

One authority, with an explicit precedence:

    explicit argument  >  process environment  >  .env file  >  coded default

The defect this replaces: the database class called
``load_dotenv(".env.postgres", override=True)`` inside its own constructor,
*then* read ``os.getenv('POSTGRES_DATABASE')``. Because ``override=True``
rewrites the process environment, the file always won and the environment read
on the next line could never see an externally-supplied value. A subprocess
launched with ``POSTGRES_DATABASE=torinai_abl_blank`` connected to
``torinai_db`` and said nothing.

That was found by an ablation in which every condition -- including the ones
whose learned rules had been deleted -- loaded identical rules and passed
identically. The severance oracle worked: it showed the intended intervention
was not causally connected to the runtime's actual authority. The same defect
reaches CI, staging, container secrets, credential rotation and any maintenance
script that expects deployment configuration to override local defaults.

A database implementation consumes configuration; it does not mutate the
process it runs in. Resolution here reads ``.env`` files with ``dotenv_values``,
which returns a mapping and leaves ``os.environ`` untouched, so importing or
constructing a database never changes what any other component will observe.

Provenance is recorded per field so the answer to "which database am I actually
configured for, and who decided that" is available rather than inferred.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence

from dotenv import dotenv_values

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent.parent

#: Consulted in order; the first file that exists supplies fallback values.
DEFAULT_ENV_FILES: Sequence[Path] = (
    _ROOT / ".env.postgres",
    _ROOT / ".env.production",
)

#: TorinAI's OWN PostgreSQL instance. 5432 is the shared Homebrew instance that
#: also holds agentso's tenant databases, and TorinAI connected there as a
#: superuser with BypassRLS -- no boundary at all between the substrate and that
#: data. The instances were separated for that reason: separate port, separate
#: data directory, separate process.
#:
#: THE CODED DEFAULT MUST BE 5433, NOT 5432. This is the value used when no
#: env file and no environment variable is found -- a container, a different
#: working directory, a copied deployment. Defaulting to 5432 means the
#: fallback path silently lands on agentso's instance, which is both the wrong
#: data and a boundary violation. A missing config should fail toward TorinAI's
#: own database, never toward somebody else's.
#:
#: Imported by every other module that needs a port, so this is the one place
#: it is written down.
DEFAULT_PORT = 5433

DEFAULTS: Dict[str, Any] = {
    "host": "localhost",
    "port": DEFAULT_PORT,
    "database": "torinai_db",
    "user": "postgres",
    "password": "",
    "pool_min_size": 5,
    "pool_max_size": 20,
}

ENV_KEYS: Dict[str, str] = {
    "host": "POSTGRES_HOST",
    "port": "POSTGRES_PORT",
    "database": "POSTGRES_DATABASE",
    "user": "POSTGRES_USER",
    "password": "POSTGRES_PASSWORD",
    "pool_min_size": "POSTGRES_POOL_MIN_SIZE",
    "pool_max_size": "POSTGRES_POOL_MAX_SIZE",
}

_INTEGERS = {"port", "pool_min_size", "pool_max_size"}


class DatabaseIdentityError(RuntimeError):
    """Raised when the connected database is not the one that was intended.

    A process reporting that it operates against one database while writing to
    another is an authority contradiction, and for anything mutation-capable it
    has to stop rather than proceed on the assumption.
    """


@dataclass(frozen=True)
class PostgresConfig:
    host: str
    port: int
    database: str
    user: str
    password: str
    pool_min_size: int
    pool_max_size: int
    #: field name -> "explicit" | "environment" | "dotenv:<file>" | "default"
    provenance: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def resolve(
        cls,
        *,
        env: Optional[Mapping[str, str]] = None,
        env_files: Optional[Sequence[Path]] = None,
        **explicit: Any,
    ) -> "PostgresConfig":
        """Resolve settings without mutating the process environment."""
        environment = os.environ if env is None else env
        files = DEFAULT_ENV_FILES if env_files is None else env_files

        from_file: Dict[str, str] = {}
        file_label = ""
        for path in files:
            if path.exists():
                from_file = {k: v for k, v in dotenv_values(path).items() if v is not None}
                file_label = f"dotenv:{path.name}"
                break

        values: Dict[str, Any] = {}
        provenance: Dict[str, str] = {}
        for name, default in DEFAULTS.items():
            key = ENV_KEYS[name]
            supplied = explicit.get(name)
            if supplied is not None:
                raw, source = supplied, "explicit"
            elif environment.get(key) not in (None, ""):
                raw, source = environment[key], "environment"
            elif from_file.get(key) not in (None, ""):
                raw, source = from_file[key], file_label
            else:
                raw, source = default, "default"

            values[name] = int(raw) if name in _INTEGERS else str(raw)
            provenance[name] = source

        return cls(**values, provenance=provenance)

    def describe(self) -> Dict[str, Any]:
        """Observable identity of the connection. Never includes the password."""
        return {
            "host": self.host,
            "port": self.port,
            "database": self.database,
            "user": self.user,
            "configuration_source": dict(self.provenance),
        }

    def __repr__(self) -> str:
        return (f"PostgresConfig(host={self.host!r}, port={self.port}, "
                f"database={self.database!r}, user={self.user!r}, "
                f"password=<redacted>)")
