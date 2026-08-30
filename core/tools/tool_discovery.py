"""Tool discovery ranker: BM25 + sentence embeddings + TorinAI's capability graph.

Three signals are fused per query:

1. LEXICAL (BM25 over name*3 + description + parameter names), with concatenated
   bigrams, light stemming and a small vocabulary-bridge table so user words the
   registry never uses ("mess", "sluggish", "repo") reach the words it does.

2. DENSE (all-MiniLM-L6-v2 over "pretty name. short description", plus a
   name-only vector). Absolute normalization, not min-max: a query nothing
   matches must stay low rather than be stretched back up to 1.0.

3. CAPABILITY — the part a standalone scorer cannot have. Every registered tool
   declares a ToolCapabilityProfile, and capabilities.py infers the capabilities
   a task needs from its wording. That gives two features, both scored on a
   tool's single strongest matching capability rather than a sum, and both
   discounted by how discriminative that capability is (`read_data` has 36
   providers and means almost nothing; `dns_lookup` has 2 and means almost
   everything):
     * cap_direct : how well the tool provides what the query asked for.
     * cap_sib    : pseudo-relevance feedback over the capability graph — the
       capabilities of the top couple of results pull in their siblings. It may
       only reorder the tail of the shortlist, never the head, so corroboration
       cannot displace a tool that matched the wording outright. This is what
       recovers the second and third gold tool on queries like "write a readme
       for this repo" (generate_readme found -> generate_api_docs pulled in
       through DOCUMENT_CODE).

Plus the fallback machinery that keeps the shell reachable: a generalist floor
driven by IDF coverage (the registry has no word for what was asked -> lift
run_shell_command), an entity gate (an IP/CVE/hash in the query means the user is
asking about the internet, not this laptop) and a machine-inspection heuristic.

Public API:
    build_index(tools) -> index      tools: live Tool objects or plain dicts
    rank(index, query, k) -> [name]

Everything is lazy: importing this module loads no model and touches no disk.
The embedding model is constructed on the first rank() (or the first build_index
that misses the cache), guarded by a lock, and tool vectors are cached to disk
keyed by a fingerprint of the catalog, so a restart with an unchanged registry
does no encoding at all. If sentence_transformers or the model files are
unavailable the dense signal is dropped and the remaining signals are reweighted;
rank() never raises.
"""

from __future__ import annotations
from core.capability import raise_if_structural

import contextlib
import hashlib
import json
import logging
import math
import os
import re
import tempfile
import threading
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

from core.model_policy import (
    ModelClass, model_use_permitted, record_model_executed,
)

logger = logging.getLogger(__name__)

# ASKED, NOT RESTATED. How this loads differs from the memory embedder on
# purpose -- it degrades to BM25 rather than raising, and pins CPU for a
# measured reason. WHICH model it loads is the same fact in both places, and
# writing it out twice meant an upgrade in one left the other behind.
try:
    from core.memory.utils.embedding_service import EMBEDDING_MODEL_ID as _MODEL_ID
except Exception:  # embeddings are optional here by design
    _MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
_CACHE_VERSION = "v1"
_EMB_DIM = 384          # all-MiniLM-L6-v2; change with _MODEL_ID


from core.semantics.lexical_normalization import match_key


def _usable_vectors(arr, rows: int) -> bool:
    """Is this a vector matrix we can actually rank against?

    Shape and finiteness are both load-bearing, and they fail differently:
    a wrong second dimension raises on the query matmul (so every call quietly
    drops to the BM25-only path, forever), while NaN/Inf raise nothing at all —
    they poison argsort and hand back the same alphabetically-first tools for
    every query, with no error anywhere. Neither is acceptable from a file on
    disk we did not write this run, so both are checked before use.
    """
    try:
        return (isinstance(arr, np.ndarray) and arr.ndim == 2
                and arr.shape[0] == rows and arr.shape[1] == _EMB_DIM
                and arr.dtype.kind == "f" and bool(np.isfinite(arr).all()))
    except Exception:
        return False


# ============================================================== cache location

def _cache_dir() -> str:
    override = os.environ.get("TORIN_TOOL_DISCOVERY_CACHE")
    if override:
        return override
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(root, "data", "cache", "tool_discovery")


def _cache_paths() -> Tuple[str, str]:
    d = _cache_dir()
    return (os.path.join(d, "tool_embeddings.npy"),
            os.path.join(d, "tool_embeddings.meta.json"))


# =================================================================== tokenizing

# Function words only. Verbs like run/find/get/show carry real signal here
# (run_pytest, find_todos, get_cpu_usage) and IDF already discounts them.
_STOP = set("""
a an the and or of to in on for with by from at as is are was were be been being
this that these those it its i me my mine we our ours you your yours
do does did done can could would shall
please just also any all some each every other another
what which who whom whose when where why how
if then than so such about into over under again further
here there very too much many more most less least
""".split())

_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_NONWORD = re.compile(r"[^a-z0-9]+")
_DOUBLE_END = re.compile(r"([bdfglmnprt])\1$")


def _stem(w: str) -> str:
    """The retrieval form of a word. Owned by core.semantics.

    THIS WAS A PRIVATE STEMMER, AND IT WAS WRONG ON WORDS THAT MATTER HERE.
    Measured: `indices` -> `indice` and `analyses` -> `analyse`, neither of
    which is a word, so a query for "indices" could never reach a tool indexed
    under "index". `physics` -> `physic` destroyed the mass noun. Irregulars
    were not handled at all: `geese`, `children`, `mice` passed through
    unchanged.

    Three implementations of this existed -- here, in the Self's language
    faculty (`core.agents.autonomous.self_model`, formerly
    `core.semantics.conversation`), and in `lexical_normalization` -- and all
    three disagreed. `lexical_normalization` already declares the invariant
    that one surface form has one canonical interpretation across every
    cognitive path; it just had no retrieval reading for callers like this one
    to use. It does now, and this delegates.

    Cost measured at 1.55 us/word against 0.56 for the old stemmer, on a path
    that ranks ~92 tools: not a factor.
    """
    if len(w) <= 3:
        return w
    return match_key(w) or w


def _raw_tokens(text: str) -> List[str]:
    text = _CAMEL.sub(" ", text)
    return [t for t in _NONWORD.split(text.lower()) if t]


def _tokens(text: str) -> List[str]:
    return [_stem(t) for t in _raw_tokens(text)
            if t not in _STOP and len(t) >= 2]


def _concat_bigrams(raw: Sequence[str]) -> List[str]:
    """'unit tests' -> 'unittest'; catches run_unittest, find_todos, etc."""
    out = []
    for i in range(len(raw) - 1):
        a, b = raw[i], raw[i + 1]
        if a in _STOP or b in _STOP:
            continue
        if len(a) + len(b) >= 5:
            out.append(_stem(a + b))
    return out


def _pretty(name: str) -> str:
    return " ".join(_raw_tokens(name))


def _short(desc: str, limit: int = 260) -> str:
    """First couple of sentences — long usage caveats add noise to embeddings."""
    desc = " ".join(desc.split())
    if len(desc) <= limit:
        return desc
    cut = desc[:limit]
    dot = cut.rfind(". ")
    return cut[: dot + 1] if dot > 60 else cut


