"""Oracles for StaticCodeAnalyzer.

This is HARD GATE 1 in _verify_generated_code: anything it clears goes on to be
deployed into the running substrate, and anything it rejects raises. It had no
tests at all.

Each test states the behaviour that was actually observed before the fix, so
none of them pass against the old implementation by accident.
"""
import ast

import pytest

from core.learning.enhanced_asi_self_improvement import StaticCodeAnalyzer as S


# --------------------------------------------------------------------------
# Ordinary Python must be analysable. The one caller passes strict=True.
# --------------------------------------------------------------------------

ORDINARY = [
    ("class with __init__", 'class F:\n    def __init__(self):\n        self.x = 1\n'),
    ("module guard", 'def main():\n    return 1\n\nif __name__ == "__main__":\n    main()\n'),
    ("plain function", 'def add(a, b):\n    return a + b\n'),
    ("constant getattr", 'def f(o):\n    return getattr(o, "name")\n'),
    ("constant setattr", 'def f(o):\n    setattr(o, "count", 1)\n'),
    ("dunder in a method name", 'class F:\n    def __repr__(self):\n        return "F"\n'),
]


@pytest.mark.parametrize("label,code", ORDINARY, ids=[c[0] for c in ORDINARY])
def test_ordinary_python_passes_strict(label, code):
    """A blanket `__[a-zA-Z_]+__` suspicious pattern matched __init__, __repr__,
    __name__ and __main__, and regexes flagged every getattr/setattr. With
    strict=True -- what _verify_generated_code uses -- that made ordinary Python
    fail the hard gate, so no realistic generated improvement could ever be
    verified."""
    result = S.analyze(code, strict=True)
    assert result["safe"] is True, (
        f"{label} rejected: {result['reason']}"
    )


# --------------------------------------------------------------------------
# Dangerous code must still be caught.
# --------------------------------------------------------------------------

DANGEROUS = [
    ("direct exec", 'def f():\n    exec("x=1")\n'),
    ("direct eval", 'def f():\n    return eval("1+1")\n'),
    ("dunder import", 'def f():\n    return __import__("os")\n'),
    ("indirect exec via getattr", 'def f(o):\n    return getattr(o, "exec")("bad")\n'),
    ("globals subscript", 'def f():\n    globals()["exec"]("bad")\n'),
    ("sandbox escape chain",
     'def f():\n    return ().__class__.__bases__[0].__subclasses__()\n'),
    ("__globals__ builtins reach", 'def f(g):\n    return g.__globals__["__builtins__"]\n'),
    ("os.system", 'import os\ndef f():\n    os.system("id")\n'),
    ("shell=True", 'import subprocess\ndef f():\n    subprocess.run("x", shell=True)\n'),
    ("pickle.loads", 'import pickle\ndef f(b):\n    return pickle.loads(b)\n'),
    ("sql drop", 'def f(c):\n    c.execute("DROP TABLE users")\n'),
]


@pytest.mark.parametrize("label,code", DANGEROUS, ids=[c[0] for c in DANGEROUS])
def test_dangerous_code_is_rejected(label, code):
    result = S.analyze(code, strict=True)
    assert result["safe"] is False, f"{label} was cleared"
    assert result["dangerous_patterns"], f"{label} produced no dangerous finding"


# --------------------------------------------------------------------------
# Nothing to analyse is not a pass.
# --------------------------------------------------------------------------

EMPTY = [
    ("empty string", ""),
    ("whitespace", "   \n\n  "),
    ("comment only", "# nothing here\n"),
    ("docstring only", '"""just a docstring"""\n'),
]


@pytest.mark.parametrize("label,code", EMPTY, ids=[c[0] for c in EMPTY])
def test_nothing_to_analyse_fails_closed(label, code):
    """These matched no pattern, so the result was safe=True with the reason
    'Code passed static analysis' -- an absence of code reported as code that
    had been checked and cleared, on the gate that precedes deployment."""
    result = S.analyze(code, strict=True)
    assert result["safe"] is False
    assert "nothing was verified" in result["reason"].lower()


