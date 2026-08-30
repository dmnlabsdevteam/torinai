#!/usr/bin/env python3
"""
Mutation Detector - AST-based Detection of Runtime Mutation Attempts

Analyzes generated code for attempts to bypass security constraints through:
- sys.modules modifications
- Import overwrites
- Attribute patching on critical modules
- Constraint parameter changes
- Dynamic import manipulation
"""

import ast
import logging
from typing import List, Tuple, Set, Dict, Any
from dataclasses import dataclass

from core.governance.critical_modules import (
    CRITICAL_MODULES as _CRITICAL_MODULES,
    CRITICAL_MODULE_PREFIXES as _CRITICAL_PREFIXES,
    is_critical)

logger = logging.getLogger(__name__)


@dataclass
class MutationViolation:
    """Detected mutation attempt"""
    violation_type: str
    line_number: int
    code_snippet: str
    severity: str  # CRITICAL, HIGH, MEDIUM
    details: str


class MutationDetector(ast.NodeVisitor):
    """
    AST-based mutation detector

    Analyzes Python code for patterns that could bypass security constraints:
    1. sys.modules assignments/modifications
    2. importlib dynamic imports
    3. setattr() on critical modules
    4. __import__() with variable module names
    5. exec()/eval() usage
    6. Modifications to validator/governor parameters
    """

    #: Owned by core.governance.critical_modules. Both this (pre-execution)
    #: and runtime_governance (post-execution) enforce against the same list;
    #: it was written out twice and could drift.
    CRITICAL_MODULE_PATTERNS = list(_CRITICAL_PREFIXES)
    CRITICAL_MODULES = set(_CRITICAL_MODULES)

    #: Builtins whose aliasing defeats a name-based check.
    DANGEROUS_BUILTINS = {'exec', 'eval', 'setattr', 'delattr', '__import__',
                          'compile', 'globals', 'vars'}

    def __init__(self, code: str):
        self.code = code
        self.code_lines = code.split('\n')
        self.violations: List[MutationViolation] = []
        self.imports: Set[str] = set()
        #: local name -> module path. `import sys as s` binds 's' -> 'sys'.
        #: Without this, one alias defeated every check in the file: verified
        #: that `import sys as s; s.modules[...] = x` passed as SAFE.
        self.import_aliases: Dict[str, str] = {}
        #: local name -> dangerous builtin. `run = exec` binds 'run' -> 'exec'.
        self.builtin_aliases: Dict[str, str] = {}
        #: local name -> literal string. `code = "..."` then `exec(code)` is the
        #: shape in this module's own self-test, and passing the payload through
        #: one variable was enough to hide it from analysis.
        self.string_constants: Dict[str, str] = {}

    def detect_mutations(self) -> Tuple[bool, List[MutationViolation]]:
        """
        Analyze code for mutation attempts

        Returns:
            (is_safe, violations) - False if mutations detected
        """
        try:
            tree = ast.parse(self.code)
            self.visit(tree)

            # SEVERITY NOW DECIDES. It was collected, reported, and ignored:
            # `is_safe` was `len(violations) == 0`, and the validator blocked on
            # any violation, so HIGH blocked exactly as hard as CRITICAL and the
            # grading carried no information.
            #
            # Measured over 250 real core/ files: 9 are flagged, every one HIGH
            # and every one legitimate (dynamic component loading in
            # health_monitor, sys.path setup in tools). Blocking those is a
            # false positive; reporting them is useful.
            #
            # CRITICAL means the code names a critical module and tampers with
            # it. HIGH means a construct static analysis cannot follow -- worth
            # surfacing, not worth blocking on its own.
            blocking = [v for v in self.violations if v.severity == "CRITICAL"]
            is_safe = len(blocking) == 0

            if self.violations:
                logger.warning(
                    "🚨 Mutation detector: %d violation(s), %d blocking",
                    len(self.violations), len(blocking)
                )
                for v in self.violations:
                    logger.warning(
                        f"  {v.severity}: {v.violation_type} at line {v.line_number}"
                    )

            return (is_safe, self.violations)

        except SyntaxError as e:
            # NOT SAFE -- UNANALYSED. This returned (True, []) on the reasoning
            # that UpgradeValidator would catch the syntax error separately.
            # That makes this gate's answer depend on another gate running, and
            # "I could not parse this" is not "I found no mutations". Verified:
            # `detect_mutations('def broken(:')` reported is_safe=True.
            logger.error("Mutation detection could not parse the code: %s", e)
            return (False, [MutationViolation(
                violation_type="unanalysable_code",
                line_number=getattr(e, 'lineno', 0) or 0,
                code_snippet=self._get_code_snippet(getattr(e, 'lineno', 0) or 0),
                severity="CRITICAL",
                details=(f"Code could not be parsed, so it was never checked "
                         f"for mutations: {e}. Unanalysed code is not cleared "
                         f"code."),
            )])
        except Exception as e:
            # THE COMMENT SAID "Fail-safe". IT WAS FAIL-OPEN. A crashed tamper
            # detector reported no tampering, which is the one answer it must
            # never give -- the same shape as a security check whose exception
            # handler returns "nothing found".
            logger.error("Mutation detection failed: %s", e, exc_info=True)
            return (False, [MutationViolation(
                violation_type="detector_failure",
                line_number=0,
                code_snippet="",
                severity="CRITICAL",
                details=(f"The mutation detector itself failed ({type(e).__name__}: "
                         f"{e}), so this code is UNCHECKED. It is not cleared."),
            )])

    def visit_Import(self, node: ast.Import):
        """Track imports AND the local name each is bound to."""
        for alias in node.names:
            self.imports.add(alias.name)
            # `import x.y.z` binds `x`; `import x.y.z as n` binds `n`.
            local = alias.asname or alias.name.split('.')[0]
            self.import_aliases[local] = alias.name
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        """Track from-imports, including names pulled out of a module."""
        if node.module:
            self.imports.add(node.module)
            for alias in node.names:
                local = alias.asname or alias.name
                # `from importlib import import_module` must be as visible as
                # `importlib.import_module` -- only the dotted form was checked.
                self.import_aliases[local] = f"{node.module}.{alias.name}"
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign):
        """Detect sys.modules assignments"""
        # `run = exec` -- an alias defeats every check keyed on the name.
        if isinstance(node.value, ast.Name) and node.value.id in self.DANGEROUS_BUILTINS:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.builtin_aliases[target.id] = node.value.id

        # `code = "<python>"` -- remembered so exec(code) can be read. Only a
        # single literal assignment is tracked; a name reassigned later is
        # dropped rather than guessed at.
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    if target.id in self.string_constants:
                        self.string_constants.pop(target.id)   # ambiguous now
                    else:
                        self.string_constants[target.id] = node.value.value

        for target in node.targets:
            if isinstance(target, ast.Subscript):
                if self._is_module_dict_access(target):
                    self.violations.append(MutationViolation(
                        violation_type="module_dict_assignment",
                        line_number=node.lineno,
                        code_snippet=self._get_code_snippet(node.lineno),
                        severity="CRITICAL",
                        details=("Write through a critical module's __dict__. "
                                 "Equivalent to monkey-patching it. BLOCKED."),
                    ))
                elif self._is_globals_access(target):
                    self.violations.append(MutationViolation(
                        violation_type="globals_assignment",
                        line_number=node.lineno,
                        code_snippet=self._get_code_snippet(node.lineno),
                        severity="HIGH",
                        details=("Assignment through globals()/vars() rebinds a "
                                 "module-level name dynamically, which static "
                                 "analysis cannot follow."),
                    ))

            # Check for sys.modules[...] = ...
            if isinstance(target, ast.Subscript):
                if self._is_sys_modules_access(target):
                    code_snippet = self._get_code_snippet(node.lineno)
                    self.violations.append(MutationViolation(
                        violation_type="sys_modules_assignment",
                        line_number=node.lineno,
                        code_snippet=code_snippet,
                        severity="CRITICAL",
                        details=(
                            "Attempt to modify sys.modules detected. "
                            "This could replace critical security modules at runtime. "
                            "BLOCKED to prevent constraint relaxation."
                        )
                    ))

            # Check for direct attribute assignment to critical modules
            if isinstance(target, ast.Attribute):
                if self._is_critical_module_attr(target):
                    code_snippet = self._get_code_snippet(node.lineno)
                    self.violations.append(MutationViolation(
                        violation_type="critical_module_attribute_assignment",
                        line_number=node.lineno,
                        code_snippet=code_snippet,
                        severity="CRITICAL",
                        details=(
                            f"Attempt to modify attribute '{target.attr}' on critical module. "
                            "BLOCKED to prevent security infrastructure tampering."
                        )
                    ))

        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        """Detect dangerous function calls"""

        # Resolve an aliased builtin back to what it really is, so `run = exec`
        # is treated as exec. Verified previously to slip through entirely.
        called = None
        if isinstance(node.func, ast.Name):
            called = self.builtin_aliases.get(node.func.id, node.func.id)

        # object.__setattr__(m, ...) / type.__setattr__(m, ...) bypass bare setattr
        if isinstance(node.func, ast.Attribute) and node.func.attr in ('__setattr__', '__delattr__'):
            if node.args and self._could_be_critical_module(node.args[0]):
                self.violations.append(MutationViolation(
                    violation_type="dunder_setattr_on_critical_module",
                    line_number=node.lineno,
                    code_snippet=self._get_code_snippet(node.lineno),
                    severity="CRITICAL",
                    details=("object.__setattr__ used on a critical module — "
                             "the same patch as setattr, spelled to avoid it. "
                             "BLOCKED."),
                ))

        # importlib.reload(critical) re-executes a module, discarding any
        # runtime state the safety layer established.
        if isinstance(node.func, ast.Attribute) and node.func.attr == 'reload':
            if node.args and self._could_be_critical_module(node.args[0]):
                self.violations.append(MutationViolation(
                    violation_type="reload_critical_module",
                    line_number=node.lineno,
                    code_snippet=self._get_code_snippet(node.lineno),
                    severity="CRITICAL",
                    details=("importlib.reload() of a critical module discards "
                             "its established state. BLOCKED."),
                ))

        # sys.path manipulation shadows a module by making another importable first.
        if isinstance(node.func, ast.Attribute) and node.func.attr in ('insert', 'append', 'extend'):
            value = node.func.value
            if (isinstance(value, ast.Attribute) and value.attr == 'path'
                    and isinstance(value.value, ast.Name)
                    and self.import_aliases.get(value.value.id, value.value.id) == 'sys'):
                self.violations.append(MutationViolation(
                    violation_type="sys_path_manipulation",
                    line_number=node.lineno,
                    code_snippet=self._get_code_snippet(node.lineno),
                    severity="HIGH",
                    details=("sys.path modified — a module can be shadowed by "
                             "placing another earlier on the path."),
                ))

        # from importlib import import_module; import_module(name)
        if isinstance(node.func, ast.Name):
            bound = self.import_aliases.get(node.func.id, '')
            if bound.endswith('importlib.import_module') and node.args:
                if not isinstance(node.args[0], ast.Constant):
                    self.violations.append(MutationViolation(
                        violation_type="importlib_dynamic_import",
                        line_number=node.lineno,
                        code_snippet=self._get_code_snippet(node.lineno),
                        severity="HIGH",
                        details=("import_module() with a variable name, imported "
                                 "unqualified. Could enable module substitution."),
                    ))

        # Check for setattr() on critical modules
        if called == 'setattr':
            if len(node.args) >= 1:
                first_arg = node.args[0]
                if self._could_be_critical_module(first_arg):
                    code_snippet = self._get_code_snippet(node.lineno)
                    self.violations.append(MutationViolation(
                        violation_type="setattr_on_critical_module",
                        line_number=node.lineno,
                        code_snippet=code_snippet,
                        severity="CRITICAL",
                        details=(
                            "setattr() call on potentially critical module detected. "
                            "Could be used to patch security functions. BLOCKED."
                        )
                    ))

        # exec/eval OF A LITERAL STRING is analysable -- the payload is right
        # there. The self-test's own case is `exec("...sys.modules[...] = fake")`,
        # which was reported HIGH-but-not-blocking because only the exec call
        # was seen and never its contents. A constant argument is recursed into,
        # so a mutation hidden in a literal blocks exactly as if it were written
        # inline. A non-constant payload stays HIGH: it genuinely cannot be read.
        if called in ('exec', 'eval', 'compile') and node.args:
            payload = node.args[0]
            source = None
            if isinstance(payload, ast.Constant) and isinstance(payload.value, str):
                source = payload.value
            elif isinstance(payload, ast.Name):
                source = self.string_constants.get(payload.id)
            if source is not None:
                try:
                    inner = MutationDetector(source)
                    inner.import_aliases = dict(self.import_aliases)
                    inner.builtin_aliases = dict(self.builtin_aliases)
                    inner.visit(ast.parse(source))
                    for v in inner.violations:
                        self.violations.append(MutationViolation(
                            violation_type=f"{v.violation_type}_in_{called}_payload",
                            line_number=node.lineno,
                            code_snippet=self._get_code_snippet(node.lineno),
                            severity=v.severity,
                            details=(f"Inside a literal string passed to {called}(): "
                                     f"{v.details}"),
                        ))
                except SyntaxError:
                    # A literal that is not parseable Python is not a payload
                    # this can reason about; the generic finding below stands.
                    pass

        # Check for exec() / eval(), including through an alias
        if called in ('exec', 'eval'):
            code_snippet = self._get_code_snippet(node.lineno)
            self.violations.append(MutationViolation(
                violation_type=f"{called}_usage",
                line_number=node.lineno,
                code_snippet=code_snippet,
                severity="HIGH",
                details=(
                    f"{called}() usage detected. "
                    "Dynamic code execution can bypass static analysis. "
                    "BLOCKED for safety."
                )
            ))

        # Check for __import__() with non-constant module names
        if called == '__import__':
            if len(node.args) >= 1:
                if not isinstance(node.args[0], ast.Constant):
                    code_snippet = self._get_code_snippet(node.lineno)
                    self.violations.append(MutationViolation(
                        violation_type="dynamic_import",
                        line_number=node.lineno,
                        code_snippet=code_snippet,
                        severity="HIGH",
                        details=(
                            "__import__() with variable module name detected. "
                            "Could be used for import shadowing. BLOCKED."
                        )
                    ))

        # Check for importlib.import_module() with variable names
        if isinstance(node.func, ast.Attribute):
            if (isinstance(node.func.value, ast.Name) and
                node.func.value.id == 'importlib' and
                node.func.attr == 'import_module'):
                if len(node.args) >= 1:
                    if not isinstance(node.args[0], ast.Constant):
                        code_snippet = self._get_code_snippet(node.lineno)
                        self.violations.append(MutationViolation(
                            violation_type="importlib_dynamic_import",
                            line_number=node.lineno,
                            code_snippet=code_snippet,
                            severity="HIGH",
                            details=(
                                "importlib.import_module() with variable name detected. "
                                "Could enable module substitution. BLOCKED."
                            )
                        ))

        self.generic_visit(node)

    def visit_Delete(self, node: ast.Delete):
        """Detect deletions of critical imports or attributes"""
        for target in node.targets:
            if isinstance(target, ast.Subscript):
                if self._is_sys_modules_access(target):
                    code_snippet = self._get_code_snippet(node.lineno)
                    self.violations.append(MutationViolation(
                        violation_type="sys_modules_deletion",
                        line_number=node.lineno,
                        code_snippet=code_snippet,
                        severity="CRITICAL",
                        details=(
                            "Attempt to delete from sys.modules detected. "
                            "Could enable module replacement. BLOCKED."
                        )
                    ))

        self.generic_visit(node)

    def _is_sys_modules_access(self, node: ast.Subscript) -> bool:
        """Whether this is sys.modules[...], however `sys` was bound.

        Required the literal name `sys`, so `import sys as s` defeated it
        outright -- verified.
        """
        if isinstance(node.value, ast.Attribute) and node.value.attr == 'modules':
            base = node.value.value
            if isinstance(base, ast.Name):
                return self.import_aliases.get(base.id, base.id) == 'sys'
        return False

    def _is_module_dict_access(self, node: ast.Subscript) -> bool:
        """Whether this is <critical module>.__dict__[...].

        Writing through `__dict__` patches a module exactly as `setattr` does
        and was not checked at all.
        """
        if isinstance(node.value, ast.Attribute) and node.value.attr == '__dict__':
            return self._could_be_critical_module(node.value.value)
        return False

    @staticmethod
    def _is_globals_access(node: ast.Subscript) -> bool:
        """Whether this is globals()[...] — rebinding a name in this module."""
        return (isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id in ('globals', 'vars'))

    def _is_critical_module_attr(self, node: ast.Attribute) -> bool:
        """Check if node is an attribute of a critical module"""
        # Get the base name
        base = node
        parts = []

        while isinstance(base, ast.Attribute):
            parts.insert(0, base.attr)
            base = base.value

        if isinstance(base, ast.Name):
            parts.insert(0, base.id)

        module_path = '.'.join(parts[:-1]) if len(parts) > 1 else ''

        # Check if it matches critical module patterns
        for pattern in self.CRITICAL_MODULE_PATTERNS:
            if module_path.startswith(pattern):
                return True

        return module_path in self.CRITICAL_MODULES

    def _could_be_critical_module(self, node: ast.AST) -> bool:
        """Whether this expression actually names a critical module.

        BOTH PREVIOUS TESTS WERE FALSE-POSITIVE ENGINES, measured against the
        live module:

          `node.id in critical_module` was a SUBSTRING test against the module
          path, so `setattr(a, ...)` and `setattr(e, ...)` were reported
          CRITICAL -- any single letter occurring anywhere in
          "core.learning.meta_learning" matched.

          The second test returned True for EVERY name as soon as the file
          imported anything under a critical prefix. TorinAI's own generated
          code imports `core.learning.*` constantly, so effectively every
          `setattr` in real code was blocked as a mutation attempt.

        A name is now critical only when this file actually bound it to a
        critical module -- `import core.learning.meta_learning as m` makes `m`
        critical, and nothing else does.
        """
        if isinstance(node, ast.Name):
            bound = self.import_aliases.get(node.id)
            return bool(bound) and is_critical(bound)
        # Dotted form: core.learning.meta_learning
        if isinstance(node, ast.Attribute):
            return is_critical(self._dotted_name(node))
        return False

    @staticmethod
    def _dotted_name(node: ast.AST) -> str:
        """Reconstruct a dotted path from an Attribute/Name chain, or ''."""
        parts: List[str] = []
        while isinstance(node, ast.Attribute):
            parts.insert(0, node.attr)
            node = node.value
        if isinstance(node, ast.Name):
            parts.insert(0, node.id)
            return ".".join(parts)
        return ""

    def _get_code_snippet(self, line_number: int) -> str:
        """Get code snippet around line number"""
        if 1 <= line_number <= len(self.code_lines):
            return self.code_lines[line_number - 1].strip()
        return ""