# ========================================================================= BM25

NAME_COVERAGE_BONUS = 0.6   # a hit in the tool's own name is worth more


class _BM25:
    """Per-(term, doc) contribution is query-independent, so it is baked into one
    dense float32 matrix at build time. Query time is a gather plus a
    matrix-vector product rather than a Python loop over postings."""

    def __init__(self, docs, name_sets=None, k1: float = 1.4, b: float = 0.72):
        self.k1, self.b = k1, b
        self.N = len(docs)
        self.len = np.array([len(d) for d in docs], dtype=np.float32)
        self.avg = float(self.len.mean()) if self.N else 1.0

        counts = [Counter(d) for d in docs]
        df = Counter()
        for c in counts:
            df.update(c.keys())
        self.idf = {t: math.log(1.0 + (self.N - n + 0.5) / (n + 0.5))
                    for t, n in df.items()}
        self.max_idf = math.log(1.0 + (self.N + 0.5) / 0.5) if self.N else 1.0
        self.oov_idf = 0.92 * self.max_idf

        self.row = {t: i for i, t in enumerate(self.idf)}
        norm = self.k1 * (1 - self.b + self.b * self.len / max(self.avg, 1e-6))
        V = len(self.row)
        self.M = np.zeros((V, self.N), dtype=np.float32)
        self.C = np.zeros((V, self.N), dtype=np.float32)
        name_sets = name_sets or [set()] * self.N
        for i, c in enumerate(counts):
            for t, f in c.items():
                r = self.row[t]
                idf = self.idf[t]
                self.M[r, i] = idf * (f * (self.k1 + 1)) / (f + norm[i])
                self.C[r, i] = idf * (
                    1.0 + (NAME_COVERAGE_BONUS if t in name_sets[i] else 0.0))
        self.idf_arr = np.array([self.idf[t] for t in self.row], dtype=np.float32)

    def score(self, q_tokens, weights=None):
        """(scores, ideal). Out-of-vocabulary query terms still count toward
        `ideal`, so a query full of unknown words scores low in absolute terms
        instead of being renormalized back up to 1.0."""
        agg: Dict[int, float] = {}
        ideal = 0.0
        for j, t in enumerate(q_tokens):
            w = 1.0 if weights is None else weights[j]
            r = self.row.get(t)
            if r is None:
                ideal += w * self.oov_idf
                continue
            ideal += w * float(self.idf_arr[r])
            agg[r] = agg.get(r, 0.0) + w
        if not agg:
            return np.zeros(self.N, dtype=np.float32), ideal
        rows = np.fromiter(agg.keys(), dtype=np.int64, count=len(agg))
        wvec = np.fromiter(agg.values(), dtype=np.float32, count=len(agg))
        return self.M[rows].T @ wvec, ideal

    def coverage(self, uniq_tokens) -> float:
        """Largest share of the query's IDF mass any single tool accounts for.
        Original terms only — expansions are guesses and must not talk us into
        confidence we have not earned."""
        total = 0.0
        rows = []
        for t in uniq_tokens:
            r = self.row.get(t)
            if r is None:
                total += self.oov_idf
                continue
            total += float(self.idf_arr[r])
            rows.append(r)
        if total <= 1e-6 or not rows:
            return 0.0
        acc = self.C[np.asarray(rows, dtype=np.int64)].sum(axis=0)
        return float(min(max(acc.max() / total, 0.0), 1.0))


# ================================================================= dense model

_MODEL = None
_MODEL_FAILED = False
_MODEL_LOCK = threading.Lock()


@contextlib.contextmanager
def _quiet_loader():
    """Keep the encoder's first load off the console.

    transformers writes a 103-step 'Loading weights' progress bar and a weight
    LOAD REPORT table straight to stderr — ~29 KB of noise the first time
    discover_tools() is called, in whatever terminal TorinAI happens to be
    running in. Turning those two off at the source is enough; redirecting
    stderr wholesale would also swallow whatever other threads print during the
    half-second the load holds _MODEL_LOCK. Verbosity is restored afterwards so
    this stays a decision about our own load, not a process-wide logging change.
    """
    restore = []
    try:
        from transformers.utils import logging as hf_log
        prev = hf_log.get_verbosity()
        hf_log.set_verbosity_error()
        restore.append(lambda: hf_log.set_verbosity(prev))
        if hasattr(hf_log, "disable_progress_bar"):
            hf_log.disable_progress_bar()
            restore.append(hf_log.enable_progress_bar)
    except Exception:
        pass
    prev_bars = os.environ.get("HF_HUB_DISABLE_PROGRESS_BARS")
    os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
    try:
        yield
    finally:
        if prev_bars is None:
            os.environ.pop("HF_HUB_DISABLE_PROGRESS_BARS", None)
        else:
            os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = prev_bars
        for fn in reversed(restore):
            try:
                fn()
            except Exception:
                pass


def _model():
    """Load the encoder once, offline, pinned to CPU. Returns None if the model
    is unavailable — every caller must handle that."""
    global _MODEL, _MODEL_FAILED
    if _MODEL is not None or _MODEL_FAILED:
        return _MODEL
    with _MODEL_LOCK:
        if _MODEL is not None or _MODEL_FAILED:
            return _MODEL
        try:
            os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
            # HF_HUB_OFFLINE as an env var is useless here: huggingface_hub
            # snapshots it into module constants the moment it is imported, and
            # by the time this runs torch/transformers have long since pulled it
            # in. local_files_only is an argument, so it is honoured whatever the
            # import order was. Without it the first discover_tools() opens a
            # live connection to huggingface.co, and on a host that drops rather
            # than refuses that traffic it blocks on connect timeouts while
            # holding this lock — every concurrent caller waits with it.
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
            from sentence_transformers import SentenceTransformer

            # device pinned on purpose: MiniLM-L6 on one short query is
            # dispatch-bound, and letting it auto-select MPS costs ~19 ms/query
            # in a tensor sync for identical vectors.
            with _quiet_loader():
                try:
                    _MODEL = SentenceTransformer(_MODEL_ID, device="cpu",
                                                 local_files_only=True)
                except TypeError:      # older sentence-transformers
                    _MODEL = SentenceTransformer(_MODEL_ID, device="cpu")
        except Exception as e:
            _MODEL_FAILED = True
            logger.warning(
                "tool discovery: embeddings unavailable (%s: %s) — falling back "
                "to lexical + capability ranking", type(e).__name__, e)
        return _MODEL


def _encode(texts) -> Optional[np.ndarray]:
    # Unlike the memory embedder, this one degrades rather than raises: BM25 and
    # the capability graph are deterministic and still rank without it, which is
    # what keeps the strict lane usable instead of merely empty.
    #
    # The attempt is still counted, so assert_model_free() reports honestly that
    # ranking reached for an encoder. Degrading quietly and reporting the run as
    # model-free would be the lie worth avoiding.
    if not model_use_permitted(ModelClass.ENCODER, "tool_discovery._encode"):
        return None

    m = _model()
    if m is None:
        return None
    try:
        encoded = np.asarray(
            m.encode(texts, normalize_embeddings=True, batch_size=64,
                     show_progress_bar=False),
            dtype=np.float32)
    except Exception as e:
        logger.warning("tool discovery: encode failed (%s: %s)", type(e).__name__, e)
        return None
    record_model_executed(ModelClass.ENCODER, "tool_discovery._encode")
    return encoded


