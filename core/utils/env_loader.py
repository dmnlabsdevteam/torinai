#!/usr/bin/env python3
"""Environment loader (portable).

This project supports env-based configuration via `.env.production` and/or `.env`.
Historically, this module hardcoded a Dominion Labs workstation path and carried
MySQL-era defaults. Those assumptions have been removed.

Resolution order:
- If `TORINAI_ENV_FILE` (or `DOMINION_ENV_FILE`) is set, load that path.
- Else, look for `.env.production` then `.env` in common repo locations.
"""

import os
import logging
import subprocess
from pathlib import Path
from typing import Optional, Iterable

logger = logging.getLogger(__name__)

DEFAULT_ENV_FILES: tuple[str, ...] = (".env.production", ".env")


def _candidate_roots() -> Iterable[Path]:
    """Return likely repo roots to search for env files."""
    here = Path(__file__).resolve()

    # TorinAI/core/utils/env_loader.py -> TorinAI
    torinai_root = here.parents[2]
    yield torinai_root

    # Workspace root (one above TorinAI)
    workspace_root = here.parents[3]
    yield workspace_root

    # Current working directory (useful when running scripts)
    yield Path.cwd()


def resolve_env_files() -> list[Path]:
    """The env files to load, in BASE→OVERRIDE order (later files win).

    THE MASTER LIVES OUTSIDE THE AI FOLDER. The Dominion Labs workspace `.env`
    (one above TorinAI) is the single source of every shared credential the AI
    needs -- Cloudflare, threat-intelligence (ABUSEIPDB/VIRUSTOTAL/OTX), and the
    rest. TorinAI's own `.env.production`/`.env` are the AI-specific layer that
    OVERRIDES the master where they disagree.

    The previous resolver returned the FIRST file it found, and it searched the
    TorinAI root first, so it loaded only the local partial file and never the
    master -- which is exactly why threat_intel had zero sources despite the
    keys existing. Loading the workspace master as a base, then the local files
    on top, gives the process every key with the local layer still winning.

    The workspace `.env` also carries PG_*/agentso credentials for the sibling
    web app; those are inert here because TorinAI reads POSTGRES_*/DB_* through
    PostgresConfig (which asserts its own database identity) and nothing reads
    PG_*. So the master can be a safe base without repointing the database.
    """
    explicit = os.getenv("TORINAI_ENV_FILE") or os.getenv("DOMINION_ENV_FILE")
    if explicit:
        p = Path(explicit).expanduser().resolve()
        return [p] if p.exists() else []

    here = Path(__file__).resolve()
    torinai_root = here.parents[2]
    workspace_root = here.parents[3]

    files: list[Path] = []
    # Base first (workspace master), then the AI-specific overrides. Within a
    # location, .env.production before .env so .env still wins locally.
    for root in (workspace_root, torinai_root):
        for name in (".env.production", ".env"):
            candidate = root / name
            if candidate.exists() and candidate not in files:
                files.append(candidate)
    return files


def resolve_env_file() -> Optional[Path]:
    """The single winning env file (the last override), for messaging.

    Kept for callers that want one representative path. The real loading uses
    `resolve_env_files()`, which layers the workspace master under the local
    overrides.
    """
    files = resolve_env_files()
    return files[-1] if files else None


def load_global_env(force_reload: bool = False):
    """
    Load environment variables from the Dominion Labs global .env file

    This ensures all services (TorinAI, security systems, Cloud Storage, etc.)
    use the same environment configuration.

    Args:
        force_reload: If True, reload even if already loaded

    Returns:
        True if loaded successfully, False otherwise
    """
    # Check if already loaded (unless force reload)
    if not force_reload and os.getenv('DOMINION_ENV_LOADED'):
        logger.debug("Global environment already loaded")
        return True

    env_files = resolve_env_files()
    if not env_files:
        logger.debug("No .env file found; using existing process environment")
        return False

    try:
        # Load each layer in base→override order (workspace master first, local
        # overrides last). override=True so a later layer wins, which is the
        # whole point of the ordering.
        try:
            from dotenv import load_dotenv
            for env_file in env_files:
                load_dotenv(env_file, override=True)
            logger.info("✅ Loaded environment from: %s",
                        ", ".join(str(f) for f in env_files))
        except ImportError:
            # Fallback: Manual parsing if dotenv not available
            logger.warning("python-dotenv not available, using manual parsing")
            for env_file in env_files:
                _manual_load_env(env_file)

        # Mark as loaded
        os.environ['DOMINION_ENV_LOADED'] = 'true'
        return True

    except Exception as e:
        logger.error(f"Failed to load global environment: {e}")
        return False


def _manual_load_env(env_file: Path):
    """
    Manually parse .env file if python-dotenv not available

    Args:
        env_file: Path to .env file
    """
    with open(env_file, 'r') as f:
        for line in f:
            line = line.strip()

            # Skip comments and empty lines
            if not line or line.startswith('#'):
                continue

            # Parse KEY=VALUE
            if '=' in line:
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip()

                # Remove quotes if present
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                elif value.startswith("'") and value.endswith("'"):
                    value = value[1:-1]

                # Set environment variable
                os.environ[key] = value


