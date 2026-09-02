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
from .directive_evolution_engine import DirectiveEvolutionEngine, EvolutionType
from .singleton_constitution import get_singleton_constitution
from .governance_agent import GovernanceAgent
from core.database import get_unified_db

# NOTE (2026-09-02): DirectiveABTesting is no longer wired here. Comparing
# directive variants to pick a winner IS learning, and learning is owned by the
# MetaLearner (the learning authority) — a directive is an arm, so competing
# variants are competing arms it already ranks by measured posteriors. The
# separate embedded-t-test A/B module was a second learner bypassing the
# authority; it is archived in archive/llm_era_directive_governance_2026-09-02/.

logger = logging.getLogger(__name__)


class DirectiveSystem:
    """
    Main Directive Orchestration System

    Integrates all directive components:

    Components:
    1. DirectiveManager - CRUD operations for directives
    2. Learning authority (MetaLearner) - owns directive effectiveness + variant
       selection (directives are arms); credited via log_directive_application
    3. DirectiveEvolutionEngine - lifecycle EVENT LOG (not a learner)
    4. GovernanceAgent → constitution - model-free validation against the 5 laws

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
        evolution_engine: Optional[DirectiveEvolutionEngine] = None,
        db = None
    ):
        """
        Initialize directive system

        Args:
            directive_manager: Directive manager
            evolution_engine: Evolution engine (lifecycle EVENT LOG, not a learner)
            db: Database for persistence (will use singleton if not provided)
        """
        self.db = db  # Will be set in initialize()

        # Core components - pass None for db, they will get singleton in their initialize()
        self.directive_manager = directive_manager or DirectiveManager(db=None)
        self.evolution_engine = evolution_engine or DirectiveEvolutionEngine(db=None)

        # GOVERNANCE — a proposed directive is vetted through the GovernanceAgent
        # (the compliance-DECISION authority), which scores it against the 5 laws
        # via the constitution (the law authority) and reports requires_governance.
        # This replaced the removed five-judge vote and keeps the authority chain
        # intact (DirectiveSystem → GovernanceAgent → constitution) rather than
        # re-deciding compliance here. Model-free; the GovernanceAgent emits its
        # own compliance metrics. Uses the process-wide singleton constitution the
        # coordinator activates, so no second law authority is stood up.
        self.governance_agent = GovernanceAgent(constitution=get_singleton_constitution())

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
            'directives_deprecated': 0,
            'directives_rejected_by_governance': 0
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
            # get_directives_by_category returns InternalDirective OBJECTS, not
            # dicts — read via _attr so this combine path is not broken.
            directive_ids.append(self._attr(directive, 'directive_id'))
            params = self._attr(directive, 'directive_parameters', None)
            if params:
                # Merge parameters (later directives override earlier ones)
                combined_params.update(params)

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
        Record a directive application's outcome and CREDIT it to the learning
        authority.

        Which directive works is owned by the MetaLearner (the learning
        authority): a directive is an ARM, scoped by its category, and its
        outcome flows to `track_learning_outcome`. There is no embedded A/B stat
        or self-computed effectiveness here — that would be a second learner
        bypassing the authority. The directive's avg_* fields (via the DB
        aggregate) are a DESCRIPTIVE record only, written on the application seam
        (log_application → update_application_outcome), never the selection
        authority.

        Args:
            directive_id: Directive identifier
            decision_id: Decision identifier (the application_id, when present)
            decision_context: Decision context
            outcome_metrics: Outcome metrics (all [0.0-1.0]); may carry
                'success', 'time_ms', and 'outcome_class'
        """
        from core.learning.meta_learning import (
            get_meta_learner, TaskFamily, OutcomeClass)

        outcome_quality = float(outcome_metrics.get('outcome_quality', 0.5))
        success = bool(outcome_metrics.get('success', outcome_quality >= 0.5))

        # Map to the credit taxonomy. A genuine low-quality outcome means the
        # directive's guidance underperformed (STRATEGY_FAILURE); a real success
        # is SUCCESS. A caller that knows the true cause passes outcome_class.
        klass = outcome_metrics.get('outcome_class')
        if klass is None:
            klass = OutcomeClass.SUCCESS if success else OutcomeClass.STRATEGY_FAILURE

        # The category scopes the arm so a directive competes only with other
        # directives of the same category, not unrelated arms.
        directive = await self.directive_manager.get_directive(directive_id)
        category_val = getattr(
            getattr(directive, 'directive_category', None), 'value', 'general'
        ) if directive else 'general'

        # CREDIT THE LEARNING AUTHORITY — the MetaLearner owns directive
        # effectiveness. track_learning_outcome auto-registers the arm.
        try:
            meta = get_meta_learner()
            await meta.track_learning_outcome(
                task_type=TaskFamily.CONTROL,
                strategy_type=f"directive:{category_val}:{directive_id}",
                success=success,
                performance_score=outcome_quality,
                time_ms=float(outcome_metrics.get('time_ms', 0.0)),
                outcome_class=klass,
                context={"directive_id": directive_id, "category": category_val,
                         "source": "directive_application",
                         **(decision_context or {})},
            )
        except Exception as e:
            logger.warning("directive learning credit failed for %s: %s",
                           directive_id, e)

        # Descriptive outcome record (raw averages via the DB aggregate) — only
        # when the application row exists (decision_id is its application_id).
        # This is NOT the decision authority; it is a materialized view.
        if decision_id:
            try:
                await self.directive_manager.update_application_outcome(
                    application_id=decision_id,
                    outcome_quality=outcome_quality,
                    intrinsic_reward=float(outcome_metrics.get('intrinsic_reward', 0.5)),
                    constitutional_alignment=float(outcome_metrics.get('constitutional_alignment', 1.0)),
                    system_health_impact=float(outcome_metrics.get('system_health_impact', 1.0)),
                    success=success,
                )
            except Exception as e:
                logger.debug("directive descriptive aggregate skipped for %s: %s",
                             directive_id, e)

        self.metrics['successful_applications' if success else 'failed_applications'] += 1
        logger.debug(
            "Directive %s outcome credited to learning authority "
            "(q=%.3f, success=%s)", directive_id, outcome_quality, success)

    @staticmethod
    def _attr(obj, name, default=None):
        """Read a field from an InternalDirective object OR a dict."""
        if isinstance(obj, dict):
            return obj.get(name, default)
        return getattr(obj, name, default)

    async def select_guidance(self, category: DirectiveCategory,
                              context: Optional[Dict[str, Any]] = None):
        """Return the guidance params of the BEST active directive for a category,
        chosen by the LEARNING AUTHORITY (the MetaLearner over the category's
        directive arms), plus its directive_id so the caller can credit the
        outcome. Returns ({}, None) when no active directive exists — the caller
        then uses its own current default (never a fabricated guidance). Selection
        is the authority's; there is no local ranking heuristic here.
        """
        actives = await self.get_active_directives(category)
        if not actives:
            return {}, None
        if len(actives) == 1:
            d = actives[0]
            return dict(self._attr(d, 'directive_parameters', {}) or {}), \
                self._attr(d, 'directive_id')

        # Multiple active directives compete — the MetaLearner picks the best arm.
        cat_val = getattr(category, 'value', category)
        chosen_id = None
        try:
            from core.learning.meta_learning import get_meta_learner, TaskFamily
            sel = await get_meta_learner().select_strategy(
                task_type=TaskFamily.CONTROL,
                strategy_prefix=f"directive:{cat_val}:")
            st = getattr(sel, 'strategy_type', '') if sel is not None else ''
            marker = f"directive:{cat_val}:"
            if st and marker in st:
                chosen_id = st.split(marker, 1)[1]
        except Exception as e:
            logger.debug("directive selection via MetaLearner unavailable: %s", e)

        for d in actives:
            if self._attr(d, 'directive_id') == chosen_id:
                return dict(self._attr(d, 'directive_parameters', {}) or {}), chosen_id
        # No authority verdict yet (cold arms): fall back to the store's own
        # ordering (avg_outcome_quality DESC) — descriptive, not a second learner.
        d = actives[0]
        return dict(self._attr(d, 'directive_parameters', {}) or {}), \
            self._attr(d, 'directive_id')

    async def promote_eligible_directives(self, *, min_trials: int = 5,
                                          min_success_rate: float = 0.6) -> int:
        """Promote DRAFT directives the LEARNING AUTHORITY has shown to work.

        A draft becomes ACTIVE only when its MetaLearner arm has enough trials and
        a success rate above the bar — the authority owns the "is this good enough"
        judgement, not a local statistic. Returns how many were promoted. This is
        the MetaLearner-driven half of the lifecycle; the constitution already
        gated CREATION.
        """
        promoted = 0
        try:
            from core.learning.meta_learning import get_meta_learner
            from .directive_types import DirectiveStatus
            meta = get_meta_learner()
            drafts = await self.directive_manager.get_directives_by_status(
                DirectiveStatus.DRAFT)
        except Exception as e:
            logger.debug("promote_eligible_directives unavailable: %s", e)
            return 0

        for d in drafts:
            did = self._attr(d, 'directive_id')
            cat_val = getattr(self._attr(d, 'directive_category', None), 'value',
                              self._attr(d, 'directive_category', 'general'))
            # Find the arm for this directive (MetaLearner may namespace with a
            # TaskFamily prefix, so match by suffix).
            marker = f"directive:{cat_val}:{did}"
            arm = next((s for sid, s in meta.strategies.items()
                        if marker in sid), None)
            if arm is None:
                continue
            trials = getattr(arm, 'trials', 0)
            successes = getattr(arm, 'successes', 0)
            if trials < min_trials:
                continue
            rate = successes / trials if trials else 0.0
            if rate < min_success_rate:
                continue
            if await self.promote_directive(did, performance_improvement=rate):
                promoted += 1
                logger.info("Directive %s PROMOTED by learning authority "
                            "(trials=%d, success_rate=%.2f)", did, trials, rate)
        return promoted

    async def create_directive_with_governance(
        self,
        directive_name: str,
        category: DirectiveCategory,
        directive_text: str,
        directive_parameters: Dict[str, Any],
        created_by: str = "system"
    ) -> Optional[str]:
        """
        Create a directive, gated by CONSTITUTIONAL validation.

        Governance is now the constitution (model-free), not a five-judge vote: the
        proposed directive is scored against the 5 laws and only created if it
        passes. A rejected proposal returns None and is NOT persisted.

        Args:
            directive_name: Directive name
            category: Directive category
            directive_text: Directive text
            directive_parameters: Directive parameters
            created_by: Who created the directive

        Returns:
            directive_id if created, None if rejected by the constitution
        """
        from .directive_types import InternalDirective

        # Build the proposed directive (DRAFT until promoted).
        directive = InternalDirective(
            directive_id=InternalDirective.generate_id(),
            directive_name=directive_name,
            directive_category=category,
            directive_text=directive_text,
            directive_parameters=directive_parameters,
        )

        # GOVERNANCE: vet through the GovernanceAgent (the compliance-decision
        # authority), which scores the directive against the 5 laws via the
        # constitution and reports requires_governance. A directive is a policy the
        # substrate applies to itself, so it is checked as an internal action.
        category_val = getattr(category, "value", category)
        record = await self.governance_agent.check_action_compliance(
            action_id=directive.directive_id,
            action_description=directive_text,
            action_params={**(directive_parameters or {}),
                           "task_type": category_val,
                           "reasoning": f"directive proposed by {created_by}"},
            source_type="internal",
        )
        validation = {
            "approved": not record.requires_governance,
            "overall_compliance": round(record.overall_compliance, 4),
            "compliance_scores": record.compliance_scores,
            "violations_detected": record.violations_detected,
        }
        if record.requires_governance:
            self.metrics['directives_rejected_by_governance'] += 1
            logger.warning(
                "Directive '%s' REJECTED by governance: violations=%s "
                "overall=%.2f — not persisted",
                directive_name, record.violations_detected,
                record.overall_compliance)
            return None

        # Approved by governance — record it on the directive and persist.
        directive.governance_validated = True
        directive.constitutional_validated = True
        created = await self.directive_manager.create_directive(directive)
        if not created:
            logger.error("Failed to persist governance-approved directive")
            return None
        directive_id = directive.directive_id

        # Log evolution (CREATED) carrying the governance verdict.
        await self.evolution_engine.log_evolution(
            directive_id=directive_id,
            evolution_type=EvolutionType.CREATED,
            previous_version=None,
            new_version=1,
            changes={'created': True, 'created_by': created_by,
                     'governance_validation': validation},
            trigger_reason=(f"Created by {created_by}; governance approved "
                            f"(overall={validation['overall_compliance']})")
        )

        self.metrics['directives_created'] += 1
        logger.info("Created directive %s: %s (governance-approved, overall=%.2f)",
                    directive_id, directive_name, record.overall_compliance)
        return directive_id

    async def promote_directive(
        self,
        directive_id: str,
        reason: str = "promoted by learning authority",
        performance_improvement: float = 0.0
    ) -> bool:
        """
        Promote a directive to ACTIVE.

        Fixed from the dead path: the manager has no update_directive_status and
        returns InternalDirective OBJECTS (not dicts), so this mutates the fetched
        object's status/activation_date and persists via update_directive.

        Args:
            directive_id: Directive identifier
            reason: Promotion reason
            performance_improvement: Measured improvement (from the learning authority)

        Returns:
            True if promoted successfully
        """
        directive = await self.directive_manager.get_directive(directive_id)
        if not directive:
            return False

        directive.status = DirectiveStatus.ACTIVE
        directive.activation_date = datetime.now()
        if not await self.directive_manager.update_directive(directive):
            return False

        current_version = getattr(directive, 'version', 1)
        await self.evolution_engine.log_evolution(
            directive_id=directive_id,
            evolution_type=EvolutionType.PROMOTED,
            previous_version=max(1, current_version - 1),
            new_version=current_version,
            changes={'promoted_to': 'active'},
            trigger_reason=reason,
            improvement_score=performance_improvement
        )

        self.metrics['directives_promoted'] += 1
        logger.info(f"Promoted directive {directive_id}: {reason}")
        self.cache_last_updated = None  # Invalidate cache
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
        # Fixed from the dead path: no update_directive_status exists, and the
        # manager returns an InternalDirective OBJECT — mutate + persist.
        directive = await self.directive_manager.get_directive(directive_id)
        if not directive:
            return False

        directive.status = DirectiveStatus.DEPRECATED
        directive.deprecation_date = datetime.now()
        if not await self.directive_manager.update_directive(directive):
            return False

        current_version = getattr(directive, 'version', 1)

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

    # NOTE (2026-09-02): create_ab_test() was REMOVED. Directive variant
    # comparison is the MetaLearner's job — competing directive variants are
    # competing arms it ranks by measured posteriors (see log_directive_application
    # crediting each directive arm). A separate A/B test would be a second learner
    # bypassing the learning authority. Archived in
    # archive/llm_era_directive_governance_2026-09-02/.

    async def get_system_summary(self) -> Dict[str, Any]:
        """Get comprehensive system summary (metrics for the health monitor)."""
        # Get directive counts by status
        all_directives = await self.directive_manager.get_all_directives()

        status_counts = {}
        for directive in all_directives:
            # get_all_directives returns InternalDirective OBJECTS.
            st = self._attr(directive, 'status', None)
            status = getattr(st, 'value', st) or 'unknown'
            status_counts[status] = status_counts.get(status, 0) + 1

        # Get evolution metrics (lifecycle event log)
        evo_metrics = await self.evolution_engine.get_metrics()

        return {
            'total_directives': len(all_directives),
            'directives_by_status': status_counts,
            'application_metrics': self.metrics.copy(),
            # Governance decisions on directives are the GovernanceAgent's; its
            # counters are the honest directive-governance metrics.
            'governance': self.governance_agent.metrics.copy(),
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
