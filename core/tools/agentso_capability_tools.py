"""
AgentSO Capability-Based Tool Discovery
Dynamically generates and registers tools based on user's enabled integrations and capabilities.
"""

import asyncio
from typing import List, Dict, Set, Optional, Any
from enum import Enum
from dataclasses import dataclass

from .capabilities import Capability
from .tool_registry import ToolRegistry, ToolParameter, ToolCategory, ToolSafety
from .connector_tools import ConnectorTool
from ..database import DatabaseManager


class CapabilityMode(Enum):
    """Execution mode for a capability"""
    READ = "read"   # Read-only analysis and reporting
    AUTO = "auto"   # Autonomous actions and remediation


@dataclass
class CapabilityConfig:
    """User's configuration for a specific capability"""
    capability_id: str
    integration_id: str
    enabled: bool
    mode: CapabilityMode
    config: Dict[str, Any]  # Capability-specific settings


@dataclass
class CapabilityMapping:
    """Maps a high-level capability to connector tool methods"""
    capability: Capability
    connector_type: str
    read_methods: List[str]   # Methods available in read mode
    auto_methods: List[str]   # Additional methods in auto mode
    category: ToolCategory = ToolCategory.SECURITY
    safety_level: ToolSafety = ToolSafety.MODERATE


# ============================================================================
# CAPABILITY TO TOOL MAPPINGS
# ============================================================================