# =========================================================== brand-prefix gate
# Vendor-namespaced tools (splunk_*, crowdstrike_*, ...) are only correct when
# the user actually wants that vendor.

_BRAND_FALLBACK = {
    "virustotal", "crowdstrike", "misp", "restapi", "splunk", "elastic",
    "github", "snyk", "sonarqube", "qradar", "arcsight", "logrhythm",
    "shodan", "alienvaultotx", "threatconnect", "recordedfuture", "thehive",
    "shuffle", "qualys", "awssecurityhub", "azuresecuritycenter", "pagerduty",
}
_NEVER_BRAND = {
    "get", "run", "find", "search", "list", "create", "check", "analyze",
    "generate", "execute", "validate", "parse", "detect", "extract", "scan",
    "add", "convert", "merge", "sort", "filter", "read", "write", "delete",
    "move", "copy", "start", "stop", "restart", "kill", "install", "apply",
    "block", "unblock", "solve", "simulate", "store", "query", "update",
    "monitor", "post", "send", "compress", "decompress", "sync", "calculate",
    "semantic", "static", "load", "fuzz", "mutation", "golden", "chaos",
    "auto", "hunt", "notify", "report", "ask", "prove", "aggregate", "test",
    "type", "lint", "count", "trace", "build", "download", "upload", "http",
    "web", "browser", "dns", "ping", "port", "file", "data", "code", "schema",
    "rename", "inline", "refactor", "optimize", "migrate", "format", "fix",
    "deduplicate", "transform", "identify", "recommend", "benchmark", "profile",
    "forecast", "visualize", "connection", "transaction", "migration", "row",
    "safe", "atomic", "sanitize", "encrypt", "decrypt", "hash", "reload",
    "modify", "set", "manage", "docs", "versioned", "adr", "link", "export",
    "synthesize", "conduct", "scaffold", "implement", "compile", "license",
    "repository", "integration", "distributed", "slo", "anomaly", "dashboard",
    "clipboard", "notification", "system", "user", "team", "channel",
    "scrub", "purge", "rotate", "obfuscate", "nuke", "aggressive", "nuclear",
    "obliterate", "remove", "file_legal", "package",
}


def _brand_prefixes(names: Sequence[str]) -> set:
    """Detect vendor prefixes offline: real English words are one WordPiece
    token, brand names are not."""
    counts = Counter(n.split("_")[0].lower() for n in names)
    multi = {p for p, n in counts.items() if n >= 2 and p not in _NEVER_BRAND}
    m = _model()
    if m is not None:
        try:
            tk = m.tokenizer
            return {p for p in multi if len(tk.tokenize(p)) >= 2} | (_BRAND_FALLBACK & multi)
        except Exception:
            pass
    return _BRAND_FALLBACK & multi


# =============================================================== entity signals
# A query carrying a machine-readable indicator is an intel lookup, not a
# question about this laptop.

_ENTITY_PATTERNS = (
    ("ip", re.compile(
        r"\b(?:\d{1,3}\.){3}\d{1,3}\b"
        r"|\b(?:[0-9a-f]{1,4}:){3,7}[0-9a-f]{0,4}\b", re.I)),
    ("cve", re.compile(r"\bcve[-\s]?\d{4}[-\s]?\d{4,7}\b", re.I)),
    ("hash", re.compile(r"\b(?:[a-f0-9]{32}|[a-f0-9]{40}|[a-f0-9]{64})\b", re.I)),
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+\.[a-z]{2,}\b", re.I)),
    ("url", re.compile(r"\bhttps?://\S+|\bwww\.\S+", re.I)),
    ("domain", re.compile(
        r"\b[a-z0-9][a-z0-9-]{1,62}\.(?:com|net|org|io|ru|cn|co|xyz|info|biz|"
        r"top|dev|app|me|tk|onion|gov|edu|uk|de|fr|jp|br|in|us|site|club|live|"
        r"online|shop|pw|cc|su|ml|ga|cf|gq)\b", re.I)),
)

_SECURITY_INTENT = set("""
sketchy suspicious suspect malicious malware threat threats reputation safe
unsafe dangerous phishing phish attack attacker attacking abuse abusive
blocklist blacklist blocked block quarantine compromised infected infection
ioc iocs indicator indicators botnet c2 scam spam fraud evil bad hostile
virus trojan ransomware exploit exploited vulnerability vuln breach breached
intrusion intel intelligence enrich enrichment reputation risky hack hacked
brute scanning scanner attacked geolocate whois owns
""".split())

_ENTITY_TERMS = {
    "ip": ["ip", "address", "reputation", "threat", "intelligence", "host",
           "malicious", "indicator", "geolocation", "abuse"],
    "domain": ["domain", "dns", "reputation", "threat", "whois", "lookup",
               "malicious", "indicator", "intelligence"],
    "url": ["url", "scan", "reputation", "malicious", "link", "phishing", "threat"],
    "hash": ["hash", "file", "malware", "sample", "report", "scan", "indicator",
             "threat"],
    "cve": ["cve", "vulnerability", "exploit", "advisory", "patch", "severity",
            "security"],
    "email": ["email", "address", "phishing", "sender", "header", "threat"],
}
_ENTITY_HINT = {
    "ip": "IP address reputation threat intelligence lookup",
    "domain": "domain reputation DNS threat intelligence lookup",
    "url": "URL reputation scan malicious link",
    "hash": "file hash malware sample report",
    "cve": "CVE vulnerability exploit advisory",
    "email": "email address phishing sender analysis",
}
_ENTITY_TERMS_PLAIN = {
    "ip": ["ip", "address", "host", "network", "lookup", "ping"],
    "domain": ["domain", "dns", "host", "lookup", "url", "http", "status",
               "ping", "resolve"],
    "url": ["url", "http", "request", "fetch", "web", "page", "status", "link",
            "content"],
    "hash": ["hash", "file", "checksum", "digest"],
    "cve": ["cve", "vulnerability", "advisory", "severity"],
    "email": ["email", "address", "message", "send"],
}
_ENTITY_HINT_PLAIN = {
    "ip": "IP address host network lookup",
    "domain": "domain name host status HTTP request",
    "url": "fetch the content of this web page over HTTP",
    "hash": "file hash checksum",
    "cve": "CVE vulnerability advisory",
    "email": "email address message",
}


def _security_intent(query: str) -> bool:
    return bool(set(_raw_tokens(query)) & _SECURITY_INTENT)


def _entities(query: str) -> List[str]:
    found = []
    for kind, pat in _ENTITY_PATTERNS:
        if pat.search(query):
            found.append(kind)
    # An IPv4 must not double as a domain; a bare version string is neither.
    if "ip" in found and "domain" in found:
        found.remove("domain")
    return found


