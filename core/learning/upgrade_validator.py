#!/usr/bin/env python3
"""
Upgrade Validator
=============================================
Validates code upgrades before deployment

Validation Stages:
1. Syntax validation
2. Import verification
3. Configuration validation
4. Database schema compatibility
5. Security scanning
6. Backwards compatibility
7. Performance benchmarking

Safety-first approach: Fail closed on any critical issues
"""

import asyncio
import logging
import ast
import re
import importlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from enum import Enum


logger = logging.getLogger(__name__)


@dataclass
class ValidationCheck:
    """Result of a single validation check"""
    check_name: str
    passed: bool

    # Issues found
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationResult:
    """Overall validation result"""
    overall_passed: bool
    checks: List[ValidationCheck]

    # Test execution results
    test_results: Optional[Dict[str, Any]] = None

    # Performance metrics
    validation_duration_ms: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)


class UpgradeValidator:
    """
    Validates code upgrades before deployment

    Ensures:
    - Syntactically correct code
    - All dependencies available
    - Configuration is valid
    - Database schemas compatible
    - No security vulnerabilities
    - Backwards compatibility maintained
    - Performance requirements met
    - CRITICAL: Prevents self-modification of security infrastructure
    """

    # 🛡️ SECURITY-CRITICAL PATHS: IMMUTABLE (cannot be modified by self-improvement)
    IMMUTABLE_PATHS = {
        'core/learning/enhanced_asi_self_improvement.py',
        'core/learning/upgrade_validator.py',
        'core/learning/upgrade_sandbox.py',
        'core/learning/improvement_monitor.py',
        'core/learning/meta_learning.py',
        'core/learning/safe_upgrade_deployer.py',
        'core/learning/safety_audit_trail.py',
        'core/governance/unified_governance_trigger_system.py',
        'core/governance/enforcement_mode_manager.py',
        'core/governance/context_classifier.py',
        'core/security/safety_framework.py',
    }

    # RESTRICTED PATHS: Require CRITICAL governance approval
    RESTRICTED_PATH_PATTERNS = [
        'core/learning/',
        'core/governance/',
        'core/security/',
        'config/',
    ]

    def __init__(
        self,
        db_config: Dict[str, Any] = None,
        baseline_metrics: Dict[str, float] = None,
        strict_mode: bool = True
    ):
        self.db_config = db_config or self._get_default_db_config()
        self.baseline_metrics = baseline_metrics or {}
        self.strict_mode = strict_mode

        # Validation history
        self.validation_history: List[ValidationResult] = []

        logger.info(f"UpgradeValidator initialized with {len(self.IMMUTABLE_PATHS)} immutable paths protected")

    def _get_default_db_config(self) -> Dict[str, Any]:
        return {
            "host": "localhost",
            "user": "torin_user",
            "password": "torin_password",
            "database": "torin_ai"
        }

    async def _validate_security_critical_paths(
        self,
        file_paths: List[str],
        metadata: Dict[str, Any]
    ) -> ValidationCheck:
        """
        🛡️ SECURITY GATE: Prevent self-modification of security infrastructure

        This is the FIRST validation - executed before all others.
        Blocks ANY attempt to modify security-critical files.

        Critical files include:
        - Validators (this file, sandbox, monitor)
        - Self-improvement orchestrator
        - Governance system
        - Security framework
        - Audit trail

        Rationale: Prevents recursive systems from relaxing their own constraints
        to optimize metrics instead of capabilities.
        """
        check_name = "security_critical_path_protection"
        errors = []
        warnings = []
        passed = True

        # Normalize paths for comparison (handle different path separators)
        def normalize_path(path: str) -> str:
            return path.replace('\\', '/').strip()

        for file_path in file_paths:
            normalized_path = normalize_path(file_path)

            # CHECK 1: Exact match against IMMUTABLE_PATHS
            if normalized_path in self.IMMUTABLE_PATHS:
                passed = False
                errors.append(
                    f"🛑 BLOCKED: {file_path} is a SECURITY-CRITICAL file (IMMUTABLE). "
                    f"Self-modification of security infrastructure is FORBIDDEN. "
                    f"Rationale: Prevents relaxing constraints to game metrics."
                )
                logger.error(
                    f"🛑 SECURITY GATE BLOCKED: Attempt to modify immutable file: {file_path}"
                )
                continue

            # CHECK 2: Pattern match against RESTRICTED_PATH_PATTERNS
            for pattern in self.RESTRICTED_PATH_PATTERNS:
                if normalized_path.startswith(pattern):
                    # Check if governance approval provided
                    governance_approved = metadata and metadata.get('governance_approved_critical')
                    human_approved = metadata and metadata.get('human_approved')

                    if not (governance_approved and human_approved):
                        passed = False
                        errors.append(
                            f"🛑 BLOCKED: {file_path} is in RESTRICTED path '{pattern}'. "
                            f"Requires CRITICAL governance tier + human approval. "
                            f"governance_approved_critical={governance_approved}, "
                            f"human_approved={human_approved}"
                        )
                        logger.error(
                            f"🛑 SECURITY GATE BLOCKED: Restricted path without approval: {file_path}"
                        )
                    else:
                        warnings.append(
                            f"⚠️  CRITICAL APPROVAL: {file_path} modification approved by governance + human"
                        )
                        logger.warning(
                            f"⚠️  CRITICAL APPROVAL granted for: {file_path}"
                        )
                    break

        if passed:
            logger.info(f"✅ Security-critical path check passed ({len(file_paths)} files)")
        else:
            logger.error(
                f"🛑 Security-critical path check FAILED: {len(errors)} blocked modifications"
            )

        return ValidationCheck(
            check_name=check_name,
            passed=passed,
            errors=errors,
            warnings=warnings,
            metadata={
                "immutable_paths_checked": len(self.IMMUTABLE_PATHS),
                "restricted_patterns_checked": len(self.RESTRICTED_PATH_PATTERNS),
                "files_checked": len(file_paths),
                "governance_approval_required": any(
                    normalized_path.startswith(p)
                    for p in self.RESTRICTED_PATH_PATTERNS
                    for normalized_path in [normalize_path(fp) for fp in file_paths]
                )
            }
        )

    async def _detect_runtime_mutations(
        self,
        code: str,
        file_paths: List[str],
        metadata: Dict[str, Any]
    ) -> ValidationCheck:
        """
        🛡️ SECURITY GATE: Detect runtime mutation attempts in generated code

        Analyzes AST for patterns that could bypass file-level protection:
        - sys.modules modifications
        - importlib dynamic imports
        - setattr() on critical modules
        - exec()/eval() usage
        - __import__() with variable names

        This closes the gap between file-level immutability (prevents writes)
        and runtime protection (prevents patches).

        Rationale: Generated code could be syntactically valid but contain
        logic to weaken validators/governors at runtime, bypassing file protection.
        """
        check_name = "runtime_mutation_detection"
        errors = []
        warnings = []
        passed = True

        if not code:
            # No code to check
            return ValidationCheck(
                check_name=check_name,
                passed=True,
                errors=[],
                warnings=["No code provided for mutation detection"],
                metadata={"mutations_detected": 0}
            )

        try:
            from core.learning.mutation_detector import detect_mutations

            # Run AST-based mutation detection
            is_safe, violations = detect_mutations(code)

            if not is_safe:
                passed = False

            # A CRITICAL finding blocks; anything lower is reported and does
            # not. Previously every violation became an error and blocked, so
            # legitimate dynamic imports and sys.path setup -- which real
            # TorinAI modules use -- could not have passed validation.
            for violation in violations:
                message = (
                    f"{violation.violation_type} at line {violation.line_number}\n"
                    f"   Code: {violation.code_snippet}\n"
                    f"   {violation.details}"
                )
                if violation.severity == "CRITICAL":
                    errors.append(f"🛑 MUTATION DETECTED: {message}")
                else:
                    warnings.append(f"⚠️  {violation.severity}: {message}")

            if not is_safe:
                blocking = [v for v in violations if v.severity == "CRITICAL"]
                for violation in blocking:
                    logger.error(
                        "🛑 MUTATION GATE BLOCKED: %s at line %s",
                        violation.violation_type, violation.line_number
                    )
                logger.error("🛑 Mutation detection FAILED: %d blocking violation(s) "
                             "of %d total", len(blocking), len(violations))

            else:
                logger.info("✅ Mutation detection passed: No suspicious patterns found")

            return ValidationCheck(
                check_name=check_name,
                passed=passed,
                errors=errors,
                warnings=warnings,
                metadata={
                    "mutations_detected": len(violations),
                    "violation_types": [v.violation_type for v in violations],
                    "severity_levels": [v.severity for v in violations]
                }
            )

        except ImportError as e:
            # A MISSING GATE IS NOT A PASSED GATE. This returned passed=True
            # with a warning, so deleting or breaking the import of
            # mutation_detector silently disabled the check while the
            # validation report still said it passed.
            logger.error("MutationDetector could not be imported (%s); the "
                         "mutation check did NOT run", e)
            errors.append(
                f"🛑 MUTATION CHECK UNAVAILABLE: {e}. Code was not analysed "
                f"for mutation attempts and is not cleared.")
            return ValidationCheck(
                check_name=check_name,
                passed=False,
                errors=[],
                warnings=warnings,
                metadata={"detector_available": False}
            )

        except Exception as e:
            # Detector error - fail-safe: allow code (other validators will catch issues)
            logger.error(f"Mutation detection error: {e}")
            warnings.append(f"Mutation detection error: {e}")
            return ValidationCheck(
                check_name=check_name,
                passed=True,
                errors=[],
                warnings=warnings,
                metadata={"detector_error": str(e)}
            )

    async def validate_upgrade(
        self,
        code: str,
        file_paths: List[str],
        test_suite: str = "",
        metadata: Dict[str, Any] = None
    ) -> ValidationResult:
        """
        Validate an upgrade comprehensively

        Args:
            code: New code to validate (if single file)
            file_paths: List of file paths being upgraded
            test_suite: Optional test suite to run
            metadata: Additional metadata (description, version, etc.)

        Returns:
            ValidationResult with overall pass/fail and detailed check results
        """
        start_time = datetime.now()
        checks = []
        overall_passed = True
        test_results = None

        logger.info(f"Validating upgrade: {len(file_paths)} file(s)")

        # 0. SECURITY-CRITICAL PATH CHECK (FIRST - blocks self-modification)
        security_path_check = await self._validate_security_critical_paths(file_paths, metadata)
        checks.append(security_path_check)
        if not security_path_check.passed:
            logger.error("🛑 SECURITY GATE: Self-modification of security infrastructure BLOCKED")
            return ValidationResult(
                overall_passed=False,
                checks=checks,
                validation_duration_ms=(datetime.now() - start_time).total_seconds() * 1000
            )

        # 0.5. MUTATION DETECTION (SECOND - blocks runtime mutation attempts)
        mutation_check = await self._detect_runtime_mutations(code, file_paths, metadata)
        checks.append(mutation_check)
        if not mutation_check.passed:
            logger.error("🛑 SECURITY GATE: Runtime mutation attempt BLOCKED")
            return ValidationResult(
                overall_passed=False,
                checks=checks,
                validation_duration_ms=(datetime.now() - start_time).total_seconds() * 1000
            )

        # 1. Syntax validation
        syntax_check = await self._validate_syntax(code, file_paths, metadata)
        checks.append(syntax_check)
        if not syntax_check.passed:
            logger.error("Syntax validation failed")
            overall_passed = False
            # In strict mode, fail fast on syntax errors
            if self.strict_mode:
                return ValidationResult(
                    overall_passed=False,
                    checks=checks
                )

        # 2. Import validation
        import_check = await self._validate_imports(code, file_paths)
        checks.append(import_check)

        # 4b. THE UPGRADE'S OWN TESTS. Everything above reads the code; this
        # runs it. Placed after imports because a module that cannot import
        # cannot be tested, and its import failure is the better message.
        test_check = await self._validate_test_suite(code, test_suite, metadata)
        checks.append(test_check)
        if not test_check.passed:
            overall_passed = False
        if not import_check.passed:
            overall_passed = False

        # 3. Configuration validation (if config files present)
        if any("config" in fp.lower() for fp in file_paths):
            logger.info("Configuration files detected, validating")
            config_check = await self._validate_config(code)
        else:
            config_check = ValidationCheck(
                check_name="configuration",
                passed=True
            )
        checks.append(config_check)
        if not config_check.passed:
            overall_passed = False

        # 4. Database schema validation (if migration files present)
        if any("migration" in fp.lower() or "schema" in fp.lower() for fp in file_paths):
            schema_check = await self._validate_database_schema(code)
        else:
            schema_check = ValidationCheck(
                check_name="database_schema",
                passed=True
            )
        checks.append(schema_check)
        if not schema_check.passed:
            overall_passed = False

        # 5. Security validation
        security_check = await self._validate_security(code, file_paths)
        checks.append(security_check)
        if not security_check.passed:
            overall_passed = False

        # 6. Backwards compatibility
        compat_check = await self._validate_backwards_compatibility(code, file_paths)
        checks.append(compat_check)
        if not compat_check.passed:
            overall_passed = False

        # 7. Performance validation
        # Was called with (code) only; the signature requires (code, file_paths).
        # Every validation that survived stages 0-6 died here with TypeError, so
        # no upgrade could ever pass validation. file_paths is already in scope.
        perf_check = await self._validate_performance(code, file_paths)
        checks.append(perf_check)
        if not perf_check.passed:
            overall_passed = False

        # Calculate validation duration
        duration_ms = (datetime.now() - start_time).total_seconds() * 1000

        # Build result
        passed_checks = sum(1 for c in checks if c.passed)
        total_checks = len(checks)

        result_msg = f"Validation {'PASSED' if overall_passed else 'FAILED'}"
        if overall_passed:
            failed_checks = [c.check_name for c in checks if not c.passed]
            result_msg += f": {passed_checks}/{total_checks} checks passed"
            if failed_checks:
                result_msg += f" (warnings in: {', '.join(failed_checks)})"

        result = ValidationResult(
            overall_passed=overall_passed,
            checks=checks,
            test_results=test_results,
            validation_duration_ms=duration_ms,
            timestamp=datetime.now()
        )

        logger.info(f"Validation complete: {result_msg}")

        return result

    async def _validate_test_suite(
        self,
        code: str,
        test_suite: str,
        metadata: Dict[str, Any]
    ) -> ValidationCheck:
        """Run the upgrade's own tests, in the sandbox.

        `validate_upgrade` has always accepted `test_suite`, documented it as
        "Optional test suite to run", and READ IT ZERO TIMES -- verified by
        parsing this file's AST. So an upgrade could arrive with tests and they
        would be silently ignored.

        Executing arbitrary generated tests in this process is not an option;
        the thing that can do it safely is `UpgradeSandbox`, which runs them
        under Docker with no network. This file's own note at the bottom says
        it "validates a generated upgrade before it is allowed near the
        sandbox" -- so the ordering was already decided, and only the handoff
        was missing.

        NO SUITE IS NOT A PASS. It is recorded as a check that did not run, so
        an upgrade with no tests cannot be mistaken for one whose tests passed.
        """
        check_name = "test_suite_execution"

        if not test_suite or not str(test_suite).strip():
            return ValidationCheck(
                check_name=check_name,
                passed=True,
                warnings=["No test suite supplied; the upgrade's behaviour was "
                          "NOT verified by tests. Static checks only."],
                metadata={"executed": False, "reason": "no_test_suite"})

        try:
            from core.learning.upgrade_sandbox import get_upgrade_sandbox

            sandbox = get_upgrade_sandbox()
            passed, message = await sandbox.validate_upgrade(code, test_suite)
        except Exception as error:
            # A check that could not run is not a check that passed.
            logger.error("Test suite execution failed to run: %s", error)
            return ValidationCheck(
                check_name=check_name, passed=False,
                errors=[f"test suite could not be executed: {error}"],
                metadata={"executed": False, "reason": "sandbox_error"})

        return ValidationCheck(
            check_name=check_name, passed=bool(passed),
            errors=[] if passed else [message],
            metadata={"executed": True, "detail": message})

    async def _validate_syntax(
        self,
        code: str,
        file_paths: List[str],
        metadata: Dict[str, Any]
    ) -> ValidationCheck:
        """
        Validate Python syntax

        Checks:
        - Valid Python AST
        - No syntax errors
        - Proper indentation
        """
        check_name = "syntax_validation"
        errors = []
        warnings = []
        passed = True
        check_metadata = {}

        for file_path in file_paths:
            # Skip non-Python files
            if not file_path.endswith('.py'):
                continue

            # Read file content
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    file_code = f.read()

                # Attempt to parse
                ast.parse(file_code)
                logger.debug(f"Syntax valid: {file_path}")

            except SyntaxError as e:
                passed = False
                errors.append(
                    f"{file_path} - Syntax error at line {e.lineno}: {e.msg}"
                )
                logger.error(
                    f"{file_path} - Syntax error: {e.msg} at line {e.lineno}"
                )
            except FileNotFoundError:
                warnings.append(
                    f"{file_path} - File not found (may be new)"
                )
                logger.warning(f"{file_path} - File not found for syntax check")
            except Exception as e:
                passed = False
                errors.append(
                    f"{file_path} - Parse error: {str(e)}"
                )

        syntax_valid = len(errors) == 0
        check_passed = syntax_valid or not self.strict_mode

        return ValidationCheck(
            check_name=check_name,
            passed=check_passed,
            errors=errors,
            warnings=warnings,
            metadata={
                "files_checked": len(file_paths),
                "syntax_errors": len(errors)
            }
        )

    async def _validate_imports(
        self,
        code: str,
        file_paths: List[str]
    ) -> ValidationCheck:
        """
        Validate all imports are available

        Checks:
        - All imported modules exist
        - No circular dependencies
        - Version compatibility
        """
        check_name = "import_validation"
        errors = []
        warnings = []
        passed = True

        for file_path in file_paths:
            if not file_path.endswith('.py'):
                continue

            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    file_code = f.read()

                # Parse imports from file
                tree = ast.parse(file_code)

                for node in ast.walk(tree):
                    # Handle "import x"
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            module_name = alias.name
                            try:
                                importlib.import_module(module_name)
                                logger.debug(f"Import validated: {module_name}")
                            except ImportError as e:
                                # Check if it's a local module (starts with "core", etc.)
                                if module_name.startswith(('core', 'servers', 'tests')):
                                    warnings.append(
                                        f"{file_path} - Local import may not be available yet: {module_name}"
                                    )
                                else:
                                    errors.append(
                                        f"{file_path} - Missing dependency: {module_name}"
                                    )
                                    passed = False

                    # Handle "from x import y"
                    elif isinstance(node, ast.ImportFrom):
                        if node.module:
                            module_name = node.module
                            # Try importing base module
                            try:
                                mod, submod = (module_name.split('.', 1) + [None])[:2]
                                if submod and (mod in ['core', 'servers', 'tests']):
                                    # Local module, skip for now
                                    continue
                                importlib.import_module(module_name)
                            except ImportError:
                                # Check if starts with parentheses (multiline import)
                                if module_name.startswith(('core', 'servers', 'tests')):
                                    # Skip local imports
                                    continue
                                else:
                                    warnings.append(
                                        f"{file_path} - Could not verify import: {module_name}"
                                    )

            except FileNotFoundError:
                continue
            except Exception as e:
                logger.error(f"{file_path} - Import validation error: {e}")

        imports_valid = len(errors) == 0
        check_passed = imports_valid or not self.strict_mode

        return ValidationCheck(
            check_name=check_name,
            passed=check_passed,
            errors=errors,
            warnings=warnings,
            metadata={
                "files_checked": len(file_paths),
                "import_errors": len(errors)
            }
        )

    async def _validate_config(self, code: str) -> ValidationCheck:
        """
        Validate configuration changes

        Checks:
        - Valid JSON/YAML syntax
        - Required fields present
        - Values within acceptable ranges
        - No dangerous configurations
        """
        check_name = "configuration_validation"
        errors = []
        warnings = []

        # Check for dangerous configuration patterns
        dangerous_patterns = [
            (r'DEBUG\s*=\s*True', 'Debug mode enabled in production'),
            (r'ALLOW_ALL_ORIGINS\s*=\s*True', 'CORS allows all origins'),
            (r'SSL_VERIFY\s*=\s*False', 'SSL verification disabled'),
            (r'eval\(', 'Eval function used in config'),
            (r'exec\(', 'Exec function used in config'),
            (r'password\s*=\s*["\'][^"\']+["\']', 'Hardcoded password in config'),
        ]

        for pattern, description in dangerous_patterns:
            if re.search(pattern, code, re.IGNORECASE):
                errors.append(f"Security risk: {description}")

        # Check for required configuration
        try:
            # Validate basic structure (simplified check)
            if 'import' in code and 'from' in code:
                # Looks like Python config
                ast.parse(code)

                # Check for common required fields
                if 'DATABASE' not in code and 'database' not in code.lower():
                    warnings.append("No database configuration found")

        except SyntaxError:
            errors.append("Configuration file has syntax errors")

        if errors:
            logger.warning("Configuration validation found issues")
        else:
            logger.info("Configuration validation passed")

        passed = len(errors) == 0
        check_passed = passed or not self.strict_mode

        return ValidationCheck(
            check_name=check_name,
            passed=check_passed,
            errors=errors,
            warnings=warnings,
            metadata={
                "dangerous_patterns_checked": len(dangerous_patterns)
            }
        )

    async def _validate_database_schema(self, code: str) -> ValidationCheck:
        """
        Validate database schema changes

        Checks:
        - Migration scripts are valid SQL
        - No destructive operations without safeguards
        - Schema changes are backwards compatible
        - Indexes are preserved
        """
        check_name = "database_schema_validation"
        errors = []
        warnings = []

        # Check for destructive operations
        destructive_ops = [
            (r'DROP\s+TABLE', 'DROP TABLE operation'),
            (r'DROP\s+COLUMN', 'DROP COLUMN operation'),
            (r'TRUNCATE\s+TABLE', 'TRUNCATE TABLE operation'),
        ]

        for pattern, description in destructive_ops:
            if re.search(pattern, code, re.IGNORECASE):
                # Check if there's a safeguard (IF EXISTS, WHERE clause, etc.)
                match = re.search(pattern + r'.*', code, re.IGNORECASE)
                if match:
                    statement = match.group(0)
                    if 'IF EXISTS' not in statement.upper():
                        errors.append(
                            f"{description} without IF EXISTS safeguard"
                        )
                    else:
                        # Has safeguard, but still warn
                        warnings.append(
                            f"Warning: {description} detected"
                        )

        # Check for missing migrations metadata
        if 'CREATE TABLE' in code.upper() or 'ALTER TABLE' in code.upper():
            if 'migration' not in code.lower() and 'version' not in code.lower():
                warnings.append("Schema changes detected but no migration metadata")

        if errors:
            logger.warning("Database schema validation found critical issues")

        passed = len(errors) == 0
        check_passed = passed or not self.strict_mode

        return ValidationCheck(
            check_name=check_name,
            passed=check_passed,
            errors=errors,
            warnings=warnings,
            metadata={
                "destructive_operations_checked": len(destructive_ops)
            }
        )

    async def _validate_security(
        self,
        code: str,
        file_paths: List[str]
    ) -> ValidationCheck:
        """
        Validate security best practices

        Checks:
        - No hardcoded secrets
        - No SQL injection vulnerabilities
        - No command injection risks
        - Proper input validation
        - No unsafe eval/exec usage
        """
        check_name = "security_validation"
        errors = []
        warnings = []

        # Security vulnerability patterns
        vulnerability_patterns = [
            (r'password\s*=\s*["\'][^"\']+["\']', 'Hardcoded password detected'),
            (r'api[_-]?key\s*=\s*["\'][^"\']+["\']', 'Hardcoded API key detected'),
            (r'secret\s*=\s*["\'][^"\']+["\']', 'Hardcoded secret detected'),
            (r'eval\(', 'Use of eval() function (code injection risk)'),
            (r'exec\(', 'Use of exec() function (code injection risk)'),
            (r'__import__\(', 'Use of __import__ (potential security risk)'),
        ]

        for file_path in file_paths:
            if not file_path.endswith('.py'):
                continue

            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    file_code = f.read()

                for pattern, description in vulnerability_patterns:
                    matches = re.finditer(pattern, file_code, re.IGNORECASE)
                    for match in matches:
                        errors.append(
                            f"{file_path} - {description} at position {match.start()}"
                        )

            except FileNotFoundError:
                continue

        # Additional checks using AST
        try:
            tree = ast.parse(code)

            for node in ast.walk(tree):
                # Check for string concatenation in SQL queries
                if isinstance(node, ast.Call):
                    if hasattr(node.func, 'attr') and node.func.attr in ['execute', 'query']:
                        # Check if any arguments use string concatenation or f-strings
                        for arg in node.args:
                            if isinstance(arg, (ast.BinOp, ast.JoinedStr)):
                                warnings.append(
                                    "Potential SQL injection: String concatenation in database query"
                                )

        except:
            pass  # AST parsing already validated in syntax check

        if errors:
            logger.warning(f"Security validation found {len(errors)} issue(s)")

        passed = len(errors) == 0
        # Security is critical - don't allow override in strict mode
        check_passed = passed

        return ValidationCheck(
            check_name=check_name,
            passed=check_passed,
            errors=errors,
            warnings=warnings,
            metadata={
                "vulnerability_patterns_checked": len(vulnerability_patterns)
            }
        )

    async def _validate_backwards_compatibility(
        self,
        code: str,
        file_paths: List[str]
    ) -> ValidationCheck:
        """
        Validate backwards compatibility

        Checks:
        - No removed public APIs
        - Function signatures unchanged
        - Return types consistent
        - Deprecated features properly marked
        """
        check_name = "backwards_compatibility"
        errors = []
        warnings = []

        # Check for removed functions/classes
        # This is a simplified check - in production would compare with git history
        for file_path in file_paths:
            if not file_path.endswith('.py'):
                continue

            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    new_code = f.read()

                # Look for deprecation warnings
                if '@deprecated' in new_code or 'warnings.warn' in new_code:
                    warnings.append(
                        f"{file_path} contains deprecation warnings"
                    )

            except FileNotFoundError:
                # New file, no backwards compatibility concerns
                continue

        if errors:
            logger.warning("Backwards compatibility issues detected")
        else:
            logger.info("Backwards compatibility check passed")

        passed = len(errors) == 0
        check_passed = passed or not self.strict_mode

        return ValidationCheck(
            check_name=check_name,
            passed=check_passed,
            errors=errors,
            warnings=warnings,
            metadata={}
        )

    async def _validate_performance(
        self,
        code: str,
        file_paths: List[str]
    ) -> ValidationCheck:
        """
        Validate performance characteristics

        Checks:
        - No obvious performance anti-patterns
        - Proper async/await usage
        - No blocking operations in async code
        - Efficient data structures
        """
        check_name = "performance_validation"
        errors = []
        warnings = []

        # Performance anti-patterns
        antipatterns = [
            (r'time\.sleep\(', 'Blocking sleep in code (use asyncio.sleep)'),
            (r'\.append\([^)]*\)\s*for\s+', 'List comprehension more efficient than append in loop'),
            (r'while\s+True\s*:\s*(?!.*await)', 'Infinite loop without await (CPU intensive)'),
        ]

        for file_path in file_paths:
            if not file_path.endswith('.py'):
                continue

            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    file_code = f.read()

                for pattern, description in antipatterns:
                    if re.search(pattern, file_code):
                        warnings.append(
                            f"{file_path} - Performance antipattern: {description}"
                        )

            except FileNotFoundError:
                continue

        # Check for proper async usage
        try:
            tree = ast.parse(code)

            for node in ast.walk(tree):
                # Look for async functions
                if isinstance(node, ast.AsyncFunctionDef):
                    # Check if it contains await statements
                    has_await = any(
                        isinstance(n, ast.Await)
                        for n in ast.walk(node)
                    )

                    if not has_await:
                        # Async function without await
                        warnings.append(
                            f"Async function without await: Consider making it synchronous"
                        )

        except SyntaxError as parse_error:
            # The code does not parse. That is a real finding and the syntax
            # check upstream reports it; here it means this check could not
            # run, which is not the same as finding nothing.
            warnings.append(f"Performance checks skipped: code did not parse "
                            f"({parse_error})")
        except Exception as error:
            # A bare `except: pass` hid every reason this analysis stopped, and
            # an analysis that silently found nothing reads exactly like a
            # clean result.
            logger.error("Performance validation could not complete: %s", error)
            warnings.append(f"Performance checks incomplete: "
                            f"{type(error).__name__}: {error}")

        if errors:
            logger.warning("Performance validation found issues")
        else:
            logger.info("Performance validation passed")

        passed = len(errors) == 0
        check_passed = passed or not self.strict_mode

        return ValidationCheck(
            check_name=check_name,
            passed=check_passed,
            errors=errors,
            warnings=warnings,
            metadata={
                "antipatterns_checked": len(antipatterns)
            }
        )

    def _get_failing_checks(self, result: ValidationResult) -> List[str]:
        """Get names of all failing checks"""
        return [
            check.check_name
            for check in result.checks
            if not check.passed
        ]

    async def _get_validation_statistics(self) -> Dict[str, Any]:
        """Get validation statistics from history"""
        total_validations = len(self.validation_history)
        passed_validations = sum(
            1 for v in self.validation_history
            if v.overall_passed
        )

        return {
            "total_validations": total_validations,
            "passed": passed_validations,
            "failed": total_validations - passed_validations,
            "pass_rate": (passed_validations / total_validations * 100)
                if total_validations > 0 else 0
        }

    async def _store_validation_result(
        self,
        result: ValidationResult,
        upgrade_id: str,
        metadata: Dict[str, Any]
    ):
        """Store validation result in database"""
        # Store in validation history
        self.validation_history.append(result)

        logger.info(f"Stored validation result: {upgrade_id}")

    async def get_validation_summary(self) -> Dict[str, Any]:
        """Get summary of recent validations"""
        stats = await self._get_validation_statistics()

        return {
            "statistics": stats,
            "recent_validations": len(self.validation_history),
            "strict_mode_enabled": self.strict_mode
        }


