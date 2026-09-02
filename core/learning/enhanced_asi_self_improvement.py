#!/usr/bin/env python3
"""
Enhanced ASI Self-Improvement System
=====================================
Advanced self-improvement orchestration for ASI development

Integrates all learning components into unified improvement cycles:
- Continuous learning pipeline
- Meta-learning strategies
- Code generation & deployment (via Unified LLM - Unified LLM local)
- Performance monitoring
- Frontier capability forecasting
- Safety boundary enforcement

This system enables safe, measured self-improvement with:
- Multi-level evaluation
- Rollback capabilities
- Human oversight requirements
- Comprehensive audit trails

LLM Integration: Uses Unified LLM service (Unified LLM local model) for:
- Code generation
- Analysis and reasoning
- Impact assessment
- Strategy selection
"""

import hashlib
import asyncio
import logging
import json
import os
import re
import ast
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from enum import Enum
from collections import defaultdict
import time
from contextlib import asynccontextmanager

from core.capability import raise_if_structural

# EVERY ONE OF THESE IS AN IN-REPO MODULE, SO NONE OF THEM IS OPTIONAL.
#
# All twelve sat behind `try: ... except ImportError: name = None`, the idiom
# for a dependency that may genuinely be absent. None of them can be: they are
# `core.learning.*`, `core.services.*`, `core.tools`, `core.governance`,
# `core.memory` — they ship in this repository and all twelve import cleanly.
#
# What the guard bought was silence. A typo in a module, a broken import inside
# one of them, a renamed symbol — any of it turned the name to None, and the
# capability that needed it degraded at some later point with a log line, or
# not even that. That is the failure mode this file exists to prevent in other
# components, and it was load-bearing in its own imports.
#
# Imported plainly. If one of these cannot be imported, this module cannot do
# its job, and it should say so at import time rather than at the point where
# some phase quietly returns nothing.
from core.learning.meta_learning import get_meta_learner, LearningStrategy
from core.learning.improvement_monitor import get_improvement_monitor, MetricType
from core.learning.upgrade_validator import get_upgrade_validator
from core.learning.safe_upgrade_deployer import get_safe_deployer, DeploymentStrategy
from core.learning.safety_audit_trail import get_safety_audit_trail, SafetyEventType
from core.learning.performance_profiler import get_performance_profiler
from core.learning.capability_benchmark_suite import get_capability_benchmark_suite
from core.tools import get_tool_registry
from core.governance import get_unified_governance, ActionCategory
from core.memory import get_memory_agent, MemoryType, MemoryPriority

from core.learning.learning_interfaces import IAdaptationEngine

logger = logging.getLogger(__name__)

#: Consecutive cycles the capability benchmarks may fail to run before further
#: self-modification is refused. One unverified cycle is a blip -- the suite
#: needs an LLM service and one may be briefly down. A run of them means the
#: system is changing itself while blind to whether it is losing competence,
#: which is the capability narrowing the benchmark phase exists to prevent.
#: Counted in-process: the streak resets on restart, so this bounds a single
#: run rather than all of history.
MAX_UNVERIFIED_CAPABILITY_CYCLES = 3


#: Filesystem calls that delete. Matched on the call name so the idiom used
#: -- os.remove, shutil.rmtree, Path(p).unlink() -- does not decide the verdict.
_DESTRUCTIVE_ATTRS = frozenset({
    "rmtree", "remove", "unlink", "rmdir", "removedirs", "truncate",
})


class StaticCodeAnalyzer:
    """
    Deterministic static analysis for generated code.
    Catches dangerous patterns that LLM verification might miss.
    """

    # Dangerous patterns that should NEVER appear in generated code
    DANGEROUS_PATTERNS = [
        (r'\bexec\s*\(', "exec() allows arbitrary code execution"),
        (r'\beval\s*\(', "eval() allows arbitrary code execution"),
        (r'\b__import__\s*\(', "__import__() can load arbitrary modules"),
        (r'\bcompile\s*\(', "compile() can execute arbitrary code"),
        (r'sys\.modules\s*\[', "Direct sys.modules manipulation is dangerous"),
        (r'globals\s*\(\s*\)\s*\[', "Direct globals() manipulation is dangerous"),
        (r'locals\s*\(\s*\)\s*\[', "Direct locals() manipulation is dangerous"),
        (r'__builtins__', "Accessing __builtins__ is dangerous"),
        (r'subprocess\.(?:call|run|Popen).*shell\s*=\s*True', "Shell=True enables command injection"),
        (r'os\.system\s*\(', "os.system() enables command injection"),
        (r'open\s*\([^)]*[\'"]w[\'"]', "File writing should be controlled"),
        (r'pickle\.loads?\s*\(', "Pickle can execute arbitrary code"),
        (r'yaml\.load\s*\((?!.*Loader)', "yaml.load without safe loader is dangerous"),
        (r'rm\s+-rf', "Destructive file operations in shell commands"),
        (r'DROP\s+(?:TABLE|DATABASE)', "SQL DROP operations are destructive"),
        (r'DELETE\s+FROM.*WHERE\s+1\s*=\s*1', "Dangerous SQL DELETE without proper WHERE clause"),
        # The dunders actually used to climb out of a sandbox --
        # ().__class__.__bases__[0].__subclasses__(), f.__globals__['__builtins__'].
        # These replace a blanket `__[a-zA-Z_]+__` match that lived in the
        # SUSPICIOUS list: it flagged `__init__`, `__name__` and `__main__`, so
        # with strict=True (what the one caller uses) every ordinary Python
        # class and module guard failed the hard gate. Naming the escape chain
        # catches more than the blanket did -- it is DANGEROUS, not "review" --
        # while ordinary code stops being rejected.
        (r'\.__(?:subclasses|globals|code|closure|bases|mro|func|self|reduce|reduce_ex)__\b',
         "Dunder attribute used in sandbox-escape chains"),
        # Fallback spellings for the unparseable path; the AST pass states these
        # precisely and these are skipped when the code parsed.
        (r'shutil\.rmtree\s*\(', "Recursive directory deletion"),
        (r'os\.(?:remove|unlink|rmdir|removedirs)\s*\(', "File or directory deletion"),
        (r'\.write_(?:text|bytes)\s*\(', "File writing should be controlled"),
    ]

    #: The DANGEROUS_PATTERNS the AST pass proves more precisely. Skipped when
    #: the code parsed, so one call yields one finding; applied when it does not
    #: parse, where they are the only analysis that can still run.
    _AST_COVERED_PATTERNS = frozenset({
        r'\bexec\s*\(',
        r'\beval\s*\(',
        r'\b__import__\s*\(',
        r'\bcompile\s*\(',
        r'globals\s*\(\s*\)\s*\[',
        r'locals\s*\(\s*\)\s*\[',
        r'subprocess\.(?:call|run|Popen).*shell\s*=\s*True',
        r'os\.system\s*\(',
        r'open\s*\([^)]*[\'"]w[\'"]',
        r'shutil\.rmtree\s*\(',
        r'os\.(?:remove|unlink|rmdir|removedirs)\s*\(',
        r'\.write_(?:text|bytes)\s*\(',
    })

    # Suspicious patterns that should be reviewed (not automatic failure)
    #
    # getattr/setattr were dropped from this list: the AST pass reports the same
    # calls and can tell `getattr(o, "name")` from `getattr(o, "exec")`, so
    # keeping the regexes only produced a second finding for one call and made
    # every count read double.
    SUSPICIOUS_PATTERNS = [
        (r'import\s+(?:socket|urllib|requests)', "Network access in generated code"),
        (r'open\s*\(', "File I/O operations should be reviewed"),
    ]

    @staticmethod
    def analyze(code: str, strict: bool = True) -> Dict[str, Any]:
        """
        Perform static analysis on generated code.

        Args:
            code: Code to analyze
            strict: If True, suspicious patterns also cause failures

        Returns:
            Dict with analysis results:
            {
                "safe": bool,
                "dangerous_patterns": List[Dict],
                "suspicious_patterns": List[Dict],
                "reason": str
            }
        """
        # A non-string reached re.finditer as "expected string or bytes-like
        # object, got 'NoneType'" from deep inside the scan. Generation
        # returning None is an upstream fault, and it should say so here rather
        # than surface as a regex error.
        if not isinstance(code, str):
            raise TypeError(
                f"StaticCodeAnalyzer.analyze() requires source text, got "
                f"{type(code).__name__}; the generation step produced no code")

        dangerous_found = []
        suspicious_found = []

        # NOTHING TO ANALYSE IS NOT A PASS. Empty, blank and comment-only input
        # matched no pattern, so the result was safe=True with the reason "Code
        # passed static analysis" -- an absence of code reported as code that
        # had been checked and cleared. This is the first hard gate before
        # deployment, so it fails closed instead.
        if not StaticCodeAnalyzer._has_executable_code(code):
            return {
                "safe": False,
                "dangerous_patterns": [],
                "suspicious_patterns": [],
                "reason": "No executable code to analyse — nothing was verified",
            }

        # AST-based analysis to catch dynamic/indirect execution patterns that
        # regex scans often miss (e.g., getattr(x, "exec")(...)).
        ast_dangerous, ast_suspicious, parsed = StaticCodeAnalyzer._analyze_ast(code)
        dangerous_found.extend(ast_dangerous)
        suspicious_found.extend(ast_suspicious)

        # ONE FINDING PER FACT. Both layers detect exec/eval/os.system/shell=True,
        # so a single `os.system("rm -rf /")` was reported three times and the
        # reason read "Found 3 dangerous pattern(s)" for one call. Where the code
        # parsed, the AST pass is authoritative for what it can prove -- it knows
        # `os.system` from a variable named `system` -- and these regexes are the
        # cruder statement of the same rule.
        #
        # They are NOT dropped: when parsing fails there is no AST to be
        # authoritative, and then they are the only defence left.
        skip = StaticCodeAnalyzer._AST_COVERED_PATTERNS if parsed else frozenset()

        # Check for dangerous patterns
        for pattern, reason in StaticCodeAnalyzer.DANGEROUS_PATTERNS:
            if pattern in skip:
                continue
            matches = list(re.finditer(pattern, code, re.IGNORECASE | re.MULTILINE))
            if matches:
                for match in matches:
                    line_num = code[:match.start()].count('\n') + 1
                    dangerous_found.append({
                        "pattern": pattern,
                        "reason": reason,
                        "line": line_num,
                        "match": match.group(0)
                    })

        # Check for suspicious patterns
        for pattern, reason in StaticCodeAnalyzer.SUSPICIOUS_PATTERNS:
            matches = list(re.finditer(pattern, code, re.IGNORECASE | re.MULTILINE))
            if matches:
                for match in matches:
                    line_num = code[:match.start()].count('\n') + 1
                    suspicious_found.append({
                        "pattern": pattern,
                        "reason": reason,
                        "line": line_num,
                        "match": match.group(0)
                    })

        # Determine if code is safe
        is_safe = len(dangerous_found) == 0
        if strict:
            is_safe = is_safe and len(suspicious_found) == 0

        # Build result
        result = {
            "safe": is_safe,
            "dangerous_patterns": dangerous_found,
            "suspicious_patterns": suspicious_found,
            "reason": ""
        }

        if dangerous_found:
            result["reason"] = f"Found {len(dangerous_found)} dangerous pattern(s): " + \
                             ", ".join([f"{d['reason']} at line {d['line']}" for d in dangerous_found])
        elif suspicious_found and strict:
            result["reason"] = f"Found {len(suspicious_found)} suspicious pattern(s): " + \
                             ", ".join([f"{s['reason']} at line {s['line']}" for s in suspicious_found])
        else:
            result["reason"] = "Code passed static analysis"

        return result

    @staticmethod
    def _has_executable_code(code: str) -> bool:
        """Whether there is anything here that DOES something.

        Parsed rather than pattern-matched, so a docstring-only or comment-only
        body is recognised as carrying no statements. Unparseable input counts
        as code: it still has to reach the analysis and be reported as a syntax
        finding, not dismissed as empty.

        THE STUB SHAPES COUNT AS EMPTY, and they are what a generator actually
        emits. This caught zero-byte and comment-only input, and passed all
        three of these, which are the emptiest improvements anything real
        produces:

            def improve_component(): pass
            def improve_component(): ...
            import os                      # and nothing else

        Measured: each returned True, so `_test_improvements` would record a
        passed sandbox test for a function that does nothing. A gate that
        accepts `pass` is not meaningfully stricter than one that accepts "".
        """
        if not code.strip():
            return False
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return True

        def _is_inert(node) -> bool:
            """A statement that cannot change anything."""
            if isinstance(node, (ast.Pass, ast.Import, ast.ImportFrom)):
                return True
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
                return True                      # docstring or bare literal
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Ellipsis):
                return True                      # `...` on older grammars
            # A definition whose whole body is inert defines nothing that acts.
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                return all(_is_inert(child) for child in node.body)
            return False

        return any(not _is_inert(node) for node in tree.body)

    @staticmethod
    def _analyze_ast(code: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], bool]:
        """AST-based analysis to detect indirect execution and dynamic imports.

        Returns (dangerous, suspicious, parsed). Findings use the same shape as
        the regex ones. `parsed` tells the caller whether this pass could be
        authoritative: when the code did not parse there is no AST to reason
        over, and the regex layer must run its overlapping rules instead.
        """

        def _finding(kind: str, reason: str, line: int, match: str) -> Dict[str, Any]:
            return {
                "pattern": f"ast:{kind}",
                "reason": reason,
                "line": int(line or 0) or 1,
                "match": match,
            }

        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            line = getattr(e, "lineno", 1) or 1
            msg = getattr(e, "msg", "syntax error")
            return (
                [_finding("syntax_error", f"Code does not parse: {msg}", line, "ast.parse")],
                [],
                False,
            )
        except Exception as e:
            # AN ANALYSIS THAT DID NOT RUN FOUND NOTHING DANGEROUS -- and that is
            # exactly what returning ([], []) claimed. This is the layer that
            # catches indirect execution the regexes miss, so silently yielding
            # no findings made a crashed scan indistinguishable from clean code
            # on the deployment gate. Reported as a dangerous finding: the gate
            # must not clear code the analyser could not read.
            logger.error("AST analysis failed: %s: %s", type(e).__name__, e)
            return (
                [_finding("analysis_failed",
                          f"Static AST analysis could not run ({type(e).__name__}: {e}); "
                          f"code cannot be cleared",
                          1, "ast.parse")],
                [],
                False,
            )

        dangerous: List[Dict[str, Any]] = []
        suspicious: List[Dict[str, Any]] = []

        dangerous_call_names = {"exec", "eval", "compile", "__import__"}

        def _node_text(node: ast.AST) -> str:
            try:
                seg = ast.get_source_segment(code, node)
                if seg:
                    return seg.strip()
            except Exception:
                pass
            try:
                return ast.unparse(node).strip()  # type: ignore[attr-defined]
            except Exception:
                return node.__class__.__name__

        def _const_str(node: ast.AST) -> Optional[str]:
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                return node.value
            return None

        for node in ast.walk(tree):
            # Direct calls: exec(...), eval(...), compile(...), __import__(...)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                fn = node.func.id
                if fn in dangerous_call_names:
                    dangerous.append(
                        _finding(
                            f"call_{fn}",
                            f"{fn}() allows arbitrary code execution",
                            getattr(node, "lineno", 1),
                            _node_text(node),
                        )
                    )

                if fn in {"getattr", "setattr"}:
                    # getattr(obj, "exec")(...), setattr(obj, "__import__", ...)
                    if len(node.args) >= 2:
                        name = _const_str(node.args[1])
                        if name in {"exec", "eval", "__import__", "compile", "system", "popen", "Popen"}:
                            dangerous.append(
                                _finding(
                                    f"{fn}_danger_name",
                                    f"{fn}() used to access dangerous attribute '{name}'",
                                    getattr(node, "lineno", 1),
                                    _node_text(node),
                                )
                            )
                        elif name is None:
                            # ONLY A NON-CONSTANT NAME IS DYNAMIC. This flagged
                            # every getattr/setattr, so `getattr(o, "name")` --
                            # which is exactly `o.name` and has nothing to
                            # review -- failed the strict gate. What cannot be
                            # checked statically is a computed name:
                            # getattr(o, user_input) is unknowable from here,
                            # and that is the case worth reviewing.
                            suspicious.append(
                                _finding(
                                    f"{fn}_dynamic",
                                    f"{fn}() with a computed attribute name cannot be "
                                    f"checked statically and should be reviewed",
                                    getattr(node, "lineno", 1),
                                    _node_text(node),
                                )
                            )

                if fn == "open":
                    # The regex required a literal 'w', so 'wb', 'a', 'x' and a
                    # variable mode were all read as harmless. A mode that
                    # cannot be resolved statically is not evidence of a read:
                    # open(p, mode) is reported, because nothing here can show
                    # it is not a write.
                    mode = _const_str(node.args[1]) if len(node.args) >= 2 else None
                    for kw in node.keywords or []:
                        if kw.arg == "mode":
                            mode = _const_str(kw.value)
                    computed = (len(node.args) >= 2 and mode is None) or any(
                        kw.arg == "mode" and _const_str(kw.value) is None
                        for kw in node.keywords or [])
                    if mode is not None and any(ch in mode for ch in "wax+"):
                        dangerous.append(
                            _finding(
                                "fs_open_write",
                                f"open() in mode {mode!r} writes to the filesystem; "
                                f"file writing should be controlled",
                                getattr(node, "lineno", 1), _node_text(node)))
                    elif computed:
                        dangerous.append(
                            _finding(
                                "fs_open_computed_mode",
                                "open() with a computed mode cannot be shown to be "
                                "read-only",
                                getattr(node, "lineno", 1), _node_text(node)))

                if fn in {"globals", "locals", "vars"}:
                    # globals()["exec"](...), vars(builtins)["eval"](...)
                    suspicious.append(
                        _finding(
                            f"{fn}_use",
                            f"{fn}() access can enable indirect execution; review required",
                            getattr(node, "lineno", 1),
                            _node_text(node),
                        )
                    )

            # Indirect patterns: globals()["exec"], locals()["eval"], vars()["__import__"]
            if isinstance(node, ast.Subscript):
                base = node.value
                if isinstance(base, ast.Call) and isinstance(base.func, ast.Name):
                    base_name = base.func.id
                    if base_name in {"globals", "locals", "vars"}:
                        key = None
                        try:
                            # py3.9+: slice is expr
                            key = _const_str(node.slice)  # type: ignore[arg-type]
                        except Exception:
                            key = None

                        if key in {"exec", "eval", "compile", "__import__", "__builtins__"}:
                            dangerous.append(
                                _finding(
                                    f"{base_name}_subscript_danger",
                                    f"{base_name}()[{key!r}] enables indirect execution",
                                    getattr(node, "lineno", 1),
                                    _node_text(node),
                                )
                            )

            # Dynamic import patterns: importlib.import_module(x)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                attr = node.func.attr
                # importlib.import_module(...)
                if attr in {"import_module", "reload"}:
                    suspicious.append(
                        _finding(
                            f"importlib_{attr}",
                            f"Dynamic import via importlib.{attr}() should be reviewed",
                            getattr(node, "lineno", 1),
                            _node_text(node),
                        )
                    )

                # subprocess.run/call/Popen with shell=True
                if attr in {"run", "call", "Popen"}:
                    if isinstance(node.func.value, ast.Name) and node.func.value.id == "subprocess":
                        for kw in node.keywords or []:
                            if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                                dangerous.append(
                                    _finding(
                                        "subprocess_shell_true",
                                        "subprocess.* with shell=True enables command injection",
                                        getattr(node, "lineno", 1),
                                        _node_text(node),
                                    )
                                )

                # os.system(...)
                if attr == "system":
                    if isinstance(node.func.value, ast.Name) and node.func.value.id == "os":
                        dangerous.append(
                            _finding(
                                "os_system",
                                "os.system() enables command injection",
                                getattr(node, "lineno", 1),
                                _node_text(node),
                            )
                        )

                # DESTRUCTIVE AND WRITING FILESYSTEM CALLS.
                #
                # The only filesystem rule was one regex for open(..., 'w'), so
                # the policy it stated -- generated code does not write or delete
                # files -- held for exactly one spelling. open(p,'wb'),
                # open(p,'a'), open(p,mode), Path(p).write_text(), os.remove()
                # and shutil.rmtree() all cleared the gate, while the shell
                # string `rm -rf` was blocked. Recursive directory deletion
                # passing while its shell equivalent failed is a rule that
                # rewards phrasing rather than detecting the operation.
                #
                # Matched on the call here, so spelling stops mattering.
                if attr in _DESTRUCTIVE_ATTRS:
                    dangerous.append(
                        _finding(
                            f"fs_destructive_{attr}",
                            f"{attr}() deletes files or directories",
                            getattr(node, "lineno", 1),
                            _node_text(node),
                        )
                    )
                if attr in {"write_text", "write_bytes"}:
                    dangerous.append(
                        _finding(
                            f"fs_write_{attr}",
                            f"{attr}() writes to the filesystem; file writing "
                            f"should be controlled",
                            getattr(node, "lineno", 1),
                            _node_text(node),
                        )
                    )

        return (dangerous, suspicious, True)


class ImprovementPhase(Enum):
    """Phases of self-improvement cycle"""
    ASSESSMENT = "assessment"
    PLANNING = "planning"
    GENERATION = "generation"
    VALIDATION = "validation"
    TESTING = "testing"
    DEPLOYMENT = "deployment"
    EVALUATION = "evaluation"
    REFLECTION = "reflection"


class ImprovementScope(Enum):
    """Scope of improvement"""
    MINOR = "minor"  # Small optimization, low risk
    MODERATE = "moderate"  # Feature enhancement, medium risk
    MAJOR = "major"  # Significant change, high risk
    TRANSFORMATIVE = "transformative"  # Capability expansion, requires human approval


@dataclass
class ImprovementTarget:
    """Target for self-improvement"""
    target_id: str
    component: str
    metric: str
    current_value: float
    target_value: float

    # Analysis
    improvement_potential: float  # 0-100%
    difficulty: str  # "easy", "medium", "hard", "very_hard"
    risk_level: str  # "low", "medium", "high", "critical"

    # Metadata
    identified_at: datetime = field(default_factory=datetime.now)
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ImprovementCycle:
    """Complete self-improvement cycle"""
    cycle_id: str
    phase: ImprovementPhase
    scope: ImprovementScope

    # Targets
    targets: List[ImprovementTarget]

    # Results
    improvements_generated: List[str]
    improvements_deployed: List[str]
    success_rate: float = 0.0

    # Metrics
    start_time: datetime = field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    duration_sec: float = 0.0

    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)