# ========================================================= machine inspection

_LOCAL_RE = re.compile(
    r"\b(my|this|the)\s+(computer|machine|laptop|mac|macbook|pc|desktop|box|system|host|workstation|phone)\b"
    r"|\bon\s+(my|this)\s+(machine|computer|laptop|mac|macbook|box|host|system|pc|desktop)\b"
    r"|\blocal(ly|host)?\b"
    r"|\bmy\s+(usb|drive|disk|screen|network|wifi|cpu|memory|ram|gpu|battery|ports?|filesystem)\b"
    r"|\bthis\s+(mac|box|laptop)\b|\battached\s+to\b|\bplugged\s+(in|into)\b"
    r"|\bconnected\s+to\s+(my|this|the)\b",
    re.I,
)
_HARDWARE = set("""
usb device devices hardware peripheral peripherals dongle bluetooth serial
adapter webcam camera microphone mic printer scanner monitor display screen
keyboard mouse trackpad headphone headphones speaker gpu battery thunderbolt
hdmi ethernet wifi router modem sd card drive drives volume volumes partition
firmware driver drivers kernel chipset cpu ram
""".split())
_INSPECT = set("""
locate find detect list show see check identify discover what which whether
is are any connected attached plugged mounted installed running present
""".split())
_PERF = set("""
sluggish slow slowly laggy lag lagging freeze freezing frozen hang hanging
hangs unresponsive stuck grinding crawling thrashing overheating hot loud
fans fan spiking spike bogged choking struggling pegged maxed hogging hog
hogs eating chewing consuming burning wasting sucking leaking
""".split())
_MACHINE_NOUN = set("""
machine computer laptop mac macbook pc desktop box system host workstation
everything resources memory ram cpu disk swap
""".split())

_SHELL = "run_shell_command"
# Tools that inspect *this* machine. Everything else talks to a remote service.
_LOCAL_TOOLS = (
    "system_info", "list_processes", "get_process_info", "run_python",
    "get_cpu_usage", "get_memory_usage", "get_disk_usage", "get_network_stats",
    "get_service_status", "list_directory", "file_watcher", "check_dependencies",
    "manage_docker", "get_environment_variable",
)
_PERF_TOOLS = (
    "list_processes", "get_process_info", "get_cpu_usage", "get_memory_usage",
    "get_disk_usage", "system_info",
)


def _machine_signal(query: str, entities: Sequence[str]):
    """(strength, shell_ok, perf). `entities` gates the whole heuristic: an
    IP/domain/hash/CVE means the user is asking about something on the internet,
    and hardware wording like "host"/"connected" is a false friend."""
    if entities:
        return 0.0, False, False

    seq = _raw_tokens(query)
    raw = set(seq)
    local = 1.0 if _LOCAL_RE.search(query) else 0.0
    if not local:
        for a, b in zip(seq, seq[1:]):
            if a in ("my", "this") and b in _HARDWARE:
                local = 1.0
                break

    hw = len(raw & _HARDWARE)
    insp = len(raw & _INSPECT)
    perf = bool(raw & _PERF) and bool(raw & _MACHINE_NOUN)

    if perf:
        return 0.85, False, True      # specific usage tools exist for this
    if local and hw:
        return 1.0, True, False
    if local and insp:
        return 0.8, True, False
    if local:
        return 0.5, True, False
    if hw >= 2 and insp:
        return 0.45, True, False
    return 0.0, True, False


# ========================================================= vocabulary bridges
# Keys and values are stems; values are filtered against the corpus vocabulary at
# build time, so listing a word the registry never uses is free.

_EXPAND = {
    "mess": ["refactor", "smell", "quality", "clean", "maintainability", "code"],
    "messy": ["refactor", "smell", "quality", "maintainability", "code"],
    "clean": ["refactor", "quality", "smell", "improve", "maintainability"],
    "cleanup": ["refactor", "quality", "smell", "unused", "dead"],
    "tidy": ["refactor", "quality", "smell", "format"],
    "ugly": ["refactor", "quality", "smell"],
    "spaghetti": ["refactor", "smell", "complexity", "quality"],
    "gnarly": ["refactor", "smell", "complexity"],
    "simplify": ["refactor", "quality", "complexity", "extract"],
    "rewrite": ["refactor", "code", "improve"],
    "function": ["function", "method", "code", "extract"],
    "readable": ["quality", "refactor", "maintainability"],
    "repo": ["repository", "codebase", "project", "code", "directory"],
    "repository": ["repository", "codebase", "project", "code"],
    "codebase": ["codebase", "code", "repository", "project"],
    "live": ["search", "find", "locate", "code"],
    "lives": ["search", "find", "locate", "code"],
    "defined": ["symbol", "search", "definition", "code", "ast"],
    "definition": ["symbol", "search", "definition", "ast"],
    "implemented": ["code", "search", "symbol", "implementation"],
    "logic": ["code", "implementation", "function"],
    "auth": ["authentication", "auth", "login"],
    "grep": ["grep", "search", "pattern", "text"],
    "regex": ["regex", "pattern", "search"],
    "usb": ["shell", "command", "system", "device", "port"],
    "hardware": ["shell", "command", "system", "device"],
    "peripheral": ["shell", "command", "system", "device"],
    "dongle": ["shell", "command", "system", "device"],
    "bluetooth": ["shell", "command", "system", "device"],
    "computer": ["shell", "command", "system", "machine"],
    "machine": ["shell", "command", "system"],
    "laptop": ["shell", "command", "system", "machine"],
    "terminal": ["shell", "command", "execute"],
    "bash": ["shell", "command", "execute"],
    "zsh": ["shell", "command", "execute"],
    "cli": ["shell", "command", "execute"],
    "locate": ["find", "search", "shell"],
    "sluggish": ["cpu", "memory", "usage", "process", "system", "performance"],
    "slow": ["cpu", "memory", "usage", "process", "performance"],
    "hog": ["cpu", "memory", "usage", "process"],
    "hogging": ["cpu", "memory", "usage", "process"],
    "eating": ["cpu", "memory", "usage", "process"],
    "ram": ["memory", "usage"],
    "cpu": ["cpu", "usage", "processor", "process"],
    "folder": ["directory", "path", "file"],
    "dir": ["directory", "path", "file"],
    "dep": ["dependency", "package"],
    "deps": ["dependency", "package"],
    "env": ["environment", "variable"],
    "container": ["docker", "container"],
    "kube": ["docker", "container"],
    "db": ["database", "sql", "query"],
    "vuln": ["vulnerability", "security", "scan"],
    "cred": ["credential", "secret", "password"],
    "doc": ["documentation", "readme"],
    "todo": ["todo", "comment", "fixme"],
    "fixme": ["todo", "comment", "fixme"],
}

_WHERE = set("where locate find search look show which whereabouts".split())
_CODE_CTX = set("""
repo repos repository codebase code codes source sources file files function
functions class classes method methods module modules package project
implementation logic handler handlers defined define definition declared
implemented symbol symbols variable constant import imports endpoint route
""".split())
_CODE_LOC_TERMS = ["search", "code", "codebase", "pattern", "symbol", "grep",
                   "semantic", "file", "ast", "text"]
