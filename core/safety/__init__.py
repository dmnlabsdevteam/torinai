"""
Safety Module

Multi-layered AI safety systems for autonomous operation.

Main Components:
- MultiLevelSafetyPrompts: Layered safety constraints (system, meta, action prompts)
- CommitmentContract: Pre/post-action commitment verification

Usage:
    from core.safety import MultiLevelSafetyPrompts, CommitmentContract, CommitmentType

    # Multi-level safety prompts
    safety_prompts = MultiLevelSafetyPrompts()

    prompt = safety_prompts.build_complete_prompt(
        task="Analyze system performance",
        context={"execution_mode": "autonomous", "risk_level": "LOW"},
        pending_action={"type": "read_logs", "parameters": {}}
    )

    # Commitment contracts
    contract = CommitmentContract(action_id="action_123", action_type="execute_tool")

    await contract.make_commitment(
        commitment_type=CommitmentType.OUTCOME,
        commitment_statement="This action will improve performance without data loss",
        verification_method="automated_check"
    )

    # ... execute action ...

    verification_report = await contract.verify_commitments(
        action_result=result,
        execution_context=context
    )
"""

from core.safety.multi_level_prompts import (
    MultiLevelSafetyPrompts,
    SafetyPromptIntegration,
    verify_safety_prompt_compliance
)

from core.safety.commitment_contracts import (
    CommitmentContract,
    CommitmentType,
    ViolationSeverity,
    Commitment,
    VerificationResult,
    CommitmentVerificationReport,
    execute_action_with_commitments
)

__all__ = [
    # Multi-Level Safety Prompts
    "MultiLevelSafetyPrompts",
    "SafetyPromptIntegration",
    "verify_safety_prompt_compliance",

    # Commitment Contracts
    "CommitmentContract",
    "CommitmentType",
    "ViolationSeverity",
    "Commitment",
    "VerificationResult",
    "CommitmentVerificationReport",
    "execute_action_with_commitments",
]