class EnhancedASISelfImprovement(IAdaptationEngine):
    """
    Enhanced ASI Self-Improvement Orchestrator

    Coordinates all learning components for safe, effective self-improvement:
    - Identifies improvement opportunities across all systems
    - Generates and validates improvements using Unified LLM (Unified LLM)
    - Deploys improvements with safety checks
    - Learns from improvement outcomes
    - Forecasts capability trajectories

    LLM: Uses Unified LLM local model via Unified LLM service
    """

    @staticmethod
    @staticmethod
    def _answer_of(result: Any) -> str:
        """The model's answer, or a raised error saying why there isn't one.

        `NeuralSymbolicBridge.reason()` reports a generation failure by putting
        the reason IN the answer -- "Error: LLM generation failed (LLM service
        not initialized)" -- and recording the real state in `metadata`
        (`verified`, `generation_failed`, `model_available`, `model_error`).
        Five call sites here passed `result.answer` straight to `_extract_json`,
        which found no JSON in that sentence and raised
        `JSONDecodeError: No valid JSON found in LLM response`.
        
        So an unreachable model surfaced, three layers away, as a malformed
        response -- and the recorded cycle history says "target selection
        unavailable (JSONDecodeError)" for what was actually a llama-server that
        was not running. Days of that history describe the wrong defect.
        
        The metadata is authoritative and is read first, exactly as it is for
        `verified` elsewhere in the substrate.
        """
        metadata = getattr(result, "metadata", None) or {}
        if metadata.get("generation_failed") or metadata.get("model_error"):
            raise RuntimeError(
                "teacher generation failed: "
                f"{metadata.get('model_error') or metadata.get('reason') or 'unknown'}"
            )
        # THE SUBSTRATE COULD NOT REPRESENT THE INPUT. That is the fact, and it
        # is a fact about the substrate. This used to read "model required and
        # unavailable", which asserts that reasoning depends on a model -- the
        # architecture backwards. A teacher only widens which inputs can be
        # taken; its absence is why there is no answer here, not why one was
        # needed.
        if metadata.get("reason") == "unsupported_input":
            raise RuntimeError(
                "the substrate could not represent this input"
                + ("" if metadata.get("teacher_available")
                   else " and no teacher was reachable to widen coverage")
                + f" ({metadata.get('formalizer_error') or 'no formalizer matched'})"
            )
        answer = getattr(result, "answer", None)
        if not answer:
            raise RuntimeError("the reasoner returned an empty answer")
        return answer

    @staticmethod
    def _extract_json(text: str) -> Any:
        """Robustly extract JSON from an LLM response that may contain prose or code fences."""
        import re as _re
        if not text:
            raise ValueError("Empty response from LLM")
        # Strip markdown code fences: ```json ... ``` or ``` ... ```
        text = _re.sub(r'^```(?:json)?\s*', '', text.strip(), flags=_re.IGNORECASE)
        text = _re.sub(r'\s*```$', '', text.strip())
        text = text.strip()
        # Try direct parse first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # Try to extract the first {...} or [...] block
        for pattern in (r'\{[\s\S]*\}', r'\[[\s\S]*\]'):
            m = _re.search(pattern, text)
            if m:
                try:
                    return json.loads(m.group(0))
                except json.JSONDecodeError:
                    pass
        raise json.JSONDecodeError(f"No valid JSON found in LLM response", text, 0)

    def __init__(self, db_config: Dict[str, Any] = None):
        self.db_config = db_config or {}
        self.cycles: List[ImprovementCycle] = []
        self.improvement_history: Dict[str, List[float]] = defaultdict(list)

        # Learning components (lazy initialization)
        self._meta_learner = None
        self._monitor = None
        self._validator = None
        self._deployer = None
        self._audit_trail = None
        self._profiler = None
        self._neural_bridge = None  # Neural bridge for automatic memory capture

        # New infrastructure integrations
        self._tool_registry = None  # Replaces code_generator
        self._governance = None  # Replaces safety_boundaries + governance_pattern_learner

        # Configuration
        self.max_concurrent_improvements = 3
        self.improvement_threshold = 0.05  # 5% minimum improvement
        self.safety_threshold = 0.9  # 90% safety confidence required

        # LLM configuration (plug-and-play via Unified LLM)
        self.llm_temperature = 0.3  # Lower temperature for code generation

        # Circular dependency guard (prevents deadlock)
        self._cycle_in_progress = False
        self._max_cycle_nesting = 2
        self._env_state = None
        self._topology = None
        self._behavioral = None
        self._services = None
        self._current_cycle_nesting = 0

        logger.info("EnhancedASISelfImprovement initialized (using Unified LLM)")

    # Lazy component initialization
    @property
    def meta_learner(self):
        if self._meta_learner is None:
            try:
                self._meta_learner = get_meta_learner()
            except Exception as e:
                # Bare `except:` also swallowed KeyboardInterrupt/SystemExit and
                # discarded the reason, so a dependency broken by an import
                # error, a config fault or a crash all became the same silent
                # None -- indistinguishable from one that is simply absent.
                logger.error("Meta learner unavailable: %s: %s", type(e).__name__, e)
        return self._meta_learner

    @property
    def monitor(self):
        if self._monitor is None:
            try:
                self._monitor = get_improvement_monitor()
            except Exception as e:
                # Bare `except:` also swallowed KeyboardInterrupt/SystemExit and
                # discarded the reason, so a dependency broken by an import
                # error, a config fault or a crash all became the same silent
                # None -- indistinguishable from one that is simply absent.
                logger.error("Improvement monitor unavailable: %s: %s", type(e).__name__, e)
        return self._monitor

    @property
    def validator(self):
        if self._validator is None:
            self._validator = get_upgrade_validator()
            if not self._validator:
                raise RuntimeError("UpgradeValidator unavailable")
        return self._validator

    @property
    def deployer(self):
        if self._deployer is None:
            try:
                self._deployer = get_safe_deployer()
            except Exception as e:
                # Bare `except:` also swallowed KeyboardInterrupt/SystemExit and
                # discarded the reason, so a dependency broken by an import
                # error, a config fault or a crash all became the same silent
                # None -- indistinguishable from one that is simply absent.
                logger.error("Safe deployer unavailable: %s: %s", type(e).__name__, e)
        return self._deployer

    @property
    def tool_registry(self):
        """Get tool registry for code generation (replaces code_generator)"""
        if self._tool_registry is None:
            try:
                self._tool_registry = get_tool_registry()
                logger.info("Connected to tool registry (300+ tools)")
            except Exception as e:
                # Bare `except:` also swallowed KeyboardInterrupt/SystemExit and
                # discarded the reason, so a dependency broken by an import
                # error, a config fault or a crash all became the same silent
                # None -- indistinguishable from one that is simply absent.
                logger.error("Tool registry unavailable: %s: %s", type(e).__name__, e)
        return self._tool_registry

    @property
    def governance(self):
        """Get unified governance system (replaces safety_boundaries + governance_pattern_learner)"""
        if self._governance is None:
            try:
                self._governance = get_unified_governance()
                logger.info("Connected to unified governance system")
            except Exception as e:
                # Bare `except:` also swallowed KeyboardInterrupt/SystemExit and
                # discarded the reason, so a dependency broken by an import
                # error, a config fault or a crash all became the same silent
                # None -- indistinguishable from one that is simply absent.
                logger.error("Unified governance unavailable: %s: %s", type(e).__name__, e)
        return self._governance

    @property
    def audit_trail(self):
        if self._audit_trail is None:
            try:
                self._audit_trail = get_safety_audit_trail()
            except Exception as e:
                # Bare `except:` also swallowed KeyboardInterrupt/SystemExit and
                # discarded the reason, so a dependency broken by an import
                # error, a config fault or a crash all became the same silent
                # None -- indistinguishable from one that is simply absent.
                logger.error("Safety audit trail unavailable: %s: %s", type(e).__name__, e)
        return self._audit_trail

    @property
    def env_state(self):
        """Service discovery, resources, capabilities. Was never wired: the
        cycle reasoned about components with no idea what was RUNNING."""
        if self._env_state is None:
            from core.system.environment_state import EnvironmentState
            self._env_state = EnvironmentState()
        return self._env_state

    @property
    def topology(self):
        """Dependency graph, critical tiers, single points of failure. Also
        never wired -- so a target scoring 0 and a target scoring 0 that nine
        other services depend on looked identical."""
        if self._topology is None:
            from core.system.infrastructure_topology import InfrastructureTopology
            self._topology = InfrastructureTopology()
        return self._topology

    async def observe_system(self) -> Dict[str, Any]:
        """What the system looks like right now, from its own awareness layer.

        `core/system` -- environment_state, infrastructure_topology,
        active_discovery -- had ZERO references in this file. The cycle chose
        what to improve from one 0-100 health number per component, with no
        notion of what was running, what depended on what, or which failures
        cascade. This is the picture reasoning gets to work from.
        """
        observation: Dict[str, Any] = {}
        try:
            await self.env_state.refresh()
            observation["environment"] = self.env_state.get_state_summary()
        except Exception as e:
            raise_if_structural(e, "EnhancedASISelfImprovement.observe_system")
            logger.warning("Environment state unavailable: %s", e)
            observation["environment_error"] = f"{type(e).__name__}: {e}"

        try:
            self.topology.update_from_environment(self.env_state)
            critical = self.topology.get_critical_services()
            spofs, cascades = [], []
            for service in critical:
                impact = self.topology.assess_failure_impact(service)
                if impact.get("is_single_point_of_failure"):
                    spofs.append(service)
                if self.topology.would_cascade_fail(service):
                    cascades.append({
                        "service": service,
                        "affected": impact.get("total_affected", 0),
                        "critical_affected": impact.get("critical_affected", 0),
                    })
            observation["topology"] = {
                "critical_services": critical,
                "single_points_of_failure": spofs,
                "cascade_risks": cascades,
            }
        except Exception as e:
            raise_if_structural(e, "EnhancedASISelfImprovement.observe_system")
            logger.warning("Topology unavailable: %s", e)
            # Selection reads `topology` for cascade and single-point-of-
            # failure weight. Absent, the solver still runs but scores every
            # component as though nothing depended on it -- a quieter answer,
            # not a worse-behaved one, so the reason is recorded.
            observation["topology_error"] = f"{type(e).__name__}: {e}"

        # PERFORMANCE METRICS. `self.profiler` had ZERO references: the
        # profiler resolved on demand and was never asked anything, so
        # assessment ran on one coarse 0-100 health number per component with
        # no latency, no error rate, no throughput and no trend.
        try:
            observation["performance"] = await self.profiler.get_statistics()
        except Exception as e:
            raise_if_structural(e, "EnhancedASISelfImprovement.observe_system")
            logger.warning("Profiler statistics unavailable: %s", e)
            observation["performance_error"] = f"{type(e).__name__}: {e}"

        # OBSERVED DEPENDENCIES, as distinct from declared ones. The topology
        # above is what the registry SAYS depends on what; this is what was
        # seen to actually talk to what, which is the only way a declared
        # dependency can be shown to be wrong.
        try:
            await self.behavioral.observe(duration_s=self.BEHAVIOUR_OBSERVE_SEC)
            observation["behaviour"] = {
                "flows": len(getattr(self.behavioral, "flows", []) or []),
                "failures": len(getattr(self.behavioral, "failures", []) or []),
            }
        except Exception as e:
            raise_if_structural(e, "EnhancedASISelfImprovement.observe_system")
            logger.warning("Behavioural observation unavailable: %s", e)
            observation["behaviour_error"] = f"{type(e).__name__}: {e}"

        return observation

    @property
    def behavioral(self):
        """Observed service behaviour — flows, dependencies, failure events."""
        if self._behavioral is None:
            from core.system.behavioral_analysis import BehavioralAnalysis
            self._behavioral = BehavioralAnalysis()
        return self._behavioral

    @property
    def services(self):
        """The DI container, so a wired component is resolved rather than
        constructed here — constructing our own is how two owners of one
        concept appear."""
        if self._services is None:
            from core.system.service_locator import get_service_locator
            self._services = get_service_locator()
        return self._services

    @property
    def profiler(self):
        if self._profiler is None:
            try:
                self._profiler = get_performance_profiler()
            except Exception as e:
                # Bare `except:` also swallowed KeyboardInterrupt/SystemExit and
                # discarded the reason, so a dependency broken by an import
                # error, a config fault or a crash all became the same silent
                # None -- indistinguishable from one that is simply absent.
                logger.error("Performance profiler unavailable: %s: %s", type(e).__name__, e)
        return self._profiler

    @property
    def neural_bridge(self):
        """Get neural bridge for automatic memory capture"""
        if self._neural_bridge is None:
            try:
                from core.reasoning.neural_bridge import get_neural_bridge
                self._neural_bridge = get_neural_bridge()
                logger.info("Connected to neural bridge for memory capture")
            except Exception as e:
                logger.warning(f"Neural bridge not available: {e}")
        return self._neural_bridge

    async def run_improvement_cycle(
        self,
        scope: ImprovementScope = ImprovementScope.MINOR,
        target_components: List[str] = None,
        context: Dict[str, Any] = None
    ) -> ImprovementCycle:
        """
        Run complete self-improvement cycle

        Phases:
        1. Assessment - Identify improvement opportunities (uses Unified LLM for analysis)
        2. Planning - Select targets and strategies (uses Unified LLM for strategy)
        3. Generation - Generate improvements (uses Unified LLM for code generation)
        4. Validation - Validate safety and correctness
        5. Testing - Test in sandbox
        6. Deployment - Deploy if safe
        7. Evaluation - Measure impact (uses Unified LLM for impact analysis)
        8. Reflection - Learn from results (uses Unified LLM for reflection)
        """
        cycle_id = f"cycle_{datetime.now().timestamp()}"

        # NORMALISED ONCE, HERE. `context` defaults to None and was passed down
        # untouched, while every consumer annotates it as a plain Dict and uses
        # it as one: planning does `context["selection_policy"] = ...` and the
        # deployment gate does `context.get("human_approved")`. So a cycle
        # started with the default signature -- the ordinary way to start one --
        # died in Phase 2 with "'NoneType' object does not support item
        # assignment", after assessment and target selection had both already
        # done their work.
        #
        # One site already worked around it locally (`metadata=context or {}`),
        # which left the other two to fail. Fixing it at the entry point means
        # every phase downstream receives the dict its signature promises.
        context = context or {}

        # CIRCULAR DEPENDENCY GUARD: Prevent deadlock
        if self._cycle_in_progress:
            self._current_cycle_nesting += 1

            if self._current_cycle_nesting > self._max_cycle_nesting:
                logger.error(
                    f"🛑 CIRCULAR DEPENDENCY DETECTED: Self-improvement cycle nesting exceeded "
                    f"({self._current_cycle_nesting} > {self._max_cycle_nesting})"
                )
                raise RuntimeError(
                    "Circular dependency detected: Self-improvement cycle called recursively. "
                    "This prevents deadlock. Check for autonomous_coordinator ← → self-improvement circular calls."
                )

            logger.warning(
                f"⚠️  Nested self-improvement cycle detected (depth: {self._current_cycle_nesting}). "
                "Allowing but monitoring for deadlock."
            )

        self._cycle_in_progress = True

        try:
            logger.info(
                f"Starting improvement cycle: {cycle_id} "
                f"(scope={scope.value})"
            )

            # Create cycle record
            cycle = ImprovementCycle(
                cycle_id=cycle_id,
                phase=ImprovementPhase.ASSESSMENT,
                scope=scope,
                targets=[],
                improvements_generated=[],
                improvements_deployed=[],
                start_time=datetime.now(),
                # THE SAME DICT, NOT A COPY OF IT. `context or {}` looks like a
                # None-guard, but an empty dict is falsy too -- so a cycle
                # started the ordinary way got a metadata dict that was a
                # DIFFERENT object from context. Phases record their decisions
                # into context (`context["selection_policy"] = ...`), and those
                # writes then landed on an object the cycle never read: the
                # policy that chose the targets was recorded nowhere, and the
                # cycle reported selection_policy=None.
                #
                # It worked whenever a caller passed a non-empty context, which
                # is what made it look intermittent rather than broken.
                # Normalisation at the entry point guarantees a dict here, so
                # the guard has nothing left to do.
                metadata=context
            )

            # Phase 0: OBSERVE THE SYSTEM before deciding anything about it.
            system_view = await self.observe_system()
            context["system"] = system_view
            cycle.metadata["system_observation"] = system_view
            _env = (system_view.get("environment") or {}).get("services") or {}
            _topo = system_view.get("topology") or {}
            logger.info(
                "System observed: %s services running, %s degraded, %d critical, "
                "%d single point(s) of failure, %d cascade risk(s)",
                _env.get("running", "?"), _env.get("degraded", "?"),
                len(_topo.get("critical_services") or []),
                len(_topo.get("single_points_of_failure") or []),
                len(_topo.get("cascade_risks") or []))

            # Phase 1: Assessment - Identify opportunities (using Unified LLM)
            cycle.phase = ImprovementPhase.ASSESSMENT
            targets = await self._assess_improvements(
                scope, target_components, context
            )
            cycle.targets = targets
            cycle.metadata["targets_identified"] = len(targets)

            if not targets:
                logger.info("No improvement targets identified")
                cycle.end_time = datetime.now()
                cycle.duration_sec = (cycle.end_time - cycle.start_time).total_seconds()
                self.cycles.append(cycle)
                await self._persist_cycle(cycle)
                return cycle

            # Phase 1.5: Remediation — ACT on targets that are simply down.
            #
            # RUNS BEFORE PLANNING, deliberately. Remediation is deterministic
            # (restart what is not running) and needs no model, while planning
            # calls the LLM. Placed after planning, the cycle could not recover
            # the very dependency it needs: with the inference worker dead,
            # planning failed with "No valid JSON found in LLM response" and the
            # cycle ended before ever reaching the step that restarts the LLM.
            #
            # A stopped subsystem is fixed by starting it, and doing so IS an
            # improvement -- recorded as one, so a cycle can report success
            # instead of only enumerating what is broken.
            remediation = await self._remediate_targets(targets, context)
            cycle.metadata["remediation"] = remediation
            for component in remediation["recovered"]:
                cycle.improvements_deployed.append(f"recovered:{component}")

            # AN OPERATIONAL FINDING IS NEVER A CODE FINDING.
            #
            # Only `recovered` was removed, so a component whose restart was
            # ATTEMPTED AND FAILED fell through to planning and then to code
            # generation. A remedy failing does not make a different remedy
            # correct: "the content security scanner is not running" is not
            # answered by writing a new function, whether or not the restart
            # worked. That is why every target reaching generation in the last
            # run was a liveness issue.
            #
            # Liveness targets leave the improvement path entirely. The ones
            # that recovered are improvements; the ones that did not are
            # recorded as needing operational attention, which is a real
            # finding and not a silent drop.
            recovered = set(remediation["recovered"])
            attempted = set(remediation["attempted"])
            unrecovered = sorted(attempted - recovered)
            if unrecovered:
                cycle.metadata["needs_operator"] = unrecovered
                logger.warning(
                    "%d component(s) are down and could not be restarted: %s — "
                    "operational, not a code defect; not sent to generation",
                    len(unrecovered), ", ".join(unrecovered))
            targets = [t for t in targets if t.component not in attempted]
            if not targets:
                cycle.phase = ImprovementPhase.EVALUATION
                cycle.success_rate = 1.0 if remediation["recovered"] else 0.0
                cycle.end_time = datetime.now()
                cycle.duration_sec = (cycle.end_time - cycle.start_time).total_seconds()
                cycle.metadata["early_exit_reason"] = "all_targets_remediated"
                logger.info("✅ Cycle complete via remediation: %d component(s) recovered",
                            len(remediation["recovered"]))
                self.cycles.append(cycle)
                await self._persist_cycle(cycle)
                return cycle

            # Phase 2: Planning - Select targets and strategies (using Unified LLM)
            cycle.phase = ImprovementPhase.PLANNING
            selected_targets = await self._plan_improvements(targets, scope, context)
            cycle.metadata["targets_selected"] = len(selected_targets)

            if not selected_targets:
                logger.info("No improvement targets selected after governance/planning; ending cycle early")
                cycle.end_time = datetime.now()
                cycle.duration_sec = (cycle.end_time - cycle.start_time).total_seconds()
                cycle.metadata["early_exit_reason"] = "no_targets_selected"
                self.cycles.append(cycle)
                await self._persist_cycle(cycle)
                return cycle

            # Phase 3: Generation - Generate improvements (using Unified LLM)
            cycle.phase = ImprovementPhase.GENERATION
            improvements = await self._generate_improvements(
                selected_targets, scope, context
            )
            cycle.improvements_generated = improvements
            cycle.metadata["improvements_generated"] = len(improvements)

            if not improvements:
                logger.info("No improvements could be generated; ending cycle early")
                cycle.end_time = datetime.now()
                cycle.duration_sec = (cycle.end_time - cycle.start_time).total_seconds()
                cycle.metadata["early_exit_reason"] = "no_improvements_generated"
                # Remediation already happened. Reporting 0.0 here erased two
                # genuinely recovered subsystems because success was computed
                # only from DEPLOYED CODE -- so a cycle that fixed the system
                # by restarting it looked identical to one that achieved
                # nothing. Anything in improvements_deployed is work that was
                # done, whether it was generated or recovered.
                cycle.success_rate = self._cycle_success_rate(cycle)
                self.cycles.append(cycle)
                await self._persist_cycle(cycle)
                return cycle

            # Phase 4: Validation - Validate safety and correctness
            cycle.phase = ImprovementPhase.VALIDATION
            validated = await self._validate_improvements(improvements, context)
            cycle.metadata["improvements_validated"] = len(validated)

            # Phase 5: Testing - Test in sandbox
            cycle.phase = ImprovementPhase.TESTING
            tested = await self._test_improvements(validated, context)
            cycle.metadata["improvements_tested"] = len(tested)

            # Phase 6: Deployment - Deploy if safe (HARD GATE)
            cycle.phase = ImprovementPhase.DEPLOYMENT
            is_safe = await self._is_deployment_safe(scope, tested, context)
            if tested and is_safe:
                deployed = await self._deploy_improvements(tested, scope, context)
                cycle.improvements_deployed = deployed
                cycle.metadata["improvements_deployed"] = len(deployed)
            else:
                error_msg = "🛑 HARD GATE FAILED: Deployment blocked by safety checks"
                logger.error(error_msg)

                # Record failure in audit trail
                if self.audit_trail:
                    await self.audit_trail.record_event(
                        event_type=SafetyEventType.BLOCKED_ACTION,
                        severity="CRITICAL",
                        description=error_msg,
                        action="deploy_improvements",
                        outcome="blocked_cycle_aborted",
                        component="enhanced_asi",
                        details={
                            "reason": "Deployment safety gate enforcement",
                            "is_safe": is_safe,
                            "tested_count": len(tested) if tested else 0
                        }
                    )

                raise RuntimeError(
                    "Deployment safety checks FAILED. Self-improvement cycle ABORTED."
                )

            # Phase 7: Evaluation - Measure impact (using Unified LLM)
            cycle.phase = ImprovementPhase.EVALUATION
            if cycle.improvements_deployed:
                impact = await self._evaluate_impact(
                    cycle.improvements_deployed, selected_targets, context
                )
                cycle.metadata["impact"] = impact
                # Impact measures the DEPLOYED improvements; recoveries are
                # counted alongside them rather than replaced by them.
                #
                # An UNMEASURED impact contributes nothing. Its success_rate is
                # 0.0 by initialisation, not by observation, and feeding that
                # into max() was harmless only because the deployment rate
                # floors it -- but reading a value that was never measured is
                # how a zero starts being treated as a finding.
                deployment_rate = self._cycle_success_rate(cycle)
                cycle.success_rate = (
                    max(float(impact.get("success_rate", 0.0)), deployment_rate)
                    if impact.get("measured") else deployment_rate
                )

            # Phase 7.5: Capability Regression Check - Frozen benchmark validation
            # This prevents "capability narrowing" - optimizing specific metrics while losing general competence
            if cycle.improvements_deployed:
                logger.info("Running capability regression checks...")
                capability_report = await self._check_capability_regression(cycle_id, context)

                if capability_report:
                    cycle.metadata["capability_report"] = {
                        "overall_score": capability_report.overall_score,
                        "reasoning_score": capability_report.reasoning_score,
                        "coding_score": capability_report.coding_score,
                        "analysis_score": capability_report.analysis_score,
                        "comprehension_score": capability_report.comprehension_score,
                        "regression_detected": capability_report.regression_detected,
                        "regression_domains": capability_report.regression_domains,
                        "regression_severity": capability_report.regression_severity,
                        "baseline_delta": capability_report.baseline_delta
                    }

                    # HARD GATE: Block if severe capability regression detected
                    if capability_report.regression_detected and capability_report.regression_severity == "SEVERE":
                        error_msg = (
                            f"🛑 CAPABILITY REGRESSION DETECTED: SEVERE regression in "
                            f"{', '.join(capability_report.regression_domains)}. "
                            f"Baseline delta: {capability_report.baseline_delta:.2%}. "
                            "BLOCKING to prevent capability narrowing."
                        )
                        logger.error(error_msg)

                        # Record in audit trail
                        if self.audit_trail:
                            await self.audit_trail.record_event(
                                event_type=SafetyEventType.BLOCKED_ACTION,
                                severity="CRITICAL",
                                description=error_msg,
                                action="deploy_improvements",
                                outcome="blocked_capability_regression",
                                component="capability_benchmarks",
                                details={
                                    "reason": "Severe capability regression detected",
                                    "regression_domains": capability_report.regression_domains,
                                    "regression_severity": capability_report.regression_severity,
                                    "baseline_delta": capability_report.baseline_delta,
                                    "overall_score": capability_report.overall_score
                                }
                            )

                        raise RuntimeError(
                            f"Capability regression check FAILED. {error_msg}"
                        )

                    # UNMEASURED is not UNCHANGED.
                    #
                    # The suite reports severity UNKNOWN when it could not run
                    # at all (no LLM service, no benchmarks loaded). That used
                    # to arrive as regression_detected=False / severity NONE —
                    # identical to a clean pass — so an improvement could be
                    # deployed with its capability check silently skipped, which
                    # is precisely the capability-narrowing this gate exists to
                    # prevent. Surfaced separately so it cannot be read as a
                    # pass, and counted so a persistent inability to measure is
                    # visible rather than routine.
                    elif capability_report.regression_severity == "UNKNOWN":
                        self._capability_unmeasured_cycles = getattr(
                            self, "_capability_unmeasured_cycles", 0
                        ) + 1
                        unverified = self._capability_unmeasured_cycles
                        cycle.metadata["capability_unverified_streak"] = unverified
                        logger.error(
                            f"🚫 CAPABILITY UNVERIFIED: benchmarks did not run for this cycle "
                            f"({capability_report.tests_passed + capability_report.tests_failed} "
                            f"tests executed). Regression has NOT been ruled out. "
                            f"Consecutive unverified cycles: {unverified}"
                        )

                        # A COUNTER NOTHING READS IS NOT A GATE.
                        #
                        # This incremented and logged, and no decision anywhere
                        # consulted the value -- so a system that could never
                        # run its benchmarks deployed self-modifications
                        # indefinitely with capability regression never ruled
                        # out. That is exactly the capability narrowing the
                        # whole phase exists to prevent, arrived at one
                        # unverified cycle at a time.
                        #
                        # One unverified cycle is a blip. A run of them means
                        # the system is modifying itself while blind to whether
                        # it is losing competence, and it must stop until the
                        # benchmarks can run again.
                        if unverified >= MAX_UNVERIFIED_CAPABILITY_CYCLES:
                            blocked = (
                                f"🛑 CAPABILITY UNVERIFIABLE for {unverified} consecutive "
                                f"cycles (limit {MAX_UNVERIFIED_CAPABILITY_CYCLES}). Refusing "
                                f"to keep self-modifying while unable to measure whether "
                                f"competence is being lost.")
                            logger.error(blocked)
                            if self.audit_trail:
                                await self.audit_trail.record_event(
                                    event_type=SafetyEventType.BLOCKED_ACTION,
                                    severity="CRITICAL",
                                    description=blocked,
                                    action="deploy_improvements",
                                    outcome="blocked_capability_unverifiable",
                                    component="capability_benchmarks",
                                    details={"cycle_id": cycle_id,
                                             "consecutive_unverified": unverified},
                                )
                            raise RuntimeError(blocked)

                    # WARNING: Log moderate regression but allow
                    elif capability_report.regression_detected:
                        self._capability_unmeasured_cycles = 0
                        logger.warning(
                            f"⚠️  CAPABILITY REGRESSION: {capability_report.regression_severity} regression in "
                            f"{', '.join(capability_report.regression_domains)}. Allowing but monitoring."
                        )
                    else:
                        self._capability_unmeasured_cycles = 0

                # Phase 7.6: Long-Horizon Drift Detection (30-cycle rolling trends)
                # Catches "boiling frog" degradation: 1% per cycle = 30% over 30 cycles
                try:
                    # Get benchmark suite
                    if get_capability_benchmark_suite:
                        benchmark_suite = get_capability_benchmark_suite()

                        # Detect drift across all domains
                        drift_results = {}
                        for domain in ['overall', 'reasoning', 'coding', 'analysis', 'comprehension']:
                            drift_analysis = await benchmark_suite.detect_long_horizon_drift(
                                domain=domain,
                                window_size=30
                            )

                            if 'error' not in drift_analysis:
                                drift_results[domain] = drift_analysis

                                # CRITICAL: Block if catastrophic cumulative drift detected
                                if drift_analysis['severity'] == "CRITICAL":
                                    error_msg = (
                                        f"🚨 CATASTROPHIC LONG-HORIZON DRIFT: {domain} domain shows "
                                        f"{drift_analysis['cumulative_change_pct']:.1f}% cumulative change "
                                        f"over {drift_analysis['window_size']} cycles. "
                                        f"Drift velocity: {drift_analysis['drift_velocity_pct_per_cycle']:.3f}%/cycle. "
                                        "BLOCKING to prevent slow capability decay."
                                    )
                                    logger.error(error_msg)

                                    if self.audit_trail:
                                        await self.audit_trail.record_event(
                                            event_type=SafetyEventType.BLOCKED_ACTION,
                                            severity="CRITICAL",
                                            description=error_msg,
                                            action="deploy_improvements",
                                            outcome="blocked_capability_drift",
                                            component="capability_drift_detection",
                                            details={
                                                "reason": "Catastrophic long-horizon drift detected",
                                                "domain": domain,
                                                "cumulative_change_pct": drift_analysis['cumulative_change_pct'],
                                                "drift_velocity": drift_analysis['drift_velocity_pct_per_cycle'],
                                                "window_size": drift_analysis['window_size']
                                            }
                                        )

                                    raise RuntimeError(
                                        f"Long-horizon drift check FAILED. {error_msg}"
                                    )

                                # HIGH: Warn but allow (intervention needed soon)
                                elif drift_analysis['severity'] == "HIGH":
                                    logger.error(
                                        f"🚨 HIGH long-horizon drift in {domain}: "
                                        f"{drift_analysis['cumulative_change_pct']:.1f}% over {drift_analysis['window_size']} cycles. "
                                        "Immediate attention required!"
                                    )

                        # Store drift results in cycle metadata
                        cycle.metadata["drift_analysis"] = drift_results
                        logger.info(f"Long-horizon drift detection complete for {len(drift_results)} domains")

                except Exception as drift_error:
                    logger.warning(f"Long-horizon drift detection failed: {drift_error}")
                    # Don't block cycle on drift detection failure (fail-open for drift, fail-closed for regression)

            # Phase 8: Reflection - Learn from results (using Unified LLM)
            cycle.phase = ImprovementPhase.REFLECTION
            await self._reflect_on_cycle(cycle)

            # Complete cycle
            cycle.end_time = datetime.now()
            cycle.duration_sec = (cycle.end_time - cycle.start_time).total_seconds()

            # Store cycle
            self.cycles.append(cycle)
            await self._persist_cycle(cycle)

            logger.info(
                f"Improvement cycle complete: {cycle_id} "
                f"(deployed={len(cycle.improvements_deployed)}, "
                f"success_rate={cycle.success_rate:.1%})"
            )

            try:
                from core.utils.notification_publisher import send_system_notification
                severity = "info" if cycle.success_rate > 0.5 else "warning"
                await send_system_notification(
                    title=f"ASI Self-Improvement Cycle Complete",
                    message=f"**Cycle:** {cycle_id}\n**Scope:** {scope.value}\n**Deployed:** {len(cycle.improvements_deployed)} improvements\n**Success Rate:** {cycle.success_rate:.1%}\n**Duration:** {cycle.duration_sec:.1f}s",
                    severity=severity,
                    metadata={
                        "cycle_id": cycle_id,
                        "scope": scope.value,
                        "deployed_count": len(cycle.improvements_deployed),
                        "success_rate": f"{cycle.success_rate:.1%}",
                        "duration_sec": cycle.duration_sec
                    }
                )
            except Exception as e:
                logger.warning(f"Failed to send ASI notification: {e}")

            return cycle

        except Exception as e:
            logger.error(f"Improvement cycle failed: {e}")
            cycle.metadata["error"] = str(e)
            cycle.end_time = datetime.now()
            cycle.duration_sec = (cycle.end_time - cycle.start_time).total_seconds()
            # A FAILED cycle is history too. Persisting only the cycles that ran
            # to completion would make the record a survivorship sample: every
            # statistic computed from it would describe the runs that worked.
            self.cycles.append(cycle)
            try:
                await self._persist_cycle(cycle)
            except Exception as persist_error:
                logger.error("Could not record failed cycle %s: %s",
                             cycle.cycle_id, persist_error)
            return cycle

        finally:
            # CLEANUP: Reset circular dependency guard
            if self._current_cycle_nesting > 0:
                self._current_cycle_nesting -= 1
            else:
                self._cycle_in_progress = False

    async def _assess_improvements(
        self,
        scope: ImprovementScope,
        target_components: List[str],
        context: Dict[str, Any]
    ) -> List[ImprovementTarget]:
        """Phase 1: Assess improvement opportunities using Unified LLM"""
        targets = []

        try:
            # A MISSING MONITOR IS NOT A HEALTHY SYSTEM.
            #
            # This was `if self.monitor:` with no else, so an unavailable
            # monitor skipped the whole assessment and fell through to
            # `return targets` — an empty list. The handler below already
            # refuses to let a CRASHED assessment report [], for exactly the
            # reason that the cycle reads [] as "the system needs no
            # improvement". An assessment that never ran reaches the same
            # false conclusion by a quieter route.
            if not self.monitor:
                raise RuntimeError(
                    "ImprovementMonitor is unavailable, so no component health "
                    "can be read; refusing to report zero improvement targets "
                    "as evidence that the system needs none.")

            if self.monitor:
                # Identify underperforming components
                components = target_components or await self._get_all_components()

                # WORST FIRST, NOT FIRST TEN.
                #
                # `components[:10]` took an arbitrary slice of 76 in whatever
                # order the registry returned, so 66 components could never be
                # candidates however badly they scored, and which 10 were
                # eligible depended on row order. Ranked on the persisted score
                # -- cheap, and only a prioritisation: the LIVE reading taken
                # below is what actually decides whether a target is created
                # and what its current_value is.
                if not target_components:
                    components = await self._rank_by_recorded_health(components)

                for component in components[:self.MAX_ASSESSMENT_CANDIDATES]:
                    # Get current metrics
                    health = await self._get_component_health(component)

                    if health and health["health_score"] < 90:  # Below 90% health
                        # Use Unified LLM to analyze improvement opportunity
                        analysis = await self._analyze_improvement_opportunity(
                            component, health, scope
                        )

                        target = ImprovementTarget(
                            target_id=f"{component}_{datetime.now().timestamp()}",
                            component=component,
                            # The metric is what was measured; the CAUSE is in
                            # health['issues']. Without it a target says only
                            # "score 40" and every remediation has to guess --
                            # which is why tool selection below always fell
                            # through to generate_function.
                            metric="health_score",
                            current_value=health["health_score"],
                            target_value=analysis.get("target_value", 95.0),
                            improvement_potential=analysis.get("potential", 10.0),
                            difficulty=analysis.get("difficulty", "medium"),
                            risk_level=self._estimate_risk(scope, component),
                            context={**analysis.get("context", {}),
                                     "issues": health.get("issues", []),
                                     "status": health.get("status")}
                        )
                        targets.append(target)

            logger.info(f"Assessment complete: {len(targets)} targets identified")
            return targets

        except Exception as e:
            # AN ASSESSMENT THAT CRASHED FOUND NOTHING, AND SO DID AN
            # ASSESSMENT THAT RAN. Returning [] made those the same answer, and
            # the cycle above reads an empty list as "the system needs no
            # improvement" — a broken assessor therefore reports perfect health
            # forever, which is the one conclusion it has no evidence for.
            logger.error(f"Assessment failed: {e}", exc_info=True)
            raise RuntimeError(f"Improvement assessment failed: {e}") from e

    #: Difficulties the solver knows how to weight. Anything else has no
    #: adjustment and would silently score as "medium".
    _KNOWN_DIFFICULTIES = frozenset({"easy", "medium", "hard", "very_hard"})

    @classmethod
    def _validate_opportunity(cls, analysis: Any, component: str) -> None:
        """Raise unless a proposed opportunity is usable as a scoring input.

        Every field here is consumed by target selection. Range-checking is the
        substrate refusing to take a proposer's word for how much its own
        suggestion is worth.
        """
        if not isinstance(analysis, dict):
            raise ValueError(f"analysis for {component} is "
                             f"{type(analysis).__name__}, not an object")

        target = analysis.get("target_value")
        potential = analysis.get("potential")
        difficulty = analysis.get("difficulty")

        for name, value in (("target_value", target), ("potential", potential)):
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValueError(f"{name} for {component} is {value!r}, not a number")
            if not 0.0 <= float(value) <= 100.0:
                raise ValueError(f"{name} for {component} is {value}, outside 0-100")

        if difficulty not in cls._KNOWN_DIFFICULTIES:
            raise ValueError(
                f"difficulty for {component} is {difficulty!r}; the solver only "
                f"weights {sorted(cls._KNOWN_DIFFICULTIES)}")

    async def _analyze_improvement_opportunity(
        self,
        component: str,
        health: Dict[str, Any],
        scope: ImprovementScope
    ) -> Dict[str, Any]:
        """
        Analyze improvement opportunity using heuristics or LLM.

        Assessment is Phase 1 — its job is to identify targets and set realistic
        goals, not to generate improvements (that's Phase 3).  The LLM path is
        only used when the inference queue is EMPTY; otherwise we use the
        heuristic immediately.

        Why: each neural_bridge.reason() call submits a job to the unified_llm
        inference queue BEFORE awaiting the result.  If the call is later
        cancelled by asyncio.wait_for, the job is already in the queue and
        keeps running as a ghost — the future has no listener but the 32B model
        still burns 350-375 s on it.  Three analyses per cycle × recurring cycles
        = queue permanently saturated, every subsequent call times out, and the
        cycle never makes progress past assessment.
        """
        current_score = health["health_score"]

        # Assessment goes through the substrate reasoner when it is present.
        # The reasoner (and, behind it, the teacher) manages its own execution
        # queue and timeouts — this module holds no model handle to peek at.
        use_reasoner = self.neural_bridge is not None

        if use_reasoner:
            try:
                from core.reasoning.neural_bridge import ReasoningRequest, ReasoningMode

                query = f"""Analyze this improvement opportunity:

Component: {component}
Current health score: {health['health_score']:.1f}%
Scope: {scope.value}

Provide analysis in JSON format:
{{
    "target_value": <realistic target 90-100>,
    "potential": <improvement potential 0-100>,
    "difficulty": "easy|medium|hard|very_hard",
    "context": {{"key_factors": [...], "recommended_approach": "..."}}
}}"""

                request = ReasoningRequest(
                    query=query,
                    context=[f"Analyzing improvement for {component}", f"Scope: {scope.value}"],
                )

                # Short timeout — queue was empty when we checked, so the job
                # should start almost immediately.  If it doesn't complete
                # within 180 s something changed; fall through to heuristic.
                result = await asyncio.wait_for(
                    self.neural_bridge.reason(request), timeout=180.0
                )
                analysis = self._extract_json(self._answer_of(result))

                # A PROPOSAL IS CHECKED BEFORE IT BECOMES A NUMBER THE SYSTEM
                # ACTS ON. This returned the parsed JSON directly, and the
                # caller feeds `potential` and `difficulty` into the target --
                # from there into the constraint solver's scoring, where
                # `potential` is multiplied by 10 and `difficulty` selects an
                # adjustment. A reply proposing potential=500 or
                # difficulty="trivial" therefore reached target selection
                # unchallenged: the proposer was setting its own weight.
                #
                # Out of range is not repaired into something plausible, which
                # would be inventing the answer the reasoner failed to give --
                # it falls through to the deterministic heuristic below.
                self._validate_opportunity(analysis, component)

                logger.info(
                    f"Analysis for {component}: target={analysis.get('target_value')}, "
                    f"potential={analysis.get('potential')}, difficulty={analysis.get('difficulty')}"
                )
                return analysis

            except Exception as e:
                logger.warning(f"Reasoned assessment unusable for {component} ({e}); "
                               f"using the deterministic heuristic")
                # Fall through to heuristic below

        # ── Heuristic fallback (always used when queue is busy) ──────────────
        # scope.value is a string ("minor", "moderate", etc.), so map to numeric
        _scope_mult = {
            ImprovementScope.MINOR: 1,
            ImprovementScope.MODERATE: 2,
            ImprovementScope.MAJOR: 3,
            ImprovementScope.TRANSFORMATIVE: 4,
        }.get(scope, 1)

        if current_score >= 90:
            improvement_potential = 2.0 + (_scope_mult * 1.0)
            target_value = min(100.0, current_score + improvement_potential)
            difficulty = "hard"
        elif current_score >= 75:
            improvement_potential = 5.0 + (_scope_mult * 2.0)
            target_value = min(98.0, current_score + improvement_potential)
            difficulty = "medium"
        elif current_score >= 60:
            improvement_potential = 8.0 + (_scope_mult * 3.0)
            target_value = min(95.0, current_score + improvement_potential)
            difficulty = "medium"
        else:
            improvement_potential = 15.0 + (_scope_mult * 5.0)
            target_value = min(90.0, current_score + improvement_potential)
            difficulty = "easy"

        if scope == ImprovementScope.TRANSFORMATIVE:
            difficulty = "very_hard"
        elif scope == ImprovementScope.MAJOR and difficulty == "easy":
            difficulty = "medium"

        reason = "inference queue busy" if queue_depth > 0 else "neural bridge unavailable"
        logger.info(
            f"Heuristic assessment ({reason}): {component} "
            f"current={current_score:.1f} → target={target_value:.1f} "
            f"(potential={improvement_potential:.1f}, difficulty={difficulty})"
        )

        return {
            "target_value": target_value,
            "potential": improvement_potential,
            "difficulty": difficulty,
            "context": {
                "fallback": True,
                "reason": reason,
                "heuristic": "score_based_realistic_targets"
            }
        }

    async def _plan_improvements(
        self,
        targets: List[ImprovementTarget],
        scope: ImprovementScope,
        context: Dict[str, Any]
    ) -> List[ImprovementTarget]:
        """Phase 2: Plan improvements with governance approval"""
        selected = []

        try:
            # Sort by improvement potential
            sorted_targets = sorted(
                targets,
                key=lambda t: t.improvement_potential,
                reverse=True
            )

            # Map scope to governance action category
            scope_to_action = {
                ImprovementScope.MINOR: ActionCategory.LEARNING_PARAMETERS,
                ImprovementScope.MODERATE: ActionCategory.CONFIGURATION_CHANGES,
                ImprovementScope.MAJOR: ActionCategory.CONFIGURATION_CHANGES,
                ImprovementScope.TRANSFORMATIVE: ActionCategory.CONFIGURATION_CHANGES
            }

            action_category = scope_to_action.get(scope)

            if self.governance and action_category:
                decision = await self.governance.evaluate_action(
                    action_category=action_category,
                    action_type="self_improvement",
                    parameters={
                        "scope": scope.value,
                        "targets": [{"component": t.component, "metric": t.metric} for t in sorted_targets],
                        "impact": "self_improvement",
                        "estimated_risk": self._estimate_risk_level(scope)
                    },
                    context=context if isinstance(context, dict) else {}
                )

                # Handle governance decision - GovernanceTriggerEvaluation fields:
                # enforcement_mode (EnforcementMode enum), decision_tier (DecisionTier enum),
                # rationale (str), triggered (bool)
                from core.governance.unified_governance_trigger_system import EnforcementMode, DecisionTier

                if decision.enforcement_mode == EnforcementMode.MUST_BLOCK:
                    reason = decision.rationale or "No reason"
                    logger.warning(f"🛑 Governance BLOCKED improvement: {reason}")
                    if self.audit_trail:
                        await self.audit_trail.record_event(
                            event_type=SafetyEventType.BLOCKED_ACTION,
                            severity="HIGH",
                            description=f"Governance blocked self-improvement: {reason}",
                            action="block_improvement",
                            outcome="blocked",
                            component="enhanced_asi",
                            details={"scope": scope.value, "reason": reason}
                        )
                    return []

                if decision.decision_tier in (DecisionTier.IMPORTANT, DecisionTier.CRITICAL):
                    reason = decision.rationale or "Approval required"
                    logger.info(f"⏸️  Governance requires approval ({decision.decision_tier.value}): {reason}")
                    if self.audit_trail:
                        await self.audit_trail.record_event(
                            event_type=SafetyEventType.REQUIRES_APPROVAL,
                            severity="MEDIUM",
                            description=f"Governance requires approval for self-improvement: {reason}",
                            action="request_approval",
                            outcome="pending_approval",
                            component="enhanced_asi",
                            details={"scope": scope.value, "reason": reason}
                        )
                    return []

                # Apply governance-recommended limits (from matched_conditions if available)
                max_targets = decision.matched_conditions.get("max_targets", 3) if decision.matched_conditions else 3

                # SELECTION: the LLM proposes; the deterministic policy is the floor.
                #
                # Planning previously REQUIRED the model. With the inference
                # worker unavailable, _reason_select_targets raised, planning
                # re-raised, and the cycle died before it could improve
                # anything -- including the LLM itself. A substrate whose
                # symbolic layer is the floor cannot have its improvement loop
                # stop because the teacher is out of the room.
                #
                # The fallback is DETERMINISTIC, not invented: targets are
                # already ranked, and the ranking is built from measured health.
                # Which policy chose is recorded, so an LLM-reasoned selection
                # is never mistaken for a mechanical one -- the same distinction
                # as attributed-vs-observational transfer verdicts.
                selection_policy = "deterministic_worst_health_first"

                # SUBSTRATE FIRST, LITERALLY. The choice is solved before it is
                # described to anyone. Only if the solver cannot express or
                # settle it does the prose formulation get asked, and only then
                # does a teacher enter the picture.
                constrained = self.select_targets_by_constraint(
                    sorted_targets[:max_targets * 2], scope, context, max_targets)
                if constrained and constrained.get("selected_indices"):
                    for idx in constrained["selected_indices"]:
                        if 0 <= idx < len(sorted_targets):
                            selected.append(sorted_targets[idx])
                    if selected:
                        selection_policy = "constraint_solved"
                        context["selection_rationale"] = constrained.get("rationale")
                        context["selection_excluded_by_risk"] = constrained.get(
                            "excluded_by_risk")

                if not selected and self.neural_bridge and len(sorted_targets) > 0:
                    try:
                        planning_result = await self._reason_select_targets(
                            sorted_targets[:max_targets * 2], scope, context
                        )
                        selected_indices = planning_result.get("selected_indices", [])
                        for idx in selected_indices[:max_targets]:
                            if 0 <= idx < len(sorted_targets):
                                selected.append(sorted_targets[idx])
                        if selected:
                            selection_policy = "reasoned"
                    except Exception as e:
                        raise_if_structural(e, "EnhancedASISelfImprovement._plan_improvements")
                        logger.warning(
                            "Reasoned target selection unavailable (%s); using the "
                            "deterministic worst-health-first policy", e)

                if not selected:
                    # Ranked on the MEASUREMENT, not on improvement_potential.
                    # Potential comes from _analyze_improvement_opportunity,
                    # which asks the LLM -- so ranking by it would make the
                    # "deterministic" fallback depend on the model it exists to
                    # do without. current_value is the health score the monitor
                    # recorded; lowest first is worst-first, and it needs
                    # nothing but the measurement.
                    selected = sorted(
                        targets, key=lambda t: (t.current_value, t.component)
                    )[:max_targets]

                context["selection_policy"] = selection_policy
                logger.info("Target selection policy: %s (%d selected)",
                            selection_policy, len(selected))

                # Log approval to safety audit
                if self.audit_trail:
                    await self.audit_trail.record_event(
                        event_type=SafetyEventType.DECISION,
                        severity="LOW",
                        description=f"Governance approved {len(selected)} self-improvement targets",
                        action="plan_improvements",
                        outcome="approved",
                        component="enhanced_asi",
                        details={
                            "governance_tier": (
                                decision.decision_tier.value
                                if hasattr(decision, 'decision_tier') and hasattr(decision.decision_tier, 'value')
                                else str(getattr(decision, 'decision_tier', 'unknown'))
                            ),
                            "targets_selected": len(selected),
                            "targets": [t.component for t in selected]
                        }
                    )

                logger.info(f"✅ Governance approved {len(selected)} improvement targets")

            else:
                # Governance unavailable or action_category not mapped.
                # MINOR scope: fail-open with conservative limit (max 2 targets).
                # MODERATE+: fail-closed — higher risk changes need human oversight.
                if scope == ImprovementScope.MINOR:
                    logger.warning(
                        "⚠️  Governance system unavailable — allowing MINOR scope "
                        "self-improvement with conservative target limit (max 2)"
                    )
                    if self.audit_trail:
                        try:
                            await self.audit_trail.record_event(
                                event_type=SafetyEventType.DECISION,
                                severity="MEDIUM",
                                description="Governance unavailable — fail-open for MINOR scope self-improvement",
                                action="plan_improvements",
                                outcome="fail_open",
                                component="enhanced_asi",
                                details={
                                    "phase": "planning",
                                    "scope": scope.value,
                                    "targets_count": len(sorted_targets)
                                }
                            )
                        except Exception as _audit_err:
                            logger.error("SafetyAuditTrail.record_event failed (fail-open branch): %s", _audit_err)
                    selected = sorted_targets[:2]
                else:
                    # MODERATE / MAJOR / TRANSFORMATIVE — fail-closed
                    logger.error(
                        f"🛑 GOVERNANCE GATE FAILED: Governance unavailable for {scope.value} scope — ABORTED"
                    )
                    if self.audit_trail:
                        try:
                            await self.audit_trail.record_event(
                                event_type=SafetyEventType.BLOCKED_ACTION,
                                severity="HIGH",
                                description=f"Governance unavailable — fail-closed for {scope.value} scope self-improvement",
                                action="block_improvement",
                                outcome="blocked",
                                component="enhanced_asi",
                                details={
                                    "phase": "planning",
                                    "scope": scope.value,
                                    "targets_count": len(sorted_targets)
                                }
                            )
                        except Exception as _audit_err:
                            # The fail-OPEN branch above logs this failure; the
                            # fail-CLOSED branch swallowed it silently, so the
                            # higher-severity path was the one that could lose
                            # its record of having blocked anything.
                            logger.error(
                                "SafetyAuditTrail.record_event failed "
                                "(fail-closed branch): %s", _audit_err)
                    raise RuntimeError(
                        f"Governance system is REQUIRED for {scope.value} scope but unavailable. "
                        "Self-improvement cycle ABORTED."
                    )

            logger.info(f"Planning complete: {len(selected)} targets selected")
            return selected

        except Exception as e:
            # "Planning failed" and "nothing was worth improving" are different
            # facts and both used to arrive as []. The cycle reads an empty list
            # as a clean assessment and completes successfully, so a broken
            # planner looked identical to a healthy system with no work to do.
            raise_if_structural(e, "EnhancedASISelfImprovement._plan_improvements")
            logger.error("Planning failed: %s", e)
            raise RuntimeError(f"improvement planning failed: {e}") from e

    def _estimate_risk_level(self, scope: ImprovementScope) -> str:
        """Estimate risk level based on scope"""
        risk_map = {
            ImprovementScope.MINOR: "LOW",
            ImprovementScope.MODERATE: "MEDIUM",
            ImprovementScope.MAJOR: "HIGH",
            ImprovementScope.TRANSFORMATIVE: "CRITICAL"
        }
        return risk_map.get(scope, "MEDIUM")

    #: What a target is worth, in integer units the solver can optimise over.
    #: Scaled by 10 so a 0.1% difference in potential is still expressible.
    _DIFFICULTY_ADJUSTMENT = {"easy": 50, "medium": 0, "hard": -50, "very_hard": -100}

    #: Risk the scope will not accept at all. A MINOR cycle does not touch
    #: critical-risk components; that is a constraint, not a preference, so it
    #: is expressed as one.
    _SCOPE_RISK_CEILING = {
        "minor": {"critical", "high"},
        "moderate": {"critical"},
        "major": set(),
        "transformative": set(),
    }

    def select_targets_by_constraint(
        self,
        targets: List[ImprovementTarget],
        scope: ImprovementScope,
        context: Dict[str, Any],
        max_targets: int,
    ) -> Optional[Dict[str, Any]]:
        """Choose targets by SOLVING the choice, not by describing it in prose.

        Selecting what to improve is an optimisation: take at most k, refuse
        anything above the scope's risk ceiling, and prefer the components whose
        failure reaches furthest through the topology. Every term is a number
        the substrate already holds.

        It was posed as an English chat prompt -- "Select optimal improvement
        targets ... Return JSON" -- which the substrate cannot represent, so it
        declined every time (`unsupported_input`) and the cycle fell to
        worst-health-first. The question's FORM was what forced the model-shaped
        path, not any inability to reason.

        Returns None when the solver cannot express or settle the problem, so
        the caller can fall through. The solver's answer is verified in the
        sense that matters here: it satisfies the stated constraints and no
        admissible selection scores higher.
        """
        try:
            from z3 import Int, Sum

            from core.reasoning.constraint_solver import get_constraint_solver
        except Exception as e:
            raise_if_structural(e, "EnhancedASISelfImprovement.select_targets_by_constraint")
            logger.debug("Constraint solver unavailable: %s", e)
            return None

        solver = get_constraint_solver()
        if not solver.available or not targets:
            return None

        # Cascade weight: a component whose service is a single point of
        # failure, or whose failure takes others down, is worth more to fix.
        # Read from the system observation, which is why that had to be wired.
        topology = ((context or {}).get("system") or {}).get("topology") or {}
        spofs = {str(x).lower() for x in (topology.get("single_points_of_failure") or [])}
        cascade = {str(c.get("service", "")).lower(): int(c.get("affected", 0))
                   for c in (topology.get("cascade_risks") or [])}

        ceiling = self._SCOPE_RISK_CEILING.get(scope.value, set())

        problem = solver.create_problem()
        values: List[int] = []
        admissible: List[int] = []
        for i, t in enumerate(targets):
            solver.add_variable(problem, f"pick_{i}", "int", lower=0, upper=1)

            name = str(t.component).lower()
            worth = int(round(float(t.improvement_potential or 0.0) * 10))
            worth += self._DIFFICULTY_ADJUSTMENT.get(str(t.difficulty), 0)
            worth += 100 * cascade.get(name, 0)
            worth += 250 if name in spofs else 0
            values.append(max(worth, 0))

            if str(t.risk_level) in ceiling:
                # Not a low preference -- inadmissible. Stated as a constraint.
                solver.add_constraint(problem, Int(f"pick_{i}") == 0)
            else:
                admissible.append(i)

        if not admissible:
            logger.info("Constraint selection: no target is admissible at scope %s "
                        "(risk ceiling %s)", scope.value, sorted(ceiling))
            return {"selected_indices": [], "rationale": "no admissible target",
                    "policy": "constraint_solved"}

        picks = [Int(f"pick_{i}") for i in range(len(targets))]
        solver.add_constraint(problem, Sum(picks) <= int(max_targets))
        solver.add_constraint(problem, Sum(picks) >= 1)

        solution = solver.optimize(
            problem, Sum([picks[i] * values[i] for i in range(len(targets))]),
            maximize=True)

        if not solution.satisfiable:
            logger.info("Constraint selection unsatisfiable (%s)", solution.raw_status)
            return None

        chosen = [i for i in range(len(targets))
                  if int(solution.model.get(f"pick_{i}", 0)) == 1]
        rationale = "; ".join(
            f"{targets[i].component}(value={values[i]}"
            + (", SPOF" if str(targets[i].component).lower() in spofs else "")
            + (f", cascade={cascade[str(targets[i].component).lower()]}"
               if str(targets[i].component).lower() in cascade else "")
            + ")"
            for i in chosen)
        logger.info("Constraint selection chose %d of %d: %s",
                    len(chosen), len(targets), rationale or "none")
        return {"selected_indices": chosen,
                "rationale": rationale,
                "policy": "constraint_solved",
                "values": values,
                "excluded_by_risk": [targets[i].component for i in range(len(targets))
                                     if i not in admissible]}

    #: REASONING IS THE SUBSTRATE'S, AND THE MODEL IS A CONTRIBUTOR TO IT.
    #:
    #: Every reasoning call in this file passed `mode=ReasoningMode.NEURAL`,
    #: which routes straight to the model and skips `_substrate_first()`
    #: entirely -- so with llama-server down the log read "LLM target selection
    #: unavailable ... falling back to the deterministic policy", as though the
    #: only two options were a model or a heuristic. Torin was never asked.
    #:
    #: The bridge is substrate-first by construction: it asks whether the
    #: substrate can represent the question itself before any model is
    #: consulted, and its own comment states the principle -- model availability
    #: affects input coverage, not whether there is a reasoning floor. The model
    #: is reached only if the router escalates to it, which is what "teacher /
    #: helper" means operationally: it may propose, it is never the seat of the
    #: decision.
    #:
    #: The deterministic worst-health-first policy stays as the floor beneath
    #: both. It is not a fallback for a missing model; it is what the cycle does
    #: when neither substrate nor model has anything better to say.
    async def _reason_select_targets(
        self,
        targets: List[ImprovementTarget],
        scope: ImprovementScope,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Use Unified LLM to select optimal improvement targets"""
        try:
            # THE DIAGNOSIS WAS ALREADY IN HAND AND WAS BEING DISCARDED.
            #
            # This described each target with three numbers -- potential,
            # difficulty, risk -- while `t.context["issues"]` held the actual
            # finding ("Content security scanner is not running: no port is
            # registered for `security_content`"). Reasoning was asked to choose
            # between nine items it had been told nothing about, so no reasoner,
            # substrate or model, could do better than worst-first.
            def _describe(index: int, t) -> str:
                issues = [str(i) for i in (t.context or {}).get("issues", [])][:3]
                lines = [f"{index}. {t.component} — health {t.current_value} "
                         f"(target {t.target_value}), difficulty {t.difficulty}, "
                         f"risk {t.risk_level}"]
                lines += [f"     finding: {i}" for i in issues]
                status = (t.context or {}).get("status")
                if status:
                    lines.append(f"     status: {status}")
                return "\n".join(lines)

            targets_desc = "\n".join(_describe(i, t) for i, t in enumerate(targets))

            # And the system it all sits in, so a component nine services depend
            # on is distinguishable from one nothing depends on.
            _system = (context or {}).get("system") or {}
            _t = _system.get("topology") or {}
            system_desc = (
                f"Services running: {((_system.get('environment') or {}).get('services') or {})}\n"
                f"Critical services: {_t.get('critical_services')}\n"
                f"Single points of failure: {_t.get('single_points_of_failure')}\n"
                f"Cascade risks: {_t.get('cascade_risks')}"
            ) if _system else "System observation unavailable."

            query = f"""Select optimal improvement targets:

System state:
{system_desc}

Available targets:
{targets_desc}

Scope: {scope.value}
Max targets: {3 if scope == ImprovementScope.MODERATE else 5}

Select targets that:
- Maximize improvement potential
- Balance risk vs reward
- Are achievable given scope

Return JSON:
{{
    "selected_indices": [0, 2, 4],
    "rationale": "..."
}}"""

            # Route through neural bridge for automatic memory capture
            from core.reasoning.neural_bridge import ReasoningRequest, ReasoningMode

            request = ReasoningRequest(
                query=query,
                context=[f"Selecting improvement targets", f"Scope: {scope.value}", f"Available targets: {len(targets)}"],
            )

            result = await asyncio.wait_for(self.neural_bridge.reason(request), timeout=300.0)
            return self._extract_json(self._answer_of(result))

        except Exception as e:
            # NO INVENTED SELECTION.
            #
            # This returned `range(min(3, len(targets)))` -- the first three
            # targets -- whenever the LLM call failed. The caller received a
            # well-formed selection it could not distinguish from a reasoned
            # one, so a broken or timed-out model silently chose what the system
            # would modify about itself. In a self-improvement pipeline that is
            # the last place a plausible-looking default belongs.
            raise_if_structural(e, "EnhancedASISelfImprovement._reason_select_targets")
            logger.error("LLM target selection failed: %s", e)
            raise RuntimeError(
                f"target selection unavailable ({type(e).__name__}: {e}); "
                f"refusing to select improvement targets without it") from e

    #: A degradation whose cause is "this is not running" is fixed by starting
    #: it, not by writing code. These are the phrases HealthMonitor emits for
    #: exactly that condition (see _failures_reported_as_metrics and the
    #: explicit issues in the individual checks).
    _LIVENESS_ISSUE_MARKERS = (
        'is not running', 'not alive', 'is inactive', 'not initialized',
        'not attached', 'reports it is not running',
    )

    #: How long a health reading stays current. Beyond this the component is
    #: treated as unmeasured rather than as whatever it last was.
    HEALTH_READING_MAX_AGE_SEC = 900

    #: How many components one assessment will take a live reading of. Each is
    #: a real measurement, so this is a cost bound, not a coverage claim --
    #: worst-first ordering is what makes a bound acceptable.
    MAX_ASSESSMENT_CANDIDATES = 10

    #: Behavioural observation window. Short on purpose: this runs once per
    #: cycle and is a sample of live traffic, not a benchmark.
    BEHAVIOUR_OBSERVE_SEC = 2.0

    def _reading_is_live(self, component: str, health: Any) -> bool:
        """Is this reading from a process that still exists, and recent enough?

        Returns False for a stale reading or one written by a process that has
        since exited. Both are "not measured", which is a different fact from
        any health score -- and the one this file spent its history conflating.
        """
        import socket as _socket

        meta = health.get("measured_by") if isinstance(health, dict) else None
        if not meta:
            # Written before provenance was recorded. Not treated as a failure,
            # but not treated as fresh either: it is accepted only if the row
            # itself is recent.
            updated = health.get("last_updated") if isinstance(health, dict) else None
            if updated is None:
                return True
            age = (datetime.now() - updated.replace(tzinfo=None)).total_seconds()
            return age <= self.HEALTH_READING_MAX_AGE_SEC

        try:
            measured_at = datetime.fromisoformat(meta["at"])
        except (KeyError, TypeError, ValueError):
            return False
        age = (datetime.now() - measured_at).total_seconds()
        if age > self.HEALTH_READING_MAX_AGE_SEC:
            logger.debug("Health reading for %s is %.0fs old; treating as unmeasured",
                         component, age)
            return False

        # Same host and the writing process still alive?
        if meta.get("host") != _socket.gethostname():
            return False
        pid = meta.get("pid")
        if pid is None:
            return False
        try:
            os.kill(int(pid), 0)          # signal 0: existence check only
        except (OSError, ValueError):
            logger.debug(
                "Health reading for %s came from pid %s which is gone; the "
                "in-process state it measured no longer exists", component, pid)
            return False
        return True

    async def _remeasure(self, component: str) -> Optional[Dict[str, Any]]:
        """Re-run the health check for a component and return the fresh reading.

        _get_component_health reads the PERSISTED store, which still holds the
        measurement that identified the fault -- comparing against it after a
        restart would compare a value to itself and confirm nothing. This drives
        the same check that detected the problem, so the verdict comes from the
        instrument rather than from the actor.
        """
        from core.health.health_monitor import get_health_monitor

        monitor = get_health_monitor()
        base = component.split(".", 1)[0]
        if base not in monitor.COMPONENT_MANIFEST:
            return None

        await monitor.check_component_health(base)   # re-measures and persists
        record = monitor.component_health.get(component)
        if record is None:
            return None
        # Read the COMPUTED score, not a status bucket. _STATUS_SCORE maps the
        # four statuses to 100/75/40/10, so a component remediated from 0.61 to
        # 0.89 -- a real recovery -- re-measured as 75.0 both times and the
        # verification concluded nothing had changed. This is the verification
        # step for remediation; it has to be able to see the improvement it is
        # verifying. None stays None: unmeasurable is not a score.
        computed = (record.metrics or {}).get("_health_score")
        if computed is None:
            return None
        score = round(float(computed) * 100.0, 2)
        return {"health_score": float(score),
                "status": record.status.value,
                "issues": list(record.issues or [])}

    async def _remediate_targets(
        self,
        targets: List[ImprovementTarget],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Phase 2.5: ACT on targets that are simply down.

        The cycle could previously only do one thing with a degraded component:
        ask an LLM to write code for it. For the most common real degradation --
        a subsystem that is not running -- generated code is the wrong remedy
        and the right one already existed: RecoveryManager can restart these,
        and now has registered handlers for them.

        Restarting a stopped subsystem IS an improvement, and it is reported as
        one. A cycle that only ever emits failures has no way to show that
        anything got better.
        """
        outcome = {"attempted": [], "recovered": [], "failed": [],
                   "not_applicable": [], "remediation_available": True}

        try:
            from core.health.recovery_manager import get_recovery_manager
            recovery = get_recovery_manager()
        except Exception as e:
            raise_if_structural(e, "EnhancedASISelfImprovement._remediate_targets")
            # An empty outcome is what a run where NOTHING NEEDED REMEDIATION
            # also returns, and this one is persisted into the cycle record. A
            # later reader could not tell "no component was down" from "the
            # thing that restarts components could not be reached" -- and the
            # second means every liveness target below went unaddressed.
            logger.error("Recovery manager unavailable; cannot remediate: %s", e)
            outcome["remediation_available"] = False
            outcome["error"] = f"{type(e).__name__}: {e}"
            return outcome

        for target in targets:
            issues = [str(i).lower() for i in (target.context or {}).get("issues", [])]
            liveness = [i for i in issues
                        if any(marker in i for marker in self._LIVENESS_ISSUE_MARKERS)]
            if not liveness:
                outcome["not_applicable"].append(target.component)
                continue

            # Sub-components are addressed by their own id; the restart handler
            # is keyed on the subsystem, so both forms are tried.
            keys = [target.component]
            if "." in target.component:
                keys.append(target.component.split(".", 1)[1])
                keys.append(target.component.split(".", 1)[0])

            outcome["attempted"].append(target.component)
            before = target.current_value
            acted = False
            for key in keys:
                try:
                    if not await recovery.execute_recovery_action(
                            key, "restart_component", {"reason": liveness[0],
                                                       "source": "asi_improvement_cycle"}):
                        continue

                    # THE RESTART RETURNING TRUE IS NOT EVIDENCE.
                    #
                    # A handler reports that its start call did not raise. That
                    # is not the same as the subsystem being up: restarting the
                    # LLM returned True while its inference worker stayed dead,
                    # so the cycle recorded a recovery, moved on, and then
                    # failed in planning against the same dead worker. Recovery
                    # is confirmed by RE-MEASURING, through the health path that
                    # detected the fault in the first place.
                    after = await self._remeasure(target.component)
                    if after is None:
                        logger.warning(
                            "Restart of %s reported success but the component has no "
                            "measurement; not counted as recovered", target.component)
                        continue
                    if after["health_score"] > before:
                        outcome["recovered"].append(target.component)
                        logger.info(
                            "✅ RECOVERED %s: %.0f -> %.0f (%s)",
                            target.component, before, after["health_score"], liveness[0][:60])
                        acted = True
                        break
                    logger.info(
                        "Restart of %s reported success but health did not improve "
                        "(%.0f -> %.0f); not counted as recovered",
                        target.component, before, after["health_score"])
                except Exception as e:
                    raise_if_structural(e, "EnhancedASISelfImprovement._remediate_targets")
                    logger.debug("Restart of %s failed: %s", key, e)
            if not acted:
                outcome["failed"].append(target.component)

        logger.info(
            "Remediation: %d attempted, %d recovered, %d failed, %d not applicable",
            len(outcome["attempted"]), len(outcome["recovered"]),
            len(outcome["failed"]), len(outcome["not_applicable"]))
        return outcome

    async def _generate_improvements(
        self,
        targets: List[ImprovementTarget],
        scope: ImprovementScope,
        context: Dict[str, Any]
    ) -> List[str]:
        """Phase 3: Generate improvements using tool_registry (300+ tools)"""
        improvements = []
        #: Targets that could not be attempted, and why. A target that silently
        #: disappears from this phase is indistinguishable from one that was
        #: never selected.
        skipped: List[Dict[str, str]] = []

        try:
            if not self.tool_registry:
                # `[]` here means "generated nothing", which is what a cycle
                # with no viable targets also returns — so a missing tool
                # registry completed the phase and the cycle carried on to
                # report a successful run that produced no code. The deployer
                # guard two phases later raises for the identical shape; this
                # one warned and returned the ambiguous value.
                raise RuntimeError(
                    "Tool registry is unavailable, so no improvement can be "
                    "generated; refusing to report an empty generation phase "
                    "as a completed one.")

            for target in targets:
                # Map improvement type to tool name
                # THE TOOL IS CHOSEN BY THE RANKER, NOT BY A DICTIONARY MISS.
                #
                # This was `tool_map.get(target.metric, "generate_function")`
                # over a six-entry map keyed on `performance`/`quality`/
                # `coverage`/... -- and `target.metric` is hardcoded
                # "health_score" at the one place targets are constructed. The
                # lookup therefore ALWAYS missed and every improvement, for
                # every component, for every finding, was `generate_function`.
                # Forever. A 300+ tool registry and a ranker (BM25 + encoder +
                # capability graph) sat behind a dict that could not hit.
                #
                # `discover_tools` scores the whole live registry against the
                # actual finding text, which is what makes "the scanner is not
                # running" and "outcomes are recorded asymmetrically" able to
                # reach different tools. The score of the chosen tool is kept:
                # it is the model-free signal for whether the selection was any
                # good, and it is recorded with the improvement.
                _issues = " ".join(str(i) for i in (target.context or {}).get("issues", []))
                # `target.metric` is the hardcoded literal "health_score" and
                # contributes only noise -- it pulled `check_mysql_health` and
                # `get_team_health_metrics` to the top for every finding. The
                # component and the finding text are the signal.
                _query = f"{target.component} {_issues}".strip()
                try:
                    ranked = self.tool_registry.discover_tools(
                        _query, limit=5, with_scores=True)
                except Exception as e:
                    raise_if_structural(e, "EnhancedASISelfImprovement._generate_improvements")
                    logger.warning("Tool discovery failed for %s (%s)",
                                   target.component, e)
                    ranked = []

                if not ranked:
                    logger.warning("No tool ranked for %s; skipping rather than "
                                   "defaulting to a generator that may not fit",
                                   target.component)
                    skipped.append({"component": target.component,
                                    "reason": "no_tool_ranked"})
                    continue

                tool, _tool_score = ranked[0]
                tool_name = getattr(tool, "name", "unknown")

                # THIS DIVIDED THE TOP SCORE BY ITSELF.
                #
                # `_tool_score` IS `ranked[0][1]`, so `_tool_score / _top_score`
                # was 1.0 on every call a score could be computed for -- a
                # measurement with one possible value. `selection_score` is
                # meant to say how well the CHOSEN tool ranked, and since this
                # code always takes `ranked[0]`, the answer to that is trivially
                # "best". What is NOT trivial, and is what the signal is
                # actually for, is how DECISIVELY it was best: a top tool
                # barely ahead of the runner-up was close to arbitrary, and a
                # tool chosen by a wide margin was not.
                #
                # 1.0 means nothing else came close; near 0.0 means the ranker
                # had no real preference. None when there was no runner-up to
                # compare against -- one candidate is not a decisive choice, it
                # is an absence of alternatives.
                _chosen_score = float(_tool_score)
                _runner_up = float(ranked[1][1]) if len(ranked) > 1 else None
                if _runner_up is None or _chosen_score <= 0:
                    _selection_score = None
                else:
                    _selection_score = round(
                        max(0.0, (_chosen_score - _runner_up) / _chosen_score), 4)
                logger.info("Tool for %s: %s (score %.3f) — ranked over %d candidates: %s",
                            target.component, tool_name, float(_tool_score), len(ranked),
                            ", ".join(getattr(t, "name", "?") for t, _ in ranked[:4]))

                # Build requirements and get existing code
                requirements = self._build_requirements(target, scope)
                try:
                    existing_code = await self._get_existing_code(target.component)
                except FileNotFoundError as missing:
                    # SKIP THIS TARGET, NOT THE CYCLE. `_get_existing_code` no
                    # longer fabricates placeholder source, which is right --
                    # but one component without a file must not abort
                    # generation for every other target. Same shape as the
                    # missing-tool `continue` above, and the reason is recorded
                    # rather than dropped.
                    logger.warning("Skipping %s: %s", target.component, missing)
                    skipped.append({"component": target.component,
                                    "reason": "source_not_found"})
                    continue

                # Execute tool with target context.
                # GenerateFunctionTool (and siblings) require positional-style
                # 'description' and 'function_name'; all tools accept **kwargs
                # so the extra keyword args are harmless for other tools.
                # THROUGH THE REGISTRY, NOT STRAIGHT AT THE TOOL.
                #
                # This called `tool.execute(...)` -- the raw Tool method --
                # which bypasses `ToolRegistry.execute_tool()`, and that is
                # where the safety framework lives: the per-invocation
                # governance evaluation, the irreversibility gate, the
                # determination attached to the result, and the outcome
                # recorded to `safety_assessments` afterwards.
                #
                # So the ONE subsystem whose purpose is to modify the system
                # was the one running its tools ungated. Every other caller in
                # the codebase goes through the registry; self-improvement went
                # around it.
                _fn_slug = target.component.replace('.', '_').replace('/', '_').replace('-', '_')
                result = await self.tool_registry.execute_tool(
                    tool_name,
                    {
                        "description": requirements,
                        "function_name": f"improve_{_fn_slug}",
                        "component": target.component,
                        "requirements": requirements,
                        "existing_code": existing_code,
                        "scope": scope.value,
                        "context": context,
                        "parameters": {
                            "metric": target.metric,
                            "current_value": target.current_value,
                            "target_value": target.target_value,
                        },
                    },
                )

                # The safety layer's reading of what we just ran, kept with the
                # improvement rather than discarded.
                _safety = (result.metadata or {}).get("safety") if isinstance(
                    getattr(result, "metadata", None), dict) else None
                if _safety:
                    logger.info("Tool %s ran at risk=%s (rule %s)", tool_name,
                                _safety.get("risk_level"), _safety.get("rule") or "-")

                if result.success:
                    # VERIFICATION GATE: Verify generated code matches requirements
                    _output = result.output if isinstance(result.output, dict) else {}
                    generated_code = _output.get("code", "")

                    # NO CODE IS A FAILED GENERATION, NOT A QUIET SUCCESS.
                    #
                    # The branch below read `if generated_code and self.llm:` and
                    # fell through to an else commented "No LLM available or no
                    # code" -- so an EMPTY result skipped verification entirely
                    # and was then stored, counted as an improvement, validated,
                    # and passed the sandbox (an empty module imports perfectly).
                    # Measured: every improvement in `generated_improvements` from
                    # today is zero bytes with `file_paths: []` and
                    # `quality_score: 0.8`, and the cycle reported
                    # "2/2 validated, 2/2 tested".
                    #
                    # A tool that returns success with no code has not improved
                    # anything, and the cycle must not be able to report that it
                    # has.
                    if not StaticCodeAnalyzer._has_executable_code(generated_code or ""):
                        logger.warning(
                            "Skipping %s: %s returned success but no executable code "
                            "(%d bytes)", target.component, tool_name,
                            len(generated_code or ""))
                        skipped.append({"component": target.component,
                                        "reason": "generator_returned_no_code"})
                        continue

                    if generated_code and self.neural_bridge:
                        verification = await self._verify_generated_code(
                            code=generated_code,
                            requirements=requirements,
                            target=target,
                            tool_name=tool_name
                        )

                        if not verification["matches_requirements"]:
                            logger.warning(
                                f"⚠️  Generated code verification failed for {target.component}: "
                                f"{verification['reason']}"
                            )
                            # Skip this improvement if verification fails
                            continue

                        # Update confidence based on verification
                        verified_confidence = min(
                            _output.get("confidence", 0.8),
                            verification.get("confidence", 0.8)
                        )
                    else:
                        # Code exists but no verifier was reachable. The tool's
                        # own confidence is a claim by the producer about its own
                        # output, so it is carried through UNVERIFIED rather than
                        # presented as a verification result.
                        verified_confidence = _output.get("confidence", 0.8)
                        logger.info("No verifier reachable for %s; carrying the "
                                    "generator's own confidence unverified",
                                    target.component)

                    # Store verified generated code and create improvement ID
                    improvement_id = f"{target.component}_{target.metric}_{int(time.time())}"
                    await self._store_generated_code(improvement_id, {
                        "code": generated_code,
                        "tool_used": tool_name,
                        "confidence": verified_confidence,
                        "target": target,
                        "file_paths": _output.get("file_paths", []),
                        "verification": verification if generated_code else None
                    })
                    improvements.append(improvement_id)

                    # COMPUTED AND THEN DROPPED. `_selection_score` had exactly
                    # one reference in the file -- the line that assigned it --
                    # so the one model-free signal about whether the tool
                    # choice was any good never left the local scope.
                    # `tool_usage_history.selection_score` is the column built
                    # for it and stayed NULL. Recorded on the context here so
                    # it reaches the persisted cycle record.
                    context.setdefault("tool_selection", []).append({
                        "improvement_id": improvement_id,
                        "component": target.component,
                        "tool": tool_name,
                        "score": round(_chosen_score, 4),
                        "runner_up": (round(_runner_up, 4)
                                      if _runner_up is not None else None),
                        "decisiveness": _selection_score,
                        "candidates": len(ranked),
                    })
                    logger.info(f"✅ Generated improvement for {target.component} using {tool_name}")
                else:
                    logger.warning(f"❌ Tool {tool_name} failed: {result.error}")

            if skipped:
                logger.warning(
                    "Generation skipped %d target(s): %s", len(skipped),
                    ", ".join(f"{s['component']} ({s['reason']})" for s in skipped))
            logger.info(f"Generation complete: {len(improvements)} improvements "
                        f"generated, {len(skipped)} skipped")
            return improvements

        except Exception as e:
            # Same shape as assessment: [] here is read as "nothing could be
            # improved", not "the generator broke". A cycle that silently
            # generates nothing still records itself as a completed cycle.
            logger.error(f"Generation failed: {e}", exc_info=True)
            raise RuntimeError(f"Improvement generation failed: {e}") from e

    async def _verify_generated_code(
        self,
        code: str,
        requirements: str,
        target: ImprovementTarget,
        tool_name: str
    ) -> Dict[str, Any]:
        """
        Verify generated code matches requirements using static analysis + LLM.
        NO SILENT FALLBACKS - fails loudly if verification cannot be performed.

        Checks (in order):
        1. Static analysis for dangerous patterns (HARD GATE)
        2. LLM verification for requirements match (HARD GATE)
        3. Code targets the correct component/metric
        4. Code changes are reasonable and safe

        Args:
            code: Generated code to verify
            requirements: Original requirements
            target: Improvement target
            tool_name: Tool that generated the code

        Returns:
            Dict with verification results:
            {
                "matches_requirements": bool,
                "confidence": float (0-1),
                "reason": str,
                "issues": List[str],
                "static_analysis": Dict
            }

        Raises:
            RuntimeError: If LLM service unavailable or verification fails
        """
        # HARD GATE 1: Static analysis (deterministic check)
        logger.info(f"🔍 Running static analysis on generated code from {tool_name}")
        static_result = StaticCodeAnalyzer.analyze(code, strict=True)

        if not static_result["safe"]:
            logger.error(f"🛑 STATIC ANALYSIS FAILED: {static_result['reason']}")
            raise RuntimeError(
                f"Generated code failed static analysis: {static_result['reason']}. "
                f"Dangerous patterns: {static_result['dangerous_patterns']}"
            )

        logger.info(f"✅ Static analysis passed")

        # HARD GATE 2: a semantic verdict is required. A MODEL IS NOT.
        #
        # This read "LLM service is REQUIRED for code verification. Cannot
        # proceed without semantic verification" and refused on `not self.llm`
        # -- so the substrate could not check its own generated code unless a
        # model was up, which is the model-as-brain architecture stated as
        # policy. What the gate actually needs is a VERDICT; where the verdict
        # comes from is not its business.
        #
        # The verdict is asked of the substrate: the bridge routes through
        # `_substrate_first` and the eleven kinds, and there is no model
        # fallback -- a question it cannot settle returns honest inability. The
        # gate is exactly as strict: no verdict is still a refusal, three lines down.
        # What changed is that "no model" and "no verdict" are no longer the
        # same sentence.

        # Build verification prompt
        verification_prompt = f"""Verify that the generated code matches the requirements.

**Target:**
- Component: {target.component}
- Metric: {target.metric}
- Current Value: {target.current_value}
- Target Value: {target.target_value}
- Improvement Type: {tool_name}

**Requirements:**
{requirements}

**Generated Code:**
```python
{code}
```

**Verification Checklist:**
1. Does the code address the stated requirements?
2. Does it target the correct component ({target.component})?
3. Does it improve the metric ({target.metric})?
4. Are the changes reasonable and safe?
5. Are there unrelated changes or scope creep?

Respond in JSON format:
{{
    "matches_requirements": true/false,
    "confidence": 0.0-1.0,
    "reason": "Brief explanation",
    "issues": ["list", "of", "issues"] or []
}}
"""

        # HARD GATE 3: LLM verification with timeout
        try:
            # THIS OVERRODE THE SERVICE DEFAULT WITH THE VALUE THAT DEFAULT
            # EXISTS TO REPLACE. UnifiedLLMService.generate() declares
            # max_tokens=2048, commented "Increased from 500 - allows fuller
            # responses" -- 500 had already been found to truncate. This gate
            # passed 500 explicitly and so reintroduced it, on the safety check.
            #
            # The served model (Qwen3.6) emits chain-of-thought into
            # reasoning_content before its answer, so the budget covers the
            # reasoning first and `content` gets the remainder. Measured here
            # with the verification prompt:
            #
            #   max_tokens=500  -> 16.4s, content truncated mid-JSON, parse FAILS
            #   max_tokens=1500 -> 33.9s, parses
            #   max_tokens=3000 -> 42.2s, parses
            #
            # That is why the cycle died at "Failed to parse LLM verification
            # response ... Raw response:" and discarded every generated
            # improvement. Raising the budget alone would then have hit the 30s
            # timeout, which is below the smallest budget that works, so both
            # move together -- as the budget note in unified_llm says: a short
            # max_tokens causes finish_reason=length truncation, and the timeout
            # is the right lever.
            #
            # Reasoning is kept for this call. It is a judgement about whether
            # generated code matches its requirements, which is exactly the kind
            # of call that benefits from deliberation; suppressing thinking
            # (chat_template_kwargs enable_thinking=false, which this server
            # honours) belongs on structured-extraction calls, not here.
            verification_timeout = 120.0
            logger.info("Running semantic verification (substrate-first) with "
                        f"{verification_timeout:.0f}s timeout")
            from core.reasoning.neural_bridge import ReasoningMode, ReasoningRequest

            request = ReasoningRequest(
                query=verification_prompt,
                context=[f"Verifying generated code for {target.component}",
                         f"Improvement type: {tool_name}"],
            )
            reasoning = await asyncio.wait_for(
                self.neural_bridge.reason(request), timeout=verification_timeout)
            # Reads metadata before the answer, so an unreachable model is
            # reported as an unreachable model rather than as unparseable JSON.
            response = self._answer_of(reasoning)
        except asyncio.TimeoutError:
            raise RuntimeError(
                f"Semantic verification timed out after {verification_timeout:.0f} "
                f"seconds for tool {tool_name}.")
        except Exception as e:
            raise RuntimeError(f"Semantic verification produced no verdict: {e}") from e

        # HARD GATE 4: Parse and validate LLM response
        try:
            # The class already has one way to read JSON out of an LLM reply,
            # used at five other call sites: it strips ```json fences and finds
            # the object inside surrounding prose, and raises rather than
            # substituting a default. This gate was the only place still calling
            # json.loads directly, so a fenced or prose-wrapped reply failed here
            # while the same reply parsed everywhere else.
            result = self._extract_json(response)

            # Validate response structure
            if not isinstance(result, dict):
                raise ValueError("LLM response is not a dictionary")

            if "matches_requirements" not in result:
                raise ValueError("LLM response missing 'matches_requirements' field")

            # Ensure confidence is in valid range
            result["confidence"] = max(0.0, min(1.0, result.get("confidence", 0.5)))

            # Add static analysis results to output
            result["static_analysis"] = static_result

            logger.info(
                f"✅ LLM verification complete: "
                f"matches={result['matches_requirements']}, "
                f"confidence={result['confidence']:.2f}"
            )

            return result

        except (json.JSONDecodeError, ValueError) as e:
            raise RuntimeError(
                f"Failed to parse LLM verification response: {e}. "
                f"Raw response: {response[:200]}"
            ) from e

    async def _validate_improvements(
        self,
        improvements: List[str],
        context: Dict[str, Any]
    ) -> List[str]:
        """Phase 4: Validate improvements - HARD GATE (blocks invalid code)"""
        validated = []

        try:
            # HARD GATE: Validator REQUIRED
            if not self.validator:
                logger.error("🛑 HARD GATE FAILED: Validator not available")
                raise RuntimeError(
                    "UpgradeValidator is REQUIRED for self-improvement. "
                    "Cannot proceed without deterministic validation."
                )

            for improvement_id in improvements:
                # Get generated code
                code = await self._get_generated_code(improvement_id)

                if not code:
                    # SILENTLY SKIPPED. `if code:` with no else dropped an
                    # improvement whose stored code could not be found: it was
                    # neither validated nor failed, it just left the list, and
                    # the only trace was a shorter result. The gate below
                    # ("at least one must validate") then cannot tell five that
                    # failed from five that were never there.
                    #
                    # `_test_improvements` fixed exactly this one phase later;
                    # the same hole was still open here.
                    raise RuntimeError(
                        f"No stored code for improvement {improvement_id}; it was "
                        f"generated and cannot now be found. Refusing to skip it "
                        f"silently.")

                if code:
                    # Validate with baseline metrics enforcement
                    result = await self.validator.validate_upgrade(
                        code=code["code"],
                        file_paths=code.get("file_paths", []),
                        test_suite=code.get("test_suite", ""),
                        metadata=context
                    )

                    # HARD GATE: Validation must pass
                    if result.overall_passed:
                        validated.append(improvement_id)
                        logger.info(f"✅ Validation passed: {improvement_id}")
                    else:
                        # FAIL CYCLE: Validation failure blocks deployment
                        error_msg = f"🛑 HARD GATE FAILED: Validation failed for {improvement_id}"
                        logger.error(error_msg)
                        logger.error(f"   Violations: {result.checks}")

                        # Record failure in audit trail (if available)
                        if self.audit_trail:
                            await self.audit_trail.record_event(
                                event_type=SafetyEventType.BLOCKED_ACTION,
                                severity="HIGH",
                                description=error_msg,
                                action="validate_improvement",
                                outcome="blocked_validation_failed",
                                component="enhanced_asi",
                                details={
                                    "improvement_id": improvement_id,
                                    "validation_failures": [c.check_name for c in result.checks if not c.passed],
                                    "reason": "UpgradeValidator hard gate enforcement"
                                }
                            )

                        raise RuntimeError(
                            f"UpgradeValidator BLOCKED improvement {improvement_id}. "
                            f"Failed checks: {[c.check_name for c in result.checks if not c.passed]}. "
                            f"Self-improvement cycle ABORTED."
                        )

            # HARD GATE: At least one improvement must validate
            if not validated:
                logger.error("🛑 HARD GATE FAILED: No improvements passed validation")
                raise RuntimeError(
                    f"All {len(improvements)} improvements failed validation. "
                    "Self-improvement cycle ABORTED."
                )

            logger.info(f"✅ Validation complete: {len(validated)}/{len(improvements)} improvements validated")
            return validated

        except RuntimeError:
            # Re-raise hard gate failures
            raise
        except Exception as e:
            # HARD GATE: Validation errors block cycle
            logger.error(f"🛑 HARD GATE FAILED: Validation error: {e}")
            raise RuntimeError(f"UpgradeValidator error: {e}. Self-improvement cycle ABORTED.")

    async def _test_improvements(
        self,
        improvements: List[str],
        context: Dict[str, Any]
    ) -> List[str]:
        """Phase 5: Test improvements in sandbox - HARD GATE (blocks failing tests)"""
        tested = []

        try:
            # HARD GATE: Sandbox REQUIRED
            from core.learning.upgrade_sandbox import get_upgrade_sandbox
            sandbox = get_upgrade_sandbox()

            if not sandbox:
                logger.error("🛑 HARD GATE FAILED: Sandbox not available")
                raise RuntimeError(
                    "UpgradeSandbox is REQUIRED for self-improvement. "
                    "Cannot deploy untested code."
                )

            for improvement_id in improvements:
                # Get code
                code = await self._get_generated_code(improvement_id)

                if not code:
                    # SILENTLY SKIPPED. `if code:` dropped an improvement whose
                    # stored code could not be found -- it was neither tested
                    # nor failed, it simply left the list, and the only trace
                    # was a shorter result. An artifact that vanished between
                    # generation and testing is a storage fault, and the gate
                    # below ("at least one must pass") cannot see the
                    # difference between five that failed and five that were
                    # never there.
                    raise RuntimeError(
                        f"No stored code for improvement {improvement_id}; it was "
                        f"generated and cannot now be found. Refusing to skip it "
                        f"silently."
                    )

                if code:
                    # Run in sandbox
                    # `language`, `timeout` and `context` are NOT parameters of
                    # run_code. Its signature is
                    # `run_code(code, entry_point="main", *args, **kwargs)`, so
                    # all three were forwarded as keyword arguments INTO the
                    # generated function -- which was then called as
                    # `main(language=..., timeout=..., context=...)`. The
                    # generators emit `improve_<component>`, never `main`, so
                    # the import failed before the arity ever mattered and this
                    # hard gate could not be passed by any generated code.
                    # Timeout is the sandbox's own config, not a call argument.
                    # AN EMPTY MODULE IMPORTS PERFECTLY.
                    #
                    # Import-only is the right test for code whose signature the
                    # caller does not know, but it says nothing about whether
                    # there is any code. Both improvements in the last cycle were
                    # ZERO BYTES and this gate passed them 2/2 — a hard gate that
                    # cannot fail for the emptiest possible input is not a gate.
                    # Checked before the container is even started.
                    if not StaticCodeAnalyzer._has_executable_code(code.get("code") or ""):
                        raise RuntimeError(
                            f"Improvement {improvement_id} carries no executable code "
                            f"({len(code.get('code') or '')} bytes). Refusing to record "
                            f"a passed sandbox test for an empty module.")

                    result = await sandbox.run_code(
                        code["code"],
                        entry_point=None,      # import-only: see run_code
                    )

                    # HARD GATE: Tests must pass
                    if result.success and not result.errors:
                        tested.append(improvement_id)
                        logger.info(f"✅ Testing passed: {improvement_id}")
                    else:
                        # FAIL CYCLE: Test failure blocks deployment
                        error_msg = f"🛑 HARD GATE FAILED: Testing failed for {improvement_id}"
                        logger.error(error_msg)
                        logger.error(f"   Errors: {result.errors}")

                        # Record failure in audit trail
                        if self.audit_trail:
                            await self.audit_trail.record_event(
                                event_type=SafetyEventType.BLOCKED_ACTION,
                                severity="HIGH",
                                description=error_msg,
                                action="sandbox_test_improvement",
                                outcome="blocked_tests_failed",
                                component="enhanced_asi",
                                details={
                                    "improvement_id": improvement_id,
                                    "test_errors": result.errors,
                                    "reason": "UpgradeSandbox hard gate enforcement"
                                }
                            )

                        raise RuntimeError(
                            f"UpgradeSandbox BLOCKED improvement {improvement_id}. "
                            f"Test errors: {result.errors}. "
                            f"Self-improvement cycle ABORTED."
                        )

            # HARD GATE: At least one improvement must pass testing
            if not tested:
                logger.error("🛑 HARD GATE FAILED: No improvements passed testing")
                raise RuntimeError(
                    f"All {len(improvements)} improvements failed testing. "
                    "Self-improvement cycle ABORTED."
                )

            logger.info(f"✅ Testing complete: {len(tested)}/{len(improvements)} improvements tested")
            return tested

        except RuntimeError:
            # Re-raise hard gate failures
            raise
        except Exception as e:
            # HARD GATE: Testing errors block cycle
            logger.error(f"🛑 HARD GATE FAILED: Testing error: {e}")
            raise RuntimeError(f"UpgradeSandbox error: {e}. Self-improvement cycle ABORTED.")

    async def _is_deployment_safe(
        self,
        scope: ImprovementScope,
        improvements: List[str],
        context: Dict[str, Any]
    ) -> bool:
        """Check if deployment is safe - HARD GATE (blocks unhealthy deployments)"""

        # HARD GATE 0: DOES THE SYSTEM BEING UPGRADED STILL WORK?
        #
        # `UpgradeTestSuite` is 551 lines of real integration tests -- database
        # integrity, schema and queries, core/iOS/backend service health, the
        # LLM, memory and learning API contracts, an end-to-end flow, service
        # communication, response time, memory and throughput -- and it had
        # ZERO CALLERS. Built to answer exactly "is the system this change is
        # going into still sound", and never asked.
        #
        # Everything the cycle checked before this was about the CHANGE: static
        # analysis of the generated text, a sandbox import, a health average.
        # Nothing exercised the running subsystems the change would land in.
        #
        # `validate_upgrade(test_suite=...)` reads a field that
        # `_store_generated_code` never writes, so the validator has been
        # receiving "" on every improvement ever generated. That is the same
        # gap from the other side.
        try:
            from pathlib import Path as _Path

            from core.learning.upgrade_test_suite import UpgradeTestSuite

            suite = UpgradeTestSuite(workspace_path=_Path(__file__).resolve().parents[2])
            suite_result = await suite.run_all_tests()
            context["upgrade_test_suite"] = {
                "total": suite_result.total_tests,
                "passed": suite_result.passed,
                "failed": suite_result.failed,
                "skipped": suite_result.skipped,
                "summary": suite_result.summary,
            }
            if suite_result.failed:
                failed_names = [t.name for t in (suite_result.test_results or [])
                                if getattr(t, "passed", True) is False]
                logger.error(
                    "🛑 HARD GATE FAILED: the system does not pass its own upgrade "
                    "tests (%d/%d failed: %s) — refusing to deploy a self-modification "
                    "into it", suite_result.failed, suite_result.total_tests,
                    ", ".join(failed_names[:6]))
                if self.audit_trail:
                    await self.audit_trail.record_event(
                        event_type=SafetyEventType.BLOCKED_ACTION,
                        severity="HIGH",
                        description=(f"Upgrade test suite failed "
                                     f"{suite_result.failed}/{suite_result.total_tests}"),
                        action="upgrade_test_suite",
                        outcome="blocked_system_tests_failed",
                        component="enhanced_asi",
                        details={"failed": failed_names,
                                 "summary": suite_result.summary},
                    )
                return False
            # A SKIPPED TEST DID NOT ANSWER THE QUESTION THIS GATE ASKS.
            #
            # `skipped` was hardcoded to 0 in the suite, so this gate has only
            # ever seen zero -- while up to seven tests could return
            # {"status": "skipped"} and be counted as PASSED. Gate 0 asks "does
            # the system this change is going into still work"; a test that
            # could not run because its dependency was unavailable has not
            # said yes, and deploying a self-modification on that is the same
            # mistake as treating an unrun benchmark as a clean capability pass.
            if suite_result.skipped:
                skipped_names = [t.name for t in (suite_result.test_results or [])
                                 if getattr(t, "skipped", False)]
                logger.error(
                    "🛑 HARD GATE FAILED: %d of %d system tests could not run "
                    "(%s) — the system's health is unverified, so a "
                    "self-modification must not be deployed into it",
                    suite_result.skipped, suite_result.total_tests,
                    ", ".join(skipped_names[:6]))
                if self.audit_trail:
                    await self.audit_trail.record_event(
                        event_type=SafetyEventType.BLOCKED_ACTION,
                        severity="HIGH",
                        description=(f"System tests unverified: "
                                     f"{suite_result.skipped}/{suite_result.total_tests} skipped"),
                        action="upgrade_test_suite",
                        outcome="blocked_system_tests_skipped",
                        component="enhanced_asi",
                        details={"skipped": skipped_names,
                                 "summary": suite_result.summary},
                    )
                return False

            logger.info("✅ Upgrade test suite: %d/%d passed (%d n/a)",
                        suite_result.passed, suite_result.total_tests,
                        suite_result.total_tests - suite_result.passed)
        except Exception as e:
            # A gate that cannot run is not a gate that passed.
            raise_if_structural(e, "EnhancedASISelfImprovement._is_deployment_safe")
            logger.error("🛑 HARD GATE FAILED: upgrade test suite could not run: %s", e)
            return False

        # HARD GATE 1: System health check via ImprovementMonitor
        if self.monitor:
            try:
                system_state = await self.monitor.get_system_state()

                # Support both dict-style and attribute-style states
                # A GATE MUST FAIL CLOSED.
                #
                # These read `overall_health_score` with a default of 100.0 and
                # `critical_components` with a default of 0 -- so a state that
                # did not carry those fields was read as a perfectly healthy
                # system with nothing critical, and the gate OPENED. The one
                # condition the gate exists to detect is the one it could not
                # see. Absence now raises, which the handler below turns into a
                # refusal to deploy.
                def _required(name: str):
                    value = (system_state.get(name) if isinstance(system_state, dict)
                             else getattr(system_state, name, None))
                    if value is None:
                        raise ValueError(
                            f"system state carries no {name!r}; system health "
                            f"cannot be confirmed and deployment must not proceed")
                    return value

                overall_health = float(_required("overall_health_score"))
                critical_components = int(_required("critical_components"))
                active_degradations = int(_required("active_degradations"))
                total_components = int(_required("total_components"))
                overall_error_rate = active_degradations / max(total_components, 1)

                # Check overall health score (threshold: 80)
                if overall_health < 80:
                    logger.error(
                        f"🛑 HARD GATE FAILED: System health too low for deployment "
                        f"({overall_health:.1f}/100, threshold: 80)"
                    )
                    return False

                # Check for critical components
                if critical_components > 0:
                    logger.error(
                        f"🛑 HARD GATE FAILED: {critical_components} components in CRITICAL state"
                    )
                    return False

                # Check error rate (threshold: 5%)
                if overall_error_rate > 0.05:
                    logger.error(
                        f"🛑 HARD GATE FAILED: Error rate too high "
                        f"({overall_error_rate:.1%}, threshold: 5%)"
                    )
                    return False

                logger.info(
                    f"✅ ImprovementMonitor health check passed "
                    f"(health={overall_health:.1f}, "
                    f"error_rate={overall_error_rate:.1%})"
                )

            except Exception as e:
                logger.error(f"🛑 HARD GATE FAILED: Health check error: {e}")
                return False
        else:
            # No monitor means system health is UNKNOWN, not acceptable. This
            # logged a warning and fell through to deploy -- the gate was
            # skipped entirely whenever the thing that evaluates it was absent.
            logger.error(
                "🛑 HARD GATE FAILED: ImprovementMonitor unavailable — system "
                "health cannot be verified, so deployment is refused")
            return False

        # HARD GATE 2: Human approval for major/transformative changes.
        #
        # This read `context.get("human_approved", False)` -- a boolean the
        # CALLER puts in its own dictionary. The thing being governed supplied
        # its own authorization, nothing in core/ ever set the key, and the
        # error message told you to set it yourself. An approval nobody granted,
        # revocable by nobody, recorded nowhere.
        #
        # Now the request is a row, a person decides it in the dashboard, and
        # the decision is read back from that row. Pending is NOT approval.
        if scope in [ImprovementScope.MAJOR, ImprovementScope.TRANSFORMATIVE]:
            from core.governance import approval_requests

            components = sorted({str(t) for t in (context.get("target_components")
                                                  or improvements or [])})
            action_id = (f"asi:{scope.value}:"
                         f"{hashlib.sha256('|'.join(components).encode()).hexdigest()[:16]}")

            decision = await approval_requests.decision_for(action_id)

            if decision is None:
                pending_request = await approval_requests.request(
                    action_id=action_id,
                    action_type="self_improvement_deployment",
                    tier=scope.value.upper(),
                    scope=scope.value,
                    requester="enhanced_asi",
                    summary=(f"Deploy {len(improvements)} {scope.value} "
                             f"self-modification(s) to "
                             f"{', '.join(components[:3]) or 'the substrate'}"),
                    rationale=(f"Scope {scope.value} requires human approval "
                               f"before self-modification is deployed."),
                    details={
                        "scope": scope.value,
                        "improvements": list(improvements),
                        "components": components,
                        "upgrade_test_suite": context.get("upgrade_test_suite"),
                    })
                logger.error(
                    "🛑 HARD GATE FAILED: %s changes require human approval — "
                    "request #%d is waiting in the dashboard notification centre",
                    scope.value, pending_request.approval_id)
                context["approval_pending"] = pending_request.approval_id
                return False

            if decision is False:
                logger.error("🛑 HARD GATE FAILED: a person DECLINED this %s "
                             "self-modification", scope.value)
                context["approval_declined"] = action_id
                return False

            granted = await approval_requests.find(action_id)
            logger.info("✅ Human approval confirmed for %s changes by %s%s",
                        scope.value, granted.decided_by if granted else "unknown",
                        " (Touch ID)" if granted and granted.authenticated else "")
            context["approved_by"] = granted.decided_by if granted else None

        return True

    async def _deploy_improvements(
        self,
        improvements: List[str],
        scope: ImprovementScope,
        context: Dict[str, Any]
    ) -> List[str]:
        """Phase 6: Deploy improvements"""
        deployed = []

        try:
            if not self.deployer:
                # The sandbox two phases earlier is a HARD GATE that raises
                # when unavailable. This returned [] for the same condition, so
                # a missing deployer read as "deployed nothing" and the cycle
                # completed successfully having shipped no code.
                raise RuntimeError(
                    "SafeUpgradeDeployer is REQUIRED to deploy improvements; "
                    "refusing to report an empty deployment as a completed one."
                )

            # Select deployment strategy
            strategy = {
                ImprovementScope.MINOR: DeploymentStrategy.IMMEDIATE,
                ImprovementScope.MODERATE: DeploymentStrategy.CANARY,
                ImprovementScope.MAJOR: DeploymentStrategy.BLUE_GREEN,
                ImprovementScope.TRANSFORMATIVE: DeploymentStrategy.BLUE_GREEN
            }.get(scope, DeploymentStrategy.CANARY)

            for improvement_id in improvements:
                # Get code
                code = await self._get_generated_code(improvement_id)

                if not code:
                    # Tested a moment ago, missing now. Skipping it quietly
                    # produced a cycle that reported fewer deployments than
                    # improvements with nothing recording why.
                    raise RuntimeError(
                        f"No stored code for improvement {improvement_id} at "
                        f"deployment; it passed testing and cannot now be found."
                    )

                if code:
                    # Deploy
                    # deploy_upgrade's signature is (file_paths, metadata).
                    # This passed code= and strategy=, which are not parameters
                    # -- a TypeError the moment the deployer was ever wired up.
                    # The strategy and code travel in metadata instead.
                    result = await self.deployer.deploy_upgrade(
                        file_paths=code.get("file_paths", []),
                        metadata={
                            **context,
                            "improvement_id": improvement_id,
                            "scope": scope.value,
                            "strategy": getattr(strategy, "value", str(strategy)),
                            "code": code["code"],
                        },
                    )

                    if result.success:
                        deployed.append(improvement_id)
                        logger.info(f"Deployment successful: {improvement_id}")

                        # Record in audit trail
                        if self.audit_trail:
                            await self.audit_trail.record_deployment(
                                deployment_id=result.deployment_id,
                                component=code.get("component", "unknown"),
                                success=True,
                                details={
                                    "improvement_id": improvement_id,
                                    "strategy": strategy.value,
                                    "scope": scope.value
                                }
                            )
                    else:
                        # RECORDED, not merely logged. Only successes reached
                        # the audit trail, so the deployment record was a list
                        # of things that worked and the trail over-reported the
                        # success rate of every cycle it described.
                        logger.warning(f"Deployment failed: {improvement_id}")
                        if self.audit_trail:
                            await self.audit_trail.record_deployment(
                                deployment_id=getattr(result, "deployment_id", "")
                                or f"failed_{improvement_id}",
                                component=code.get("component", "unknown"),
                                success=False,
                                details={
                                    "improvement_id": improvement_id,
                                    "strategy": strategy.value,
                                    "scope": scope.value,
                                    "error": getattr(result, "error", None),
                                },
                            )

            logger.info(f"Deployment complete: {len(deployed)} improvements deployed")

            # Send Slack notification for successful deployments
            if deployed:
                try:
                    from core.integration.slack_notifier import send_slack_notification
                    asyncio.create_task(send_slack_notification({
                        "title": "🚀 System Improvements Deployed",
                        "message": f"**Improvements:** {len(deployed)} successfully deployed\n**Type:** Self-improvement\n**Status:** Active and monitoring impact",
                        "severity": "info"
                    }))
                except Exception as e:
                    # A notification is a side effect; failing to send one must
                    # not affect a deployment that already happened. Narrowed
                    # from a bare except so it cannot swallow KeyboardInterrupt,
                    # and the reason is recorded rather than discarded.
                    logger.debug("Deployment notification not sent: %s", e)

            return deployed

        except Exception as e:
            # DEPLOYING NOTHING AND FAILING TO DEPLOY ARE DIFFERENT FACTS.
            # `return []` reported the second as the first, and the caller then
            # skipped impact evaluation and the capability regression gate --
            # both of which are conditioned on `cycle.improvements_deployed` --
            # so a deployment that blew up produced a clean, complete-looking
            # cycle record.
            logger.error(f"Deployment failed: {e}", exc_info=True)
            raise RuntimeError(f"Deployment phase failed: {e}") from e

    async def _evaluate_impact(
        self,
        deployed: List[str],
        targets: List[ImprovementTarget],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Phase 7: Evaluate improvement impact using Unified LLM for analysis"""
        impact = {
            "total_deployed": len(deployed),
            "improvements": [],
            "unmeasured": [],
            "success_rate": 0.0,
            "avg_improvement": 0.0,
            "measured": False,
        }

        try:
            # Wait for metrics to stabilize
            await asyncio.sleep(5)

            # Measure impact on each target
            improvements_measured = []
            unmeasured = []

            for target in targets:
                # Get updated metrics
                updated_health = await self._get_component_health(target.component)

                if not updated_health:
                    # SURVIVORSHIP. `if updated_health:` with no else dropped a
                    # target that could not be re-measured, and the success rate
                    # below was then computed over the survivors: three of five
                    # unmeasurable and two meeting target reported 100%. The
                    # rate is the number the cycle is judged on, so the targets
                    # that went quiet were exactly the ones excluded from
                    # judging it.
                    unmeasured.append({"component": target.component,
                                       "metric": target.metric,
                                       "reason": "no health reading after deployment"})
                    continue

                after = updated_health["health_score"]
                before = target.current_value
                if before:
                    improvement_pct = (after - before) / before * 100
                else:
                    # A BASELINE OF ZERO IS THE URGENT CASE, NOT AN EDGE CASE.
                    # Dividing by it raised ZeroDivisionError into the handler
                    # below, which returned zeros for the whole evaluation --
                    # so the worst-scoring component, the one most likely to be
                    # selected, could poison the measurement of every other
                    # target in the cycle. There is no percentage change from
                    # zero; the absolute change is the honest report.
                    improvement_pct = None

                improvements_measured.append({
                    "component": target.component,
                    "metric": target.metric,
                    "before": before,
                    "after": after,
                    "improvement_pct": improvement_pct,
                    "absolute_change": after - before,
                    "target_met": after >= target.target_value
                })

            impact["improvements"] = improvements_measured
            impact["unmeasured"] = unmeasured

            # Calculate success rate over EVERY target acted on. An unmeasured
            # target is not a success, and excluding it is what inflated the
            # rate; it counts in the denominator and never in the numerator.
            attempted = len(improvements_measured) + len(unmeasured)
            if attempted:
                impact["measured"] = bool(improvements_measured)
                successful = sum(1 for i in improvements_measured if i["target_met"])
                impact["success_rate"] = successful / attempted

                with_pct = [i["improvement_pct"] for i in improvements_measured
                            if i["improvement_pct"] is not None]
                impact["avg_improvement"] = (sum(with_pct) / len(with_pct)
                                             if with_pct else 0.0)

            if improvements_measured:
                # The analysis is routed through the neural bridge, which is
                # substrate-first. Gating it on `self.llm` skipped it whenever
                # the model was down, even though the router only reaches a
                # model if it cannot answer without one.
                impact["detailed_analysis"] = await self._reason_about_impact(
                    improvements_measured, context)

            # LONG-HORIZON TRACKING, AGAINST A PERSISTED BASELINE.
            #
            # `ImprovementMonitor.track_cross_cycle_capability` is the most
            # complete symmetric implementation in the codebase -- it holds a
            # baseline per component/metric across cycles and returns
            # improving / stable / DEGRADING at a +/-5% threshold -- and it had
            # ZERO CALLERS, so `unified.long_term_baselines` was empty and no
            # component's capability was ever compared with where it started.
            #
            # Without this the cycle could only ever see the delta it produced
            # itself, which is why self-improvement tracked improvement and
            # never regression: nothing held the earlier value to fall from.
            for measured in improvements_measured:
                try:
                    tracked = await self.monitor.track_cross_cycle_capability(
                        component_name=measured["component"],
                        metric_name=measured["metric"],
                        current_value=float(measured["after"]),
                        cycle_number=len(self.cycles) + 1)
                except Exception as error:
                    logger.error("Cross-cycle tracking failed for %s: %s",
                                 measured["component"], error)
                    continue

                measured["long_horizon"] = tracked
                if tracked.get("trend_status") == "degrading":
                    # A component below its own long-term baseline is a
                    # regression whether or not this cycle caused it.
                    logger.error(
                        "📉 CAPABILITY REGRESSION: %s.%s is %.1f%% below its "
                        "baseline of %.2f after %s cycle(s)",
                        measured["component"], measured["metric"],
                        abs(float(tracked.get("pct_change_from_baseline") or 0.0)),
                        float(tracked.get("baseline_value") or 0.0),
                        tracked.get("cycles_tracked"))
                    impact.setdefault("regressions", []).append({
                        "component": measured["component"],
                        "metric": measured["metric"],
                        "baseline": tracked.get("baseline_value"),
                        "current": tracked.get("current_value"),
                        "pct_change": tracked.get("pct_change_from_baseline"),
                        "cycles_tracked": tracked.get("cycles_tracked"),
                    })

            if unmeasured:
                logger.warning(
                    "Impact evaluation could not re-measure %d of %d target(s): %s",
                    len(unmeasured), attempted,
                    ", ".join(u["component"] for u in unmeasured))

            logger.info(
                f"Impact evaluation complete: "
                f"success_rate={impact['success_rate']:.1%} "
                f"({len(improvements_measured)}/{attempted} measured), "
                f"avg_improvement={impact['avg_improvement']:.1f}%"
            )

            return impact

        except Exception as e:
            # A CRASHED EVALUATION IS NOT A ZERO RESULT. This returned the
            # initialised dict, so "the improvements helped nothing" and "the
            # measurement broke" were the same recorded value -- and that value
            # is persisted as the cycle's impact and read back by the
            # statistics and reflection paths. `measured` stays False and the
            # reason is carried, so a later reader can tell the two apart.
            logger.error(f"Impact evaluation failed: {e}", exc_info=True)
            impact["measured"] = False
            impact["evaluation_error"] = f"{type(e).__name__}: {e}"
            return impact

    async def _reason_about_impact(
        self,
        improvements: List[Dict[str, Any]],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Use Unified LLM for detailed impact analysis"""
        try:
            improvements_desc = "\n".join([
                f"- {i['component']}: {i['before']:.1f}% → {i['after']:.1f}% "
                f"({i['improvement_pct']:+.1f}%)"
                for i in improvements
            ])

            query = f"""Analyze improvement impact:

Improvements:
{improvements_desc}

Provide analysis in JSON:
{{
    "overall_assessment": "...",
    "strengths": ["...", "..."],
    "concerns": ["...", "..."],
    "recommendations": ["...", "..."]
}}"""

            # Route through neural bridge for automatic memory capture
            from core.reasoning.neural_bridge import ReasoningRequest, ReasoningMode

            request = ReasoningRequest(
                query=query,
                context=[f"Analyzing improvement impact", f"Total improvements: {len(improvements)}"],
            )

            result = await asyncio.wait_for(self.neural_bridge.reason(request), timeout=300.0)
            return self._extract_json(self._answer_of(result))

        except Exception as e:
            # `{}` is what a successful analysis with nothing to say would also
            # return. Naming the failure keeps "no analysis" separable from
            # "analysis unavailable" in the persisted cycle record.
            logger.error(f"Impact analysis produced no verdict: {e}")
            return {"analysis_error": f"{type(e).__name__}: {e}"}

    async def _check_capability_regression(
        self,
        cycle_id: str,
        context: Dict[str, Any]
    ) -> Optional[Any]:
        """
        Phase 7.5: Check for capability regression using frozen benchmarks

        This prevents "capability narrowing" - where system optimizes specific
        metrics (latency, memory) but loses general reasoning competence.

        Returns:
            CapabilityReport or None if benchmarks unavailable
        """
        try:
            # No `if get_capability_benchmark_suite is None: return None` here.
            # It was unreachable once the import became hard, and it was the
            # same fail-open hole as the handler below: a returned None means
            # the caller's `if capability_report:` skips the SEVERE-regression
            # gate, so "the suite is missing" and "no regression found" read
            # identically.
            benchmark_suite = get_capability_benchmark_suite()

            # No model is injected: a language model belongs to the teacher, not
            # to a benchmark harness. The suite runs its model-free benchmarks;
            # any benchmark that genuinely needs a model reports that honestly.

            # Load benchmarks if not already loaded
            if not benchmark_suite.benchmarks_loaded:
                await benchmark_suite.load_benchmarks()

            # Run benchmarks for this cycle
            # Sample 20 tests per domain (5 from each domain) for efficiency
            capability_report = await benchmark_suite.run_benchmarks(
                cycle_id=cycle_id,
                domains=None,  # Test all domains
                sample_size=20  # Limit to 20 tests total for speed
            )

            # Log results
            if capability_report.regression_detected:
                logger.warning(
                    f"⚠️  Capability regression: {capability_report.regression_severity} in "
                    f"{', '.join(capability_report.regression_domains)}"
                )
                logger.warning(
                    f"   Overall score: {capability_report.overall_score:.2%} "
                    f"(baseline delta: {capability_report.baseline_delta:+.2%})"
                )
            else:
                logger.info(
                    f"✅ No capability regression detected. Overall score: {capability_report.overall_score:.2%}"
                )

            # Record in audit trail
            if self.audit_trail:
                await self.audit_trail.record_event(
                    event_type=SafetyEventType.DECISION,
                    severity="LOW",
                    description=(
                        f"Capability benchmark: overall {capability_report.overall_score:.2%}, "
                        f"baseline delta {capability_report.baseline_delta:+.2%}"
                    ),
                    action="run_capability_benchmarks",
                    outcome=("regression_detected" if capability_report.regression_detected
                             else "no_regression"),
                    component="capability_benchmarks",
                    details={
                        "cycle_id": cycle_id,
                        "overall_score": capability_report.overall_score,
                        "reasoning_score": capability_report.reasoning_score,
                        "coding_score": capability_report.coding_score,
                        "analysis_score": capability_report.analysis_score,
                        "comprehension_score": capability_report.comprehension_score,
                        "regression_detected": capability_report.regression_detected,
                        "regression_severity": capability_report.regression_severity,
                        "tests_passed": capability_report.tests_passed,
                        "tests_failed": capability_report.tests_failed
                    }
                )

            return capability_report

        except Exception as e:
            # A SAFETY GATE THAT ERRORS IS NOT A PASS.
            #
            # This returned None, and the caller reads `if capability_report:`
            # -- so a crashed regression check skipped the SEVERE-regression
            # hard gate entirely and the cycle continued with code already
            # deployed. "The benchmarks did not run" and "the benchmarks found
            # no regression" became the same answer, and only one of them means
            # the system still works.
            logger.error(f"Capability regression check failed: {e}", exc_info=True)
            if self.audit_trail:
                await self.audit_trail.record_event(
                    event_type=SafetyEventType.INCIDENT,
                    severity="CRITICAL",
                    description=f"Capability regression check could not run: {e}",
                    action="check_capability_regression",
                    outcome="gate_unavailable",
                    component="enhanced_asi",
                    details={"cycle_id": cycle_id, "error": str(e)},
                )
            raise RuntimeError(
                f"Capability regression check could not run ({e}). Refusing to "
                f"treat an unrun benchmark as a passed one — cycle {cycle_id} "
                f"has deployed code and cannot be certified."
            ) from e

    async def _reflect_on_cycle(
        self,
        cycle: ImprovementCycle
    ):
        """Phase 8: Reflect on cycle and learn using Unified LLM

        Each step below is independently guarded. A single ``try`` around all
        of them meant the first failure skipped every later step -- and the
        first step failed on every cycle, so improvement history and the
        governance record were never reached either.
        """
        # Reflection (optional -- the rest does not depend on it).
        # `_reason_about_cycle` routes through the neural bridge, which is
        # substrate-first; gating it on `self.llm` skipped reflection whenever
        # the model was down, even though the router only reaches a model when
        # it cannot answer without one.
        try:
            cycle.metadata["reflection"] = await self._reason_about_cycle(cycle)
        except Exception as e:
            logger.error(f"Reflection failed for {cycle.cycle_id}: {e}", exc_info=True)

        # THE REWARD SIGNAL. This is how self-improvement outcomes reach the
        # bandit. It called meta_learner.record_learning_outcome(...), which
        # MetaLearner has never had -- the real method is track_learning_outcome
        # with a different shape (strategy_type label, scalar performance_score,
        # time_ms). Every cycle raised AttributeError into a swallowing handler,
        # so the learner never saw a single self-improvement outcome.
        if not self.meta_learner:
            # The reward signal is the whole point of this phase. Its absence
            # left no trace at all, so a run where the bandit learned nothing
            # looked exactly like one where it learned.
            cycle.metadata["reward_signal_recorded"] = False
            cycle.metadata["reward_signal_error"] = "meta_learner unavailable"
            logger.error("Meta-learner unavailable: cycle %s produced NO reward "
                         "signal; the bandit will not learn from it",
                         cycle.cycle_id)
        if self.meta_learner:
            try:
                from core.learning.meta_learning import TaskFamily
                outcome_class = self._classify_cycle_outcome(cycle)
                await self.meta_learner.track_learning_outcome(
                    task_type=TaskFamily.REASONING,
                    strategy_type=self._infer_strategy(cycle),
                    success=cycle.success_rate > 0.7,
                    performance_score=cycle.success_rate,
                    time_ms=cycle.duration_sec * 1000.0,
                    outcome_class=outcome_class,
                    context={
                        "scope": cycle.scope.value,
                        "targets_count": len(cycle.targets),
                        "deployed_count": len(cycle.improvements_deployed),
                        "cycle_id": cycle.cycle_id,
                        "abort_reason": (cycle.metadata or {}).get("abort_reason"),
                        "source": "self_improvement",
                    },
                )
                cycle.metadata["reward_signal_recorded"] = True
            except Exception as e:
                # Recorded on the cycle, not only in the log. This is the one
                # path by which self-improvement outcomes reach the bandit, and
                # it has silently failed before -- the call named a method
                # MetaLearner never had, and every cycle swallowed the
                # AttributeError here for as long as that lasted.
                cycle.metadata["reward_signal_recorded"] = False
                cycle.metadata["reward_signal_error"] = f"{type(e).__name__}: {e}"
                logger.error(f"Meta-learning record failed for {cycle.cycle_id}: {e}", exc_info=True)

        # Update improvement history
        for target in cycle.targets:
            self.improvement_history[target.component].append(cycle.success_rate)

        # Record governance patterns. The attribute was `governance_learner`,
        # which is not defined on this class -- the property is `governance`.
        # TWO DEFECTS, ONE BLOCK.
        #
        # It called `governance.learn_from_decision(...)`, which exists nowhere
        # in the codebase -- the only two references were this call and the
        # AttributeError handler catching it, logged at DEBUG. So every cycle
        # "recorded a governance pattern" by raising and silently swallowing,
        # and the debug level meant nobody saw it happen.
        #
        # And it fired only when `success_rate > 0.8`, so the record would have
        # been of successes alone. A pattern store shown nothing but approvals
        # that worked cannot learn which ones to stop.
        #
        # `GovernancePatternLearner.record_decision` is the real API, but that
        # module states it is in-memory, non-persistent and for the governance
        # test-suite -- wiring the production cycle into a volatile store would
        # replace a silent no-op with a silent forget. So the outcome is
        # recorded where it durably lives, on the cycle, for every result
        # rather than the good ones; a real pattern sink is a decision that has
        # not been made yet.
        cycle.metadata["governance_outcome"] = {
            "action": f"improve_{cycle.scope.value}",
            "success_rate": cycle.success_rate,
            "deployed": len(cycle.improvements_deployed or []),
            "outcome": "success" if cycle.success_rate > 0.8 else "unsuccessful",
            "pattern_sink": None,
        }

        logger.info(f"Reflection complete for cycle {cycle.cycle_id}")

    async def _reason_about_cycle(
        self,
        cycle: ImprovementCycle
    ) -> Dict[str, Any]:
        """Use Unified LLM for cycle reflection"""
        try:
            query = f"""Reflect on improvement cycle:

Cycle ID: {cycle.cycle_id}
Scope: {cycle.scope.value}
Targets: {len(cycle.targets)}
Generated: {len(cycle.improvements_generated)}
Deployed: {len(cycle.improvements_deployed)}
Success Rate: {cycle.success_rate:.1%}
Duration: {cycle.duration_sec:.1f}s

Provide reflection in JSON:
{{
    "lessons_learned": ["...", "..."],
    "what_worked": ["...", "..."],
    "what_failed": ["...", "..."],
    "next_steps": ["...", "..."]
}}"""

            # Route through neural bridge for automatic memory capture
            from core.reasoning.neural_bridge import ReasoningRequest, ReasoningMode

            request = ReasoningRequest(
                query=query,
                context=[
                    f"Reflecting on improvement cycle {cycle.cycle_id}",
                    f"Scope: {cycle.scope.value}",
                    f"Success rate: {cycle.success_rate:.1%}"
                ],
            )

            result = await asyncio.wait_for(self.neural_bridge.reason(request), timeout=300.0)
            return self._extract_json(self._answer_of(result))

        except Exception as e:
            logger.error(f"LLM reflection failed: {e}")
            return {}

    def _measured_cycles_per_day(self) -> Optional[float]:
        """How often cycles have actually run, or None if it cannot be measured.

        Read from the recorded cycle times rather than assumed, because the
        only honest way to turn a per-cycle rate into a per-day horizon is to
        know the cadence -- and one cycle, or several with no elapsed time
        between them, does not establish one.
        """
        stamps = sorted(c.start_time for c in self.cycles if c.start_time)
        if len(stamps) < 2:
            return None
        span_days = (stamps[-1] - stamps[0]).total_seconds() / 86400.0
        if span_days <= 0:
            return None
        return (len(stamps) - 1) / span_days

    async def forecast_capabilities(
        self,
        horizon_days: int = 90
    ) -> Dict[str, Any]:
        """
        Forecast capability development over time horizon using Unified LLM

        Uses:
        - Historical improvement rates
        - Meta-learning effectiveness
        - Frontier predictions
        - Unified LLM for trend analysis
        """
        # THE UNITS DID NOT LINE UP AND THE TREND WAS NOT A TREND.
        #
        # `improvement_history` holds cycle SUCCESS RATES, which are 0-1. The
        # old code took `sum(history[-3:]) / 3` -- an AVERAGE -- called it a
        # trend, multiplied it by `horizon_days / 30` as though it were a
        # monthly rate of change, added the result to a 0-1 level and clamped
        # the sum at 100. A component sitting steadily at 0.9 therefore
        # "projected" to 3.6. Every number this returned was unfounded.
        #
        # A rate of change is (last - first) / intervals, in the same units as
        # the series. Converting it to a horizon in DAYS needs a cadence -- how
        # often cycles actually run -- which is measurable from the recorded
        # cycle times and is stated rather than assumed. Without it the
        # projection is refused instead of guessed.
        forecast = {
            "horizon_days": horizon_days,
            "capabilities": [],
            "estimated_breakthroughs": [],
            "confidence": None,
            "cycles_per_day": None,
            "avg_improvement_rate_per_cycle": None,
        }

        try:
            forecast["avg_improvement_rate_per_cycle"] = self._calculate_avg_improvement_rate()
            cadence = self._measured_cycles_per_day()
            forecast["cycles_per_day"] = cadence
            projected_cycles = (cadence * horizon_days) if cadence else None
            if cadence is None:
                forecast["projection_unavailable"] = (
                    "fewer than two recorded cycles, or no elapsed time between "
                    "them, so cycle cadence cannot be measured and a horizon in "
                    "days cannot be converted into expected cycles")

            for component, history in self.improvement_history.items():
                if len(history) < 3:          # a rate needs more than one interval
                    continue
                current = float(history[-1])
                rate_per_cycle = (float(history[-1]) - float(history[0])) / (len(history) - 1)
                projected_level = (
                    max(0.0, min(1.0, current + rate_per_cycle * projected_cycles))
                    if projected_cycles is not None else None)

                forecast["capabilities"].append({
                    "component": component,
                    "observations": len(history),
                    "current_level": current,
                    "improvement_rate_per_cycle": rate_per_cycle,
                    "projected_level": projected_level,
                    "units": "cycle success rate, 0-1",
                })

            # Substrate-first: `_reason_about_forecast` routes through the
            # neural bridge, so gating it on `self.llm` skipped analysis that
            # may not have needed a model at all.
            if forecast["capabilities"]:
                enhanced = await self._reason_about_forecast(forecast, horizon_days)
                forecast["enhanced_analysis"] = enhanced

            forecast["complete"] = True
            logger.info(
                f"Capability forecast: {len(forecast['capabilities'])} components, "
                f"{len(forecast['estimated_breakthroughs'])} breakthroughs"
            )

            return forecast

        except Exception as e:
            # A HALF-BUILT FORECAST IS NOT A FORECAST. This returned whatever
            # had been filled in so far, so a caller could not tell a complete
            # projection from one that died partway -- which is exactly what
            # happened on every call for as long as the phantom predictor
            # method was there.
            logger.error(f"Capability forecast failed: {e}", exc_info=True)
            forecast["complete"] = False
            forecast["error"] = f"{type(e).__name__}: {e}"
            return forecast

    async def _reason_about_forecast(
        self,
        forecast: Dict[str, Any],
        horizon_days: int
    ) -> Dict[str, Any]:
        """Use Unified LLM to enhance capability forecast"""
        try:
            # Matches the shape `forecast_capabilities` now produces: levels are
            # cycle success rates in 0-1 (not percentages), the rate is per
            # CYCLE, and `projected_level` is None when cadence could not be
            # measured. The old format read `improvement_rate` -- a key that no
            # longer exists -- and applied `:.1f` to a value that can be None,
            # so this raised KeyError/TypeError rather than describing anything.
            def _describe(c):
                projected = c.get("projected_level")
                projected_text = ("not projected (cadence unmeasured)"
                                  if projected is None else f"{projected:.3f}")
                return (f"- {c['component']}: {c['current_level']:.3f} → {projected_text} "
                        f"(rate {c['improvement_rate_per_cycle']:+.4f}/cycle, "
                        f"n={c['observations']}, units: cycle success rate 0-1)")

            capabilities_desc = "\n".join(
                _describe(c) for c in forecast["capabilities"][:10])

            query = f"""Enhance capability forecast:

Time horizon: {horizon_days} days
Current projections:
{capabilities_desc}

Provide enhanced analysis in JSON:
{{
    "key_trends": ["...", "..."],
    "accelerating_areas": ["...", "..."],
    "bottlenecks": ["...", "..."],
    "strategic_recommendations": ["...", "..."]
}}"""

            # Route through neural bridge for automatic memory capture
            from core.reasoning.neural_bridge import ReasoningRequest, ReasoningMode

            request = ReasoningRequest(
                query=query,
                context=[
                    f"Enhancing capability forecast",
                    f"Time horizon: {horizon_days} days",
                    f"Capabilities analyzed: {len(forecast['capabilities'])}"
                ],
            )

            result = await asyncio.wait_for(self.neural_bridge.reason(request), timeout=300.0)
            return self._extract_json(self._answer_of(result))

        except Exception as e:
            logger.error(f"LLM forecast enhancement failed: {e}")
            return {}

    # Helper methods

    @staticmethod
    def _cycle_success_rate(cycle: ImprovementCycle) -> float:
        """What fraction of the work this cycle set out to do actually landed.

        Stated once, because it was previously computed in two places from two
        different things: the remediation exit used recoveries, the impact path
        used deployed code, and the generation exit used neither -- so a cycle
        that recovered two subsystems and generated nothing reported 0.0.

        A recovery and a deployed improvement are both improvements; the
        denominator is what the cycle selected to act on.
        """
        attempted = len(cycle.targets or [])
        if not attempted:
            return 0.0
        return min(1.0, len(cycle.improvements_deployed or []) / attempted)

    async def _persist_cycle(self, cycle: ImprovementCycle) -> bool:
        """Record a completed cycle.

        self.cycles and self.improvement_history are in-process lists built from
        empty in __init__ and never loaded from anywhere. Every statistic this
        class reports -- total cycles, success rate, average improvement rate,
        the per-component history forecast_capabilities() reads -- therefore
        reset to zero on restart, and a cycle that genuinely recovered five
        subsystems left no trace that it had happened.
        """
        from core.database import get_database_manager

        components = sorted({t.component for t in (cycle.targets or [])})
        await get_database_manager().execute_query(
            """
            INSERT INTO unified.improvement_cycles
                (cycle_id, scope, phase, success_rate, targets_count,
                 generated_count, deployed_count, deployed, components,
                 duration_sec, started_at, ended_at, metadata)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9::jsonb,$10,$11,$12,$13::jsonb)
            ON CONFLICT (cycle_id) DO UPDATE SET
                phase           = EXCLUDED.phase,
                success_rate    = EXCLUDED.success_rate,
                deployed_count  = EXCLUDED.deployed_count,
                deployed        = EXCLUDED.deployed,
                duration_sec    = EXCLUDED.duration_sec,
                ended_at        = EXCLUDED.ended_at,
                metadata        = EXCLUDED.metadata
            """,
            (
                cycle.cycle_id, cycle.scope.value, cycle.phase.value,
                float(cycle.success_rate), len(cycle.targets or []),
                len(cycle.improvements_generated or []),
                len(cycle.improvements_deployed or []),
                json.dumps(list(cycle.improvements_deployed or [])),
                json.dumps(components),
                float(cycle.duration_sec), cycle.start_time, cycle.end_time,
                json.dumps({k: v for k, v in (cycle.metadata or {}).items()
                            if isinstance(v, (str, int, float, bool, list, dict))
                            or v is None}),
            ),
            commit=True,
        )
        return True

    async def initialize(self) -> int:
        """Bring the singleton up with the history it actually has.

        `load_history` was written to fix a stated defect -- the class starting
        every process claiming zero cycles -- and had ZERO CALLERS, so the
        defect was still live in every run.

        `core/main.py` already does `if hasattr(asi, 'initialize'): await
        asi.initialize()` and then logs "Enhanced ASI Self-Improvement ready".
        There was no `initialize`, so the guard skipped silently and the
        success line was printed for an initialisation that never happened.
        Defining it here makes that call real and that log line true.

        Failure to load is reported, not swallowed: starting with an empty
        history is exactly the condition being fixed, so it must not be
        reachable quietly.
        """
        loaded = await self.load_history()
        logger.info("Enhanced ASI initialised with %d cycle(s) of history", loaded)
        return loaded

    async def load_history(self) -> int:
        """Rebuild in-memory cycle history from the store.

        Without this the class starts every process claiming zero cycles and no
        improvement history, which is indistinguishable from a system that has
        never improved anything.
        """
        from core.database import get_database_manager

        rows = await get_database_manager().execute_query(
            """SELECT cycle_id, scope, phase, success_rate, deployed, components,
                      duration_sec, started_at, ended_at, metadata
               FROM unified.improvement_cycles
               ORDER BY started_at""",
            fetch_all=True) or []

        self.cycles = []
        self.improvement_history = defaultdict(list)
        for row in rows:
            components = row["components"]
            if isinstance(components, str):
                components = json.loads(components)
            deployed = row["deployed"]
            if isinstance(deployed, str):
                deployed = json.loads(deployed)

            cycle = ImprovementCycle(
                cycle_id=row["cycle_id"],
                phase=ImprovementPhase(row["phase"]),
                scope=ImprovementScope(row["scope"]),
                targets=[],
                improvements_generated=[],
                improvements_deployed=list(deployed or []),
                success_rate=float(row["success_rate"]),
                start_time=row["started_at"],
                end_time=row["ended_at"],
                duration_sec=float(row["duration_sec"]),
            )
            self.cycles.append(cycle)
            for component in (components or []):
                self.improvement_history[component].append(cycle.success_rate)

        logger.info(
            "Loaded %d improvement cycle(s) covering %d component(s) from store",
            len(self.cycles), len(self.improvement_history))
        return len(self.cycles)

    async def _get_all_components(self) -> List[str]:
        """Improvement candidates, resolved through the component registry.

        This was five hardcoded names -- chat_agent, memory_system,
        reasoning_engine, learning_system, safety_framework. Those subsystems
        are real, but nothing measured them under those names, so paired with
        the fabricated 85.0 in _get_component_health the assessment produced the
        same five targets on every cycle regardless of the state of the system.
        They are superseded here rather than removed: the registry declares
        `memory`, `learning`, `reasoning`, `safety` and `agents` among 29
        subsystems and 47 sub-components, all of them measured.

        unified.components is the authority, NOT unified.component_health.
        Reading the health table directly would treat anything that ever wrote a
        row there as a component -- it still holds six rows whose names are
        metric keys (`overall_status`, `active_alerts`), and because those carry
        the old 0-1 scale they would sort as the most degraded things in the
        system and be selected first. A component is something declared, not
        anything that once appeared in a measurement.
        """
        from core.database import get_database_manager

        db = get_database_manager()
        rows = await db.execute_query(
            """SELECT c.component_id
               FROM unified.components c
               JOIN unified.component_health h ON h.component_name = c.component_id
               WHERE c.monitoring_enabled IS TRUE
               ORDER BY h.health_score ASC, c.component_name""",
            fetch_all=True,
        ) or []

        # component_id, not component_name: the id is what the health store is
        # keyed on. Returning the bare name turned `security.audit_worker` into
        # `audit_worker`, which then resolved to no measurement at all.
        components = [r["component_id"] for r in rows]
        if not components:
            raise RuntimeError(
                "No declared component has a health measurement. Improvement "
                "targets cannot be selected: the registry and the health store "
                "have no component in common, which means measurements are not "
                "reaching the store rather than that the system is healthy")
        logger.info("Improvement candidates: %d measured component(s)", len(components))
        return components

    async def _rank_by_recorded_health(self, components: List[str]) -> List[str]:
        """Components ordered worst-recorded-health first.

        Ranking only. The recorded score may be stale or from a dead process --
        `_get_component_health` decides that -- but it is the right thing to
        PRIORITISE by, and it costs one query instead of 76 measurements.
        A component with no recorded score sorts last rather than first: an
        absent measurement is not evidence of a problem.
        """
        try:
            state = await self.monitor.get_system_state()
        except Exception as e:
            raise_if_structural(e, "EnhancedASISelfImprovement._rank_by_recorded_health")
            logger.debug("Cannot rank by health (%s); keeping registry order", e)
            return list(components)

        # DICT OR OBJECT. `get_system_state()` returns either depending on the
        # monitor, which is why `_get_component_health` and `_is_deployment_safe`
        # both branch on `isinstance(state, dict)`. This read the attribute
        # only, so against a dict state `getattr` returned None, `recorded`
        # became {}, every component scored inf, and "worst health first"
        # silently degraded to ALPHABETICAL -- the identical shape of the defect
        # `_get_component_health`'s docstring records having fixed.
        if isinstance(state, dict):
            recorded = state.get("component_health") or {}
        else:
            recorded = getattr(state, "component_health", None) or {}

        if not recorded:
            logger.warning(
                "No component_health in system state; improvement candidates "
                "cannot be ranked by health and are left in registry order")

        def score_of(name: str) -> float:
            entry = recorded.get(name)
            if entry is None:
                return float("inf")
            value = (entry.get("health_score") if isinstance(entry, dict)
                     else getattr(entry, "health_score", None))
            return float(value) if value is not None else float("inf")

        return sorted(components, key=lambda c: (score_of(c), c))

    async def _get_component_health(
        self,
        component: str
    ) -> Optional[Dict[str, Any]]:
        """Real measured health for a component, or None if it has none.

        THREE defects here made every improvement target rest on invented data:

        1. It read `state.components`. SystemImprovementState has no such field
           -- the per-component map is called `component_health`. The getattr
           default meant the lookup returned {} on every call no matter how
           healthy the system was.
        2. A missing component produced a fabricated `health_score: 85.0`.
           Assessment treats anything under 90 as needing improvement, so an
           unknown component was indistinguishable from a measured-degraded one
           and the system would generate work from a number nobody measured.
        3. The bare `except:` returned the same 85.0, so a broken monitor
           produced the identical answer to a healthy system.

        A component with no measurement now returns None, and the caller skips
        it. "Not measured" and "measured at 85" are different facts.
        """
        if not self.monitor:
            return None

        # A BROKEN INSTRUMENT IS NOT A READING. Only "this component has no
        # measurement" returns None; anything that means the monitor could not
        # answer propagates, because degrading it to None would put a broken
        # monitor and an unmeasured component on the same footing again.
        try:
            state = await self.monitor.get_system_state()
        except Exception as e:
            raise_if_structural(e, "EnhancedASISelfImprovement._get_component_health")
            raise

        if state is None:
            raise RuntimeError(
                "ImprovementMonitor.get_system_state() returned None -- it failed "
                "and reported the failure as an absence of state. Component "
                "health cannot be assumed; the monitor must be repaired")

        if isinstance(state, dict):
            components = state.get("component_health") or {}
        else:
            components = getattr(state, "component_health", None) or {}

        health = components.get(component) if isinstance(components, dict) else None
        if health is None:
            # NO ROW AND A STALE ROW ARE THE SAME PROBLEM: there is no current
            # measurement. Returning None here skipped the component before the
            # liveness branch below could re-measure it -- and in a fresh
            # process the monitor's aggregate is EMPTY (every persisted row
            # belongs to a dead pid and is filtered out), so this branch caught
            # all 76 components and assessment found zero targets while
            # `_remeasure` returned real readings for the same names.
            logger.debug("No stored health for %r; measuring it now", component)
            fresh = await self._remeasure(component)
            if fresh is None:
                return None
            return {
                "health_score": float(fresh["health_score"]),
                "status": fresh.get("status"),
                "last_check": datetime.now().isoformat(),
                "issues": list(fresh.get("issues") or []),
                "remeasured": True,
            }

        # A READING FROM A DEAD PROCESS IS NOT A CURRENT MEASUREMENT.
        #
        # Most health metrics are in-process singleton state (watchdog.
        # is_running, model_loaded, scheduler_active), so a row is only true of
        # the process that wrote it. One process restarted its own watchdog and
        # persisted "health_system: healthy"; every other process saw it
        # stopped, and this method handed that row back as current system state
        # so the component was excluded from improvement. Provenance is checked
        # here rather than trusted.
        if not self._reading_is_live(component, health):
            # NOT LIVE IS A REASON TO MEASURE, NOT A REASON TO GIVE UP.
            #
            # The liveness rule is right: most health metrics are in-process
            # singleton state, so a row is only true of the process that wrote
            # it. But returning None here made assessment skip the component
            # entirely, and every reading in a fresh process is by definition
            # written by a process that has since exited. Measured: 74 fresh
            # components, 13 of them scoring under 90 -- `learning` at 22.0,
            # `agents` at 40.0 -- and assessment identified ZERO targets,
            # because all 74 readings belonged to a dead pid.
            #
            # `_remeasure` already drives the same health check in THIS process
            # and was used for post-remediation verification only. Using it
            # here is what makes the cycle able to see the system it is meant
            # to improve. A component the manifest cannot measure still returns
            # None -- unmeasurable stays unmeasurable.
            fresh = await self._remeasure(component)
            if fresh is None:
                logger.debug("No live reading for %r and it cannot be measured "
                             "in this process", component)
                return None
            return {
                "health_score": float(fresh["health_score"]),
                "status": fresh.get("status"),
                "last_check": datetime.now().isoformat(),
                "issues": list(fresh.get("issues") or []),
                "remeasured": True,
            }

        # ComponentHealth object or plain dict, normalised to what callers read.
        score = health.get("health_score") if isinstance(health, dict) \
            else getattr(health, "health_score", None)
        if score is None:
            return None
        return {
            "health_score": float(score),
            "status": (health.get("status") if isinstance(health, dict)
                       else getattr(health, "status", None)),
            "last_check": datetime.now().isoformat(),
            "issues": (health.get("issues", []) if isinstance(health, dict)
                       else getattr(health, "issues", []) or []),
        }

    #: Components whose modification is CRITICAL risk regardless of scope:
    #: the machinery that constrains, audits or performs self-modification.
    #: Matched on the registry's dotted ids by exact name or namespace prefix.
    #:
    #: This was `["safety_framework", "security_system"]`, compared with `in`
    #: against `component`. Measured against the 76 components that actually
    #: carry health rows, that list matched EXACTLY ZERO of them -- the registry
    #: names them `security.safety_framework`, `security`, `safety`,
    #: `governance`. So `_estimate_risk` never returned "critical" for anything
    #: in its life, every safety component was rated by scope alone, and at
    #: MINOR scope that means "low" -- fully admissible to the constraint
    #: solver, whose risk ceiling exists to keep exactly these out.
    _CRITICAL_COMPONENTS = frozenset({
        "safety", "security", "governance", "firewall", "malware_sandbox",
        "content_security", "threat_intel",
        # The improver itself. A cycle rewriting its own gates is the most
        # consequential change it can make.
        "learning.asi_self_improvement",
    })

    @classmethod
    def _is_safety_critical(cls, component: str) -> bool:
        """Exact id, or anything inside a safety-critical namespace."""
        name = str(component).strip().lower()
        if name in cls._CRITICAL_COMPONENTS:
            return True
        return any(name.startswith(f"{critical}.")
                   for critical in cls._CRITICAL_COMPONENTS)

    def _estimate_risk(
        self,
        scope: ImprovementScope,
        component: str
    ) -> str:
        """Risk of modifying this component at this scope."""
        if self._is_safety_critical(component):
            return "critical"
        elif scope == ImprovementScope.TRANSFORMATIVE:
            return "high"
        elif scope == ImprovementScope.MAJOR:
            return "medium"
        else:
            return "low"

    def _build_requirements(
        self,
        target: ImprovementTarget,
        scope: ImprovementScope
    ) -> str:
        """Build requirements for code generation"""
        return f"""
Improve {target.component} {target.metric}:
- Current value: {target.current_value:.1f}
- Target value: {target.target_value:.1f}
- Improvement needed: {target.improvement_potential:.1f}%
- Difficulty: {target.difficulty}
- Risk level: {target.risk_level}
- Scope: {scope.value}

Requirements:
- Maintain backward compatibility
- Add comprehensive error handling
- Include logging for monitoring
- Follow existing code patterns
- Optimize for {target.metric}
"""

    async def _resolve_component_module(self, component: str) -> Optional[str]:
        """The module a component is implemented in, per the registry.

        `unified.components.dependencies` carries `{"module": "..."}` and is the
        authority on where a component lives. Nothing read it: source lookup
        guessed four paths off the component NAME, so `content_security`
        (actually `core.security.content_security`) and `llm` (actually
        `core.services.unified_llm`) both reported "no source found" for files
        sitting in the tree, and every target was skipped.
        """
        from core.database import get_database_manager

        db = get_database_manager()
        rows = await db.execute_query(
            "SELECT dependencies FROM unified.components WHERE component_id = $1",
            (component,), fetch_all=True) or []
        if not rows:
            return None
        deps = rows[0].get("dependencies")
        if isinstance(deps, str):
            try:
                deps = json.loads(deps)
            except json.JSONDecodeError as error:
                # A CORRUPT REGISTRY ROW IS NOT AN ABSENT ONE. Returning None
                # here sends the caller to guess conventional paths, which is
                # what it does when the registry simply has no entry -- so a
                # malformed `dependencies` blob looked identical to a component
                # nobody had declared, and the guess could land on the wrong file.
                logger.error("Registry row for %r has unreadable dependencies "
                             "(%s); treating as unresolved", component, error)
                return None
        if not isinstance(deps, dict):
            logger.error("Registry dependencies for %r is %s, not an object; "
                         "treating as unresolved", component, type(deps).__name__)
            return None
        module = deps.get("module")
        return str(module) if module else None

    async def _get_existing_code(self, component: str) -> str:
        """The component's real source, or a refusal saying why there is none."""
        import os

        module = await self._resolve_component_module(component)
        if module:
            # A component implemented by a third-party package is not ours to
            # improve. That is a different fact from "the file is missing", and
            # collapsing them would send the generator after psutil.
            if not module.startswith("core."):
                raise FileNotFoundError(
                    f"Component {component!r} is implemented by {module!r}, which "
                    f"is not part of this codebase. Nothing here to improve.")
            path = module.replace(".", "/") + ".py"
            if os.path.exists(path):
                with open(path, "r") as handle:
                    return handle.read()
            raise FileNotFoundError(
                f"Registry says {component!r} is {module!r} but {path} does not "
                f"exist. The registry and the tree disagree.")

        # No registry entry: fall back to the conventional locations, which is
        # a guess and is reported as one.
        search_paths = [
            f"core/{component}.py",
            f"core/agents/{component}.py",
            f"core/learning/{component}.py",
            f"core/services/{component}.py",
        ]
        for path in search_paths:
            if os.path.exists(path):
                with open(path, "r") as handle:
                    return handle.read()

        # NO PLACEHOLDER SOURCE. This returned
        # "# Existing code for {component}\n# (file not found)" -- a two-line
        # comment presented as the component's source, which the generator was
        # then asked to IMPROVE.
        raise FileNotFoundError(
            f"No registry module for {component!r} and no source at any of "
            f"{search_paths}. Refusing to return placeholder text as its code.")

    async def _store_generated_code(
        self,
        improvement_id: str,
        code_data: Dict[str, Any]
    ) -> bool:
        """
        Store generated code to database.
        Raises:
            RuntimeError: If database storage fails
        """
        try:
            from core.database import get_database_manager
            db = get_database_manager()

            if not db:
                raise RuntimeError("Database manager is not available. Cannot store generated code.")

            # Store generated code in database (Postgres)
            await db.execute_query(
                """
                INSERT INTO generated_improvements
                (improvement_id, code, file_paths, component, tool_used, confidence, quality_score, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
                """,
                params=(
                    improvement_id,
                    code_data.get("code", ""),
                    json.dumps(code_data.get("file_paths", [])),
                    code_data.get("target", {}).component if hasattr(code_data.get("target"), 'component') else "unknown",
                    code_data.get("tool_used", ""),
                    code_data.get("confidence", 0.8),
                    code_data.get("confidence", 0.8),  # Use confidence as quality score
                ),
                commit=True,
            )

            logger.info(f"✅ Stored generated code: {improvement_id}")
            return True

        except Exception as e:
            logger.error(f"🛑 Database storage failed: {e}")
            raise RuntimeError(f"Failed to store generated code {improvement_id}: {e}") from e

    async def _get_generated_code(
        self,
        improvement_id: str
    ) -> Dict[str, Any]:
        """Get generated code by ID from database"""
        from core.database import get_database_manager
        db = get_database_manager()

        if not db:
            raise RuntimeError("Database manager unavailable")

        results = await db.query(
            "SELECT code, file_paths, component, quality_score FROM generated_improvements WHERE improvement_id = $1",
            (improvement_id,)
        )

        if not results:
            raise RuntimeError(f"Code not found: {improvement_id}")

        row = results[0]

        # Decode file_paths which are stored as JSON in the database
        file_paths_raw = row.get('file_paths')
        # AN INVENTED PATH IS AN ANSWER TO THE SECURITY GATE'S QUESTION.
        #
        # Both branches below substituted ['/tmp/improvement.py'] when the
        # stored value could not be decoded. `file_paths` is passed straight to
        # `validator.validate_upgrade(file_paths=...)`, whose FIRST check is
        # `_validate_security_critical_paths` -- the gate that blocks a
        # self-modification from touching security-critical files. A temp path
        # is definitionally not security-critical, so a decode failure silently
        # converted "I do not know which files this changes" into "it changes
        # something harmless", and the gate passed on evidence that was made up
        # here rather than read from the row.
        if isinstance(file_paths_raw, str):
            try:
                file_paths = json.loads(file_paths_raw)
            except (TypeError, ValueError) as error:
                raise RuntimeError(
                    f"file_paths for improvement {improvement_id} could not be "
                    f"decoded ({error}); refusing to substitute a path, because "
                    f"the security-critical-path gate would then be answered "
                    f"with a value this function invented.") from error
        elif isinstance(file_paths_raw, (list, tuple)):
            file_paths = list(file_paths_raw)
        else:
            raise RuntimeError(
                f"file_paths for improvement {improvement_id} is "
                f"{type(file_paths_raw).__name__}, which cannot be read as a "
                f"path list; refusing to substitute one.")

        if not isinstance(file_paths, list):
            raise RuntimeError(
                f"file_paths for improvement {improvement_id} decoded to "
                f"{type(file_paths).__name__}, not a list of paths.")

        return {
            "code": row.get('code', ''),
            "file_paths": file_paths,
            "component": row.get('component', 'unknown'),
            "quality_score": row.get('quality_score', 0.0)
        }

    # Signatures of a broken pipeline rather than a bad improvement strategy.
    # These are defects in TorinAI's own machinery: a phase that cannot run
    # says nothing about whether the improvement scope was well chosen.
    _INFRASTRUCTURE_SIGNATURES = (
        "importerror", "cannot import name", "modulenotfounderror",
        "has no attribute", "not defined", "get_upgrade_validator",
        "get_upgrade_sandbox", "get_safe_deployer",
        "upgradesandbox error", "validator error", "deployer",
        "connection refused", "pool is closed", "database",
    )

    def _classify_cycle_outcome(self, cycle: ImprovementCycle) -> "OutcomeClass":
        """Decide whether this cycle is evidence about the improvement strategy.

        The concrete case this exists for: phases 4 and 5 currently abort every
        cycle because ``get_upgrade_validator`` and ``get_upgrade_sandbox`` do
        not exist. Crediting that as a strategy failure would teach the bandit
        that every improvement scope is worthless -- a false causal relation
        learned from a defect in our own code. It is INFRASTRUCTURE_FAILURE and
        earns no credit until the pipeline is repaired.
        """
        from core.learning.meta_learning import OutcomeClass

        meta = cycle.metadata or {}
        blob = " ".join(
            str(meta.get(k, "")) for k in ("abort_reason", "error", "failure_reason")
        ).lower()

        if blob and any(sig in blob for sig in self._INFRASTRUCTURE_SIGNATURES):
            return OutcomeClass.INFRASTRUCTURE_FAILURE

        if cycle.success_rate > 0.7:
            return OutcomeClass.SUCCESS

        # The cycle ran end-to-end but produced nothing deployable: that is a
        # genuine result for this scope, so it counts against it.
        if cycle.improvements_generated:
            return OutcomeClass.STRATEGY_FAILURE

        # Nothing was even generated and no infrastructure signature — we
        # cannot attribute this, so nobody is charged for it.
        return OutcomeClass.INSUFFICIENT_EVIDENCE

    def _infer_strategy(self, cycle: ImprovementCycle) -> str:
        """Infer the meta-learning strategy label for a cycle.

        Returns a MetaLearner strategy_type (a plain string), which is what
        track_learning_outcome consumes. The previous version returned
        LearningStrategy.GRADIENT_DESCENT / EVOLUTIONARY / META_GRADIENT /
        HIERARCHICAL -- none of which exist on any LearningStrategy in this
        codebase (GRADIENT_DESCENT and EVOLUTIONARY are OptimizationMethod
        members; META_GRADIENT exists nowhere), so every branch raised
        AttributeError into a swallowing handler.

        The improvement scope IS the strategy under test: how much the system
        changes in one cycle. Recording it per scope lets the bandit learn
        which scope actually pays off.
        """
        return f"improve_{cycle.scope.value}"

    def _calculate_avg_improvement_rate(self) -> float:
        """Calculate average improvement rate across components"""
        if not self.improvement_history:
            return 0.0

        rates = []
        for component, history in self.improvement_history.items():
            if len(history) >= 2:
                # PER INTERVAL, NOT PER POINT. This divided the total change by
                # len(history), but n readings span n-1 intervals -- so the
                # change between two readings was reported at half its size,
                # and the understatement shrank as history grew. The guard
                # above keeps the denominator at 1 or more.
                rate = (history[-1] - history[0]) / (len(history) - 1)
                rates.append(rate)

        return sum(rates) / len(rates) if rates else 0.0

    # update_model_weights() and _validate_human_approval() REMOVED 2026-08-21.
    #
    # They belong to the architecture where an LLM was the centre of the system
    # and learning meant changing its weights. That is not what this is: the
    # substrate learns by inducing rules, recording evidence and revising
    # posteriors, and there are no model weights for it to update. The local
    # model is a GGUF served by llama-server -- a fixed artefact that proposes
    # and formalises, never a thing whose parameters this system adjusts.
    #
    # So the honest verdict is not "unimplemented", it is "does not apply".
    # It carried five real safety gates and then reported a deployment that
    # never happened; making it refuse would have left a permanent refusal in
    # the codebase for a capability the architecture no longer has.
    #
    # Archived at archive/model_weight_capability/.

    async def get_persisted_statistics(self) -> Dict[str, Any]:
        """Statistics from the DURABLE record, not this process's memory.

        `get_statistics()` counts `self.cycles`, which is an in-process list. A
        freshly constructed singleton therefore reports zero cycles no matter
        how much self-improvement has actually happened -- and the health
        monitor constructs one on every check. Measured: 11 rows in
        unified.improvement_cycles while the check reported 0, which scored the
        learning component 46/100 and blocked further self-improvement on the
        grounds that self-improvement had never run. A subsystem that reads its
        own liveness off an object it just built cannot observe itself.

        Returns the same keys as get_statistics() so the two are substitutable.
        """
        from core.database import get_database_manager

        db = get_database_manager()
        if not getattr(db, "initialized", False):
            await db.initialize()

        rows = await db.execute_query(
            """SELECT count(*)                                   AS total_cycles,
                      count(*) FILTER (WHERE success_rate > 0.7)  AS successful_cycles,
                      COALESCE(sum(deployed_count), 0)            AS total_deployed,
                      COALESCE(avg(duration_sec), 0.0)            AS avg_duration
               FROM unified.improvement_cycles""", fetch_all=True)
        row = rows[0] if rows else {}
        total = int(row.get("total_cycles") or 0)

        components = await db.execute_query(
            """SELECT count(DISTINCT component) AS n
               FROM unified.improvement_cycles,
                    LATERAL jsonb_array_elements_text(
                        CASE WHEN jsonb_typeof(components) = 'array'
                             THEN components ELSE '[]'::jsonb END) AS component""",
            fetch_all=True)

        return {
            "total_cycles": total,
            "successful_cycles": int(row.get("successful_cycles") or 0),
            # None, not 0.0, over zero cycles: a success rate with no cycles to
            # average is undefined, and reporting 0.0 makes "never ran" look
            # like "always failed".
            "success_rate": (int(row.get("successful_cycles") or 0) / total) if total else None,
            "total_improvements_deployed": int(row.get("total_deployed") or 0),
            "avg_cycle_duration": float(row.get("avg_duration") or 0.0),
            "components_improved": int((components[0]["n"] if components else 0) or 0),
        }

    def get_statistics(self) -> Dict[str, Any]:
        """Get self-improvement statistics"""
        total_cycles = len(self.cycles)

        if total_cycles == 0:
            return {
                "total_cycles": 0,
                "successful_cycles": 0,
                # None, not 0.0 -- the same reason `get_persisted_statistics`
                # gives: a success rate with no cycles to average is undefined,
                # and 0.0 makes "never ran" look like "always failed". That
                # twin's docstring says the two are substitutable, and they
                # were not: this one still returned the misleading half of the
                # very defect it documents fixing.
                "success_rate": None,
                "total_improvements_deployed": 0,
                "avg_cycle_duration": 0.0,
                "components_improved": 0
            }

        successful = sum(1 for c in self.cycles if c.success_rate > 0.7)
        total_deployed = sum(len(c.improvements_deployed) for c in self.cycles)
        avg_duration = sum(c.duration_sec for c in self.cycles) / total_cycles

        return {
            "total_cycles": total_cycles,
            "successful_cycles": successful,
            "success_rate": successful / total_cycles,
            "total_improvements_deployed": total_deployed,
            "avg_cycle_duration": avg_duration,
            "components_improved": len(self.improvement_history)
        }


# Singleton instance
_asi_self_improvement = None


def get_asi_self_improvement() -> EnhancedASISelfImprovement:
    """Get global ASI self-improvement instance"""
    global _asi_self_improvement
    if _asi_self_improvement is None:
        _asi_self_improvement = EnhancedASISelfImprovement()
    return _asi_self_improvement


# CLI test
if __name__ == "__main__":
    async def main():
        logging.basicConfig(level=logging.INFO)

        print("\n=== Enhanced ASI Self-Improvement Test ===")
        print("LLM: Unified LLM (local)")
        asi = get_asi_self_improvement()

        # Run minor improvement cycle
        cycle = await asi.run_improvement_cycle(
            scope=ImprovementScope.MINOR,
            target_components=["chat_agent", "memory_system"],
            context={"test": True}
        )

        print(f"\nCycle: {cycle.cycle_id}")
        print(f"Phase: {cycle.phase.value}")
        print(f"Targets: {len(cycle.targets)}")
        print(f"Generated: {len(cycle.improvements_generated)}")
        print(f"Deployed: {len(cycle.improvements_deployed)}")
        print(f"Success rate: {cycle.success_rate:.1%}")
        print(f"Duration: {cycle.duration_sec:.1f}s")

        # Forecast capabilities
        forecast = await asi.forecast_capabilities(horizon_days=90)
        print(f"\nCapability Forecast ({forecast['horizon_days']} days):")
        print(f"Components: {len(forecast['capabilities'])}")
        print(f"Breakthroughs: {len(forecast['estimated_breakthroughs'])}")
        print(f"Confidence: {forecast['confidence']:.1%}")

        # Statistics
        stats = asi.get_statistics()
        print(f"\nStatistics:")
        print(f"LLM Model: {stats['llm_model']}")
        print(f"Total cycles: {stats['total_cycles']}")
        print(f"Success rate: {stats['success_rate']:.1%}")
        print(f"Improvements deployed: {stats['total_improvements_deployed']}")
        print(f"Components improved: {stats['components_improved']}")

        print("\n=== Test Complete ===")

    asyncio.run(main())
