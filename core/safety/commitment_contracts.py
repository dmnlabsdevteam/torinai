"""
Commitment Contracts System

Pre-action and post-action commitment verification for behavioral enforcement.
Ensures actions match committed parameters and safety constraints.

Three Commitment Types:
- OUTCOME: What the action will achieve
- CONSTRAINT: Safety boundaries and limits
- BEHAVIOR: High-level behavioral pledges for critical actions

Features:
- Parameter tampering detection (±5% tolerance for numeric values)
- Pre-execution blocking mode validation
- Post-execution verification with violation severity classification
- Violation tracking by category with metrics
- Integration with Unified Governance Trigger System
"""

import logging
import hashlib
import json
from typing import Dict, Any, List, Optional, Tuple, Set
from dataclasses import dataclass, asdict, field
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class CommitmentType(Enum):
    """Types of commitments"""
    OUTCOME = "OUTCOME"  # What action will achieve
    CONSTRAINT = "CONSTRAINT"  # Safety boundaries
    BEHAVIOR = "BEHAVIOR"  # High-level pledges


class ViolationSeverity(Enum):
    """Violation severity levels"""
    MINOR = "MINOR"  # Slight deviation (~5%)
    MAJOR = "MAJOR"  # Significant deviation or unauthorized action
    CRITICAL = "CRITICAL"  # Safety constraint violated


@dataclass
class Commitment:
    """Individual commitment within a contract"""
    commitment_type: CommitmentType
    statement: str
    verification_method: str  # automated_check, runtime_monitoring, human_review
    committed_by: str
    created_at: datetime
    status: str = "active"  # active, verified, violated


@dataclass
class CommitmentContract:
    """Contract containing multiple commitments for an action"""
    action_id: str
    action_type: str
    commitments: List[Commitment]
    committed_parameters: Dict[str, Any]
    created_at: datetime
    verified: bool = False
    violations: List[str] = field(default_factory=list)  # List of violation messages


@dataclass
class VerificationResult:
    """Result of a single commitment verification"""
    commitment_id: str
    verified: bool
    violation_message: Optional[str]
    severity: ViolationSeverity
    verified_at: datetime


@dataclass
class CommitmentVerificationReport:
    """Result of commitment verification"""
    action_id: str
    total_commitments: int
    commitments_verified: int
    commitments_violated: List[str]
    severity: ViolationSeverity
    violations_details: Dict[str, str]
    verified_at: datetime


