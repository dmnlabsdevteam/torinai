#!/usr/bin/env python3
"""
Tool Registry System
===================
Central registry for all tools available to the Singleton.

Provides:
- Tool registration and discovery
- Parameter validation
- Safety checks
- Usage tracking
- Constitutional oversight
- Governance integration

Author: Torin AI Team
"""

from core.capability import raise_if_structural
import asyncio
import hashlib
import json
import logging
import math
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

# Phase 2: Governance integration
from core.governance import (
    UnifiedGovernanceTriggerSystem,
    ActionCategory,
    EnforcementMode,
    DecisionTier,
)
from core.safety import (
    CommitmentContract,
    CommitmentType,
    execute_action_with_commitments
)

# Chaos engineering decorators
from core.chaos.decorators import inject_latency, inject_error


# ── Tool error enrichment ─────────────────────────────────────────────────────
# Each entry is (category_tag, [regex_patterns], hint_text).
# Patterns are matched against the lowercased error string.
# The FIRST matching category wins — more specific patterns go first.

import re as _re

_ERROR_CATEGORIES = [

    # ════════════════════════════════════════════════════════════════════════
    # FILESYSTEM TOOLS  (read_file, write_file, patch_file, list_directory,
    #                    search_files, move_file, copy_file, delete_file)
    # ════════════════════════════════════════════════════════════════════════

    # ── patch_file: old_string not found — MUST be before FILE_NOT_FOUND ────
    (
        "PATCH_STRING_NOT_FOUND",
        [
            r"old_string not found",
            r"exact text was not found",
            r"old_string.*not found",
            r"copy.*verbatim.*read_file",
        ],
        """patch_file could not locate old_string in the file.
  The file may have been modified since you last read it, or whitespace differs.
  Retry steps (do each in order until one works):
  1. read_file(path, start_line=<line>, end_line=<line+20>) on the exact section to change.
  2. Copy the text character-for-character from that read_file output — do not reconstruct from memory.
  3. Indentation, trailing spaces, and blank lines must match exactly.
  4. If the section has moved, use grep_search(pattern="<unique_phrase>") to find its new line number.
  5. Retry patch_file with the freshly-read text as old_string.""",
    ),

    # ── patch_file: ambiguous match ──────────────────────────────────────────
    (
        "PATCH_AMBIGUOUS",
        [
            r"old_string.*ambiguous",
            r"old_string matches \d+ locations",
            r"must be unique",
            r"add more surrounding context",
        ],
        """patch_file found old_string in more than one place — it must be unique.
  Retry steps:
  1. read_file(path, start_line=<target_line-5>, end_line=<target_line+5>) to get broader context.
  2. Extend old_string to include 3-5 unique surrounding lines (function signature, comment, etc.).
  3. Verify uniqueness: grep_search(pattern="<key_phrase_in_old_string>") should return exactly one hit.
  4. Retry patch_file with the extended old_string.""",
    ),

    # ── patch_file / write_file: no-op ───────────────────────────────────────
    (
        "PATCH_NOOP",
        [
            r"old_string and new_string are identical",
            r"no-op patch",
            r"patch changes nothing",
            r"content.*already.*present",
            r"already contains",
        ],
        """The patch changed nothing — old_string and new_string are identical.
  The file already contains the content you tried to write, or you made a copy error.
  Retry steps:
  1. read_file the section you intended to change to see its current state.
  2. If the desired change is already there, proceed to the next step (run tests).
  3. If you intended a different change, identify the correct old_string from what read_file returns.
  4. Construct a new_string that is genuinely different, then retry patch_file.""",
    ),

    # ── write_file: truncation guard ─────────────────────────────────────────
    (
        "TRUNCATION_GUARD",
        [
            r"truncation guard",
            r"content is too short",
            r"less than 80.*original",
            r"refusing to overwrite",
        ],
        """write_file rejected the write — new content is far shorter than the existing file.
  You are about to destroy content by writing a partial/stub replacement.
  Retry steps:
  1. Switch to patch_file — provide only old_string (the lines to replace) and new_string (the replacement).
  2. patch_file leaves the rest of the file untouched; you do not need the full file content.
  3. If you genuinely need to rewrite the whole file, read_file it completely first, apply your change
     to the full text in memory, then write_file the complete result.""",
    ),

    # ── File not found ────────────────────────────────────────────────────────
    (
        "FILE_NOT_FOUND",
        [
            r"no such file or directory",
            r"filenotfounderror",
            r"path.*does not exist",
            r"cannot find.*file",
            r"file.*not found",
            r"no such path",
        ],
        """The file or directory does not exist at the given path.
  Retry steps:
  1. grep_search(pattern="<filename_keyword>", path=".") to locate the correct path.
  2. list_directory(path="<parent_dir>") to see what actually exists there.
  3. Check for typos, case sensitivity, or a missing subdirectory.
  4. If the path uses ~, expand it: run_python("import os; print(os.path.expanduser('~/<rel_path>'))").
  5. Retry the original tool call with the corrected path.""",
    ),

    # ── Write / delete permission denied ─────────────────────────────────────
    (
        "WRITE_PERMISSION",
        [
            r"read.?only file system",
            r"permission denied.*write",
            r"cannot write",
            r"isadirectoryerror",
            r"oserror.*\[errno 13\]",
            r"oserror.*\[errno 30\]",
        ],
        """Write or delete failed — the path is read-only or the process lacks permission.
  Retry steps:
  1. run_command("ls -la '<parent_dir>'") to inspect actual permissions.
  2. Try writing to a writable path instead: store/outputs/<task_id>/ or /tmp/.
  3. If the target is a project source file, confirm it is not git-locked:
     run_command("git status '<file_path>'").
  4. run_command("chmod u+w '<file_path>'") to grant write permission if appropriate.
  5. Retry the write with the corrected path or after fixing permissions.""",
    ),

    # ── File already exists (exclusive create) ────────────────────────────────
    (
        "FILE_EXISTS",
        [
            r"file.*already exists",
            r"fileexistserror",
            r"oserror.*\[errno 17\]",
        ],
        """A file already exists at the target path.
  Retry steps:
  1. read_file the existing file to understand its current contents.
  2. If you want to update it, use patch_file (targeted change) or write_file with mode="write".
  3. If you want to append, use write_file with mode="append".
  4. If the file should be replaced entirely, read it first, merge your changes, then write_file.""",
    ),

    # ── Directory not empty (delete/move) ─────────────────────────────────────
    (
        "DIR_NOT_EMPTY",
        [
            r"directory not empty",
            r"oserror.*\[errno 66\]",
            r"directory.*not.*empty",
        ],
        """Cannot delete or move a non-empty directory.
  Retry steps:
  1. list_directory(path="<dir>", recursive=True) to see what is inside.
  2. Delete or move the contents individually first, then retry the directory operation.
  3. Alternatively: run_command("rm -rf '<dir>'") if removal of all contents is intended.""",
    ),

    # ── Large file read (auto-batched) ────────────────────────────────────────
    (
        "LARGE_FILE_BATCHED",
        [
            r"batched.*next_batch",
            r"use start_line.*end_line.*next batch",
            r"file.*too large.*batch",
        ],
        """The file is too large to return in one read — a partial batch was returned.
  Retry steps:
  1. Use the next_batch hint in the result to get the next chunk:
     read_file(path, start_line=<next>, end_line=<next+499>).
  2. Continue reading in batches until you have the section you need.
  3. For log files, use tail_lines=<N> to read only the most recent entries.
  4. For searching within a large file, use grep_search(pattern="<keyword>", path="<file>")
     instead of reading the whole file.""",
    ),


    # ════════════════════════════════════════════════════════════════════════
    # EXECUTION TOOLS  (run_python, run_shell_command, execute_sandbox,
    #                   install_package, kill_process)
    # ════════════════════════════════════════════════════════════════════════

    # ── Module / import error ─────────────────────────────────────────────────
    (
        "MODULE_NOT_FOUND",
        [
            r"modulenotfounderror",
            r"no module named",
            r"importerror.*cannot import",
            r"cannot import name",
        ],
        """A Python import failed inside run_python or a test file.
  Retry steps:
  1. run_command("pip show <package_name>") to check if it is installed.
  2. If missing: run_command("pip install <package_name>") then retry.
  3. If pip is unavailable: run_command("python3 -m pip install <package_name>").
  4. For project-internal imports: verify the module path with grep_search(pattern="class <Name>|def <func>").
  5. Add sys.path.insert(0, '<project_root>') at the top of run_python code to ensure project modules resolve.""",
    ),

    # ── Shell command not found ───────────────────────────────────────────────
    (
        "COMMAND_NOT_FOUND",
        [
            r"command not found",
            r"no such file or directory.*bin",
            r"exec.*not found",
            r"is not recognized as.*command",
            r"zsh:.*not found",
            r"bash:.*not found",
        ],
        """The shell command was not found on PATH.
  Retry steps:
  1. run_command("which <command>") — if it prints a path, use that absolute path.
  2. run_command("brew list | grep <command>") or run_command("pip list | grep <command>").
  3. If it is a Python CLI tool: run_command("python3 -m <module_name> <args>") instead.
  4. If the binary is installed elsewhere: run_command("find /usr /opt /usr/local -name '<cmd>' 2>/dev/null").
  5. Install the tool if missing: run_command("brew install <tool>") or run_command("pip install <tool>").""",
    ),

    # ── Python syntax / indentation error ────────────────────────────────────
    (
        "PYTHON_SYNTAX_ERROR",
        [
            r"syntaxerror",
            r"indentationerror",
            r"unexpected indent",
            r"expected an indented block",
            r"invalid syntax",
        ],
        """Python syntax or indentation error in run_python code or a source file.
  Retry steps:
  1. Identify the exact line number from the traceback.
  2. Check indentation: Python requires consistent 4-space indentation; do not mix tabs and spaces.
  3. Check for unclosed brackets, parentheses, triple-quotes, or missing colons.
  4. If the error is in a file you just wrote, read_file it to inspect the exact content on disk.
  5. Test a minimal version of the code first; add complexity only after the base runs cleanly.""",
    ),

    # ── Process / sandbox timeout ─────────────────────────────────────────────
    (
        "TIMEOUT",
        [
            r"timed? out",
            r"timeout.*exceeded",
            r"deadline.*exceeded",
            r"asyncio\.timeouterror",
            r"read timeout",
            r"operation.*timed out",
            r"execution timed out",
        ],
        """The operation timed out before completing.
  Retry steps:
  1. Reduce scope: fewer rows, shorter date range, smaller file section, fewer iterations.
  2. For shell commands, increase the timeout parameter or use: run_command("timeout 120 <cmd>").
  3. For file reads on large files, switch to read_file(start_line=..., end_line=...) batches.
  4. Check if the target service is healthy: run_command("ps aux | grep <service_name>").
  5. Run a quick smoke-test version of the operation to confirm it works at small scale, then scale up.""",
    ),

    # ── Process resource exhaustion ───────────────────────────────────────────
    (
        "RESOURCE_EXHAUSTION",
        [
            r"memoryerror",
            r"out of memory",
            r"killed.*signal 9",
            r"killed.*oom",
            r"disk.*full",
            r"no space left",
            r"resource.*exhausted",
        ],
        """Resource exhaustion — memory, disk, or process killed by the OS.
  Retry steps:
  1. run_command("df -h && free -h") to check current disk and memory state.
  2. For memory: process data in smaller chunks; avoid loading entire large files at once.
  3. For disk: run_command("du -sh /tmp/* 2>/dev/null | sort -rh | head -20") to find large files to clean.
  4. For OOM: reduce batch size in the code and retry with explicit chunk loops.
  5. Verify the operation actually requires this resource, or find a lower-memory alternative algorithm.""",
    ),

    # ── Runtime error inside run_python ──────────────────────────────────────
    (
        "RUNTIME_ERROR",
        [
            r"runtimeerror",
            r"zerodivisionerror",
            r"indexerror",
            r"keyerror",
            r"attributeerror",
            r"nameerror.*not defined",
            r"recursionerror",
            r"stopiteration",
        ],
        """A runtime exception occurred inside run_python or run_shell_command.
  Retry steps:
  1. Read the full traceback — identify the exact line and variable that caused the error.
  2. For KeyError/IndexError: print the object's keys or length before accessing it.
  3. For AttributeError: confirm the object type with run_python("print(type(obj), dir(obj))").
  4. For NameError: ensure all variables and imports are defined before use.
  5. Add defensive checks (if key in dict, if len(list) > i) and retry.""",
    ),


    # ════════════════════════════════════════════════════════════════════════
    # TESTING TOOLS  (run_pytest, run_unittest, generate_test, benchmark)
    # ════════════════════════════════════════════════════════════════════════

    # ── No tests collected / collection error ────────────────────────────────
    (
        "TEST_NOT_FOUND",
        [
            r"no tests ran",
            r"no tests were run",
            r"collected 0 items",
            r"no tests found",
            r"error.*collecting",
            r"could not import.*test",
            r"importerror.*test",
            r"did not warn",
            r"failed.*did not warn",
        ],
        """pytest collected no tests, or the test file has an import/collection error.
  Retry steps:
  1. run_command("python -m pytest '<test_file>' --collect-only -v") to see what pytest can find.
  2. Confirm the test file path is correct and single-quoted (paths on this machine contain spaces).
  3. Run only the specific test file — never the whole tests/ directory.
  4. Verify the test file imports correctly:
     run_python("import sys; sys.path.insert(0,'<torinai_root>'); import <module>; print('OK')").
  5. If the test expects behaviour the source does not yet implement (e.g. a warning never raised),
     fix the SOURCE file to add the missing behaviour, then re-run the test.""",
    ),

    # ── Test assertion failure ────────────────────────────────────────────────
    (
        "TEST_ASSERTION_FAILED",
        [
            r"assertionerror.*test",
            r"assert.*failed",
            r"expected.*got",
            r"assertEqual.*failed",
            r"failed.*assert",
            r"not equal.*assert",
        ],
        """A test assertion failed — the code under test produced an unexpected result.
  Retry steps:
  1. Read the full failure output to identify which assertion failed and what values were compared.
  2. read_file the source function under test to understand its current logic.
  3. Determine whether the SOURCE is wrong (fix source, re-run test) or the TEST is wrong (fix test).
  4. Add a run_python debug snippet that calls the function directly and prints its return value.
  5. patch_file the source to correct the logic, then re-run the targeted test file.""",
    ),

    # ── Benchmark / performance regression ───────────────────────────────────
    (
        "PERFORMANCE_REGRESSION",
        [
            r"performance.*regression",
            r"benchmark.*failed",
            r"slower than.*baseline",
            r"exceeded.*time.*budget",
            r"latency.*too high",
        ],
        """A performance benchmark failed or exceeded its threshold.
  Retry steps:
  1. run_python a timing snippet to measure the slow function in isolation.
  2. Use grep_search to find recent changes to the function: grep_search(pattern="def <func_name>").
  3. Profile with: run_python("import cProfile; cProfile.run('<statement>')").
  4. Identify the bottleneck and patch_file a targeted optimization.
  5. Re-run the benchmark to confirm the regression is resolved.""",
    ),


    # ════════════════════════════════════════════════════════════════════════
    # SEARCH TOOLS  (grep_search, semantic_search, analyze_code,
    #                find_files, list_code_structure)
    # ════════════════════════════════════════════════════════════════════════

    # ── Search returned no results ────────────────────────────────────────────
    (
        "SEARCH_NO_RESULTS",
        [
            r"no matches found",
            r"no results.*found",
            r"search.*returned.*empty",
            r"0 matches",
            r"nothing matched",
        ],
        """The search returned no results.
  Retry steps:
  1. Broaden the pattern — try a shorter keyword or partial word (e.g. "config" instead of "configuration").
  2. Try a different tool: semantic_search for concept-level search vs grep_search for exact text.
  3. Check the search path — list_directory(path=".") to confirm you are searching the right directory.
  4. Try a case-insensitive variant or regex alternative.
  5. Search parent directories: grep_search(pattern="<term>", path="<project_root>").""",
    ),

    # ── Regex error in search ─────────────────────────────────────────────────
    (
        "SEARCH_INVALID_REGEX",
        [
            r"invalid.*regex",
            r"regex.*error",
            r"re\.error",
            r"bad escape",
            r"nothing to repeat",
            r"unbalanced parenthes",
        ],
        """The search pattern is not valid regex.
  Retry steps:
  1. Set is_regex=False to treat the pattern as a plain text search.
  2. If regex is needed, escape special characters: ., *, +, (, ), [, ], {, }, ^, $, |, \\, ?.
  3. Test the regex with: run_python("import re; re.compile('<pattern>'); print('OK')").
  4. Simplify the pattern and add complexity after confirming the base pattern compiles.""",
    ),


    # ════════════════════════════════════════════════════════════════════════
    # DATABASE TOOLS  (postgres_query, mysql_query, redis_get/set,
    #                  clickhouse_query, mysql_table_info)
    # ════════════════════════════════════════════════════════════════════════

    # ── DB connection / server down ───────────────────────────────────────────
    (
        "DATABASE_CONNECTION",
        [
            r"can't connect to.*server",
            r"lost connection to.*server",
            r"database.*unreachable",
            r"connection.*refused.*\d{4}",
            r"server.*not.*running",
            r"pg.*connection.*failed",
            r"asyncpg.*cannotconnect",
        ],
        """Cannot connect to the database server.
  DISCOVER the endpoint before probing it. Every step below reads the real
  configuration rather than assuming a host, port, file or service name -- this
  guidance is generic, and a caller's deployment is not knowable from here.
  Retry steps:
  1. Resolve the configured target, do not assume localhost or a default port:
     run_python("from core.database.postgres_config import PostgresConfig; c=PostgresConfig.resolve(); print(c.host, c.port, c.database, dict(c.provenance))")
     The provenance says which source decided each field, so a wrong value is
     traceable to the file or variable that set it.
  2. Probe THAT endpoint, with its port: run_command("pg_isready -h <host> -p <port>")
     (for MySQL: run_command("mysqladmin ping -h <host> -P <port>")).
  3. If it does not answer, find what is actually listening before concluding
     the server is down: run_command("lsof -nP -iTCP -sTCP:LISTEN | grep -i -E 'postgres|mysql'").
     More than one instance on different ports is common; connecting to the
     wrong one reads a different database, which is worse than an error.
  4. Start it only if nothing is listening on the configured port. Discover how
     it is managed rather than guessing a version or init system:
     run_command("brew services list") on macOS, run_command("systemctl list-units '*sql*'") on Linux.
  5. Retry the database tool once step 2 answers on the configured port.""",
    ),

    # ── SQL error (bad query / missing table) ─────────────────────────────────
    (
        "DATABASE_QUERY_ERROR",
        [
            r"operationalerror",
            r"table.*doesn.*exist",
            r"unknown column",
            r"no such table",
            r"relation.*does not exist",
            r"column.*does not exist",
            r"syntax error.*at or near",
            r"pg.*error",
            r"clickhouse.*exception",
        ],
        """The SQL query failed — bad syntax, missing table, or unknown column.
  Retry steps:
  1. For missing table: run_command("psql -c '\\dt'") or use mysql_table_info to list tables.
  2. For unknown column: fetch the schema first with mysql_table_info(table_name="<table>").
  3. For syntax errors: simplify the query to a basic SELECT, verify it works, then add complexity.
  4. Check if a migration is needed: grep_search(pattern="CREATE TABLE.*<table_name>", path="migrations/").
  5. Retry with the corrected table name, column name, or fixed SQL syntax.""",
    ),

    # ── Redis error ───────────────────────────────────────────────────────────
    (
        "REDIS_ERROR",
        [
            r"redis.*error",
            r"connection.*redis",
            r"redis.*not.*running",
            r"redis.*refused",
        ],
        """Redis operation failed.
  Retry steps:
  1. run_command("redis-cli ping") — should return PONG if Redis is running.
  2. run_command("brew services start redis") to start it if needed.
  3. Verify the Redis host/port in config: grep_search(pattern="REDIS_URL|redis_host", path="config/").
  4. For key-not-found: use redis_get with a default value or check key existence first.
  5. Retry the Redis operation after confirming the server is reachable.""",
    ),


    # ════════════════════════════════════════════════════════════════════════
    # NETWORK TOOLS  (http_request, download_file, api_call,
    #                 websocket_connect, graphql_query)
    # ════════════════════════════════════════════════════════════════════════

    # ── HTTP error responses ──────────────────────────────────────────────────
    (
        "HTTP_ERROR",
        [
            r"\b4\d{2}\b(?!.*\b401\b)(?!.*\b403\b)",  # 4xx except 401/403 (covered by CREDENTIAL)
            r"\b5\d{2}\b",
            r"http.*error",
            r"bad gateway",
            r"service unavailable",
            r"internal server error",
            r"not found.*404",
            r"status.*4\d\d",
            r"status.*5\d\d",
        ],
        """An HTTP error response was received.
  Retry steps:
  1. Check the status code: 404 = wrong URL, 500/502/503 = server error (retry later), 400 = bad request body.
  2. For 404: verify the endpoint URL with grep_search(pattern="<api_base_url>") or API docs.
  3. For 400: print the request body and compare with the API's expected schema.
  4. For 500/503: run_command("curl -v '<url>'") to get full headers; wait 30s and retry once.
  5. For rate limit (429) see the RATE_LIMIT hint above.""",
    ),

    # ── Hostname not found / DNS failure ─────────────────────────────────────
    # Must come BEFORE the generic NETWORK_ERROR block so it matches first.
    (
        "HOST_NOT_FOUND",
        [
            r"name or service not known",
            r"nodename nor servname provided",
            r"name resolution.*fail",
            r"cannot resolve.*hostname",
            r"getaddrinfo.*failed",
            r"temporary failure in name resolution",
            r"clientconnectordnserror",
        ],
        """The hostname does not exist — you likely used a made-up or misspelled URL.
  Do NOT retry http_request with the same hostname.

  If you are trying to search or research a topic, use the correct tool:
    conduct_research(topic='your topic here')   — searches arXiv, GitHub, Wikipedia, news, etc.
    search_academic(query='your topic here')    — arXiv, Semantic Scholar, PubMed

  If you need to fetch a specific real page, use known working URLs, e.g.:
    https://news.ycombinator.com               (Hacker News front page)
    https://github.com/trending                (GitHub trending repos)
    https://arxiv.org/search/?query=<topic>    (arXiv search)
    https://api.github.com/search/repositories?q=<topic>&sort=stars   (GitHub API)
    https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch=<topic>&format=json

  Do NOT invent or guess hostnames — only pass URLs you know are real.""",
    ),

    # ── Network / connection failure ──────────────────────────────────────────
    (
        "NETWORK_ERROR",
        [
            r"connection refused",
            r"connection.*timed out",
            r"network.*unreachable",
            r"failed to establish.*connection",
            r"connectionerror",
            r"socket.*error",
            r"ssl.*error",
            r"certificate.*verify.*failed",
            r"errno 111",
            r"errno 110",
        ],
        """Network or connection failure.
  Retry steps:
  1. run_command("curl -s --max-time 5 https://api.github.com") to test general connectivity.
  2. For a local service: run_command("lsof -i :<port>") to confirm it is listening.
  3. For SSL errors: run_command("openssl s_client -connect <host>:443") to inspect the cert.
  4. Retry after confirming the network path is reachable.""",
    ),

    # ── Rate limit ────────────────────────────────────────────────────────────
    (
        "RATE_LIMIT",
        [
            r"\b429\b", r"rate.?limit", r"too many requests",
            r"quota.*exceeded", r"quota.*exhausted", r"daily.*limit",
            r"requests.*per.*minute", r"throttl",
        ],
        """Rate limit or quota reached.
  Retry steps:
  1. Wait at least 60 seconds, then retry the same request.
  2. run_command("gh api rate_limit") for GitHub API remaining budget.
  3. For repeated limits, check if multiple concurrent calls are hitting the same endpoint and serialize them.
  4. If a per-key limit, try a different API key if one is configured in the environment.
  5. For daily quotas, queue the work and retry it as a follow-up task.""",
    ),

    # ── Download failed / partial download ───────────────────────────────────
    (
        "DOWNLOAD_ERROR",
        [
            r"download.*failed",
            r"incomplete.*download",
            r"partial.*content",
            r"content.*length.*mismatch",
            r"checksum.*mismatch",
        ],
        """File download failed or was incomplete.
  Retry steps:
  1. Retry the download — transient network errors are common.
  2. run_command("curl -L -o '<dest>' '<url>'") as an alternative to the download_file tool.
  3. Check available disk space: run_command("df -h '<dest_dir>'").
  4. Verify the URL is still valid with http_request(url="<url>", method="HEAD").
  5. For large files, consider streaming or downloading in parts.""",
    ),


    # ════════════════════════════════════════════════════════════════════════
    # AUTH / CREDENTIAL  (shared across all tools)
    # ════════════════════════════════════════════════════════════════════════

    (
        "CREDENTIAL",
        [
            r"no.*token", r"token.*not found", r"missing.*token",
            r"no.*api.*key", r"api.*key.*not found", r"missing.*api.*key",
            r"unauthorized", r"\b401\b", r"\b403\b", r"forbidden",
            r"authentication.*failed", r"unauthenticated",
            r"no.*credential", r"credential.*not found", r"missing.*credential",
            r"github_token", r"gh_token", r"github.*pat",
            r"no.*github", r"github.*not.*configured",
            r"invalid.*token", r"token.*expired", r"token.*revoked",
        ],
        """Credential not found or rejected.
  Retry steps — try each in order until one succeeds:
  1. run_command("gh auth token")
  2. read_file("~/.config/gh/hosts.yml")  — gh CLI stores OAuth tokens here
  3. run_command("grep -r 'GITHUB_TOKEN\\|GH_TOKEN\\|GITHUB_PAT' ~/.env .env ../.env 2>/dev/null | head -5")
  4. run_command("security find-generic-password -s github -w 2>/dev/null")  — macOS Keychain
  5. run_python("import os; print(os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN','NOT SET'))")
  If none return a token, record the absence in the task output and proceed with whatever is available.""",
    ),


    # ════════════════════════════════════════════════════════════════════════
    # CODE GENERATION / ANALYSIS TOOLS  (generate_code, refactor_code,
    #                                    analyze_code, lint_code)
    # ════════════════════════════════════════════════════════════════════════

    # ── Generated code fails to parse / compile ───────────────────────────────
    (
        "GENERATED_CODE_INVALID",
        [
            r"generated.*code.*invalid",
            r"code.*generation.*failed",
            r"could not parse.*generated",
            r"ast.*parse.*failed",
            r"compile.*failed",
        ],
        """The generated or refactored code is syntactically invalid.
  Retry steps:
  1. run_python("import ast; ast.parse(open('<file>').read()); print('OK')") to validate the file.
  2. read_file the generated file and find the exact syntax error line from the traceback.
  3. patch_file the invalid section with corrected syntax.
  4. Re-validate with ast.parse before proceeding to tests.""",
    ),

    # ── Lint / style errors ───────────────────────────────────────────────────
    (
        "LINT_ERROR",
        [
            r"flake8.*error",
            r"pylint.*error",
            r"ruff.*error",
            r"mypy.*error",
            r"type.*error.*mypy",
            r"linting.*failed",
            r"style.*violation",
        ],
        """Linting or type-checking errors were found.
  Retry steps:
  1. Read the linter output line by line — each line identifies a file, line number, and rule.
  2. For type errors: run_python the function with explicit type assertions to verify types.
  3. patch_file each violation individually — do not rewrite the whole file.
  4. Re-run the linter after each patch to confirm the specific error is resolved.
  5. For repeated false positives, add a targeted inline suppression comment (# noqa: <rule>).""",
    ),


    # ════════════════════════════════════════════════════════════════════════
    # MONITORING / SYSTEM TOOLS  (get_metrics, check_service_health,
    #                              get_logs, system_info, process_monitor)
    # ════════════════════════════════════════════════════════════════════════

    # ── Service not running ───────────────────────────────────────────────────
    (
        "SERVICE_NOT_RUNNING",
        [
            r"service.*not.*running",
            r"service.*stopped",
            r"service.*inactive",
            r"daemon.*not.*running",
            r"process.*not.*found",
            r"no.*process.*listening",
        ],
        """The target service or daemon is not running.
  Retry steps:
  1. run_command("brew services list") or run_command("systemctl list-units --type=service --state=running") to list running services.
  2. run_command("brew services start <service>") or run_command("systemctl start <service>") to start it.
  3. read_file the service log to understand why it stopped: run_command("tail -50 /var/log/<service>.log").
  4. run_command("ps aux | grep <process_name>") to check if it is running under a different name.
  5. Retry the monitoring tool after confirming the service is active.""",
    ),

    # ── Metrics / telemetry unavailable ──────────────────────────────────────
    (
        "METRICS_UNAVAILABLE",
        [
            r"metrics.*unavailable",
            r"metric.*not.*found",
            r"telemetry.*not.*configured",
            r"prometheus.*error",
            r"statsd.*error",
            r"no data.*metric",
        ],
        """Metrics or telemetry data is unavailable.
  Retry steps:
  1. Verify the metrics endpoint is reachable: http_request(url="http://localhost:9090/-/ready").
  2. Check if the metrics agent is configured: grep_search(pattern="prometheus|statsd|metrics", path="config/").
  3. Try a different time range or aggregation window in the query.
  4. Fall back to log-based metrics: grep_search(pattern="<event_keyword>", path="logs/") and count matches.
  5. Document what data sources are available and use those instead.""",
    ),

    # ── Log file empty or not found ───────────────────────────────────────────
    (
        "LOG_NOT_FOUND",
        [
            r"log.*not found",
            r"log.*file.*empty",
            r"no log.*entries",
            r"log.*directory.*missing",
        ],
        """Log file is missing or empty.
  Retry steps:
  1. list_directory(path="logs/") or list_directory(path="/var/log/") to find the correct log path.
  2. grep_search(pattern="<service_name>", path="logs/") to locate the right log file.
  3. run_command("find . -name '*.log' -newer /tmp -ls 2>/dev/null") to find recently written logs.
  4. Check if logging is enabled in config: grep_search(pattern="log_level|logging", path="config/").
  5. Retry after identifying the correct log file path.""",
    ),


    # ════════════════════════════════════════════════════════════════════════
    # MEMORY / LEARNING TOOLS  (store_memory, retrieve_memory,
    #                            update_belief, semantic_similarity)
    # ════════════════════════════════════════════════════════════════════════

    # ── Memory store / retrieval failure ─────────────────────────────────────
    (
        "MEMORY_ERROR",
        [
            r"memory.*store.*failed",
            r"memory.*retrieval.*failed",
            r"embedding.*failed",
            r"vector.*store.*error",
            r"pgvector.*error",
            r"memory.*not.*initialized",
            r"memory.*agent.*unavailable",
        ],
        """Memory storage or retrieval failed.
  Retry steps:
  1. run_python("from core.memory.agent import get_memory_agent; a=get_memory_agent(); print('OK' if a else 'NONE')") to check availability.
  2. Check the configured PostgreSQL/pgvector endpoint -- resolve it first, do
     not assume localhost or a default port:
     run_python("from core.database.postgres_config import PostgresConfig; c=PostgresConfig.resolve(); print(c.host, c.port, c.database)")
     then run_command("pg_isready -h <host> -p <port>").
  3. Try storing a simpler/shorter memory entry to isolate whether the failure is size-related.
  4. Check the embedding service: grep_search(pattern="embedding_service", path="core/memory/").
  5. Retry the memory operation after confirming the vector store is running.""",
    ),


    # ════════════════════════════════════════════════════════════════════════
    # PARSE / DATA ERRORS  (shared across all tools)
    # ════════════════════════════════════════════════════════════════════════

    (
        "PARSE_ERROR",
        [
            r"json.*decode.*error",
            r"jsondecode",
            r"expecting value.*line.*column",
            r"invalid.*json",
            r"yaml.*error",
            r"parse.*error",
            r"unexpected token",
            r"csv.*error",
            r"xml.*parse",
        ],
        """Output could not be parsed — malformed JSON, YAML, XML, or CSV.
  Retry steps:
  1. run_python("print(repr(raw_output[:500]))") to inspect the raw bytes/characters.
  2. Check if the output was truncated — look for an incomplete closing bracket or quote.
  3. For JSON: try json.loads() with error handling; fall back to regex extraction if needed.
  4. If an API returned an HTML error page instead of JSON, there is a network or auth issue — check those first.
  5. For YAML: verify indentation and quoting; try loading with yaml.safe_load() inside run_python.""",
    ),

    # ════════════════════════════════════════════════════════════════════════
    # GIT TOOLS  (git_commit, git_push, git_pull, git_diff, git_log,
    #             git_checkout, git_merge, git_stash)
    # ════════════════════════════════════════════════════════════════════════

    # ── Not a git repository ──────────────────────────────────────────────────
    (
        "GIT_NOT_INITIALIZED",
        [
            r"not a git repository",
            r"fatal.*not a git",
            r"\.git.*not found",
        ],
        """The current directory is not inside a git repository.
  Retry steps:
  1. run_command("git -C '<expected_root>' status") to check if the root is elsewhere.
  2. run_command("find . -name '.git' -maxdepth 4 -type d") to locate the repo root.
  3. If no repo exists yet: run_command("git init && git add -A && git commit -m 'init'").
  4. Retry the git command with the correct repository root path.""",
    ),

    # ── Dirty state blocks checkout / rebase ─────────────────────────────────
    (
        "GIT_DIRTY_STATE",
        [
            r"local changes.*would be overwritten",
            r"please commit.*stash",
            r"cannot.*checkout.*modified",
            r"uncommitted changes",
            r"working tree.*not clean",
        ],
        """Git operation blocked by uncommitted local changes.
  Retry steps:
  1. run_command("git status") to see which files are modified.
  2. run_command("git stash push -m 'auto-stash before <operation>'") to stash changes.
  3. Retry the git operation.
  4. Restore changes afterwards: run_command("git stash pop").""",
    ),

    # ── Remote rejected push ──────────────────────────────────────────────────
    (
        "GIT_REMOTE_REJECTED",
        [
            r"rejected.*non-fast-forward",
            r"push rejected",
            r"remote.*rejected",
            r"updates were rejected",
            r"fetch first",
        ],
        """The remote rejected the push — the branch has diverged.
  Retry steps:
  1. run_command("git pull --rebase origin <branch>") to rebase on top of the remote.
  2. If there are conflicts, resolve them (see GIT_MERGE_CONFLICT hint).
  3. run_command("git push origin <branch>") after the rebase completes cleanly.
  4. Do NOT force-push to a shared branch without explicit instruction to do so.""",
    ),

    # ── Merge conflict ────────────────────────────────────────────────────────
    (
        "GIT_MERGE_CONFLICT",
        [
            r"merge conflict",
            r"automatic merge failed",
            r"conflict.*both modified",
            r"unmerged paths",
            r"<<<<<<.*======.*>>>>>>",
        ],
        """A merge or rebase produced conflicts.
  Retry steps:
  1. run_command("git diff --name-only --diff-filter=U") to list conflicting files.
  2. read_file each conflicted file to see the conflict markers (<<<<<<, ======, >>>>>>).
  3. patch_file to replace the conflict block with the correct merged content.
  4. run_command("git add '<file>'") for each resolved file.
  5. run_command("git rebase --continue") or run_command("git merge --continue") to finish.""",
    ),


    # ════════════════════════════════════════════════════════════════════════
    # SLACK / COMMUNICATION TOOLS  (send_slack, slack_react,
    #                                slack_list_channels, slack_read_messages)
    # ════════════════════════════════════════════════════════════════════════

    # ── Slack channel not found ───────────────────────────────────────────────
    (
        "SLACK_CHANNEL_NOT_FOUND",
        [
            r"channel.*not found",
            r"channel_not_found",
            r"no.*channel.*named",
            r"channel_id.*invalid",
        ],
        """The Slack channel ID or name was not found.
  Retry steps:
  1. Use slack_list_channels() to get the full list of channels and their IDs.
  2. Match the desired channel name to its ID from the list.
  3. Use the channel ID (C01XXXXXX format), not the human-readable name, in the tool call.
  4. Retry the Slack tool with the correct channel ID.""",
    ),

    # ── Slack message too long ────────────────────────────────────────────────
    (
        "SLACK_MESSAGE_TOO_LONG",
        [
            r"msg_too_long",
            r"message.*too long",
            r"slack.*character.*limit",
            r"text.*exceeds.*limit",
        ],
        """Slack rejected the message because it exceeds the character limit (40,000 chars).
  Retry steps:
  1. Split the message into multiple parts: Part 1/N, Part 2/N, etc.
  2. For code blocks: upload as a Slack file attachment instead of inline text.
  3. Summarize the content to fit in one message, then reference the full data by file path.
  4. Retry by sending each part as a separate slack_send call.""",
    ),


    # ════════════════════════════════════════════════════════════════════════
    # ENCODING / CHARACTER ERRORS  (shared across file, network, and DB tools)
    # ════════════════════════════════════════════════════════════════════════

    (
        "ENCODING_ERROR",
        [
            r"unicodedecodeerror",
            r"unicodeencodeerror",
            r"codec.*can.*t decode",
            r"ordinal not in range",
            r"invalid.*byte.*sequence",
        ],
        """A Unicode encoding or decoding error occurred.
  Retry steps:
  1. For reading a file: use read_file's encoding parameter (try 'latin-1' or 'cp1252' as fallback).
  2. run_python("open('<file>', 'rb').read(200)") to inspect the raw bytes.
  3. run_python("open('<file>', 'r', encoding='utf-8', errors='replace').read(500)") to read with replacement.
  4. For API responses: check the Content-Type header for the declared encoding.
  5. Normalize to UTF-8 and retry: run_python("data.encode('utf-8', 'replace').decode('utf-8')").""",
    ),


    # ════════════════════════════════════════════════════════════════════════
    # CONCURRENCY / ASYNC ERRORS  (shared across execution and network tools)
    # ════════════════════════════════════════════════════════════════════════

    (
        "CONCURRENCY_ERROR",
        [
            r"runtimeerror.*event loop",
            r"asyncio.*coroutine",
            r"cannot run.*event loop.*is running",
            r"nest_asyncio",
            r"deadlock",
            r"lock.*timeout",
            r"race condition",
            r"concurrent.*modification",
        ],
        """Asyncio or concurrency error.
  Retry steps:
  1. For "event loop is already running": use asyncio.run() only at top level, not inside an existing loop.
  2. run_python("import nest_asyncio; nest_asyncio.apply()") to allow nested event loops in notebooks/shells.
  3. For thread-safety issues: serialize the access or use a queue.Queue() to coordinate.
  4. For deadlocks: add a timeout to all lock.acquire() calls and log which lock is stuck.
  5. Retry after restructuring the async/sync boundary.""",
    ),


    # ════════════════════════════════════════════════════════════════════════
    # SYSTEM / OS PERMISSION  (shared across file, shell, and monitoring tools)
    # ════════════════════════════════════════════════════════════════════════

    (
        "SYSTEM_PERMISSION",
        [
            r"operation not permitted",
            r"oserror.*\[errno 1\]",
            r"eperm",
            r"not permitted.*sudo",
            r"must be run as root",
            r"requires.*elevated.*privilege",
            r"sip.*protected",
        ],
        """OS permission denied — the operation requires elevated privileges.
  Retry steps:
  1. run_command("ls -la '<path>'") to check the file's current ownership and permissions.
  2. For SIP-protected macOS paths (/System, /usr): find an alternative writable path.
  3. For plist/launchd operations: run_command("launchctl print system/<service>") needs no sudo.
  4. For cron entries: run_command("crontab -l") (current user) doesn't need sudo.
  5. If the operation genuinely requires root, document what command needs to be run and ask the user.""",
    ),


    # ── Tool misuse (wrong tool for the job) ──────────────────────────────────
    (
        "TOOL_MISUSE",
        [
            r"tool.*not.*appropriate",
            r"wrong.*tool",
            r"should use.*instead",
            r"tool.*cannot.*perform",
            r"this tool does not support",
            r"not designed.*for",
            r"incorrect tool",
        ],
        """The chosen tool cannot perform the requested operation.
  Retry steps:
  1. Identify what the operation requires (read, write, search, execute, network call, etc.).
  2. Use list_tools() or request_tools(capability="<description>") to discover the correct tool.
  3. grep_search(pattern="<tool_keyword>", path="core/tools/") to find tools by name.
  4. Retry the operation with the appropriate tool.""",
    ),

    # ── Bad parameters / type error ───────────────────────────────────────────
    (
        "BAD_PARAMETERS",
        [
            r"assertionerror",
            r"valueerror",
            r"typeerror",
            r"invalid.*parameter",
            r"unexpected.*keyword",
            r"takes \d+ positional argument",
            r"required.*argument.*missing",
            r"unexpected.*argument",
        ],
        """Invalid or wrong-type parameters were passed to the tool.
  Retry steps:
  1. Re-read the tool's parameter schema — check required names, types (string/int/bool/list/dict), and defaults.
  2. For TypeErrors: confirm types with run_python("print(type(<value>))") before passing.
  3. For unexpected keyword argument: remove the unknown parameter and retry.
  4. For missing required arguments: identify which parameter is missing from the schema.
  5. Retry with corrected parameter types and names.""",
    ),
]


