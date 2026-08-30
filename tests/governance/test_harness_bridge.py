"""Run the TestBase governance suites under pytest, and report what they say.

There are two test frameworks in this repository. Most tests are pytest; the
governance phase suites subclass `tests/test_base.TestBase`, an in-house
harness with session management, per-test timing and durable result tracking.
Those classes take constructor arguments, so pytest declines to collect them
(`cannot collect test class ... because it has a __init__ constructor`) and
reports nothing at all for them.

"Reports nothing" is the problem. It is indistinguishable from passing, and it
was not passing: when these suites were first run through this bridge, 11 of
their 40 tests were failing, invisibly, while the pytest run went green.

This does not port the suites to pytest or replace the harness -- the harness
does things pytest does not, and rewriting 40 tests to prove a point would risk
changing what they assert. It runs each suite through its own runner and turns
the harness's own tally into a pytest result, so a governance regression fails
the build like anything else.
"""
import ast
import importlib
import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))


def _harness_suites():
    """Every TestBase subclass here that pytest cannot collect itself.

    Discovered by parsing rather than importing, so collection cannot be broken
    by a suite whose import has side effects.
    """
    found = []
    for path in sorted(HERE.glob("test_*.py")):
        if path.name == Path(__file__).name:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            bases = {b.id if isinstance(b, ast.Name) else getattr(b, "attr", "")
                     for b in node.bases}
            has_init = any(getattr(m, "name", "") == "__init__" for m in node.body)
            has_runner = any(getattr(m, "name", "") == "run_all_tests" for m in node.body)
            if "TestBase" in bases and has_init and has_runner:
                found.append((path.stem, node.name))
    return found


SUITES = _harness_suites()


def test_the_bridge_found_the_uncollectable_suites():
    """If this ever finds nothing, the bridge has silently stopped covering
    anything -- the exact failure it exists to prevent."""
    assert SUITES, "no TestBase governance suites discovered"


@pytest.mark.parametrize("module_name,class_name", SUITES,
                         ids=[f"{m}::{c}" for m, c in SUITES])
@pytest.mark.asyncio
async def test_governance_suite(module_name, class_name):
    module = importlib.import_module(f"tests.governance.{module_name}")
    suite = getattr(module, class_name)()

    await suite.run_all_tests()

    failures = [r.test_name for r in suite.results if r.failed]
    assert not failures, (
        f"{class_name}: {suite.failed_tests} of "
        f"{suite.passed_tests + suite.failed_tests} governance tests failed\n  "
        + "\n  ".join(failures)
    )
