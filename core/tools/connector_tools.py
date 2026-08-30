#!/usr/bin/env python3
"""
AgentSO Connector Tools
=======================
Wraps AgentSO connectors as TorinAI tools.

Connectors are imported directly from services/agentso/connectors/.
When users configure connectors in AgentSO (providing API keys, credentials),
those connectors become immediately available to the VLM.

Author: Torin AI Team
"""

import sys
import logging
from pathlib import Path
from typing import List

from .tool_registry import Tool, ToolParameter, ToolResult, ToolCategory, ToolSafety
from .capabilities import Capability, ToolCapabilityProfile, CapabilityMetadata

logger = logging.getLogger(__name__)

# Add AgentSO to Python path so we can import connectors
AGENTSO_PATH = Path(__file__).parent.parent.parent.parent / "services" / "agentso"
if str(AGENTSO_PATH) not in sys.path:
    sys.path.insert(0, str(AGENTSO_PATH))

def get_active_connector():
    """Get the active connector with credentials already configured."""
    try:
        from connector_manager import connector_manager
        return connector_manager.get_connector()
    except ImportError as e:
        logger.error(f"Failed to import AgentSO connector_manager: {e}")
        return None


class ConnectorTool(Tool):
    """Wraps an AgentSO connector method as a TorinAI tool."""

    def __init__(self, connector_name: str, method_name: str, description: str,
                 parameters: List[ToolParameter], category: ToolCategory = ToolCategory.SECURITY,
                 safety_level: ToolSafety = ToolSafety.MODERATE):
        super().__init__()
        self.name = f"{connector_name}_{method_name}"
        self.description = description
        self.category = category
        self.safety_level = safety_level
        self.parameters = parameters
        self._connector_name = connector_name
        self._method_name = method_name

        from .capabilities import infer_capability_from_task
        inferred = infer_capability_from_task(description, threshold=1.0)
        cap_list = [CapabilityMetadata(capability=cap, description=description) for cap in inferred]
        if not cap_list:
            cap_list = [CapabilityMetadata(capability=Capability.HTTP_REQUEST, description=description)]
        self.capability_profile = ToolCapabilityProfile(
            tool_name=self.name,
            capabilities=cap_list,
            requires_network=True
        )

    async def execute(self, **kwargs) -> ToolResult:
        """Execute the connector method."""
        try:
            connector = get_active_connector()
            if not connector:
                return ToolResult(success=False, output=None,
                                error="No active connector. Configure one in AgentSO first.",
                                tool_name=self.name, parameters=kwargs)

            # Verify connector type matches
            connector_type = connector.__class__.__name__.replace('Connector', '').lower()
            if connector_type != self._connector_name:
                return ToolResult(success=False, output=None,
                                error=f"Active connector is {connector_type}, need {self._connector_name}",
                                tool_name=self.name, parameters=kwargs)

            # Execute method
            method = getattr(connector, self._method_name)
            result = await method(**kwargs)

            # Check for error in result
            if isinstance(result, dict) and 'error' in result:
                return ToolResult(success=False, output=result, error=result['error'],
                                tool_name=self.name, parameters=kwargs)

            return ToolResult(success=True, output=result, tool_name=self.name, parameters=kwargs)

        except Exception as e:
            logger.error(f"Error in {self.name}: {e}", exc_info=True)
            return ToolResult(success=False, output=None, error=str(e),
                            tool_name=self.name, parameters=kwargs)


