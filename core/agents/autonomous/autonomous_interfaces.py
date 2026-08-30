"""
Autonomous control interfaces for decision-making and planning
"""

import asyncio
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Set, Union
from dataclasses import dataclass
from enum import Enum


class AutonomyLevel(Enum):
    """Levels of autonomous operation"""
    REACTIVE = "reactive"
    DELIBERATIVE = "deliberative" 
    ADAPTIVE = "adaptive"
    CREATIVE = "creative"
    SELF_MODIFYING = "self_modifying"


class PlanningStrategy(Enum):
    """Planning strategy types"""
    HIERARCHICAL = "hierarchical"
    REACTIVE = "reactive"
    GOAL_ORIENTED = "goal_oriented"
    ADAPTIVE = "adaptive"


class DecisionType(Enum):
    """Types of decisions"""
    OPERATIONAL = "operational"
    STRATEGIC = "strategic"
    EMERGENCY = "emergency"
    MAINTENANCE = "maintenance"


@dataclass
class Decision:
    """Decision data structure"""
    decision_id: str
    decision_type: DecisionType
    context: Dict[str, Any]
    options: List[Dict[str, Any]]
    selected_option: Optional[Dict[str, Any]] = None
    confidence: float = 0.0
    timestamp: float = 0.0


@dataclass
class ExecutionPlan:
    """Execution plan data structure"""
    plan_id: str
    goal: str
    strategy: PlanningStrategy
    steps: List[Dict[str, Any]]
    resources: Dict[str, Any]
    constraints: List[str]
    estimated_duration: float = 0.0


class IDecisionEngine(ABC):
    """Interface for decision-making"""
    
    @abstractmethod
    async def analyze_situation(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze current situation for decision-making"""
        pass
    
    @abstractmethod
    async def generate_options(self, situation: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate possible decision options"""
        pass
    
    @abstractmethod
    async def evaluate_options(self, options: List[Dict[str, Any]], criteria: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Evaluate decision options against criteria"""
        pass
    
    @abstractmethod
    async def make_decision(self, options: List[Dict[str, Any]]) -> Decision:
        """Make the final decision"""
        pass


class IPlanningEngine(ABC):
    """Interface for planning and goal management"""
    
    @abstractmethod
    async def create_goal(self, goal_data: Dict[str, Any]) -> str:
        """Create a new goal"""
        pass
    
    @abstractmethod
    async def generate_plan(self, goal_id: str, strategy: PlanningStrategy) -> ExecutionPlan:
        """Generate execution plan for a goal"""
        pass
    
    @abstractmethod
    async def update_plan(self, plan_id: str, updates: Dict[str, Any]) -> bool:
        """Update an existing plan"""
        pass
    
    @abstractmethod
    async def monitor_execution(self, plan_id: str) -> Dict[str, Any]:
        """Monitor plan execution progress"""
        pass
    
    @abstractmethod
    async def adapt_plan(self, plan_id: str, feedback: Dict[str, Any]) -> ExecutionPlan:
        """Adapt plan based on feedback"""
        pass


class IAutonomousController(ABC):
    """Main autonomous controller interface"""
    
    @abstractmethod
    async def initialize(self, autonomy_level: AutonomyLevel = AutonomyLevel.ADAPTIVE) -> bool:
        """Initialize the autonomous controller"""
        pass
    
    @abstractmethod
    async def set_autonomy_level(self, level: AutonomyLevel) -> bool:
        """Set the autonomy level"""
        pass
    
    @abstractmethod
    async def get_autonomy_level(self) -> AutonomyLevel:
        """Get current autonomy level"""
        pass
    
    @abstractmethod
    async def process_input(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process input and generate autonomous response"""
        pass
    
    @abstractmethod
    async def execute_autonomous_cycle(self) -> Dict[str, Any]:
        """Execute one autonomous decision-action cycle"""
        pass
    
    @abstractmethod
    async def get_system_status(self) -> Dict[str, Any]:
        """Get autonomous system status"""
        pass
    
    @abstractmethod
    async def handle_emergency(self, emergency_data: Dict[str, Any]) -> Dict[str, Any]:
        """Handle emergency situations"""
        pass
    
    @abstractmethod
    async def learn_from_experience(self, experience: Dict[str, Any]) -> bool:
        """Learn from autonomous experiences"""
        pass