def test_non_string_input_names_the_real_fault():
    """None reached re.finditer and surfaced as 'expected string or bytes-like
    object' from inside the scan, rather than as the upstream fault it is."""
    with pytest.raises(TypeError, match="produced no code"):
        S.analyze(None, strict=True)


# --------------------------------------------------------------------------
# One finding per fact.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("code,expected", [
    ('def f():\n    exec("x=1")\n', 1),
    ('import subprocess\ndef f():\n    subprocess.run("x", shell=True)\n', 1),
    ('def f():\n    globals()["exec"]("bad")\n', 1),
])
def test_a_single_call_is_reported_once(code, expected):
    """Both layers detect these, so one `exec()` produced two findings and one
    `os.system("rm -rf /")` produced three -- the reason line then claimed
    'Found 3 dangerous pattern(s)' for a single call."""
    result = S.analyze(code, strict=True)
    assert len(result["dangerous_patterns"]) == expected


def test_genuinely_distinct_facts_are_still_counted_separately():
    """Deduplication must not merge two different problems on one line."""
    result = S.analyze('import os\ndef f():\n    os.system("rm -rf /")\n', strict=True)
    reasons = " ".join(d["reason"] for d in result["dangerous_patterns"])
    assert "os.system" in reasons and "Destructive file operations" in reasons


# --------------------------------------------------------------------------
# Precision: only what cannot be checked statically is "suspicious".
# --------------------------------------------------------------------------

def test_computed_attribute_name_is_flagged():
    """getattr(o, "name") is exactly o.name and has nothing to review;
    getattr(o, k) cannot be resolved statically and does."""
    assert S.analyze('def f(o, k):\n    return getattr(o, k)\n', strict=True)["safe"] is False
    assert S.analyze('def f(o):\n    return getattr(o, "name")\n', strict=True)["safe"] is True


# --------------------------------------------------------------------------
# Failure of the analysis is not a clean result.
# --------------------------------------------------------------------------

def test_unparseable_code_keeps_regex_coverage():
    """With no AST there is nothing to be authoritative, so the overlapping
    regexes must run rather than be skipped."""
    result = S.analyze('def f(:\n    os.system("id")\n', strict=True)
    assert result["safe"] is False
    reasons = " ".join(d["reason"] for d in result["dangerous_patterns"])
    assert "does not parse" in reasons
    assert "os.system" in reasons, "the fallback layer must still scan unparseable code"


def test_crashed_ast_analysis_cannot_clear_code(monkeypatch):
    """`except Exception: return ([], [])` meant an analysis that did not run
    reported no findings -- indistinguishable from clean code, on a gate whose
    whole job is to withhold clearance."""
    import core.learning.enhanced_asi_self_improvement as mod

    real_parse = ast.parse
    calls = {"n": 0}

    def exploding_parse(src, *a, **kw):
        # _has_executable_code parses first; fail only the analysis pass.
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("simulated analyser fault")
        return real_parse(src, *a, **kw)

    monkeypatch.setattr(mod.ast, "parse", exploding_parse)

    result = S.analyze('def f():\n    return 1\n', strict=True)
    assert result["safe"] is False
    assert any("could not run" in d["reason"] for d in result["dangerous_patterns"])


def test_parse_flag_is_reported_to_the_caller():
    """analyze() needs to know whether the AST pass could be authoritative."""
    _, _, parsed = S._analyze_ast('def f():\n    return 1\n')
    assert parsed is True
    _, _, parsed_bad = S._analyze_ast('def f(:\n')
    assert parsed_bad is False


# --------------------------------------------------------------------------
# The gate itself.
# --------------------------------------------------------------------------