# ── Pre-compiled pattern cache — avoids re.compile() overhead on every call ──
# Each entry: (tag, [compiled_regex, ...], hint_text)
_COMPILED_CATEGORIES: list = [
    (tag, [_re.compile(p, _re.IGNORECASE) for p in patterns], hint)
    for tag, patterns, hint in _ERROR_CATEGORIES
]

# ── Retry policy frozensets ───────────────────────────────────────────────────
# RETRYABLE: the same goal can succeed with different args or after waiting.
# TERMINAL:  the executor must stop retrying this path and switch strategy.
RETRYABLE_ERRORS: frozenset = frozenset({
    "PATCH_STRING_NOT_FOUND", "PATCH_AMBIGUOUS", "TIMEOUT", "NETWORK_ERROR",
    "RATE_LIMIT", "DOWNLOAD_ERROR", "DATABASE_CONNECTION", "REDIS_ERROR",
    "SEARCH_NO_RESULTS", "TEST_NOT_FOUND", "TEST_ASSERTION_FAILED",
    "SERVICE_NOT_RUNNING", "MEMORY_ERROR", "GIT_DIRTY_STATE",
    "GIT_REMOTE_REJECTED", "GIT_MERGE_CONFLICT", "HTTP_ERROR",
    "ENCODING_ERROR", "CONCURRENCY_ERROR", "LARGE_FILE_BATCHED",
    "MODULE_NOT_FOUND", "COMMAND_NOT_FOUND", "PYTHON_SYNTAX_ERROR",
    "RUNTIME_ERROR", "GENERATED_CODE_INVALID", "LINT_ERROR",
    "DATABASE_QUERY_ERROR", "UNCLASSIFIED_ERROR",
})
TERMINAL_ERRORS: frozenset = frozenset({
    "FILE_NOT_FOUND", "CREDENTIAL", "BAD_PARAMETERS", "GIT_NOT_INITIALIZED",
    "WRITE_PERMISSION", "SYSTEM_PERMISSION", "PATCH_NOOP",
    "TRUNCATION_GUARD", "TOOL_MISUSE", "FILE_EXISTS",
})

