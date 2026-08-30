#!/usr/bin/env python3
"""
Safety Framework

Multi-layered AI safety system for monitoring and enforcing safety constraints.
Proactive monitoring with compliance tracking and audit trails.

Architecture:
- System-level constraints (constitutional principles)
- Meta-level constraints (context-aware)
- Action-level constraints (task-specific)

Integration:
- Multi-level safety prompts for LLM guidance
- Commitment contracts for action verification
- Governance trigger system for escalation
- Audit logging for compliance
"""

import asyncio
import logging
import os
import re
import json
import time
import uuid
from typing import Dict, Any, List, Optional, Tuple, Set
from datetime import datetime
from dataclasses import dataclass, field
from enum import Enum

from core.safety.multi_level_prompts import (
    MultiLevelSafetyPrompts, SafetyLevel, verify_safety_prompt_compliance
)
from core.safety.commitment_contracts import (
    CommitmentContractManager, CommitmentType, ViolationSeverity
)

logger = logging.getLogger(__name__)


# Canonical risk taxonomy. Previously this module defined its own RiskLevel
# using MODERATE while core.tools.capabilities used MEDIUM, making the two
# incomparable. capabilities.RiskLevel wins on usage (291 sites vs 12) and has
# no core dependencies, so it is safe to import from anywhere.
from core.tools.capabilities import RiskLevel

# Back-compat: MODERATE was this module's name for MEDIUM.
MODERATE = RiskLevel.MEDIUM

# A governance rule's declared `safety_risk` mapped to a numeric score. When a
# rule matches it SETS the score — the rule is evidence about this specific
# invocation and outranks any static per-tool prior.
SAFETY_RISK_SCORE = {
    "LOW": 0.10,
    "MODERATE": 0.35,
    "MEDIUM": 0.35,
    "HIGH": 0.65,
    "CRITICAL": 0.90,
}

# Single source of truth for score → level. Used by both the prior path and the
# rule path so they cannot drift apart.
RISK_BANDS = ((0.7, RiskLevel.CRITICAL), (0.5, RiskLevel.HIGH), (0.3, RiskLevel.MEDIUM))


def risk_level_for_score(score: float) -> RiskLevel:
    for threshold, level in RISK_BANDS:
        if score >= threshold:
            return level
    return RiskLevel.LOW


class GovernanceBlockError(Exception):
    """Raised when governance enforcement mode is MUST_BLOCK."""
    def __init__(self, action_type: str, trigger: str, risk_score: float, reasoning: str = ""):
        self.action_type = action_type
        self.trigger = trigger
        self.risk_score = risk_score
        super().__init__(
            f"Governance BLOCK: action='{action_type}' trigger='{trigger}' "
            f"risk={risk_score:.3f} — {reasoning}"
        )


# GovernanceApprovalRequired lived here and was NEVER RAISED. It belonged to
# the retired governance-session model -- risk score crosses a threshold, the
# action is queued, judges vote, a human approves. That model is gone: the
# Singleton keeps tool autonomy and safety produces recorded signals rather
# than approval queues. Three `except` clauses were catching it, which read as
# a live approval path to anyone reviewing the code and could never fire.
@dataclass
class SafetyEvaluation:
    """Result of safety evaluation"""
    action_id: str
    safety_level: SafetyLevel
    risk_level: RiskLevel
    constraints_applicable: List[str]
    monitoring_required: bool
    approval_required: bool
    violations_detected: List[str] = field(default_factory=list)
    evaluated_at: datetime = field(default_factory=datetime.now)

    # WHAT WAS DETERMINED, not just how bad it scored.
    #
    # A risk level is a number; the agent cannot reason over a number. What it
    # can reason over is that THIS invocation matched a rule saying it writes
    # under a system path, that the effect is mostly irreversible, and why
    # someone wrote that down. Those were being formatted into an English
    # sentence in `constraints_applicable` and nowhere else, so anything
    # downstream had to parse prose back into fields.
    #
    # Empty where no rule matched, which is itself the signal: the system has
    # no specific interpretation of this action and is running on the coarse
    # per-tool prior.
    trigger_id: str = ""
    trigger_name: str = ""
    rationale: str = ""
    irreversibility: str = ""
    impact_level: str = ""
    safety_risk: str = ""

    #: WHAT THE TOOL DECLARES ABOUT ITSELF -- capability set, declared risk,
    #: whether it touches credentials or the network, whether it is idempotent.
    #: Reported SEPARATELY from the reading above, because a declaration and an
    #: observation are different kinds of claim: `run_shell_command` declares
    #: CRITICAL capability on every call, and only the reading distinguishes
    #: `echo hello` from `rm -rf /`. Collapsing the two is the original defect.
    capability: Dict[str, Any] = field(default_factory=dict)

    def determination(self) -> Dict[str, Any]:
        """The interpretation, in the shape a caller hands to the agent."""
        return {
            "risk_level": self.risk_level.value,
            "safety_level": self.safety_level.value,
            "monitoring_required": self.monitoring_required,
            "rule": self.trigger_id,
            "rule_name": self.trigger_name,
            "rationale": self.rationale,
            "irreversibility": self.irreversibility,
            "impact_level": self.impact_level,
            "safety_risk": self.safety_risk,
            "violations": list(self.violations_detected),
            "capability": dict(self.capability),
        }