_CODE_LOC_HINT = "search the codebase to find where this code is defined"


def _code_location(query: str) -> bool:
    raw = set(_raw_tokens(query))
    return bool(raw & _WHERE) and bool(raw & _CODE_CTX)


def _expansions(index, q_tok):
    """A bridge is a guess about what the user meant, so it stays well below the
    weight of a word actually typed."""
    out = {}
    for t in dict.fromkeys(q_tok):
        for e in index.expand.get(t, ()):
            out[e] = max(out.get(e, 0.0), EXPANSION_WEIGHT)
    for t in q_tok:
        out.pop(t, None)
    return out


# ========================================================== capability signal

_CAP_FN = None
_CAP_FN_RESOLVED = False
_CAP_LOCK = threading.Lock()


def _cap_fn():
    """Resolve capabilities.py's query -> capability inference lazily.

    The cheap lexical inference is preferred: it is ~0.07 ms/query against
    ~15 ms for the full regex table, which would dominate the whole ranker's
    latency budget. Set TORIN_DISCOVERY_FULL_CAPS=1 to use the full table."""
    global _CAP_FN, _CAP_FN_RESOLVED
    if _CAP_FN_RESOLVED:
        return _CAP_FN
    with _CAP_LOCK:
        if _CAP_FN_RESOLVED:
            return _CAP_FN
        fn = None
        want_full = os.environ.get("TORIN_DISCOVERY_FULL_CAPS") == "1"
        for mod in ("core.tools.capabilities", "capabilities"):
            try:
                m = __import__(mod, fromlist=["*"])
            except Exception:
                continue
            if not want_full and hasattr(m, "_lexical_capability_inference"):
                _lex = m._lexical_capability_inference
                fn = lambda q, _lex=_lex: _lex(q.lower(), CAP_FLOOR)
            elif hasattr(m, "infer_capability_from_task"):
                _full = m.infer_capability_from_task
                fn = lambda q, _full=_full: _full(q, CAP_FLOOR)
            if fn is not None:
                break
        if fn is None:
            logger.warning("tool discovery: capability inference unavailable — "
                           "ranking on lexical + dense signals only")
        _CAP_FN = fn
        _CAP_FN_RESOLVED = True
        return _CAP_FN


def _infer_caps(query: str) -> Dict[str, float]:
    fn = _cap_fn()
    if fn is None:
        return {}
    try:
        raw = fn(query) or {}
    except Exception as e:
        logger.debug("tool discovery: capability inference failed: %s", e)
        return {}
    out: Dict[str, float] = {}
    for cap, score in raw.items():
        key = getattr(cap, "value", None) or str(cap)
        try:
            out[key] = max(out.get(key, 0.0), float(score))
        except (TypeError, ValueError):
            continue
    return out


def _cap_demand(ix, caps: Dict[str, float]) -> Optional[np.ndarray]:
    """Inferred capabilities -> per-capability demand in [0, 1], discounted by
    how discriminative the capability is."""
    if not caps or ix.n_caps == 0:
        return None
    v = np.zeros(ix.n_caps, dtype=np.float32)
    for name, conf in caps.items():
        col = ix.cap_col.get(name)
        if col is not None:
            v[col] = max(float(v[col]), min(float(conf), CAP_CONF_CAP) / CAP_CONF_CAP)
    if not v.any():
        return None
    return v * ix.cap_w ** CAP_W_POW


# ==================================================================== the index

class _Index:
    """Opaque handle returned by build_index()."""
    pass


def _tool_record(tool) -> Optional[Tuple[str, str, List[str], List[str]]]:
    """(name, description, param names, capability values) from a live Tool or a
    plain dict. Returns None for anything unusable."""
    try:
        if isinstance(tool, dict):
            name = tool.get("name") or ""
            desc = tool.get("description") or ""
            params = tool.get("params") or tool.get("parameters") or []
            if isinstance(params, dict):
                params = list(params.keys())
            params = [str(getattr(p, "name", p)) for p in params]
            caps = tool.get("caps") or tool.get("capabilities") or []
        else:
            name = getattr(tool, "name", "") or ""
            desc = getattr(tool, "description", "") or ""
            params = [str(getattr(p, "name", p))
                      for p in (getattr(tool, "parameters", None) or [])]
            caps = []
            profile = getattr(tool, "capability_profile", None)
            if profile is not None:
                try:
                    caps = list(profile.get_capability_names())
                except Exception:
                    caps = []
        if not name:
            return None
        caps = sorted({str(getattr(c, "value", c)) for c in caps})
        return str(name), str(desc), params, caps
    except Exception:
        return None


def _fingerprint(records) -> str:
    h = hashlib.sha1()
    h.update(_MODEL_ID.encode())
    h.update(_CACHE_VERSION.encode())
    for name, desc, params, _caps in records:
        h.update(name.encode("utf-8", "ignore"))
        h.update(b"\x00")
        h.update(desc.encode("utf-8", "ignore"))
        h.update(b"\x00")
        h.update(",".join(params).encode("utf-8", "ignore"))
        h.update(b"\x01")
    return h.hexdigest()


def _load_cache(sig: str, n: int):
    arr_path, meta_path = _cache_paths()
    if not (os.path.exists(arr_path) and os.path.exists(meta_path)):
        return None, None
    try:
        with open(meta_path) as f:
            meta = json.load(f)
        if meta.get("sig") != sig or meta.get("n") != n:
            return None, None
        if meta.get("dim") not in (None, _EMB_DIM):
            return None, None
        arr = np.load(arr_path)          # allow_pickle stays off: never execute a cache file
        if not _usable_vectors(arr, 2 * n):
            logger.warning("tool discovery: embedding cache failed validation "
                           "(shape/finiteness) — rebuilding")
            return None, None
        brands = meta.get("brands")
        if not isinstance(brands, list):
            brands = []
        return arr.astype(np.float32, copy=False), {str(b) for b in brands}
    except Exception as e:
        logger.debug("tool discovery: embedding cache unusable: %s", e)
        return None, None


def _save_cache(sig: str, n: int, arr: np.ndarray, brands) -> None:
    arr_path, meta_path = _cache_paths()
    try:
        d = os.path.dirname(arr_path)
        try:
            os.makedirs(d, exist_ok=True)
            probe = tempfile.NamedTemporaryFile(dir=d, delete=True)
            probe.close()
        except Exception:
            d = os.path.join(tempfile.gettempdir(), "torin_tool_discovery")
            os.makedirs(d, exist_ok=True)
            arr_path = os.path.join(d, os.path.basename(arr_path))
            meta_path = os.path.join(d, os.path.basename(meta_path))
        tmp = arr_path + ".tmp.npy"
        np.save(tmp, arr)
        os.replace(tmp, arr_path)
        tmp = meta_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"sig": sig, "n": n, "model": _MODEL_ID, "dim": _EMB_DIM,
                       "version": _CACHE_VERSION, "brands": sorted(brands)}, f)
        os.replace(tmp, meta_path)
    except Exception as e:
        logger.debug("tool discovery: could not write embedding cache: %s", e)