# ── Compressed short hints — 1-line summary for iteration-prompt injection ────
_SHORT_HINTS: dict = {
    "PATCH_STRING_NOT_FOUND":  "read_file target section → copy exact text → retry patch_file",
    "PATCH_AMBIGUOUS":         "read_file broader context → extend old_string with 3-5 unique lines → retry",
    "PATCH_NOOP":              "File already has this content → read_file to verify → proceed to tests",
    "TRUNCATION_GUARD":        "Use patch_file (targeted) not write_file — it changes only the specific section",
    "FILE_NOT_FOUND":          "grep_search to locate correct path → list_directory to verify → retry",
    "WRITE_PERMISSION":        "Write to store/outputs/<id>/ or /tmp/ → or chmod u+w the file",
    "FILE_EXISTS":             "read_file the existing file → patch_file or write_file(mode='write')",
    "DIR_NOT_EMPTY":           "list_directory to see contents → delete contents first → retry",
    "LARGE_FILE_BATCHED":      "read_file(start_line=<next>, end_line=<next+499>) for the next batch",
    "MODULE_NOT_FOUND":        "pip install <pkg> → sys.path.insert(0,'<root>') → retry",
    "COMMAND_NOT_FOUND":       "which <cmd> → python3 -m <module> if Python CLI → brew/pip install",
    "PYTHON_SYNTAX_ERROR":     "Traceback line → fix indent/brackets/colons → re-run",
    "TIMEOUT":                 "Reduce scope (rows/range/size) → timeout 120 flag → check service health",
    "RESOURCE_EXHAUSTION":     "df -h && free -h → process in smaller chunks → retry",
    "RUNTIME_ERROR":           "Read traceback → print(type(obj), dir(obj)) → add defensive checks → retry",
    "TEST_NOT_FOUND":          "pytest '<file>' --collect-only → single-quote path → check imports",
    "TEST_ASSERTION_FAILED":   "Read failure → read_file source → fix source or test → re-run",
    "PERFORMANCE_REGRESSION":  "cProfile slow function → patch_file optimization → re-benchmark",
    "SEARCH_NO_RESULTS":       "Broaden pattern → try semantic_search → check search path",
    "SEARCH_INVALID_REGEX":    "Set is_regex=False → escape special chars → test re.compile()",
    "DATABASE_CONNECTION":     "Resolve configured host/port → pg_isready -h <host> -p <port> → lsof for other instances → start only if nothing listens → retry",
    "DATABASE_QUERY_ERROR":    "List tables → fetch schema → fix SQL → retry",
    "REDIS_ERROR":             "redis-cli ping → start redis → check REDIS_URL → retry",
    "HTTP_ERROR":              "404=wrong URL · 400=bad body · 5xx=server error → fix → retry",
    "NETWORK_ERROR":           "curl -s --max-time 5 <url> → lsof -i :<port> → check DNS → retry",
    "RATE_LIMIT":              "Wait 60s → gh api rate_limit → serialize concurrent calls",
    "DOWNLOAD_ERROR":          "Retry → curl -L as fallback → df -h for disk space",
    "CREDENTIAL":              "gh auth token → ~/.config/gh/hosts.yml → grep .env → Keychain",
    "GENERATED_CODE_INVALID":  "ast.parse to validate → read_file error line → patch_file fix",
    "LINT_ERROR":              "Read linter output line by line → patch_file each violation → re-run",
    "SERVICE_NOT_RUNNING":     "brew services list → start service → tail -50 service.log",
    "METRICS_UNAVAILABLE":     "Check endpoint health → grep config for metrics setup",
    "LOG_NOT_FOUND":           "list_directory logs/ → find . -name '*.log' → grep_search",
    "MEMORY_ERROR":            "Check memory agent → resolve configured host/port → pg_isready -h <host> -p <port> → retry",
    "PARSE_ERROR":             "print(repr(raw[:500])) → check truncation → json.loads() fallback",
    "GIT_NOT_INITIALIZED":     "find .git dir → git init if needed → retry with correct root",
    "GIT_DIRTY_STATE":         "git status → git stash → retry → git stash pop",
    "GIT_REMOTE_REJECTED":     "git pull --rebase → resolve conflicts → git push",
    "GIT_MERGE_CONFLICT":      "git diff --name-only -U → read_file conflict → patch_file → git add → continue",
    "SLACK_CHANNEL_NOT_FOUND": "slack_list_channels() → use channel ID not name → retry",
    "SLACK_MESSAGE_TOO_LONG":  "Split into parts or upload as file → send separately",
    "ENCODING_ERROR":          "open(encoding='latin-1') or errors='replace' → inspect raw bytes",
    "CONCURRENCY_ERROR":       "nest_asyncio.apply() → serialize access → add lock timeouts",
    "SYSTEM_PERMISSION":       "ls -la → use writable path → document if root required",
    "BAD_PARAMETERS":          "Re-read tool schema → fix types/names → remove unknown params → retry",
    "TOOL_MISUSE":             "list_tools() or request_tools() → identify correct tool → retry with right tool",
    "UNCLASSIFIED_ERROR":      "Explain WHY it failed in one sentence → try different args → try alternative tool",
}


@dataclass
class ToolErrorInfo:
    """Structured error object returned by _enrich_tool_error.

    Replaces raw enriched-string returns so executors can reason over error state
    programmatically without parsing free-form text.

    Fields:
        status         — always "error"
        tool           — name of the failing tool
        error_category — matched tag (e.g. PATCH_STRING_NOT_FOUND) or UNCLASSIFIED_ERROR
        message        — original raw error string
        retryable      — True if the same goal may succeed with different args/approach
        recovery_hint  — full numbered steps (verbose, for logs and first-occurrence hints)
        short_hint     — compressed 1-liner (for repeated-failure context injection)
    """
    status: str = "error"
    tool: str = ""
    error_category: str = "UNCLASSIFIED_ERROR"
    message: str = ""
    retryable: bool = True
    recovery_hint: str = ""
    short_hint: str = ""

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "tool": self.tool,
            "error_category": self.error_category,
            "message": self.message,
            "retryable": self.retryable,
            "recovery_hint": self.recovery_hint,
            "short_hint": self.short_hint,
        }

    def to_prompt_str(self, verbose: bool = True) -> str:
        """String suitable for LLM injection.

        verbose=True  → full recovery_hint  (first failure / debug logs)
        verbose=False → compressed short_hint (repeated-failure injection)
        """
        retryable_label = "RETRYABLE" if self.retryable else "TERMINAL — do not retry this approach"
        hint_body = (self.recovery_hint if verbose else self.short_hint).strip()
        return (
            f"{self.message}\n\n"
            f"[RECOVERY_HINT:{self.error_category} for '{self.tool}']\n"
            f"retryable: {retryable_label}\n"
            f"{hint_body}"
        )

    def __str__(self) -> str:
        return self.to_prompt_str(verbose=True)


def _enrich_tool_error(error_str: str, tool_name: str) -> "ToolErrorInfo":
    """Classify *error_str* against pre-compiled failure patterns.

    Returns a ToolErrorInfo with:
      - error_category  — matched tag or UNCLASSIFIED_ERROR
      - retryable       — whether the executor should attempt a different approach
      - recovery_hint   — full numbered steps (for first-occurrence / debug)
      - short_hint      — 1-line summary (for repeated-failure injection)

    Uses _COMPILED_CATEGORIES (pre-compiled at module load) for performance.
    Falls back to UNCLASSIFIED_ERROR with a forced-reflection prompt (point 9).
    """
    low = error_str.lower()
    for category, compiled_patterns, hint in _COMPILED_CATEGORIES:
        for rx in compiled_patterns:
            if rx.search(low):
                return ToolErrorInfo(
                    status="error",
                    tool=tool_name,
                    error_category=category,
                    message=error_str,
                    retryable=(category in RETRYABLE_ERRORS),
                    recovery_hint=hint.strip(),
                    short_hint=_SHORT_HINTS.get(category, hint.strip()[:120]),
                )
    # No category matched → UNCLASSIFIED_ERROR (point 9: forced reflection before retry)
    _reflection_hint = (
        "Before retrying, state in ONE sentence why this tool call failed.\n"
        "Then choose a different approach — different arguments, different tool, or reduced scope.\n"
        "Do NOT repeat the exact same call."
    )
    return ToolErrorInfo(
        status="error",
        tool=tool_name,
        error_category="UNCLASSIFIED_ERROR",
        message=error_str,
        retryable=True,
        recovery_hint=(
            "The error did not match a known category. Diagnosis steps:\n"
            "  1. Read the full exception message — identify the specific line and failure type.\n"
            "  2. Explain in one sentence WHY the tool failed before retrying.\n"
            "  3. Try a minimal version of the operation (fewer parameters, smaller scope).\n"
            "  4. Verify all paths/IDs/names exist: use grep_search or list_directory.\n"
            "  5. Check the tool's parameter schema — confirm required fields and types.\n"
            "  6. If the error is in external infrastructure (DB, API, file), diagnose that first.\n"
            "  IMPORTANT: Do NOT retry with the exact same arguments."
        ),
        short_hint=_reflection_hint,
    )


async def _record_safety_outcome_async(action_id: str, success: bool, error: Optional[str] = None):
    """Close a safety assessment with the real outcome. Fire-and-forget."""
    try:
        from core.security.safety_framework import get_safety_framework
        await get_safety_framework().record_outcome(action_id, success, error)
    except Exception as e:
        logger.debug(f"safety outcome not recorded for {action_id}: {e}")


async def _persist_tool_execution_async(entry: Dict[str, Any]) -> None:
    """Persist ONE tool execution outcome, success or failure alike.

    The symmetric counterpart to _persist_tool_error_async. Errors were durable
    and successes were not, which made the stored history a survivorship sample:
    every success rate computed from it was 0, and a tool that works perfectly
    was indistinguishable from one that always fails.

    Fire-and-forget, like the error path -- recording an outcome must not delay
    returning it to the caller.
    """
    try:
        from core.database import get_database_manager
        db = get_database_manager()
        if db is None or not getattr(db, 'initialized', False):
            return

        # Derived from the execution, so a retried write cannot double-count and
        # the same call is one row however many times it is persisted.
        digest = hashlib.sha256(
            "\x1f".join((
                str(entry.get("tool_name")), str(entry.get("timestamp")),
                str(entry.get("session_id")), str(entry.get("success")),
            )).encode()
        ).hexdigest()[:32]

        await db.execute_query(
            """
            INSERT INTO unified.tool_execution_events
                (execution_id, tool_name, category, safety_level, success,
                 error, execution_time, user_id, session_id, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW())
            ON CONFLICT (execution_id) DO NOTHING
            """,
            (
                f"exec_{digest}",
                str(entry.get("tool_name"))[:255],
                str(entry.get("category"))[:64] if entry.get("category") else None,
                str(entry.get("safety_level"))[:32] if entry.get("safety_level") else None,
                bool(entry.get("success")),
                (str(entry.get("error"))[:2000] if entry.get("error") else None),
                float(entry.get("execution_time") or 0.0),
                str(entry.get("user_id"))[:255] if entry.get("user_id") else None,
                str(entry.get("session_id"))[:255] if entry.get("session_id") else None,
            ),
            commit=True,
        )
    except Exception as e:
        # Never let recording an outcome break the execution it describes.
        logger.debug("Tool execution outcome not persisted: %s", e)