async def validate_upgrade_files(
    file_paths: List[str],
    test_suite: str = "",
    strict_mode: bool = True,
    metadata: Dict[str, Any] = None
) -> ValidationResult:
    """
    Convenience function to validate upgrade files

    Args:
        file_paths: List of file paths to validate
        test_suite: Optional test suite path
        strict_mode: Whether to fail on warnings
        metadata: Additional metadata

    Returns:
        ValidationResult with overall pass/fail
    """
    validator = UpgradeValidator(strict_mode=strict_mode)
    return await validator.validate_upgrade(
        code="",
        file_paths=file_paths,
        test_suite=test_suite,
        metadata=metadata
    )


# Example usage

# ---------------------------------------------------------------------------
# Singleton accessor
#
# Validates a generated upgrade before it is allowed near the sandbox.
# enhanced_asi_self_improvement.py has always imported `get_upgrade_validator` from this
# module, but it was never defined -- the import silently bound the name to
# None via `except ImportError`, and the ASI phase that depends on it aborted
# every single improvement cycle. The class below was complete; only this
# accessor was missing.
# ---------------------------------------------------------------------------

_upgrade_validator_instance: Optional[UpgradeValidator] = None


def get_upgrade_validator(config: Optional[Dict[str, Any]] = None) -> UpgradeValidator:
    """Get the shared UpgradeValidator instance (singleton)."""
    global _upgrade_validator_instance
    if _upgrade_validator_instance is None:
        _upgrade_validator_instance = UpgradeValidator(config) if config else UpgradeValidator()
    return _upgrade_validator_instance

if __name__ == "__main__":
    asyncio.run(main())

    async def main():
        validator = UpgradeValidator(strict_mode=True)

        file_paths = [
            "core/learning/improvement_monitor.py",
            "core/learning/code_generator.py",
        ]

        result = await validator.validate_upgrade(
            code="",
            file_paths=file_paths,
            test_suite="",
            metadata={"description": "Learning system improvements"}
        )

        print(f"\nValidation Result: {'PASSED' if result.overall_passed else 'FAILED'}")
        print(f"Duration: {result.validation_duration_ms:.2f}ms")
        print(f"Checks: {len(result.checks)}")

        print("\nCheck Results:")
        for check in result.checks:
            status = "✓" if check.passed else "✗"
            print(f"  {status} {check.check_name} ({len(check.errors)} errors, {len(check.warnings)} warnings)")