def build_index(tools: Iterable[Any]) -> _Index:
    """Build a ranking index over the live registry's tools.

    `tools` may be Tool instances (name / description / parameters /
    capability_profile are read off them) or plain dicts with those keys.
    """
    records = []
    for t in tools or ():
        rec = _tool_record(t)
        if rec is not None:
            records.append(rec)

    ix = _Index()
    ix.names = [r[0] for r in records]
    ix.n = len(records)
    ix.pos = {n: i for i, n in enumerate(ix.names)}

    lex_docs, sem_texts, name_texts, name_sets = [], [], [], []
    for name, desc, params, _caps in records:
        pretty = _pretty(name)
        n_tok = _tokens(pretty) + _concat_bigrams(_raw_tokens(pretty))
        d_tok = _tokens(desc)
        p_tok = _tokens(" ".join(params))
        # field weighting by repetition; BM25 length-normalizes it back out
        lex_docs.append(n_tok * 3 + d_tok + p_tok)
        name_sets.append(set(n_tok))
        sem_texts.append("{}. {}".format(pretty, _short(desc)))
        name_texts.append(
            "{}{}".format(pretty, (" (" + ", ".join(params) + ")") if params else ""))

    ix.bm25 = _BM25(lex_docs, name_sets)

    # ---- capability graph: a tool x capability membership matrix plus a
    # per-capability discriminative weight.
    cap_df = Counter()
    for _n, _d, _p, caps in records:
        cap_df.update(set(caps))
    ix.cap_col = {c: i for i, c in enumerate(sorted(cap_df))}
    ix.n_caps = len(ix.cap_col)
    N = max(ix.n, 1)
    ix.cap_idf = np.array(
        [math.log(1.0 + (N - cap_df[c] + 0.5) / (cap_df[c] + 0.5))
         for c in sorted(cap_df)], dtype=np.float32)
    ix.cap_B = np.zeros((ix.n, ix.n_caps), dtype=np.float32)   # membership
    for i, (_n, _d, _p, caps) in enumerate(records):
        for c in caps:
            col = ix.cap_col.get(c)
            if col is not None:
                ix.cap_B[i, col] = 1.0
    # Per-capability discriminative weight in [0, 1]: `read_data` (36 providers)
    # says almost nothing about a tool, `query_metrics` (2) says nearly everything.
    max_idf = float(ix.cap_idf.max()) if ix.n_caps else 1.0
    ix.cap_w = (ix.cap_idf / max(max_idf, 1e-6)) if ix.n_caps else np.zeros(0, np.float32)

    # ---- dense vectors, from disk when the catalog has not changed
    sig = _fingerprint(records)
    cached, brands = _load_cache(sig, ix.n)
    if cached is not None:
        ix.emb_sem = cached[: ix.n]
        ix.emb_name = cached[ix.n:]
        ix.brands = brands
        ix.dense_ok = True
        _model()  # warm the encoder so the first rank() is not slow
        if _MODEL is None:
            ix.dense_ok = False
    else:
        sem = _encode(sem_texts) if ix.n else None
        nam = _encode(name_texts) if ix.n else None
        # Vectors are validated on the way out as well as on the way in: a model
        # that returns the wrong shape or a NaN must not be written to the cache
        # and inherited by every later process.
        if not _usable_vectors(sem, ix.n) or not _usable_vectors(nam, ix.n):
            if sem is not None or nam is not None:
                logger.warning("tool discovery: encoder returned unusable vectors "
                               "— dense signal disabled")
            sem = nam = None
        if sem is not None and nam is not None:
            ix.emb_sem, ix.emb_name = sem, nam
            ix.brands = _brand_prefixes(ix.names)
            ix.dense_ok = True
            _save_cache(sig, ix.n, np.vstack([sem, nam]), ix.brands)
        else:
            dim = 384
            ix.emb_sem = np.zeros((ix.n, dim), dtype=np.float32)
            ix.emb_name = np.zeros((ix.n, dim), dtype=np.float32)
            ix.brands = _brand_prefixes(ix.names)
            ix.dense_ok = False

    ix.prefix = [n.split("_")[0].lower() for n in ix.names]
    ix.is_brand = np.array([1.0 if p in ix.brands else 0.0 for p in ix.prefix],
                           dtype=np.float32)
    ix.shell_i = ix.pos.get(_SHELL, -1)
    ix.local_idx = [ix.pos[n] for n in _LOCAL_TOOLS if n in ix.pos]
    ix.perf_idx = [ix.pos[n] for n in _PERF_TOOLS if n in ix.pos]

    vocab = ix.bm25.idf
    ix.expand = {}
    for k, vals in _EXPAND.items():
        keep = [v for v in dict.fromkeys(_stem(v) for v in vals) if v in vocab]
        if keep:
            ix.expand[_stem(k)] = keep

    ix.generalist_rows = {ix.pos[n]: lift for n, lift in GENERALISTS.items()
                          if n in ix.pos}
    _cap_fn()  # resolve capability inference now, not on the hot path
    return ix


# =========================================================================rank

W_DENSE = 0.55
W_LEX = 0.45
W_LEX_NODENSE = 0.85   # lexical weight when embeddings are unavailable
W_RRF = 0.18
RRF_K = 60.0
DENSE_FULL = 0.62      # cosine treated as a "perfect" semantic match
LEX_FULL = 0.55        # fraction of query IDF mass treated as full coverage
BRAND_PENALTY = 0.30
BRAND_FLOOR = 0.45     # share of the vendor penalty that always applies
WEAK_TOP = 0.46        # base fused score below which nothing really fits
FAMILY_CAP = 2         # max results from one vendor namespace

EXPANSION_WEIGHT = 0.42     # vocabulary bridge, a guess about intent
ENTITY_WEIGHT = 0.85        # injected indicator vocabulary, near-literal weight
ENTITY_WEIGHT_PLAIN = 0.60  # same, with no security intent expressed
ENTITY_BRAND_RELIEF = 0.35  # an IOC lookup really is a vendor call
CODE_LOC_WEIGHT = 0.62      # injected code-search vocabulary

# Capability fusion.
CAP_FLOOR = 1.0        # min confidence from capabilities.py to consider
CAP_CONF_CAP = 7.0     # confidences are 0-10; clamp so one pattern cannot swamp
CAP_W_POW = 1.3        # exponent on the per-capability discriminative weight
W_CAP = 0.26           # weight of the query -> capability match
W_CAP_RRF = 0.3        # capability rank's share of the RRF vote
W_SIB = 0.25           # weight of capability-graph pseudo-relevance feedback
SIB_TOP = 2            # how many leading tools seed the sibling profile
SIB_MIN_LEAD = 0.42    # do not propagate from a lead nothing really matched
SIB_PROTECT = 3        # leading ranks the sibling boost may not reorder (0 = off)

# Generalist floor, anchored to this query's own score spread.
FLOOR_MAX = 1.0
FLOOR_BOTTOM = 11    # rank whose score counts as "no lift at all"
FLOOR_GAMMA = 1.55   # >1: partial coverage still buries the generalists
GENERALISTS = {
    "run_shell_command": 1.00,
    "system_info": 0.30,
}


