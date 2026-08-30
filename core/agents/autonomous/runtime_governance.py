#!/usr/bin/env python3
"""
Runtime Governance

Real-time governance policy enforcement during execution:
- Monitors runtime execution
- Detects policy violations in real-time
- Emergency halt for critical violations
- Checkpoint-based enforcement
"""

import logging
import json
import sys
import hashlib
import importlib
import inspect
import asyncio
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .governance_agent import GovernanceAgent, ViolationSeverity
from .singleton_constitution import SingletonConstitution

from core.governance.critical_modules import (
    CRITICAL_MODULES as _CRITICAL_MODULES)

logger = logging.getLogger(__name__)


class EnforcementAction(Enum):
    """Actions taken by runtime governance"""
    ALLOW = "allow"  # Allow execution to continue
    WARN = "warn"  # Log warning, allow execution
    SLOW = "slow"  # Rate-limit execution
    BLOCK = "block"  # Block current operation
    HALT = "halt"  # Emergency halt - stop all execution


@dataclass
class RuntimeViolation:
    """Runtime governance violation detected during execution"""
    violation_id: str
    action_id: str
    violation_type: str  # resource_limit, rate_limit, policy_violation, etc.
    severity: ViolationSeverity
    details: str
    enforcement_action: EnforcementAction
    detected_at: datetime = field(default_factory=datetime.now)
    metrics: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EnforcementCheckpoint:
    """Checkpoint for governance policy enforcement"""
    checkpoint_id: str
    action_id: str
    checkpoint_type: str  # pre_execution, mid_execution, post_execution
    policies_checked: List[str]
    violations_detected: List[RuntimeViolation]
    passed: bool
    checked_at: datetime = field(default_factory=datetime.now)


#: Marks the fingerprint format. A baseline stored by an older version held
#: `str(value)[:200]`, which cannot be compared against these -- every
#: attribute would look changed. Entries without this prefix are treated as
#: stale and re-captured instead of compared, so upgrading does not produce a
#: storm of false violations.
_FINGERPRINT_VERSION = "fp1"


def attribute_fingerprint(value: Any) -> str:
    """A stable, JSON-safe identity for a module attribute.

    WHY NOT `str(value)[:200]`, WHICH IS WHAT THIS REPLACES. The baseline was
    stored as a truncated string and the verifier then asked
    `if callable(original_value)` before comparing -- but a string is never
    callable, so the `function_replaced` branch could not execute. Monkey-patch
    detection was structurally incapable of firing: replacing a module function
    with a lambda produced zero violations. Verified by patching
    `meta_learning.get_meta_learner` and `TaskFamily` on a live instance.

    `str()` could not have worked anyway -- a function's repr contains its
    memory address, so it changes across processes, and the baseline is
    persisted to `governance_module_state` and reloaded in a later one.

    A function is identified by qualname plus a hash of its compiled bytecode,
    both stable across runs and both changing when the function is replaced.
    """
    try:
        if inspect.isfunction(value) or inspect.ismethod(value):
            code = getattr(value, "__code__", None)
            digest = (hashlib.sha256(code.co_code).hexdigest()[:16]
                      if code is not None else "nocode")
            return (f"{_FINGERPRINT_VERSION}:function:"
                    f"{getattr(value, '__module__', '?')}."
                    f"{getattr(value, '__qualname__', '?')}:{digest}")
        if inspect.isclass(value):
            return (f"{_FINGERPRINT_VERSION}:class:"
                    f"{value.__module__}.{value.__qualname__}")
        if inspect.isroutine(value):        # builtins, C functions
            return (f"{_FINGERPRINT_VERSION}:routine:"
                    f"{getattr(value, '__module__', '?')}."
                    f"{getattr(value, '__qualname__', repr(value))}")
        if inspect.ismodule(value):
            return f"{_FINGERPRINT_VERSION}:module:{value.__name__}"
        if value is None or isinstance(value, (bool, int, float, str, bytes)):
            # Scalars are constants like STRICT_MODEL_FREE; flipping one is a
            # real event, so the value itself is part of the identity.
            return f"{_FINGERPRINT_VERSION}:value:{type(value).__name__}:{repr(value)[:150]}"
        # Containers and instances hold state that legitimately changes. Only
        # the TYPE is fixed, so swapping a dict for a function is caught while
        # ordinary mutation is not reported.
        return (f"{_FINGERPRINT_VERSION}:object:"
                f"{type(value).__module__}.{type(value).__name__}")
    except Exception:
        return f"{_FINGERPRINT_VERSION}:unfingerprintable"


#: Fingerprint kinds whose replacement is a security event rather than
#: ordinary state change.
_EXECUTABLE_KINDS = ("function", "class", "routine")


