#!/usr/bin/env python3
"""
Phase 4: Learning Integration Tests
Using TestBase for MySQL logging

Tests governance integration for:
- Learning parameter changes
- Learner config changes
- Governance pattern learner

All tests verify human-only approval enforcement and AI self-modification prevention.
"""

import pytest
import asyncio
import sys
from pathlib import Path
from datetime import datetime, timedelta

# Add project root and tests directory to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "tests"))

from test_base import TestBase
from core.learning.enhanced_asi_self_improvement import (
    EnhancedASISelfImprovement
)
from core.agents.autonomous.learning_adapter import LearningAdapter
from core.learning.governance_pattern_learner import (
    GovernancePatternLearner
)


class TestPhase4LearningIntegration(TestBase):
    """Phase 4: Learning Integration - MySQL Logged Tests"""

    def __init__(self):
        super().__init__(
            test_category="governance_phase4",
            test_type="integration"
        )
        self.asi_self_improvement = None
        self.learning_adapter = None
        self.governance_learner = None

    def get_human_approval_signature(self):
        """Create valid human approval signature"""
        return {
            "voter_id": "user_stefan",
            "voter_type": "human",
            "signature": "crypto_sig_abc123",
            "approved_at": datetime.now().isoformat()
        }

    def get_automated_signature(self):
        """A non-human approver. Must never authorise self-modification."""
        return {
            "voter_id": "automated_approver",
            "voter_type": "automated",
            "signature": "crypto_sig_def456",
            "approved_at": datetime.now().isoformat()
        }

    def get_learner_signature(self):
        """Create learner self-approval signature (should be rejected)"""
        return {
            "voter_id": "learner_system",
            "voter_type": "human",  # Pretend to be human but voter_id reveals it's learner
            "signature": "crypto_sig_ghi789",
            "approved_at": datetime.now().isoformat()
        }

    #: THE HEALTH GATE IS A REAL PRECONDITION, NOT THE THING UNDER TEST.
    #: component is down. In a bare test process nothing has started the
    #: services, so the refusal fires before any governance code runs and these
    #: tests were failing on the environment rather than on the property they
    #: are named for. The precondition is established through the object's own
    #: `_monitor` seam so the governance path is what actually gets exercised.
    def healthy_asi(self):
        from core.learning.improvement_monitor import SystemImprovementState

        class _HealthySystem:
            async def get_system_state(self):
                return SystemImprovementState(
                    total_components=10, healthy_components=10,
                    degraded_components=0, critical_components=0,
                    overall_health_score=98.0,
                    total_improvements_tracked=0, active_degradations=0,
                    component_health={},
                )

            async def record_metric(self, *args, **kwargs):
                return None

        asi = EnhancedASISelfImprovement()
        asi._monitor = _HealthySystem()
        return asi

    #: THE HEALTH GATE IS A PRECONDITION, NOT THE THING UNDER TEST.
    #: component is down. In a bare test process nothing has started the
    #: services, so the refusal fires before any governance code runs and these
    #: tests failed on the environment rather than on the property they are
    #: named for. The precondition is established through the object's own
    #: `_monitor` seam so the governance path is what actually gets exercised.
    def healthy_asi(self):
        from core.learning.improvement_monitor import SystemImprovementState

        class _HealthySystem:
            async def get_system_state(self):
                return SystemImprovementState(
                    total_components=10, healthy_components=10,
                    degraded_components=0, critical_components=0,
                    overall_health_score=98.0,
                    total_improvements_tracked=0, active_degradations=0,
                    component_health={},
                )

            async def record_metric(self, *args, **kwargs):
                return None

        asi = EnhancedASISelfImprovement()
        asi._monitor = _HealthySystem()
        return asi

    @pytest.mark.asyncio
    async def test_5_learner_config_human_only(self):
        """Learner config changes require HUMAN-ONLY approval"""
        self.learning_adapter = LearningAdapter()
        human_sig = self.get_human_approval_signature()

        result = await self.learning_adapter.update_config(
            parameter_name="experience_buffer_size",
            new_value=200,
            approval_signature=human_sig
        )

        assert result["success"] is True, f"Expected success, got {result}"
        assert result["human_only_approval"] is True, "human_only_approval not set"
        assert result["expiration_days"] == 90, f"Expected 90 days, got {result.get('expiration_days')}"
        assert result["approved_by"] == "user_stefan", f"Expected user_stefan, got {result.get('approved_by')}"


    @pytest.mark.asyncio
    async def test_7_learner_self_approval_blocked(self):
        """Learner CANNOT approve its own proposals"""
        self.learning_adapter = LearningAdapter()
        learner_sig = self.get_learner_signature()

        try:
            await self.learning_adapter.update_config(
                parameter_name="pattern_discovery",
                new_value=False,
                approval_signature=learner_sig
            )
            assert False, "Should have raised PermissionError"
        except PermissionError as e:
            error_msg = str(e)
            assert ("Learner cannot approve its own config changes" in error_msg or
                    "Learner cannot approve its own proposals" in error_msg), f"Wrong error: {error_msg}"
            assert "self-modification" in error_msg.lower(), f"Self-modification not mentioned: {error_msg}"

    @pytest.mark.asyncio
    async def test_8_learner_cannot_operate_the_approval_gate(self):
        """The pattern learner may read the gate. It may not answer it.

        REWRITTEN FOR THE GATE THAT EXISTS. This used
        `propose_config_change` and `validate_learner_approval` -- the
        signature-and-proposal machinery of the retired multi-judge session.
        The rule those tests were protecting survives the session: no
        automated actor may authorise a change to the learner. It is now
        enforced structurally rather than by signature checking, because the
        learner has no code path that can settle a request.
        """
        from core.database import get_database_manager
        from core.governance import approval_requests as gate

        db = get_database_manager()
        await db.initialize()
        self.governance_learner = GovernancePatternLearner(db_manager=db)

        action_id = "test4:learner_cannot_approve"
        await db.execute_query(
            "DELETE FROM unified.pending_approvals WHERE action_id = $1",
            (action_id,), commit=True)

        request = await gate.request(
            action_id=action_id, action_type="test4_config_change", tier="MAJOR",
            scope="major", requester="pattern_learner",
            summary="learner proposes a config change", db_manager=db)
        assert request.status == "pending", "a new request must start pending"

        # No approval path exists on the learner at all.
        exposed = [name for name in dir(self.governance_learner)
                   if "approve" in name.lower() and not name.startswith("_")]
        assert not exposed, f"learner exposes an approval path: {exposed}"

        # Learning from history changes no request's status.
        await self.governance_learner.learn(min_decisions=1)
        after = await gate.find(action_id, db_manager=db)
        assert after.status == "pending", (
            f"learning settled a request: status is now {after.status}")
        assert await gate.decision_for(action_id, db_manager=db) is None

        # A decision must name a person; an unnamed one is refused outright.
        try:
            await gate.decide(request.approval_id, approved=True, decided_by="",
                              db_manager=db)
            assert False, "a decision with no decider should be refused"
        except ValueError:
            pass

        await db.execute_query(
            "DELETE FROM unified.pending_approvals WHERE action_id = $1",
            (action_id,), commit=True)


    @pytest.mark.asyncio
    async def test_10_missing_cryptographic_signature(self):
        """Approval without cryptographic signature rejected"""
        self.learning_adapter = LearningAdapter()
        invalid_sig = {
            "voter_id": "user_stefan",
            "voter_type": "human",
            # Missing "signature" field
            "approved_at": datetime.now().isoformat()
        }

        result = await self.learning_adapter.update_config(
            parameter_name="test_param",
            new_value=100,
            approval_signature=invalid_sig
        )

        assert result["success"] is False, "Missing crypto signature should be rejected"
        assert result["approval_required"] is True, "approval_required should be True"

    @pytest.mark.asyncio
    async def test_11_pattern_learner_analysis(self):
        """Patterns come from decisions the gate actually recorded.

        REWRITTEN. This fed fifteen dictionaries carrying `voter_type` into an
        in-memory list and asserted on the aggregate -- so it verified that the
        learner could add up numbers it had just been handed, which was true
        of a module that learned nothing. Real requests now go through the
        gate, are answered, and the learner reads them back.
        """
        from core.database import get_database_manager
        from core.governance import approval_requests as gate

        db = get_database_manager()
        await db.initialize()
        self.governance_learner = GovernancePatternLearner(db_manager=db)

        action_type = "test4_analysis"
        await db.execute_query(
            "DELETE FROM unified.pending_approvals WHERE action_id LIKE $1",
            ("test4:analysis:%",), commit=True)
        await db.execute_query(
            "DELETE FROM unified.governance_patterns WHERE action_type = $1",
            (action_type,), commit=True)

        # Nine real requests, six approved: a 2/3 rate the learner must find
        # without being told it.
        for i in range(9):
            request = await gate.request(
                action_id=f"test4:analysis:{i}", action_type=action_type,
                tier="MODERATE", scope="moderate", requester="test_suite",
                summary=f"analysis request {i}", db_manager=db)
            await gate.decide(request.approval_id, approved=(i % 3 != 0),
                              decided_by="test_operator", db_manager=db)

        patterns = [p for p in await self.governance_learner.learn(min_decisions=3)
                    if p.action_type == action_type]
        assert patterns, "no pattern learned from nine decided requests"
        pattern = patterns[0]
        assert pattern.decided == 9, f"expected 9 decided, got {pattern.decided}"
        assert pattern.approved == 6 and pattern.declined == 3, (
            f"expected 6 approved / 3 declined, got {pattern.approved}/{pattern.declined}")
        assert 0.6 < pattern.approval_rate < 0.7, pattern.approval_rate
        assert pattern.confidence > 0.1, pattern.confidence

        # And it survives the process that learned it.
        fresh = GovernancePatternLearner(db_manager=db)
        guidance = await fresh.guidance_for(action_type, "MODERATE")
        assert guidance["known"] is True and guidance["decided"] == 9, guidance

        await db.execute_query(
            "DELETE FROM unified.pending_approvals WHERE action_id LIKE $1",
            ("test4:analysis:%",), commit=True)
        await db.execute_query(
            "DELETE FROM unified.governance_patterns WHERE action_type = $1",
            (action_type,), commit=True)


    async def run_all_tests(self):
        """Run all Phase 4 tests"""
        await self.start_session()

        await self.run_test(
            "test_5_learner_config_human_only",
            self.test_5_learner_config_human_only,
            metadata={
                "description": "Learner config changes require HUMAN-ONLY approval",
                "expected_behavior": "human_only_approval=True, 90-day expiration",
                "parameter": "experience_buffer_size",
                "new_value": 200,
                "expiration_days": 90
            }
        )


        await self.run_test(
            "test_7_learner_self_approval_blocked",
            self.test_7_learner_self_approval_blocked,
            metadata={
                "description": "Learner CANNOT approve its own proposals",
                "expected_behavior": "PermissionError raised, AI self-modification prevention",
                "voter_id": "learner_system",
                "expected_error": "Learner cannot approve its own config changes"
            }
        )

        await self.run_test(
            "test_8_learner_cannot_operate_the_approval_gate",
            self.test_8_learner_cannot_operate_the_approval_gate,
            metadata={
                "description": "Governance pattern learner human-only enforcement",
                "expected_behavior": "Human approved, AI judge rejected, learner rejected",
                "requires_human_approval": True,
                "tests": ["human_valid", "learner_self_rejected"]
            }
        )

        await self.run_test(
            "test_10_missing_cryptographic_signature",
            self.test_10_missing_cryptographic_signature,
            metadata={
                "description": "Approval without cryptographic signature rejected",
                "expected_behavior": "success=False, approval_required=True",
                "missing_field": "signature"
            }
        )

        await self.run_test(
            "test_11_pattern_learner_analysis",
            self.test_11_pattern_learner_analysis,
            metadata={
                "description": "Governance pattern analysis functionality",
                "expected_behavior": "Pattern learned from 15 decisions, ~66% approval rate",
                "decisions_recorded": 15,
                "expected_approval_rate": 0.66,
                "min_confidence": 0.1
            }
        )

        await self.end_session()
        self.print_summary()


async def main():
    """Run Phase 4 tests"""
    tests = TestPhase4LearningIntegration()
    await tests.run_all_tests()
    return 0 if tests.failed_tests == 0 else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