def _rrf(scores: np.ndarray) -> np.ndarray:
    order = np.argsort(-scores, kind="stable")
    r = np.empty(len(scores), dtype=np.float32)
    r[order] = np.arange(len(scores), dtype=np.float32)
    return (1.0 / (RRF_K + r + 1.0)).astype(np.float32)


def _coverage(ix, q_tok) -> float:
    return ix.bm25.coverage(list(dict.fromkeys(q_tok)))


def _select(ix, fused: np.ndarray, k: int) -> List[int]:
    """Top k by score, but never let one vendor namespace flood the list."""
    k = min(k, ix.n)
    order = np.argsort(-fused, kind="stable")
    chosen, used, deferred = [], Counter(), []
    for i in order:
        if len(chosen) >= k:
            break
        p = ix.prefix[i]
        if p in ix.brands:
            if used[p] >= FAMILY_CAP:
                deferred.append(i)
                continue
            used[p] += 1
        chosen.append(int(i))
    for i in deferred:                      # backfill if we ran short
        if len(chosen) >= k:
            break
        chosen.append(int(i))
    return chosen


def _rank_lexical(ix, query: str, k: int) -> List[Tuple[str, float]]:
    """Last-resort path: BM25 only. Used if the fused ranker raises."""
    try:
        toks = _tokens(query)
        if not toks:
            return [(n, 0.0) for n in ix.names[:k]]
        lex, _ideal = ix.bm25.score(toks)
        order = np.argsort(-lex, kind="stable")[:k]
        return [(ix.names[int(i)], float(lex[int(i)])) for i in order]
    except Exception:
        return [(n, 0.0) for n in ix.names[:k]]


def _rank(ix, query: str, k: int) -> List[Tuple[str, float]]:
    q = (query or "").strip()
    if not q or ix.n == 0:
        return [(n, 0.0) for n in ix.names[:k]]

    ents = _entities(q)
    raw = _raw_tokens(q)
    q_tok = _tokens(q)
    q_big = _concat_bigrams(raw)

    toks = list(q_tok) + list(q_big)
    wts = [1.0] * len(q_tok) + [0.6] * len(q_big)

    for t, w in _expansions(ix, q_tok).items():
        toks.append(t)
        wts.append(w)

    dense_text = q

    # code-location intent: none of "where / live / logic" appears in the search
    # tools' own text, so supply the words they are written in.
    if _code_location(q):
        seen = set(toks)
        for t in _CODE_LOC_TERMS:
            s = _stem(t)
            if s not in seen:
                seen.add(s)
                toks.append(s)
                wts.append(CODE_LOC_WEIGHT)
        dense_text = "{} . {}".format(q, _CODE_LOC_HINT)

    sec = bool(ents) and _security_intent(q)
    if ents:
        terms = _ENTITY_TERMS if sec else _ENTITY_TERMS_PLAIN
        hints = _ENTITY_HINT if sec else _ENTITY_HINT_PLAIN
        w = ENTITY_WEIGHT if sec else ENTITY_WEIGHT_PLAIN
        seen = set(toks)
        hint = []
        for kind in ents:
            for t in terms[kind]:
                s = _stem(t)
                if s not in seen:
                    seen.add(s)
                    toks.append(s)
                    wts.append(w)
            hint.append(hints[kind])
        dense_text = "{} . {}".format(dense_text, " ".join(hint))

    lex, ideal = ix.bm25.score(toks, wts)

    qv = _encode([dense_text]) if ix.dense_ok else None
    if qv is not None and not _usable_vectors(qv, 1):
        # Turn the dense signal off for good rather than raise once per query:
        # an exception here would drop every later call to the BM25-only
        # fallback, which loses the capability and generalist-floor signals too.
        logger.warning("tool discovery: query vector unusable — dense signal disabled")
        ix.dense_ok = False
        qv = None
    if qv is None:
        dense = np.zeros(ix.n, dtype=np.float32)
        dense_n = dense
        lex_n = np.clip(lex / max(LEX_FULL * ideal, 1e-6), 0.0, 1.15)
        rrf = _rrf(lex)
        w_dense = 0.0
        w_lex = W_LEX_NODENSE
    else:
        qv = qv[0]
        cos_sem = ix.emb_sem @ qv
        cos_name = ix.emb_name @ qv
        dense = 0.68 * cos_sem + 0.32 * cos_name
        dense = np.maximum(dense, 0.85 * np.maximum(cos_sem, cos_name))
        # Absolute normalization: a query nothing matches must stay low, so the
        # top hit is NOT stretched to 1.0 the way min-max would.
        dense_n = np.clip(np.clip(dense, 0.0, None) / DENSE_FULL, 0.0, 1.15)
        lex_n = np.clip(lex / max(LEX_FULL * ideal, 1e-6), 0.0, 1.15)
        rrf = _rrf(dense) + _rrf(lex)
        w_dense = W_DENSE
        w_lex = W_LEX

    # ---- capability signal: what TorinAI knows that a text ranker does not
    cap_direct = None
    if ix.n_caps:
        demand = _cap_demand(ix, _infer_caps(q))
        if demand is not None:
            # A tool scores on its single best-matching capability, not on the
            # sum: overlapping on three vague ones ("read_data", "analyze_code")
            # must not outrank actually providing the one that was asked for.
            cap_direct = (ix.cap_B * demand).max(axis=1)
            rrf = rrf + W_CAP_RRF * _rrf(cap_direct)

    rrf_n = rrf / max(float(rrf.max()), 1e-9)
    fused = w_dense * dense_n + w_lex * lex_n + W_RRF * rrf_n
    base = fused.copy()

    if cap_direct is not None:
        fused = fused + W_CAP * cap_direct

    # exact tool-name mention wins outright
    qflat = " " + re.sub(r"[^a-z0-9]+", " ", q.lower()) + " "
    qsquash = qflat.replace(" ", "")
    for i, n in enumerate(ix.names):
        if " " + n.replace("_", " ") + " " in qflat:
            fused[i] += 1.5

    # Vendor gate: a splunk_/crowdstrike_/github_ tool is a priori unlikely
    # unless the user named that vendor — but only a prior: strong semantic
    # evidence dissolves the penalty, so "quarantine the infected laptop" can
    # still reach crowdstrike_contain_host.
    if ix.brands:
        qwords = set(raw)
        mentioned = np.array(
            [1.0 if p in ix.brands and (p in qwords or (len(p) >= 6 and p in qsquash))
             else 0.0 for p in ix.prefix], dtype=np.float32)
        evidence = np.clip(dense_n if ix.dense_ok else lex_n, 0.0, 1.0)
        relief = BRAND_FLOOR + (1.0 - BRAND_FLOOR) * (1.0 - evidence)
        penalty = BRAND_PENALTY * (ENTITY_BRAND_RELIEF if sec else 1.0)
        fused -= penalty * ix.is_brand * (1.0 - mentioned) * relief

    # ---- capability-graph pseudo-relevance feedback.
    # The tools already leading the list vouch for a region of the capability
    # graph; their siblings there are the ones a text ranker misses (a query
    # names one way of doing the job, the registry offers three).
    if W_SIB > 0.0 and ix.n_caps and ix.n > 1:
        lead = float(fused.max())
        if lead >= SIB_MIN_LEAD:
            top = np.argsort(-fused, kind="stable")[:min(SIB_TOP, ix.n)]
            w = np.clip(fused[top] / max(lead, 1e-6), 0.0, 1.0)
            # How strongly the leaders vouch for each capability, then, per tool,
            # its single strongest shared capability. A max (not a sum) so a tool
            # cannot accumulate a high score out of several vague generic
            # overlaps — it has to actually do the same specific thing.
            mass = (ix.cap_B[top] * w[:, None]).max(axis=0) * ix.cap_w ** CAP_W_POW
            sib = (ix.cap_B * mass).max(axis=1)
            sib[top] = 0.0                  # do not re-reward the seeds
            if SIB_PROTECT > 0 and ix.n > SIB_PROTECT:
                # Sibling evidence is corroboration, not a reason to lead: it
                # reorders the tail of the shortlist (where recall is won) and is
                # forbidden from disturbing the head (where precision is won).
                order = np.argsort(-fused, kind="stable")
                head = order[:SIB_PROTECT]
                ceiling = float(fused[head[-1]]) - 1e-4
                boosted = fused + W_SIB * sib
                np.minimum(boosted, ceiling, out=boosted)
                boosted[head] = fused[head]
                fused = boosted
            else:
                fused = fused + W_SIB * sib

    # ---- fallback: machine-inspection questions, or nothing fits at all
    mach, shell_ok, is_perf = _machine_signal(q, ents)
    weak = float(base.max()) < WEAK_TOP

    if is_perf and ix.perf_idx:
        fused[ix.perf_idx] += 0.34 * mach

    if ix.shell_i >= 0 and shell_ok and (mach > 0 or weak):
        if mach > 0 and ix.local_idx:
            fused[ix.local_idx] += 0.30 * mach
        specific = max((float(dense[j]) for j in ix.local_idx if j != ix.shell_i),
                       default=0.0)
        order = np.argsort(-fused, kind="stable")
        lead = float(fused[order[0]])
        if (mach >= 0.8 and specific < 0.45) or (weak and mach >= 0.8):
            target = lead + 0.05                                   # lead the list
        else:
            target = float(fused[order[min(2, ix.n - 1)]]) + 0.01  # slot into top 3
        fused[ix.shell_i] = max(float(fused[ix.shell_i]), target)

    # ---- generalist floor: absolute, coverage-adaptive. Fires whenever the
    # registry simply has no vocabulary for what was asked ("git diff", "what
    # version of node"), which no per-query heuristic can enumerate.
    if ix.generalist_rows and not ents:
        cov = _coverage(ix, q_tok)
        m = min(FLOOR_BOTTOM + 1, ix.n)
        part = np.partition(fused, -m)
        hi = float(fused.max()) + 0.05
        lo = float(part[-m])
        room = max(hi - lo, 0.0)
        floor = FLOOR_MAX * ((1.0 - cov) ** FLOOR_GAMMA)
        for row, lift in ix.generalist_rows.items():
            fused[row] = max(float(fused[row]), lo + room * floor * lift)

    return [(ix.names[i], float(fused[i])) for i in _select(ix, fused, k)]


