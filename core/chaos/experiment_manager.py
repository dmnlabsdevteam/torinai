#!/usr/bin/env python3
"""
Chaos Experiment Manager
=========================

Manages chaos experiment lifecycle, CRUD operations, and scenario library.
"""

import json
import logging
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from .types import (
    ChaosExperiment,
    ChaosType,
    ExperimentStatus,
    Hypothesis,
    InjectionConfig,
)

logger = logging.getLogger(__name__)


class ChaosExperimentManager:
    """
    Chaos Experiment Manager

    Responsibilities:
    - CRUD operations for chaos experiments
    - Experiment configuration validation
    - Scenario library management
    - Blast radius configuration
    - Hypothesis definition and validation
    - Experiment versioning and history
    """

    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize chaos experiment manager.

        Args:
            config_path: Path to chaos_config.json (default: config/chaos_config.json)
        """
        self.config_path = config_path or str(
            Path(__file__).parent.parent.parent / "config" / "chaos_config.json"
        )
        self.config = self._load_config()

        # PostgreSQL persistence via LoggingDatabase (unified schema)
        from core.database.logging_database import get_logging_db
        self.db = get_logging_db()

        # In-memory cache for quick access
        self.experiments_cache: Dict[str, ChaosExperiment] = {}

        # Scenario library (loaded from scenario files)
        self.scenarios: Dict[str, Dict] = {}

        logger.info("ChaosExperimentManager initialized with PostgreSQL logging database")

    def _load_config(self) -> Dict:
        """Load chaos configuration from JSON file"""
        try:
            with open(self.config_path, 'r') as f:
                config = json.load(f)
            logger.info(f"Loaded chaos config from {self.config_path}")
            return config
        except Exception as e:
            logger.error(f"Failed to load chaos config: {e}")
            return self._get_default_config()

    def _get_default_config(self) -> Dict:
        """Get default configuration"""
        return {
            "enabled": True,
            "safety_controls": {
                "max_concurrent_experiments": 3,
                "max_blast_radius_production": 50
            },
            "target_systems": {}
        }

    async def create_experiment(
        self,
        name: str,
        description: str,
        target_system: str,
        chaos_type: ChaosType,
        environment: str,
        injection_config: InjectionConfig,
        blast_radius: int = 1,
        hypothesis: Optional[Hypothesis] = None,
        created_by: str = "torin_ai"
    ) -> ChaosExperiment:
        """
        Create a new chaos experiment.

        Args:
            name: Experiment name
            description: Experiment description
            target_system: Target system (e.g., "learning_system")
            chaos_type: Type of chaos to inject
            environment: Environment (dev, staging, production)
            injection_config: Injection configuration
            blast_radius: Percentage of traffic to affect (1-100)
            hypothesis: Experiment hypothesis
            created_by: Creator identifier

        Returns:
            ChaosExperiment instance

        Raises:
            ValueError: If validation fails
        """
        # Generate experiment ID
        experiment_id = f"chaos_{uuid.uuid4().hex[:12]}"

        # Create experiment
        experiment = ChaosExperiment(
            experiment_id=experiment_id,
            name=name,
            description=description,
            target_system=target_system,
            chaos_type=chaos_type,
            environment=environment,
            injection_config=injection_config,
            blast_radius=blast_radius,
            hypothesis=hypothesis,
            created_by=created_by,
            status=ExperimentStatus.PENDING
        )

        # Validate experiment
        validation_result = await self.validate_experiment(experiment)
        if not validation_result["valid"]:
            raise ValueError(f"Experiment validation failed: {validation_result['errors']}")

        # Log to PostgreSQL via LoggingDatabase
        experiment_config = {
            "target_system": target_system,
            "chaos_type": chaos_type.value if hasattr(chaos_type, 'value') else str(chaos_type),
            "environment": environment,
            "injection_config": {
                "component": injection_config.component,
                "injection_point": injection_config.injection_point,
                "chaos_type": injection_config.chaos_type.value if hasattr(injection_config.chaos_type, 'value') else str(injection_config.chaos_type),
                "delay_ms": injection_config.delay_ms,
                "jitter_ms": injection_config.jitter_ms,
                "error_rate": injection_config.error_rate,
                "error_type": injection_config.error_type,
                "resource_type": injection_config.resource_type,
                "limit_value": injection_config.limit_value
            },
            "blast_radius": blast_radius
        }

        hypothesis_dict = None
        if hypothesis:
            hypothesis_dict = {
                "description": hypothesis.description,
                "expected_behavior": hypothesis.expected_behavior,
                "success_criteria": [
                    {
                        "name": criterion.name,
                        "metric_name": criterion.metric_name,
                        "operator": criterion.operator,
                        "expected_value": criterion.expected_value
                    }
                    for criterion in hypothesis.success_criteria
                ] if hasattr(hypothesis, 'success_criteria') else []
            }

        success = await self.db.log_chaos_experiment(
            experiment_id=experiment_id,
            name=name,
            description=description,
            target_system=target_system,
            chaos_type=chaos_type.value if hasattr(chaos_type, 'value') else str(chaos_type),
            environment=environment,
            experiment_config=experiment_config,
            blast_radius=blast_radius,
            created_by=created_by,
            hypothesis=hypothesis_dict,
            metadata=None
        )

        if not success:
            logger.error(f"Failed to persist experiment {experiment_id} to MySQL")

        # Cache experiment
        self.experiments_cache[experiment_id] = experiment

        logger.info(f"Created chaos experiment: {experiment_id} ({name})")

        return experiment

    async def get_experiment(self, experiment_id: str) -> Optional[ChaosExperiment]:
        """
        Get experiment by ID.

        Args:
            experiment_id: Experiment identifier

        Returns:
            ChaosExperiment instance or None if not found
        """
        # Check cache first
        if experiment_id in self.experiments_cache:
            return self.experiments_cache[experiment_id]

        # Load from PostgreSQL logging database
        experiments = await self.db.get_chaos_experiments(limit=1000)
        for exp_dict in experiments:
            if exp_dict.get('experiment_id') == experiment_id:
                # Reconstruct ChaosExperiment from dict
                experiment = self._reconstruct_experiment_from_dict(exp_dict)
                # Cache it
                self.experiments_cache[experiment_id] = experiment
                return experiment

        return None

    async def list_experiments(
        self,
        target_system: Optional[str] = None,
        environment: Optional[str] = None,
        status: Optional[ExperimentStatus] = None
    ) -> List[ChaosExperiment]:
        """
        List experiments with optional filtering.

        Args:
            target_system: Filter by target system
            environment: Filter by environment
            status: Filter by status

        Returns:
            List of matching experiments
        """
        # Get from PostgreSQL with filters
        status_str = status.value if status and hasattr(status, 'value') else None
        experiments_dicts = await self.db.get_chaos_experiments(
            target_system=target_system,
            environment=environment,
            status=status_str,
            limit=1000
        )

        # Reconstruct ChaosExperiment objects
        experiments = []
        for exp_dict in experiments_dicts:
            experiment = self._reconstruct_experiment_from_dict(exp_dict)
            experiments.append(experiment)
            # Update cache
            self.experiments_cache[experiment.experiment_id] = experiment

        return experiments

    def _reconstruct_experiment_from_dict(self, exp_dict: Dict[str, Any]) -> ChaosExperiment:
        """
        Reconstruct ChaosExperiment from database dict

        Args:
            exp_dict: Experiment dict from MySQL

        Returns:
            ChaosExperiment instance
        """
        # Extract config
        config = exp_dict.get('experiment_config', {})
        injection_config_dict = config.get('injection_config', {})

        # Reconstruct InjectionConfig
        injection_config = InjectionConfig(
            component=injection_config_dict.get('component', 'unknown'),
            injection_point=injection_config_dict.get('injection_point', 'unknown'),
            chaos_type=ChaosType(injection_config_dict.get('chaos_type', 'latency')),
            delay_ms=injection_config_dict.get('delay_ms'),
            jitter_ms=injection_config_dict.get('jitter_ms'),
            error_rate=injection_config_dict.get('error_rate'),
            error_type=injection_config_dict.get('error_type'),
            resource_type=injection_config_dict.get('resource_type'),
            limit_value=injection_config_dict.get('limit_value')
        )

        # Reconstruct Hypothesis if present
        hypothesis = None
        hypothesis_dict = exp_dict.get('hypothesis')
        if hypothesis_dict:
            hypothesis = Hypothesis(
                description=hypothesis_dict.get('description', ''),
                expected_behavior=hypothesis_dict.get('expected_behavior', {})
            )

        # Reconstruct ChaosExperiment
        experiment = ChaosExperiment(
            experiment_id=exp_dict['experiment_id'],
            name=exp_dict['name'],
            description=exp_dict.get('description', ''),
            target_system=exp_dict['target_system'],
            chaos_type=ChaosType(exp_dict['chaos_type']),
            environment=exp_dict['environment'],
            injection_config=injection_config,
            blast_radius=exp_dict.get('blast_radius', 1),
            hypothesis=hypothesis,
            created_by=exp_dict.get('created_by', 'torin_ai'),
            status=ExperimentStatus(exp_dict['status'])
        )

        # Set optional fields
        experiment.governance_decision_id = exp_dict.get('governance_decision_id')
        experiment.governance_tier = exp_dict.get('governance_tier')
        experiment.started_at = exp_dict.get('started_at')
        experiment.ended_at = exp_dict.get('ended_at')
        experiment.duration_seconds = exp_dict.get('duration_seconds')
        experiment.rollback_reason = exp_dict.get('rollback_reason')
        experiment.metadata = exp_dict.get('metadata', {})

        return experiment

    async def update_experiment(
        self,
        experiment_id: str,
        **updates
    ) -> Optional[ChaosExperiment]:
        """
        Update experiment fields.

        Args:
            experiment_id: Experiment identifier
            **updates: Fields to update

        Returns:
            Updated experiment or None if not found
        """
        experiment = await self.get_experiment(experiment_id)
        if not experiment:
            logger.warning(f"Experiment not found: {experiment_id}")
            return None

        # Update allowed fields
        allowed_fields = {
            'status', 'blast_radius', 'governance_decision_id',
            'governance_tier', 'started_at', 'ended_at',
            'duration_seconds', 'rollback_reason'
        }

        # Prepare updates for persistence layer
        db_updates = {}

        for field, value in updates.items():
            if field in allowed_fields:
                setattr(experiment, field, value)
                logger.debug(f"Updated experiment {experiment_id}: {field} = {value}")

                # Map to persistence field names
                if field == 'status' and hasattr(value, 'value'):
                    db_updates['status'] = value.value
                elif field == 'governance_tier' and hasattr(value, 'value'):
                    db_updates['governance_tier'] = value.value
                else:
                    db_updates[field] = value

        # Persist to PostgreSQL
        if db_updates:
            await self.db.update_chaos_experiment(experiment_id, **db_updates)

        # Update cache
        self.experiments_cache[experiment_id] = experiment

        return experiment

    async def delete_experiment(self, experiment_id: str) -> bool:
        """
        Delete an experiment.

        Args:
            experiment_id: Experiment identifier

        Returns:
            True if deleted, False if not found
        """
        # Delete from PostgreSQL (cascades to metrics and events via FK)
        try:
            await self.db.delete_chaos_experiment(experiment_id)

            # Remove from cache
            if experiment_id in self.experiments_cache:
                del self.experiments_cache[experiment_id]

            logger.info(f"Deleted experiment: {experiment_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to delete experiment {experiment_id}: {e}")
            return False

    async def validate_experiment(self, experiment: ChaosExperiment) -> Dict:
        """
        Validate experiment configuration.

        Args:
            experiment: Experiment to validate

        Returns:
            Validation result with 'valid' bool and 'errors' list
        """
        errors = []

        # Check if target system exists in config
        if experiment.target_system not in self.config.get("target_systems", {}):
            errors.append(f"Unknown target system: {experiment.target_system}")

        # Check if target system is enabled
        target_config = self.config.get("target_systems", {}).get(experiment.target_system, {})
        if not target_config.get("enabled", True):
            errors.append(f"Target system disabled: {experiment.target_system}")

        # Validate blast radius
        if not 1 <= experiment.blast_radius <= 100:
            errors.append(f"Invalid blast radius: {experiment.blast_radius} (must be 1-100)")

        # Check blast radius limits per environment
        max_blast_radius = self._get_max_blast_radius(experiment.environment, experiment.target_system)
        if experiment.blast_radius > max_blast_radius:
            errors.append(
                f"Blast radius {experiment.blast_radius}% exceeds limit for "
                f"{experiment.environment}: {max_blast_radius}%"
            )

        # Validate environment
        valid_environments = ["dev", "staging", "production"]
        if experiment.environment not in valid_environments:
            errors.append(f"Invalid environment: {experiment.environment}")

        # Validate injection config component
        valid_components = target_config.get("components", [])
        if valid_components and experiment.injection_config.component not in valid_components:
            errors.append(
                f"Unknown component: {experiment.injection_config.component} "
                f"(valid: {valid_components})"
            )

        return {
            "valid": len(errors) == 0,
            "errors": errors
        }

    def _get_max_blast_radius(self, environment: str, target_system: str) -> int:
        """Get maximum allowed blast radius for environment/system"""
        safety_controls = self.config.get("safety_controls", {})

        # Check system-specific limit
        target_config = self.config.get("target_systems", {}).get(target_system, {})
        system_limit = target_config.get("max_blast_radius")
        if system_limit is not None:
            return system_limit

        # Check environment-specific limit
        if environment == "dev":
            return safety_controls.get("max_blast_radius_dev", 100)
        elif environment == "staging":
            return safety_controls.get("max_blast_radius_staging", 100)
        elif environment == "production":
            return safety_controls.get("max_blast_radius_production", 50)

        return 100

    async def set_blast_radius(self, experiment_id: str, blast_radius: int) -> bool:
        """
        Update experiment blast radius.

        Args:
            experiment_id: Experiment identifier
            blast_radius: New blast radius (1-100)

        Returns:
            True if updated successfully
        """
        experiment = await self.get_experiment(experiment_id)
        if not experiment:
            return False

        if not 1 <= blast_radius <= 100:
            logger.error(f"Invalid blast radius: {blast_radius}")
            return False

        # Check if within limits
        max_blast_radius = self._get_max_blast_radius(
            experiment.environment,
            experiment.target_system
        )

        if blast_radius > max_blast_radius:
            logger.error(
                f"Blast radius {blast_radius}% exceeds limit: {max_blast_radius}%"
            )
            return False

        experiment.blast_radius = blast_radius
        logger.info(f"Updated blast radius for {experiment_id}: {blast_radius}%")

        return True

    def load_scenario_library(self, scenarios_dir: Optional[str] = None):
        """
        Load scenario library from scenario files.

        Args:
            scenarios_dir: Directory containing scenario files
        """
        try:
            # Import scenarios from the scenarios module
            from .scenarios import (
                TOOL_SCENARIOS,
                LEARNING_SCENARIOS,
                SECURITY_SCENARIOS,
                REASONING_SCENARIOS,
                AGENT_SCENARIOS,
                DOMAIN_SCENARIOS,
                MEMORY_SCENARIOS,
                INTELLIGENCE_SCENARIOS,
                MONITORING_SCENARIOS,
                SERVICES_SCENARIOS,
            )

            # Combine all scenario dictionaries
            all_scenario_groups = [
                TOOL_SCENARIOS,
                LEARNING_SCENARIOS,
                SECURITY_SCENARIOS,
                REASONING_SCENARIOS,
                AGENT_SCENARIOS,
                DOMAIN_SCENARIOS,
                MEMORY_SCENARIOS,
                INTELLIGENCE_SCENARIOS,
                MONITORING_SCENARIOS,
                SERVICES_SCENARIOS,
            ]

            # Load scenarios from each group
            for scenario_group in all_scenario_groups:
                if isinstance(scenario_group, dict):
                    # Dict format: {scenario_id: scenario_config}
                    for scenario_id, scenario_config in scenario_group.items():
                        self.scenarios[scenario_id] = scenario_config
                        logger.debug(f"Loaded scenario: {scenario_id}")
                elif isinstance(scenario_group, list):
                    # List format: [{"id": scenario_id, ...}, ...]
                    for scenario in scenario_group:
                        scenario_id = scenario.get("id")
                        if scenario_id:
                            self.scenarios[scenario_id] = scenario
                            logger.debug(f"Loaded scenario: {scenario_id}")

            logger.info(f"Loaded {len(self.scenarios)} total scenarios from scenarios module")

        except Exception as e:
            logger.error(f"Failed to load scenarios from module: {e}")
            import traceback
            traceback.print_exc()

    async def get_scenario_template(self, scenario_id: str) -> Optional[Dict]:
        """
        Get a scenario template by ID.

        Args:
            scenario_id: Scenario identifier

        Returns:
            Scenario template dict or None if not found
        """
        return self.scenarios.get(scenario_id)

    async def create_experiment_from_scenario(
        self,
        scenario_id: str,
        environment: str,
        blast_radius: int = 1,
        created_by: str = "torin_ai"
    ) -> Optional[ChaosExperiment]:
        """
        Create an experiment from a scenario template.

        Args:
            scenario_id: Scenario identifier
            environment: Target environment
            blast_radius: Blast radius override
            created_by: Creator identifier

        Returns:
            ChaosExperiment instance or None if scenario not found
        """
        scenario = await self.get_scenario_template(scenario_id)
        if not scenario:
            logger.error(f"Scenario not found: {scenario_id}")
            return None

        # Extract scenario configuration
        name = scenario.get("name", scenario_id)
        description = scenario.get("description", "")
        target_system = scenario.get("target_system", scenario.get("target", "unknown"))
        chaos_type_obj = scenario.get("chaos_type")

        # Parse chaos type
        if isinstance(chaos_type_obj, ChaosType):
            chaos_type = chaos_type_obj
        elif isinstance(chaos_type_obj, str):
            try:
                chaos_type = ChaosType(chaos_type_obj)
            except ValueError:
                logger.error(f"Invalid chaos type in scenario: {chaos_type_obj}")
                return None
        else:
            logger.error(f"Invalid chaos type in scenario: {chaos_type_obj}")
            return None

        # Get injection config from scenario
        injection_config_dict = scenario.get("injection_config", {})
        component = scenario.get("component", injection_config_dict.get("component", "unknown"))
        injection_point = scenario.get("injection_point", injection_config_dict.get("injection_point", "unknown"))

        # Create injection config
        injection_config = InjectionConfig(
            component=component,
            injection_point=injection_point,
            chaos_type=chaos_type,
            delay_ms=injection_config_dict.get("delay_ms"),
            jitter_ms=injection_config_dict.get("jitter_ms"),
            error_rate=injection_config_dict.get("error_rate"),
            error_type=injection_config_dict.get("error_type"),
            resource_type=injection_config_dict.get("resource_type"),
            limit_value=injection_config_dict.get("limit_value")
        )

        # Create hypothesis if present
        hypothesis = None
        if "hypothesis" in scenario:
            hypothesis_dict = scenario["hypothesis"]

            # Handle two formats:
            # 1. Dict format: {"hypothesis_statement": "...", "expected_behavior": {...}}
            # 2. String format: just a string description
            if isinstance(hypothesis_dict, dict):
                description = hypothesis_dict.get("hypothesis_statement", "")
                expected_behavior = hypothesis_dict.get("expected_behavior", {})
            else:
                description = str(hypothesis_dict)
                expected_behavior = scenario.get("expected_behavior", {})

            # Handle case where expected_behavior might be a string
            if isinstance(expected_behavior, str):
                expected_behavior = {}

            hypothesis = Hypothesis(
                description=description,
                expected_behavior=expected_behavior
            )

            # Add success criteria
            for criterion_name, criterion_value in scenario.get("success_criteria", {}).items():
                hypothesis.add_criterion(
                    name=criterion_name,
                    metric_name=criterion_name,
                    operator="==",
                    expected_value=criterion_value
                )

        # Create experiment
        experiment = await self.create_experiment(
            name=f"{name} ({environment})",
            description=description,
            target_system=target_system,
            chaos_type=chaos_type,
            environment=environment,
            injection_config=injection_config,
            blast_radius=blast_radius,
            hypothesis=hypothesis,
            created_by=created_by
        )

        # Populate metadata with scenario context
        experiment.metadata = {
            "scenario_id": scenario_id,
            "scenario_name": name,
            "scenario_description": description,
            "environment": environment,
            "created_from_scenario": True,
            "blast_radius_requested": blast_radius,
            "injection_component": component,
            "injection_point": injection_point
        }

        logger.info(f"Created experiment from scenario {scenario_id}: {experiment.experiment_id}")

        return experiment

    async def get_active_experiments(self, target_system: Optional[str] = None) -> List[ChaosExperiment]:
        """
        Get all currently running experiments.

        Args:
            target_system: Optional filter by target system

        Returns:
            List of running experiments
        """
        # Get running experiments from MySQL
        experiments = await self.list_experiments(
            target_system=target_system,
            status=ExperimentStatus.RUNNING
        )

        return experiments

    async def get_experiment_count_by_status(self) -> Dict[str, int]:
        """
        Get count of experiments by status.

        Returns:
            Dict mapping status to count
        """
        try:
            result = await self.db.execute_query(
                """
                SELECT status, COUNT(*) as count
                FROM chaos_experiments
                GROUP BY status
                """,
                fetch='all'
            )

            counts = {}
            if result:
                for row in result:
                    counts[row[0]] = row[1]

            return counts

        except Exception as e:
            logger.error(f"Failed to get experiment counts: {e}")
            return {}


# Singleton instance
_experiment_manager = None


def get_experiment_manager() -> ChaosExperimentManager:
    """Get global experiment manager instance"""
    global _experiment_manager
    if _experiment_manager is None:
        _experiment_manager = ChaosExperimentManager()
        # Load scenario library on initialization
        _experiment_manager.load_scenario_library()
    return _experiment_manager
