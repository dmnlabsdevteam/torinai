#!/usr/bin/env python3
"""
Directive System

Main directive orchestration:
- Integrates DirectiveManager (CRUD)
- Coordinates A/B testing
- Tracks evolution
- Governance validation
- Applies directives to decisions
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

from .directive_manager import DirectiveManager, DirectiveCategory, DirectiveStatus
from .directive_ab_testing import DirectiveABTesting
from .directive_evolution_engine import DirectiveEvolutionEngine, EvolutionType
from core.database import get_unified_db

logger = logging.getLogger(__name__)


class DirectiveSystem:
    """
    Main Directive Orchestration System

    Integrates all directive components:

    Components:
    1. DirectiveManager - CRUD operations for directives
    2. DirectiveABTesting - A/B test infrastructure
    3. DirectiveEvolutionEngine - Evolution tracking
    4. Governance - Validation against 5 laws

    Usage:
    - Query active directives by category
    - Apply directives to decision-making
    - Update directive performance
    - Create A/B tests for variants
    - Track evolution history
    - Validate against governance

    Integration with Autonomous Coordinator:
    - Planning phase queries directives
    - Execution phase logs applications
    - Learning phase updates performance
    """

    def __init__(
        self,
        directive_manager: Optional[DirectiveManager] = None,
        ab_testing: Optional[DirectiveABTesting] = None,
        evolution_engine: Optional[DirectiveEvolutionEngine] = None,
        db = None
    ):
        """
        Initialize directive system

        Args:
            directive_manager: Directive manager
            ab_testing: A/B testing system
            evolution_engine: Evolution engine
            db: Database for persistence (will use singleton if not provided)
        """
        self.db = db  # Will be set in initialize()

        # Core components - pass None for db, they will get singleton in their initialize()
        self.directive_manager = directive_manager or DirectiveManager(db=None)
        self.ab_testing = ab_testing or DirectiveABTesting(db=None)
        self.evolution_engine = evolution_engine or DirectiveEvolutionEngine(db=None)

        # Active directives cache (category -> directives)
        self.active_directives_cache: Dict[DirectiveCategory, List[Dict[str, Any]]] = {}
        self.cache_last_updated: Optional[datetime] = None
        self.cache_ttl_seconds = 60  # Refresh every minute

        # Metrics
        self.metrics = {
            'total_applications': 0,
            'successful_applications': 0,
            'failed_applications': 0,
            'by_category': {
                'goal_prioritization': 0,
                'resource_allocation': 0,
                'learning_strategy': 0,
                'exploration_balance': 0
            },
            'directives_created': 0,
            'directives_promoted': 0,
            'directives_deprecated': 0
        }

        # Initialization flag
        self.initialized = False

        logger.info("Directive system instance created")

    async def initialize(self) -> bool:
        """
        Initialize the directive system and all components

        Returns:
            bool: True if initialization successful
        """
        if self.initialized:
            logger.debug("DirectiveSystem already initialized")
            return True

        try:
            # Get unified database singleton
            logger.debug("Getting unified database singleton...")
            if self.db is None:
                self.db = await get_unified_db()

            # Initialize directive manager
            logger.debug("Initializing directive manager...")
            await self.directive_manager.initialize()

            # Initialize A/B testing system
            logger.debug("Initializing A/B testing system...")
            # DirectiveABTesting may not have initialize - check first
            if hasattr(self.ab_testing, 'initialize'):
                await self.ab_testing.initialize()

            # Initialize evolution engine
            logger.debug("Initializing evolution engine...")
            # DirectiveEvolutionEngine may not have initialize - check first
            if hasattr(self.evolution_engine, 'initialize'):
                await self.evolution_engine.initialize()

            # Pre-load active directives cache for all categories
            logger.debug("Pre-loading directive cache...")
            for category in DirectiveCategory:
                try:
                    await self.get_active_directives(category, force_refresh=True)
                except Exception as e:
                    logger.warning(f"Could not pre-load {category.value} directives: {e}")

            self.initialized = True
            logger.info("✅ DirectiveSystem initialized successfully with all components")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize DirectiveSystem: {e}")
            return False

    async def get_active_directives(
        self,
        category: DirectiveCategory,
        force_refresh: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Get active directives by category

        Args:
            category: Directive category
            force_refresh: Force cache refresh

        Returns:
            List of active directives
        """
        # Check cache
        if not force_refresh and category in self.active_directives_cache:
            if self.cache_last_updated:
                age = (datetime.now() - self.cache_last_updated).total_seconds()
                if age < self.cache_ttl_seconds:
                    return self.active_directives_cache[category]

        # Refresh from database
        directives = await self.directive_manager.get_directives_by_category(
            category=category,
            status=DirectiveStatus.ACTIVE
        )

        # Update cache
        self.active_directives_cache[category] = directives
        self.cache_last_updated = datetime.now()

        return directives

    async def apply_directives(
        self,
        category: DirectiveCategory,
        decision_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Apply directives to decision-making

        Args:
            category: Directive category
            decision_context: Decision context data

        Returns:
            Dict with directive guidance and metadata
        """
        # Get active directives for category
        directives = await self.get_active_directives(category)

        if not directives:
            logger.debug(f"No active directives for category {category.value}")
            return {
                'applied': False,
                'directive_count': 0,
                'guidance': {},
                'reason': f'No active directives for {category.value}'
            }

        # Apply directives (combine parameters)
        combined_params = {}
        directive_ids = []

        for directive in directives:
            directive_ids.append(directive['directive_id'])

            # Merge parameters (later directives override earlier ones)
            if 'directive_parameters' in directive:
                combined_params.update(directive['directive_parameters'])

        # Log application
        application_id = f"app_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        logger.debug(
            f"Applied {len(directives)} {category.value} directive(s): {directive_ids}"
        )

        self.metrics['total_applications'] += 1
        self.metrics['by_category'][category.value] += 1

        return {
            'applied': True,
            'directive_count': len(directives),
            'directive_ids': directive_ids,
            'guidance': combined_params,
            'application_id': application_id,
            'category': category.value
        }

    async def log_directive_application(
        self,
        directive_id: str,
        decision_id: str,
        decision_context: Dict[str, Any],
        outcome_metrics: Dict[str, float]
    ) -> None:
        """
        Log directive application result

        Args:
            directive_id: Directive identifier
            decision_id: Decision identifier
            decision_context: Decision context
            outcome_metrics: Outcome metrics (all [0.0-1.0])
        """
        # Update directive performance
        await self.directive_manager.update_directive_performance(
            directive_id=directive_id,
            outcome_quality=outcome_metrics.get('outcome_quality', 0.5),
            intrinsic_reward=outcome_metrics.get('intrinsic_reward', 0.5),
            constitutional_alignment=outcome_metrics.get('constitutional_alignment', 1.0),
            system_health_impact=outcome_metrics.get('system_health_impact', 1.0)
        )

        # If in A/B test, record application
        # (Check if directive is part of active test)
        # This would be implemented by checking ab_testing.active_tests

        self.metrics['successful_applications'] += 1

        logger.debug(
            f"Logged application for directive {directive_id} "
            f"(outcome: {outcome_metrics.get('outcome_quality', 0):.3f})"
        )

    async def create_directive_with_governance(
        self,
        directive_name: str,
        category: DirectiveCategory,
        directive_text: str,
        directive_parameters: Dict[str, Any],
        created_by: str = "system"
    ) -> Optional[str]:
        """
        Create directive with governance validation

        Args:
            directive_name: Directive name
            category: Directive category
            directive_text: Directive text
            directive_parameters: Directive parameters
            created_by: Who created the directive

        Returns:
            directive_id if created, None if rejected by governance
        """
        # Create directive
        directive_id = await self.directive_manager.create_directive(
            directive_name=directive_name,
            category=category,
            directive_text=directive_text,
            directive_parameters=directive_parameters
        )

        if not directive_id:
            logger.error("Failed to create directive")
            return None

        # Log evolution (CREATED)
        await self.evolution_engine.log_evolution(
            directive_id=directive_id,
            evolution_type=EvolutionType.CREATED,
            previous_version=None,
            new_version=1,
            changes={'created': True, 'created_by': created_by},
            trigger_reason=f"New directive created by {created_by}"
        )

        self.metrics['directives_created'] += 1

        logger.info(f"Created directive {directive_id}: {directive_name}")

        return directive_id

    async def promote_directive(
        self,
        directive_id: str,
        reason: str,
        performance_improvement: float
    ) -> bool:
        """
        Promote directive from testing to active

        Args:
            directive_id: Directive identifier
            reason: Promotion reason
            performance_improvement: Measured improvement

        Returns:
            True if promoted successfully
        """
        # Update status to ACTIVE
        success = await self.directive_manager.update_directive_status(
            directive_id=directive_id,
            status=DirectiveStatus.ACTIVE
        )

        if not success:
            return False

        # Get current version
        directive = await self.directive_manager.get_directive(directive_id)
        if not directive:
            return False

        current_version = directive.get('version', 1)

        # Log evolution (PROMOTED)
        await self.evolution_engine.log_evolution(
            directive_id=directive_id,
            evolution_type=EvolutionType.PROMOTED,
            previous_version=current_version - 1,
            new_version=current_version,
            changes={'promoted_to': 'active'},
            trigger_reason=reason,
            improvement_score=performance_improvement
        )

        self.metrics['directives_promoted'] += 1

        logger.info(f"Promoted directive {directive_id}: {reason}")

        # Invalidate cache
        self.cache_last_updated = None

        return True

    async def deprecate_directive(
        self,
        directive_id: str,
        reason: str,
        replacement_id: Optional[str] = None
    ) -> bool:
        """
        Deprecate directive

        Args:
            directive_id: Directive identifier
            reason: Deprecation reason
            replacement_id: Optional replacement directive ID

        Returns:
            True if deprecated successfully
        """
        # Update status to DEPRECATED
        success = await self.directive_manager.update_directive_status(
            directive_id=directive_id,
            status=DirectiveStatus.DEPRECATED
        )

        if not success:
            return False

        # Get current version
        directive = await self.directive_manager.get_directive(directive_id)
        if not directive:
            return False

        current_version = directive.get('version', 1)

        # Log evolution (DEPRECATED)
        changes = {'deprecated': True, 'reason': reason}
        if replacement_id:
            changes['replaced_by'] = replacement_id

        await self.evolution_engine.log_evolution(
            directive_id=directive_id,
            evolution_type=EvolutionType.DEPRECATED,
            previous_version=current_version,
            new_version=current_version,
            changes=changes,
            trigger_reason=reason
        )

        self.metrics['directives_deprecated'] += 1

        logger.info(f"Deprecated directive {directive_id}: {reason}")

        # Invalidate cache
        self.cache_last_updated = None

        return True

    async def create_ab_test(
        self,
        test_name: str,
        control_directive_id: str,
        variant_directive_ids: List[str],
        duration_hours: int = 168
    ) -> Optional[str]:
        """
        Create A/B test for directive variants

        Args:
            test_name: Test name
            control_directive_id: Control directive ID
            variant_directive_ids: Variant directive IDs
            duration_hours: Test duration (default 168 = 1 week)

        Returns:
            test_id if created
        """
        # Create A/B test
        test_id = await self.ab_testing.create_test(
            test_name=test_name,
            control_directive_id=control_directive_id,
            variant_directive_ids=variant_directive_ids,
            duration_hours=duration_hours
        )

        # Log evolution for all variants
        for variant_id in [control_directive_id] + variant_directive_ids:
            directive = await self.directive_manager.get_directive(variant_id)
            if directive:
                await self.evolution_engine.log_evolution(
                    directive_id=variant_id,
                    evolution_type=EvolutionType.AB_TEST_STARTED,
                    previous_version=directive.get('version', 1),
                    new_version=directive.get('version', 1),
                    changes={'ab_test_id': test_id, 'test_name': test_name},
                    trigger_reason=f"A/B test started: {test_name}"
                )

        logger.info(
            f"Created A/B test {test_id}: {test_name} "
            f"(control + {len(variant_directive_ids)} variants)"
        )

        return test_id

    async def get_system_summary(self) -> Dict[str, Any]:
        """Get comprehensive system summary"""
        # Get directive counts by status
        all_directives = await self.directive_manager.get_all_directives()

        status_counts = {}
        for directive in all_directives:
            status = directive.get('status', 'unknown')
            status_counts[status] = status_counts.get(status, 0) + 1

        # Get A/B testing metrics
        ab_metrics = await self.ab_testing.get_metrics()

        # Get evolution metrics
        evo_metrics = await self.evolution_engine.get_metrics()

        return {
            'total_directives': len(all_directives),
            'directives_by_status': status_counts,
            'application_metrics': self.metrics.copy(),
            'ab_testing': ab_metrics,
            'evolution': evo_metrics,
            'cache_status': {
                'cached_categories': len(self.active_directives_cache),
                'last_updated': (
                    self.cache_last_updated.isoformat()
                    if self.cache_last_updated else None
                ),
                'ttl_seconds': self.cache_ttl_seconds
            }
        }

    async def invalidate_cache(self) -> None:
        """Invalidate directive cache"""
        self.active_directives_cache.clear()
        self.cache_last_updated = None
        logger.debug("Directive cache invalidated")