async def _persist_tool_error_async(
    tool_error: "ToolErrorInfo",
    task_id: Optional[str] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> None:
    """Persist a ToolErrorInfo record to the tool_error_events PostgreSQL table.
    Designed for fire-and-forget via asyncio.create_task().
    """
    try:
        from core.database import get_database_manager
        db = get_database_manager()
        if db is None or not getattr(db, 'initialized', False):
            return
        await db.execute_query(
            """
            INSERT INTO tool_error_events
                (task_id, session_id, user_id, tool_name, error_category,
                 retryable, message, short_hint, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
            """,
            (
                task_id,
                session_id,
                user_id,
                tool_error.tool,
                tool_error.error_category,
                tool_error.retryable,
                (tool_error.message or "")[:2000],
                (tool_error.short_hint or "")[:500],
            ),
        )
    except Exception as _pe:
        logger.debug(f"[tool_error_persist] Failed: {_pe}")

    # ALSO to the canonical record. `tool_error_events` holds the tool-specific
    # detail and only the tool layer reads it -- 1,441 rows that the recovery
    # manager, the coordinator's recurring-failure check and the improvement
    # cycle have never been able to see. A non-retryable tool error is a
    # component failing, and those are the systems whose job is to notice.
    try:
        if not tool_error.retryable:
            from core.observability import failure_record

            await failure_record.report(
                component=f"tools.{tool_error.tool}",
                failure_type="tool_error",
                description=(tool_error.message or "tool execution failed")[:2000],
                source_system="tool_registry",
                severity="medium",
                metadata={"error_category": tool_error.error_category,
                          "retryable": bool(tool_error.retryable),
                          "hint": (tool_error.short_hint or "")[:500],
                          "task_id": task_id, "session_id": session_id},
            )
    except Exception as _fe:
        logger.debug(f"[tool_error_persist] canonical record failed: {_fe}")


# Keep a reference to the credential hint for callers that import it directly
_CREDENTIAL_RECOVERY_HINT = next(
    hint for tag, _, hint in _ERROR_CATEGORIES if tag == "CREDENTIAL"
)
_CREDENTIAL_SIGNALS = next(
    patterns for tag, patterns, _ in _ERROR_CATEGORIES if tag == "CREDENTIAL"
)

# Capability-based discovery system (NEW)
from core.tools.capabilities import (
    Capability,
    CapabilityMetadata,
    ToolCapabilityProfile,
    RiskLevel,
    infer_capability_from_task
)


logger = logging.getLogger(__name__)


class ToolCategory(Enum):
    """Tool categories"""
    FILESYSTEM = "filesystem"
    EXECUTION = "execution"
    SEARCH = "search"
    MACOS = "macos"
    NETWORK = "network"
    DATABASE = "database"
    SYSTEM = "system"
    COMMUNICATION = "communication"
    MONITORING = "monitoring"
    AI_ML = "ai_ml"
    DATA_PROCESSING = "data_processing"
    CODE_GENERATION = "code_generation"
    TESTING = "testing"
    DOCUMENTATION = "documentation"
    SECURITY = "security"
    REASONING = "reasoning"
    # 12 learning tools were registering category="learning" as a raw
    # string because this member did not exist, so ToolCategory stopped
    # being the single authority for categories and get_usage_stats()
    # crashed on `tool.category.value` for every one of them.
    LEARNING = "learning"


class ToolSafety(Enum):
    """Safety levels for tools - for monitoring/logging purposes only"""
    SAFE = "safe"  # Read-only, no side effects
    MODERATE = "moderate"  # Can modify files
    DANGEROUS = "dangerous"  # Can execute code
    CRITICAL = "critical"  # System-level changes
    HIGH_RISK = "high_risk"  # Repository-wide or highly destructive operations

    # NOTE: No approval gates - Singleton has full autonomy
    # Constitutional monitoring watches for drift, doesn't block actions


@dataclass
class ToolParameter:
    """Tool parameter specification"""
    name: str
    type: str  # "string", "number", "boolean", "array", "object"
    description: str
    required: bool = True
    default: Any = None
    enum: Optional[List[Any]] = None
    min_value: Optional[Union[int, float]] = None
    max_value: Optional[Union[int, float]] = None
    pattern: Optional[str] = None  # Regex for validation


@dataclass
class ToolResult:
    """Result from tool execution"""
    success: bool
    output: Any
    error: Optional[str] = None
    execution_time: float = 0.0
    tokens_used: int = 0
    tool_name: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    requires_approval: bool = False
    approval_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class Tool(ABC):
    """
    Base class for all tools.

    Tools provide specific capabilities to the Singleton:
    - Reading/writing files
    - Executing code
    - Searching codebase
    - System operations
    - macOS integrations

    All tools are:
    1. Validated before execution
    2. Logged for constitutional oversight
    3. Subject to safety constraints
    4. Tracked for learning
    5. Declared by capabilities they provide (for semantic discovery)
    """

    def __init__(self):
        # Only set defaults if not already defined as class attributes
        if not hasattr(self, 'name'):
            self.name: str = self.__class__.__name__.replace('Tool', '').lower()
        if not hasattr(self, 'description'):
            self.description: str = ""
        if not hasattr(self, 'category'):
            self.category: ToolCategory = ToolCategory.SYSTEM
        if not hasattr(self, 'safety_level'):
            self.safety_level: ToolSafety = ToolSafety.SAFE
        if not hasattr(self, 'parameters'):
            self.parameters: List[ToolParameter] = []

        # What running this tool DOES, as (action_class, irreversibility).
        #
        # Declared here, next to the tool, rather than in a lookup table
        # elsewhere: a side table drifts the moment a tool changes, and the
        # tool is the only place that knows what it does. Strings rather than
        # the ActionClass enum so core.tools does not depend on core.safety.
        #
        # None means UNDECLARED, which is not the same as harmless --
        # classify_action falls back to a deliberately calibrated default and
        # the coverage test reports it, so an unmapped tool is visible rather
        # than silently assumed safe.
        #
        # Omit it for tools whose consequence depends on their arguments
        # (shells, query runners): those are read from the payload instead,
        # and a static declaration would be wrong for half their invocations.
        if not hasattr(self, 'consequence'):
            self.consequence: Optional[Tuple[str, str]] = None

        self.usage_count: int = 0
        self.last_used: Optional[datetime] = None

        # Capability-based discovery (NEW)
        # Tools declare what they CAN do, not just what they ARE
        if not hasattr(self, 'capability_profile'):
            self.capability_profile: Optional['ToolCapabilityProfile'] = None

        # NOTE: No approval system - Singleton has full autonomy
        # Tools are logged for constitutional monitoring, not blocked
        
    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """
        Execute the tool with given parameters.
        
        Args:
            **kwargs: Tool-specific parameters
            
        Returns:
            ToolResult with success status and output
        """
        pass
    
    def validate_parameters(self, params: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """
        Validate parameters before execution.

        Supports both List[ToolParameter] and raw JSON Schema dict formats.

        Returns:
            (is_valid, error_message)
        """
        # ── Dict-format (JSON Schema) parameters ─────────────────────────────
        # Some tools (e.g. chaos tools) declare parameters as a raw JSON Schema
        # dict {"type": "object", "properties": {...}, "required": [...]}
        # rather than a List[ToolParameter]. Handle that format here.
        if isinstance(self.parameters, dict):
            props = self.parameters.get("properties", {})
            required_names: List[str] = self.parameters.get("required", [])
            valid_names_dict = set(props.keys())

            unknown = [k for k in params if k not in valid_names_dict]
            if unknown:
                schema_summary = ", ".join(
                    f"{k} ({'required' if k in required_names else 'optional'}, type={props[k].get('type','?')})"
                    for k in props
                ) or "(no parameters)"
                return False, (
                    f"Unknown parameter(s): {unknown}. "
                    f"Valid parameters for '{self.name}': [{schema_summary}]. "
                    f"Fix the parameter name(s) and retry."
                )

            for req in required_names:
                if req not in params:
                    schema_summary = ", ".join(
                        f"{k} ({'required' if k in required_names else 'optional'}, type={props[k].get('type','?')})"
                        for k in props
                    ) or "(no parameters)"
                    return False, (
                        f"Missing required parameter: '{req}'. "
                        f"Full schema for '{self.name}': [{schema_summary}]."
                    )

            # Basic type validation against the JSON Schema properties
            for pname, value in params.items():
                pdef = props.get(pname, {})
                ptype = pdef.get("type")
                if ptype == "string" and not isinstance(value, str):
                    return False, f"Parameter '{pname}' must be a string, got {type(value).__name__}"
                elif ptype in ("number", "integer") and not isinstance(value, (int, float)):
                    return False, f"Parameter '{pname}' must be a number, got {type(value).__name__}"
                elif ptype == "boolean" and not isinstance(value, bool):
                    return False, f"Parameter '{pname}' must be a boolean, got {type(value).__name__}"
                elif ptype == "array" and not isinstance(value, list):
                    return False, f"Parameter '{pname}' must be an array, got {type(value).__name__}"
                elif ptype == "object" and not isinstance(value, dict):
                    return False, f"Parameter '{pname}' must be an object, got {type(value).__name__}"
                # Enum validation
                if "enum" in pdef and value not in pdef["enum"]:
                    return False, f"Parameter '{pname}' must be one of: {pdef['enum']}"
                # Range validation
                if "minimum" in pdef and isinstance(value, (int, float)):
                    if value < pdef["minimum"]:
                        return False, f"Parameter '{pname}' must be >= {pdef['minimum']}"
                if "maximum" in pdef and isinstance(value, (int, float)):
                    if value > pdef["maximum"]:
                        return False, f"Parameter '{pname}' must be <= {pdef['maximum']}"

            return True, None

        # ── Unknown-parameter guard (List[ToolParameter] format) ──────────────
        # Catch typos/wrong names early and emit the full schema so the model
        # can correct on the very next call without hunting for the schema.
        valid_names = {p.name for p in self.parameters}
        unknown = [k for k in params if k not in valid_names]
        if unknown:
            schema_summary = ", ".join(
                f"{p.name} ({'required' if p.required else f'optional, default={p.default}'}: {p.type})"
                for p in self.parameters
            ) or "(no parameters)"
            return False, (
                f"Unknown parameter(s): {unknown}. "
                f"Valid parameters for '{self.name}': [{schema_summary}]. "
                f"Fix the parameter name(s) and retry."
            )

        for param in self.parameters:
            if param.required and param.name not in params:
                schema_summary = ", ".join(
                    f"{p.name} ({'required' if p.required else f'optional, default={p.default}'}: {p.type})"
                    for p in self.parameters
                ) or "(no parameters)"
                return False, (
                    f"Missing required parameter: '{param.name}'. "
                    f"Full schema for '{self.name}': [{schema_summary}]."
                )
            
            if param.name in params:
                value = params[param.name]
                
                # Type validation with actionable error messages
                if param.type == "string" and not isinstance(value, str):
                    return False, f"Parameter {param.name} must be a string, got {type(value).__name__}"
                elif param.type == "number" and not isinstance(value, (int, float)):
                    return False, f"Parameter {param.name} must be a number, got {type(value).__name__}"
                elif param.type == "boolean" and not isinstance(value, bool):
                    return False, f"Parameter {param.name} must be a boolean, got {type(value).__name__}"
                elif param.type == "array" and not isinstance(value, list):
                    # Provide helpful guidance for common mistakes
                    if isinstance(value, str):
                        return False, (
                            f"Parameter {param.name} must be an array, got string. "
                            f"Use run_code tool to parse data into an array first, "
                            f"e.g., [1.5, 2.3, 3.1] not \"[1.5, 2.3, 3.1]\""
                        )
                    return False, f"Parameter {param.name} must be an array, got {type(value).__name__}"
                elif param.type == "object" and not isinstance(value, dict):
                    return False, f"Parameter {param.name} must be an object, got {type(value).__name__}"
                
                # Enum validation
                if param.enum and value not in param.enum:
                    return False, f"Parameter {param.name} must be one of: {param.enum}"
                
                # Range validation
                if param.min_value is not None and isinstance(value, (int, float)):
                    if value < param.min_value:
                        return False, f"Parameter {param.name} must be >= {param.min_value}"
                if param.max_value is not None and isinstance(value, (int, float)):
                    if value > param.max_value:
                        return False, f"Parameter {param.name} must be <= {param.max_value}"
        
        return True, None
    
    def to_json_schema(self) -> Dict[str, Any]:
        """
        Convert tool to JSON schema for LLM function calling.

        Returns schema compatible with OpenAI/Anthropic function calling format.
        Supports both List[ToolParameter] and raw JSON Schema dict formats.
        """
        # Some tools (e.g. chaos tools) define parameters as a raw JSON Schema dict
        if isinstance(self.parameters, dict):
            return {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters
            }

        properties = {}
        required = []

        for param in self.parameters:
            prop = {
                "type": param.type,
                "description": param.description
            }
            
            if param.enum:
                prop["enum"] = param.enum
            if param.min_value is not None:
                prop["minimum"] = param.min_value
            if param.max_value is not None:
                prop["maximum"] = param.max_value
            if param.pattern:
                prop["pattern"] = param.pattern
            if param.default is not None:
                prop["default"] = param.default
            
            properties[param.name] = prop
            
            if param.required:
                required.append(param.name)
        
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required
            }
        }
    
    def to_openai_schema(self) -> Dict[str, Any]:
        """
        Convert tool to an OpenAI-compatible function schema for native tool calling.

        This is the format expected by create_chat_completion(tools=[...]):
        {
            "type": "function",
            "function": {
                "name": "...",
                "description": "...",
                "parameters": { "type": "object", "properties": {...}, "required": [...] }
            }
        }

        Supports both List[ToolParameter] and raw JSON Schema dict parameter formats.
        """
        # Some tools define parameters as a raw JSON Schema dict already
        if isinstance(self.parameters, dict):
            params_schema = self.parameters
        else:
            properties: Dict[str, Any] = {}
            required: List[str] = []

            for param in self.parameters:
                prop: Dict[str, Any] = {
                    "type": param.type,
                    "description": param.description,
                }
                if param.enum:
                    prop["enum"] = param.enum
                if param.min_value is not None:
                    prop["minimum"] = param.min_value
                if param.max_value is not None:
                    prop["maximum"] = param.max_value
                if param.pattern:
                    prop["pattern"] = param.pattern
                if param.default is not None:
                    prop["default"] = param.default
                # Arrays need an items type; default to string if unspecified
                if param.type == "array" and "items" not in prop:
                    prop["items"] = {"type": "string"}

                properties[param.name] = prop
                if param.required:
                    required.append(param.name)

            params_schema = {
                "type": "object",
                "properties": properties,
                "required": required,
            }

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": params_schema,
            },
        }

    async def _track_usage(self):
        """Track tool usage for learning"""
        self.usage_count += 1
        self.last_used = datetime.now()

    # ========== CAPABILITY-BASED METHODS (NEW) ==========

    def provides_capability(self, capability: Capability) -> bool:
        """Check if this tool provides a specific capability"""
        if not self.capability_profile:
            return False
        return self.capability_profile.provides_capability(capability)

    def get_capabilities(self) -> Set[Capability]:
        """Get set of all capabilities this tool provides"""
        if not self.capability_profile:
            return set()
        return self.capability_profile.get_capability_names()

    def matches_context(self, capability: Capability, context: Dict[str, Any]) -> bool:
        """
        Check if this tool's capability implementation matches the given context.

        Example:
            ReadFileTool.matches_context(
                Capability.READ_DATA,
                {"data_source": "file", "file_path": "/var/log/system.log"}
            ) → True
        """
        if not self.capability_profile:
            return False
        return self.capability_profile.matches_context(capability, context)