class RuntimeGovernance:
    """
    Runtime Governance Enforcement

    Monitors and enforces governance policies during execution:

    Enforcement Points:
    1. Pre-execution checks (before action starts)
    2. Mid-execution monitoring (during action execution)
    3. Post-execution validation (after action completes)

    Policies Enforced:
    - Resource limits (memory, CPU, time)
    - Rate limits (actions per minute)
    - Constitutional compliance (5 governance laws)
    - Safety constraints (no harm, transparency)
    - Runtime mutation protection (module freezing, integrity verification)

    Actions:
    - ALLOW: Continue execution
    - WARN: Log warning
    - SLOW: Rate-limit
    - BLOCK: Stop current operation
    - HALT: Emergency stop all execution
    """

    # 🛡️ CRITICAL MODULES: Protected from runtime mutation (monkey-patching, sys.modules replacement)
    #: Owned by core.governance.critical_modules -- this was a duplicate
    #: 14-entry literal that could drift from the detector's copy.
    CRITICAL_MODULES = sorted(_CRITICAL_MODULES)

    # 🛡️ CRITICAL CONFIG FILES: Protected from tampering (file hash verification)
    # Paths are relative to the project root (4 levels up from this file's directory).
    CRITICAL_CONFIG_FILES = [
        "config/governance_triggers.json",
    ]

    def __init__(
        self,
        governance_agent: Optional[GovernanceAgent] = None,
        constitution: Optional[SingletonConstitution] = None,
        enable_emergency_halt: bool = True
    ):
        """
        Initialize runtime governance

        Args:
            governance_agent: Governance agent for compliance checks
            constitution: Constitution for law enforcement
            enable_emergency_halt: Enable emergency halt capability
        """
        self.governance_agent = governance_agent or GovernanceAgent()
        self.constitution = constitution or SingletonConstitution()
        self.enable_emergency_halt = enable_emergency_halt

        # Execution state
        self.active_actions: Dict[str, Dict[str, Any]] = {}  # action_id -> state
        self.halted = False
        self.halt_reason: Optional[str] = None

        # Runtime violations
        self.violations: List[RuntimeViolation] = []
        self.checkpoints: List[EnforcementCheckpoint] = []

        # Resource limits
        self.resource_limits = {
            'max_concurrent_actions': 50,  # Increased from 10 - was blocking legitimate autonomous actions
            'max_execution_time_seconds': 300,  # 5 minutes
            'max_memory_mb': 1024,
            'rate_limit_per_minute': 120  # Increased from 60 - Singleton thinks frequently
        }

        # Rate limiting
        self.action_timestamps: List[datetime] = []

        # Metrics
        self.metrics = {
            'total_checkpoints': 0,
            'passed_checkpoints': 0,
            'failed_checkpoints': 0,
            'violations_detected': 0,
            'emergency_halts': 0,
            'actions_blocked': 0,
            'actions_slowed': 0,
            'runtime_mutations_detected': 0,
            'integrity_checks_performed': 0
        }

        # Runtime mutation protection
        self._frozen_modules: Dict[str, bool] = {}
        self._original_file_hashes: Dict[str, str] = {}
        self._original_module_attrs: Dict[str, Dict[str, Any]] = {}
        self._runtime_protection_enabled = False

        # Config file integrity hashes (keyed by relative path string)
        self._config_file_hashes: Dict[str, str] = {}
        # Project root: 4 levels up from this file
        self._project_root = Path(__file__).resolve().parent.parent.parent.parent

        # Database for persistence
        self.db = None
        self._db_initialized = False
        #: Whether the tamper-detection baseline actually loaded.
        #: Read this before trusting any integrity verdict.
        self.baseline_loaded = False

        logger.info(
            f"Runtime governance initialized "
            f"(emergency_halt: {enable_emergency_halt})"
        )

    async def initialize(self) -> bool:
        """Initialize database and load persisted state"""
        if self._db_initialized:
            return True

        try:
            # Initialize database
            from core.database import TorinUnifiedDatabase
            self.db = TorinUnifiedDatabase()
            await self.db.initialize()
            logger.info("Runtime governance database connected")

            # Load persisted state
            self._frozen_modules = await self._load_frozen_modules_from_db()
            self._original_file_hashes = await self._load_file_hashes_from_db()
            self._original_module_attrs = await self._load_module_attrs_from_db()

            logger.info(f"Loaded {len(self._frozen_modules)} frozen modules from database")

            self._db_initialized = True
            self.baseline_loaded = True
            return True

        except Exception as e:
            # NOT "non-critical". What failed to load is the tamper-detection
            # BASELINE: frozen modules, original file hashes, original module
            # attributes. Without it verify_runtime_integrity() has nothing to
            # compare against, so returning True told every caller that runtime
            # protection was armed when it could not detect anything.
            #
            # The object still works in a degraded mode, so this does not raise
            # -- it reports the mode instead of hiding it.
            logger.error(
                "Runtime governance has NO integrity baseline (database "
                "unavailable: %s). Tamper detection cannot report drift until "
                "the baseline loads.", e)
            self.db = None
            self._db_initialized = False
            self.baseline_loaded = False
            return False

    def _calculate_file_hash(self, file_path: Path) -> Optional[str]:
        """Calculate SHA-256 hash of file contents"""
        try:
            if not file_path.exists():
                return None

            with open(file_path, 'rb') as f:
                return hashlib.sha256(f.read()).hexdigest()
        except Exception as e:
            logger.warning(f"Failed to hash {file_path}: {e}")
            return None

    async def _freeze_module(self, module_name: str) -> bool:
        """
        Freeze module to prevent runtime mutation

        Creates read-only proxy of module's __dict__ to prevent attribute modification.

        Args:
            module_name: Full module name (e.g., 'core.learning.meta_learning')

        Returns:
            True if frozen successfully
        """
        if module_name in self._frozen_modules:
            return True

        if module_name not in sys.modules:
            # IMPORT IT RATHER THAN SKIP IT.
            #
            # This returned False whenever a critical module happened not to be
            # imported yet, and the only trace was a debug line. Measured: 3 of
            # the 14 declared-critical modules were unprotected at runtime --
            # including `core.security.safety_framework`, the main safety
            # module. Protection silently covered whatever the process had
            # loaded, which is not a security boundary.
            #
            # A module on this list is one the system has declared it depends
            # on for its own safety, so importing it to establish a baseline is
            # the intent, not a side effect.
            try:
                importlib.import_module(module_name)
                logger.info("Imported %s to establish its integrity baseline",
                            module_name)
            except Exception as import_error:
                # A declared-critical module that cannot be imported is a real
                # problem, not a debug detail: nothing will ever detect it
                # being tampered with.
                logger.error(
                    "CRITICAL MODULE UNPROTECTED: %s could not be imported "
                    "(%s); no integrity baseline exists for it",
                    module_name, import_error)
                return False

        try:
            module = sys.modules[module_name]

            # Store original attributes for integrity checking
            original_attrs = {
                attr: attribute_fingerprint(getattr(module, attr, None))
                for attr in dir(module)
                if not attr.startswith('_')
            }
            self._original_module_attrs[module_name] = original_attrs

            # Calculate hash of source file
            file_hash = None
            file_path = None
            if hasattr(module, '__file__') and module.__file__:
                source_path = Path(module.__file__)
                file_hash = self._calculate_file_hash(source_path)
                file_path = str(source_path)
                if file_hash:
                    self._original_file_hashes[module_name] = file_hash

            # Mark as frozen (protection via integrity verification, not dict freezing)
            # Note: Can't actually make module.__dict__ read-only (Python limitation)
            # Protection works by storing baseline state and detecting mutations via verify_runtime_integrity()
            self._frozen_modules[module_name] = True

            # Store to database
            await self._store_module_state_to_db(
                module_name=module_name,
                is_frozen=True,
                file_hash=file_hash,
                file_path=file_path,
                original_attrs=original_attrs
            )

            logger.debug(f"🔒 Froze module: {module_name}")
            return True

        except Exception as e:
            logger.error(f"Failed to freeze module {module_name}: {e}")
            return False

    async def enable_runtime_protection(self) -> Dict[str, Any]:
        """
        Enable runtime mutation protection for all critical modules

        Should be called during system initialization after all modules loaded.

        Returns:
            Dict with protection status
        """
        logger.info("🛡️  Enabling runtime mutation protection...")

        frozen_count = 0
        failed_modules = []

        for module_name in self.CRITICAL_MODULES:
            if await self._freeze_module(module_name):
                frozen_count += 1
            else:
                failed_modules.append(module_name)

        # Hash critical config files
        hashed_configs = []
        failed_configs = []
        for rel_path in self.CRITICAL_CONFIG_FILES:
            abs_path = self._project_root / rel_path
            h = self._calculate_file_hash(abs_path)
            if h:
                self._config_file_hashes[rel_path] = h
                hashed_configs.append(rel_path)
                logger.debug(f"🔒 Config file hash stored: {rel_path}")
            else:
                failed_configs.append(rel_path)
                logger.warning(f"⚠️  Could not hash config file: {abs_path}")

        self._runtime_protection_enabled = True

        status = {
            'enabled': True,
            'frozen_modules': frozen_count,
            'total_critical_modules': len(self.CRITICAL_MODULES),
            'failed_modules': failed_modules,
            'file_hashes_stored': len(self._original_file_hashes),
            'config_files_hashed': hashed_configs,
            'config_files_failed': failed_configs,
        }

        logger.info(
            f"✅ Runtime protection enabled: {frozen_count}/{len(self.CRITICAL_MODULES)} modules frozen, "
            f"{len(hashed_configs)}/{len(self.CRITICAL_CONFIG_FILES)} config files hash-protected"
        )

        if failed_modules:
            logger.warning(f"⚠️  Failed to freeze {len(failed_modules)} modules: {failed_modules}")

        return status

    async def verify_runtime_integrity(self) -> Dict[str, Any]:
        """
        Verify runtime integrity of critical modules

        Checks for:
        - sys.modules replacement (module swap attacks)
        - Attribute modification (monkey-patching)
        - Source file modification (file tampering)

        Returns:
            Dict with integrity status and violations detected
        """
        if not self._runtime_protection_enabled:
            logger.warning("Runtime protection not enabled, cannot verify integrity")
            return {'error': 'protection_not_enabled'}

        self.metrics['integrity_checks_performed'] += 1
        violations = []

        logger.debug("🔍 Verifying runtime integrity...")

        for module_name in self.CRITICAL_MODULES:
            # CHECK 1: Module still in sys.modules (not replaced)
            if module_name in self._frozen_modules:
                if module_name not in sys.modules:
                    violations.append({
                        'type': 'module_removed',
                        'module': module_name,
                        'severity': 'CRITICAL',
                        'details': 'Module removed from sys.modules (possible replacement attack)'
                    })
                    continue

                module = sys.modules[module_name]

                # CHECK 2: Attribute integrity (monkey-patching detection)
                if module_name in self._original_module_attrs:
                    original_attrs = self._original_module_attrs[module_name]

                    # A baseline written before fingerprinting cannot be
                    # compared against one written after it. Re-capture instead
                    # of reporting every attribute as changed.
                    stale = [v for v in original_attrs.values()
                             if not str(v).startswith(_FINGERPRINT_VERSION + ":")]
                    if stale:
                        logger.warning(
                            "Baseline for %s predates attribute fingerprinting "
                            "(%d entries); re-capturing rather than comparing",
                            module_name, len(stale))
                        self._original_module_attrs[module_name] = {
                            attr: attribute_fingerprint(getattr(module, attr, None))
                            for attr in dir(module) if not attr.startswith('_')}
                        continue

                    for attr_name, original_value in original_attrs.items():
                        if not hasattr(module, attr_name):
                            violations.append({
                                'type': 'attribute_removed',
                                'module': module_name,
                                'attribute': attr_name,
                                'severity': 'HIGH',
                                'details': f'Attribute {attr_name} removed from module'
                            })
                            continue

                        # COMPARE FINGERPRINTS, NOT OBJECT IDENTITY.
                        #
                        # This branch was `if callable(original_value)` against
                        # a stored *string*, so it never ran and monkey-patching
                        # went undetected entirely. Identity (`is`) could not
                        # work either: the baseline is reloaded from the
                        # database in a later process, where no original object
                        # survives to compare against.
                        current = attribute_fingerprint(getattr(module, attr_name))
                        if current == original_value:
                            continue

                        kind = str(original_value).split(":")[1] if ":" in str(original_value) else ""
                        if kind in _EXECUTABLE_KINDS:
                            violations.append({
                                'type': 'function_replaced',
                                'module': module_name,
                                'attribute': attr_name,
                                'severity': 'CRITICAL',
                                'details': (f'{kind} {attr_name} replaced '
                                            f'(monkey-patched): expected '
                                            f'{original_value}, found {current}')
                            })
                        elif kind == "value":
                            # A module-level constant changed -- STRICT_MODEL_FREE
                            # and friends live here, so this is reportable, but
                            # it is not the same as executable code being swapped.
                            violations.append({
                                'type': 'constant_changed',
                                'module': module_name,
                                'attribute': attr_name,
                                'severity': 'HIGH',
                                'details': (f'Module constant {attr_name} changed: '
                                            f'{original_value} -> {current}')
                            })

                # CHECK 3: Source file integrity (file tampering detection)
                if module_name in self._original_file_hashes:
                    if hasattr(module, '__file__') and module.__file__:
                        source_path = Path(module.__file__)
                        current_hash = self._calculate_file_hash(source_path)

                        if current_hash != self._original_file_hashes[module_name]:
                            violations.append({
                                'type': 'file_modified',
                                'module': module_name,
                                'file': str(source_path),
                                'severity': 'CRITICAL',
                                'details': 'Source file modified at runtime'
                            })

        # CHECK 4: Critical config file integrity
        for rel_path, original_hash in self._config_file_hashes.items():
            abs_path = self._project_root / rel_path
            current_hash = self._calculate_file_hash(abs_path)
            if current_hash is None:
                violations.append({
                    'type': 'config_file_missing',
                    'module': rel_path,
                    'file': str(abs_path),
                    'severity': 'CRITICAL',
                    'details': f'Critical config file missing or unreadable: {rel_path}'
                })
            elif current_hash != original_hash:
                violations.append({
                    'type': 'config_file_modified',
                    'module': rel_path,
                    'file': str(abs_path),
                    'severity': 'CRITICAL',
                    'details': f'Critical config file tampered at runtime: {rel_path}'
                })

        # Record violations
        if violations:
            self.metrics['runtime_mutations_detected'] += len(violations)

            for violation in violations:
                logger.error(
                    f"🚨 RUNTIME MUTATION DETECTED: {violation['type']} "
                    f"in {violation['module']} (severity: {violation['severity']})"
                )

                # Create runtime violation
                runtime_violation = RuntimeViolation(
                    violation_id=f"runtime_mutation_{violation['module']}_{datetime.now().timestamp()}",
                    action_id="runtime_integrity_check",
                    violation_type=violation['type'],
                    severity=ViolationSeverity.CRITICAL,
                    details=violation['details'],
                    enforcement_action=EnforcementAction.HALT,
                    metrics=violation
                )

                self.violations.append(runtime_violation)

            # CRITICAL violations trigger emergency halt
            critical_violations = [v for v in violations if v['severity'] == 'CRITICAL']
            if critical_violations:
                await self.emergency_halt(
                    f"Runtime mutation detected: {len(critical_violations)} critical violations"
                )

        integrity_status = {
            'verified': True,
            'violations_detected': len(violations),
            'violations': violations,
            'modules_checked': len(self.CRITICAL_MODULES),
            'integrity_ok': len(violations) == 0
        }

        if violations:
            logger.warning(f"⚠️  Integrity check FAILED: {len(violations)} violations")

            # Send Slack notification for governance violations
            try:
                from core.integration.slack_notifier import send_slack_notification
                asyncio.create_task(send_slack_notification({
                    "title": "⚠️ Governance Integrity Violation",
                    "message": f"**Violations:** {len(violations)} detected\n**Type:** Integrity check failure\n**Status:** System operating outside governance bounds",
                    "severity": "warning"
                }))
            except:
                pass
        else:
            logger.debug("✅ Integrity check PASSED: No mutations detected")

        return integrity_status

    async def pre_execution_check(
        self,
        action_id: str,
        action_description: str,
        action_params: Dict[str, Any],
        singleton_context: Optional[Dict[str, Any]] = None
    ) -> EnforcementCheckpoint:
        """
        Pre-execution governance checkpoint

        Checks BEFORE action execution:
        - Constitutional compliance
        - Resource availability
        - Rate limits
        - Concurrent action limits

        IMPORTANT CONTRACT: If this method returns a passing checkpoint, the caller
        MUST call clear_action(action_id) when the action completes (success or failure).
        Failure to do so will cause active_actions to leak and eventually block all
        future actions when max_concurrent_actions is reached.
        
        Use a try/finally pattern:
            checkpoint = await runtime_governance.pre_execution_check(action_id, ...)
            if checkpoint.passed:
                try:
                    await execute_action()
                finally:
                    runtime_governance.clear_action(action_id)

        Args:
            action_id: Action identifier
            action_description: What the action does
            action_params: Action parameters
            singleton_context: Singleton's reasoning

        Returns:
            EnforcementCheckpoint with pass/fail and violations
        """
        logger.debug(f"Pre-execution check for action {action_id}...")

        checkpoint_id = f"pre_{action_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        violations_detected = []
        policies_checked = []

        # Check 1: System not halted
        if self.halted:
            violations_detected.append(RuntimeViolation(
                violation_id=f"halt_{action_id}",
                action_id=action_id,
                violation_type="system_halted",
                severity=ViolationSeverity.CRITICAL,
                details=f"System halted: {self.halt_reason}",
                enforcement_action=EnforcementAction.BLOCK
            ))
            policies_checked.append("system_halt_check")

        # Check 2: Concurrent action limit (with stale action cleanup first)
        await self._cleanup_stale_actions()
        
        if len(self.active_actions) >= self.resource_limits['max_concurrent_actions']:
            violations_detected.append(RuntimeViolation(
                violation_id=f"concurrent_{action_id}",
                action_id=action_id,
                violation_type="concurrent_limit_exceeded",
                severity=ViolationSeverity.MEDIUM,
                details=f"Too many concurrent actions: {len(self.active_actions)}",
                enforcement_action=EnforcementAction.SLOW
            ))
            policies_checked.append("concurrent_action_limit")

        # Check 3: Rate limit
        now = datetime.now()
        recent_actions = [
            ts for ts in self.action_timestamps
            if (now - ts).total_seconds() < 60
        ]
        if len(recent_actions) >= self.resource_limits['rate_limit_per_minute']:
            violations_detected.append(RuntimeViolation(
                violation_id=f"rate_{action_id}",
                action_id=action_id,
                violation_type="rate_limit_exceeded",
                severity=ViolationSeverity.LOW,
                details=f"Rate limit exceeded: {len(recent_actions)}/min",
                enforcement_action=EnforcementAction.SLOW
            ))
            policies_checked.append("rate_limit")

        # Check 4: Constitutional compliance
        compliance_record = await self.governance_agent.check_action_compliance(
            action_id=action_id,
            action_description=action_description,
            action_params=action_params,
            singleton_context=singleton_context
        )
        policies_checked.append("constitutional_compliance")

        if compliance_record.requires_governance:
            violations_detected.append(RuntimeViolation(
                violation_id=f"compliance_{action_id}",
                action_id=action_id,
                violation_type="policy_violation",
                severity=ViolationSeverity.HIGH,
                details=f"Compliance violations: {', '.join(compliance_record.violations_detected)}",
                enforcement_action=EnforcementAction.BLOCK,
                metrics={'compliance_scores': compliance_record.compliance_scores}
            ))

        # Create checkpoint
        checkpoint = EnforcementCheckpoint(
            checkpoint_id=checkpoint_id,
            action_id=action_id,
            checkpoint_type="pre_execution",
            policies_checked=policies_checked,
            violations_detected=violations_detected,
            passed=len(violations_detected) == 0
        )

        # Store checkpoint
        self.checkpoints.append(checkpoint)

        # Update metrics
        self.metrics['total_checkpoints'] += 1
        if checkpoint.passed:
            self.metrics['passed_checkpoints'] += 1
        else:
            self.metrics['failed_checkpoints'] += 1
            self.metrics['violations_detected'] += len(violations_detected)

        # If passed, track action start
        if checkpoint.passed:
            self.active_actions[action_id] = {
                'started_at': datetime.now(),
                'description': action_description,
                'params': action_params
            }
            self.action_timestamps.append(datetime.now())

        logger.info(
            f"Pre-execution check {checkpoint_id}: "
            f"passed={checkpoint.passed}, violations={len(violations_detected)}"
        )

        return checkpoint

    async def mid_execution_monitor(
        self,
        action_id: str,
        current_state: Dict[str, Any]
    ) -> Optional[RuntimeViolation]:
        """
        Monitor action during execution

        Checks DURING action execution:
        - Execution time limit
        - Resource consumption
        - Unexpected behavior

        Args:
            action_id: Action identifier
            current_state: Current execution state

        Returns:
            RuntimeViolation if detected, None otherwise
        """
        if action_id not in self.active_actions:
            logger.warning(f"Action {action_id} not tracked in active actions")
            return None

        action_info = self.active_actions[action_id]
        elapsed = (datetime.now() - action_info['started_at']).total_seconds()

        # Check execution time limit
        if elapsed > self.resource_limits['max_execution_time_seconds']:
            violation = RuntimeViolation(
                violation_id=f"timeout_{action_id}",
                action_id=action_id,
                violation_type="execution_timeout",
                severity=ViolationSeverity.HIGH,
                details=f"Execution time exceeded: {elapsed:.1f}s",
                enforcement_action=EnforcementAction.HALT,
                metrics={'elapsed_seconds': elapsed}
            )

            self.violations.append(violation)
            self.metrics['violations_detected'] += 1

            logger.warning(
                f"Mid-execution violation detected for {action_id}: "
                f"timeout after {elapsed:.1f}s"
            )

            return violation

        return None

    async def post_execution_validate(
        self,
        action_id: str,
        result: Dict[str, Any]
    ) -> EnforcementCheckpoint:
        """
        Post-execution governance validation

        Checks AFTER action completes:
        - Result quality
        - Side effects
        - Resource cleanup

        Args:
            action_id: Action identifier
            result: Action execution result

        Returns:
            EnforcementCheckpoint with validation results
        """
        logger.debug(f"Post-execution validation for action {action_id}...")

        checkpoint_id = f"post_{action_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        violations_detected = []
        policies_checked = ["result_validation", "resource_cleanup"]

        # Check if action was tracked
        if action_id in self.active_actions:
            # Remove from active actions
            action_info = self.active_actions.pop(action_id)

            # Calculate execution duration
            duration = (datetime.now() - action_info['started_at']).total_seconds()

            # Check for failures
            if not result.get('success', False):
                error = result.get('error', 'Unknown error')
                violations_detected.append(RuntimeViolation(
                    violation_id=f"failure_{action_id}",
                    action_id=action_id,
                    violation_type="execution_failure",
                    severity=ViolationSeverity.MEDIUM,
                    details=f"Action failed: {error}",
                    enforcement_action=EnforcementAction.WARN,
                    metrics={'duration_seconds': duration}
                ))

        # Create checkpoint
        checkpoint = EnforcementCheckpoint(
            checkpoint_id=checkpoint_id,
            action_id=action_id,
            checkpoint_type="post_execution",
            policies_checked=policies_checked,
            violations_detected=violations_detected,
            passed=len(violations_detected) == 0
        )

        # Store checkpoint
        self.checkpoints.append(checkpoint)

        # Update metrics
        self.metrics['total_checkpoints'] += 1
        if checkpoint.passed:
            self.metrics['passed_checkpoints'] += 1
        else:
            self.metrics['failed_checkpoints'] += 1
            self.metrics['violations_detected'] += len(violations_detected)

        logger.info(
            f"Post-execution validation {checkpoint_id}: "
            f"passed={checkpoint.passed}"
        )

        return checkpoint

    async def _cleanup_stale_actions(self, max_age_seconds: int = 600) -> int:
        """
        Clean up actions that have been active for too long (likely stuck/leaked).
        
        Args:
            max_age_seconds: Maximum age for an action before it's considered stale (default 10 minutes)
            
        Returns:
            Number of stale actions cleaned up
        """
        now = datetime.now()
        stale_action_ids = []
        
        for action_id, action_info in self.active_actions.items():
            started_at = action_info.get('started_at')
            if started_at and (now - started_at).total_seconds() > max_age_seconds:
                stale_action_ids.append(action_id)
        
        for action_id in stale_action_ids:
            logger.warning(f"🧹 Cleaning up stale action: {action_id} (exceeded {max_age_seconds}s)")
            self.active_actions.pop(action_id, None)
        
        if stale_action_ids:
            logger.warning(
                f"🧹 Cleaned up {len(stale_action_ids)} LEAKED actions from governance tracking. "
                f"This indicates a bug - some code path called pre_execution_check() but never "
                f"called clear_action(). Leaked action IDs: {stale_action_ids}"
            )
        
        return len(stale_action_ids)

    def clear_action(self, action_id: str) -> bool:
        """
        Explicitly clear an action from active tracking.
        Called when a task completes (success or failure).
        
        Args:
            action_id: The action ID to clear
            
        Returns:
            True if action was found and cleared, False otherwise
        """
        if action_id in self.active_actions:
            action_info = self.active_actions.pop(action_id)
            duration = (datetime.now() - action_info.get('started_at', datetime.now())).total_seconds()
            logger.debug(f"✓ Cleared action {action_id} from governance (ran {duration:.1f}s)")
            return True
        else:
            logger.debug(f"Action {action_id} not in active_actions (already cleared or never started)")
        return False

    async def emergency_halt(self, reason: str) -> None:
        """
        Emergency halt - stop all execution immediately

        Args:
            reason: Reason for emergency halt
        """
        if not self.enable_emergency_halt:
            logger.warning(f"Emergency halt disabled, ignoring halt request: {reason}")
            return

        self.halted = True
        self.halt_reason = reason
        self.metrics['emergency_halts'] += 1

        logger.critical(
            f"EMERGENCY HALT TRIGGERED: {reason}\n"
            f"All execution stopped. Active actions: {len(self.active_actions)}"
        )

        # Send critical alert to human via Slack
        try:
            from core.integration.slack_notifier import get_slack_notifier
            slack = get_slack_notifier()
            await slack.send_security_alert(
                alert_title="🚨 EMERGENCY HALT",
                alert_message=f"**Reason**: {reason}\n**Active actions**: {len(self.active_actions)}\n\nAll execution has been stopped immediately.",
                severity="CRITICAL",
                metadata={
                    'halt_reason': reason,
                    'active_actions': len(self.active_actions),
                    'timestamp': datetime.now().isoformat()
                }
            )
        except Exception as e:
            logger.error(f"Failed to send emergency alert: {e}")

        # Save state for recovery to unified PostgreSQL
        try:
            from core.database import get_database_manager
            db = get_database_manager()
            await db.execute_query(
                """
                INSERT INTO emergency_halts (
                    reason,
                    active_actions,
                    timestamp,
                    metadata
                ) VALUES ($1, $2, $3, $4)
                """,
                params=(
                    reason,
                    # active_actions is a TEXT column — store the ids, not a count
                    ",".join(sorted(self.active_actions.keys())),
                    datetime.now(),
                    # metadata is JSONB — must be valid JSON, not a Python repr
                    json.dumps(
                        {
                            "active_action_count": len(self.active_actions),
                            "active_action_ids": sorted(self.active_actions.keys()),
                        },
                        default=str,
                    ),
                ),
                commit=True,
            )
        except Exception as e:
            logger.error(f"Failed to persist emergency halt: {e}")

        # Report the halt to health monitoring. The halt itself is already in
        # effect — self.halted blocks every subsequent admission check — so this
        # is notification, not the mechanism.
        try:
            from core.health.recovery_manager import get_recovery_manager, FailureType
            await get_recovery_manager().handle_failure(
                failure_type=FailureType.COMPONENT_FAILURE,
                component="runtime_governance",
                description=f"Emergency halt engaged: {reason}",
                severity="critical",
                metadata={"active_actions": len(self.active_actions)},
            )
        except Exception as e:
            logger.error(f"Failed to report emergency halt to recovery manager: {e}")

    async def resume(self, authorized_by: str) -> bool:
        """
        Resume execution after halt

        Args:
            authorized_by: Who authorized the resume

        Returns:
            True if resumed successfully
        """
        if not self.halted:
            logger.warning("System not halted, cannot resume")
            return False

        logger.info(f"Resuming execution (authorized by: {authorized_by})")

        self.halted = False
        self.halt_reason = None

        return True

    def can_accept_action(self) -> Tuple[bool, str, str]:
        """Read-only capacity check: can the system take on an action right now?

        Unlike pre_execution_check() this registers nothing, so it carries no
        clear_action() obligation and cannot leak active_actions. Intended for
        SafetyFramework, which composes this into its single admission answer
        while runtime governance retains the pre/mid/post lifecycle.

        Returns:
            (accepted, reason, severity) — severity is 'critical' | 'medium' | 'low' | ''
        """
        if self.halted:
            return False, f"system halted: {self.halt_reason}", "critical"

        active = len(self.active_actions)
        if active >= self.resource_limits['max_concurrent_actions']:
            return False, f"concurrent action limit reached ({active})", "medium"

        now = datetime.now()
        recent = [ts for ts in self.action_timestamps
                  if (now - ts).total_seconds() < 60]
        if len(recent) >= self.resource_limits['rate_limit_per_minute']:
            return False, f"rate limit exceeded ({len(recent)}/min)", "low"

        return True, "", ""

    async def get_runtime_status(self) -> Dict[str, Any]:
        """Get current runtime governance status"""
        return {
            'halted': self.halted,
            'halt_reason': self.halt_reason,
            'active_actions': len(self.active_actions),
            'recent_violations': len([
                v for v in self.violations
                if (datetime.now() - v.detected_at).total_seconds() < 3600
            ]),
            'metrics': self.metrics.copy(),
            'resource_limits': self.resource_limits.copy(),
            'checkpoints_recent': len([
                c for c in self.checkpoints
                if (datetime.now() - c.checked_at).total_seconds() < 3600
            ])
        }

    async def get_active_actions(self) -> List[Dict[str, Any]]:
        """Get list of currently active actions"""
        now = datetime.now()
        return [
            {
                'action_id': action_id,
                'description': info['description'],
                'started_at': info['started_at'].isoformat(),
                'elapsed_seconds': (now - info['started_at']).total_seconds()
            }
            for action_id, info in self.active_actions.items()
        ]

    # =========================================================================
    # DATABASE PERSISTENCE METHODS
    # =========================================================================

    async def _ensure_governance_module_table(self) -> None:
        """Ensure governance_module_state table exists"""
        if not hasattr(self, 'db') or not self.db:
            return

        try:
            # Table is created centrally via postgres_schemas.sql; just sanity-check access.
            await self.db.execute_query(
                "SELECT 1 FROM governance_module_state LIMIT 1",
                fetch_one=True,
            )
        except Exception as e:
            logger.debug(f"Governance module table may already exist: {e}")

    async def _store_module_state_to_db(self, module_name: str, is_frozen: bool,
                                       file_hash: Optional[str] = None,
                                       file_path: Optional[str] = None,
                                       original_attrs: Optional[Dict[str, Any]] = None) -> None:
        """Store module state to database"""
        if not hasattr(self, 'db') or not self.db:
            return

        try:
            await self._ensure_governance_module_table()

            import json
            attrs_json = json.dumps(original_attrs) if original_attrs else None

            await self.db.execute_query(
                """
                INSERT INTO governance_module_state (
                    module_name,
                    is_frozen,
                    file_hash,
                    file_path,
                    original_attributes,
                    frozen_at,
                    last_verified
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, CURRENT_TIMESTAMP
                )
                ON CONFLICT (module_name) DO UPDATE SET
                    is_frozen = EXCLUDED.is_frozen,
                    file_hash = EXCLUDED.file_hash,
                    file_path = EXCLUDED.file_path,
                    original_attributes = EXCLUDED.original_attributes,
                    frozen_at = EXCLUDED.frozen_at,
                    last_verified = CURRENT_TIMESTAMP
                """,
                params=(
                    module_name,
                    is_frozen,
                    file_hash,
                    file_path,
                    attrs_json,
                    datetime.now() if is_frozen else None,
                ),
                commit=True,
            )

            logger.debug(f"Stored module state to DB: {module_name}")

        except Exception as e:
            logger.error(f"Failed to store module state: {e}")

    async def _load_frozen_modules_from_db(self) -> Dict[str, bool]:
        """Load frozen modules from database"""
        if not hasattr(self, 'db') or not self.db:
            return {}

        try:
            results = await self.db.execute_query(
                """
                SELECT module_name
                FROM governance_module_state
                WHERE is_frozen = TRUE
                """
            )

            return {row['module_name']: True for row in results}

        except Exception as e:
            logger.error(f"Failed to load frozen modules: {e}")
            return {}

    async def _load_file_hashes_from_db(self) -> Dict[str, str]:
        """Load file hashes from database"""
        if not hasattr(self, 'db') or not self.db:
            return {}

        try:
            results = await self.db.execute_query(
                """
                SELECT module_name, file_hash
                FROM governance_module_state
                WHERE file_hash IS NOT NULL
                """
            )

            return {row['module_name']: row['file_hash'] for row in results}

        except Exception as e:
            logger.error(f"Failed to load file hashes: {e}")
            return {}

    async def _load_module_attrs_from_db(self) -> Dict[str, Dict[str, Any]]:
        """Load original module attributes from database"""
        if not hasattr(self, 'db') or not self.db:
            return {}

        try:
            import json
            results = await self.db.execute_query(
                """
                SELECT module_name, original_attributes
                FROM governance_module_state
                WHERE original_attributes IS NOT NULL
                """
            )

            attrs_dict = {}
            for row in results:
                try:
                    attrs = json.loads(row['original_attributes']) if isinstance(row['original_attributes'], str) else row['original_attributes']
                    if attrs:
                        attrs_dict[row['module_name']] = attrs
                except Exception as parse_error:
                    logger.debug(f"Failed to parse module attrs: {parse_error}")
                    continue

            return attrs_dict

        except Exception as e:
            logger.error(f"Failed to load module attributes: {e}")
            return {}

    async def clear_old_violations(self, max_age_hours: int = 24) -> int:
        """
        Clear violations older than max_age_hours

        Args:
            max_age_hours: Maximum age in hours

        Returns:
            Number of violations cleared
        """
        now = datetime.now()
        initial_count = len(self.violations)

        self.violations = [
            v for v in self.violations
            if (now - v.detected_at).total_seconds() < (max_age_hours * 3600)
        ]

        cleared = initial_count - len(self.violations)

        if cleared > 0:
            logger.info(f"Cleared {cleared} old violations (older than {max_age_hours}h)")

        return cleared


# Singleton instance
_runtime_governance = None


def get_runtime_governance() -> RuntimeGovernance:
    """Get global runtime governance instance"""
    global _runtime_governance
    if _runtime_governance is None:
        _runtime_governance = RuntimeGovernance()
    return _runtime_governance
