#!/usr/bin/env python3
"""
Monitoring & Metrics Tools
===========================
System monitoring and performance metrics

Tools:
- get_cpu_usage: Current CPU usage
- get_memory_usage: Current memory usage
- get_disk_usage: Disk space usage
- get_network_stats: Network traffic stats
- check_mysql_health: MySQL connection pool and slow queries
- check_postgresql_health: PostgreSQL connection pool and query statistics
- get_service_status: Check if service is running
- parse_logs: Parse log files for errors
- query_metrics: Query stored metrics
- create_alert: Create system alert
- get_performance_profile: Profile code execution

Author: Torin AI Team
"""

import logging
import psutil
import uuid
import json
import statistics
from typing import Any, Dict, List, Optional
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

from .tool_registry import Tool, ToolParameter, ToolResult, ToolCategory, ToolSafety
from .capabilities import Capability, ToolCapabilityProfile, CapabilityMetadata, RiskLevel


logger = logging.getLogger(__name__)


class GetCPUUsageTool(Tool):
    """Get CPU usage"""

    def __init__(self):
        super().__init__()
        self.name = "get_cpu_usage"
        self.description = "Get current CPU usage percentage"
        self.category = ToolCategory.MONITORING
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="interval",
                type="number",
                description="Measurement interval in seconds",
                required=False,
                default=1,
                min_value=0.1,
                max_value=10
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="get_cpu_usage",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.ANALYZE_PERFORMANCE,
                    description="Monitor CPU usage"
                )
            ]
        )

    async def execute(self, interval: float = 1) -> ToolResult:
        try:
            cpu_percent = psutil.cpu_percent(interval=interval)
            cpu_count = psutil.cpu_count()
            per_cpu = psutil.cpu_percent(interval=interval, percpu=True)

            return ToolResult(
                success=True,
                output={
                    'cpu_percent': cpu_percent,
                    'cpu_count': cpu_count,
                    'per_cpu': per_cpu,
                    'load_average': psutil.getloadavg() if hasattr(psutil, 'getloadavg') else None
                }
            )
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class GetMemoryUsageTool(Tool):
    """Get memory usage"""

    def __init__(self):
        super().__init__()
        self.name = "get_memory_usage"
        self.description = "Get current memory usage statistics"
        self.category = ToolCategory.MONITORING
        self.safety_level = ToolSafety.SAFE
        self.parameters = []

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="get_memory_usage",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.ANALYZE_PERFORMANCE,
                    description="Monitor memory usage"
                )
            ]
        )

    async def execute(self) -> ToolResult:
        try:
            mem = psutil.virtual_memory()
            swap = psutil.swap_memory()

            return ToolResult(
                success=True,
                output={
                    'total_gb': round(mem.total / (1024**3), 2),
                    'available_gb': round(mem.available / (1024**3), 2),
                    'used_gb': round(mem.used / (1024**3), 2),
                    'percent': mem.percent,
                    'swap_total_gb': round(swap.total / (1024**3), 2),
                    'swap_used_gb': round(swap.used / (1024**3), 2),
                    'swap_percent': swap.percent
                }
            )
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class GetDiskUsageTool(Tool):
    """Get disk usage"""

    def __init__(self):
        super().__init__()
        self.name = "get_disk_usage"
        self.description = "Get disk space usage for filesystem"
        self.category = ToolCategory.MONITORING
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="path",
                type="string",
                description="Path to check (defaults to root)",
                required=False,
                default="/"
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="get_disk_usage",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.ANALYZE_PERFORMANCE,
                    description="Monitor disk usage"
                )
            ]
        )

    async def execute(self, path: str = "/") -> ToolResult:
        try:
            usage = psutil.disk_usage(path)

            return ToolResult(
                success=True,
                output={
                    'path': path,
                    'total_gb': round(usage.total / (1024**3), 2),
                    'used_gb': round(usage.used / (1024**3), 2),
                    'free_gb': round(usage.free / (1024**3), 2),
                    'percent': usage.percent
                }
            )
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class GetNetworkStatsTool(Tool):
    """Get network statistics"""

    def __init__(self):
        super().__init__()
        self.name = "get_network_stats"
        self.description = "Get network traffic statistics"
        self.category = ToolCategory.MONITORING
        self.safety_level = ToolSafety.SAFE
        self.parameters = []

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="get_network_stats",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.ANALYZE_PERFORMANCE,
                    description="Monitor network statistics"
                )
            ]
        )

    async def execute(self) -> ToolResult:
        try:
            net_io = psutil.net_io_counters()

            return ToolResult(
                success=True,
                output={
                    'bytes_sent_mb': round(net_io.bytes_sent / (1024**2), 2),
                    'bytes_recv_mb': round(net_io.bytes_recv / (1024**2), 2),
                    'packets_sent': net_io.packets_sent,
                    'packets_recv': net_io.packets_recv,
                    'errors_in': net_io.errin,
                    'errors_out': net_io.errout,
                    'drops_in': net_io.dropin,
                    'drops_out': net_io.dropout
                }
            )
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class CheckMySQLHealthTool(Tool):
    """Check MySQL health"""

    def __init__(self):
        super().__init__()
        self.name = "check_mysql_health"
        self.description = "Check MySQL connection pool, active connections, and slow queries"
        self.category = ToolCategory.DATABASE
        self.safety_level = ToolSafety.SAFE
        self.parameters = []

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="check_mysql_health",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.CHECK_CONNECTIVITY,
                    description="Check MySQL database health"
                ),
                CapabilityMetadata(
                    capability=Capability.MONITOR_HEALTH,
                    description="Monitor MySQL database health",
                    input_types=[],
                    output_types=["health_status"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=9
                )
            ]
        )

    async def execute(self) -> ToolResult:
        try:
            from core.database import get_database_manager
            db = get_database_manager()

            conn_stats = await db.execute_query("""
                SELECT
                    COUNT(*) as total_connections,
                    SUM(CASE WHEN state = 'active' THEN 1 ELSE 0 END) as active_connections,
                    SUM(CASE WHEN state = 'idle' THEN 1 ELSE 0 END) as idle_connections
                FROM pg_stat_activity
                WHERE datname = current_database()
            """, fetch_one=True) or {}

            slow_count = await db.execute_query("""
                SELECT COUNT(*) as slow_queries
                FROM pg_stat_activity
                WHERE state = 'active' AND query_start < NOW() - INTERVAL '1 second'
            """, fetch_one=True) or {'slow_queries': 0}

            return ToolResult(
                success=True,
                output={
                    'total_connections': conn_stats.get('total_connections', 0),
                    'active_connections': conn_stats.get('active_connections', 0),
                    'idle_connections': conn_stats.get('idle_connections', 0),
                    'slow_queries': slow_count.get('slow_queries', 0),
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class CheckPostgreSQLHealthTool(Tool):
    """Check PostgreSQL health"""

    def __init__(self):
        super().__init__()
        self.name = "check_postgresql_health"
        self.description = "Check PostgreSQL connection pool, active connections, and query statistics"
        self.category = ToolCategory.DATABASE
        self.safety_level = ToolSafety.SAFE
        self.parameters = []

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="check_postgresql_health",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.CHECK_CONNECTIVITY,
                    description="Check PostgreSQL database health"
                ),
                CapabilityMetadata(
                    capability=Capability.MONITOR_HEALTH,
                    description="Monitor PostgreSQL database health",
                    input_types=[],
                    output_types=["health_status"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=9
                )
            ]
        )

    async def execute(self) -> ToolResult:
        try:
            from core.database import TorinUnifiedDatabase

            db = TorinUnifiedDatabase()
            await db.initialize()

            # Get connection stats
            stats_query = """
            SELECT
                COUNT(*) as total_connections,
                SUM(CASE WHEN state = 'active' THEN 1 ELSE 0 END) as active_connections,
                SUM(CASE WHEN state = 'idle' THEN 1 ELSE 0 END) as idle_connections,
                SUM(CASE WHEN state = 'idle in transaction' THEN 1 ELSE 0 END) as idle_in_transaction
            FROM pg_stat_activity
            WHERE datname = current_database()
            """

            conn_stats = await db.execute_query(stats_query, fetch_one=True)

            # Get database size
            size_query = "SELECT pg_size_pretty(pg_database_size(current_database())) as db_size"
            size_result = await db.execute_query(size_query, fetch_one=True)

            # Get slow query stats (queries > 1 second)
            slow_query = """
            SELECT COUNT(*) as slow_queries
            FROM pg_stat_statements
            WHERE mean_exec_time > 1000
            """
            slow_result = await db.execute_query(slow_query, fetch_one=True) or {'slow_queries': 0}

            # Get table counts for key schemas
            table_counts = {}
            for schema in ['unified', 'memory_hot', 'memory_cold']:
                count_query = f"""
                SELECT COUNT(*) as table_count
                FROM information_schema.tables
                WHERE table_schema = '{schema}'
                """
                result = await db.execute_query(count_query, fetch_one=True)
                table_counts[schema] = result['table_count'] if result else 0

            await db.close()

            return ToolResult(
                success=True,
                output={
                    'pool_size': db.pool_max_size if hasattr(db, 'pool_max_size') else 'N/A',
                    'total_connections': conn_stats['total_connections'],
                    'active_connections': conn_stats['active_connections'],
                    'idle_connections': conn_stats['idle_connections'],
                    'idle_in_transaction': conn_stats['idle_in_transaction'],
                    'database_size': size_result['db_size'],
                    'slow_queries': slow_result.get('slow_queries', 0),
                    'schemas': table_counts
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class GetServiceStatusTool(Tool):
    """Check service status"""

    def __init__(self):
        super().__init__()
        self.name = "get_service_status"
        self.description = "Check if a system service is running"
        self.category = ToolCategory.MONITORING
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="service_name",
                type="string",
                description="Service name to check",
                required=True
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="get_service_status",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.MANAGE_PROCESS,
                    description="Get service status information"
                ),
                CapabilityMetadata(
                    capability=Capability.MONITOR_HEALTH,
                    description="Monitor health of system services",
                    input_types=["service_name"],
                    output_types=["status"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=9
                )
            ]
        )

    async def execute(self, service_name: str) -> ToolResult:
        try:
            import subprocess
            import platform

            system = platform.system()

            if system == "Darwin":  # macOS
                cmd = ["launchctl", "list", service_name]
            elif system == "Linux":
                cmd = ["systemctl", "is-active", service_name]
            else:
                return ToolResult(success=False, output=None, error=f"Unsupported system: {system}")

            result = subprocess.run(cmd, capture_output=True, text=True)

            return ToolResult(
                success=True,
                output={
                    'service': service_name,
                    'running': result.returncode == 0,
                    'status': result.stdout.strip()
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class ParseLogsTool(Tool):
    """Parse log files for errors"""

    def __init__(self):
        super().__init__()
        self.name = "parse_logs"
        self.description = "Parse log files and find errors, warnings, or specific patterns"
        self.category = ToolCategory.MONITORING
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="log_file",
                type="string",
                description="Path to log file",
                required=True
            ),
            ToolParameter(
                name="pattern",
                type="string",
                description="Pattern to search for (e.g., 'ERROR', 'WARNING')",
                required=False,
                default="ERROR"
            ),
            ToolParameter(
                name="last_n_lines",
                type="number",
                description="Only check last N lines",
                required=False,
                default=1000,
                min_value=10,
                max_value=10000
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="parse_logs",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.READ_DATA,
                    description="Parse and analyze log files"
                )
            ]
        )

    async def execute(self, log_file: str, pattern: str = "ERROR", last_n_lines: int = 1000) -> ToolResult:
        try:
            log_path = Path(log_file).expanduser().resolve()

            if not log_path.exists():
                return ToolResult(success=False, output=None, error=f"Log file not found: {log_path}")

            # Read last N lines
            with open(log_path, 'r') as f:
                lines = f.readlines()[-last_n_lines:]

            # Find matching lines
            matches = []
            for i, line in enumerate(lines):
                if pattern in line:
                    matches.append({
                        'line_number': len(lines) - last_n_lines + i + 1,
                        'content': line.strip()
                    })

            return ToolResult(
                success=True,
                output={
                    'log_file': str(log_path),
                    'pattern': pattern,
                    'total_lines_checked': len(lines),
                    'matches_found': len(matches),
                    'matches': matches[:50]  # Limit to 50 matches
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class QueryMetricsTool(Tool):
    """Query stored metrics"""

    def __init__(self):
        super().__init__()
        self.name = "query_metrics"
        self.description = "Query stored system metrics from database"
        self.category = ToolCategory.DATABASE
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="metric_type",
                type="string",
                description="Type of metric to query",
                required=True,
                enum=["health", "performance", "security", "api", "llm"]
            ),
            ToolParameter(
                name="hours_ago",
                type="number",
                description="How many hours of data to retrieve",
                required=False,
                default=24,
                min_value=1,
                max_value=168
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="query_metrics",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.READ_DATA,
                    description="Query system metrics"
                )
            ]
        )

    async def execute(self, metric_type: str, hours_ago: int = 24) -> ToolResult:
        try:
            from core.database import get_database_manager
            db = get_database_manager()
            cutoff_time = datetime.now() - timedelta(hours=hours_ago)

            table_map = {
                'health': 'health_metrics',
                'performance': 'performance_logs',
                'security': 'security_logs',
                'api': 'api_logs',
                'llm': 'llm_logs'
            }

            table = table_map.get(metric_type)
            if not table:
                return ToolResult(success=False, output=None, error=f"Unknown metric type: {metric_type}")

            results = await db.execute_query(
                f"SELECT * FROM {table} WHERE timestamp >= $1 ORDER BY timestamp DESC LIMIT 100",
                (cutoff_time,),
                fetch_all=True
            ) or []

            return ToolResult(
                success=True,
                output={
                    'metric_type': metric_type,
                    'hours': hours_ago,
                    'count': len(results),
                    'metrics': results
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class CreateAlertTool(Tool):
    """Create system alert"""

    def __init__(self):
        super().__init__()
        self.name = "create_alert"
        self.description = "Create a system alert in the database"
        self.category = ToolCategory.DATABASE
        self.safety_level = ToolSafety.MODERATE
        self.parameters = [
            ToolParameter(
                name="alert_type",
                type="string",
                description="Type of alert",
                required=True,
                enum=["health", "security", "performance", "error"]
            ),
            ToolParameter(
                name="message",
                type="string",
                description="Alert message",
                required=True
            ),
            ToolParameter(
                name="severity",
                type="string",
                description="Alert severity",
                required=False,
                default="medium",
                enum=["low", "medium", "high", "critical"]
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="create_alert",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.NOTIFY,
                    description="Create monitoring alerts"
                ),
                CapabilityMetadata(
                    capability=Capability.CREATE_ALERT,
                    description="Create monitoring alerts for threshold violations",
                    input_types=["alert_config"],
                    output_types=["alert_id"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=9
                )
            ]
        )

    async def execute(self, alert_type: str, message: str, severity: str = "medium") -> ToolResult:
        try:
            from core.database import get_database_manager

            db = get_database_manager()

            await db.execute_query(
                """
                INSERT INTO system_alerts (source, message, severity, timestamp)
                VALUES ($1, $2, $3, $4)
                """,
                params=(alert_type, message, severity, datetime.now()),
                commit=True,
            )

            return ToolResult(
                success=True,
                output={
                    'alert_created': True,
                    'type': alert_type,
                    'severity': severity,
                },
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class GetPerformanceProfileTool(Tool):
    """Profile code execution"""

    def __init__(self):
        super().__init__()
        self.name = "get_performance_profile"
        self.description = "Get performance profiling data for TorinAI processes"
        self.category = ToolCategory.MONITORING
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="process_name",
                type="string",
                description="Process name to profile (optional)",
                required=False
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="get_performance_profile",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.ANALYZE_PERFORMANCE,
                    description="Get performance profiles"
                )
            ]
        )

    async def execute(self, process_name: str = None) -> ToolResult:
        try:
            import os

            # Get current process info
            current_proc = psutil.Process(os.getpid())

            with current_proc.oneshot():
                info = {
                    'pid': current_proc.pid,
                    'name': current_proc.name(),
                    'cpu_percent': current_proc.cpu_percent(interval=0.1),
                    'memory_mb': round(current_proc.memory_info().rss / (1024**2), 2),
                    'num_threads': current_proc.num_threads(),
                    'num_fds': current_proc.num_fds() if hasattr(current_proc, 'num_fds') else None,
                    'create_time': datetime.fromtimestamp(current_proc.create_time()).isoformat()
                }

            return ToolResult(success=True, output=info)

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class DistributedTracingTool(Tool):
    """Manage distributed tracing with trace IDs for end-to-end request tracking"""

    def __init__(self):
        super().__init__()
        self.name = "distributed_tracing"
        self.description = "Create, propagate, and query distributed trace IDs for end-to-end request tracking"
        self.category = ToolCategory.MONITORING
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="operation",
                type="string",
                description="Tracing operation",
                required=True,
                enum=["create_trace", "create_span", "end_span", "get_trace", "query_traces"]
            ),
            ToolParameter(
                name="trace_id",
                type="string",
                description="Trace ID (auto-generated if not provided)",
                required=False
            ),
            ToolParameter(
                name="span_id",
                type="string",
                description="Span ID (for end_span operation)",
                required=False
            ),
            ToolParameter(
                name="span_name",
                type="string",
                description="Span name/operation name",
                required=False
            ),
            ToolParameter(
                name="parent_span_id",
                type="string",
                description="Parent span ID for nested spans",
                required=False
            ),
            ToolParameter(
                name="tags",
                type="object",
                description="Tags/metadata for the span",
                required=False
            ),
            ToolParameter(
                name="service_name",
                type="string",
                description="Service name",
                required=False
            ),
            ToolParameter(
                name="query_filter",
                type="object",
                description="Filter for querying traces",
                required=False
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="distributed_tracing",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.ANALYZE_PERFORMANCE,
                    description="Perform distributed tracing"
                )
            ]
        )

        # In-memory trace storage (in production, use proper tracing backend)
        self.traces: Dict[str, Dict] = {}
        self.spans: Dict[str, Dict] = {}

    async def execute(self, operation: str, trace_id: str = None, span_id: str = None,
                     span_name: str = None, parent_span_id: str = None, tags: Dict = None,
                     service_name: str = None, query_filter: Dict = None) -> ToolResult:
        try:
            if operation == "create_trace":
                # Create new trace
                new_trace_id = trace_id or str(uuid.uuid4())
                self.traces[new_trace_id] = {
                    "trace_id": new_trace_id,
                    "start_time": datetime.now().isoformat(),
                    "service_name": service_name or "unknown",
                    "spans": [],
                    "tags": tags or {}
                }

                return ToolResult(
                    success=True,
                    output={
                        "operation": "create_trace",
                        "trace_id": new_trace_id,
                        "created_at": self.traces[new_trace_id]["start_time"]
                    }
                )

            elif operation == "create_span":
                if not trace_id:
                    return ToolResult(success=False, output=None, error="trace_id required for create_span")
                if not span_name:
                    return ToolResult(success=False, output=None, error="span_name required for create_span")

                if trace_id not in self.traces:
                    return ToolResult(success=False, output=None, error=f"Trace {trace_id} not found")

                new_span_id = span_id or str(uuid.uuid4())
                span = {
                    "span_id": new_span_id,
                    "trace_id": trace_id,
                    "span_name": span_name,
                    "parent_span_id": parent_span_id,
                    "service_name": service_name or self.traces[trace_id]["service_name"],
                    "start_time": datetime.now().isoformat(),
                    "end_time": None,
                    "duration_ms": None,
                    "tags": tags or {},
                    "status": "in_progress"
                }

                self.spans[new_span_id] = span
                self.traces[trace_id]["spans"].append(new_span_id)

                return ToolResult(
                    success=True,
                    output={
                        "operation": "create_span",
                        "trace_id": trace_id,
                        "span_id": new_span_id,
                        "span_name": span_name,
                        "start_time": span["start_time"]
                    }
                )

            elif operation == "end_span":
                if not span_id:
                    return ToolResult(success=False, output=None, error="span_id required for end_span")

                if span_id not in self.spans:
                    return ToolResult(success=False, output=None, error=f"Span {span_id} not found")

                span = self.spans[span_id]
                end_time = datetime.now()
                start_time = datetime.fromisoformat(span["start_time"])
                duration_ms = (end_time - start_time).total_seconds() * 1000

                span["end_time"] = end_time.isoformat()
                span["duration_ms"] = round(duration_ms, 2)
                span["status"] = "completed"
                if tags:
                    span["tags"].update(tags)

                return ToolResult(
                    success=True,
                    output={
                        "operation": "end_span",
                        "span_id": span_id,
                        "duration_ms": span["duration_ms"],
                        "status": "completed"
                    }
                )

            elif operation == "get_trace":
                if not trace_id:
                    return ToolResult(success=False, output=None, error="trace_id required for get_trace")

                if trace_id not in self.traces:
                    return ToolResult(success=False, output=None, error=f"Trace {trace_id} not found")

                trace = self.traces[trace_id].copy()
                trace["spans"] = [self.spans[span_id].copy() for span_id in trace["spans"] if span_id in self.spans]

                # Calculate total duration
                completed_spans = [s for s in trace["spans"] if s.get("duration_ms")]
                if completed_spans:
                    trace["total_duration_ms"] = sum(s["duration_ms"] for s in completed_spans)

                return ToolResult(
                    success=True,
                    output={
                        "operation": "get_trace",
                        "trace": trace
                    }
                )

            elif operation == "query_traces":
                # Query traces with optional filtering
                matching_traces = []
                for tid, trace in self.traces.items():
                    if query_filter:
                        # Simple filtering
                        if "service_name" in query_filter and trace.get("service_name") != query_filter["service_name"]:
                            continue
                        if "min_duration_ms" in query_filter:
                            total_duration = sum(
                                self.spans.get(sid, {}).get("duration_ms", 0)
                                for sid in trace["spans"]
                            )
                            if total_duration < query_filter["min_duration_ms"]:
                                continue

                    matching_traces.append({
                        "trace_id": tid,
                        "service_name": trace.get("service_name"),
                        "start_time": trace.get("start_time"),
                        "span_count": len(trace["spans"])
                    })

                return ToolResult(
                    success=True,
                    output={
                        "operation": "query_traces",
                        "traces": matching_traces,
                        "count": len(matching_traces)
                    }
                )

            else:
                return ToolResult(success=False, output=None, error=f"Unknown operation: {operation}")

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class SLOSLIToolingTool(Tool):
    """Track SLO/SLI metrics and calculate error budgets"""

    def __init__(self):
        super().__init__()
        self.name = "slo_sli_tooling"
        self.description = "Track Service Level Objectives (SLOs) and Service Level Indicators (SLIs), calculate error budgets"
        self.category = ToolCategory.MONITORING
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="operation",
                type="string",
                description="SLO/SLI operation",
                required=True,
                enum=["define_slo", "record_sli", "get_slo_status", "calculate_error_budget", "list_slos"]
            ),
            ToolParameter(
                name="slo_name",
                type="string",
                description="SLO identifier",
                required=False
            ),
            ToolParameter(
                name="target_percentage",
                type="number",
                description="Target SLO percentage (e.g., 99.9)",
                required=False
            ),
            ToolParameter(
                name="window_days",
                type="integer",
                description="Rolling window in days",
                required=False,
                default=30
            ),
            ToolParameter(
                name="success",
                type="boolean",
                description="Whether the request/event was successful",
                required=False
            ),
            ToolParameter(
                name="latency_ms",
                type="number",
                description="Request latency in milliseconds",
                required=False
            ),
            ToolParameter(
                name="sli_type",
                type="string",
                description="SLI type",
                required=False,
                enum=["availability", "latency", "error_rate"]
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="slo_sli_tooling",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.ANALYZE_PERFORMANCE,
                    description="Monitor SLO/SLI metrics"
                )
            ]
        )

        # SLO definitions
        self.slos: Dict[str, Dict] = {}
        # SLI measurements
        self.sli_data: Dict[str, List] = defaultdict(list)

    async def execute(self, operation: str, slo_name: str = None, target_percentage: float = None,
                     window_days: int = 30, success: bool = None, latency_ms: float = None,
                     sli_type: str = None) -> ToolResult:
        try:
            if operation == "define_slo":
                if not slo_name or not target_percentage or not sli_type:
                    return ToolResult(
                        success=False,
                        output=None,
                        error="slo_name, target_percentage, and sli_type required for define_slo"
                    )

                self.slos[slo_name] = {
                    "slo_name": slo_name,
                    "target_percentage": target_percentage,
                    "sli_type": sli_type,
                    "window_days": window_days,
                    "created_at": datetime.now().isoformat()
                }

                return ToolResult(
                    success=True,
                    output={
                        "operation": "define_slo",
                        "slo_name": slo_name,
                        "target": f"{target_percentage}%",
                        "type": sli_type,
                        "window_days": window_days
                    }
                )

            elif operation == "record_sli":
                if not slo_name:
                    return ToolResult(success=False, output=None, error="slo_name required for record_sli")

                if slo_name not in self.slos:
                    return ToolResult(success=False, output=None, error=f"SLO {slo_name} not defined")

                slo = self.slos[slo_name]
                measurement = {
                    "timestamp": datetime.now().isoformat(),
                    "sli_type": slo["sli_type"]
                }

                if slo["sli_type"] == "availability":
                    if success is None:
                        return ToolResult(success=False, output=None, error="success required for availability SLI")
                    measurement["success"] = success

                elif slo["sli_type"] == "latency":
                    if latency_ms is None:
                        return ToolResult(success=False, output=None, error="latency_ms required for latency SLI")
                    measurement["latency_ms"] = latency_ms
                    # Consider latency SLI: latency < threshold is success
                    latency_threshold = slo.get("latency_threshold_ms", 1000)
                    measurement["success"] = latency_ms < latency_threshold

                elif slo["sli_type"] == "error_rate":
                    if success is None:
                        return ToolResult(success=False, output=None, error="success required for error_rate SLI")
                    measurement["success"] = success

                self.sli_data[slo_name].append(measurement)

                return ToolResult(
                    success=True,
                    output={
                        "operation": "record_sli",
                        "slo_name": slo_name,
                        "measurement": measurement
                    }
                )

            elif operation == "get_slo_status":
                if not slo_name:
                    return ToolResult(success=False, output=None, error="slo_name required for get_slo_status")

                if slo_name not in self.slos:
                    return ToolResult(success=False, output=None, error=f"SLO {slo_name} not defined")

                slo = self.slos[slo_name]
                measurements = self.sli_data[slo_name]

                # Filter to window
                cutoff = datetime.now() - timedelta(days=slo["window_days"])
                recent_measurements = [
                    m for m in measurements
                    if datetime.fromisoformat(m["timestamp"]) > cutoff
                ]

                if not recent_measurements:
                    return ToolResult(
                        success=True,
                        output={
                            "operation": "get_slo_status",
                            "slo_name": slo_name,
                            "status": "no_data",
                            "message": "No measurements in window"
                        }
                    )

                # Calculate actual SLI
                successful = sum(1 for m in recent_measurements if m.get("success", False))
                total = len(recent_measurements)
                actual_percentage = (successful / total) * 100

                # Determine status
                status = "meeting" if actual_percentage >= slo["target_percentage"] else "breaching"

                return ToolResult(
                    success=True,
                    output={
                        "operation": "get_slo_status",
                        "slo_name": slo_name,
                        "target": f"{slo['target_percentage']}%",
                        "actual": f"{actual_percentage:.2f}%",
                        "status": status,
                        "total_measurements": total,
                        "successful_measurements": successful,
                        "window_days": slo["window_days"]
                    }
                )

            elif operation == "calculate_error_budget":
                if not slo_name:
                    return ToolResult(success=False, output=None, error="slo_name required for calculate_error_budget")

                if slo_name not in self.slos:
                    return ToolResult(success=False, output=None, error=f"SLO {slo_name} not defined")

                slo = self.slos[slo_name]
                measurements = self.sli_data[slo_name]

                # Filter to window
                cutoff = datetime.now() - timedelta(days=slo["window_days"])
                recent_measurements = [
                    m for m in measurements
                    if datetime.fromisoformat(m["timestamp"]) > cutoff
                ]

                if not recent_measurements:
                    return ToolResult(
                        success=True,
                        output={
                            "operation": "calculate_error_budget",
                            "slo_name": slo_name,
                            "error_budget_remaining": "100.00%",
                            "message": "No measurements in window"
                        }
                    )

                # Calculate error budget
                total = len(recent_measurements)
                allowed_failures = total * (1 - slo["target_percentage"] / 100)
                actual_failures = sum(1 for m in recent_measurements if not m.get("success", False))
                error_budget_remaining = max(0, allowed_failures - actual_failures)
                error_budget_percentage = (error_budget_remaining / allowed_failures * 100) if allowed_failures > 0 else 100

                return ToolResult(
                    success=True,
                    output={
                        "operation": "calculate_error_budget",
                        "slo_name": slo_name,
                        "target_slo": f"{slo['target_percentage']}%",
                        "total_requests": total,
                        "allowed_failures": round(allowed_failures, 2),
                        "actual_failures": actual_failures,
                        "error_budget_remaining": round(error_budget_remaining, 2),
                        "error_budget_percentage": f"{error_budget_percentage:.2f}%",
                        "window_days": slo["window_days"]
                    }
                )

            elif operation == "list_slos":
                slos_list = [
                    {
                        "slo_name": name,
                        "target": f"{slo['target_percentage']}%",
                        "type": slo["sli_type"],
                        "window_days": slo["window_days"],
                        "measurement_count": len(self.sli_data[name])
                    }
                    for name, slo in self.slos.items()
                ]

                return ToolResult(
                    success=True,
                    output={
                        "operation": "list_slos",
                        "slos": slos_list,
                        "count": len(slos_list)
                    }
                )

            else:
                return ToolResult(success=False, output=None, error=f"Unknown operation: {operation}")

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class AnomalyDetectionTool(Tool):
    """Detect anomalies in operational metrics using statistical methods"""

    def __init__(self):
        super().__init__()
        self.name = "anomaly_detection"
        self.description = "Detect anomalies in operational metrics using statistical analysis (z-score, moving average)"
        self.category = ToolCategory.MONITORING
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="metric_name",
                type="string",
                description="Metric name to analyze",
                required=True
            ),
            ToolParameter(
                name="values",
                type="array",
                description="Array of metric values to analyze",
                required=False
            ),
            ToolParameter(
                name="value",
                type="number",
                description="Single value to check for anomaly",
                required=False
            ),
            ToolParameter(
                name="method",
                type="string",
                description="Detection method",
                required=False,
                default="z_score",
                enum=["z_score", "iqr", "moving_average"]
            ),
            ToolParameter(
                name="threshold",
                type="number",
                description="Threshold for anomaly detection (e.g., 3.0 for z-score)",
                required=False,
                default=3.0
            ),
            ToolParameter(
                name="window_size",
                type="integer",
                description="Window size for moving average method",
                required=False,
                default=10
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="anomaly_detection",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.DETECT_ANOMALY,
                    description="Detect system anomalies"
                ),
                CapabilityMetadata(
                    capability=Capability.ANALYZE_THREAT,
                    description="Analyze anomalies to detect security threats",
                    input_types=["time_series"],
                    output_types=["anomalies", "threat_score"],
                    latency="medium",
                    cost="medium",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                )
            ]
        )

        # Store historical data for each metric
        self.metric_history: Dict[str, List[float]] = defaultdict(list)

    async def execute(self, metric_name: str, values: List[float] = None, value: float = None,
                     method: str = "z_score", threshold: float = 3.0, window_size: int = 10) -> ToolResult:
        try:
            # Determine data to analyze
            if values:
                data = values
            elif value is not None:
                # Add to history and analyze
                self.metric_history[metric_name].append(value)
                data = self.metric_history[metric_name]
            else:
                return ToolResult(success=False, output=None, error="Either values or value must be provided")

            if len(data) < 3:
                return ToolResult(
                    success=True,
                    output={
                        "metric_name": metric_name,
                        "anomaly_detected": False,
                        "message": "Insufficient data for anomaly detection (need at least 3 points)"
                    }
                )

            anomalies = []

            if method == "z_score":
                # Z-score method
                mean = statistics.mean(data)
                stdev = statistics.stdev(data) if len(data) > 1 else 0

                if stdev == 0:
                    return ToolResult(
                        success=True,
                        output={
                            "metric_name": metric_name,
                            "method": "z_score",
                            "anomaly_detected": False,
                            "message": "No variance in data"
                        }
                    )

                for idx, val in enumerate(data):
                    z_score = abs((val - mean) / stdev)
                    if z_score > threshold:
                        anomalies.append({
                            "index": idx,
                            "value": val,
                            "z_score": round(z_score, 3),
                            "mean": round(mean, 3),
                            "stdev": round(stdev, 3)
                        })

                return ToolResult(
                    success=True,
                    output={
                        "metric_name": metric_name,
                        "method": "z_score",
                        "threshold": threshold,
                        "data_points": len(data),
                        "mean": round(mean, 3),
                        "stdev": round(stdev, 3),
                        "anomaly_detected": len(anomalies) > 0,
                        "anomalies": anomalies,
                        "anomaly_count": len(anomalies)
                    }
                )

            elif method == "iqr":
                # Interquartile Range method
                sorted_data = sorted(data)
                n = len(sorted_data)
                q1_idx = n // 4
                q3_idx = 3 * n // 4
                q1 = sorted_data[q1_idx]
                q3 = sorted_data[q3_idx]
                iqr = q3 - q1
                lower_bound = q1 - threshold * iqr
                upper_bound = q3 + threshold * iqr

                for idx, val in enumerate(data):
                    if val < lower_bound or val > upper_bound:
                        anomalies.append({
                            "index": idx,
                            "value": val,
                            "q1": round(q1, 3),
                            "q3": round(q3, 3),
                            "iqr": round(iqr, 3),
                            "lower_bound": round(lower_bound, 3),
                            "upper_bound": round(upper_bound, 3)
                        })

                return ToolResult(
                    success=True,
                    output={
                        "metric_name": metric_name,
                        "method": "iqr",
                        "threshold": threshold,
                        "data_points": len(data),
                        "q1": round(q1, 3),
                        "q3": round(q3, 3),
                        "iqr": round(iqr, 3),
                        "anomaly_detected": len(anomalies) > 0,
                        "anomalies": anomalies,
                        "anomaly_count": len(anomalies)
                    }
                )

            elif method == "moving_average":
                # Moving average method
                if len(data) < window_size:
                    return ToolResult(
                        success=True,
                        output={
                            "metric_name": metric_name,
                            "method": "moving_average",
                            "anomaly_detected": False,
                            "message": f"Insufficient data for window size {window_size}"
                        }
                    )

                for idx in range(window_size, len(data)):
                    window = data[idx - window_size:idx]
                    window_mean = statistics.mean(window)
                    window_stdev = statistics.stdev(window) if len(window) > 1 else 0

                    if window_stdev > 0:
                        deviation = abs((data[idx] - window_mean) / window_stdev)
                        if deviation > threshold:
                            anomalies.append({
                                "index": idx,
                                "value": data[idx],
                                "window_mean": round(window_mean, 3),
                                "window_stdev": round(window_stdev, 3),
                                "deviation": round(deviation, 3)
                            })

                return ToolResult(
                    success=True,
                    output={
                        "metric_name": metric_name,
                        "method": "moving_average",
                        "threshold": threshold,
                        "window_size": window_size,
                        "data_points": len(data),
                        "anomaly_detected": len(anomalies) > 0,
                        "anomalies": anomalies,
                        "anomaly_count": len(anomalies)
                    }
                )

            else:
                return ToolResult(success=False, output=None, error=f"Unknown method: {method}")

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class DashboardGeneratorTool(Tool):
    """Generate dashboard configurations for Grafana and other monitoring platforms"""

    def __init__(self):
        super().__init__()
        self.name = "dashboard_generator"
        self.description = "Generate dashboard configurations (Grafana JSON, etc.) for monitoring platforms"
        self.category = ToolCategory.MONITORING
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="dashboard_name",
                type="string",
                description="Dashboard name/title",
                required=True
            ),
            ToolParameter(
                name="platform",
                type="string",
                description="Dashboard platform",
                required=False,
                default="grafana",
                enum=["grafana", "datadog", "prometheus"]
            ),
            ToolParameter(
                name="panels",
                type="array",
                description="Array of panel configurations",
                required=True
            ),
            ToolParameter(
                name="datasource",
                type="string",
                description="Data source name",
                required=False,
                default="Prometheus"
            ),
            ToolParameter(
                name="refresh_interval",
                type="string",
                description="Dashboard refresh interval (e.g., '30s', '1m')",
                required=False,
                default="30s"
            ),
            ToolParameter(
                name="time_range",
                type="string",
                description="Default time range (e.g., 'now-1h', 'now-24h')",
                required=False,
                default="now-1h"
            ),
            ToolParameter(
                name="output_file",
                type="string",
                description="Output file path for the dashboard JSON",
                required=False
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="dashboard_generator",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.VISUALIZE,
                    description="Generate monitoring dashboards"
                )
            ]
        )

    async def execute(self, dashboard_name: str, platform: str = "grafana", panels: List[Dict] = None,
                     datasource: str = "Prometheus", refresh_interval: str = "30s",
                     time_range: str = "now-1h", output_file: str = None) -> ToolResult:
        try:
            if not panels:
                return ToolResult(success=False, output=None, error="panels array required")

            if platform == "grafana":
                # Generate Grafana dashboard JSON
                dashboard = {
                    "dashboard": {
                        "title": dashboard_name,
                        "tags": ["generated", "torinai"],
                        "timezone": "browser",
                        "schemaVersion": 36,
                        "version": 1,
                        "refresh": refresh_interval,
                        "time": {
                            "from": time_range,
                            "to": "now"
                        },
                        "panels": []
                    },
                    "overwrite": True
                }

                # Generate panels
                panel_id = 1
                y_pos = 0

                for panel_config in panels:
                    panel_type = panel_config.get("type", "graph")
                    title = panel_config.get("title", f"Panel {panel_id}")
                    query = panel_config.get("query", "")

                    grafana_panel = {
                        "id": panel_id,
                        "title": title,
                        "type": panel_type,
                        "datasource": datasource,
                        "gridPos": {
                            "h": panel_config.get("height", 8),
                            "w": panel_config.get("width", 12),
                            "x": panel_config.get("x", 0),
                            "y": y_pos
                        },
                        "targets": [
                            {
                                "expr": query,
                                "refId": "A",
                                "legendFormat": panel_config.get("legend", "")
                            }
                        ]
                    }

                    # Add panel-specific options
                    if panel_type == "graph":
                        grafana_panel["yaxes"] = [
                            {"format": "short"},
                            {"format": "short"}
                        ]
                        grafana_panel["lines"] = True
                        grafana_panel["fill"] = 1

                    elif panel_type == "stat":
                        grafana_panel["options"] = {
                            "reduceOptions": {
                                "values": False,
                                "calcs": ["lastNotNull"]
                            }
                        }

                    elif panel_type == "table":
                        grafana_panel["options"] = {
                            "showHeader": True
                        }

                    dashboard["dashboard"]["panels"].append(grafana_panel)
                    panel_id += 1
                    y_pos += panel_config.get("height", 8)

                # Save to file if requested
                if output_file:
                    output_path = Path(output_file).expanduser().resolve()
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(output_path, 'w') as f:
                        json.dump(dashboard, f, indent=2)

                return ToolResult(
                    success=True,
                    output={
                        "dashboard_name": dashboard_name,
                        "platform": "grafana",
                        "panel_count": len(panels),
                        "dashboard_json": dashboard,
                        "output_file": str(output_path) if output_file else None
                    }
                )

            elif platform == "datadog":
                # Generate Datadog dashboard JSON
                dashboard = {
                    "title": dashboard_name,
                    "description": f"Generated dashboard: {dashboard_name}",
                    "widgets": [],
                    "layout_type": "ordered",
                    "is_read_only": False,
                    "notify_list": []
                }

                for panel_config in panels:
                    widget = {
                        "definition": {
                            "title": panel_config.get("title", ""),
                            "type": panel_config.get("type", "timeseries"),
                            "requests": [
                                {
                                    "q": panel_config.get("query", ""),
                                    "display_type": "line"
                                }
                            ]
                        }
                    }
                    dashboard["widgets"].append(widget)

                if output_file:
                    output_path = Path(output_file).expanduser().resolve()
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(output_path, 'w') as f:
                        json.dump(dashboard, f, indent=2)

                return ToolResult(
                    success=True,
                    output={
                        "dashboard_name": dashboard_name,
                        "platform": "datadog",
                        "widget_count": len(panels),
                        "dashboard_json": dashboard,
                        "output_file": str(output_path) if output_file else None
                    }
                )

            elif platform == "prometheus":
                # Generate Prometheus recording rules
                rules = {
                    "groups": [
                        {
                            "name": dashboard_name.replace(" ", "_").lower(),
                            "interval": refresh_interval,
                            "rules": []
                        }
                    ]
                }

                for panel_config in panels:
                    rule = {
                        "record": panel_config.get("title", "metric").replace(" ", "_").lower(),
                        "expr": panel_config.get("query", "")
                    }
                    rules["groups"][0]["rules"].append(rule)

                if output_file:
                    output_path = Path(output_file).expanduser().resolve()
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(output_path, 'w') as f:
                        json.dump(rules, f, indent=2)

                return ToolResult(
                    success=True,
                    output={
                        "dashboard_name": dashboard_name,
                        "platform": "prometheus",
                        "rule_count": len(panels),
                        "rules_json": rules,
                        "output_file": str(output_path) if output_file else None
                    }
                )

            else:
                return ToolResult(success=False, output=None, error=f"Unknown platform: {platform}")

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))