class ToolRegistry:
    """
    Central registry for all available tools with lazy loading and capability-based discovery.

    Responsibilities:
    - Register tool factories (lazy loading - tools loaded on first use)
    - Capability-based discovery (find tools by what they CAN do)
    - Validate tool calls
    - Execute tools safely
    - Track usage
    - Constitutional oversight

    Architecture:
    - Tools are registered as factories (Callable that returns Tool instance)
    - Only loaded when first accessed (solves slow startup problem)
    - Capability index maps capabilities → tool names for fast lookup
    - Context-aware selection picks best tool for specific use case
    """

    def __init__(self):
        # Legacy: Eagerly loaded tools (backwards compatibility)
        self.tools: Dict[str, Tool] = {}

        # NEW: Lazy loading system
        self.tool_factories: Dict[str, Callable[[], Tool]] = {}  # tool_name → factory
        self.loaded_tools: Dict[str, Tool] = {}                   # tool_name → loaded instance

        # NEW: Capability-based discovery
        self.capability_index: Dict[Capability, List[str]] = {}   # capability → [tool_names]

        # NEW: Category index for lazy tools (register_factory populates this)
        self.category_index: Dict[str, List[str]] = {}            # category_str → [tool_names]

        # Tracking and monitoring
        self.usage_log: List[Dict[str, Any]] = []
        self.constitutional_monitor: Optional[Any] = None

        # NO APPROVAL SYSTEM: Singleton has full autonomy to use tools
        # Constitutional monitoring observes and ensures alignment,
        # but does NOT block Singleton's actions
        
    def register(self, tool: Tool):
        """
        Register a tool (backwards compatibility - eager loading).

        For new code, prefer register_factory() for lazy loading.
        """
        self.tools[tool.name] = tool

        # Also register in lazy loading system for consistency
        self.loaded_tools[tool.name] = tool

        # Build capability index if tool has capability profile
        if hasattr(tool, 'capability_profile') and tool.capability_profile:
            for capability in tool.capability_profile.get_capability_names():
                if capability not in self.capability_index:
                    self.capability_index[capability] = []
                if tool.name not in self.capability_index[capability]:
                    self.capability_index[capability].append(tool.name)

        # Handle both enum and string values for category and safety_level
        if hasattr(tool, 'category') and tool.category:
            category_str = tool.category.value if hasattr(tool.category, 'value') else str(tool.category)
        else:
            category_str = "unknown"

        if hasattr(tool, 'safety_level') and tool.safety_level:
            safety_str = tool.safety_level.value if hasattr(tool.safety_level, 'value') else str(tool.safety_level)
        else:
            safety_str = "unknown"

        logger.info(f"🔧 Registered tool: {tool.name} ({category_str}, {safety_str})")

    def register_factory(
        self,
        tool_name: str,
        factory: Callable[[], Tool],
        capabilities: Optional[List[Capability]] = None,
        category: Optional[ToolCategory] = None,
        safety_level: Optional[ToolSafety] = None
    ):
        """
        Register a tool factory for lazy loading (NEW - preferred method).

        Tools are not instantiated until first use, solving slow startup problem.

        Args:
            tool_name: Unique name for the tool
            factory: Callable that returns Tool instance when called
            capabilities: List of capabilities this tool provides
            category: Tool category (for metadata)
            safety_level: Safety level (for metadata)

        Example:
            registry.register_factory(
                "read_file",
                lambda: ReadFileTool(),
                capabilities=[Capability.READ_DATA],
                category=ToolCategory.FILESYSTEM,
                safety_level=ToolSafety.SAFE
            )
        """
        self.tool_factories[tool_name] = factory

        # Build capability index
        if capabilities:
            for capability in capabilities:
                if capability not in self.capability_index:
                    self.capability_index[capability] = []
                if tool_name not in self.capability_index[capability]:
                    self.capability_index[capability].append(tool_name)

        # Build category index (was previously discarded — caused 0-tools bug)
        if category:
            cat_str = category.value if hasattr(category, 'value') else str(category)
            if cat_str not in self.category_index:
                self.category_index[cat_str] = []
            if tool_name not in self.category_index[cat_str]:
                self.category_index[cat_str].append(tool_name)

        logger.debug(f"📦 Registered factory: {tool_name} (lazy load)")

    @inject_latency("tool_registry", "get_tool", delay_ms=50, jitter_ms=20)
    def get_tool(self, name: str) -> Optional[Tool]:
        """
        Get tool by name with lazy loading support.

        Checks:
        1. Already loaded tools (loaded_tools cache)
        2. Legacy eagerly loaded tools (tools dict)
        3. Tool factories (lazy load on first access)

        Args:
            name: Tool name

        Returns:
            Tool instance or None if not found
        """
        # Check if already loaded (lazy system)
        if name in self.loaded_tools:
            return self.loaded_tools[name]

        # Check legacy eager-loaded tools
        if name in self.tools:
            tool = self.tools[name]
            # Cache in loaded_tools for consistency
            self.loaded_tools[name] = tool
            return tool

        # Lazy load from factory
        if name in self.tool_factories:
            logger.debug(f"⚡ Lazy loading tool: {name}")
            tool = self.tool_factories[name]()
            self.loaded_tools[name] = tool

            # Build capability index from loaded tool
            if hasattr(tool, 'capability_profile') and tool.capability_profile:
                for capability in tool.capability_profile.get_capability_names():
                    if capability not in self.capability_index:
                        self.capability_index[capability] = []
                    if name not in self.capability_index[capability]:
                        self.capability_index[capability].append(name)

            return tool

        return None
    
    def list_tools(self, category: Optional[ToolCategory] = None) -> List[Tool]:
        """
        List all tools, optionally filtered by category.

        NOTE: This only returns eagerly-loaded tools (backwards compatibility).
        For capability-based discovery, prefer find_providers() which supports lazy loading.
        """
        if category:
            return [t for t in self.tools.values() if t.category == category]
        return list(self.tools.values())

    def get_tools_by_category(self, category_str: str) -> List[Tool]:
        """
        Get tools by category string, with lazy loading support.

        Unlike list_tools(), this uses the category_index populated by
        register_factory() and lazy-loads tools on first access.

        Args:
            category_str: Category name (e.g. 'filesystem', 'execution', 'system')

        Returns:
            List of Tool instances in that category
        """
        tool_names = self.category_index.get(category_str, [])
        tools = []
        for name in tool_names:
            tool = self.get_tool(name)  # Handles lazy loading
            if tool:
                tools.append(tool)
        return tools

    def get_tools_schema(self) -> List[Dict[str, Any]]:
        """
        Get OpenAI-compatible JSON schemas for ALL registered tools (for LLM function calling).

        Returns {"type":"function","function":{...}} format for both eagerly-loaded
        tools (self.tools) and lazy-loaded tools (self.tool_factories).
        """
        schemas: List[Dict[str, Any]] = []

        # Eager tools — already loaded
        for tool in self.tools.values():
            try:
                schemas.append(tool.to_openai_schema())
            except Exception as e:
                logger.warning("get_tools_schema: to_openai_schema() failed for %s: %s", tool.name, e)

        # Lazy tools — load on demand (skip any already included above)
        for name in self.tool_factories:
            if name in self.tools:
                continue
            tool = self.get_tool(name)
            if tool is None:
                continue
            try:
                schemas.append(tool.to_openai_schema())
            except Exception as e:
                logger.warning("get_tools_schema: to_openai_schema() failed for lazy %s: %s", name, e)

        return schemas

    # ========== CAPABILITY-BASED DISCOVERY (NEW - PREFERRED) ==========

    def find_providers(
        self,
        capability: Capability,
        context: Optional[Dict[str, Any]] = None,
        load_tools: bool = True
    ) -> List[Tool]:
        """
        Find all tools that provide a specific capability (PREFERRED over list_tools).

        Uses lazy loading - only loads tools that match the requested capability.

        Args:
            capability: The capability to search for
            context: Optional context for filtering (e.g., {"data_source": "file"})
            load_tools: Whether to lazy-load tools (default True)

        Returns:
            List of Tool instances providing this capability

        Example:
            # Find all tools that can read data
            providers = registry.find_providers(Capability.READ_DATA)

            # Find tools that can read data from files specifically
            providers = registry.find_providers(
                Capability.READ_DATA,
                context={"data_source": "file"}
            )
        """
        tool_names = self.capability_index.get(capability, [])

        if not load_tools:
            # Return tool names without loading
            return tool_names

        providers = []
        for tool_name in tool_names:
            tool = self.get_tool(tool_name)
            if not tool:
                continue

            # If context provided, check if tool matches
            if context:
                if tool.matches_context(capability, context):
                    providers.append(tool)
            else:
                providers.append(tool)

        return providers

    def select_best_provider(
        self,
        capability: Capability,
        context: Optional[Dict[str, Any]] = None,
        weights: Optional[Dict[str, float]] = None,
        prefer_low_latency: bool = False,
        prefer_low_cost: bool = False
    ) -> Optional[Tool]:
        """
        Select the best tool for a specific capability given context.

        Uses weighted scoring to pick the most appropriate provider:
        1. Context matching (does tool handle this specific use case?)
        2. Weighted scoring based on priority, reliability, latency, cost
        3. Resource constraints (network, filesystem, database)
        4. Execution characteristics (batch, streaming, idempotent)

        Args:
            capability: The capability needed
            context: Context for selection (e.g., file path, URL, etc.)
            weights: Optional scoring weights (priority, reliability, latency, cost)
            prefer_low_latency: Prioritize fast tools (adjusts weights)
            prefer_low_cost: Prioritize low-cost tools (adjusts weights)

        Returns:
            Best Tool instance or None if no providers

        Example:
            # System picks ReadFileTool over FetchURLTool for file paths
            tool = registry.select_best_provider(
                Capability.READ_DATA,
                context={"data_source": "file", "path": "/var/log/system.log"}
            )

            # Custom weights for optimization
            tool = registry.select_best_provider(
                Capability.READ_DATA,
                context=context,
                weights={"priority": 2.0, "reliability": 1.0, "latency": -0.5, "cost": -0.1}
            )
        """
        providers = self.find_providers(capability, context=context)

        if not providers:
            return None

        if len(providers) == 1:
            return providers[0]

        # Build weights based on preferences
        scoring_weights = weights.copy() if weights else {}

        if prefer_low_latency:
            scoring_weights["latency"] = scoring_weights.get("latency", -0.3) * 2.0

        if prefer_low_cost:
            scoring_weights["cost"] = scoring_weights.get("cost", -0.2) * 2.0

        # Score each provider using capability profile scoring
        scored_providers = []
        for tool in providers:
            if tool.capability_profile:
                score = tool.capability_profile.score_for_context(
                    capability,
                    context or {},
                    weights=scoring_weights if scoring_weights else None
                )
            else:
                # Fallback for tools without capability profiles
                score = 0.0

            scored_providers.append((score, tool))

        # Return highest scoring provider (excluding -inf scores)
        scored_providers = [(s, t) for s, t in scored_providers if s != float('-inf')]
        if not scored_providers:
            return None

        scored_providers.sort(key=lambda x: x[0], reverse=True)
        return scored_providers[0][1]

    def find_capabilities_for_task(
        self,
        task_description: str,
        threshold: float = 1.0,
        return_scores: bool = False
    ) -> Union[Set[Capability], Dict[Capability, float]]:
        """
        Infer needed capabilities from a task description.

        Uses regex pattern matching with confidence scoring as fallback
        when AI doesn't explicitly request capabilities.

        Args:
            task_description: Natural language task description
            threshold: Minimum confidence score to include (default 1.0)
            return_scores: If True, return dict with scores; if False, return set

        Returns:
            Set of capabilities or Dict mapping capabilities to confidence scores

        Example:
            # Get capabilities above threshold
            caps = registry.find_capabilities_for_task(
                "analyze the system logs in /var/log/"
            )
            # → {Capability.READ_DATA, Capability.ANALYZE_CODE}

            # Get capabilities with scores
            caps_with_scores = registry.find_capabilities_for_task(
                "read the file at /var/log/system.log",
                return_scores=True
            )
            # → {Capability.READ_DATA: 8.0}
        """
        scored_capabilities = infer_capability_from_task(task_description, threshold)

        if return_scores:
            return scored_capabilities
        else:
            return set(scored_capabilities.keys())

    def get_tools_by_capabilities(
        self,
        capabilities: List[Capability],
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[Capability, List[Tool]]:
        """
        Get tools for multiple capabilities at once.

        Args:
            capabilities: List of capabilities needed
            context: Optional context for all lookups

        Returns:
            Dict mapping each capability to its providers

        Example:
            tools_map = registry.get_tools_by_capabilities([
                Capability.READ_DATA,
                Capability.ANALYZE_CODE
            ])
            # → {
            #     Capability.READ_DATA: [ReadFileTool, FetchURLTool],
            #     Capability.ANALYZE_CODE: [AnalyzeCodeTool]
            # }
        """
        result = {}
        for capability in capabilities:
            providers = self.find_providers(capability, context=context)
            result[capability] = providers
        return result

    def discover_tools(
        self,
        task_description: str,
        limit: int = 10,
        context: Optional[Dict[str, Any]] = None,
        with_scores: bool = False
    ) -> List[Tool]:
        """
        Find the tools most relevant to a natural-language task.

        This is the discovery entry point callers should use. find_providers()
        answers "who can do capability X" and returns providers in registration
        order; it is not a ranking. This ranks the whole live registry against
        the wording of the task, so the caller can hand a small, relevant tool
        set to an LLM instead of everything the capability graph happens to
        touch.

        Ranking lives in core.tools.tool_discovery, which fuses BM25 over tool
        names and descriptions, sentence embeddings, and this registry's own
        capability graph. The embedding model is loaded on the first call, not
        at import, and if it is unavailable the ranking degrades to lexical +
        capability rather than failing.

        Args:
            task_description: Natural language task
            limit: Maximum tools to return
            context: Optional context; a ranked tool is kept only if the context
                suits at least one capability it declares
            with_scores: Return (tool, relevance) pairs instead of tools. The
                score is uncalibrated across queries; a caller filtering noise
                should threshold relative to the top score, because a task the
                registry has no vocabulary for still fills every slot.

        Returns:
            Tools ordered most-relevant first, or (tool, score) pairs when
            with_scores is set. Never raises: if ranking is unavailable for any
            reason the result is an empty list.
        """
        if not task_description or not str(task_description).strip():
            return []
        try:
            limit = max(0, int(limit))
        except Exception:
            limit = 10
        if limit == 0:
            return []

        try:
            from . import tool_discovery
        except Exception as e:
            # `except` must not turn a wiring defect into an empty result.
            raise_if_structural(e, 'tool_registry.discover_tools')
            logger.warning("discover_tools: ranker unavailable: %s", e)
            return []

        # The catalog is the live registry. Factories are included by name; the
        # ranker only needs name/description/parameters/capabilities, and
        # get_tool() materialises a factory tool on demand.
        #
        # De-duplicated on purpose: a tool that has been instantiated from a
        # factory appears in BOTH self.tools and self.tool_factories, so the
        # naive concatenation lists ~12 of them twice. Duplicates skew the BM25
        # document statistics and let the same Tool object come back twice in
        # one result list.
        # Sorted, not registration order: registration order is an accident of
        # module import order, and it is a tie-break input to the ranker's
        # document statistics, so leaving it unsorted makes results vary between
        # processes for no reason. Sorting also measurably helps here (one query
        # on the 75-query eval recovers from zero recall).
        by_name: Dict[str, Tool] = {}
        for name in sorted(set(list(self.tools) + list(self.tool_factories))):
            try:
                tool = self.get_tool(name)
            except Exception:
                continue
            if tool is None:
                continue
            # Key on the tool's own name: that is what the ranker returns.
            by_name.setdefault(getattr(tool, "name", None) or name, tool)
        if not by_name:
            return []
        catalog: List[Tool] = list(by_name.values())

        # Ask for extra: the context filter below can drop results, and we still
        # want to fill `limit` when it does.
        want = limit if context is None else min(len(catalog), limit * 3)
        try:
            scored = tool_discovery.discover_scored(
                catalog, str(task_description), want)
        except Exception as e:
            # discover_scored() already swallows its own failures; this is belt
            # and braces so the registry's contract holds unconditionally.
            # `except` must not turn a wiring defect into an empty result.
            raise_if_structural(e, 'tool_registry.discover_tools')
            logger.warning("discover_tools: ranking failed: %s", e)
            return []

        # WHAT HISTORY SAYS ABOUT THIS KIND OF TASK.
        #
        # The ranker scores relevance from wording and the capability graph. It
        # has no idea which tools actually WORK for this intent -- that is
        # measured elsewhere, recorded to `tool_usage_history`, and aggregated
        # into per-(intent, category) success rates that nothing on this path
        # read. The system learned which tools work and then chose as though it
        # had not.
        #
        # A damped nudge, not an override: it reorders near-ties and cannot lift
        # an irrelevant tool above a relevant one, because a tool never tried
        # for this intent must not be ranked below one that has merely by virtue
        # of being untried.
        try:
            from core.learning.adaptive_tool_owner import apply_learned_affinity

            def _category_of(tool_name: str) -> str:
                tool = by_name.get(tool_name)
                category = getattr(tool, "category", None)
                return getattr(category, "value", category) or ""

            scored = apply_learned_affinity(
                str(task_description), scored, _category_of)
        except Exception as e:
            # Learning must never be able to empty a tool search.
            raise_if_structural(e, 'tool_registry.discover_tools')
            logger.debug("discover_tools: affinity unavailable: %s", e)

        results: List[Any] = []
        for name, score in scored:
            tool = by_name.get(name)
            if tool is None:
                continue
            if context is not None and not self._matches_any_context(tool, context):
                continue
            results.append((tool, score) if with_scores else tool)
            if len(results) >= limit:
                break
        return results

    @staticmethod
    def _matches_any_context(tool: Tool, context: Dict[str, Any]) -> bool:
        """Keep a tool if any capability it declares is usable in this context.

        find_providers() applies context per capability because it is asked about
        one. Discovery is asked about a task, so a tool survives if the context
        suits it for anything it can do.
        """
        try:
            profile = getattr(tool, "capability_profile", None)
            if profile is None:
                return True
            caps = list(profile.get_capability_names())
            if not caps:
                return True
            return any(tool.matches_context(cap, context) for cap in caps)
        except Exception as e:
            # Fails OPEN deliberately -- discovery must not drop a tool because
            # its own matcher raised. But the swallow was silent, so a broken
            # matcher looked exactly like a tool that matched everything.
            logger.warning(
                "context matching raised for %s (%s: %s); including it rather "
                "than dropping it, but the matcher is broken",
                getattr(tool, "name", "?"), type(e).__name__, e)
            return True

    def get_capability_coverage(self) -> Dict[Capability, int]:
        """
        Get coverage statistics for each capability.

        Returns:
            Dict mapping capabilities to number of providers

        Example:
            coverage = registry.get_capability_coverage()
            # → {
            #     Capability.READ_DATA: 3,  # 3 tools provide this
            #     Capability.WRITE_DATA: 2,
            #     ...
            # }
        """
        return {cap: len(tools) for cap, tools in self.capability_index.items()}

    def resolve_capability_dependencies(
        self,
        capability: Capability,
        context: Optional[Dict[str, Any]] = None
    ) -> List[Capability]:
        """
        Resolve all dependencies for a capability recursively.

        Returns a topologically sorted list of capabilities that must be
        executed before the requested capability.

        Args:
            capability: The capability to resolve dependencies for
            context: Context for provider selection

        Returns:
            List of capabilities in execution order (dependencies first)

        Example:
            # CONDUCT_RESEARCH depends on HTTP_REQUEST, PARSE_HTML, SUMMARIZE_TEXT
            deps = registry.resolve_capability_dependencies(Capability.CONDUCT_RESEARCH)
            # → [Capability.HTTP_REQUEST, Capability.PARSE_HTML,
            #    Capability.SUMMARIZE_TEXT, Capability.CONDUCT_RESEARCH]
        """
        visited = set()
        result = []

        def visit(cap: Capability):
            if cap in visited:
                return
            visited.add(cap)

            # Get best provider for this capability
            tool = self.select_best_provider(cap, context=context)
            if not tool or not tool.capability_profile:
                return

            # Get dependencies for this capability
            dependencies = tool.capability_profile.get_capability_dependencies(cap)

            # Visit dependencies first (depth-first)
            for dep_cap in dependencies:
                visit(dep_cap)

            # Add current capability after dependencies
            result.append(cap)

        visit(capability)
        return result

    def build_execution_plan(
        self,
        capabilities: List[Capability],
        context: Optional[Dict[str, Any]] = None
    ) -> List[tuple[Capability, str]]:
        """
        Build an execution plan for multiple capabilities with dependency resolution.

        Returns a list of (capability, tool_name) tuples in execution order,
        resolving all dependencies automatically.

        Args:
            capabilities: List of capabilities needed
            context: Context for provider selection

        Returns:
            List of (Capability, tool_name) tuples in execution order

        Example:
            plan = registry.build_execution_plan([
                Capability.CONDUCT_RESEARCH,
                Capability.GENERATE_REPORT
            ])
            # → [
            #     (Capability.HTTP_REQUEST, "fetch_url"),
            #     (Capability.PARSE_HTML, "parse_html"),
            #     (Capability.SUMMARIZE_TEXT, "summarize"),
            #     (Capability.CONDUCT_RESEARCH, "research_tool"),
            #     (Capability.GENERATE_REPORT, "report_generator")
            # ]
        """
        all_capabilities = []
        seen = set()

        # Resolve dependencies for each requested capability
        for capability in capabilities:
            resolved = self.resolve_capability_dependencies(capability, context)
            for cap in resolved:
                if cap not in seen:
                    all_capabilities.append(cap)
                    seen.add(cap)

        # Select best provider for each capability
        execution_plan = []
        for capability in all_capabilities:
            tool = self.select_best_provider(capability, context=context)
            if tool:
                execution_plan.append((capability, tool.name))

        return execution_plan

    # ========== END CAPABILITY-BASED DISCOVERY ==========

    @inject_latency("tool_registry", "execute_tool", delay_ms=100, jitter_ms=50)
    @inject_error("tool_registry", "execute_tool", error_type=RuntimeError, error_rate=0.05, error_message="Chaos-injected tool execution error")
    async def execute_tool(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        user_id: Optional[str] = None,
        session_id: Optional[str] = None
    ) -> ToolResult:
        """
        Execute a tool with constitutional oversight (with chaos injection support).

        Args:
            tool_name: Name of tool to execute
            parameters: Tool parameters
            user_id: User requesting tool execution
            session_id: Current session

        Returns:
            ToolResult
        """
        start_time = datetime.now()
        
        # Get tool
        tool = self.get_tool(tool_name)
        if not tool:
            # Provide structured suggestions for LLMs / agents
            suggestions = self._suggest_tools(tool_name)
            return ToolResult(
                success=False,
                output=None,
                error=f"TOOL_NOT_FOUND: Tool not found: {tool_name}",
                tool_name=tool_name,
                parameters=parameters,
                metadata={
                    "error_type": "TOOL_NOT_FOUND",
                    "requested_tool": tool_name,
                    "suggestions": suggestions,
                    "hint": "Use list_tools() or the Torin tools API to discover valid tool names, or pick one of the suggested tools."
                }
            )
        
        # ── Parameter alias remapping ─────────────────────────────────────────
        # Silently remap common model mistakes before validation so the agent
        # doesn't burn an iteration on a trivially wrong parameter name.
        # Format: { tool_name: { wrong_name: correct_name } }
        _PARAM_ALIASES: Dict[str, Dict[str, str]] = {
            "web_search":   {"num_results": "max_results", "n": "max_results",
                             "count": "max_results", "limit": "max_results"},
            "web_fetch":    {"url_path": "url", "link": "url", "uri": "url"},
            "write_file":   {"path": "file_path", "filename": "file_path",
                             "filepath": "file_path"},
            "patch_file":   {"path": "file_path", "filename": "file_path",
                             "filepath": "file_path"},
            "read_file":    {"path": "file_path", "filename": "file_path",
                             "filepath": "file_path"},
        }
        _aliases = _PARAM_ALIASES.get(tool_name, {})
        if _aliases:
            _remapped = {_aliases.get(k, k): v for k, v in parameters.items()}
            if _remapped != parameters:
                _fixed = [f"{old}→{_aliases[old]}" for old in parameters if old in _aliases]
                logger.debug("Parameter alias remap for %s: %s", tool_name, ", ".join(_fixed))
                parameters = _remapped

        # Validate parameters
        is_valid, error = tool.validate_parameters(parameters)
        if not is_valid:
            # Include the full parameter schema so the model can fix on the next call
            _schema_parts = []
            if hasattr(tool, 'parameters') and tool.parameters:
                if isinstance(tool.parameters, dict):
                    # JSON Schema dict format (e.g. chaos tools)
                    _props = tool.parameters.get("properties", {})
                    _required_names = tool.parameters.get("required", [])
                    for _k, _v in _props.items():
                        _req = 'required' if _k in _required_names else 'optional'
                        _desc = f" — {_v.get('description', '')}" if _v.get('description') else ""
                        _schema_parts.append(f"  • {_k} ({_req}, type={_v.get('type', '?')}){_desc}")
                else:
                    # List[ToolParameter] format
                    for p in tool.parameters:
                        _req = 'required' if p.required else f'optional, default={p.default}'
                        _desc = f" — {p.description}" if getattr(p, 'description', None) else ""
                        _schema_parts.append(f"  • {p.name} ({_req}, type={p.type}){_desc}")
            _schema_str = "\n".join(_schema_parts) if _schema_parts else "  (no parameters)"
            _full_error = (
                f"PARAMETER_VALIDATION_FAILED: {error}\n"
                f"Parameter schema for '{tool_name}':\n{_schema_str}"
            )
            return ToolResult(
                success=False,
                output=None,
                error=_full_error,
                tool_name=tool_name,
                parameters=parameters,
                metadata={
                    "error_type": "PARAMETER_VALIDATION",
                    "validation_error": error,
                    "hint": f"Fix parameter names/types. Schema for '{tool_name}':\n{_schema_str}"
                }
            )

        # Phase 0: RecoveryManager gating (THROTTLE/ISOLATE)
        # If the system is in an isolation window, block risky tools.
        # If the system is throttled, add a small delay before executing tools.
        try:
            from core.health.recovery_manager import get_recovery_manager

            rm = get_recovery_manager()
            allowed, reason, throttle_delay_s = rm.tool_execution_policy(
                tool_name=tool_name,
                tool_category=getattr(tool, "category", None),
                tool_safety_level=getattr(tool, "safety_level", None),
            )

            if not allowed:
                return ToolResult(
                    success=False,
                    output=None,
                    error=f"RECOVERY_ISOLATION_BLOCK: {reason or 'Blocked by RecoveryManager isolation policy'}",
                    tool_name=tool_name,
                    parameters=parameters,
                    metadata={
                        "error_type": "RECOVERY_ISOLATION_BLOCK",
                        "reason": reason,
                        "tool_name": tool_name,
                        "tool_category": getattr(tool, "category", None),
                        "tool_safety_level": getattr(tool, "safety_level", None),
                    },
                )

            if throttle_delay_s and throttle_delay_s > 0:
                await asyncio.sleep(float(throttle_delay_s))
        except Exception:
            pass
        
        # Phase 2: Safety evaluation — the single gate.
        #
        # safety_framework composes content safety, parameter validation, code
        # sanitization, ASI risk scoring and the governance trigger table, and
        # persists every evaluation to `safety_assessments`.
        #
        # There is NO approval gate by design. The Singleton retains full tool
        # autonomy — elevated risk is scored, recorded and surfaced as context,
        # not blocked. Only hard invariants (injection, dangerous content
        # patterns, MUST_BLOCK triggers) deny execution.
        from core.security.safety_framework import GovernanceBlockError

        safety_action_id = f"tool_{tool_name}_{uuid.uuid4().hex[:8]}"
        _tool_safety = getattr(tool, "safety_level", None)
        _tool_safety = _tool_safety.value if hasattr(_tool_safety, "value") else _tool_safety

        # WHAT THE TOOL DECLARES ABOUT ITSELF, read from the tool we already
        # hold rather than looked up by name -- the caller knows which object
        # it is about to run, and a name lookup could disagree with it.
        _capability = {}
        _profile = getattr(tool, "capability_profile", None)
        if _profile is not None:
            try:
                _capability = _profile.declared_summary()
            except Exception as _cap_error:      # a profile must never block a call
                logger.debug(f"capability summary unavailable for {tool_name}: {_cap_error}")

        try:
            from core.security.safety_framework import get_safety_framework
            framework = get_safety_framework()
            approved, safety_eval = await framework.evaluate_action(
                action_id=safety_action_id,
                action_type="execute_tool",
                parameters={"tool_name": tool_name, **parameters},
                tool_name=tool_name,
                tool_safety=_tool_safety,
                capability=_capability,
            )
        except GovernanceBlockError as e:
            # Belt-and-braces: evaluate_action returns (False, eval) for blocks,
            # but if any path still raises, a block must never become an allow.
            logger.error(f"SAFETY BLOCK (raised) for {tool_name}: {e}")
            return ToolResult(
                success=False,
                output=None,
                error=f"SAFETY_BLOCKED: {tool_name} denied — {e}",
                tool_name=tool_name,
                parameters=parameters,
                metadata={"error_type": "SAFETY_BLOCKED", "action_id": safety_action_id},
            )
        except Exception as e:
            # A failure to *evaluate* is not a failure of the action. Safety must
            # not take the system down, so execution proceeds — but this is
            # deliberately distinct from the block path above.
            logger.error(f"Safety evaluation error for {tool_name}: {e}")
            approved, safety_eval = True, None

        if not approved and safety_eval is not None:
            logger.error(
                f"SAFETY_BLOCKED: {tool_name} risk={safety_eval.risk_level.value} "
                f"violations={safety_eval.violations_detected}"
            )
            return ToolResult(
                success=False,
                output=None,
                error=(
                    f"SAFETY_BLOCKED: {tool_name} denied — "
                    f"{'; '.join(safety_eval.violations_detected) or 'safety constraint'}"
                ),
                tool_name=tool_name,
                parameters=parameters,
                metadata={
                    "error_type": "SAFETY_BLOCKED",
                    "action_id": safety_action_id,
                    "safety": safety_eval.determination(),
                },
            )

        if safety_eval is not None and safety_eval.monitoring_required:
            logger.info(
                f"ELEVATED RISK: {tool_name} risk={safety_eval.risk_level.value} "
                f"tool_safety={_tool_safety} — executing with monitoring"
            )

        # Tier routing removed: CRITICAL/IMPORTANT no longer divert to an
        # approval queue. safety_framework already scored and recorded this
        # action above; elevated risk executes with monitoring.

        # Execute tool
        try:
            result = await tool.execute(**parameters)
            result.tool_name = tool_name
            result.parameters = parameters
            result.execution_time = (datetime.now() - start_time).total_seconds()

            # HAND THE DETERMINATION BACK. This layer is not a bouncer -- almost
            # everything runs -- so its whole product is a deterministic,
            # model-free reading of what the agent just did, and a reading the
            # agent never receives is not a signal, it is a log line.
            #
            # It WAS a log line: on the allowed path the evaluation went to
            # `logger.info` and to `safety_assessments`, and nothing reached the
            # caller. Only the BLOCKED path put anything on the result, which is
            # the one case where the agent already knows something happened.
            #
            # Attached under its own key rather than merged in, so a tool's own
            # metadata can never collide with it or overwrite it.
            if safety_eval is not None:
                if not isinstance(result.metadata, dict):
                    result.metadata = {}
                result.metadata["safety"] = safety_eval.determination()

            # Close the safety assessment with what actually happened. This is
            # what makes safety_assessments a labelled dataset rather than a log.
            #
            # Awaited deliberately, not fire-and-forget: a create_task here
            # leaves a window where the assessment exists without its outcome,
            # and anything lost in that window biases the dataset toward
            # whatever happened to finish. The write is a single indexed UPDATE.
            if safety_eval is not None:
                await _record_safety_outcome_async(
                    safety_action_id, result.success,
                    None if result.success else (result.error or "tool returned failure")
                )

            # Track usage
            await tool._track_usage()

            # Enrich controlled failures (success=False returned by the tool itself,
            # not unhandled exceptions) with structured ToolErrorInfo.
            if not result.success and result.error:
                _tei = _enrich_tool_error(result.error, tool_name)
                result.error = _tei.to_prompt_str(verbose=True)
                if isinstance(result.metadata, dict):
                    result.metadata.setdefault("error_category", _tei.error_category)
                    result.metadata.setdefault("retryable", _tei.retryable)
                    result.metadata.setdefault("short_hint", _tei.short_hint)
                asyncio.create_task(_persist_tool_error_async(
                    _tei, session_id=session_id, user_id=user_id
                ))

            # Log for constitutional monitoring
            self._log_usage(tool, parameters, result, user_id, session_id)

            # An invoked tool is an OBSERVED operator. `_log_usage` records that
            # it ran; this records what it means -- the tool concept gains real
            # evidence, so a tool that has done work stops being
            # indistinguishable from one that is merely registered.
            #
            # Keyed on the invocation SHAPE, so a tool called in a loop does not
            # out-corroborate every other source in the store, and deduped in
            # process so the hot path pays one round trip per shape.
            await self._observe_invocation(tool, parameters, result.success)

            return result

        except Exception as e:
            logger.error(f"Tool execution error ({tool_name}): {e}", exc_info=True)

            # Send notification for tool failure
            try:
                from core.utils.notification_helpers import notify_tool_failure
                asyncio.create_task(notify_tool_failure(
                    tool_name=tool_name,
                    error=e,
                    parameters=parameters,
                    context=f"User: {user_id}, Session: {session_id}"
                ))
            except Exception as notify_error:
                logger.warning(f"Failed to send tool failure notification: {notify_error}")

            # Return rich, machine-readable error info for agents
            _raw_err = f"EXECUTION_ERROR: {e.__class__.__name__}: {str(e)}"
            # If this is a parameter-name TypeError, inject the schema so the
            # model sees exactly which params are valid on the next attempt.
            if isinstance(e, TypeError) and (
                "unexpected keyword argument" in str(e)
                or "missing" in str(e).lower()
            ):
                _schema_parts = []
                if hasattr(tool, 'parameters') and tool.parameters:
                    for p in tool.parameters:
                        _req = 'required' if p.required else f'optional, default={p.default}'
                        _desc = f" — {p.description}" if getattr(p, 'description', None) else ""
                        _schema_parts.append(f"  • {p.name} ({_req}, type={p.type}){_desc}")
                _schema_str = "\n".join(_schema_parts) if _schema_parts else "  (no parameters)"
                _raw_err += f"\nValid parameters for '{tool_name}':\n{_schema_str}"
            _tei = _enrich_tool_error(_raw_err, tool_name)
            asyncio.create_task(_persist_tool_error_async(
                _tei, session_id=session_id, user_id=user_id
            ))
            return ToolResult(
                success=False,
                output=None,
                error=_tei.to_prompt_str(verbose=True),
                tool_name=tool_name,
                parameters=parameters,
                execution_time=(datetime.now() - start_time).total_seconds(),
                metadata={
                    "error_type": f"TOOL_EXECUTION_ERROR:{_tei.error_category}",
                    "exception_type": e.__class__.__name__,
                    "exception_message": str(e),
                    "error_category": _tei.error_category,
                    "retryable": _tei.retryable,
                    "short_hint": _tei.short_hint,
                    "hint": (
                        f"Error category: {_tei.error_category} "
                        f"({'retryable' if _tei.retryable else 'TERMINAL — do not retry'}). "
                        "Follow the RECOVERY_HINT steps above. "
                        "Do NOT repeat the exact same call — change at least one parameter or approach."
                    )
                }
            )
    
    async def project_capabilities(self) -> Dict[str, int]:
        """Project every registered tool into the concept layer as an operator.

        The concept graph knew about operators Torin had LEARNED and nothing
        about the ones it could already perform, so cross-domain grounding could
        recognise an unfamiliar situation as a learned rule but never as
        something there was already a tool for. A tool's parameter list is a
        precondition list in another notation; projecting it makes the registry
        searchable by the same structural matcher.

        Enumerates eager AND lazy tools by the same union used by discovery --
        `self.tools` alone omits every lazily registered tool, which is most of
        them.
        """
        from core.domain.evidence_producers import submit_tool_capability

        counts = {"tools": 0, "projected": 0, "no_structure": 0,
                  "unreadable_structure": 0, "failed": 0}
        for name in sorted(set(list(self.tools) + list(self.tool_factories))):
            try:
                tool = self.get_tool(name)
            except Exception:
                counts["failed"] += 1
                continue
            if tool is None:
                counts["failed"] += 1
                continue
            counts["tools"] += 1
            try:
                result = await submit_tool_capability(tool)
            except Exception as e:
                counts["failed"] += 1
                logger.warning("tool %s could not be projected: %s: %s",
                               name, type(e).__name__, e)
                continue
            # WHAT "PROJECTED" MEANS. `read_successfully` only reports that no
            # extractor raised -- a tool read cleanly that produced no concepts
            # satisfies it just as well as one that produced eleven. Counting
            # that as projected would report full coverage for a store that
            # gained nothing, which is the silent-negative shape this service
            # exists to avoid elsewhere.
            #
            # So `projected` counts tools that actually landed a concept, and a
            # tool that declares neither parameters nor capabilities is counted
            # separately: that is a gap in what the tool says about itself, not
            # an ingestion failure.
            if not result.read_successfully:
                counts["unreadable_structure"] += 1
            elif result.accepted:
                counts["projected"] += 1
            else:
                counts["no_structure"] += 1

        logger.info(
            "Projected %d/%d tools as operators (%d declare no structure, "
            "%d had an extractor fail, %d unreadable)",
            counts["projected"], counts["tools"], counts["no_structure"],
            counts["unreadable_structure"], counts["failed"])
        return counts

    async def _observe_invocation(self, tool, parameters, succeeded: bool) -> None:
        """Submit one tool invocation as evidence. Never fails the tool call."""
        try:
            from core.domain.evidence_producers import submit_tool_invocation

            await submit_tool_invocation(
                getattr(tool, "name", ""), parameters or {}, bool(succeeded),
                category=str(getattr(getattr(tool, "category", None), "value", "tools")))
        except Exception as e:
            # The tool ran and its result is real. Losing that because the
            # semantic layer could not record it would be the larger defect --
            # but a silent pass would make a broken producer look like a tool
            # with nothing to observe, so it is logged at error.
            logger.error(
                "tool %s executed but its invocation was not recorded as "
                "evidence: %s: %s", getattr(tool, "name", "?"), type(e).__name__, e)

    def _log_usage(
        self,
        tool: Tool,
        parameters: Dict[str, Any],
        result: ToolResult,
        user_id: Optional[str],
        session_id: Optional[str]
    ):
        """Log tool usage for constitutional monitoring"""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "tool_name": tool.name,
            "category": tool.category.value if hasattr(tool.category, 'value') else str(tool.category),
            "safety_level": tool.safety_level.value if hasattr(tool.safety_level, 'value') else str(tool.safety_level),
            "parameters": parameters,
            "success": result.success,
            "error": result.error,
            "execution_time": result.execution_time,
            "user_id": user_id,
            "session_id": session_id
        }
        
        self.usage_log.append(log_entry)

        # PERSIST IT. This record is built on every execution with exactly the
        # fields learning needs -- tool, category, success, error, duration --
        # and was appended to an in-memory list that dies with the process.
        #
        # Failures had a durable home (tool_error_events, written per execution
        # from execute_tool) and successes had none, so the record Torin learns
        # from held 412 failures against 1 success. Anything computing a success
        # rate from it concluded that every tool always fails.
        #
        # Fire-and-forget on the running loop, mirroring the error path, so
        # recording an outcome never delays returning it.
        try:
            asyncio.create_task(_persist_tool_execution_async(log_entry))
        except RuntimeError:
            # No running loop (synchronous caller): the in-memory log still has
            # it, and this is reported rather than silently dropped.
            logger.debug("No running loop; tool execution outcome not persisted")

        # Notify constitutional monitor if available
        if self.constitutional_monitor:
            asyncio.create_task(
                self.constitutional_monitor.record_tool_usage(log_entry)
            )

    def _suggest_tools(self, requested_name: str, max_suggestions: int = 5) -> List[str]:
        """Suggest similar tool names for TOOL_NOT_FOUND errors.

        This is intentionally simple and fast: substring and prefix matching
        over the currently-registered tool names. It is only used for
        guidance, not correctness.
        """
        if not requested_name:
            return []

        requested_lower = requested_name.lower()

        # First: substring or superstring matches
        candidates: List[str] = []
        for name in self.tools.keys():
            lower = name.lower()
            if requested_lower in lower or lower in requested_lower:
                candidates.append(name)

        # Fallback: prefix match on first 3 characters
        if not candidates and len(requested_lower) >= 3:
            prefix = requested_lower[:3]
            for name in self.tools.keys():
                if name.lower().startswith(prefix):
                    candidates.append(name)

        # Final fallback: just return a few known tools
        if not candidates:
            candidates = list(self.tools.keys())

        return candidates[:max_suggestions]

    def get_usage_stats(self) -> Dict[str, Any]:
        """Tool inventory and SESSION usage.

        Two things were wrong here and both under-reported the system:

        `total_tools` was len(self.tools) -- the EAGER tools only. Most tools are
        registered lazily as factories, so the registry described itself as ~92
        tools when it holds ~384. Anything gating on tool count saw a quarter of
        the inventory.

        `total_uses` sums Tool.usage_count, which is an in-process attribute
        initialised to 0 and incremented on execution. It is never loaded from
        storage, so it reports 0 in any fresh process regardless of history --
        while unified.tool_error_events holds hundreds of real records. The
        counter is SESSION scope and is now named as such; persisted history is
        a different question and is not answered by an in-memory sum.
        """
        total_uses = sum(tool.usage_count for tool in self.tools.values())

        by_category = {}
        for tool in self.tools.values():
            cat = tool.category.value
            if cat not in by_category:
                by_category[cat] = {"count": 0, "usage": 0}
            by_category[cat]["count"] += 1
            by_category[cat]["usage"] += tool.usage_count

        most_used = sorted(
            self.tools.values(),
            key=lambda t: t.usage_count,
            reverse=True
        )[:5]

        return {
            "total_tools": len(self.tools) + len(self.tool_factories),
            "eager_tools": len(self.tools),
            "lazy_tools": len(self.tool_factories),
            "loaded_tools": len(self.loaded_tools),
            "session_uses": total_uses,
            "total_uses": total_uses,  # retained: existing callers read this key
            "by_category": by_category,
            "most_used": [
                {
                    "name": t.name,
                    "usage_count": t.usage_count,
                    "last_used": t.last_used.isoformat() if t.last_used else None
                }
                for t in most_used
            ]
        }