def test_analyzer_is_the_first_gate_before_deployment():
    """Its verdict must be consumed as a hard failure, not logged and passed."""
    import inspect
    from core.learning.enhanced_asi_self_improvement import EnhancedASISelfImprovement
    src = inspect.getsource(EnhancedASISelfImprovement._verify_generated_code)
    assert "StaticCodeAnalyzer.analyze(code, strict=True)" in src
    head = src.split("StaticCodeAnalyzer.analyze", 1)[1]
    assert 'if not static_result["safe"]' in head
    assert "raise RuntimeError" in head.split('if not static_result["safe"]', 1)[1][:400]


# --------------------------------------------------------------------------
# The filesystem rule has to describe the operation, not one spelling of it.
# --------------------------------------------------------------------------

WRITES_AND_DELETES = [
    ("text write", 'def f(p):\n    open(p, "w").write("x")\n'),
    ("binary write", 'def f(p):\n    open(p, "wb").write(b"x")\n'),
    ("append", 'def f(p):\n    open(p, "a").write("x")\n'),
    ("exclusive create", 'def f(p):\n    open(p, "x").write("y")\n'),
    ("computed mode", 'def f(p, mode):\n    open(p, mode).write("x")\n'),
    ("mode keyword", 'def f(p):\n    open(p, mode="w").write("x")\n'),
    ("pathlib write_text", 'from pathlib import Path\ndef f(p):\n    Path(p).write_text("x")\n'),
    ("pathlib write_bytes", 'from pathlib import Path\ndef f(p):\n    Path(p).write_bytes(b"x")\n'),
    ("os.remove", 'import os\ndef f(p):\n    os.remove(p)\n'),
    ("os.unlink", 'import os\ndef f(p):\n    os.unlink(p)\n'),
    ("shutil.rmtree", 'import shutil\ndef f(p):\n    shutil.rmtree(p)\n'),
    ("pathlib unlink", 'from pathlib import Path\ndef f(p):\n    Path(p).unlink()\n'),
]


@pytest.mark.parametrize("label,code", WRITES_AND_DELETES,
                         ids=[c[0] for c in WRITES_AND_DELETES])
def test_every_write_and_delete_spelling_is_caught(label, code):
    """The only filesystem rule was one regex requiring a literal 'w', so the
    policy held for exactly one spelling: 'wb', 'a', a computed mode,
    Path.write_text, os.remove and shutil.rmtree all cleared the gate -- while
    the shell string `rm -rf` was blocked. Recursive directory deletion passing
    while its shell equivalent failed is a rule about phrasing, not about the
    operation."""
    result = S.analyze(code, strict=False)   # strict=False: must be DANGEROUS, not merely suspicious
    assert result["safe"] is False, f"{label} cleared the gate"
    assert result["dangerous_patterns"], f"{label} produced no dangerous finding"


READS = [
    ("explicit read mode", 'def f(p):\n    return open(p, "r").read()\n'),
    ("default mode", 'def f(p):\n    return open(p).read()\n'),
]


@pytest.mark.parametrize("label,code", READS, ids=[c[0] for c in READS])
def test_reads_are_not_treated_as_writes(label, code):
    """Widening the rule must not turn every open() into a blocking finding."""
    result = S.analyze(code, strict=False)
    assert result["dangerous_patterns"] == [], f"{label} was reported as dangerous"


@pytest.mark.parametrize("code", [c[1] for c in WRITES_AND_DELETES])
def test_filesystem_findings_are_not_duplicated(code):
    """The regex fallbacks cover the same calls, so they must be skipped when
    the code parsed."""
    result = S.analyze(code, strict=False)
    assert len(result["dangerous_patterns"]) == 1


def test_destructive_calls_still_caught_when_code_does_not_parse():
    """With no AST the regex fallback is the only analysis left."""
    result = S.analyze('def f(:\n    shutil.rmtree(p)\n', strict=False)
    reasons = " ".join(d["reason"] for d in result["dangerous_patterns"])
    assert "does not parse" in reasons
    assert "Recursive directory deletion" in reasons