# Maps AgentSO capabilities to actual connector methods
CAPABILITY_MAPPINGS: List[CapabilityMapping] = [

    # ========== THREAT HUNTING ==========
    CapabilityMapping(
        capability=Capability.THREAT_HUNT,
        connector_type='qradar',
        read_methods=['search_aql', 'get_offenses'],
        auto_methods=['create_offense_note', 'update_offense_status'],
    ),
    CapabilityMapping(
        capability=Capability.THREAT_HUNT,
        connector_type='arcsight',
        read_methods=['search_events', 'get_active_channels'],
        auto_methods=['create_case'],
    ),
    CapabilityMapping(
        capability=Capability.THREAT_HUNT,
        connector_type='logrhythm',
        read_methods=['search_logs', 'get_alarms'],
        auto_methods=['update_alarm_status'],
    ),

    # ========== INCIDENT INVESTIGATION ==========
    CapabilityMapping(
        capability=Capability.INVESTIGATE_INCIDENT,
        connector_type='qradar',
        read_methods=['get_offenses', 'search_aql', 'get_offense_summary'],
        auto_methods=['update_offense_status', 'assign_offense'],
    ),
    CapabilityMapping(
        capability=Capability.INVESTIGATE_INCIDENT,
        connector_type='thehive',
        read_methods=['get_cases', 'get_case_tasks', 'get_observables'],
        auto_methods=['create_case', 'update_case', 'create_task'],
    ),
    CapabilityMapping(
        capability=Capability.INVESTIGATE_INCIDENT,
        connector_type='arcsight',
        read_methods=['get_cases', 'get_events'],
        auto_methods=['create_case', 'update_case'],
    ),

    # ========== CODE SECURITY ==========
    CapabilityMapping(
        capability=Capability.SECURITY_CODE_REVIEW,
        connector_type='github',
        read_methods=['get_code_scanning_alerts', 'list_repositories', 'get_repository_security_summary'],
        auto_methods=['create_issue', 'create_pull_request'],
        safety_level=ToolSafety.HIGH,  # Creating PRs is higher risk
    ),

    CapabilityMapping(
        capability=Capability.DEPENDENCY_SCAN,
        connector_type='github',
        read_methods=['get_vulnerabilities', 'get_dependency_graph'],
        auto_methods=['create_pull_request', 'enable_vulnerability_alerts'],
    ),

    CapabilityMapping(
        capability=Capability.SECRET_DETECTION,
        connector_type='github',
        read_methods=['get_secret_scanning_alerts'],
        auto_methods=['create_issue', 'revoke_credential'],  # Requires integration with vault/IAM
        safety_level=ToolSafety.HIGH,
    ),

    # ========== THREAT INTELLIGENCE ==========
    CapabilityMapping(
        capability=Capability.IOC_ENRICHMENT,
        connector_type='virustotal',
        read_methods=['get_ip_report', 'get_domain_report', 'get_file_report', 'get_url_report'],
        auto_methods=['scan_url', 'rescan_file'],
    ),
    CapabilityMapping(
        capability=Capability.IOC_ENRICHMENT,
        connector_type='alienvault',
        read_methods=['lookup_indicator', 'get_subscribed_pulses'],
        auto_methods=['create_pulse'],
    ),
    CapabilityMapping(
        capability=Capability.IOC_ENRICHMENT,
        connector_type='shodan',
        read_methods=['search_hosts', 'get_host_info', 'dns_lookup'],
        auto_methods=[],  # Shodan is read-only
    ),
    CapabilityMapping(
        capability=Capability.IOC_ENRICHMENT,
        connector_type='abuseipdb',
        read_methods=['check_ip'],
        auto_methods=['report_ip'],
    ),

    CapabilityMapping(
        capability=Capability.THREAT_ATTRIBUTION,
        connector_type='misp',
        read_methods=['search_iocs', 'get_events', 'get_attributes'],
        auto_methods=['create_event', 'add_attribute', 'tag_event'],
    ),

    # ========== INCIDENT RESPONSE ==========
    CapabilityMapping(
        capability=Capability.ISOLATE_HOST,
        connector_type='carbonblack',
        read_methods=['get_device_info', 'search_processes'],
        auto_methods=['quarantine_device', 'unquarantine_device'],
        safety_level=ToolSafety.CRITICAL,
    ),
    CapabilityMapping(
        capability=Capability.ISOLATE_HOST,
        connector_type='crowdstrike',
        read_methods=['get_host_info', 'search_detections'],
        auto_methods=['contain_host', 'lift_containment'],
        safety_level=ToolSafety.CRITICAL,
    ),

    CapabilityMapping(
        capability=Capability.EXECUTE_PLAYBOOK,
        connector_type='shuffle',
        read_methods=['get_workflows', 'get_workflow_executions'],
        auto_methods=['execute_workflow'],
        safety_level=ToolSafety.HIGH,
    ),

    CapabilityMapping(
        capability=Capability.WAR_ROOM_MANAGEMENT,
        connector_type='slack',
        read_methods=['list_channels', 'get_channel_history'],
        auto_methods=['create_channel', 'invite_users', 'post_message'],
    ),
    CapabilityMapping(
        capability=Capability.WAR_ROOM_MANAGEMENT,
        connector_type='pagerduty',
        read_methods=['get_incidents', 'get_users', 'get_services'],
        auto_methods=['create_incident', 'update_incident', 'add_note'],
    ),

    # ========== CLOUD SECURITY ==========
    CapabilityMapping(
        capability=Capability.CLOUD_REMEDIATION,
        connector_type='aws_security_hub',
        read_methods=['get_findings', 'get_insights'],
        auto_methods=['update_findings', 'create_finding'],
        safety_level=ToolSafety.HIGH,
    ),
    CapabilityMapping(
        capability=Capability.CLOUD_REMEDIATION,
        connector_type='azure_security_center',
        read_methods=['get_alerts', 'get_recommendations', 'get_secure_score'],
        auto_methods=['update_alert', 'apply_recommendation'],
        safety_level=ToolSafety.HIGH,
    ),

    # ========== VULNERABILITY MANAGEMENT ==========
    CapabilityMapping(
        capability=Capability.VULN_PRIORITIZATION,
        connector_type='tenable',
        read_methods=['get_vulnerabilities', 'get_assets', 'export_vulnerabilities'],
        auto_methods=['create_scan', 'launch_scan'],
    ),
    CapabilityMapping(
        capability=Capability.VULN_PRIORITIZATION,
        connector_type='qualys',
        read_methods=['get_host_list', 'get_scans'],
        auto_methods=['launch_scan'],
    ),

    # ========== COMPLIANCE ==========
    CapabilityMapping(
        capability=Capability.COMPLIANCE_CHECK,
        connector_type='qradar',
        read_methods=['search_aql', 'get_offenses'],
        auto_methods=['create_custom_rule'],
    ),
    CapabilityMapping(
        capability=Capability.COMPLIANCE_CHECK,
        connector_type='azure_security_center',
        read_methods=['get_regulatory_compliance', 'get_secure_score'],
        auto_methods=['apply_recommendation'],
    ),
]