def rank(index, query: str, k: int = 8) -> List[str]:
    """Rank tool names for a query. Never raises."""
    return [name for name, _ in rank_scored(index, query, k)]


def rank_scored(index, query: str, k: int = 8) -> List[Tuple[str, float]]:
    """Rank (name, score) pairs, best first. Never raises.

    The score is the ranker's fused relevance. It is not calibrated across
    queries — compare it against the other scores in the same result. A caller
    that wants to drop noise should do it relative to the top score, because a
    query the registry has no vocabulary for still fills k slots.
    """
    if index is None or getattr(index, "n", 0) == 0:
        return []
    try:
        return _rank(index, query, k)
    except Exception as e:
        logger.warning("tool discovery: ranking failed (%s: %s) — lexical fallback",
                       type(e).__name__, e)
        return _rank_lexical(index, query, k)


# bench harnesses expect build()/rank()
build = build_index


# ====================================================== registry-facing facade
#
# ToolRegistry is a process-wide singleton reached from async code, so the index
# it ranks against lives here, behind a lock, built on the first discover().

_INDEX = None
_INDEX_SIG: Optional[str] = None
_INDEX_LOCK = threading.Lock()


def _catalog_signature(tools: Sequence[Any]) -> str:
    """Cheap in-memory invalidation key: the tool names, in order.

    Deliberately not the full fingerprint build_index() uses for the on-disk
    vectors. That one hashes descriptions and parameters too and costs ~0.7 ms,
    which is ~15% of a whole query, and it would be paid on every call to detect
    a change that cannot happen at runtime: tools register once at startup and
    their descriptions are literals in source. A description edit still
    invalidates the disk cache on the next process start, where the full
    fingerprint is computed once.
    """
    h = hashlib.sha1()
    for t in tools:
        try:
            name = t.get("name") if isinstance(t, dict) else getattr(t, "name", "")
        except Exception:
            name = ""
        h.update(((name or "") + "\0").encode("utf-8", "replace"))
    return h.hexdigest()


def get_index(tools: Iterable[Any]):
    """The shared index for this catalog, rebuilt only when the catalog changes."""
    global _INDEX, _INDEX_SIG
    tools = list(tools)
    sig = _catalog_signature(tools)
    if _INDEX is not None and _INDEX_SIG == sig:
        return _INDEX
    with _INDEX_LOCK:
        if _INDEX is not None and _INDEX_SIG == sig:
            return _INDEX
        index = build_index(tools)
        _INDEX, _INDEX_SIG = index, sig
        return index


def discover(tools: Iterable[Any], query: str, limit: int = 10) -> List[str]:
    """Rank `tools` against `query` and return the best tool NAMES, best first.

    The entry point ToolRegistry.discover_tools() delegates to. Never raises:
    any failure below degrades to lexical ranking, and a failure to build at all
    returns an empty list.
    """
    return [name for name, _ in discover_scored(tools, query, limit)]


def discover_scored(tools: Iterable[Any], query: str,
                    limit: int = 10) -> List[Tuple[str, float]]:
    """discover() with the ranker's relevance score kept. Never raises."""
    if not query or not isinstance(query, str) or not query.strip():
        return []
    try:
        limit = max(0, int(limit))
    except Exception:
        limit = 10
    if limit == 0:
        return []
    try:
        index = get_index(tools)
    except Exception as e:
        # `except` must not turn a wiring defect into an empty result.
        raise_if_structural(e, 'tool_discovery.discover_scored')
        logger.warning(
            "tool discovery: index build failed (%s: %s) — no ranking available",
            type(e).__name__, e)
        return []
    return rank_scored(index, query, limit)


def reset() -> None:
    """Drop the shared index. For tests and for a registry rebuilt in place."""
    global _INDEX, _INDEX_SIG
    with _INDEX_LOCK:
        _INDEX, _INDEX_SIG = None, None