def detect_mutations(code: str) -> Tuple[bool, List[MutationViolation]]:
    """
    Convenience function to detect mutations in code

    Args:
        code: Python source code to analyze

    Returns:
        (is_safe, violations) - False if mutations detected
    """
    detector = MutationDetector(code)
    return detector.detect_mutations()


if __name__ == "__main__":
    # Test cases
    test_cases = [
        # Test 1: sys.modules assignment
        """
import sys
import fake_validator
sys.modules['core.learning.upgrade_validator'] = fake_validator
""",
        # Test 2: setattr on critical module
        """
import core.learning.meta_learning as meta
setattr(meta, 'validate_strategy_for_production', lambda *args: (True, "bypassed"))
""",
        # Test 3: exec usage
        """
code = "import sys; sys.modules['core.governance'] = fake"
exec(code)
""",
        # Test 4: Safe code
        """
def calculate_improvement(baseline, current):
    return (current - baseline) / baseline * 100
"""
    ]

    for i, test_code in enumerate(test_cases, 1):
        print(f"\n{'='*60}")
        print(f"Test {i}:")
        print(f"{'='*60}")
        print(test_code)
        print(f"\n{'Result':}")
        is_safe, violations = detect_mutations(test_code)
        print(f"  Safe: {is_safe}")
        if violations:
            for v in violations:
                print(f"\n  {v.severity}: {v.violation_type}")
                print(f"  Line {v.line_number}: {v.code_snippet}")
                print(f"  {v.details}")