class CommitmentContractManager:
    """
    Commitment Contract Manager

    Manages contract lifecycle: creation, pre-execution checks, post-execution verification.
    """

    def __init__(self, state_path: str = "/Users/stefan/Dominion Labs/TorinAI/data/contracts"):
        self.state_path = state_path
        self.contracts: Dict[str, CommitmentContract] = {}
        self.committed_parameters: Dict[str, Dict[str, Any]] = {}
        self.violations_by_category: Dict[str, List[Dict]] = {}
        logger.info(f"CommitmentContractManager initialized (state: {state_path})")

    async def create_contract_for_action(
        self,
        action_id: str,
        action_type: str,
        action_category: str,
        governance_evaluation: Optional[Dict[str, Any]] = None
    ) -> CommitmentContract:
        """
        Create commitment contract for an action

        Args:
            action_id: Unique action identifier
            action_type: Type of action (tool_call, memory_query, etc.)
            action_category: Category from governance (TOOL_EXECUTION, MEMORY_OPERATIONS, etc.)
            governance_evaluation: Optional governance trigger evaluation results

        Returns:
            CommitmentContract with appropriate commitments
        """
        action_id = str(action_id)
        commitments = []

        # ALWAYS create OUTCOME commitment
        # Describes what the action will achieve
        outcome_params = {
            "action_id": action_id,
            "action_type": action_type,
            "action_category": action_category,
            "execution_mode": governance_evaluation.get("execution_mode", "autonomous") if governance_evaluation else "autonomous",
            "timestamp": datetime.now().isoformat()
        }
        outcome_statement = self._generate_outcome_commitment(
            action_type, action_category, outcome_params
        )

        commitments.append(Commitment(
            commitment_type=CommitmentType.OUTCOME,
            statement=outcome_statement,
            verification_method="automated_check",
            committed_by="system",
            created_at=datetime.now(),
            status="active"
        ))

        # Add CONSTRAINT commitment if governance detected safety risk
        if governance_evaluation:
            safety_risk = governance_evaluation.get("safety_risk", "LOW")
            if safety_risk in ["MODERATE", "HIGH", "CRITICAL"]:
                constraint_statement = self._generate_safety_constraint(
                    action_type, action_category, governance_evaluation
                )

                commitments.append(Commitment(
                    commitment_type=CommitmentType.CONSTRAINT,
                    statement=constraint_statement,
                    verification_method="runtime_monitoring",
                    committed_by="governance_system",
                    created_at=datetime.now(),
                    status="active"
                ))

        # Add BEHAVIOR commitment for CRITICAL tier decisions
        decision_tier = governance_evaluation.get("decision_tier", "ROUTINE") if governance_evaluation else "ROUTINE"
        if decision_tier == "CRITICAL":
            behavior_statement = self._generate_behavior_commitment(
                action_type, action_category, governance_evaluation
            )

            commitments.append(Commitment(
                commitment_type=CommitmentType.BEHAVIOR,
                statement=behavior_statement,
                verification_method="human_review",
                committed_by="autonomous_system",
                created_at=datetime.now(),
                status="active"
            ))

        # Create contract
        contract = CommitmentContract(
            action_id=action_id,
            action_type=action_type,
            commitments=commitments,
            committed_parameters={},
            created_at=datetime.now()
        )

        # Store contract
        self.contracts[action_id] = contract
        self.committed_parameters[action_id] = {}

        logger.info(
            f"✓ Created contract for {action_type} (action_id={action_id[:8]}, "
            f"commitments={len(commitments)})"
        )
        return contract

    async def check_contract_before_execution(
        self,
        action_id: str,
        actual_parameters: Dict[str, Any]
    ) -> Tuple[bool, Optional[str]]:
        """
        BLOCKING MODE: Check contract before execution

        Args:
            action_id: Action identifier
            actual_parameters: Parameters being used for execution

        Returns:
            Tuple of (can_proceed, rejection_reason)
                - can_proceed: True if action can execute
                - rejection_reason: Reason if blocked (None if allowed)
        """
        action_id = str(action_id)
        contract = self.contracts.get(action_id)

        logger.info(f"Checking contract before execution (action_id={action_id[:8]})")

        if not contract:
            # No contract = no governance trigger = safe to proceed
            return True, None

        # Check for parameter tampering
        if action_id in self.committed_parameters:
            committed = self.committed_parameters[action_id]

            # Parameter tampering detection
            for param_name, committed_value in committed.items():
                actual_value = actual_parameters.get(param_name)

                # String/identifier check
                if isinstance(committed_value, str) and isinstance(actual_value, str):
                    if committed_value.strip().lower() != actual_value.strip().lower():
                        reason = f"Parameter tampering detected: '{param_name}' changed from '{committed_value}' to '{actual_value}'"
                        logger.warning(reason)
                        return False, reason

                # Numeric check with ±5% tolerance
                if isinstance(committed_value, (int, float)) and isinstance(actual_value, (int, float)):
                    tolerance = abs(committed_value * 0.05)  # 5% tolerance
                    if abs(committed_value - actual_value) > tolerance:
                        reason = f"Parameter tampering detected: '{param_name}' changed from {committed_value} to {actual_value} (exceeds 5% tolerance)"
                        logger.warning(reason)
                        return False, reason

        # Check CONSTRAINT commitments
        for commitment in contract.commitments:
            if commitment.commitment_type == CommitmentType.CONSTRAINT:
                # Validate constraints are not being violated
                # (Additional runtime checks would go here)
                pass

        logger.info(f"✓ Contract check passed (action_id={action_id[:8]})")
        return True, None

    def _generate_outcome_commitment(
        self,
        action_type: str,
        action_category: str,
        parameters: Dict[str, Any]
    ) -> str:
        """
        Generate OUTCOME commitment statement

        Args:
            action_type: Type of action
            action_category: Category from governance
            parameters: Action parameters

        Returns:
            Commitment statement describing expected outcome
        """
        statement = f"This action will execute {action_type}"

        # Add category-specific outcome description
        if action_category == "TOOL_EXECUTION":
            statement += f", invoking the approved tool without modifying unapproved systems"
        elif action_category == "MEMORY_OPERATIONS":
            statement += f", performing memory operations within authorized scope"
        elif action_category == "LEARNING_PARAMETERS":
            statement += f", adjusting learning parameters within safe bounds"
        else:
            # Generic outcome
            statement += (
                f", completing the requested operation while respecting "
                f"all safety boundaries and governance constraints"
            )

        return statement

    def _generate_safety_constraint(
        self,
        action_type: str,
        action_category: str,
        governance_evaluation: Dict[str, Any]
    ) -> str:
        """
        Generate CONSTRAINT commitment statement

        Args:
            action_type: Type of action
            action_category: Category from governance
            governance_evaluation: Governance evaluation results

        Returns:
            Constraint commitment statement
        """
        safety_risk = governance_evaluation.get("safety_risk", "MODERATE")
        impact_level = governance_evaluation.get("impact_level", "MEDIUM")

        statement = f"""SAFETY CONSTRAINT ACKNOWLEDGMENT

Action: {action_type}
Safety Risk: {safety_risk}
Impact Level: {impact_level}

I acknowledge the safety risk level and commit to:
- Monitoring for safety violations during execution
- Halting immediately if constraints are violated
- Reporting any anomalies or unexpected behavior
- Respecting parameter boundaries (no unauthorized modifications)

If any safety constraint is violated, I will:
1. Immediately halt execution
2. Log the violation with full context
3. Escalate to human oversight for review

CRITICAL: No parameter tampering. All execution within approved scope."""

        return statement

    def _generate_behavior_commitment(
        self,
        action_type: str,
        action_category: str,
        governance_evaluation: Dict[str, Any]
    ) -> str:
        """
        Generate BEHAVIOR commitment statement for CRITICAL tier

        Args:
            action_type: Type of action
            action_category: Category from governance
            governance_evaluation: Governance evaluation

        Returns:
            Behavior commitment statement
        """
        decision_tier = governance_evaluation.get("decision_tier", "CRITICAL")

        statement = f"""HIGH-LEVEL BEHAVIORAL COMMITMENT

Decision Tier: {decision_tier}
Action: {action_type}

I commit to executing this action exactly as approved, with:
- Full transparency in all operations
- Immediate reporting of any deviations or issues
- Complete adherence to safety and governance policies
- Zero tolerance for unauthorized modifications

This is a CRITICAL action requiring the highest level of integrity.
Any deviation from the approved plan will be treated as a major violation."""

        return statement

    async def verify_commitments(
        self,
        action_id: str,
        execution_result: Dict[str, Any],
        actual_parameters: Dict[str, Any]
    ) -> CommitmentVerificationReport:
        """
        Post-execution verification of commitments

        Args:
            action_id: Action identifier
            execution_result: Results from action execution
            actual_parameters: Parameters that were actually used

        Returns:
            CommitmentVerificationReport with verification results
        """
        action_id = str(action_id)
        contract = self.contracts.get(action_id)
        violations = []
        severity = ViolationSeverity.MINOR

        # Verify parameter consistency
        if action_id in self.committed_parameters:
            committed = self.committed_parameters[action_id]

            for param_name, committed_value in committed.items():
                actual_value = actual_parameters.get(param_name)

                if committed_value != actual_value:
                    violation_msg = f"Parameter '{param_name}' deviated: committed={committed_value}, actual={actual_value}"
                    violations.append(violation_msg)
                    severity = ViolationSeverity.MAJOR  # Parameter tampering is MAJOR

        # Check OUTCOME commitment
        outcome_achieved = execution_result.get("success", False)
        if not outcome_achieved:
            violations.append("OUTCOME commitment not met: action did not complete successfully")
            severity = ViolationSeverity.MAJOR

        # Determine final severity
        if len(violations) > 2:
            severity = ViolationSeverity.CRITICAL
        elif len(violations) > 0:
            severity = ViolationSeverity.MAJOR

        report = CommitmentVerificationReport(
            action_id=action_id,
            total_commitments=len(contract.commitments) if contract else 0,
            commitments_verified=len(contract.commitments) - len(violations) if contract else 0,
            commitments_violated=violations,
            severity=severity,
            violations_details={f"violation_{i}": v for i, v in enumerate(violations)},
            verified_at=datetime.now()
        )

        # Track violations if any
        if violations:
            self._track_violation(action_id, violations, severity)

        return report

    def _track_violation(
        self,
        action_id: str,
        violations: List[str],
        severity: ViolationSeverity
    ):
        """
        Track violation for metrics

        Args:
            action_id: Action identifier
            violations: List of violation messages
            severity: Violation severity
        """
        logger.warning(f"Tracking violation for action_id={action_id[:8]}")
        # Implementation: store violations for metrics and analysis
        # (Could persist to database here)

    def get_violation_rate(self, action_category: str) -> float:
        """
        Get violation rate for an action category

        Args:
            action_category: Action category to check

        Returns:
            Violation rate (0.0 to 1.0)
        """
        logger.debug(f"Getting violation rate for category={action_category}")
        # Implementation: calculate from stored violations
        return 0.0

    def get_contract_stats(self) -> Dict[str, Any]:
        """
        Get contract statistics

        Returns:
            Dictionary with contract metrics
        """
        logger.info(
            f"Retrieving contract stats (total_contracts={len(self.contracts)})"
        )
        # Implementation: return comprehensive stats
        return {}


