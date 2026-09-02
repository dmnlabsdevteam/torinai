#!/usr/bin/env python3
"""
Directive Manager - Complete CRUD Operations

Handles all database operations for the directive system.
100% implementation
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from contextlib import asynccontextmanager

from core.agents.autonomous.directive_types import (
    InternalDirective,
    DirectiveCategory,
    DirectiveStatus,
    DirectiveApplication,
    ContextType,
    DirectiveEvolution,
    EvolutionType,
    GovernanceLaw,
    DirectiveABTest,
    ABTestStatus,
    DirectivePerformanceReport
)
from core.database import TorinUnifiedDatabase, get_unified_db

logger = logging.getLogger(__name__)


class DirectiveManager:
    """
    Complete directive database manager with full CRUD operations.

    Responsibilities:
    - Create, read, update, delete directives
    - Log directive applications
    - Track evolution history
    - Store governance evaluations
    - Manage A/B tests
    - Calculate performance metrics
    """

    def __init__(self, db: Optional[TorinUnifiedDatabase] = None):
        """
        Initialize directive manager.

        Args:
            db: Database instance (will use singleton if not provided)
        """
        self.db = db  # Will be set to singleton in initialize() if None
        self.initialized = False

    async def initialize(self) -> bool:
        """Initialize database connection"""
        if not self.initialized:
            # Get unified database singleton if not provided
            if self.db is None:
                self.db = await get_unified_db()
            self.initialized = True
            logger.info("DirectiveManager initialized")
        return True

    # =========================================================================
    # GOVERNANCE LAWS - Read Only (Immutable)
    # =========================================================================

    async def get_all_governance_laws(self) -> List[GovernanceLaw]:
        """
        Get all governance laws from database.
        These laws are immutable and guide all directive evaluations.

        Returns:
            List of GovernanceLaw objects
        """
        async with self.db.get_connection() as conn:
            rows = await conn.fetch(
                "SELECT law_id, law_number, law_name, law_description, "
                "requirements, created_at, immutable "
                "FROM governance_laws ORDER BY law_number"
            )

        laws = []
        for row in rows:
            laws.append(GovernanceLaw(
                law_id=row[0],
                law_number=row[1],
                law_name=row[2],
                law_description=row[3],
                requirements=json.loads(row[4]),
                created_at=row[5],
                immutable=bool(row[6])
            ))

        logger.info(f"Loaded {len(laws)} governance laws")
        return laws

    async def get_governance_law(self, law_number: int) -> Optional[GovernanceLaw]:
        """
        Get specific governance law by number.

        Args:
            law_number: Law number (1-5)

        Returns:
            GovernanceLaw object or None
        """
        async with self.db.get_connection() as conn:
            row = await conn.fetchrow(
                "SELECT law_id, law_number, law_name, law_description, "
                "requirements, created_at, immutable "
                "FROM governance_laws WHERE law_number = $1",
                law_number
            )

        if not row:
            return None

        return GovernanceLaw(
            law_id=row[0],
            law_number=row[1],
            law_name=row[2],
            law_description=row[3],
            requirements=json.loads(row[4]),
            created_at=row[5],
            immutable=bool(row[6])
        )

    # =========================================================================
    # DIRECTIVE - CRUD Operations
    # =========================================================================

    async def create_directive(self, directive: InternalDirective) -> bool:
        """
        Create a new directive in the database.

        Args:
            directive: InternalDirective object to create

        Returns:
            True if successful
        """
        async with self.db.get_connection() as conn:
            await conn.execute(
                """
                INSERT INTO internal_directives (
                    directive_id, directive_name, directive_category,
                    directive_text, directive_parameters,
                    version, parent_directive_id,
                    status, activation_date, deprecation_date,
                    total_applications, successful_applications,
                    avg_outcome_quality, avg_intrinsic_reward,
                    avg_constitutional_alignment, avg_system_health_impact,
                    test_group, test_id,
                    governance_validated, constitutional_validated,
                    created_at, updated_at
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                    $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21, $22
                )
                """,
                directive.directive_id,
                directive.directive_name,
                directive.directive_category.value,
                directive.directive_text,
                json.dumps(directive.directive_parameters),
                directive.version,
                directive.parent_directive_id,
                directive.status.value,
                directive.activation_date,
                directive.deprecation_date,
                directive.total_applications,
                directive.successful_applications,
                directive.avg_outcome_quality,
                directive.avg_intrinsic_reward,
                directive.avg_constitutional_alignment,
                directive.avg_system_health_impact,
                directive.test_group,
                directive.test_id,
                directive.governance_validated,
                directive.constitutional_validated,
                directive.created_at,
                directive.updated_at
            )

        logger.info(f"Created directive: {directive.directive_id} ({directive.directive_name})")
        return True

    async def get_directive(self, directive_id: str) -> Optional[InternalDirective]:
        """
        Get directive by ID.

        Args:
            directive_id: Directive ID

        Returns:
            InternalDirective object or None
        """
        async with self.db.get_connection() as conn:
            row = await conn.fetchrow(
                """
                SELECT directive_id, directive_name, directive_category,
                       directive_text, directive_parameters,
                       version, parent_directive_id,
                       status, activation_date, deprecation_date,
                       total_applications, successful_applications,
                       avg_outcome_quality, avg_intrinsic_reward,
                       avg_constitutional_alignment, avg_system_health_impact,
                       test_group, test_id,
                       governance_validated, constitutional_validated,
                       created_at, updated_at
                FROM internal_directives
                WHERE directive_id = $1
                """,
                directive_id
            )

        if not row:
            return None

        return self._row_to_directive(row)

    async def get_directives_by_status(self, status: DirectiveStatus) -> List[InternalDirective]:
        """
        Get all directives with a specific status.

        Args:
            status: DirectiveStatus enum

        Returns:
            List of InternalDirective objects
        """
        async with self.db.get_connection() as conn:
            rows = await conn.fetch(
                """
                SELECT directive_id, directive_name, directive_category,
                       directive_text, directive_parameters,
                       version, parent_directive_id,
                       status, activation_date, deprecation_date,
                       total_applications, successful_applications,
                       avg_outcome_quality, avg_intrinsic_reward,
                       avg_constitutional_alignment, avg_system_health_impact,
                       test_group, test_id,
                       governance_validated, constitutional_validated,
                       created_at, updated_at
                FROM internal_directives
                WHERE status = $1
                ORDER BY avg_outcome_quality DESC
                """,
                status.value
            )

        return [self._row_to_directive(row) for row in rows]

    async def get_directives_by_category(
        self,
        category: DirectiveCategory,
        status: Optional[DirectiveStatus] = None
    ) -> List[InternalDirective]:
        """
        Get directives by category, optionally filtered by status.

        Args:
            category: DirectiveCategory enum
            status: Optional DirectiveStatus filter

        Returns:
            List of InternalDirective objects
        """
        async with self.db.get_connection() as conn:
            if status:
                rows = await conn.fetch(
                    """
                    SELECT directive_id, directive_name, directive_category,
                           directive_text, directive_parameters,
                           version, parent_directive_id,
                           status, activation_date, deprecation_date,
                           total_applications, successful_applications,
                           avg_outcome_quality, avg_intrinsic_reward,
                           avg_constitutional_alignment, avg_system_health_impact,
                           test_group, test_id,
                           governance_validated, constitutional_validated,
                           created_at, updated_at
                    FROM internal_directives
                    WHERE directive_category = $1 AND status = $2
                    ORDER BY avg_outcome_quality DESC
                    """,
                    category.value, status.value
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT directive_id, directive_name, directive_category,
                           directive_text, directive_parameters,
                           version, parent_directive_id,
                           status, activation_date, deprecation_date,
                           total_applications, successful_applications,
                           avg_outcome_quality, avg_intrinsic_reward,
                           avg_constitutional_alignment, avg_system_health_impact,
                           test_group, test_id,
                           governance_validated, constitutional_validated,
                           created_at, updated_at
                    FROM internal_directives
                    WHERE directive_category = $1
                    ORDER BY avg_outcome_quality DESC
                    """,
                    category.value
                )

        return [self._row_to_directive(row) for row in rows]

    async def get_all_directives(self) -> List[InternalDirective]:
        """
        Get all directives from database.

        Returns:
            List of all InternalDirective objects, ordered by performance
        """
        async with self.db.get_connection() as conn:
            rows = await conn.fetch(
                """
                SELECT directive_id, directive_name, directive_category,
                       directive_text, directive_parameters,
                       version, parent_directive_id,
                       status, activation_date, deprecation_date,
                       total_applications, successful_applications,
                       avg_outcome_quality, avg_intrinsic_reward,
                       avg_constitutional_alignment, avg_system_health_impact,
                       test_group, test_id,
                       governance_validated, constitutional_validated,
                       created_at, updated_at
                FROM internal_directives
                ORDER BY avg_outcome_quality DESC
                """
            )

        return [self._row_to_directive(row) for row in rows]

    async def update_directive(self, directive: InternalDirective) -> bool:
        """
        Update an existing directive.

        Args:
            directive: InternalDirective object with updated values

        Returns:
            True if successful
        """
        directive.updated_at = datetime.now()

        async with self.db.get_connection() as conn:
            await conn.execute(
                """
                UPDATE internal_directives SET
                    directive_name = $1,
                    directive_category = $2,
                    directive_text = $3,
                    directive_parameters = $4,
                    version = $5,
                    parent_directive_id = $6,
                    status = $7,
                    activation_date = $8,
                    deprecation_date = $9,
                    total_applications = $10,
                    successful_applications = $11,
                    avg_outcome_quality = $12,
                    avg_intrinsic_reward = $13,
                    avg_constitutional_alignment = $14,
                    avg_system_health_impact = $15,
                    test_group = $16,
                    test_id = $17,
                    governance_validated = $18,
                    constitutional_validated = $19,
                    updated_at = $20
                WHERE directive_id = $21
                """,
                directive.directive_name,
                directive.directive_category.value,
                directive.directive_text,
                json.dumps(directive.directive_parameters),
                directive.version,
                directive.parent_directive_id,
                directive.status.value,
                directive.activation_date,
                directive.deprecation_date,
                directive.total_applications,
                directive.successful_applications,
                directive.avg_outcome_quality,
                directive.avg_intrinsic_reward,
                directive.avg_constitutional_alignment,
                directive.avg_system_health_impact,
                directive.test_group,
                directive.test_id,
                directive.governance_validated,
                directive.constitutional_validated,
                directive.updated_at,
                directive.directive_id
            )

        logger.info(f"Updated directive: {directive.directive_id}")
        return True

    async def delete_directive(self, directive_id: str) -> bool:
        """
        Delete a directive (use with caution - prefer deprecation).

        Args:
            directive_id: Directive ID to delete

        Returns:
            True if successful
        """
        async with self.db.get_connection() as conn:
            await conn.execute(
                "DELETE FROM internal_directives WHERE directive_id = $1",
                directive_id
            )

        logger.warning(f"Deleted directive: {directive_id}")
        return True

    async def deprecate_directive(self, directive_id: str, reason: str) -> bool:
        """
        Deprecate a directive (preferred over deletion).

        Args:
            directive_id: Directive ID to deprecate
            reason: Reason for deprecation

        Returns:
            True if successful
        """
        directive = await self.get_directive(directive_id)
        if not directive:
            logger.error(f"Directive not found: {directive_id}")
            return False

        directive.status = DirectiveStatus.DEPRECATED
        directive.deprecation_date = datetime.now()

        await self.update_directive(directive)

        # Log evolution
        await self.log_evolution(
            directive_id=directive_id,
            evolution_type=EvolutionType.DEPRECATED,
            previous_version=directive.version,
            new_version=directive.version,
            changes={"status": "deprecated"},
            trigger_reason=reason
        )

        logger.info(f"Deprecated directive: {directive_id} - {reason}")
        return True

    # =========================================================================
    # DIRECTIVE APPLICATIONS
    # =========================================================================

    async def log_application(self, application: DirectiveApplication) -> bool:
        """
        Log a directive application.

        Args:
            application: DirectiveApplication object

        Returns:
            True if successful
        """
        async with self.db.get_connection() as conn:
            await conn.execute(
                """
                INSERT INTO directive_applications (
                    application_id, directive_id,
                    applied_at, context_type, context_data, decision_made,
                    outcome_quality, intrinsic_reward,
                    constitutional_alignment, system_health_impact, success,
                    completed_at, evaluation_completed
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13
                )
                """,
                application.application_id,
                application.directive_id,
                application.applied_at,
                application.context_type.value,
                json.dumps(application.context_data),
                application.decision_made,
                application.outcome_quality,
                application.intrinsic_reward,
                application.constitutional_alignment,
                application.system_health_impact,
                application.success,
                application.completed_at,
                application.evaluation_completed
            )

        logger.debug(f"Logged application: {application.application_id} for directive {application.directive_id}")
        return True

    async def update_application_outcome(
        self,
        application_id: str,
        outcome_quality: float,
        intrinsic_reward: float,
        constitutional_alignment: float,
        system_health_impact: float,
        success: bool
    ) -> bool:
        """
        Update application with outcome metrics.

        Args:
            application_id: Application ID
            outcome_quality: Quality score (0.0-1.0)
            intrinsic_reward: Intrinsic reward score (0.0-1.0)
            constitutional_alignment: Constitutional alignment score (0.0-1.0)
            system_health_impact: System health impact score (0.0-1.0)
            success: Whether the application was successful

        Returns:
            True if successful
        """
        async with self.db.get_connection() as conn:
            await conn.execute(
                """
                UPDATE directive_applications SET
                    outcome_quality = $1,
                    intrinsic_reward = $2,
                    constitutional_alignment = $3,
                    system_health_impact = $4,
                    success = $5,
                    completed_at = $6,
                    evaluation_completed = TRUE
                WHERE application_id = $7
                """,
                outcome_quality,
                intrinsic_reward,
                constitutional_alignment,
                system_health_impact,
                success,
                datetime.now(),
                application_id
            )

        # Trigger directive performance update
        async with self.db.get_connection() as conn:
            # Get directive_id from application
            row = await conn.fetchrow(
                "SELECT directive_id FROM directive_applications WHERE application_id = $1",
                application_id
            )
            if row:
                directive_id = row[0]
                await self.update_directive_performance(directive_id)

        logger.info(f"Updated application outcome: {application_id}")
        return True

    async def get_directive_applications(
        self,
        directive_id: str,
        hours_lookback: Optional[int] = None
    ) -> List[DirectiveApplication]:
        """
        Get applications for a directive.

        Args:
            directive_id: Directive ID
            hours_lookback: Optional lookback window in hours

        Returns:
            List of DirectiveApplication objects
        """
        async with self.db.get_connection() as conn:
            if hours_lookback:
                cutoff = datetime.now() - timedelta(hours=hours_lookback)
                rows = await conn.fetch(
                    """
                    SELECT application_id, directive_id,
                           applied_at, context_type, context_data, decision_made,
                           outcome_quality, intrinsic_reward,
                           constitutional_alignment, system_health_impact, success,
                           completed_at, evaluation_completed
                    FROM directive_applications
                    WHERE directive_id = $1 AND applied_at >= $2
                    ORDER BY applied_at DESC
                    """,
                    directive_id, cutoff
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT application_id, directive_id,
                           applied_at, context_type, context_data, decision_made,
                           outcome_quality, intrinsic_reward,
                           constitutional_alignment, system_health_impact, success,
                           completed_at, evaluation_completed
                    FROM directive_applications
                    WHERE directive_id = $1
                    ORDER BY applied_at DESC
                    """,
                    directive_id
                )

        applications = []
        for row in rows:
            applications.append(DirectiveApplication(
                application_id=row[0],
                directive_id=row[1],
                applied_at=row[2],
                context_type=ContextType(row[3]),
                context_data=json.loads(row[4]),
                decision_made=row[5],
                outcome_quality=row[6],
                intrinsic_reward=row[7],
                constitutional_alignment=row[8],
                system_health_impact=row[9],
                success=row[10],
                completed_at=row[11],
                evaluation_completed=bool(row[12])
            ))

        return applications

    # =========================================================================
    # DIRECTIVE PERFORMANCE
    # =========================================================================

    async def update_directive_performance(self, directive_id: str) -> bool:
        """
        Recalculate and update directive performance metrics from applications.

        Args:
            directive_id: Directive ID

        Returns:
            True if successful
        """
        async with self.db.get_connection() as conn:
            # Call the stored procedure
            await conn.execute(
                "CALL update_directive_performance($1)",
                directive_id
            )

        logger.debug(f"Updated performance for directive: {directive_id}")
        return True

    # =========================================================================
    # DIRECTIVE EVOLUTION
    # =========================================================================

    async def log_evolution(
        self,
        directive_id: str,
        evolution_type: EvolutionType,
        previous_version: Optional[int],
        new_version: int,
        changes: Dict[str, Any],
        trigger_reason: str,
        improvement_score: Optional[float] = None,
        performance_metrics: Optional[Dict[str, float]] = None
    ) -> str:
        """
        Log a directive evolution event.

        Args:
            directive_id: Directive ID
            evolution_type: Type of evolution
            previous_version: Previous version number
            new_version: New version number
            changes: Dict of changes made
            trigger_reason: Reason for evolution
            improvement_score: Optional improvement score
            performance_metrics: Optional performance metrics

        Returns:
            Evolution ID
        """
        evolution_id = DirectiveEvolution.generate_id()

        async with self.db.get_connection() as conn:
            await conn.execute(
                """
                INSERT INTO directive_evolution_log (
                    evolution_id, directive_id, evolution_type,
                    previous_version, new_version,
                    changes, improvement_score,
                    trigger_reason, performance_metrics,
                    evolved_at
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10
                )
                """,
                evolution_id,
                directive_id,
                evolution_type.value,
                previous_version,
                new_version,
                json.dumps(changes),
                improvement_score,
                trigger_reason,
                json.dumps(performance_metrics) if performance_metrics else None,
                datetime.now()
            )

        logger.info(f"Logged evolution: {evolution_id} for directive {directive_id}")
        return evolution_id

    # =========================================================================
    # GOVERNANCE EVALUATIONS
    # =========================================================================

    # NOTE (2026-09-02): store_governance_evaluation was REMOVED with the
    # five-judge vote. Directive governance is now a constitution validation
    # (model-free) recorded on the directive itself (governance_validated) and in
    # the evolution log, not a persisted multi-agent GovernanceEvaluation. The
    # directive_governance_evaluations table is no longer written. Archived in
    # archive/llm_era_directive_governance_2026-09-02/.

    # =========================================================================
    # A/B TESTS
    # =========================================================================

    async def create_ab_test(self, ab_test: DirectiveABTest) -> bool:
        """
        Create a new A/B test.

        Args:
            ab_test: DirectiveABTest object

        Returns:
            True if successful
        """
        async with self.db.get_connection() as conn:
            await conn.execute(
                """
                INSERT INTO directive_ab_tests (
                    test_id, test_name,
                    control_directive_id, variant_directives,
                    duration_hours, min_applications_per_variant, required_confidence,
                    status, winning_variant, confidence_level,
                    results_summary, statistical_analysis,
                    started_at, ended_at
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14
                )
                """,
                ab_test.test_id,
                ab_test.test_name,
                ab_test.control_directive_id,
                json.dumps(ab_test.variant_directive_ids),
                ab_test.duration_hours,
                ab_test.min_applications_per_variant,
                ab_test.required_confidence,
                ab_test.status.value,
                ab_test.winning_variant,
                ab_test.confidence_level,
                json.dumps(ab_test.results_summary) if ab_test.results_summary else None,
                json.dumps(ab_test.statistical_analysis) if ab_test.statistical_analysis else None,
                ab_test.started_at,
                ab_test.ended_at
            )

        logger.info(f"Created A/B test: {ab_test.test_id} - {ab_test.test_name}")
        return True

    async def update_ab_test(self, ab_test: DirectiveABTest) -> bool:
        """
        Update an A/B test.

        Args:
            ab_test: DirectiveABTest object with updated values

        Returns:
            True if successful
        """
        async with self.db.get_connection() as conn:
            await conn.execute(
                """
                UPDATE directive_ab_tests SET
                    status = $1,
                    winning_variant = $2,
                    confidence_level = $3,
                    results_summary = $4,
                    statistical_analysis = $5,
                    ended_at = $6
                WHERE test_id = $7
                """,
                ab_test.status.value,
                ab_test.winning_variant,
                ab_test.confidence_level,
                json.dumps(ab_test.results_summary) if ab_test.results_summary else None,
                json.dumps(ab_test.statistical_analysis) if ab_test.statistical_analysis else None,
                ab_test.ended_at,
                ab_test.test_id
            )

        logger.info(f"Updated A/B test: {ab_test.test_id}")
        return True

    async def get_ab_test(self, test_id: str) -> Optional[DirectiveABTest]:
        """
        Get A/B test by ID.

        Args:
            test_id: Test ID

        Returns:
            DirectiveABTest object or None
        """
        async with self.db.get_connection() as conn:
            row = await conn.fetchrow(
                """
                SELECT test_id, test_name,
                       control_directive_id, variant_directives,
                       duration_hours, min_applications_per_variant, required_confidence,
                       status, winning_variant, confidence_level,
                       results_summary, statistical_analysis,
                       started_at, ended_at
                FROM directive_ab_tests
                WHERE test_id = $1
                """,
                test_id
            )

        if not row:
            return None

        return DirectiveABTest(
            test_id=row[0],
            test_name=row[1],
            control_directive_id=row[2],
            variant_directive_ids=json.loads(row[3]),
            duration_hours=row[4],
            min_applications_per_variant=row[5],
            required_confidence=row[6],
            status=ABTestStatus(row[7]),
            winning_variant=row[8],
            confidence_level=row[9],
            results_summary=json.loads(row[10]) if row[10] else None,
            statistical_analysis=json.loads(row[11]) if row[11] else None,
            started_at=row[12],
            ended_at=row[13]
        )

    async def get_active_ab_tests(self) -> List[DirectiveABTest]:
        """
        Get all active A/B tests.

        Returns:
            List of DirectiveABTest objects
        """
        async with self.db.get_connection() as conn:
            rows = await conn.fetch(
                """
                SELECT test_id, test_name,
                       control_directive_id, variant_directives,
                       duration_hours, min_applications_per_variant, required_confidence,
                       status, winning_variant, confidence_level,
                       results_summary, statistical_analysis,
                       started_at, ended_at
                FROM directive_ab_tests
                WHERE status = 'running'
                ORDER BY started_at DESC
                """
            )

        tests = []
        for row in rows:
            tests.append(DirectiveABTest(
                test_id=row[0],
                test_name=row[1],
                control_directive_id=row[2],
                variant_directive_ids=json.loads(row[3]),
                duration_hours=row[4],
                min_applications_per_variant=row[5],
                required_confidence=row[6],
                status=ABTestStatus(row[7]),
                winning_variant=row[8],
                confidence_level=row[9],
                results_summary=json.loads(row[10]) if row[10] else None,
                statistical_analysis=json.loads(row[11]) if row[11] else None,
                started_at=row[12],
                ended_at=row[13]
            ))

        return tests

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    def _row_to_directive(self, row) -> InternalDirective:
        """Convert database row to InternalDirective object"""
        return InternalDirective(
            directive_id=row[0],
            directive_name=row[1],
            directive_category=DirectiveCategory(row[2]),
            directive_text=row[3],
            directive_parameters=json.loads(row[4]),
            version=row[5],
            parent_directive_id=row[6],
            status=DirectiveStatus(row[7]),
            activation_date=row[8],
            deprecation_date=row[9],
            total_applications=row[10],
            successful_applications=row[11],
            avg_outcome_quality=float(row[12]) if row[12] else 0.0,
            avg_intrinsic_reward=float(row[13]) if row[13] else 0.0,
            avg_constitutional_alignment=float(row[14]) if row[14] else 0.0,
            avg_system_health_impact=float(row[15]) if row[15] else 0.0,
            test_group=row[16],
            test_id=row[17],
            governance_validated=bool(row[18]),
            constitutional_validated=bool(row[19]),
            created_at=row[20],
            updated_at=row[21]
        )

    async def close(self):
        """Close database connection"""
        if self.db:
            await self.db.close()
            logger.info("DirectiveManager closed")
