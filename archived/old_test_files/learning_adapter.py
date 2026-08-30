#!/usr/bin/env python3
"""
Learning Adapter - Simplified learning and adaptation system
Consolidates all learning functionality from the monolithic controller
"""

import asyncio
import logging
import sqlite3
import json
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
from collections import defaultdict, deque
from dataclasses import asdict

from .shared_types import LearningData, Task, TaskStatus, SystemState

logger = logging.getLogger(__name__)


class LearningAdapter:
    """Manages experience storage, pattern recognition, and performance improvement"""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.active = False
        
        # Learning state
        self.experiences: deque = deque(maxlen=10000)
        self.patterns: Dict[str, Dict[str, Any]] = {}
        self.performance_metrics: Dict[str, float] = {}
        
        # Pattern recognition
        self.pattern_threshold = self.config.get("pattern_threshold", 0.7)
        self.learning_rate = self.config.get("learning_rate", 0.1)
        
        # Database for persistence
        self.db_path = self.config.get("learning_db_path", "databases/learning.db")
        self.connection: Optional[sqlite3.Connection] = None
        
        # Learning statistics
        self.stats = {
            "experiences_recorded": 0,
            "patterns_discovered": 0,
            "improvements_applied": 0,
            "learning_accuracy": 0.0
        }
    
    async def initialize(self) -> bool:
        """Initialize the learning adapter"""
        try:
            # Setup database
            self.connection = sqlite3.connect(self.db_path)
            self._create_tables()
            
            # Load existing patterns and experiences
            await self._load_learning_data()
            
            self.active = True
            logger.info("Learning adapter initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize learning adapter: {e}")
            return False
    
    async def record_experience(self, context: Dict[str, Any], action: Dict[str, Any], 
                               outcome: Dict[str, Any], success: bool) -> Optional[LearningData]:
        """Record a learning experience"""
        if not self.active:
            return None
        
        try:
            experience = LearningData(
                context=context,
                action=action,
                outcome=outcome,
                success=success,
                timestamp=datetime.now().timestamp(),
                confidence=self._calculate_experience_confidence(context, action, outcome)
            )
            
            # Store experience
            self.experiences.append(experience)
            await self._store_experience(experience)
            
            # Update performance metrics
            self._update_performance_metrics(context, action, outcome, success)
            
            # Check for new patterns
            await self._analyze_patterns()
            
            self.stats["experiences_recorded"] += 1
            logger.debug(f"Recorded experience: {action.get('type', 'unknown')} -> {success}")
            
            return experience
            
        except Exception as e:
            logger.error(f"Error recording experience: {e}")
            return None
    
    async def get_recommendations(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get action recommendations based on learned patterns"""
        if not self.active:
            return []
        
        try:
            recommendations = []
            
            # Find similar contexts
            similar_patterns = self._find_similar_patterns(context)
            
            for pattern_id, pattern in similar_patterns:
                if pattern["success_rate"] > 0.6:  # Only recommend successful patterns
                    recommendation = {
                        "action": pattern["common_action"],
                        "confidence": pattern["success_rate"],
                        "pattern_id": pattern_id,
                        "evidence_count": pattern["occurrence_count"]
                    }
                    recommendations.append(recommendation)
            
            # Sort by confidence
            recommendations.sort(key=lambda x: x["confidence"], reverse=True)
            
            return recommendations[:5]  # Top 5 recommendations
            
        except Exception as e:
            logger.error(f"Error getting recommendations: {e}")
            return []
    
    async def adapt_performance(self, task: Task, execution_result: Dict[str, Any]) -> Dict[str, Any]:
        """Adapt system performance based on task execution results"""
        adaptations = {}
        
        try:
            # Analyze execution outcome
            success = execution_result.get("success", False)
            execution_time = execution_result.get("execution_time", 0.0)
            resource_usage = execution_result.get("resource_usage", 0.0)
            
            # Record experience
            await self.record_experience(
                context={
                    "task_type": task.type.name,
                    "task_priority": task.priority.name,
                    "estimated_duration": task.estimated_duration
                },
                action={
                    "type": "task_execution",
                    "approach": execution_result.get("approach", "default")
                },
                outcome={
                    "success": success,
                    "execution_time": execution_time,
                    "resource_usage": resource_usage
                },
                success=success
            )
            
            # Generate adaptations
            if not success:
                adaptations.update(await self._suggest_failure_adaptations(task, execution_result))
            else:
                adaptations.update(await self._suggest_optimization_adaptations(task, execution_result))
            
            if adaptations:
                self.stats["improvements_applied"] += 1
                logger.info(f"Applied {len(adaptations)} performance adaptations")
            
            return adaptations
            
        except Exception as e:
            logger.error(f"Error adapting performance: {e}")
            return {}
    
    async def get_learning_insights(self) -> Dict[str, Any]:
        """Get insights from accumulated learning data"""
        try:
            insights = {
                "total_experiences": len(self.experiences),
                "success_rate": self._calculate_overall_success_rate(),
                "top_patterns": self._get_top_patterns(5),
                "performance_trends": self._analyze_performance_trends(),
                "recommendations": {
                    "high_success_actions": self._get_high_success_actions(),
                    "areas_for_improvement": self._identify_improvement_areas()
                },
                "statistics": self.stats.copy()
            }
            
            return insights
            
        except Exception as e:
            logger.error(f"Error generating learning insights: {e}")
            return {}
    
    def _calculate_experience_confidence(self, context: Dict[str, Any], 
                                      action: Dict[str, Any], outcome: Dict[str, Any]) -> float:
        """Calculate confidence score for an experience"""
        base_confidence = 0.5
        
        # Increase confidence for clear outcomes
        if "success" in outcome and isinstance(outcome["success"], bool):
            base_confidence += 0.2
        
        # Increase confidence for detailed context
        if len(context) > 2:
            base_confidence += 0.1
        
        # Increase confidence for measurable outcomes
        if any(isinstance(v, (int, float)) for v in outcome.values()):
            base_confidence += 0.2
        
        return min(1.0, base_confidence)
    
    def _update_performance_metrics(self, context: Dict[str, Any], action: Dict[str, Any],
                                  outcome: Dict[str, Any], success: bool):
        """Update performance metrics based on experience"""
        action_type = action.get("type", "unknown")
        
        if action_type not in self.performance_metrics:
            self.performance_metrics[action_type] = 0.5
        
        # Update using exponential moving average
        current_score = 1.0 if success else 0.0
        self.performance_metrics[action_type] = (
            (1 - self.learning_rate) * self.performance_metrics[action_type] +
            self.learning_rate * current_score
        )
    
    async def _analyze_patterns(self):
        """Analyze experiences to discover patterns"""
        if len(self.experiences) < 10:  # Need minimum experiences
            return
        
        try:
            # Group experiences by context similarity
            context_groups = defaultdict(list)
            
            for exp in list(self.experiences)[-100:]:  # Analyze recent experiences
                context_key = self._create_context_key(exp.context)
                context_groups[context_key].append(exp)
            
            # Find patterns in groups with sufficient data
            for context_key, experiences in context_groups.items():
                if len(experiences) >= 3:
                    pattern = self._extract_pattern(experiences)
                    if pattern and pattern["confidence"] > self.pattern_threshold:
                        self.patterns[context_key] = pattern
                        self.stats["patterns_discovered"] += 1
            
        except Exception as e:
            logger.error(f"Error analyzing patterns: {e}")
    
    def _create_context_key(self, context: Dict[str, Any]) -> str:
        """Create a consistent key for grouping similar contexts"""
        # Sort keys for consistent hashing
        sorted_items = sorted(context.items())
        return json.dumps(sorted_items, sort_keys=True)
    
    def _extract_pattern(self, experiences: List[LearningData]) -> Optional[Dict[str, Any]]:
        """Extract a pattern from a group of similar experiences"""
        if not experiences:
            return None
        
        try:
            # Calculate success rate
            successful = [exp for exp in experiences if exp.success]
            success_rate = len(successful) / len(experiences)
            
            # Find common action
            action_counts = defaultdict(int)
            for exp in experiences:
                action_key = json.dumps(exp.action, sort_keys=True)
                action_counts[action_key] += 1
            
            most_common_action = max(action_counts.items(), key=lambda x: x[1])
            common_action = json.loads(most_common_action[0])
            
            # Calculate confidence
            confidence = success_rate * (most_common_action[1] / len(experiences))
            
            pattern = {
                "success_rate": success_rate,
                "common_action": common_action,
                "occurrence_count": len(experiences),
                "confidence": confidence,
                "last_updated": datetime.now().timestamp()
            }
            
            return pattern
            
        except Exception as e:
            logger.error(f"Error extracting pattern: {e}")
            return None
    
    def _find_similar_patterns(self, context: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
        """Find patterns similar to the given context"""
        similar = []
        
        context_key = self._create_context_key(context)
        
        for pattern_id, pattern in self.patterns.items():
            # Simple similarity: exact match for now
            # Could be enhanced with fuzzy matching
            if pattern_id == context_key:
                similar.append((pattern_id, pattern))
        
        return similar
    
    async def _suggest_failure_adaptations(self, task: Task, result: Dict[str, Any]) -> Dict[str, Any]:
        """Suggest adaptations for failed task execution"""
        adaptations = {}
        
        # Suggest timeout increase if execution was cut short
        if "timeout" in result.get("error", "").lower():
            adaptations["increase_timeout"] = task.estimated_duration * 1.5
        
        # Suggest priority adjustment for repeated failures
        task_type = task.type.name
        if self.performance_metrics.get(task_type, 0.5) < 0.3:
            adaptations["adjust_priority"] = "increase"
        
        # Suggest resource allocation changes
        if "resource" in result.get("error", "").lower():
            adaptations["increase_resources"] = True
        
        return adaptations
    
    async def _suggest_optimization_adaptations(self, task: Task, result: Dict[str, Any]) -> Dict[str, Any]:
        """Suggest optimizations for successful task execution"""
        adaptations = {}
        
        execution_time = result.get("execution_time", task.estimated_duration)
        
        # Suggest duration optimization if task completed much faster/slower
        if execution_time < task.estimated_duration * 0.5:
            adaptations["reduce_estimated_duration"] = execution_time * 1.2
        elif execution_time > task.estimated_duration * 1.5:
            adaptations["increase_estimated_duration"] = execution_time * 1.1
        
        return adaptations
    
    def _calculate_overall_success_rate(self) -> float:
        """Calculate overall success rate from experiences"""
        if not self.experiences:
            return 0.0
        
        successful = sum(1 for exp in self.experiences if exp.success)
        return successful / len(self.experiences)
    
    def _get_top_patterns(self, limit: int) -> List[Dict[str, Any]]:
        """Get top patterns by confidence"""
        pattern_list = [
            {"id": pid, **pattern} 
            for pid, pattern in self.patterns.items()
        ]
        pattern_list.sort(key=lambda x: x["confidence"], reverse=True)
        return pattern_list[:limit]
    
    def _analyze_performance_trends(self) -> Dict[str, Any]:
        """Analyze performance trends over time"""
        trends = {}
        
        # Calculate trends for each action type
        for action_type, current_performance in self.performance_metrics.items():
            # Simple trend: compare with historical average
            historical_avg = 0.5  # Could be calculated from stored data
            trend = "improving" if current_performance > historical_avg else "declining"
            trends[action_type] = {
                "current": current_performance,
                "trend": trend,
                "change": current_performance - historical_avg
            }
        
        return trends
    
    def _get_high_success_actions(self) -> List[str]:
        """Get action types with high success rates"""
        return [
            action_type for action_type, performance in self.performance_metrics.items()
            if performance > 0.8
        ]
    
    def _identify_improvement_areas(self) -> List[str]:
        """Identify areas that need improvement"""
        return [
            action_type for action_type, performance in self.performance_metrics.items()
            if performance < 0.4
        ]
    
    def _create_tables(self):
        """Create database tables"""
        if not self.connection:
            return
            
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS experiences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                context TEXT NOT NULL,
                action TEXT NOT NULL,
                outcome TEXT NOT NULL,
                success BOOLEAN NOT NULL,
                confidence REAL NOT NULL,
                timestamp REAL NOT NULL
            )
        """)
        
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS patterns (
                id TEXT PRIMARY KEY,
                pattern_data TEXT NOT NULL,
                success_rate REAL NOT NULL,
                occurrence_count INTEGER NOT NULL,
                confidence REAL NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
        """)
        
        self.connection.commit()
    
    async def _store_experience(self, experience: LearningData):
        """Store experience in database"""
        if not self.connection:
            return
        
        try:
            self.connection.execute("""
                INSERT INTO experiences 
                (context, action, outcome, success, confidence, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                json.dumps(experience.context),
                json.dumps(experience.action),
                json.dumps(experience.outcome),
                experience.success,
                experience.confidence,
                experience.timestamp
            ))
            self.connection.commit()
            
        except Exception as e:
            logger.error(f"Error storing experience: {e}")
    
    async def _load_learning_data(self):
        """Load patterns and recent experiences from database"""
        if not self.connection:
            return
        
        try:
            # Load patterns
            cursor = self.connection.execute("SELECT * FROM patterns")
            for row in cursor.fetchall():
                pattern_id = row[0]
                pattern_data = json.loads(row[1])
                self.patterns[pattern_id] = pattern_data
            
            # Load recent experiences (last 1000)
            cursor = self.connection.execute("""
                SELECT context, action, outcome, success, confidence, timestamp 
                FROM experiences 
                ORDER BY timestamp DESC 
                LIMIT 1000
            """)
            
            for row in cursor.fetchall():
                experience = LearningData(
                    context=json.loads(row[0]),
                    action=json.loads(row[1]),
                    outcome=json.loads(row[2]),
                    success=row[3],
                    confidence=row[4],
                    timestamp=row[5]
                )
                self.experiences.appendleft(experience)  # Add to front to maintain order
                
        except Exception as e:
            logger.error(f"Error loading learning data: {e}")
    
    async def shutdown(self):
        """Shutdown the learning adapter"""
        self.active = False
        
        # Store current patterns
        if self.connection:
            try:
                for pattern_id, pattern in self.patterns.items():
                    self.connection.execute("""
                        INSERT OR REPLACE INTO patterns 
                        (id, pattern_data, success_rate, occurrence_count, confidence, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        pattern_id,
                        json.dumps(pattern),
                        pattern.get("success_rate", 0.0),
                        pattern.get("occurrence_count", 0),
                        pattern.get("confidence", 0.0),
                        pattern.get("created_at", datetime.now().timestamp()),
                        datetime.now().timestamp()
                    ))
                self.connection.commit()
                self.connection.close()
                
            except Exception as e:
                logger.error(f"Error during shutdown: {e}")
        
        logger.info("Learning adapter shutdown completed")