# Global registry instance
_tool_registry: Optional[ToolRegistry] = None


def get_tool_registry() -> ToolRegistry:
    """Get or create global tool registry"""
    global _tool_registry
    
    if _tool_registry is None:
        _tool_registry = ToolRegistry()
        
        # Auto-register all available tools
        _register_default_tools()
    
    return _tool_registry


def _register_tool_lazy(tool_class):
    """
    Helper to register a tool class with lazy loading.

    Instantiates once to extract metadata, then registers a factory
    that creates fresh instances on demand.

    Args:
        tool_class: Tool class (not instance)
    """
    registry = _tool_registry

    # Instantiate once to get metadata (then discard)
    metadata_instance = tool_class()
    tool_name = metadata_instance.name

    # Extract capabilities if available
    capabilities = None
    if hasattr(metadata_instance, 'capability_profile') and metadata_instance.capability_profile:
        capabilities = list(metadata_instance.capability_profile.get_capability_names())

    # Register factory that creates NEW instances on demand
    registry.register_factory(
        tool_name,
        tool_class,  # Pass class itself, not instance
        capabilities=capabilities,
        category=metadata_instance.category,
        safety_level=metadata_instance.safety_level
    )


def _register_default_tools():
    """Register all default tools with lazy loading"""
    registry = _tool_registry

    # ===== LAZY LOADING: Tools registered as factories, loaded on first use =====
    try:
        from .filesystem_tools import (
            ReadFileTool, WriteFileTool, PatchFileTool, ListDirectoryTool,
            CreateDirectoryTool, SearchFilesTool, MoveFileTool,
            CopyFileTool, DeleteFileTool, AtomicWriteFileTool,
            ValidatePathTool, CalculateChecksumTool, GetFileInfoTool,
            CompressFileTool, DecompressFileTool, FindDuplicateFilesTool,
            SyncDirectoryTool
        )
        _register_tool_lazy(ReadFileTool)
        _register_tool_lazy(WriteFileTool)
        _register_tool_lazy(PatchFileTool)
        _register_tool_lazy(ListDirectoryTool)
        _register_tool_lazy(CreateDirectoryTool)
        _register_tool_lazy(SearchFilesTool)
        _register_tool_lazy(MoveFileTool)
        _register_tool_lazy(CopyFileTool)
        _register_tool_lazy(DeleteFileTool)
        _register_tool_lazy(AtomicWriteFileTool)
        _register_tool_lazy(ValidatePathTool)
        _register_tool_lazy(CalculateChecksumTool)
        _register_tool_lazy(GetFileInfoTool)
        _register_tool_lazy(CompressFileTool)
        _register_tool_lazy(DecompressFileTool)
        _register_tool_lazy(FindDuplicateFilesTool)
        _register_tool_lazy(SyncDirectoryTool)
        logger.info("✅ Registered 17 filesystem tools (lazy)")
    except ImportError as e:
        logger.warning(f"Could not register base filesystem tools: {e}")

    try:
        from .execution_tools import (
            RunPythonTool, RunShellCommandTool, ExecuteSandboxTool,
            ListProcessesTool, KillProcessTool, StartServiceTool,
            StopServiceTool, RestartServiceTool, GetProcessInfoTool,
            RunBackgroundTaskTool, ScheduleCronJobTool, InstallPythonPackageTool,
            ExecuteWithTimeoutTool, ExecuteWithResourceLimitsTool,
            ExecuteNetworkIsolatedTool, ExecuteDeterministicTool,
            ExecuteWithArtifactCaptureTool
        )
        _register_tool_lazy(RunPythonTool)
        _register_tool_lazy(RunShellCommandTool)
        _register_tool_lazy(ExecuteSandboxTool)
        _register_tool_lazy(ListProcessesTool)
        _register_tool_lazy(KillProcessTool)
        _register_tool_lazy(StartServiceTool)
        _register_tool_lazy(StopServiceTool)
        _register_tool_lazy(RestartServiceTool)
        _register_tool_lazy(GetProcessInfoTool)
        _register_tool_lazy(RunBackgroundTaskTool)
        _register_tool_lazy(ScheduleCronJobTool)
        _register_tool_lazy(InstallPythonPackageTool)
        _register_tool_lazy(ExecuteWithTimeoutTool)
        _register_tool_lazy(ExecuteWithResourceLimitsTool)
        _register_tool_lazy(ExecuteNetworkIsolatedTool)
        _register_tool_lazy(ExecuteDeterministicTool)
        _register_tool_lazy(ExecuteWithArtifactCaptureTool)
        logger.info("✅ Registered 17 execution tools (lazy)")
    except ImportError as e:
        logger.warning(f"Could not register base execution tools: {e}")

    try:
        from .search_tools import (
            SemanticSearchTool, GrepSearchTool, AnalyzeCodeTool,
            AnalyzeCodeQualityTool, AnalyzeDependenciesTool, FindDeadCodeTool,
            SecurityScanTool, FindTodosTool, CountLinesTool,
            AnalyzeComplexityTool, DetectCodeSmellsTool, TraceDependenciesTool,
            FindCircularImportsTool, AnalyzeTestCoverageReportTool,
            FindPerformanceIssuesTool, CheckCodeStyleConsistencyTool,
            ASTSearchTool, BuildDependencyGraphTool, ExtractCallGraphTool,
            SearchSecretsAndPIITool
        )
        _register_tool_lazy(SemanticSearchTool)
        _register_tool_lazy(GrepSearchTool)
        _register_tool_lazy(AnalyzeCodeTool)
        _register_tool_lazy(AnalyzeCodeQualityTool)
        _register_tool_lazy(AnalyzeDependenciesTool)
        _register_tool_lazy(FindDeadCodeTool)
        _register_tool_lazy(SecurityScanTool)
        _register_tool_lazy(FindTodosTool)
        _register_tool_lazy(CountLinesTool)
        _register_tool_lazy(AnalyzeComplexityTool)
        _register_tool_lazy(DetectCodeSmellsTool)
        _register_tool_lazy(TraceDependenciesTool)
        _register_tool_lazy(FindCircularImportsTool)
        _register_tool_lazy(AnalyzeTestCoverageReportTool)
        _register_tool_lazy(FindPerformanceIssuesTool)
        _register_tool_lazy(CheckCodeStyleConsistencyTool)
        _register_tool_lazy(ASTSearchTool)
        _register_tool_lazy(BuildDependencyGraphTool)
        _register_tool_lazy(ExtractCallGraphTool)
        _register_tool_lazy(SearchSecretsAndPIITool)
    except ImportError as e:
        logger.warning(f"Could not register base search tools: {e}")

    try:
        from .system_tools import (
            ClipboardTool, NotificationTool, SystemInfoTool, FileWatcherTool,
            ListUsbDevicesTool, InstalledSoftwareTool
        )
        _register_tool_lazy(ClipboardTool)
        _register_tool_lazy(NotificationTool)
        _register_tool_lazy(SystemInfoTool)
        _register_tool_lazy(FileWatcherTool)
        _register_tool_lazy(ListUsbDevicesTool)
        _register_tool_lazy(InstalledSoftwareTool)
    except ImportError as e:
        logger.warning(f"Could not register system tools: {e}")

    # ===== EXTENDED TOOLS =====

    # Database & Storage Tools
    try:
        from .database_tools import (
            MySQLQueryTool, MySQLTableInfoTool, MySQLBackupTool, MySQLRestoreTool,
            RedisGetTool, RedisSetTool, R2UploadTool, R2DownloadTool,
            # Advanced database tools
            ConnectionPoolManagerTool, TransactionWrapperTool, MigrationRunnerTool,
            RowLevelAccessControlTool, SafeQueryExecutorTool
        )
        _register_tool_lazy(MySQLQueryTool)
        _register_tool_lazy(MySQLTableInfoTool)
        _register_tool_lazy(MySQLBackupTool)
        _register_tool_lazy(MySQLRestoreTool)
        _register_tool_lazy(RedisGetTool)
        _register_tool_lazy(RedisSetTool)
        _register_tool_lazy(R2UploadTool)
        _register_tool_lazy(R2DownloadTool)
        # Advanced database tools
        _register_tool_lazy(ConnectionPoolManagerTool)
        _register_tool_lazy(TransactionWrapperTool)
        _register_tool_lazy(MigrationRunnerTool)
        _register_tool_lazy(RowLevelAccessControlTool)
        _register_tool_lazy(SafeQueryExecutorTool)
    except ImportError as e:
        logger.warning(f"Could not register database tools: {e}")

    # Network & Web Tools
    try:
        from .network_tools import (
            HttpRequestTool, DownloadFileTool, UploadFileTool, ParseHTMLTool,
            ExtractLinksTool, CheckURLStatusTool, DNSLookupTool, PingHostTool,
            PortScanTool, WebSocketConnectTool, GraphQLQueryTool, APICallTool,
            WebSearchTool, WebFetchTool, BrowserTool
        )
        _register_tool_lazy(HttpRequestTool)
        _register_tool_lazy(DownloadFileTool)
        _register_tool_lazy(UploadFileTool)
        _register_tool_lazy(ParseHTMLTool)
        _register_tool_lazy(ExtractLinksTool)
        _register_tool_lazy(CheckURLStatusTool)
        _register_tool_lazy(DNSLookupTool)
        _register_tool_lazy(PingHostTool)
        _register_tool_lazy(PortScanTool)
        _register_tool_lazy(WebSocketConnectTool)
        _register_tool_lazy(GraphQLQueryTool)
        _register_tool_lazy(APICallTool)
        _register_tool_lazy(WebSearchTool)     # Real web search via DuckDuckGo
        _register_tool_lazy(WebFetchTool)      # Fast HTTP page reader (static/SSR pages)
        _register_tool_lazy(BrowserTool)       # Headless Chromium via Playwright (JS/SPAs)
    except ImportError as e:
        logger.warning(f"Could not register network tools: {e}")

    # Research Tools - Multi-source academic and data research
    try:
        from .research_tools import (
            ConductResearchTool, SearchAcademicTool, SearchDataTool, SearchNewsTool
        )
        _register_tool_lazy(ConductResearchTool)
        _register_tool_lazy(SearchAcademicTool)
        _register_tool_lazy(SearchDataTool)
        _register_tool_lazy(SearchNewsTool)
    except ImportError as e:
        logger.warning(f"Could not register research tools: {e}")

    # Academic Tools - Comprehensive academic research suite
    try:
        from .academic_tools import (
            AnalyzeResearchPaperTool, GenerateCitationTool, SynthesizeLiteratureTool,
            ExtractPaperMetadataTool, AnalyzeResearchDataTool, GenerateLatexDocumentTool,
            CreateResearchGraphTool,
            FetchPaperByDOITool, FetchPaperByArxivTool, ValidateBibliographyTool,
            ExportBibliographyCSLTool, LinkClaimToEvidenceTool, GenerateArtifactManifestTool
        )
        _register_tool_lazy(AnalyzeResearchPaperTool)
        _register_tool_lazy(GenerateCitationTool)
        _register_tool_lazy(SynthesizeLiteratureTool)
        _register_tool_lazy(ExtractPaperMetadataTool)
        _register_tool_lazy(AnalyzeResearchDataTool)
        _register_tool_lazy(GenerateLatexDocumentTool)
        _register_tool_lazy(CreateResearchGraphTool)
        _register_tool_lazy(FetchPaperByDOITool)
        _register_tool_lazy(FetchPaperByArxivTool)
        _register_tool_lazy(ValidateBibliographyTool)
        _register_tool_lazy(ExportBibliographyCSLTool)
        _register_tool_lazy(LinkClaimToEvidenceTool)
        _register_tool_lazy(GenerateArtifactManifestTool)
    except ImportError as e:
        logger.warning(f"Could not register academic tools: {e}")

    # Communication Tools
    try:
        from .communication_tools import (
            SendSlackMessageTool, PostToWebhookTool
        )
        _register_tool_lazy(SendSlackMessageTool)
        _register_tool_lazy(PostToWebhookTool)
    except ImportError as e:
        logger.warning(f"Could not register communication tools: {e}")

    # Context-Aware Slack Tools (for internal operations only)
    try:
        from .slack_tools import (
            AskForClarificationTool, ReportSecurityFindingTool, NotifyDominionLabsTeamTool
        )
        _register_tool_lazy(AskForClarificationTool)
        _register_tool_lazy(ReportSecurityFindingTool)
        _register_tool_lazy(NotifyDominionLabsTeamTool)
        logger.info("✅ Context-aware Slack tools registered (internal operations only)")
    except ImportError as e:
        logger.warning(f"Could not register context-aware Slack tools: {e}")

    # Slack Monitoring & Interaction Tools (leveraging 43+ bot events)
    try:
        from .slack_monitoring_tools import (
            GetSlackUsersTool, GetSlackChannelsTool, SearchSlackMessagesTool,
            GetChannelHistoryTool, MonitorTeamActivityTool, GetTeamHealthMetricsTool,
            PostSlackMessageTool, GetUserPresenceTool
        )
        _register_tool_lazy(GetSlackUsersTool)
        _register_tool_lazy(GetSlackChannelsTool)
        _register_tool_lazy(SearchSlackMessagesTool)
        _register_tool_lazy(GetChannelHistoryTool)
        _register_tool_lazy(MonitorTeamActivityTool)
        _register_tool_lazy(GetTeamHealthMetricsTool)
        _register_tool_lazy(PostSlackMessageTool)
        _register_tool_lazy(GetUserPresenceTool)
        logger.info("✅ Slack monitoring tools registered (8 tools for comprehensive workspace monitoring)")
    except ImportError as e:
        logger.warning(f"Could not register Slack monitoring tools: {e}")

    # Monitoring & Metrics Tools
    try:
        from .monitoring_tools import (
            GetCPUUsageTool, GetMemoryUsageTool, GetDiskUsageTool, GetNetworkStatsTool,
            CheckMySQLHealthTool, GetServiceStatusTool, ParseLogsTool, QueryMetricsTool,
            CreateAlertTool, GetPerformanceProfileTool,
            # Advanced monitoring tools
            DistributedTracingTool, SLOSLIToolingTool, AnomalyDetectionTool, DashboardGeneratorTool
        )
        _register_tool_lazy(GetCPUUsageTool)
        _register_tool_lazy(GetMemoryUsageTool)
        _register_tool_lazy(GetDiskUsageTool)
        _register_tool_lazy(GetNetworkStatsTool)
        _register_tool_lazy(CheckMySQLHealthTool)
        _register_tool_lazy(GetServiceStatusTool)
        _register_tool_lazy(ParseLogsTool)
        _register_tool_lazy(QueryMetricsTool)
        _register_tool_lazy(CreateAlertTool)
        _register_tool_lazy(GetPerformanceProfileTool)
        # Advanced monitoring tools
        _register_tool_lazy(DistributedTracingTool)
        _register_tool_lazy(SLOSLIToolingTool)
        _register_tool_lazy(AnomalyDetectionTool)
        _register_tool_lazy(DashboardGeneratorTool)
    except ImportError as e:
        logger.warning(f"Could not register monitoring tools: {e}")

    # AI/ML Operations Tools
    try:
        from .ai_ml_tools import (
            GenerateEmbeddingTool, QueryMemoryTool, StoreMemoryTool, RunInferenceTool,
            AnalyzeTrainingDataTool, GetModelInfoTool, SemanticSimilarityTool, ExtractEntitiesTool
        )
        _register_tool_lazy(GenerateEmbeddingTool)
        _register_tool_lazy(QueryMemoryTool)
        _register_tool_lazy(StoreMemoryTool)
        _register_tool_lazy(RunInferenceTool)
        _register_tool_lazy(AnalyzeTrainingDataTool)
        _register_tool_lazy(GetModelInfoTool)
        _register_tool_lazy(SemanticSimilarityTool)
        _register_tool_lazy(ExtractEntitiesTool)
    except ImportError as e:
        logger.warning(f"Could not register AI/ML tools: {e}")

    # Data Processing Tools
    try:
        from .data_processing_tools import (
            ParseJSONTool, ParseYAMLTool, ParseCSVTool, ConvertFormatTool,
            TransformDataTool, AggregateDataTool, MergeDatasetsTool, FilterDataTool,
            SortDataTool, DeduplicateDataTool,
            # Advanced data processing
            ParseJSONLTool, SchemaInferenceTool, PIIScrubbingTool, DatasetProfilingTool
        )
        _register_tool_lazy(ParseJSONTool)
        _register_tool_lazy(ParseYAMLTool)
        _register_tool_lazy(ParseCSVTool)
        _register_tool_lazy(ConvertFormatTool)
        _register_tool_lazy(TransformDataTool)
        _register_tool_lazy(AggregateDataTool)
        _register_tool_lazy(MergeDatasetsTool)
        _register_tool_lazy(FilterDataTool)
        _register_tool_lazy(SortDataTool)
        _register_tool_lazy(DeduplicateDataTool)
        # Advanced data processing tools
        _register_tool_lazy(ParseJSONLTool)
        _register_tool_lazy(SchemaInferenceTool)
        _register_tool_lazy(PIIScrubbingTool)
        _register_tool_lazy(DatasetProfilingTool)
    except ImportError as e:
        logger.warning(f"Could not register data processing tools: {e}")

    # Code Generation & Modification Tools
    try:
        from .code_generation_tools import (
            # Basic Code Generation
            GenerateFunctionTool, GenerateClassTool, GenerateModuleTool,
            RefactorCodeTool, AddDocstringTool, AddTypeHintsTool,
            FormatCodeTool, FixLintingErrorsTool, GenerateTestTool, MigrateCodeTool,
            # Code Enhancement
            AddLoggingTool, OptimizeCodeTool, ConvertToAsyncTool,
            ExtractMethodTool, InlineVariableTool, RenameSymbolTool,
            # Mathematical & Algorithm Generation
            ImplementAlgorithmTool, GenerateSymbolicMathTool,
            GenerateNumericalCodeTool, GenerateMathProofTool,
            # Advanced Code Generation
            GenerateDesignPatternTool, GenerateAPIClientTool,
            ScaffoldApplicationTool, SynthesizeFromExamplesTool, GeneratePropertyTestTool,
            # Code Generation Infrastructure
            ApplyPatchTool, CompileTypecheckGateTool, RepositoryRefactorTool,
            LicenseAttributionCheckTool
        )
        # Register Basic Code Generation Tools
        _register_tool_lazy(GenerateFunctionTool)
        _register_tool_lazy(GenerateClassTool)
        _register_tool_lazy(GenerateModuleTool)
        _register_tool_lazy(RefactorCodeTool)
        _register_tool_lazy(AddDocstringTool)
        _register_tool_lazy(AddTypeHintsTool)
        _register_tool_lazy(FormatCodeTool)
        _register_tool_lazy(FixLintingErrorsTool)
        _register_tool_lazy(GenerateTestTool)
        _register_tool_lazy(MigrateCodeTool)

        # Register Code Enhancement Tools
        _register_tool_lazy(AddLoggingTool)
        _register_tool_lazy(OptimizeCodeTool)
        _register_tool_lazy(ConvertToAsyncTool)
        _register_tool_lazy(ExtractMethodTool)
        _register_tool_lazy(InlineVariableTool)
        _register_tool_lazy(RenameSymbolTool)

        # Register Mathematical & Algorithm Generation Tools
        _register_tool_lazy(ImplementAlgorithmTool)
        _register_tool_lazy(GenerateSymbolicMathTool)
        _register_tool_lazy(GenerateNumericalCodeTool)
        _register_tool_lazy(GenerateMathProofTool)

        # Register Advanced Code Generation Tools
        _register_tool_lazy(GenerateDesignPatternTool)
        _register_tool_lazy(GenerateAPIClientTool)
        _register_tool_lazy(ScaffoldApplicationTool)
        _register_tool_lazy(SynthesizeFromExamplesTool)
        _register_tool_lazy(GeneratePropertyTestTool)

        # Register Code Generation Infrastructure Tools
        _register_tool_lazy(ApplyPatchTool)
        _register_tool_lazy(CompileTypecheckGateTool)
        _register_tool_lazy(RepositoryRefactorTool)
        _register_tool_lazy(LicenseAttributionCheckTool)
    except ImportError as e:
        logger.warning(f"Could not register code generation tools: {e}")

    # Testing & Validation Tools
    try:
        from .testing_validation_tools import (
            RunPytestTool, RunUnittestTool, CheckSyntaxTool, ValidateJSONTool,
            ValidateYAMLTool, ValidateXMLTool, ValidateSchemaTool, LintPythonTool,
            TypeCheckTool, BenchmarkCodeTool, GenerateMockTool, TestDataGeneratorTool,
            IntegrationTestRunnerTool, LoadTestTool, RunCoverageTool,
            # Advanced testing/validation tools
            FuzzTestingTool, MutationTestingTool, StaticSecurityAnalysisTool,
            GoldenTestHarnessTool, ChaosTestingTool
        )
        _register_tool_lazy(RunPytestTool)
        _register_tool_lazy(RunUnittestTool)
        _register_tool_lazy(CheckSyntaxTool)
        _register_tool_lazy(ValidateJSONTool)
        _register_tool_lazy(ValidateYAMLTool)
        _register_tool_lazy(ValidateXMLTool)
        _register_tool_lazy(ValidateSchemaTool)
        _register_tool_lazy(LintPythonTool)
        _register_tool_lazy(TypeCheckTool)
        _register_tool_lazy(BenchmarkCodeTool)
        _register_tool_lazy(GenerateMockTool)
        _register_tool_lazy(TestDataGeneratorTool)
        _register_tool_lazy(IntegrationTestRunnerTool)
        _register_tool_lazy(LoadTestTool)
        _register_tool_lazy(RunCoverageTool)
        # Advanced testing/validation tools
        _register_tool_lazy(FuzzTestingTool)
        _register_tool_lazy(MutationTestingTool)
        _register_tool_lazy(StaticSecurityAnalysisTool)
        _register_tool_lazy(GoldenTestHarnessTool)
        _register_tool_lazy(ChaosTestingTool)
    except ImportError as e:
        logger.warning(f"Could not register testing/validation tools: {e}")

    # Reasoning, Simulation, and Optimization Tools
    try:
        from .reasoning_tools import (
            ProveTheoremTool,
            SolveConstraintsTool,
            SolveLinearOptimizationTool,
            SimulatePDE1DTool,
            SimulateStateSpaceTool,
            RunMonteCarloTool,
        )

        _register_tool_lazy(ProveTheoremTool)
        _register_tool_lazy(SolveConstraintsTool)
        _register_tool_lazy(SolveLinearOptimizationTool)
        _register_tool_lazy(SimulatePDE1DTool)
        _register_tool_lazy(SimulateStateSpaceTool)
        _register_tool_lazy(RunMonteCarloTool)

        logger.info("✅ Registered reasoning/simulation/optimization tools (lazy)")
    except ImportError as e:
        logger.warning(f"Could not register reasoning/simulation tools: {e}")

    # Documentation Tools
    try:
        from .documentation_tools import (
            GenerateReadmeTool, GenerateAPIDocsTool, ExtractDocstringsTool,
            GenerateChangelogTool, CreateDiagramTool, UpdateDocsTool,
            # Advanced documentation tools
            DocsBuildPreviewTool, VersionedDocDeploymentTool, ADRGeneratorTool,
            # Real document generation tools
            GeneratePDFDocumentTool, GenerateWordDocumentTool, GeneratePowerPointTool,
            GenerateArchitectureDiagramTool, CreateFlowchartTool
        )
        _register_tool_lazy(GenerateReadmeTool)
        _register_tool_lazy(GenerateAPIDocsTool)
        _register_tool_lazy(ExtractDocstringsTool)
        _register_tool_lazy(GenerateChangelogTool)
        _register_tool_lazy(CreateDiagramTool)
        _register_tool_lazy(UpdateDocsTool)
        # Advanced documentation tools
        _register_tool_lazy(DocsBuildPreviewTool)
        _register_tool_lazy(VersionedDocDeploymentTool)
        _register_tool_lazy(ADRGeneratorTool)
        # Real document generation
        _register_tool_lazy(GeneratePDFDocumentTool)
        _register_tool_lazy(GenerateWordDocumentTool)
        _register_tool_lazy(GeneratePowerPointTool)
        _register_tool_lazy(GenerateArchitectureDiagramTool)
        _register_tool_lazy(CreateFlowchartTool)
    except ImportError as e:
        logger.warning(f"Could not register documentation tools: {e}")

    # System Management Tools
    try:
        from .system_management_tools import (
            SetEnvironmentVariableTool, GetEnvironmentVariableTool, ModifyConfigFileTool,
            ReloadConfigTool, CheckDependenciesTool, UpdateSystemTool, ManageDockerTool
        )
        _register_tool_lazy(SetEnvironmentVariableTool)
        _register_tool_lazy(GetEnvironmentVariableTool)
        _register_tool_lazy(ModifyConfigFileTool)
        _register_tool_lazy(ReloadConfigTool)
        _register_tool_lazy(CheckDependenciesTool)
        _register_tool_lazy(UpdateSystemTool)
        _register_tool_lazy(ManageDockerTool)
    except ImportError as e:
        logger.warning(f"Could not register system management tools: {e}")

    # Security & Encryption Tools
    try:
        from .security_tools import (
            # Encryption & Cryptography
            EncryptFileTool, DecryptFileTool, GeneratePasswordTool,
            HashDataTool, ValidateCertificateTool, ScanSecretsTool,
            # Active Defense & Threat Intelligence
            CheckIPThreatIntelligenceTool, BlockIPAddressTool, UnblockIPAddressTool,
            GetActiveBlocksTool, CreateWAFRuleTool, ApplyRateLimitTool,
            BlockCountryTool, GetSecurityMetricsTool, GetBlockHistoryTool,
            AddInternalThreatTool, SanitizeInputTool,
            # Input Validation Tools (NEW)
            ValidateEmailTool, ValidateURLTool, CheckMaliciousPatternsTool,
            SanitizeFilenameTool, ValidateSQLInputTool, ValidatePathTool,
            CheckRateLimitTool,
            # Defensive Security & Intrusion Detection
            DetectIntrusionTool, AnalyzeAnomalyTool, MonitorLogsTool,
            DetectBruteForceTool, AnalyzeTrafficPatternTool, AutoRespondThreatTool,
            HuntThreatsTool, DetectZeroDayTool,
            # Privacy & Digital Footprint Detection (ENABLED - Read-only, safe)
            AIDigitalFootprintDetectionTool,
            # Privacy & Digital Footprint Obliteration (DISABLED BY DEFAULT - EXTREMELY DANGEROUS)
            DigitalFootprintObliterationTool,
            RemoveFromDataBrokersTool,
            ScrubWebArchivesTool, ScrubDNSWhoisTool, DeletePackageTool,
            PurgeCDNCacheTool, FileLegalTakedownTool, RotateCredentialsTool,
            ObfuscateIdentityTool, NukeSocialMediaAccountTool,
            AggressiveDataBrokerAttackTool, NuclearObliterationTool
        )
        # Register Encryption & Cryptography Tools
        _register_tool_lazy(EncryptFileTool)
        _register_tool_lazy(DecryptFileTool)
        _register_tool_lazy(GeneratePasswordTool)
        _register_tool_lazy(HashDataTool)
        _register_tool_lazy(ValidateCertificateTool)
        _register_tool_lazy(ScanSecretsTool)

        # Register Active Defense & Threat Intelligence Tools
        _register_tool_lazy(CheckIPThreatIntelligenceTool)
        _register_tool_lazy(BlockIPAddressTool)
        _register_tool_lazy(UnblockIPAddressTool)
        _register_tool_lazy(GetActiveBlocksTool)
        _register_tool_lazy(CreateWAFRuleTool)
        _register_tool_lazy(ApplyRateLimitTool)
        _register_tool_lazy(BlockCountryTool)
        _register_tool_lazy(GetSecurityMetricsTool)
        _register_tool_lazy(GetBlockHistoryTool)
        _register_tool_lazy(AddInternalThreatTool)
        _register_tool_lazy(SanitizeInputTool)

        # Register Input Validation Tools (NEW)
        _register_tool_lazy(ValidateEmailTool)
        _register_tool_lazy(ValidateURLTool)
        _register_tool_lazy(CheckMaliciousPatternsTool)
        _register_tool_lazy(SanitizeFilenameTool)
        _register_tool_lazy(ValidateSQLInputTool)
        _register_tool_lazy(ValidatePathTool)
        _register_tool_lazy(CheckRateLimitTool)

        # Register Defensive Security & Intrusion Detection Tools
        _register_tool_lazy(DetectIntrusionTool)
        _register_tool_lazy(AnalyzeAnomalyTool)
        _register_tool_lazy(MonitorLogsTool)
        _register_tool_lazy(DetectBruteForceTool)
        _register_tool_lazy(AnalyzeTrafficPatternTool)
        _register_tool_lazy(AutoRespondThreatTool)
        _register_tool_lazy(HuntThreatsTool)
        _register_tool_lazy(DetectZeroDayTool)

        # Register AI Digital Footprint Detection Tool (ENABLED - Read-only, safe)
        _register_tool_lazy(AIDigitalFootprintDetectionTool)
        logger.info("✅ AI Digital Footprint Detection Tool registered (ENABLED - read-only intelligence gathering)")

        # Register Digital Footprint Obliteration Tools (ALL DISABLED BY DEFAULT)
        # All tools are registered but disabled - require explicit authorization to enable
        _register_tool_lazy(DigitalFootprintObliterationTool)
        _register_tool_lazy(RemoveFromDataBrokersTool)
        _register_tool_lazy(ScrubWebArchivesTool)
        _register_tool_lazy(ScrubDNSWhoisTool)
        _register_tool_lazy(DeletePackageTool)
        _register_tool_lazy(PurgeCDNCacheTool)
        _register_tool_lazy(FileLegalTakedownTool)
        _register_tool_lazy(RotateCredentialsTool)
        _register_tool_lazy(ObfuscateIdentityTool)
        _register_tool_lazy(NukeSocialMediaAccountTool)
        _register_tool_lazy(AggressiveDataBrokerAttackTool)
        _register_tool_lazy(NuclearObliterationTool)
        logger.info("⚠️  Digital footprint tools registered (13 total) - ALL DISABLED - require explicit authorization")

    except ImportError as e:
        logger.warning(f"Could not register security tools: {e}")

    # Learning & Analysis Tools (Self-Improvement, Causal Reasoning)
    try:
        from .learning_tools import (
            ProfilePerformanceTool, AnalyzeCausalFeedbackTool, DetectPatternsTool,
            ExtractLessonsLearnedTool, GenerateHypothesisTool,
            BenchmarkLearningSystemsTool, VisualizeLearningProgressTool,
            IdentifySkillGapsTool, RecommendTrainingTool, MonitorDataDriftTool,
            TriggerSelfImprovementTool
        )
        _register_tool_lazy(ProfilePerformanceTool)
        _register_tool_lazy(AnalyzeCausalFeedbackTool)
        _register_tool_lazy(DetectPatternsTool)
        _register_tool_lazy(ExtractLessonsLearnedTool)
        _register_tool_lazy(GenerateHypothesisTool)
        _register_tool_lazy(BenchmarkLearningSystemsTool)
        _register_tool_lazy(VisualizeLearningProgressTool)
        _register_tool_lazy(IdentifySkillGapsTool)
        _register_tool_lazy(RecommendTrainingTool)
        _register_tool_lazy(MonitorDataDriftTool)
        _register_tool_lazy(TriggerSelfImprovementTool)
        logger.info("✅ Registered 12 learning & analysis tools (lazy)")
    except ImportError as e:
        logger.warning(f"Could not register learning tools: {e}")

    # Chaos Engineering Tools
    try:
        from .chaos_tools import (
            CreateChaosExperimentTool,
            RunChaosExperimentTool,
            CreateChaosExperimentFromScenarioTool,
            ListChaosScenariosTool,
            GetChaosExperimentStatusTool,
            RollbackChaosExperimentTool,
        )
        _register_tool_lazy(CreateChaosExperimentTool)
        _register_tool_lazy(RunChaosExperimentTool)
        _register_tool_lazy(CreateChaosExperimentFromScenarioTool)
        _register_tool_lazy(ListChaosScenariosTool)
        _register_tool_lazy(GetChaosExperimentStatusTool)
        _register_tool_lazy(RollbackChaosExperimentTool)
        logger.info("✅ Registered 6 chaos engineering tools (lazy)")
    except ImportError as e:
        logger.warning(f"Could not register chaos tools: {e}")

    # ===== AGENTSO CONNECTOR TOOLS =====
    # Register AgentSO security connectors (VirusTotal, CrowdStrike, MISP, etc.)
    # Connectors are imported directly from services/agentso/connectors/
    try:
        from .connector_tools import register_connector_tools

        logger.info("🔌 Registering AgentSO connector tools...")
        count = register_connector_tools(registry)

        if count > 0:
            logger.info(f"✅ Registered {count} AgentSO connector tools")
        else:
            logger.warning("⚠️  No AgentSO connector tools registered")

    except ImportError as e:
        logger.warning(f"Could not load AgentSO connector tools: {e}")
    except Exception as e:
        logger.warning(f"AgentSO connector registration failed: {e}")

    # Count lazy-loaded factories + eager-loaded tools
    total_factories = len(registry.tool_factories)
    total_eager = len(registry.tools)
    logger.info(f"✅ Registered {total_factories} tool factories (lazy) + {total_eager} eager tools = {total_factories + total_eager} total")
    logger.info(f"💡 Tools will load on-demand when first accessed (fixes slow startup!)")