class SafetyFramework:
    """
    Multi-Layered Safety Framework

    Monitors and enforces safety constraints during autonomous operation.
    Integrates with governance, prompts, and commitment systems.
    """

    def __init__(self, enable_blocking: bool = True):
        self.enable_blocking = enable_blocking
        logger.info(f"SafetyFramework initialized (blocking={enable_blocking})")

        # Initialize integrated systems
        self.prompt_system = MultiLevelSafetyPrompts()
        self.contract_manager = CommitmentContractManager()  # Uses commitment contracts!
        logger.info("Safety subsystems initialized")

        # Metrics
        self.metrics = {
            'evaluations_performed': 0,
            'high_risk_actions': 0,
            'violations_detected': 0,
            'actions_blocked': 0
        }

        # Constraint database
        self.constraints = []
        self.violation_history = []

        # Safety audit trail — in-memory ring plus durable persistence
        self.audit_trail = []
        self.safety_events = []
        self._tables_ready = False

        # Escalation handlers
        self.escalation_handlers = {}
        self.alert_thresholds = {}

        logger.info("SafetyFramework ready")

    def _check_action_contract(self, tool_name, parameters) -> Optional[str]:
        """Refuse actions the task in hand does not authorise.

        Returns a violation string to block, or None to allow. No contract in
        force means unconstrained -- contracts narrow authority, they do not
        grant it, so unattached work behaves exactly as before.
        """
        try:
            from core.safety.action_contract import get_active_contract, ActionClass
            from core.safety.action_consequence import classify_action

            contract = get_active_contract()
            if contract is None:
                return None

            action_class, irreversibility = classify_action(tool_name or "", parameters or {})

            if not contract.permits(action_class):
                allowed = ", ".join(a.value for a in contract.permitted_actions)
                msg = (
                    f"action class '{action_class.value}' is not authorised by finding "
                    f"{contract.finding_id} (permitted: {allowed})"
                )
                if contract.recoverable_path and action_class == ActionClass.DELETE:
                    msg += f"; move the artifact to {contract.recoverable_path} instead"
                return msg

            if not contract.allows_irreversibility(irreversibility):
                return (
                    f"consequence '{irreversibility}' exceeds the maximum "
                    f"'{contract.max_irreversibility}' permitted by finding "
                    f"{contract.finding_id}"
                )
            return None
        except Exception as e:
            # A broken contract check must not silently disable enforcement.
            logger.error(f"action-contract check failed: {e}", exc_info=True)
            return None

    async def evaluate_action(
        self,
        action_id: str,
        action_type: str,
        parameters: Dict[str, Any],
        tool_name: Optional[str] = None,
        tool_safety: Optional[str] = None,
        is_internal: bool = True,
        source: str = "agent",
        capability: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, SafetyEvaluation]:
        """
        Evaluate action safety before execution, and persist the result.

        Every exit path is recorded to `safety_assessments` — this is the
        labelled experience log, not just an audit trail.

        Args:
            action_id: Unique action identifier
            action_type: Type of action being performed
            parameters: Action parameters
            tool_name: Tool being invoked, if any
            tool_safety: ToolSafety level, used as a risk signal (never a gate)

        Returns:
            Tuple of (approved, SafetyEvaluation)
        """
        started = time.perf_counter()
        try:
            approved, evaluation = await self._evaluate_action_impl(
                action_id, action_type, parameters, tool_safety,
                is_internal, source, tool_name, capability
            )
        except GovernanceBlockError as e:
            # Hard invariant — record before propagating
            await self._persist_evaluation(
                SafetyEvaluation(
                    action_id=action_id,
                    safety_level=SafetyLevel.CRITICAL,
                    risk_level=RiskLevel.CRITICAL,
                    constraints_applicable=[type(e).__name__],
                    monitoring_required=True,
                    approval_required=True,
                    violations_detected=[str(e)],
                ),
                action_type, tool_name, tool_safety, False,
                (time.perf_counter() - started) * 1000,
            )
            raise

        await self._persist_evaluation(
            evaluation, action_type, tool_name, tool_safety, approved,
            (time.perf_counter() - started) * 1000,
        )
        return approved, evaluation

    async def _evaluate_action_impl(
        self,
        action_id: str,
        action_type: str,
        parameters: Dict[str, Any],
        tool_safety: Optional[str] = None,
        is_internal: bool = True,
        source: str = "agent",
        tool_name: Optional[str] = None,
        capability: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, SafetyEvaluation]:
        """Evaluation logic. Callers should use evaluate_action()."""
        capability = dict(capability or {})
        evaluation = {
            'action_id': action_id,
            'action_type': action_type,
            'parameters': parameters,
            'constraints_checked': [],
            'violations': [],
            'timestamp': datetime.now().isoformat()
        }

        try:
            # Layer 0: ACTION CONTRACT — may this task do this KIND of thing?
            #
            # Distinct from every other layer, which ask "is this input safe" or
            # "how dangerous is this tool". This asks whether the work currently
            # in hand authorises this class of consequence at all. A LOW-severity
            # "go and look at this" finding must not be able to authorise an
            # irreversible action, however well-formed the arguments are.
            contract_block = self._check_action_contract(tool_name, parameters)
            if contract_block:
                evaluation['violations'].append(contract_block)
                logger.warning(f"CONTRACT BLOCK for {action_id}: {contract_block}")
                return False, SafetyEvaluation(
                    action_id=action_id,
                    safety_level=SafetyLevel.CRITICAL,
                    risk_level=RiskLevel.HIGH,
                    constraints_applicable=[contract_block],
                    monitoring_required=True,
                    approval_required=False,
                    violations_detected=[contract_block],
                    capability=capability,
                )

            # Layer 1: INPUT — injection, path traversal, rate limiting.
            # Folded in from SecurityController so callers no longer have to
            # invoke it separately. Fail-closed: untrusted input is not an
            # agent decision, so this is one of the few hard blocks.
            try:
                from core.security.controller import get_security_controller
                input_ok, input_err = await get_security_controller().validate_request(
                    parameters,
                    {
                        'action_type': action_type,
                        'action_id': action_id,
                        # Agent-originated calls are internal. Without this the full
                        # SQL-injection regex set runs on every string argument, and
                        # `(--[^\n]*$)` matches any trailing CLI flag — blocking
                        # `ls --color`, `git log --oneline`, `pytest --verbose`.
                        'is_internal': is_internal,
                        'source': source,
                        'tool_name': tool_name,
                    },
                )
            except Exception as e:
                logger.debug(f"input validation unavailable: {e}")
                input_ok, input_err = True, ""

            if not input_ok:
                evaluation['violations'].append(input_err)
                logger.warning(f"Input validation failed for {action_id}: {input_err}")
                return False, SafetyEvaluation(
                    action_id=action_id,
                    safety_level=SafetyLevel.CRITICAL,
                    risk_level=RiskLevel.CRITICAL,
                    constraints_applicable=[f"Input validation: {input_err}"],
                    monitoring_required=True,
                    approval_required=False,
                    violations_detected=[input_err],
                    capability=capability,
                )

            # Layer 2: RUNTIME CAPACITY — can the system take an action at all?
            # Composed from RuntimeGovernance so callers get one answer. This is
            # the read-only check by design: pre_execution_check() registers an
            # action and obliges the caller to clear_action(), which would leak
            # here. Runtime governance keeps the pre/mid/post lifecycle and
            # emergency halt; this only asks whether there is capacity now.
            try:
                from core.agents.autonomous.runtime_governance import get_runtime_governance
                accepted, cap_reason, cap_severity = get_runtime_governance().can_accept_action()
            except Exception as e:
                logger.debug(f"runtime capacity check unavailable: {e}")
                accepted, cap_reason, cap_severity = True, "", ""

            if not accepted:
                evaluation['violations'].append(cap_reason)
                logger.warning(f"Runtime capacity blocked {action_id}: {cap_reason}")
                return False, SafetyEvaluation(
                    action_id=action_id,
                    safety_level=(
                        SafetyLevel.CRITICAL if cap_severity == "critical"
                        else SafetyLevel.MODERATE
                    ),
                    risk_level=(
                        RiskLevel.CRITICAL if cap_severity == "critical"
                        else RiskLevel.MEDIUM
                    ),
                    constraints_applicable=[f"Runtime capacity: {cap_reason}"],
                    monitoring_required=True,
                    approval_required=False,
                    violations_detected=[cap_reason],
                    capability=capability,
                )

            # Content safety check
            if 'content' in parameters or 'message' in parameters:
                content = parameters.get('content') or parameters.get('message', '')
                violations = self._check_content_safety(content)

                if violations:
                    evaluation['violations'].extend(violations)
                    logger.warning(f"Content violations: {len(violations)} detected")

                    # Send Slack notification
                    try:
                        from core.integration.slack_notifier import send_slack_notification
                        asyncio.create_task(send_slack_notification({
                            "title": "🚨 Content Safety Violation",
                            "message": f"**Violations Detected:** {len(violations)}\n**Action:** Blocked pending approval\n**Type:** Content safety check",
                            "severity": "critical"
                        }))
                    except:
                        pass

                    return False, SafetyEvaluation(
                        action_id=action_id,
                        safety_level=SafetyLevel.HIGH,
                        risk_level=RiskLevel.HIGH,
                        constraints_applicable=[f"Content safety violation: {v}" for v in violations],
                        monitoring_required=True,
                        approval_required=True,
                        violations_detected=violations,
                        capability=capability,
                    )

            # Dangerous pattern detection
            dangerous_patterns = [
                (r'eval\(', ViolationSeverity.CRITICAL, "Code evaluation"),
                (r'exec\(', ViolationSeverity.CRITICAL, "Code execution"),
                (r'__import__', ViolationSeverity.MAJOR, "Dynamic imports"),
                (r'os\.system', ViolationSeverity.MAJOR, "System commands"),
                (r'subprocess', ViolationSeverity.MINOR, "Subprocess calls"),
                (r'rm\s+-rf', ViolationSeverity.CRITICAL, "Destructive file operations"),
                (r'DROP\s+TABLE', ViolationSeverity.MAJOR, "Database drops"),
                (r'DELETE\s+FROM', ViolationSeverity.MAJOR, "Bulk deletions"),
                (r'<script>', ViolationSeverity.MAJOR, "Script injection"),
                (r'javascript:', ViolationSeverity.MAJOR, "JavaScript protocol"),
                (r'onerror=', ViolationSeverity.MINOR, "Event handlers"),
                (r'onclick=', ViolationSeverity.MINOR, "Click handlers")
            ]

            # THESE PATTERNS SCORE. THEY DO NOT DECIDE.
            #
            # CRITICAL hits here used to return a block directly, which made a
            # twelve-line regex list the real boundary of the whole layer --
            # and an arbitrary one. Measured: `rm -rf /` was denied because it
            # happens to be in the list, while `sudo rm /etc/passwd`,
            # `dd of=/dev/disk0`, `mkfs`, `curl | sh` and `find / -delete` all
            # ran, every one of them correctly scored CRITICAL by a named rule
            # a few lines below. Two boundaries, and the accidental one won.
            #
            # What blocks is now decided in ONE place, by whether the action
            # can be undone (`unified_governance_trigger_system.blocking_mode`).
            # Every condition these patterns describe is covered there by a
            # named rule carrying a declared irreversibility class -- including
            # `eval`/`exec` (code_dynamic_eval) and dynamic imports
            # (code_dynamic_import) -- where the classification is visible and
            # arguable instead of implied by a regex.
            scored_violations = []
            pattern_risk = 0.0
            _PATTERN_RISK = {
                ViolationSeverity.CRITICAL: 0.40,
                ViolationSeverity.MAJOR: 0.25,
                ViolationSeverity.MINOR: 0.10,
            }

            for pattern, severity, description in dangerous_patterns:
                if not re.search(pattern, str(parameters), re.IGNORECASE):
                    continue
                scored_violations.append(description)
                pattern_risk += _PATTERN_RISK.get(severity, 0.10)
                logger.info(f"Dangerous pattern (scored): {description} [{severity.value}]")
                evaluation['violations'].append(description)

            # Prior risk — used only when no governance rule matches below.
            # Non-blocking MAJOR/MINOR pattern hits contribute to it.
            risk_score = min(
                1.0,
                self._assess_risk(action_type, parameters, tool_safety, tool_name,
                                  capability.get("declared_risk")) + pattern_risk
            )
            risk_level = risk_level_for_score(risk_score)

            # Update metrics
            self.metrics['evaluations_performed'] += 1
            if risk_level in [RiskLevel.HIGH, RiskLevel.CRITICAL]:
                self.metrics['high_risk_actions'] += 1

            result_eval = SafetyEvaluation(
                action_id=action_id,
                safety_level=SafetyLevel.LOW,
                risk_level=risk_level,
                constraints_applicable=(
                    [f"Scored pattern: {', '.join(scored_violations)}"]
                    if scored_violations else []
                ),
                monitoring_required=risk_level != RiskLevel.LOW,
                approval_required=risk_level == RiskLevel.CRITICAL,
                violations_detected=scored_violations,
                capability=capability,
            )

        except GovernanceBlockError:
            raise  # propagate hard governance blocks without wrapping
        except Exception as e:
            logger.error(f"Safety evaluation failed: {e}")
            return False, SafetyEvaluation(
                action_id=action_id,
                safety_level=SafetyLevel.CRITICAL,
                risk_level=RiskLevel.CRITICAL,
                constraints_applicable=[f"Evaluation error: {str(e)}"],
                monitoring_required=True,
                approval_required=True,
                violations_detected=["evaluation_error"],
                capability=capability,
            )

        # ── FULL ASI PIPELINE + GOVERNANCE GATE ───────────────────────────────
        # Runs OUTSIDE the content/pattern try-block so GovernanceBlockError and
        # propagate freely to callers.
        try:
            from core.governance.unified_governance_trigger_system import (
                get_unified_governance, EnforcementMode,
            )
            # 1. ASI structural pipeline — only for actions that carry a real plan.
            #
            # Tool calls do not. `ASIActionType["EXECUTE_TOOL"]` raises KeyError, so
            # _build_asi_action_plan falls back to OBSERVATION with empty
            # target_components/dependencies/rollback_plan, making ASI risk exactly
            # 0.3000 for every tool call ever made. That constant was then discarded
            # (gov_context is never read by the matcher). Skipping it on the tool
            # path costs nothing and saves a whole pipeline per invocation.
            assessment = None
            if not tool_name:
                action_plan = self._build_asi_action_plan(action_id, action_type, parameters)
                asi_ctx = self._build_asi_context()
                assessment = await self._get_asi_framework().assess_action_safety(
                    action_plan, asi_ctx
                )

            gov_context = {"source": source}
            if assessment is not None:
                gov_context.update({
                    "asi_risk_score": assessment.risk_score,
                    "asi_safety_level": assessment.safety_level.value,
                    "asi_decision_outcome": assessment.decision_outcome.value,
                })
            category = self._action_type_to_category(action_type)

            # tool_name travels IN the parameters the matcher sees.
            #
            # It arrives here as a separate argument, and was passed that way --
            # so every trigger whose condition keys on `tool_name` (most of the
            # TOOL_EXECUTION set: safety_infrastructure_write, the chaos rules,
            # credential access, db destruction) could not fire from this path
            # at all. The rule engine matched correctly when asked directly; the
            # gate simply never told it which tool was running. That is a silent
            # false negative: the evaluation returns "no rule matched" and the
            # static per-tool prior stands, which is exactly the per-tool
            # severity this composition exists to replace.
            #
            # A caller-supplied "tool_name" is not overwritten -- if parameters
            # already carry one, that is the value the matcher was going to use
            # and quietly substituting a different one would be its own defect.
            gov_parameters = dict(parameters or {})
            if tool_name and "tool_name" not in gov_parameters:
                gov_parameters["tool_name"] = tool_name

            gov_eval = await get_unified_governance().evaluate_action(
                action_category=category,
                action_type=action_type,
                parameters=gov_parameters,
                context=gov_context,
            )

            # 3. Compose. A matched rule SETS the risk level; it does not add to
            #    the prior.
            #
            #    This is the difference between per-tool and per-invocation
            #    severity. `run_shell_command` carries CRITICAL *capability*, but
            #    `echo hello` is evidence that THIS invocation is harmless. A rule
            #    matching on parameter values is direct evidence about the
            #    invocation and therefore outranks the static prior — in both
            #    directions, up and down.
            if gov_eval.triggered:
                if gov_eval.enforcement_mode == EnforcementMode.MUST_BLOCK:
                    # Returned as (False, evaluation) rather than raised. An
                    # exception meaning "deny" is a footgun: any caller with a
                    # broad `except` around the gate turns a block into an allow.
                    self.metrics['actions_blocked'] += 1
                    reason = (
                        f"{gov_eval.trigger_name or gov_eval.trigger_id}: "
                        f"{gov_eval.rationale or 'matched governance rule'}"
                    )
                    logger.warning(
                        f"SAFETY BLOCK: {action_type} — rule {gov_eval.trigger_id} "
                        f"({gov_eval.safety_risk})"
                    )
                    return False, SafetyEvaluation(
                        action_id=action_id,
                        safety_level=SafetyLevel.CRITICAL,
                        risk_level=RiskLevel.CRITICAL,
                        constraints_applicable=[reason],
                        monitoring_required=True,
                        approval_required=False,
                        violations_detected=[reason],
                        trigger_id=gov_eval.trigger_id or "",
                        trigger_name=gov_eval.trigger_name or "",
                        rationale=gov_eval.rationale or "",
                        irreversibility=gov_eval.irreversibility_class.value,
                        impact_level=str(gov_eval.impact_level or ""),
                        safety_risk=str(gov_eval.safety_risk or ""),
                        capability=capability,
                    )

                rule_risk = SAFETY_RISK_SCORE.get(gov_eval.safety_risk, 0.5)
                result_eval.risk_level = risk_level_for_score(rule_risk)
                result_eval.monitoring_required = rule_risk >= 0.3
                result_eval.constraints_applicable.append(
                    f"Rule {gov_eval.trigger_id}: {gov_eval.trigger_name} "
                    f"(safety_risk={gov_eval.safety_risk})"
                )
                # The determination travels as fields, not as a sentence.
                result_eval.trigger_id = gov_eval.trigger_id or ""
                result_eval.trigger_name = gov_eval.trigger_name or ""
                result_eval.rationale = gov_eval.rationale or ""
                result_eval.irreversibility = gov_eval.irreversibility_class.value
                result_eval.impact_level = str(gov_eval.impact_level or "")
                result_eval.safety_risk = str(gov_eval.safety_risk or "")
                logger.info(
                    f"SafetyFramework: rule {gov_eval.trigger_id} matched — "
                    f"risk SET to {result_eval.risk_level.value} "
                    f"(prior from tool_safety={tool_safety} overridden)"
                )
                result_eval.capability = capability
            else:
                result_eval.capability = capability
                # No rule matched: fall back to the static prior already computed
                logger.debug(
                    f"SafetyFramework: no rule matched; prior risk="
                    f"{result_eval.risk_level.value} from tool_safety={tool_safety}"
                )
        except GovernanceBlockError:
            raise  # always propagate hard blocks
        except Exception as e:
            logger.error(
                f"SafetyFramework: ASI/governance gate error — {e}", exc_info=True
            )
            # Fail open with approval flag; caller must handle
            result_eval.approval_required = True
        # ─────────────────────────────────────────────────────────────────────

        logger.info(f"Safety evaluation complete (action_id={action_id[:8]}, risk={result_eval.risk_level.value})")
        return True, result_eval

    def _check_content_safety(self, content: str) -> List[str]:
        """Check content for safety violations"""
        violations = []

        # Length check
        if len(content) > 50000:
            violations.append("Excessive content length")

        # Encoding check
        encoding_patterns = [
            r'<!-+', r'-+>', r'<!--', r'-->',
            r'"""|\'\'\'', r'<%+%>', r'\{\{+\}\}', r'\$\{+\}'
        ]

        suspicious_count = sum(1 for pattern in encoding_patterns
                              if re.search(pattern, content, re.IGNORECASE))
        if suspicious_count >= 3:
            violations.append("Suspicious encoding patterns")

        # Script injection
        if re.search(r'<script[^>]*>', content, re.IGNORECASE):
            violations.append("Script injection attempt")

        if re.search(r'javascript:', content, re.IGNORECASE):
            violations.append("JavaScript protocol detected")

        # Excessive nesting
        nesting_patterns = [r'\{\{+', r'\[\[+', r'\(\(+']
        for pattern in nesting_patterns:
            matches = re.findall(pattern, content)
            if any(len(match) > 5 for match in matches):
                violations.append("Excessive nesting detected")
                break

        # SQL injection patterns
        sql_patterns = [
            r'UNION\s+SELECT', r'OR\s+1\s*=\s*1',
            r'DROP\s+TABLE', r'DELETE\s+FROM'
        ]

        for pattern in sql_patterns:
            if re.search(pattern, content, re.IGNORECASE):
                violations.append("SQL injection pattern")
                break

        return violations

    def _sanitize_html(self, content: str) -> str:
        """Sanitize HTML content"""
        sanitized = content

        # Remove dangerous tags
        dangerous_tags = [
            (r'<script[^>]*>.*?</script>', ''),
            (r'<iframe[^>]*>.*?</iframe>', ''),
            (r'<object[^>]*>.*?</object>', ''),
            (r'<embed[^>]*>', ''),
            (r'<applet[^>]*>', ''),
            (r'<meta[^>]*>', ''),
            (r'<link[^>]*>', '')
        ]

        for pattern, replacement in dangerous_tags:
            sanitized = re.sub(pattern, replacement, sanitized, flags=re.IGNORECASE | re.DOTALL)

        # Escape special characters
        escape_map = {
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#x27;'
        }

        # Only escape if not already part of an entity
        for char, entity in escape_map.items():
            if char not in content or content.count(char) < content.count('<') * 2:
                sanitized = sanitized.replace(char, entity)

        return sanitized

    # ToolSafety contributes to the PRIOR risk only — it describes what the tool
    # is capable of, not what this invocation does. A matched governance rule
    # overrides it entirely. It never gates: the Singleton retains full tool
    # autonomy by design (see tool_registry.ToolSafety).
    TOOL_SAFETY_RISK = {
        "safe": 0.0,
        "moderate": 0.15,
        "dangerous": 0.35,
        "critical": 0.50,
        "high_risk": 0.60,
    }

    def _assess_risk(
        self,
        action_type: str,
        parameters: Dict[str, Any],
        tool_safety: Optional[str] = None,
        tool_name: Optional[str] = None,
        declared_risk: Optional[str] = None
    ) -> float:
        """
        Prior risk for an action, used when no governance rule matches.

        This is deliberately coarse — it describes what the tool is *capable* of,
        not what this invocation does. A matched rule overrides it entirely.

        Args:
            action_type: Type of action
            parameters: Action parameters
            tool_safety: ToolSafety level of the tool, as a risk signal
            tool_name: Tool being invoked — matched against the operation table

        Returns:
            Risk score (0.0 to 1.0)
        """
        risk_score = 0.0

        # TWO DECLARATIONS OF THE SAME KIND, AND THE HIGHER ONE STANDS.
        #
        # `tool_safety` is one label for the whole tool; `declared_risk` is the
        # worst of its per-capability annotations, which is finer and, until
        # now, was written 297 times and read nowhere. Both describe CAPABILITY,
        # so they are not evidence to be added together -- summing them would
        # double-count one fact and reintroduce per-tool severity by arithmetic.
        risk_score += max(
            self.TOOL_SAFETY_RISK.get((tool_safety or "").lower(), 0.0),
            self.TOOL_SAFETY_RISK.get((declared_risk or "").lower(), 0.0),
        )

        # The operation table below lists TOOL-shaped names (execute_code,
        # file_delete, database_drop). It was previously matched against
        # action_type, which for every tool call is the literal string
        # "execute_tool" — so it never fired once. Match the tool name instead.
        subject = f"{action_type} {tool_name or ''}".lower()

        # Base risk by action type
        high_risk_actions = [
            'execute_code', 'system_command', 'file_delete',
            'database_drop', 'permission_change', 'config_modify'
        ]

        moderate_risk_actions = [
            'file_write', 'database_write', 'api_call',
            'memory_modify', 'learning_adjust'
        ]

        if any(action in subject for action in high_risk_actions):
            risk_score += 0.8
        elif any(action in subject for action in moderate_risk_actions):
            risk_score += 0.4

        return min(1.0, risk_score)

    def _get_asi_framework(self):
        """Lazy singleton accessor for ASISafetyFramework (avoids circular imports)."""
        if not hasattr(self, '_asi_framework') or self._asi_framework is None:
            from core.security.asi_safety import create_asi_safety_framework
            self._asi_framework = create_asi_safety_framework()
        return self._asi_framework

    def _build_asi_action_plan(self, action_id: str, action_type: str, parameters: Dict[str, Any]):
        """Construct ASIActionPlan from the simple evaluate_action() interface."""
        from core.security.asi_safety import ASIActionPlan, ASIActionType
        try:
            asi_type = ASIActionType[action_type.upper()]
        except KeyError:
            # Unknown action type — use first enum member as generic fallback
            asi_type = next(iter(ASIActionType))
        return ASIActionPlan(
            action_id=action_id,
            action_type=asi_type,
            description=parameters.get("description", action_type),
            target_components=parameters.get("target_components", []),
            expected_outcomes=parameters.get("expected_outcomes", []),
            potential_risks=parameters.get("potential_risks", []),
            rollback_plan=parameters.get("rollback_plan"),
            estimated_impact=parameters.get("estimated_impact", {}),
            dependencies=parameters.get("dependencies", []),
        )

    def _build_asi_context(self):
        """Build ASISafetyContext from lightweight system introspection."""
        from core.security.asi_safety import ASISafetyContext
        try:
            import psutil
            resource_usage = {
                "cpu_percent": psutil.cpu_percent(interval=None),
                "memory_percent": psutil.virtual_memory().percent,
            }
        except Exception:
            resource_usage = {"cpu_percent": 0.0, "memory_percent": 0.0}

        recent_changes = [
            {"event": str(v), "timestamp": datetime.now().isoformat()}
            for v in self.violation_history[-5:]
        ] if self.violation_history else []

        return ASISafetyContext(
            system_state={"status": "operational", "pid": os.getpid()},
            current_capabilities=["tool_execution", "memory_read", "task_creation"],
            critical_components=[
                "core.governance",
                "core.security.safety_framework",
                "core.agents.autonomous.autonomous_coordinator",
            ],
            active_processes=[],
            resource_usage=resource_usage,
            recent_changes=recent_changes,
            risk_tolerance=0.3,
        )

    def _action_type_to_category(self, action_type: str):
        """Map action_type string to governance ActionCategory."""
        from core.governance.unified_governance_trigger_system import ActionCategory
        _map = {
            # Tool execution
            "tool": ActionCategory.TOOL_EXECUTION,
            "tool_execution": ActionCategory.TOOL_EXECUTION,
            # Memory operations
            "memory": ActionCategory.MEMORY_OPERATIONS,
            "memory_operations": ActionCategory.MEMORY_OPERATIONS,
            # Learning / self-modification — same category so trigger-level rules apply
            "learn": ActionCategory.LEARNING_PARAMETERS,
            "learning": ActionCategory.LEARNING_PARAMETERS,
            "learning_parameters": ActionCategory.LEARNING_PARAMETERS,
            "self_modification": ActionCategory.LEARNING_PARAMETERS,
            "self_improve": ActionCategory.LEARNING_PARAMETERS,
            "model_parameter_override": ActionCategory.LEARNING_PARAMETERS,
            "weight_change": ActionCategory.LEARNING_PARAMETERS,
            # Configuration changes
            "config": ActionCategory.CONFIGURATION_CHANGES,
            "configuration": ActionCategory.CONFIGURATION_CHANGES,
            "configuration_changes": ActionCategory.CONFIGURATION_CHANGES,
            # Task/agent creation
            "task": ActionCategory.TASK_CREATION,
            "task_creation": ActionCategory.TASK_CREATION,
            "agent_spawn": ActionCategory.TASK_CREATION,
            "agent_creation": ActionCategory.TASK_CREATION,
            # Resource allocation
            "resource": ActionCategory.RESOURCE_ALLOCATION,
            "resource_allocation": ActionCategory.RESOURCE_ALLOCATION,
            # External integrations / API calls
            "external": ActionCategory.EXTERNAL_INTEGRATIONS,
            "external_integrations": ActionCategory.EXTERNAL_INTEGRATIONS,
            "external_api_call": ActionCategory.EXTERNAL_INTEGRATIONS,
            "api_call": ActionCategory.EXTERNAL_INTEGRATIONS,
            # Curiosity / exploration
            "curiosity": ActionCategory.CURIOSITY_EXPLORATION,
            "curiosity_exploration": ActionCategory.CURIOSITY_EXPLORATION,
            "explore": ActionCategory.CURIOSITY_EXPLORATION,
        }
        # Try exact match first, then prefix match
        key = action_type.lower()
        if key in _map:
            return _map[key]
        prefix = key.split("_")[0]
        return _map.get(prefix, ActionCategory.TOOL_EXECUTION)

    # ========================================================================
    # PERSISTENCE — the labelled experience log
    # ========================================================================

    async def _ensure_tables(self) -> bool:
        if self._tables_ready:
            return True
        try:
            from core.database import get_database_manager
            db = get_database_manager()
            await db.execute_query(
                """
                CREATE TABLE IF NOT EXISTS safety_assessments (
                    assessment_id       VARCHAR(64) PRIMARY KEY,
                    -- TEXT, not VARCHAR(64). action_id is an EXTERNAL identifier
                    -- (task ids such as
                    -- security_remediation_integrity_modified_core_agents_autonomous_general_purpose_executor.py)
                    -- whose length this table does not control. Bounding it made
                    -- every long-id evaluation fail to persist: the safety
                    -- decision was still made and enforced, but the durable audit
                    -- record was silently lost — the worst half to lose.
                    -- assessment_id stays bounded because WE mint it.
                    action_id           TEXT NOT NULL,
                    action_type         TEXT NOT NULL,
                    tool_name           VARCHAR(128),
                    tool_safety         VARCHAR(16),
                    risk_level          VARCHAR(16) NOT NULL,
                    safety_level        VARCHAR(16) NOT NULL,
                    approved            BOOLEAN NOT NULL,
                    monitoring_required BOOLEAN NOT NULL DEFAULT FALSE,
                    approval_required   BOOLEAN NOT NULL DEFAULT FALSE,
                    violations          JSONB NOT NULL DEFAULT '[]'::jsonb,
                    constraints         JSONB NOT NULL DEFAULT '[]'::jsonb,
                    assess_duration_ms  NUMERIC(10,3),
                    assessed_at         TIMESTAMP NOT NULL,
                    outcome_success     BOOLEAN,
                    outcome_error       TEXT,
                    outcome_at          TIMESTAMP,
                    -- WHY it scored what it scored: rule id, rationale,
                    -- irreversibility, and what the tool declares about itself.
                    -- Without this a row records a verdict and no reasoning, so
                    -- the labelled dataset can be counted but not learned from --
                    -- you cannot ask which RULE is producing false positives if
                    -- the rule was never written down.
                    determination       JSONB NOT NULL DEFAULT '{}'::jsonb
                )
                """,
                commit=True,
            )
            # Added after the table existed; ALTER rather than a migration file
            # so an existing deployment picks it up on the next evaluation.
            await db.execute_query(
                "ALTER TABLE safety_assessments "
                "ADD COLUMN IF NOT EXISTS determination JSONB NOT NULL "
                "DEFAULT '{}'::jsonb",
                commit=True,
            )
            for stmt in (
                "CREATE INDEX IF NOT EXISTS idx_sa_assessed_at ON safety_assessments (assessed_at DESC)",
                "CREATE INDEX IF NOT EXISTS idx_sa_action_id ON safety_assessments (action_id)",
                "CREATE INDEX IF NOT EXISTS idx_sa_risk ON safety_assessments (risk_level)",
                "CREATE INDEX IF NOT EXISTS idx_sa_outcome ON safety_assessments (outcome_success)",
                # "which rule fired" is the question this table now exists to
                # answer, so it is the one that gets an index.
                "CREATE INDEX IF NOT EXISTS idx_sa_rule ON safety_assessments "
                "((determination->>'rule'))",
            ):
                await db.execute_query(stmt, commit=True)

            self._tables_ready = True
            return True
        except Exception as e:
            logger.error(f"safety_assessments table unavailable: {e}")
            return False

    async def _persist_evaluation(
        self,
        evaluation: SafetyEvaluation,
        action_type: str,
        tool_name: Optional[str],
        tool_safety: Optional[str],
        approved: bool,
        duration_ms: float,
    ) -> bool:
        """Record an evaluation. Never raises — safety must not break on a DB error."""
        if not await self._ensure_tables():
            return False
        try:
            from core.database import get_database_manager
            db = get_database_manager()
            assessment_id = f"sa_{uuid.uuid4().hex[:16]}"
            await db.execute_query(
                """
                INSERT INTO safety_assessments (
                    assessment_id, action_id, action_type, tool_name, tool_safety,
                    risk_level, safety_level, approved, monitoring_required,
                    approval_required, violations, constraints,
                    assess_duration_ms, assessed_at, determination
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11::jsonb,$12::jsonb,$13,$14,$15::jsonb)
                """,
                (
                    assessment_id,
                    evaluation.action_id,
                    action_type,
                    tool_name,
                    tool_safety,
                    evaluation.risk_level.value,
                    evaluation.safety_level.value,
                    approved,
                    evaluation.monitoring_required,
                    evaluation.approval_required,
                    json.dumps(evaluation.violations_detected or []),
                    json.dumps(evaluation.constraints_applicable or []),
                    round(duration_ms, 3),
                    evaluation.evaluated_at,
                    json.dumps(evaluation.determination()),
                ),
                commit=True,
            )

            await db.execute_query(
                """
                INSERT INTO governance_audit_log
                    (action_id, action_type, tier, approved, rationale, timestamp, source_type)
                VALUES ($1,$2,$3,$4,$5,$6,$7)
                """,
                (
                    evaluation.action_id, action_type, evaluation.risk_level.value,
                    approved,
                    "; ".join(evaluation.constraints_applicable or []) or "no constraints",
                    evaluation.evaluated_at, "safety_framework",
                ),
                commit=True,
            )
            return True
        except Exception as e:
            logger.error(f"Failed to persist safety evaluation: {e}")
            return False

    async def record_outcome(
        self,
        action_id: str,
        success: bool,
        error: Optional[str] = None
    ) -> bool:
        """Close an assessment with what actually happened.

        This is what turns the table into a labelled dataset the learning
        loop can train a policy on.
        """
        if not await self._ensure_tables():
            return False
        try:
            from core.database import get_database_manager
            db = get_database_manager()
            await db.execute_query(
                """
                UPDATE safety_assessments
                SET outcome_success = $2, outcome_error = $3, outcome_at = $4
                WHERE action_id = $1 AND outcome_at IS NULL
                """,
                (action_id, success, error, datetime.now()),
                commit=True,
            )
            return True
        except Exception as e:
            logger.error(f"Failed to record outcome for {action_id}: {e}")
            return False

    async def get_safety_metrics(self) -> Dict[str, Any]:
        """Live counters plus persisted aggregates."""
        out = dict(self.metrics)
        try:
            from core.database import get_database_manager
            db = get_database_manager()
            row = await db.execute_query(
                """
                SELECT count(*)                                         AS total,
                       count(*) FILTER (WHERE approved IS FALSE)        AS denied,
                       count(*) FILTER (WHERE monitoring_required)      AS monitored,
                       count(*) FILTER (WHERE outcome_success IS TRUE)  AS succeeded,
                       count(*) FILTER (WHERE outcome_success IS FALSE) AS failed,
                       round(avg(assess_duration_ms), 3)                AS avg_assess_ms
                FROM safety_assessments
                """,
                fetch_one=True,
            )
            if row:
                out["persisted"] = {k: (float(v) if v is not None else 0)
                                    for k, v in dict(row).items()}
        except Exception as e:
            logger.debug(f"safety metrics aggregate unavailable: {e}")
        return out

    async def log_safety_event(
        self,
        event_type: str,
        details: Dict[str, Any] = None
    ) -> str:
        """
        Log a safety event to audit trail

        Args:
            event_type: Type of safety event
            details: Event details

        Returns:
            Event ID
        """
        event_id = f"safety_{datetime.now().timestamp()}_{id(self)}"

        event_data = {
            'event_id': event_id,
            'event_type': event_type,
            'timestamp': datetime.now().isoformat(),
            'details': details or {},
            'framework_state': {
                'blocking_enabled': self.enable_blocking,
                'total_evaluations': self.metrics['evaluations_performed']
            }
        }

        self.safety_events.append(event_data)
        logger.info(f"Safety event logged: {event_type} (id={event_id[:16]})")

        # Escalate if threshold exceeded
        if self.metrics['violations_detected'] >= 10:
            # Trigger escalation
            await self._escalate_safety_concern(event_data)

        # Limit audit trail size (keep last 1000 events)
        if len(self.safety_events) > 1000:
            self.safety_events = self.safety_events[-1000:]

        return event_id

    async def _escalate_safety_concern(
        self,
        event_data: Dict[str, Any]
    ):
        """
        Escalate safety concern

        Args:
            event_data: Event triggering escalation
        """
        logger.warning(f"Escalating safety concern: {event_data['event_type']}")
        # Implementation: send to governance system, Slack, etc.

    async def monitor_execution(
        self,
        action_id: str,
        execution_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Monitor action execution for safety violations

        Args:
            action_id: Action being monitored
            execution_context: Context during execution

        Returns:
            Monitoring report
        """
        report = {
            'action_id': action_id,
            'monitoring_start': datetime.now().isoformat(),
            'violations_detected': []
        }

        # Real-time monitoring would go here
        # (Check memory usage, CPU, network calls, etc.)

        return report

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get safety framework statistics

        Returns:
            Statistics dictionary
        """
        current_time = datetime.now()

        # Calculate rates
        total_evaluations = self.metrics['evaluations_performed']
        violation_rate = (
            self.metrics['violations_detected'] / total_evaluations
            if total_evaluations > 0
            else 0.0
        )

        return {
            **self.metrics,
            'violation_rate': violation_rate,
            'blocking_enabled': self.enable_blocking,
            'constraints_count': len(self.constraints),
            'events_logged': len(self.safety_events),
            'framework_uptime': (current_time - datetime.now()).total_seconds(),
            'last_evaluation': datetime.now().isoformat()
        }

    def __del__(self):
        """Cleanup on deletion"""
        if hasattr(self, 'metrics'):
            total_evals = self.metrics.get('evaluations_performed', 0)
            logger.debug(f"SafetyFramework cleanup ({total_evals} evaluations)")


# Singleton instance
_safety_framework: Optional[SafetyFramework] = None


def get_safety_framework(enable_blocking: bool = True) -> SafetyFramework:
    """Get safety framework singleton instance"""
    global _safety_framework
    if _safety_framework is None:
        _safety_framework = SafetyFramework(enable_blocking=enable_blocking)
        logger.info("Created singleton SafetyFramework instance")
    return _safety_framework
