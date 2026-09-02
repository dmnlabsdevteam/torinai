"""
Interaction Meta-Learning System - Learn from EVERY interaction

Automatically analyzes each interaction to extract patterns:
- What worked? What didn't?
- What patterns emerge across conversations?
- How should decision-making evolve?

Updates meta-learning patterns in real-time.
"""

import asyncio
import logging
import time
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime
from collections import defaultdict
import json

from core.learning.meta_learning import get_meta_learner

logger = logging.getLogger(__name__)


@dataclass
class InteractionPattern:
    """Pattern extracted from interaction"""
    pattern_id: str
    pattern_type: str  # "user_intent", "effective_response", "common_error", "decision_rule"
    context_signature: str  # Hash of context features
    action_taken: str
    outcome_quality: float  # 0.0-1.0
    confidence: float
    frequency: int = 1
    last_seen: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class InteractionAnalysis:
    """Analysis of single interaction"""
    interaction_id: str
    timestamp: datetime
    user_intent: str
    agent_response_type: str
    was_effective: bool
    patterns_extracted: List[InteractionPattern]
    lessons_learned: List[str]
    confidence_rating: float
    processing_time: float
    metadata: Dict[str, Any] = field(default_factory=dict)


class InteractionMetaLearner:
    """
    Learns from EVERY interaction automatically.
    
    After each response:
    1. Analyze: Was this effective?
    2. Extract: What patterns apply here?
    3. Update: Adjust decision model
    4. Store: Keep for future reference
    """
    
    def __init__(self):
        self.meta_learning = None
        self.pattern_db: Dict[str, InteractionPattern] = {}
        self.interaction_history: List[InteractionAnalysis] = []
        
        # Pattern detection thresholds
        self.min_pattern_frequency = 3  # Need 3+ occurrences to trust pattern
        self.pattern_confidence_threshold = 0.7
        
        # Statistics
        self.stats = {
            'interactions_analyzed': 0,
            'patterns_discovered': 0,
            'patterns_promoted': 0,
            'patterns_updated': 0,
            'effective_interactions': 0,
            'ineffective_interactions': 0
        }
        
    async def initialize(self):
        """Initialize meta-learning system"""
        # Use the shared MetaLearner singleton for interaction meta-learning.
        # Store the interaction DB path in config for future use.
        from core.learning.meta_learning import get_meta_learner

        self.meta_learning = get_meta_learner(
            config={
                "interaction_db_path": "data/databases/learning/interaction_meta.db",
            }
        )
        await self.meta_learning.initialize()

        restored = await self._restore_pattern_db()

        logger.info(
            "Interaction meta-learner initialized - learning from every interaction "
            f"({restored} patterns restored)"
        )

    async def _restore_pattern_db(self) -> int:
        """Rebuild pattern_db from persisted meta-tasks.

        get_pattern_recommendations only returns patterns seen
        min_pattern_frequency (3) times or more. Without this restore that
        threshold was unreachable in practice: frequency lived only in memory,
        so every process start put each pattern back at 1.
        """
        try:
            tasks = await self.meta_learning.get_meta_tasks(
                task_family='pattern_recognition'
            )
        except Exception as e:
            logger.warning(f"Could not restore interaction patterns: {e}")
            return 0

        restored = 0
        for task in tasks:
            meta = task.get('metadata') or {}
            pattern_id = meta.get('pattern_id')
            if not pattern_id:
                continue
            self.pattern_db[pattern_id] = InteractionPattern(
                pattern_id=pattern_id,
                pattern_type=task.get('task_type', 'unknown'),
                context_signature=task.get('domain', ''),
                action_taken=meta.get('action', ''),
                outcome_quality=float(meta.get('quality', 0.0)),
                confidence=float(meta.get('confidence', 0.0)),
                frequency=int(task.get('support_set_size', 1) or 1),
                last_seen=task.get('updated_at') or datetime.now(),
                metadata=meta,
            )
            restored += 1

        self.stats['patterns_discovered'] = len(self.pattern_db)
        return restored
        
    async def analyze_interaction(
        self,
        user_prompt: str,
        agent_response: str,
        context: Dict[str, Any],
        was_effective: Optional[bool] = None
    ) -> InteractionAnalysis:
        """
        Analyze interaction and extract learnings.
        
        Args:
            user_prompt: What user asked
            agent_response: What Singleton answered
            context: Full context (agent_type, thinking, etc)
            was_effective: If None, will estimate
        """
        start_time = time.time()
        
        # Extract user intent
        intent = await self._extract_intent(user_prompt, context)
        
        # Determine if effective (if not explicitly provided)
        if was_effective is None:
            was_effective = await self._estimate_effectiveness(
                user_prompt, agent_response, intent, context
            )
        
        # Extract patterns
        patterns = await self._extract_patterns(
            user_prompt, agent_response, intent, context, was_effective
        )
        
        # Extract lessons
        lessons = await self._extract_lessons(
            user_prompt, agent_response, intent, patterns, was_effective
        )
        
        # Calculate confidence
        confidence = self._calculate_confidence(patterns, context)
        
        # Create analysis
        analysis = InteractionAnalysis(
            interaction_id=f"int_{int(time.time())}_{hash(user_prompt) % 10000}",
            timestamp=datetime.now(),
            user_intent=intent,
            agent_response_type=context.get('agent_type', 'unknown'),
            was_effective=was_effective,
            patterns_extracted=patterns,
            lessons_learned=lessons,
            confidence_rating=confidence,
            processing_time=time.time() - start_time,
            metadata=context
        )
        
        # Update pattern database
        await self._update_patterns(patterns)
        
        # Update statistics
        self.stats['interactions_analyzed'] += 1
        if was_effective:
            self.stats['effective_interactions'] += 1
        else:
            self.stats['ineffective_interactions'] += 1
            
        self.interaction_history.append(analysis)
        
        # Learn from this
        await self._learn_from_analysis(analysis)
        
        logger.info(f"Analyzed interaction: {intent} → {'✓' if was_effective else '✗'} ({len(patterns)} patterns)")
        
        return analysis
        
    async def _extract_intent(self, prompt: str, context: Dict[str, Any]) -> str:
        """Extract user's true intent"""
        prompt_lower = prompt.lower()
        
        # Intent categories
        if any(word in prompt_lower for word in ['fix', 'debug', 'error', 'problem', 'broken']):
            return "fix_issue"
        elif any(word in prompt_lower for word in ['analyze', 'explain', 'why', 'how']):
            return "understand"
        elif any(word in prompt_lower for word in ['create', 'build', 'make', 'implement']):
            return "create"
        elif any(word in prompt_lower for word in ['improve', 'optimize', 'better', 'enhance']):
            return "improve"
        elif any(word in prompt_lower for word in ['research', 'learn', 'study', 'explore']):
            return "research"
        elif any(word in prompt_lower for word in ['what', 'who', 'when', 'where']):
            return "information"
        else:
            return "general_query"
            
    async def _estimate_effectiveness(
        self,
        prompt: str,
        response: str,
        intent: str,
        context: Dict[str, Any]
    ) -> bool:
        """Estimate if response was effective"""
        
        # Check for obvious failures
        if "I apologize" in response or "error" in response.lower():
            return False
            
        # Check if response matches intent
        if intent == "fix_issue" and "fixed" not in response.lower():
            return False
            
        if intent == "information" and len(response) < 10:
            return False
            
        # Check for over-explanation on simple questions
        if len(prompt) < 20 and len(response) > 500:
            return False
            
        # Default: assume effective unless clear failure
        return True
        
    async def _extract_patterns(
        self,
        prompt: str,
        response: str,
        intent: str,
        context: Dict[str, Any],
        was_effective: bool
    ) -> List[InteractionPattern]:
        """Extract patterns from this interaction"""
        
        patterns = []
        
        # Pattern 1: Intent → Response type mapping
        response_type = "detailed" if len(response) > 200 else "concise"
        patterns.append(InteractionPattern(
            pattern_id=f"intent_{intent}_response_{response_type}",
            pattern_type="intent_response_mapping",
            context_signature=f"{intent}_{response_type}",
            action_taken=response_type,
            outcome_quality=1.0 if was_effective else 0.0,
            confidence=0.8
        ))
        
        # Pattern 2: Agent type effectiveness
        agent_type = context.get('agent_type', 'unknown')
        patterns.append(InteractionPattern(
            pattern_id=f"agent_{agent_type}_intent_{intent}",
            pattern_type="agent_effectiveness",
            context_signature=f"{agent_type}_{intent}",
            action_taken=agent_type,
            outcome_quality=1.0 if was_effective else 0.0,
            confidence=0.9
        ))
        
        # Pattern 3: Context features that matter
        if 'thinking_enabled' in context:
            thinking = context['thinking_enabled']
            patterns.append(InteractionPattern(
                pattern_id=f"thinking_{thinking}_intent_{intent}",
                pattern_type="thinking_effectiveness",
                context_signature=f"thinking_{thinking}_{intent}",
                action_taken=f"thinking_{thinking}",
                outcome_quality=1.0 if was_effective else 0.0,
                confidence=0.7
            ))
            
        return patterns
        
    async def _extract_lessons(
        self,
        prompt: str,
        response: str,
        intent: str,
        patterns: List[InteractionPattern],
        was_effective: bool
    ) -> List[str]:
        """Extract specific lessons from this interaction"""
        
        lessons = []
        
        if was_effective:
            # Learn what worked
            if intent == "fix_issue" and len(response) < 500:
                lessons.append("Concise fixes work well for fix_issue intent")
            elif intent == "information" and len(response) < 100:
                lessons.append("Brief answers work for simple information queries")
        else:
            # Learn what didn't work
            if intent == "fix_issue" and "research" in response.lower():
                lessons.append("Don't research when asked to fix - just fix it")
            elif len(prompt) < 50 and len(response) > 500:
                lessons.append("Simple questions don't need long explanations")
                
        return lessons
        
    def _calculate_confidence(
        self,
        patterns: List[InteractionPattern],
        context: Dict[str, Any]
    ) -> float:
        """Calculate confidence in this analysis"""
        
        # Base confidence
        confidence = 0.5
        
        # Higher confidence with more patterns
        confidence += min(len(patterns) * 0.1, 0.3)
        
        # Higher confidence with known context
        if context.get('agent_type'):
            confidence += 0.1
        if context.get('thinking_enabled'):
            confidence += 0.1
            
        return min(confidence, 1.0)
        
    async def _update_patterns(self, patterns: List[InteractionPattern]):
        """Update pattern database with new observations"""
        
        for pattern in patterns:
            if pattern.pattern_id in self.pattern_db:
                # Update existing pattern
                existing = self.pattern_db[pattern.pattern_id]
                
                # Update frequency
                existing.frequency += 1
                
                # Update outcome quality (running average)
                total = existing.outcome_quality * (existing.frequency - 1) + pattern.outcome_quality
                existing.outcome_quality = total / existing.frequency
                
                # Update confidence based on frequency
                existing.confidence = min(
                    existing.confidence + 0.05,
                    0.95
                )
                
                existing.last_seen = datetime.now()

                self.stats['patterns_updated'] += 1
            else:
                # New pattern
                self.pattern_db[pattern.pattern_id] = pattern
                self.stats['patterns_discovered'] += 1

            # Persist on every observation, not only on promotion. _learn_from_analysis
            # stores a pattern once frequency >= min_pattern_frequency, but frequency
            # is what this method accumulates -- so the promotion gate could never be
            # reached across restarts. Frequency has to be durable to grow.
            if self.meta_learning:
                await self._store_pattern_as_meta_task(
                    self.pattern_db[pattern.pattern_id]
                )

    async def _learn_from_analysis(self, analysis: InteractionAnalysis):
        """
        Learn from this analysis - update decision-making model.
        
        This is where meta-learning happens: patterns become rules.
        """
        
        # If we have high-confidence patterns, update decision model
        strong_patterns = [
            p for p in analysis.patterns_extracted
            if p.confidence >= self.pattern_confidence_threshold
            and self.pattern_db[p.pattern_id].frequency >= self.min_pattern_frequency
        ]
        
        if strong_patterns:
            # Promotion: the pattern is now trusted enough to be recommended.
            # _update_patterns already persisted it; this marks it as promoted so
            # get_pattern_recommendations and downstream readers can tell a
            # trusted rule from an accumulating observation.
            for pattern in strong_patterns:
                if self.meta_learning:
                    self.pattern_db[pattern.pattern_id].metadata['promoted'] = True
                    await self._store_pattern_as_meta_task(
                        self.pattern_db[pattern.pattern_id]
                    )
                    self.stats['patterns_promoted'] += 1
                    
    async def _store_pattern_as_meta_task(self, pattern: InteractionPattern):
        """Store pattern as meta-learning task for future reference.

        Enriches the task with global outcome statistics derived from
        TaskOutcomeRecord-based META memories so that meta-learning
        can reason over real success/failure distributions.
        """

        # Pull global outcome stats from META task_outcome records
        outcome_stats: Dict[str, Any] = await self._get_global_outcome_stats()

        # Create task configuration
        task_config = {
            'task_id': f'meta_{pattern.pattern_id}',
            'task_family': 'pattern_recognition',
            'task_type': pattern.pattern_type,
            'domain': pattern.context_signature,
            'difficulty': 1.0 - pattern.confidence,
            'support_set_size': pattern.frequency,
            'metadata': {
                'pattern_id': pattern.pattern_id,
                'action': pattern.action_taken,
                'quality': pattern.outcome_quality,
                'confidence': pattern.confidence,
                'global_outcome_stats': outcome_stats,
            }
        }

        try:
            await self.meta_learning.create_meta_task(task_config)
        except Exception as e:
            logger.warning(f"Could not create meta task: {e}")

    async def _get_global_outcome_stats(self) -> Dict[str, Any]:
        """Aggregate global outcome statistics from META task_outcome memories.

        Uses the same TaskOutcomeRecord schema leveraged by intrinsic
        motivation so interaction-level meta-learning is grounded in
        the real success/failure distribution.
        """

        try:
            from core.governance.governance_block_schema import task_outcome_from_memory
            from core.memory import get_memory_agent
            from core.memory.utils.interfaces import MemoryType

            memory_agent = await get_memory_agent()
            if not memory_agent or not memory_agent.initialized:
                return {
                    # UNMEASURED, not 50%. See _unmeasured_stats in
                    # intrinsic_motivation — same defect, second copy.
                    'success_rate': None,
                    'failure_rate': None,
                    'avg_outcome_label_confidence': None,
                    'total_attempts': 0,
                    'measured': False,
                }

            memories = await memory_agent.search_memories(
                query_text="task_outcome",
                memory_type=MemoryType.META,
                tags=["task_outcome", "performance_tracking"],
                max_results=200,
            )

            if not memories:
                return {
                    # UNMEASURED, not 50%. See _unmeasured_stats in
                    # intrinsic_motivation — same defect, second copy.
                    'success_rate': None,
                    'failure_rate': None,
                    'avg_outcome_label_confidence': None,
                    'total_attempts': 0,
                    'measured': False,
                }

            successes = 0
            failures = 0
            total_confidence = 0.0

            for memory in memories:
                record = task_outcome_from_memory(memory)
                if record is None:
                    continue

                if record.outcome == 'success':
                    successes += 1
                elif record.outcome == 'failure':
                    failures += 1

                total_confidence += float(record.confidence)

            total = successes + failures
            if total == 0:
                return {
                    # UNMEASURED, not 50%. See _unmeasured_stats in
                    # intrinsic_motivation — same defect, second copy.
                    'success_rate': None,
                    'failure_rate': None,
                    'avg_outcome_label_confidence': None,
                    'total_attempts': 0,
                    'measured': False,
                }

            return {
                'success_rate': successes / total,
                'failure_rate': failures / total,
                'avg_outcome_label_confidence': total_confidence / total,
                'measured': True,
                'total_attempts': total,
            }

        except Exception as e:
            logger.debug(f"Failed to aggregate global outcome stats: {e}")
            return {
                'success_rate': None,
                'failure_rate': None,
                'avg_outcome_label_confidence': None,
                'total_attempts': 0,
                'measured': False,
            }
            
    def get_pattern_recommendations(self, intent: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get recommendations based on learned patterns.
        
        Returns suggested actions based on past effectiveness.
        """
        
        recommendations = {
            'suggested_actions': [],
            'confidence': 0.0,
            'reasoning': []
        }
        
        # Find relevant patterns
        relevant_patterns = [
            p for p in self.pattern_db.values()
            if intent in p.context_signature
            and p.frequency >= self.min_pattern_frequency
            and p.confidence >= self.pattern_confidence_threshold
        ]
        
        if not relevant_patterns:
            return recommendations
            
        # Sort by outcome quality and confidence
        relevant_patterns.sort(
            key=lambda p: p.outcome_quality * p.confidence,
            reverse=True
        )
        
        # Build recommendations
        for pattern in relevant_patterns[:3]:  # Top 3
            recommendations['suggested_actions'].append({
                'action': pattern.action_taken,
                'expected_quality': pattern.outcome_quality,
                'confidence': pattern.confidence,
                'frequency': pattern.frequency
            })
            
            recommendations['reasoning'].append(
                f"{pattern.action_taken}: {pattern.frequency} successes, "
                f"{pattern.outcome_quality:.0%} quality"
            )
            
        recommendations['confidence'] = sum(
            p.confidence * p.outcome_quality for p in relevant_patterns[:3]
        ) / len(relevant_patterns[:3])
        
        return recommendations
        
    def get_statistics(self) -> Dict[str, Any]:
        """Get learning statistics"""
        
        effectiveness_rate = 0.0
        if self.stats['interactions_analyzed'] > 0:
            effectiveness_rate = (
                self.stats['effective_interactions'] / 
                self.stats['interactions_analyzed']
            )
            
        return {
            **self.stats,
            'effectiveness_rate': effectiveness_rate,
            'total_patterns': len(self.pattern_db),
            'high_confidence_patterns': len([
                p for p in self.pattern_db.values()
                if p.confidence >= self.pattern_confidence_threshold
                and p.frequency >= self.min_pattern_frequency
            ])
        }


# Singleton
_interaction_learner: Optional[InteractionMetaLearner] = None


async def get_interaction_learner() -> InteractionMetaLearner:
    """Get or create interaction meta-learner singleton"""
    global _interaction_learner
    
    if _interaction_learner is None:
        _interaction_learner = InteractionMetaLearner()
        await _interaction_learner.initialize()
        
    return _interaction_learner