def register_connector_tools(registry) -> int:
    """Register all AgentSO connector tools in TorinAI."""
    count = 0

    # VirusTotal Tools
    vt_tools = [
        ConnectorTool("virustotal", "scan_file",
                     "Scan a file hash in VirusTotal for malware",
                     [ToolParameter("file_hash", "string", "MD5/SHA1/SHA256 hash", True)],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
        ConnectorTool("virustotal", "scan_url",
                     "Scan a URL in VirusTotal for phishing/malware",
                     [ToolParameter("url", "string", "URL to scan", True)],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
        ConnectorTool("virustotal", "get_ip_report",
                     "Get VirusTotal threat intelligence for an IP address",
                     [ToolParameter("ip_address", "string", "IP address to check", True)],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
        ConnectorTool("virustotal", "get_domain_report",
                     "Get VirusTotal threat intelligence for a domain",
                     [ToolParameter("domain", "string", "Domain to check", True)],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
    ]
    for tool in vt_tools:
        registry.register(tool)
        count += 1

    # CrowdStrike Tools
    cs_tools = [
        ConnectorTool("crowdstrike", "search_detections",
                     "Search CrowdStrike Falcon for threat alerts (uses Alerts API v2)",
                     [ToolParameter("filters", "object", "Alert filters (severity, status, etc.)", False)],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
        ConnectorTool("crowdstrike", "get_host_info",
                     "Get detailed information about a host from CrowdStrike",
                     [ToolParameter("host_id", "string", "CrowdStrike host ID", True)],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
        ConnectorTool("crowdstrike", "contain_host",
                     "Isolate/contain a host using CrowdStrike (DANGEROUS - requires approval)",
                     [ToolParameter("host_id", "string", "Host ID to contain", True)],
                     ToolCategory.SECURITY, ToolSafety.DANGEROUS),
        ConnectorTool("crowdstrike", "lift_containment",
                     "Remove network containment from a CrowdStrike host",
                     [ToolParameter("host_id", "string", "Host ID to release", True)],
                     ToolCategory.SECURITY, ToolSafety.DANGEROUS),
        ConnectorTool("crowdstrike", "run_rtr_command",
                     "Run a real-time response command on a CrowdStrike host",
                     [ToolParameter("host_id", "string", "Host ID", True),
                      ToolParameter("command", "string", "Command to run", True)],
                     ToolCategory.SECURITY, ToolSafety.DANGEROUS),
    ]
    for tool in cs_tools:
        registry.register(tool)
        count += 1

    # MISP Tools
    misp_tools = [
        ConnectorTool("misp", "search_iocs",
                     "Search MISP for indicators of compromise",
                     [ToolParameter("value", "string", "IOC value to search", True)],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
        ConnectorTool("misp", "get_events",
                     "Get recent threat events from MISP",
                     [ToolParameter("limit", "number", "Max events", False, default=50)],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
        ConnectorTool("misp", "get_event",
                     "Get detailed information about a MISP event",
                     [ToolParameter("event_id", "string", "MISP event ID", True)],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
        ConnectorTool("misp", "create_event",
                     "Create a new threat event in MISP",
                     [ToolParameter("title", "string", "Event title", True),
                      ToolParameter("description", "string", "Event description", True)],
                     ToolCategory.SECURITY, ToolSafety.MODERATE),
        ConnectorTool("misp", "add_attribute",
                     "Add an indicator attribute to a MISP event",
                     [ToolParameter("event_id", "string", "Event ID", True),
                      ToolParameter("attribute_type", "string", "Attribute type (ip-dst, domain, hash, etc.)", True),
                      ToolParameter("value", "string", "Attribute value", True)],
                     ToolCategory.SECURITY, ToolSafety.MODERATE),
        ConnectorTool("misp", "enrich_indicators",
                     "Enrich threat indicators using MISP threat intelligence",
                     [ToolParameter("indicators", "array", "List of indicators to enrich", True)],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
    ]
    for tool in misp_tools:
        registry.register(tool)
        count += 1

    # REST API - IMPLEMENTED
    rest_tools = [
        ConnectorTool("restapi", "fetch_alerts",
                     "Fetch security alerts from custom REST API",
                     [ToolParameter("filters", "object", "Alert filters (severity, status, source, dates)", False)],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
        ConnectorTool("restapi", "create_alert",
                     "Create a new alert in the REST API system",
                     [ToolParameter("alert", "object", "Alert data", True)],
                     ToolCategory.SECURITY, ToolSafety.MODERATE),
    ]
    for tool in rest_tools:
        registry.register(tool)
        count += 1

    # Splunk - IMPLEMENTED
    splunk_tools = [
        ConnectorTool("splunk", "search",
                     "Execute a Splunk search query (SPL)",
                     [ToolParameter("query", "string", "Splunk search query", True),
                      ToolParameter("earliest_time", "string", "Time range start (e.g., '-24h')", False, default="-24h"),
                      ToolParameter("latest_time", "string", "Time range end (e.g., 'now')", False, default="now")],
                     ToolCategory.MONITORING, ToolSafety.SAFE),
    ]
    for tool in splunk_tools:
        registry.register(tool)
        count += 1

    # Elasticsearch - IMPLEMENTED
    elastic_tools = [
        ConnectorTool("elastic", "search",
                     "Execute an Elasticsearch search query",
                     [ToolParameter("index", "string", "Index name to search", True),
                      ToolParameter("query", "object", "Elasticsearch query DSL", True)],
                     ToolCategory.MONITORING, ToolSafety.SAFE),
    ]
    for tool in elastic_tools:
        registry.register(tool)
        count += 1

    # GitHub - IMPLEMENTED
    github_tools = [
        ConnectorTool("github", "get_vulnerabilities",
                     "Get Dependabot vulnerability alerts for a repository",
                     [ToolParameter("repo", "string", "Repository full name (owner/repo)", True)],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
        ConnectorTool("github", "get_code_scanning_alerts",
                     "Get code scanning alerts for a repository",
                     [ToolParameter("repo", "string", "Repository full name (owner/repo)", True)],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
        ConnectorTool("github", "get_secret_scanning_alerts",
                     "Get secret scanning alerts for a repository",
                     [ToolParameter("repo", "string", "Repository full name (owner/repo)", True)],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
        ConnectorTool("github", "list_repositories",
                     "List repositories for user or organization",
                     [ToolParameter("org", "string", "Organization name (optional)", False)],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
        ConnectorTool("github", "get_repository_security_summary",
                     "Get comprehensive security summary for a repository",
                     [ToolParameter("repo", "string", "Repository full name (owner/repo)", True)],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
    ]
    for tool in github_tools:
        registry.register(tool)
        count += 1

    # Snyk - IMPLEMENTED
    snyk_tools = [
        ConnectorTool("snyk", "get_organizations",
                     "Get all Snyk organizations",
                     [],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
        ConnectorTool("snyk", "get_projects",
                     "Get all projects for an organization",
                     [ToolParameter("org_id", "string", "Organization ID (optional)", False)],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
        ConnectorTool("snyk", "get_project_issues",
                     "Get vulnerabilities and license issues for a project",
                     [ToolParameter("org_id", "string", "Organization ID", True),
                      ToolParameter("project_id", "string", "Project ID", True)],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
        ConnectorTool("snyk", "test_package",
                     "Test a package for vulnerabilities",
                     [ToolParameter("package_manager", "string", "Package manager (npm, maven, pip, etc.)", True),
                      ToolParameter("package_file", "string", "Package file contents", True)],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
        ConnectorTool("snyk", "get_all_vulnerabilities",
                     "Get all vulnerabilities across all projects",
                     [ToolParameter("org_id", "string", "Organization ID (optional)", False)],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
    ]
    for tool in snyk_tools:
        registry.register(tool)
        count += 1

    # SonarQube - IMPLEMENTED
    sonarqube_tools = [
        ConnectorTool("sonarqube", "get_projects",
                     "Get all SonarQube projects",
                     [],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
        ConnectorTool("sonarqube", "get_issues",
                     "Get issues (bugs, vulnerabilities, code smells)",
                     [ToolParameter("project_key", "string", "Project key (optional)", False),
                      ToolParameter("severities", "array", "Filter by severities (optional)", False)],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
        ConnectorTool("sonarqube", "get_hotspots",
                     "Get security hotspots",
                     [ToolParameter("project_key", "string", "Project key (optional)", False)],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
        ConnectorTool("sonarqube", "get_measures",
                     "Get quality metrics for a project",
                     [ToolParameter("project_key", "string", "Project key", True),
                      ToolParameter("metrics", "array", "List of metric keys", True)],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
        ConnectorTool("sonarqube", "get_project_security_summary",
                     "Get comprehensive security summary for a project",
                     [ToolParameter("project_key", "string", "Project key", True)],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
    ]
    for tool in sonarqube_tools:
        registry.register(tool)
        count += 1

    # QRadar - SIEM
    qradar_tools = [
        ConnectorTool("qradar", "get_offenses",
                     "Get security offenses from IBM QRadar SIEM",
                     [ToolParameter("filters", "object", "Offense filters (status, severity, etc.)", False)],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
        ConnectorTool("qradar", "search_aql",
                     "Execute AQL query on QRadar for security events",
                     [ToolParameter("query", "string", "AQL query string", True)],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
        ConnectorTool("qradar", "fetch_alerts",
                     "Fetch security alerts from QRadar",
                     [ToolParameter("filters", "object", "Alert filters", False)],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
        ConnectorTool("qradar", "fetch_metrics",
                     "Get security metrics and statistics from QRadar",
                     [ToolParameter("time_range", "object", "Time range for metrics", False)],
                     ToolCategory.MONITORING, ToolSafety.SAFE),
    ]
    for tool in qradar_tools:
        registry.register(tool)
        count += 1

    # ArcSight - SIEM
    arcsight_tools = [
        ConnectorTool("arcsight", "get_active_channels",
                     "Get active security channels from ArcSight ESM",
                     [],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
        ConnectorTool("arcsight", "get_cases",
                     "Get security cases from ArcSight",
                     [ToolParameter("filters", "object", "Case filters", False)],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
        ConnectorTool("arcsight", "fetch_alerts",
                     "Fetch security alerts from ArcSight",
                     [ToolParameter("filters", "object", "Alert filters", False)],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
        ConnectorTool("arcsight", "fetch_investigations",
                     "Fetch security investigations from ArcSight",
                     [ToolParameter("filters", "object", "Investigation filters", False)],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
    ]
    for tool in arcsight_tools:
        registry.register(tool)
        count += 1

    # LogRhythm - SIEM
    logrhythm_tools = [
        ConnectorTool("logrhythm", "get_alarms",
                     "Get security alarms from LogRhythm SIEM",
                     [ToolParameter("status", "string", "Alarm status filter", False)],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
        ConnectorTool("logrhythm", "get_cases",
                     "Get security cases from LogRhythm",
                     [ToolParameter("status", "string", "Case status filter", False)],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
        ConnectorTool("logrhythm", "search_logs",
                     "Search logs in LogRhythm",
                     [ToolParameter("query", "string", "Log search query", True),
                      ToolParameter("max_results", "number", "Maximum results", False, default=100)],
                     ToolCategory.MONITORING, ToolSafety.SAFE),
        ConnectorTool("logrhythm", "fetch_alerts",
                     "Fetch security alerts from LogRhythm",
                     [ToolParameter("filters", "object", "Alert filters", False)],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
    ]
    for tool in logrhythm_tools:
        registry.register(tool)
        count += 1

    # Shodan - Threat Intelligence
    shodan_tools = [
        ConnectorTool("shodan", "search_hosts",
                     "Search for Internet-connected devices and services on Shodan",
                     [ToolParameter("query", "string", "Search query", True),
                      ToolParameter("limit", "number", "Max results", False, default=100)],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
        ConnectorTool("shodan", "get_host_info",
                     "Get detailed information about an IP address from Shodan",
                     [ToolParameter("ip", "string", "IP address", True)],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
        ConnectorTool("shodan", "dns_lookup",
                     "Perform DNS lookup for a domain using Shodan",
                     [ToolParameter("domain", "string", "Domain name", True)],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
        ConnectorTool("shodan", "search_exploits",
                     "Search Shodan's exploit database",
                     [ToolParameter("query", "string", "Exploit search query", True)],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
    ]
    for tool in shodan_tools:
        registry.register(tool)
        count += 1

    # AlienVault OTX - Threat Intelligence
    alienvault_tools = [
        ConnectorTool("alienvaultotx", "get_subscribed_pulses",
                     "Get threat pulses you're subscribed to in AlienVault OTX",
                     [ToolParameter("limit", "number", "Max pulses", False, default=50)],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
        ConnectorTool("alienvaultotx", "search_pulses",
                     "Search threat intelligence pulses in AlienVault OTX",
                     [ToolParameter("query", "string", "Search query", True)],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
        ConnectorTool("alienvaultotx", "lookup_indicator",
                     "Lookup threat indicator (IP, domain, hash) in AlienVault OTX",
                     [ToolParameter("indicator", "string", "Indicator value", True),
                      ToolParameter("indicator_type", "string", "Type (IPv4, domain, FileHash-SHA256, etc.)", True)],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
    ]
    for tool in alienvault_tools:
        registry.register(tool)
        count += 1

    # ThreatConnect - Threat Intelligence
    threatconnect_tools = [
        ConnectorTool("threatconnect", "get_indicators",
                     "Get threat indicators from ThreatConnect",
                     [ToolParameter("indicator_type", "string", "Type (Address, Host, EmailAddress, File, URL)", False),
                      ToolParameter("limit", "number", "Max indicators", False, default=100)],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
    ]
    for tool in threatconnect_tools:
        registry.register(tool)
        count += 1

    # Recorded Future - Threat Intelligence
    recordedfuture_tools = [
        ConnectorTool("recordedfuture", "search_threat_actors",
                     "Search for threat actors in Recorded Future",
                     [ToolParameter("query", "string", "Threat actor search query", True)],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
    ]
    for tool in recordedfuture_tools:
        registry.register(tool)
        count += 1

    # TheHive - SOAR
    thehive_tools = [
        ConnectorTool("thehive", "get_cases",
                     "Get security cases from TheHive incident response platform",
                     [ToolParameter("filters", "object", "Case filters", False)],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
        ConnectorTool("thehive", "create_case",
                     "Create a new security case in TheHive",
                     [ToolParameter("case_data", "object", "Case details (title, description, severity)", True)],
                     ToolCategory.SECURITY, ToolSafety.MODERATE),
        ConnectorTool("thehive", "fetch_alerts",
                     "Fetch security alerts from TheHive",
                     [ToolParameter("filters", "object", "Alert filters", False)],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
        ConnectorTool("thehive", "create_alert",
                     "Create a new alert in TheHive",
                     [ToolParameter("alert", "object", "Alert data", True)],
                     ToolCategory.SECURITY, ToolSafety.MODERATE),
        ConnectorTool("thehive", "update_alert",
                     "Update an existing alert in TheHive",
                     [ToolParameter("alert_id", "string", "Alert ID", True),
                      ToolParameter("alert", "object", "Updated alert data", True)],
                     ToolCategory.SECURITY, ToolSafety.MODERATE),
        ConnectorTool("thehive", "fetch_investigations",
                     "Fetch security investigations from TheHive",
                     [ToolParameter("filters", "object", "Investigation filters", False)],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
    ]
    for tool in thehive_tools:
        registry.register(tool)
        count += 1

    # Shuffle - SOAR
    shuffle_tools = [
        ConnectorTool("shuffle", "get_workflows",
                     "Get automation workflows from Shuffle SOAR",
                     [],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
        ConnectorTool("shuffle", "execute_workflow",
                     "Execute a Shuffle automation workflow",
                     [ToolParameter("workflow_id", "string", "Workflow ID", True),
                      ToolParameter("data", "object", "Input data for workflow", False)],
                     ToolCategory.SECURITY, ToolSafety.MODERATE),
    ]
    for tool in shuffle_tools:
        registry.register(tool)
        count += 1

    # Qualys - Vulnerability Management
    qualys_tools = [
        ConnectorTool("qualys", "get_host_list",
                     "Get host inventory from Qualys vulnerability scanner",
                     [],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
    ]
    for tool in qualys_tools:
        registry.register(tool)
        count += 1

    # AWS Security Hub - Cloud Security
    aws_securityhub_tools = [
        ConnectorTool("awssecurityhub", "get_findings",
                     "Get security findings from AWS Security Hub",
                     [ToolParameter("filters", "object", "Finding filters", False)],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
        ConnectorTool("awssecurityhub", "fetch_alerts",
                     "Fetch security alerts from AWS Security Hub",
                     [ToolParameter("filters", "object", "Alert filters", False)],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
        ConnectorTool("awssecurityhub", "create_alert",
                     "Import a security finding into AWS Security Hub",
                     [ToolParameter("alert", "object", "Alert data", True)],
                     ToolCategory.SECURITY, ToolSafety.MODERATE),
        ConnectorTool("awssecurityhub", "fetch_metrics",
                     "Get security metrics from AWS Security Hub",
                     [ToolParameter("time_range", "object", "Time range", False)],
                     ToolCategory.MONITORING, ToolSafety.SAFE),
    ]
    for tool in aws_securityhub_tools:
        registry.register(tool)
        count += 1

    # Azure Security Center - Cloud Security
    azure_securitycenter_tools = [
        ConnectorTool("azuresecuritycenter", "get_alerts",
                     "Get security alerts from Azure Security Center / Microsoft Defender",
                     [ToolParameter("filters", "object", "Alert filters", False)],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
        ConnectorTool("azuresecuritycenter", "fetch_alerts",
                     "Fetch security alerts from Azure Security Center",
                     [ToolParameter("filters", "object", "Alert filters", False)],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
        ConnectorTool("azuresecuritycenter", "get_recommendations",
                     "Get security recommendations from Azure Security Center",
                     [],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
        ConnectorTool("azuresecuritycenter", "get_secure_score",
                     "Get Azure Secure Score",
                     [],
                     ToolCategory.MONITORING, ToolSafety.SAFE),
        ConnectorTool("azuresecuritycenter", "fetch_metrics",
                     "Get security metrics from Azure Security Center",
                     [ToolParameter("time_range", "object", "Time range", False)],
                     ToolCategory.MONITORING, ToolSafety.SAFE),
    ]
    for tool in azure_securitycenter_tools:
        registry.register(tool)
        count += 1

    # PagerDuty - Incident Response
    pagerduty_tools = [
        ConnectorTool("pagerduty", "get_incidents",
                     "Get security incidents from PagerDuty",
                     [ToolParameter("filters", "object", "Incident filters (status, urgency, etc.)", False)],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
        ConnectorTool("pagerduty", "create_alert",
                     "Create a new incident in PagerDuty",
                     [ToolParameter("alert", "object", "Incident data (title, description, service_id, urgency)", True)],
                     ToolCategory.SECURITY, ToolSafety.MODERATE),
        ConnectorTool("pagerduty", "update_alert",
                     "Update a PagerDuty incident",
                     [ToolParameter("alert_id", "string", "Incident ID", True),
                      ToolParameter("alert", "object", "Updated incident data", True)],
                     ToolCategory.SECURITY, ToolSafety.MODERATE),
        ConnectorTool("pagerduty", "fetch_alerts",
                     "Fetch security incidents from PagerDuty",
                     [ToolParameter("filters", "object", "Incident filters", False)],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
        ConnectorTool("pagerduty", "get_services",
                     "Get PagerDuty services",
                     [],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
        ConnectorTool("pagerduty", "fetch_users",
                     "Get PagerDuty users for on-call management",
                     [],
                     ToolCategory.SECURITY, ToolSafety.SAFE),
    ]
    for tool in pagerduty_tools:
        registry.register(tool)
        count += 1

    logger.info(f"✅ Registered {count} AgentSO connector tools (VirusTotal, CrowdStrike, MISP, REST API, Splunk, Elasticsearch, GitHub, Snyk, SonarQube, QRadar, ArcSight, LogRhythm, Shodan, AlienVault OTX, ThreatConnect, Recorded Future, TheHive, Shuffle, Qualys, AWS Security Hub, Azure Security Center, PagerDuty)")
    return count