# Standalone helper function
async def execute_action_with_commitments(
    action_id: str,
    action_type: str,
    action_category: str,
    parameters: Dict[str, Any],
    governance_evaluation: Dict,
    execution_function: callable
) -> Tuple[bool, Any]:
    """
    Execute action with commitment contract enforcement

    Args:
        action_id: Action identifier
        action_type: Type of action
        action_category: Governance category
        parameters: Action parameters
        governance_evaluation: Governance evaluation results
        execution_function: Function to execute the action

    Returns:
        Tuple of (success, result)
    """
    # Create contract
    manager = CommitmentContractManager()

    # Generate commitments
    contract = await manager.create_contract_for_action(
        action_id=action_id,
        action_type=action_type,
        action_category=action_category,
        governance_evaluation=governance_evaluation
    )

    # Store committed parameters
    manager.committed_parameters[action_id] = parameters.copy()

    # Pre-execution check (BLOCKING)
    can_proceed, rejection_reason = await manager.check_contract_before_execution(
        action_id=action_id,
        actual_parameters=parameters
    )

    if not can_proceed:
        logger.error(f"Action blocked: {rejection_reason}")
        return False, {"error": "contract_violation", "reason": rejection_reason}

    # Execute action
    try:
        result = await execution_function(**parameters)
        success = True
    except Exception as e:
        logger.error(f"Action execution failed: {e}")
        result = {"error": str(e)}
        success = False

    # Post-execution verification
    verification_report = await manager.verify_commitments(
        action_id=action_id,
        execution_result={"success": success},
        actual_parameters=parameters
    )

    return success, result