def get_env(
    key: str,
    default: Optional[str] = None,
    required: bool = False
) -> Optional[str]:
    """
    Get environment variable from global .env

    Args:
        key: Environment variable key
        default: Default value if not found
        required: If True, raise error if not found

    Returns:
        Environment variable value or default

    Raises:
        ValueError: If required=True and key not found
    """
    # Ensure global env is loaded
    load_global_env()

    value = os.getenv(key, default)

    if required and value is None:
        source = resolve_env_file()
        raise ValueError(
            f"Required environment variable '{key}' not found" + (f" in {source}" if source else "")
        )

    return value


def get_cloudflare_credentials() -> dict:
    """
    Get Cloudflare credentials from global .env

    Returns:
        Dictionary with api_token and zone_id (may be None if not set)
    """
    return {
        'api_token': get_env('CLOUDFLARE_API_TOKEN'),
        'zone_id': get_env('CLOUDFLARE_ZONE_ID')
    }


def get_threat_intel_keys() -> dict:
    """
    Get threat intelligence API keys from global .env

    Returns:
        Dictionary with abuseipdb_key, virustotal_key, otx_key
    """
    return {
        'abuseipdb_key': get_env('ABUSEIPDB_API_KEY'),
        'virustotal_key': get_env('VIRUSTOTAL_API_KEY'),
        'otx_key': get_env('OTX_API_KEY')
    }


def get_database_credentials() -> dict:
    """
    Get database credentials from global .env

    Returns:
        Dictionary with host, port, user, password, database
    """
    return {
        'host': get_env('DB_HOST', 'localhost'),
        # TorinAI's own instance. 5432 is the shared agentso one.
        'port': int(get_env('DB_PORT', '5433')),
        'user': get_env('DB_USER', 'postgres'),
        'password': get_env('DB_PASSWORD'),
        'database': get_env('DB_NAME', 'torinai_db')
    }


def list_available_env_vars() -> list:
    """
    List all environment variables loaded from global .env

    Returns:
        List of (key, value) tuples (passwords/tokens are masked)
    """
    load_global_env()

    sensitive_keywords = ['password', 'token', 'key', 'secret', 'credential']

    env_vars = []
    for key, value in os.environ.items():
        # Skip system environment variables
        if key.startswith('_') or key in ['PATH', 'HOME', 'USER', 'SHELL']:
            continue

        # Mask sensitive values
        is_sensitive = any(kw in key.lower() for kw in sensitive_keywords)
        display_value = '***MASKED***' if is_sensitive and value else value

        env_vars.append((key, display_value))

    return sorted(env_vars)


def get_github_token() -> Optional[str]:
    """
    Resolve a GitHub personal access token from every available credential source.

    Resolution order (first non-empty value wins):
      1. Environment variables — GITHUB_TOKEN, GH_TOKEN, GITHUB_PAT,
         PERSONAL_ACCESS_TOKEN, GH_ACCESS_TOKEN, GITHUB_ACCESS_TOKEN, GIT_TOKEN
      2. gh CLI  — ``gh auth token``  (works when VS Code / gh CLI is authenticated)
      3. macOS Keychain  — ``git credential-osxkeychain get``
      4. Generic git credential helper — ``git credential fill``

    Returns:
        The token string, or None if nothing was found.
    """
    load_global_env()

    # 1. Environment variables
    for var in (
        "GITHUB_TOKEN", "GH_TOKEN", "GITHUB_PAT",
        "PERSONAL_ACCESS_TOKEN", "GH_ACCESS_TOKEN",
        "GITHUB_ACCESS_TOKEN", "GIT_TOKEN",
    ):
        val = os.getenv(var, "").strip()
        if val and not val.startswith("#"):
            logger.debug(f"GitHub token resolved from env var: {var}")
            return val

    # 2. gh CLI
    try:
        r = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True, text=True, timeout=5,
        )
        tok = r.stdout.strip()
        if tok and r.returncode == 0:
            logger.debug("GitHub token resolved via gh CLI")
            return tok
    except Exception:
        pass

    # 3. macOS Keychain via git-credential-osxkeychain
    try:
        r = subprocess.run(
            ["git", "credential-osxkeychain", "get"],
            input="protocol=https\nhost=github.com\n",
            capture_output=True, text=True, timeout=5,
        )
        for line in r.stdout.splitlines():
            if line.startswith("password="):
                logger.debug("GitHub token resolved from macOS Keychain")
                return line.split("=", 1)[1].strip()
    except Exception:
        pass

    # 4. Generic git credential fill (any configured helper)
    try:
        r = subprocess.run(
            ["git", "credential", "fill"],
            input="protocol=https\nhost=github.com\n",
            capture_output=True, text=True, timeout=5,
        )
        for line in r.stdout.splitlines():
            if line.startswith("password="):
                logger.debug("GitHub token resolved via git credential fill")
                return line.split("=", 1)[1].strip()
    except Exception:
        pass

    logger.warning(
        "get_github_token(): no token found. Checked env vars, gh CLI, "
        "osxkeychain, and git-credential-fill."
    )
    return None


# Auto-load on module import
load_global_env()

logger.info(f"📁 Environment loader initialized (source: {resolve_env_file()})")