# ============================================================================
# CAPABILITY DISCOVERY & REGISTRATION
# ============================================================================

class AgentSOCapabilityDiscovery:
    """Discovers and registers AgentSO tools based on user's enabled capabilities"""

    def __init__(self, db: DatabaseManager, registry: ToolRegistry):
        self.db = db
        self.registry = registry
        self._capability_map = self._build_capability_map()

    def _build_capability_map(self) -> Dict[str, List[CapabilityMapping]]:
        """Build lookup map from connector_type to capability mappings"""
        mapping = {}
        for cap_mapping in CAPABILITY_MAPPINGS:
            connector = cap_mapping.connector_type
            if connector not in mapping:
                mapping[connector] = []
            mapping[connector].append(cap_mapping)
        return mapping

    async def discover_capabilities_for_user(self, user_id: str) -> List[CapabilityConfig]:
        """
        Query database for user's enabled integrations and capability configs.

        Returns list of enabled capabilities with their configurations.
        """
        query = """
            SELECT
                ic.capability_id,
                ic.integration_id,
                ic.enabled,
                ic.mode,
                ic.config,
                di.connector_type
            FROM integration_capabilities ic
            JOIN data_integrations di ON ic.integration_id = di.id
            WHERE di.user_id = $1 AND di.active = true AND ic.enabled = true
        """

        results = await self.db.execute_query(query, (user_id,), fetch_all=True)

        capabilities = []
        for row in results:
            capabilities.append(CapabilityConfig(
                capability_id=row['capability_id'],
                integration_id=row['integration_id'],
                enabled=row['enabled'],
                mode=CapabilityMode(row['mode']),
                config=row['config'] or {}
            ))

        return capabilities

    async def get_enabled_integrations(self, user_id: str) -> Dict[str, List[str]]:
        """
        Get user's active integrations grouped by connector type.

        Returns: {
            'github': ['integration-uuid-1'],
            'qradar': ['integration-uuid-2', 'integration-uuid-3'],
            ...
        }
        """
        query = """
            SELECT id, connector_type, name
            FROM data_integrations
            WHERE user_id = $1 AND active = true
        """

        results = await self.db.execute_query(query, (user_id,), fetch_all=True)

        integrations = {}
        for row in results:
            connector_type = row['connector_type']
            if connector_type not in integrations:
                integrations[connector_type] = []
            integrations[connector_type].append(row['id'])

        return integrations

    def _generate_tool_for_capability(
        self,
        mapping: CapabilityMapping,
        mode: CapabilityMode,
        integration_id: str
    ) -> List[ConnectorTool]:
        """
        Generate ConnectorTool instances for a capability mapping based on mode.

        In READ mode: Only creates tools for read_methods
        In AUTO mode: Creates tools for both read_methods and auto_methods
        """
        tools = []

        # Always include read methods
        available_methods = mapping.read_methods.copy()

        # Add auto methods if in auto mode
        if mode == CapabilityMode.AUTO:
            available_methods.extend(mapping.auto_methods)

        # Generate tool for each method
        for method_name in available_methods:
            # Get method description from existing connector_tools.py registrations
            # or generate a default one
            description = self._get_method_description(
                mapping.connector_type,
                method_name,
                mapping.capability
            )

            # Generate parameters based on method signature
            parameters = self._infer_parameters(mapping.connector_type, method_name)

            tool = ConnectorTool(
                connector_name=mapping.connector_type,
                method_name=method_name,
                description=description,
                parameters=parameters,
                category=mapping.category,
                safety_level=mapping.safety_level,
                capability=mapping.capability,
                mode=mode,
                integration_id=integration_id
            )

            tools.append(tool)

        return tools

    def _get_method_description(
        self,
        connector_type: str,
        method_name: str,
        capability: Capability
    ) -> str:
        """Get human-readable description for a connector method"""
        # TODO: Load from connector metadata or docstrings
        # For now, generate a reasonable description
        action = method_name.replace('_', ' ').title()
        return f"{action} via {connector_type} ({capability.value})"

    def _infer_parameters(self, connector_type: str, method_name: str) -> List[ToolParameter]:
        """
        Infer parameters for a connector method.

        TODO: This should ideally inspect the actual method signature
        from the connector class. For now, use common patterns.
        """
        # Common parameter patterns
        common_params = {
            'search_aql': [
                ToolParameter(name='query', type='string', description='AQL query string', required=True),
                ToolParameter(name='range', type='string', description='Time range (e.g., "last 24 hours")', required=False),
            ],
            'get_offenses': [
                ToolParameter(name='filter', type='string', description='Filter criteria', required=False),
                ToolParameter(name='limit', type='number', description='Maximum results', required=False, default=100),
            ],
            'get_vulnerabilities': [
                ToolParameter(name='repository', type='string', description='Repository name (owner/repo)', required=True),
            ],
            'get_code_scanning_alerts': [
                ToolParameter(name='repository', type='string', description='Repository name (owner/repo)', required=True),
                ToolParameter(name='state', type='string', description='Alert state: open, closed, dismissed', required=False),
            ],
            'create_case': [
                ToolParameter(name='title', type='string', description='Case title', required=True),
                ToolParameter(name='description', type='string', description='Case description', required=True),
                ToolParameter(name='severity', type='string', description='Severity level', required=False),
            ],
            'quarantine_device': [
                ToolParameter(name='device_id', type='string', description='Device ID to quarantine', required=True),
                ToolParameter(name='reason', type='string', description='Reason for quarantine', required=True),
            ],
        }

        return common_params.get(method_name, [
            ToolParameter(name='params', type='object', description='Method parameters', required=False)
        ])

    async def register_tools_for_user(self, user_id: str) -> int:
        """
        Discover and register all AgentSO tools for a specific user.

        Returns number of tools registered.
        """
        # Get user's enabled integrations
        integrations = await self.get_enabled_integrations(user_id)

        # Get user's capability configurations
        capability_configs = await self.discover_capabilities_for_user(user_id)

        # Build lookup: (integration_id, capability_id) -> CapabilityConfig
        config_map = {
            (cfg.integration_id, cfg.capability_id): cfg
            for cfg in capability_configs
        }

        tools_registered = 0

        # For each enabled integration
        for connector_type, integration_ids in integrations.items():
            # Get capability mappings for this connector
            mappings = self._capability_map.get(connector_type, [])

            for mapping in mappings:
                # For each integration instance of this connector type
                for integration_id in integration_ids:
                    # Check if user has this capability enabled for this integration
                    config_key = (integration_id, mapping.capability.value)

                    if config_key in config_map:
                        config = config_map[config_key]

                        # Generate and register tools based on mode
                        tools = self._generate_tool_for_capability(
                            mapping,
                            config.mode,
                            integration_id
                        )

                        for tool in tools:
                            self.registry.register(tool)
                            tools_registered += 1

        return tools_registered

    async def get_capability_summary(self, user_id: str) -> Dict[str, Any]:
        """
        Get summary of user's enabled capabilities for display.

        Returns structured data for UI rendering.
        """
        integrations = await self.get_enabled_integrations(user_id)
        capabilities = await self.discover_capabilities_for_user(user_id)

        return {
            'total_integrations': sum(len(ids) for ids in integrations.values()),
            'total_capabilities': len(capabilities),
            'capabilities_by_mode': {
                'read': sum(1 for c in capabilities if c.mode == CapabilityMode.READ),
                'auto': sum(1 for c in capabilities if c.mode == CapabilityMode.AUTO),
            },
            'integrations': integrations,
            'capabilities': [
                {
                    'id': c.capability_id,
                    'mode': c.mode.value,
                    'integration_id': c.integration_id,
                }
                for c in capabilities
            ]
        }


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

async def register_agentso_tools(
    user_id: str,
    db: DatabaseManager,
    registry: ToolRegistry
) -> int:
    """
    Convenience function to register all AgentSO tools for a user.

    Usage:
        tools_count = await register_agentso_tools(user_id, db, registry)
    """
    discovery = AgentSOCapabilityDiscovery(db, registry)
    return await discovery.register_tools_for_user(user_id)


async def get_user_capabilities(
    user_id: str,
    db: DatabaseManager
) -> Dict[str, Any]:
    """
    Get summary of user's AgentSO capabilities.

    Usage:
        summary = await get_user_capabilities(user_id, db)
    """
    discovery = AgentSOCapabilityDiscovery(db, None)
    return await discovery.get_capability_summary(user_id)
