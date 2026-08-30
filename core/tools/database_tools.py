#!/usr/bin/env python3
"""
Database & Storage Tools
=========================
Tools for database operations and cloud storage

Tools:
- mysql_query: Execute SQL queries on TorinAI MySQL databases
- mysql_table_info: Get MySQL table schema and metadata
- mysql_backup: Backup MySQL database tables
- mysql_restore: Restore MySQL database from backup
- postgres_query: Execute SQL queries on unified PostgreSQL database
- postgres_safe_query_executor: Execute PostgreSQL queries with safety constraints
- redis_get: Get Redis key value
- redis_set: Set Redis key value
- r2_upload: Upload file to Cloudflare R2 storage
- r2_download: Download file from R2 storage

Author: Torin AI Team
"""

import logging
import json
import os
import asyncio
import time
import hashlib
import re
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path
from datetime import datetime

from .tool_registry import Tool, ToolParameter, ToolResult, ToolCategory, ToolSafety
from .capabilities import Capability, ToolCapabilityProfile, CapabilityMetadata, RiskLevel


logger = logging.getLogger(__name__)


class MySQLQueryTool(Tool):
    """Execute MySQL queries"""

    def __init__(self):
        super().__init__()
        self.name = "mysql_query"
        self.description = "Execute SQL queries on TorinAI databases (SELECT, INSERT, UPDATE, DELETE)"
        self.category = ToolCategory.DATABASE
        self.safety_level = ToolSafety.DANGEROUS
        self.parameters = [
            ToolParameter(
                name="query",
                type="string",
                description="SQL query to execute",
                required=True
            ),
            ToolParameter(
                name="database",
                type="string",
                description="Database name",
                required=False,
                default="torinai_unified",
                enum=["torinai_unified", "torinai_thinking_hot", "torinai_memory_cold"]
            ),
            ToolParameter(
                name="params",
                type="array",
                description="Query parameters for parameterized queries",
                required=False
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="mysql_query",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.QUERY_DATABASE,
                    description="Execute SQL queries on MySQL databases"
                ),
                CapabilityMetadata(
                    capability=Capability.MODIFY_DATABASE,
                    description="Modify MySQL data via INSERT/UPDATE/DELETE",
                    input_types=["sql", "params"],
                    output_types=["affected_rows"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.HIGH,
                    priority=8
                )
            ]
        )

    async def execute(self, query: str, database: str = "torinai_unified", params: List = None) -> ToolResult:
        try:
            from core.database import get_database_manager as get_unified_database

            # Get database connection
            db = get_unified_database()

            async with db.get_connection() as conn:
                # Convert %s placeholders to $1, $2, etc for PostgreSQL
                pg_query = query
                if params:
                    for i in range(len(params)):
                        pg_query = pg_query.replace('%s', f'${i+1}', 1)

                # Check if it's a SELECT query
                if pg_query.strip().upper().startswith('SELECT'):
                    results = await conn.fetch(pg_query, *(params or ()))
                    return ToolResult(
                        success=True,
                        output={
                            'query': query,
                            'database': database,
                            'rows': [dict(row) for row in results],
                            'count': len(results)
                        }
                    )
                else:
                    # For INSERT/UPDATE/DELETE
                    status = await conn.execute(pg_query, *(params or ()))
                    affected_rows = int(status.split()[-1]) if status else 0
                    return ToolResult(
                        success=True,
                        output={
                            'query': query,
                            'database': database,
                            'affected_rows': affected_rows,
                            'last_insert_id': None  # PostgreSQL uses RETURNING clause instead
                        }
                    )

        except Exception as e:
            logger.error(f"MySQL query error: {e}")
            return ToolResult(success=False, output=None, error=str(e))


class MySQLTableInfoTool(Tool):
    """Get MySQL table schema"""

    def __init__(self):
        super().__init__()
        self.name = "mysql_table_info"
        self.description = "Get schema and metadata for a MySQL table"
        self.category = ToolCategory.DATABASE
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="table_name",
                type="string",
                description="Table name",
                required=True
            ),
            ToolParameter(
                name="database",
                type="string",
                description="Database name",
                required=False,
                default="torinai_unified"
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="mysql_table_info",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.READ_DATA,
                    description="Read MySQL table schema and metadata"
                )
            ]
        )

    async def execute(self, table_name: str, database: str = "torinai_unified") -> ToolResult:
        try:
            from core.database import get_database_manager as get_unified_database

            db = get_unified_database()

            async with db.get_connection() as conn:
                # Get column info (PostgreSQL equivalent)
                columns = await conn.fetch(f"""
                    SELECT column_name, data_type, is_nullable, column_default
                    FROM information_schema.columns
                    WHERE table_name = $1 AND table_schema = 'unified'
                    ORDER BY ordinal_position
                """, table_name)

                # Get row count
                count_result = await conn.fetchrow(f"SELECT COUNT(*) as count FROM unified.{table_name}")

                # Get table size (PostgreSQL)
                size_info = await conn.fetchrow(f"""
                    SELECT
                        pg_relation_size($1) as data_length,
                        pg_indexes_size($1) as index_length,
                        pg_total_relation_size($1) as total_size
                """, f'unified.{table_name}')

                return ToolResult(
                    success=True,
                    output={
                        'table_name': table_name,
                        'database': database,
                        'columns': [dict(row) for row in columns],
                        'row_count': count_result['count'] if count_result else 0,
                        'size_info': dict(size_info) if size_info else {}
                    }
                )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class MySQLBackupTool(Tool):
    """Backup MySQL table"""

    def __init__(self):
        super().__init__()
        self.name = "mysql_backup"
        self.description = "Backup MySQL table to JSON file"
        self.category = ToolCategory.DATABASE
        self.safety_level = ToolSafety.MODERATE
        self.parameters = [
            ToolParameter(
                name="table_name",
                type="string",
                description="Table name to backup",
                required=True
            ),
            ToolParameter(
                name="output_path",
                type="string",
                description="Output file path for backup",
                required=True
            ),
            ToolParameter(
                name="database",
                type="string",
                description="Database name",
                required=False,
                default="torinai_unified"
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="mysql_backup",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.BACKUP_DATABASE,
                    description="Backup MySQL tables to files"
                )
            ]
        )

    async def execute(self, table_name: str, output_path: str, database: str = "torinai_unified") -> ToolResult:
        try:
            from core.database import get_database_manager as get_unified_database

            db = get_unified_database()

            async with db.get_connection() as conn:
                # Export all rows
                rows = await conn.fetch(f"SELECT * FROM unified.{table_name}")

                # Write to JSON file
                output = Path(output_path).expanduser().resolve()
                output.parent.mkdir(parents=True, exist_ok=True)

                with open(output, 'w') as f:
                    json.dump([dict(row) for row in rows], f, indent=2, default=str)

                return ToolResult(
                    success=True,
                    output={
                        'table_name': table_name,
                        'database': database,
                        'rows_backed_up': len(rows),
                        'output_file': str(output)
                    }
                )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class MySQLRestoreTool(Tool):
    """Restore MySQL table from backup"""

    def __init__(self):
        super().__init__()
        self.name = "mysql_restore"
        self.description = "Restore MySQL table from JSON backup file"
        self.category = ToolCategory.DATABASE
        self.safety_level = ToolSafety.DANGEROUS
        self.parameters = [
            ToolParameter(
                name="table_name",
                type="string",
                description="Table name to restore to",
                required=True
            ),
            ToolParameter(
                name="backup_path",
                type="string",
                description="Backup file path",
                required=True
            ),
            ToolParameter(
                name="truncate_first",
                type="boolean",
                description="Truncate table before restoring",
                required=False,
                default=True
            ),
            ToolParameter(
                name="database",
                type="string",
                description="Database name",
                required=False,
                default="torinai_unified"
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="mysql_restore",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.RESTORE_DATABASE,
                    description="Restore MySQL tables from backup files"
                )
            ]
        )

    async def execute(self, table_name: str, backup_path: str, truncate_first: bool = True,
                     database: str = "torinai_unified") -> ToolResult:
        try:
            from core.database import get_database_manager as get_unified_database

            # Read backup file
            backup = Path(backup_path).expanduser().resolve()
            if not backup.exists():
                return ToolResult(success=False, output=None, error=f"Backup file not found: {backup}")

            with open(backup, 'r') as f:
                rows = json.load(f)

            db = get_unified_database()

            async with db.get_connection() as conn:
                # Truncate if requested
                if truncate_first:
                    await conn.execute(f"TRUNCATE TABLE unified.{table_name}")

                # Insert rows
                if rows:
                    # Build INSERT query from first row's keys
                    columns = list(rows[0].keys())
                    placeholders = ', '.join([f'${i+1}' for i in range(len(columns))])
                    query = f"INSERT INTO unified.{table_name} ({', '.join(columns)}) VALUES ({placeholders})"

                    # Insert all rows
                    for row in rows:
                        values = [row[col] for col in columns]
                        await conn.execute(query, *values)

                return ToolResult(
                    success=True,
                    output={
                        'table_name': table_name,
                        'database': database,
                        'rows_restored': len(rows),
                        'truncated': truncate_first
                    }
                )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class RedisGetTool(Tool):
    """Get Redis key value"""

    def __init__(self):
        super().__init__()
        self.name = "redis_get"
        self.description = "Get value from Redis cache"
        self.category = ToolCategory.DATABASE
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="key",
                type="string",
                description="Redis key to retrieve",
                required=True
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="redis_get",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.READ_DATA,
                    description="Read data from Redis cache"
                ),
                CapabilityMetadata(
                    capability=Capability.RECEIVE_MESSAGE,
                    description="Receive messages and data from Redis pub/sub",
                    input_types=["key"],
                    output_types=["value"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=7
                )
            ]
        )

    async def execute(self, key: str) -> ToolResult:
        try:
            import redis.asyncio as redis

            # Connect to Redis
            r = redis.Redis(
                host=os.getenv('REDIS_HOST', 'localhost'),
                port=int(os.getenv('REDIS_PORT', 6379)),
                db=0,
                decode_responses=True
            )

            value = await r.get(key)
            await r.close()

            return ToolResult(
                success=True,
                output={
                    'key': key,
                    'value': value,
                    'exists': value is not None
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class RedisSetTool(Tool):
    """Set Redis key value"""

    def __init__(self):
        super().__init__()
        self.name = "redis_set"
        self.description = "Set value in Redis cache with optional TTL"
        self.category = ToolCategory.DATABASE
        self.safety_level = ToolSafety.MODERATE
        self.parameters = [
            ToolParameter(
                name="key",
                type="string",
                description="Redis key to set",
                required=True
            ),
            ToolParameter(
                name="value",
                type="string",
                description="Value to store",
                required=True
            ),
            ToolParameter(
                name="ttl_seconds",
                type="number",
                description="Time to live in seconds (optional)",
                required=False
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="redis_set",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.WRITE_DATA,
                    description="Write data to Redis cache"
                )
            ]
        )

    async def execute(self, key: str, value: str, ttl_seconds: int = None) -> ToolResult:
        try:
            import redis.asyncio as redis

            r = redis.Redis(
                host=os.getenv('REDIS_HOST', 'localhost'),
                port=int(os.getenv('REDIS_PORT', 6379)),
                db=0,
                decode_responses=True
            )

            if ttl_seconds:
                await r.setex(key, ttl_seconds, value)
            else:
                await r.set(key, value)

            await r.close()

            return ToolResult(
                success=True,
                output={
                    'key': key,
                    'set': True,
                    'ttl': ttl_seconds
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class R2UploadTool(Tool):
    """Upload file to Cloudflare R2 storage"""

    def __init__(self):
        super().__init__()
        self.name = "r2_upload"
        self.description = "Upload file to Cloudflare R2 object storage"
        self.category = ToolCategory.DATABASE
        self.safety_level = ToolSafety.MODERATE
        self.parameters = [
            ToolParameter(
                name="file_path",
                type="string",
                description="Local file path to upload",
                required=True
            ),
            ToolParameter(
                name="object_key",
                type="string",
                description="Object key in R2 (destination path)",
                required=True
            ),
            ToolParameter(
                name="bucket",
                type="string",
                description="R2 bucket name",
                required=False,
                default="torinai-system-data",
                enum=["torinai-system-data", "torinai-short-term-memory", "torinai-ml-models", "dominion-labs-data"]
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="r2_upload",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.UPLOAD,
                    description="Upload files to Cloudflare R2 storage"
                )
            ]
        )

    async def execute(self, file_path: str, object_key: str, bucket: str = "torinai-system-data") -> ToolResult:
        try:
            import boto3

            file = Path(file_path).expanduser().resolve()
            if not file.exists():
                return ToolResult(success=False, output=None, error=f"File not found: {file}")

            # Initialize R2 client
            s3_client = boto3.client(
                's3',
                endpoint_url=os.getenv('R2_ENDPOINT'),
                aws_access_key_id=os.getenv('R2_ACCESS_KEY_ID'),
                aws_secret_access_key=os.getenv('R2_SECRET_ACCESS_KEY')
            )

            # Upload file
            s3_client.upload_file(str(file), bucket, object_key)

            return ToolResult(
                success=True,
                output={
                    'file_path': str(file),
                    'bucket': bucket,
                    'object_key': object_key,
                    'uploaded': True,
                    'size_bytes': file.stat().st_size
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class R2DownloadTool(Tool):
    """Download file from Cloudflare R2 storage"""

    def __init__(self):
        super().__init__()
        self.name = "r2_download"
        self.description = "Download file from Cloudflare R2 object storage"
        self.category = ToolCategory.DATABASE
        self.safety_level = ToolSafety.MODERATE
        self.parameters = [
            ToolParameter(
                name="object_key",
                type="string",
                description="Object key in R2 (source path)",
                required=True
            ),
            ToolParameter(
                name="file_path",
                type="string",
                description="Local destination file path",
                required=True
            ),
            ToolParameter(
                name="bucket",
                type="string",
                description="R2 bucket name",
                required=False,
                default="torinai-system-data",
                enum=["torinai-system-data", "torinai-short-term-memory", "torinai-ml-models", "dominion-labs-data"]
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="r2_download",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.DOWNLOAD,
                    description="Download files from Cloudflare R2 storage"
                )
            ]
        )

    async def execute(self, object_key: str, file_path: str, bucket: str = "torinai-system-data") -> ToolResult:
        try:
            import boto3

            dest = Path(file_path).expanduser().resolve()
            dest.parent.mkdir(parents=True, exist_ok=True)

            # Initialize R2 client
            s3_client = boto3.client(
                's3',
                endpoint_url=os.getenv('R2_ENDPOINT'),
                aws_access_key_id=os.getenv('R2_ACCESS_KEY_ID'),
                aws_secret_access_key=os.getenv('R2_SECRET_ACCESS_KEY')
            )

            # Download file
            s3_client.download_file(bucket, object_key, str(dest))

            return ToolResult(
                success=True,
                output={
                    'object_key': object_key,
                    'bucket': bucket,
                    'file_path': str(dest),
                    'downloaded': True,
                    'size_bytes': dest.stat().st_size
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class ConnectionPoolManagerTool(Tool):
    """Manage database connection pools with health checks and retries"""

    def __init__(self):
        super().__init__()
        self.name = "connection_pool_manager"
        self.description = "Manage database connection pool health, test connections with retry logic"
        self.category = ToolCategory.DATABASE
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="operation",
                type="string",
                description="Operation to perform",
                required=True,
                enum=["check_health", "test_connection", "get_stats", "retry_query"]
            ),
            ToolParameter(
                name="database",
                type="string",
                description="Database name",
                required=False,
                default="torinai_unified",
                enum=["torinai_unified", "torinai_thinking_hot", "torinai_memory_cold"]
            ),
            ToolParameter(
                name="query",
                type="string",
                description="Query to execute with retry (for retry_query operation)",
                required=False
            ),
            ToolParameter(
                name="max_retries",
                type="integer",
                description="Maximum retry attempts",
                required=False,
                default=3
            ),
            ToolParameter(
                name="retry_delay",
                type="number",
                description="Delay between retries in seconds",
                required=False,
                default=1.0
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="connection_pool_manager",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.CHECK_CONNECTIVITY,
                    description="Manage database connection pools"
                )
            ]
        )

    async def execute(self, operation: str, database: str = "torinai_unified",
                     query: str = None, max_retries: int = 3, retry_delay: float = 1.0) -> ToolResult:
        try:
            from core.database import get_database_manager as get_unified_database

            db = get_unified_database()

            if operation == "check_health":
                # Check pool health
                try:
                    async with db.get_connection() as conn:
                        await conn.fetchval("SELECT 1")

                    return ToolResult(
                        success=True,
                        output={
                            'operation': 'check_health',
                            'database': database,
                            'healthy': True,
                            'pool_size': db.pool.get_size(),
                            'pool_free': db.pool.get_idle_size()
                        }
                    )
                except Exception as health_error:
                    return ToolResult(
                        success=True,
                        output={
                            'operation': 'check_health',
                            'database': database,
                            'healthy': False,
                            'error': str(health_error)
                        }
                    )

            elif operation == "test_connection":
                # Test connection with timeout
                start_time = time.time()
                try:
                    async def _test_conn():
                        async with db.get_connection() as conn:
                            return await conn.fetchrow("SELECT version() as version, NOW() as server_time")
                    result = await asyncio.wait_for(_test_conn(), timeout=5.0)

                    elapsed = time.time() - start_time
                    return ToolResult(
                        success=True,
                        output={
                            'operation': 'test_connection',
                            'database': database,
                            'connected': True,
                            'version': result['version'] if result else None,
                            'server_time': str(result['server_time']) if result else None,
                            'latency_ms': round(elapsed * 1000, 2)
                        }
                    )
                except asyncio.TimeoutError:
                    return ToolResult(
                        success=False,
                        output=None,
                        error="Connection test timed out after 5 seconds"
                    )

            elif operation == "get_stats":
                # Get pool statistics
                pool_size = db.pool.get_size()
                pool_free = db.pool.get_idle_size()
                return ToolResult(
                    success=True,
                    output={
                        'operation': 'get_stats',
                        'database': database,
                        'pool_size': pool_size,
                        'pool_free': pool_free,
                        'pool_used': pool_size - pool_free,
                        'max_size': db.pool.get_max_size(),
                        'min_size': db.pool.get_min_size()
                    }
                )

            elif operation == "retry_query":
                # Execute query with retry logic
                if not query:
                    return ToolResult(success=False, output=None, error="query parameter required for retry_query operation")

                last_error = None
                for attempt in range(max_retries):
                    try:
                        async with db.get_connection() as conn:
                            if query.strip().upper().startswith('SELECT'):
                                results = await conn.fetch(query)
                                return ToolResult(
                                    success=True,
                                    output={
                                        'operation': 'retry_query',
                                        'query': query,
                                        'attempts': attempt + 1,
                                        'rows': [dict(row) for row in results],
                                        'count': len(results)
                                    }
                                )
                            else:
                                status = await conn.execute(query)
                                affected_rows = int(status.split()[-1]) if status else 0
                                return ToolResult(
                                    success=True,
                                    output={
                                        'operation': 'retry_query',
                                        'query': query,
                                        'attempts': attempt + 1,
                                        'affected_rows': affected_rows
                                    }
                                )
                    except Exception as e:
                        last_error = str(e)
                        if attempt < max_retries - 1:
                            await asyncio.sleep(retry_delay * (attempt + 1))  # Exponential backoff
                        continue

                return ToolResult(
                    success=False,
                    output={'attempts': max_retries},
                    error=f"Query failed after {max_retries} attempts: {last_error}"
                )

            else:
                return ToolResult(success=False, output=None, error=f"Unknown operation: {operation}")

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class TransactionWrapperTool(Tool):
    """Execute multiple queries in a transaction with rollback on failure"""

    def __init__(self):
        super().__init__()
        self.name = "transaction_wrapper"
        self.description = "Execute multiple SQL queries in a transaction with automatic rollback on failure"
        self.category = ToolCategory.DATABASE
        self.safety_level = ToolSafety.DANGEROUS
        self.parameters = [
            ToolParameter(
                name="queries",
                type="array",
                description="List of SQL queries to execute in transaction",
                required=True
            ),
            ToolParameter(
                name="database",
                type="string",
                description="Database name",
                required=False,
                default="torinai_unified",
                enum=["torinai_unified", "torinai_thinking_hot", "torinai_memory_cold"]
            ),
            ToolParameter(
                name="isolation_level",
                type="string",
                description="Transaction isolation level",
                required=False,
                default="READ COMMITTED",
                enum=["READ UNCOMMITTED", "READ COMMITTED", "REPEATABLE READ", "SERIALIZABLE"]
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="transaction_wrapper",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.QUERY_DATABASE,
                    description="Execute database queries in transactions"
                )
            ]
        )

    async def execute(self, queries: List[str], database: str = "torinai_unified",
                     isolation_level: str = "READ COMMITTED") -> ToolResult:
        try:
            from core.database import get_database_manager as get_unified_database

            if not queries or len(queries) == 0:
                return ToolResult(success=False, output=None, error="queries array cannot be empty")

            db = get_unified_database()
            results = []

            try:
                async with db.get_connection() as conn:
                    # Begin transaction
                    async with conn.transaction(isolation=isolation_level.lower().replace(' ', '_')):
                        # Execute each query
                        for idx, query in enumerate(queries):
                            if query.strip().upper().startswith('SELECT'):
                                rows = await conn.fetch(query)
                                results.append({
                                    'query_index': idx,
                                    'query': query[:100] + '...' if len(query) > 100 else query,
                                    'type': 'SELECT',
                                    'rows': [dict(row) for row in rows],
                                    'count': len(rows)
                                })
                            else:
                                status = await conn.execute(query)
                                affected_rows = int(status.split()[-1]) if status else 0
                                results.append({
                                    'query_index': idx,
                                    'query': query[:100] + '...' if len(query) > 100 else query,
                                    'type': 'MODIFY',
                                    'affected_rows': affected_rows,
                                    'last_insert_id': None
                                })

                    # Commit transaction (automatic with context manager)
                    return ToolResult(
                        success=True,
                        output={
                            'database': database,
                            'isolation_level': isolation_level,
                            'queries_executed': len(queries),
                            'committed': True,
                            'results': results
                        }
                    )

            except Exception as tx_error:
                # Rollback is automatic on exception with transaction context manager
                return ToolResult(
                    success=False,
                    output={
                        'database': database,
                        'queries_executed': len(results),
                        'committed': False,
                        'rolled_back': True,
                        'partial_results': results
                    },
                    error=f"Transaction failed and rolled back: {str(tx_error)}"
                )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class MigrationRunnerTool(Tool):
    """Apply database migrations and detect schema drift"""

    def __init__(self):
        super().__init__()
        self.name = "migration_runner"
        self.description = "Apply database migrations, track migration history, and detect schema drift"
        self.category = ToolCategory.DATABASE
        self.safety_level = ToolSafety.CRITICAL
        self.parameters = [
            ToolParameter(
                name="operation",
                type="string",
                description="Migration operation to perform",
                required=True,
                enum=["apply", "check_drift", "get_history", "create_migrations_table"]
            ),
            ToolParameter(
                name="migration_file",
                type="string",
                description="Path to migration SQL file (for apply operation)",
                required=False
            ),
            ToolParameter(
                name="migration_name",
                type="string",
                description="Migration name/identifier",
                required=False
            ),
            ToolParameter(
                name="database",
                type="string",
                description="Database name",
                required=False,
                default="torinai_unified",
                enum=["torinai_unified", "torinai_thinking_hot", "torinai_memory_cold"]
            ),
            ToolParameter(
                name="expected_schema_hash",
                type="string",
                description="Expected schema hash for drift detection",
                required=False
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="migration_runner",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.MIGRATE_DATABASE,
                    description="Run database migrations"
                )
            ]
        )

    async def execute(self, operation: str, migration_file: str = None, migration_name: str = None,
                     database: str = "torinai_unified", expected_schema_hash: str = None) -> ToolResult:
        try:
            from core.database import get_database_manager as get_unified_database

            db = get_unified_database()

            if operation == "create_migrations_table":
                # Create migrations tracking table (PostgreSQL syntax)
                create_table_sql = """
                CREATE TABLE IF NOT EXISTS unified.schema_migrations (
                    id SERIAL PRIMARY KEY,
                    migration_name VARCHAR(255) NOT NULL UNIQUE,
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    checksum VARCHAR(64) NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_migration_name ON unified.schema_migrations (migration_name);
                CREATE INDEX IF NOT EXISTS idx_applied_at ON unified.schema_migrations (applied_at);
                """
                async with db.get_connection() as conn:
                    await conn.execute(create_table_sql)

                return ToolResult(
                    success=True,
                    output={
                        'operation': 'create_migrations_table',
                        'database': database,
                        'table_created': True
                    }
                )

            elif operation == "apply":
                # Apply a migration
                if not migration_file or not migration_name:
                    return ToolResult(
                        success=False,
                        output=None,
                        error="migration_file and migration_name required for apply operation"
                    )

                migration_path = Path(migration_file).expanduser().resolve()
                if not migration_path.exists():
                    return ToolResult(success=False, output=None, error=f"Migration file not found: {migration_file}")

                migration_sql = migration_path.read_text()
                checksum = hashlib.sha256(migration_sql.encode()).hexdigest()

                async with db.get_connection() as conn:
                    # Check if migration already applied
                    existing = await conn.fetchrow(
                        "SELECT checksum FROM unified.schema_migrations WHERE migration_name = $1",
                        migration_name
                    )

                    if existing:
                        if existing['checksum'] == checksum:
                            return ToolResult(
                                success=True,
                                output={
                                    'operation': 'apply',
                                    'migration_name': migration_name,
                                    'already_applied': True,
                                    'checksum_match': True
                                }
                            )
                        else:
                            return ToolResult(
                                success=False,
                                output=None,
                                error=f"Migration {migration_name} already exists with different checksum"
                            )

                    # Apply migration in transaction
                    try:
                        async with conn.transaction():
                            # Execute migration SQL (split by semicolon for multiple statements)
                            statements = [s.strip() for s in migration_sql.split(';') if s.strip()]
                            for statement in statements:
                                await conn.execute(statement)

                            # Record migration
                            await conn.execute(
                                "INSERT INTO unified.schema_migrations (migration_name, checksum) VALUES ($1, $2)",
                                migration_name, checksum
                            )

                        return ToolResult(
                            success=True,
                            output={
                                'operation': 'apply',
                                'migration_name': migration_name,
                                'database': database,
                                'applied': True,
                                'checksum': checksum,
                                'statements_executed': len(statements)
                            }
                        )

                    except Exception as apply_error:
                        return ToolResult(
                            success=False,
                            output=None,
                            error=f"Migration failed and rolled back: {str(apply_error)}"
                        )

            elif operation == "get_history":
                # Get migration history
                async with db.get_connection() as conn:
                    migrations = await conn.fetch(
                        "SELECT migration_name, applied_at, checksum FROM unified.schema_migrations ORDER BY applied_at DESC"
                    )

                return ToolResult(
                    success=True,
                    output={
                        'operation': 'get_history',
                        'database': database,
                        'migrations': [
                            {
                                'migration_name': m['migration_name'],
                                'applied_at': str(m['applied_at']),
                                'checksum': m.get('checksum', '')
                            }
                            for m in migrations
                        ],
                        'count': len(migrations)
                    }
                )

            elif operation == "check_drift":
                # Check schema drift
                async with db.get_connection() as conn:
                    # Get current schema (PostgreSQL)
                    schema = await conn.fetch("""
                        SELECT table_name, column_name, data_type, is_nullable, column_default
                        FROM information_schema.columns
                        WHERE table_schema = 'unified'
                        ORDER BY table_name, ordinal_position
                    """)

                # Calculate current schema hash
                schema_str = json.dumps([dict(row) for row in schema], sort_keys=True, default=str)
                current_hash = hashlib.sha256(schema_str.encode()).hexdigest()

                drift_detected = False
                if expected_schema_hash:
                    drift_detected = (current_hash != expected_schema_hash)

                return ToolResult(
                    success=True,
                    output={
                        'operation': 'check_drift',
                        'database': database,
                        'current_schema_hash': current_hash,
                        'expected_schema_hash': expected_schema_hash,
                        'drift_detected': drift_detected,
                        'table_count': len(set(row['table_name'] for row in schema)),
                        'column_count': len(schema)
                    }
                )

            else:
                return ToolResult(success=False, output=None, error=f"Unknown operation: {operation}")

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class RowLevelAccessControlTool(Tool):
    """Manage row-level access controls for service users"""

    def __init__(self):
        super().__init__()
        self.name = "row_level_access_control"
        self.description = "Manage row-level access controls, scoping service users to specific data owners"
        self.category = ToolCategory.DATABASE
        self.safety_level = ToolSafety.CRITICAL
        self.parameters = [
            ToolParameter(
                name="operation",
                type="string",
                description="Access control operation",
                required=True,
                enum=["create_policy", "check_access", "list_policies", "delete_policy"]
            ),
            ToolParameter(
                name="table_name",
                type="string",
                description="Table name to apply policy to",
                required=False
            ),
            ToolParameter(
                name="service_user",
                type="string",
                description="Service user identifier",
                required=False
            ),
            ToolParameter(
                name="owner_column",
                type="string",
                description="Column name that contains owner identifier",
                required=False,
                default="user_id"
            ),
            ToolParameter(
                name="allowed_owners",
                type="array",
                description="List of owner IDs this service user can access",
                required=False
            ),
            ToolParameter(
                name="database",
                type="string",
                description="Database name",
                required=False,
                default="torinai_unified",
                enum=["torinai_unified", "torinai_thinking_hot", "torinai_memory_cold"]
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="row_level_access_control",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.VALIDATE_DATA,
                    description="Validate row-level database access control"
                )
            ]
        )

    async def execute(self, operation: str, table_name: str = None, service_user: str = None,
                     owner_column: str = "user_id", allowed_owners: List = None,
                     database: str = "torinai_unified") -> ToolResult:
        try:
            from core.database import get_database_manager as get_unified_database

            db = get_unified_database()

            if operation == "create_policy":
                # Create access control policy table if not exists
                if not table_name or not service_user or not allowed_owners:
                    return ToolResult(
                        success=False,
                        output=None,
                        error="table_name, service_user, and allowed_owners required for create_policy"
                    )

                # Use unified Postgres database manager instead of direct MySQL pool
                from core.database import get_database_manager
                pg_db = get_database_manager()

                # Create policies table if not exists (Postgres DDL)
                await pg_db.execute_query(
                    """
                    CREATE TABLE IF NOT EXISTS row_access_policies (
                        id SERIAL PRIMARY KEY,
                        table_name VARCHAR(255) NOT NULL,
                        service_user VARCHAR(255) NOT NULL,
                        owner_column VARCHAR(255) NOT NULL,
                        allowed_owner VARCHAR(255) NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        CONSTRAINT uq_row_policy UNIQUE (table_name, service_user, owner_column, allowed_owner)
                    )
                    """,
                    commit=True,
                )

                # Insert policies for each allowed owner using Postgres upsert
                for owner in allowed_owners:
                    await pg_db.execute_query(
                        """
                        INSERT INTO row_access_policies
                        (table_name, service_user, owner_column, allowed_owner)
                        VALUES ($1, $2, $3, $4)
                        ON CONFLICT (table_name, service_user, owner_column, allowed_owner) DO UPDATE SET
                            allowed_owner = EXCLUDED.allowed_owner
                        """,
                        params=(table_name, service_user, owner_column, str(owner)),
                        commit=True,
                    )

                return ToolResult(
                    success=True,
                    output={
                        'operation': 'create_policy',
                        'database': database,
                        'table_name': table_name,
                        'service_user': service_user,
                        'owner_column': owner_column,
                        'allowed_owners': allowed_owners,
                        'policies_created': len(allowed_owners)
                    }
                )

            elif operation == "check_access":
                # Check if service user has access to specific owner's data
                if not table_name or not service_user:
                    return ToolResult(
                        success=False,
                        output=None,
                        error="table_name and service_user required for check_access"
                    )

                owner_id = allowed_owners[0] if allowed_owners else None
                if not owner_id:
                    return ToolResult(success=False, output=None, error="owner_id required in allowed_owners array")

                async with db.get_connection() as conn:
                    result = await conn.fetchrow("""
                        SELECT COUNT(*) as count FROM unified.row_access_policies
                        WHERE table_name = $1 AND service_user = $2 AND allowed_owner = $3
                    """, table_name, service_user, str(owner_id))

                has_access = result['count'] > 0

                return ToolResult(
                    success=True,
                    output={
                        'operation': 'check_access',
                        'database': database,
                        'table_name': table_name,
                        'service_user': service_user,
                        'owner_id': owner_id,
                        'has_access': has_access
                    }
                )

            elif operation == "list_policies":
                # List all policies for a service user or table
                async with db.get_connection() as conn:
                    if service_user and table_name:
                        policies = await conn.fetch("""
                            SELECT table_name, service_user, owner_column, allowed_owner, created_at
                            FROM unified.row_access_policies
                            WHERE service_user = $1 AND table_name = $2
                            ORDER BY created_at DESC
                        """, service_user, table_name)
                    elif service_user:
                        policies = await conn.fetch("""
                            SELECT table_name, service_user, owner_column, allowed_owner, created_at
                            FROM unified.row_access_policies
                            WHERE service_user = $1
                            ORDER BY created_at DESC
                        """, service_user)
                    elif table_name:
                        policies = await conn.fetch("""
                            SELECT table_name, service_user, owner_column, allowed_owner, created_at
                            FROM unified.row_access_policies
                            WHERE table_name = $1
                            ORDER BY created_at DESC
                        """, table_name)
                    else:
                        policies = await conn.fetch("""
                            SELECT table_name, service_user, owner_column, allowed_owner, created_at
                            FROM unified.row_access_policies
                            ORDER BY created_at DESC
                        """)

                return ToolResult(
                    success=True,
                    output={
                        'operation': 'list_policies',
                        'database': database,
                        'service_user': service_user,
                        'table_name': table_name,
                        'policies': [
                            {
                                'table_name': p['table_name'],
                                'service_user': p['service_user'],
                                'owner_column': p['owner_column'],
                                'allowed_owner': p['allowed_owner'],
                                'created_at': str(p['created_at'])
                            }
                            for p in policies
                        ],
                        'count': len(policies)
                    }
                )

            elif operation == "delete_policy":
                # Delete access policy
                if not table_name or not service_user:
                    return ToolResult(
                        success=False,
                        output=None,
                        error="table_name and service_user required for delete_policy"
                    )

                async with db.get_connection() as conn:
                    if allowed_owners:
                        # Delete specific owner policies
                        placeholders = ','.join([f'${i+3}' for i in range(len(allowed_owners))])
                        status = await conn.execute(f"""
                            DELETE FROM unified.row_access_policies
                            WHERE table_name = $1 AND service_user = $2
                            AND allowed_owner IN ({placeholders})
                        """, table_name, service_user, *[str(o) for o in allowed_owners])
                    else:
                        # Delete all policies for service user and table
                        status = await conn.execute("""
                            DELETE FROM unified.row_access_policies
                            WHERE table_name = $1 AND service_user = $2
                        """, table_name, service_user)

                    deleted_count = int(status.split()[-1]) if status else 0

                return ToolResult(
                    success=True,
                    output={
                        'operation': 'delete_policy',
                        'database': database,
                        'table_name': table_name,
                        'service_user': service_user,
                        'deleted_count': deleted_count
                    }
                )

            else:
                return ToolResult(success=False, output=None, error=f"Unknown operation: {operation}")

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class SafeQueryExecutorTool(Tool):
    """Execute queries with safety constraints (read-only mode, max rows, timeout)"""

    def __init__(self):
        super().__init__()
        self.name = "safe_query_executor"
        self.description = "Execute SQL queries with safety constraints: read-only mode, row limits, and timeouts"
        self.category = ToolCategory.DATABASE
        self.safety_level = ToolSafety.MODERATE
        self.parameters = [
            ToolParameter(
                name="query",
                type="string",
                description="SQL query to execute",
                required=True
            ),
            ToolParameter(
                name="database",
                type="string",
                description="Database name",
                required=False,
                default="torinai_unified",
                enum=["torinai_unified", "torinai_thinking_hot", "torinai_memory_cold"]
            ),
            ToolParameter(
                name="read_only",
                type="boolean",
                description="Enforce read-only mode (only SELECT queries allowed)",
                required=False,
                default=True
            ),
            ToolParameter(
                name="max_rows",
                type="integer",
                description="Maximum number of rows to return (0 = unlimited)",
                required=False,
                default=1000
            ),
            ToolParameter(
                name="timeout_seconds",
                type="number",
                description="Query timeout in seconds",
                required=False,
                default=30.0
            ),
            ToolParameter(
                name="params",
                type="array",
                description="Query parameters for parameterized queries",
                required=False
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="safe_query_executor",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.QUERY_DATABASE,
                    description="Execute SQL queries with safety constraints"
                )
            ]
        )

    async def execute(self, query: str, database: str = "torinai_unified", read_only: bool = True,
                     max_rows: int = 1000, timeout_seconds: float = 30.0, params: List = None) -> ToolResult:
        try:
            from core.database import get_database_manager as get_unified_database

            # Read-only validation
            query_upper = query.strip().upper()
            is_select = query_upper.startswith('SELECT') or query_upper.startswith('SHOW') or query_upper.startswith('DESCRIBE')

            if read_only and not is_select:
                return ToolResult(
                    success=False,
                    output=None,
                    error="Read-only mode enabled: only SELECT, SHOW, and DESCRIBE queries allowed"
                )

            # Detect dangerous patterns even in read-only mode
            dangerous_patterns = [
                r'\bINTO\s+OUTFILE\b',
                r'\bINTO\s+DUMPFILE\b',
                r'\bLOAD\s+DATA\b',
                r'\bLOAD_FILE\b'
            ]
            for pattern in dangerous_patterns:
                if re.search(pattern, query_upper):
                    return ToolResult(
                        success=False,
                        output=None,
                        error=f"Query contains forbidden pattern: {pattern}"
                    )

            db = get_unified_database()
            start_time = time.time()

            try:
                # Execute with timeout
                async def _execute_query():
                    async with db.get_connection() as conn:
                        # Convert %s placeholders to $1, $2, etc
                        pg_query = query
                        if params:
                            for i in range(len(params)):
                                pg_query = pg_query.replace('%s', f'${i+1}', 1)

                        if is_select:
                            # Fetch results with limit
                            results = await conn.fetch(pg_query, *(params or ()))

                            truncated = False
                            if max_rows > 0 and len(results) > max_rows:
                                results = results[:max_rows]
                                truncated = True

                            elapsed = time.time() - start_time

                            return ToolResult(
                                success=True,
                                output={
                                    'query': query[:200] + '...' if len(query) > 200 else query,
                                    'database': database,
                                    'read_only_mode': read_only,
                                    'rows': [dict(row) for row in results],
                                    'count': len(results),
                                    'truncated': truncated,
                                    'max_rows': max_rows,
                                    'execution_time_ms': round(elapsed * 1000, 2),
                                    'timeout_seconds': timeout_seconds
                                }
                            )
                        else:
                            # For non-SELECT queries (if read_only is False)
                            status = await conn.execute(pg_query, *(params or ()))
                            affected_rows = int(status.split()[-1]) if status else 0
                            elapsed = time.time() - start_time

                            return ToolResult(
                                success=True,
                                output={
                                    'query': query[:200] + '...' if len(query) > 200 else query,
                                    'database': database,
                                    'read_only_mode': read_only,
                                    'affected_rows': affected_rows,
                                    'last_insert_id': None,
                                    'execution_time_ms': round(elapsed * 1000, 2),
                                    'timeout_seconds': timeout_seconds
                                }
                            )

                return await asyncio.wait_for(_execute_query(), timeout=timeout_seconds)

            except asyncio.TimeoutError:
                return ToolResult(
                    success=False,
                    output={'timeout_seconds': timeout_seconds},
                    error=f"Query exceeded timeout of {timeout_seconds} seconds"
                )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class PostgresQueryTool(Tool):
    """Execute PostgreSQL queries using the unified database manager"""

    def __init__(self):
        super().__init__()
        self.name = "postgres_query"
        self.description = "Execute SQL queries on the unified PostgreSQL database (SELECT, INSERT, UPDATE, DELETE)"
        self.category = ToolCategory.DATABASE
        self.safety_level = ToolSafety.DANGEROUS
        self.parameters = [
            ToolParameter(
                name="query",
                type="string",
                description="SQL query to execute (use $1, $2 placeholders for parameters)",
                required=True
            ),
            ToolParameter(
                name="database",
                type="string",
                description="Logical database/schema to target",
                required=False,
                default="unified",
                enum=["unified", "memory_hot", "memory_cold"]
            ),
            ToolParameter(
                name="params",
                type="array",
                description="Query parameters for parameterized queries",
                required=False
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="postgres_query",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.QUERY_DATABASE,
                    description="Execute SQL queries on PostgreSQL databases"
                ),
                CapabilityMetadata(
                    capability=Capability.MODIFY_DATABASE,
                    description="Modify PostgreSQL data via INSERT/UPDATE/DELETE",
                    input_types=["sql", "params"],
                    output_types=["affected_rows"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.HIGH,
                    priority=8
                )
            ]
        )

    async def execute(self, query: str, database: str = "unified", params: List = None) -> ToolResult:
        try:
            from core.database import get_database_manager

            db = get_database_manager()

            # Initialize pool if needed
            if not getattr(db, "initialized", False):
                await db.initialize()

            query_upper = query.strip().upper()
            is_select = query_upper.startswith("SELECT") or query_upper.startswith("WITH")

            use_hot_tier = database == "memory_hot"
            use_cold_tier = database == "memory_cold"

            params_tuple: Tuple = tuple(params or ())

            if is_select:
                # Use convenience wrapper for SELECT-style queries
                rows = await db.execute_query(
                    query,
                    params_tuple,
                    use_hot_tier=use_hot_tier,
                    use_cold_tier=use_cold_tier,
                    fetch_all=True,
                ) or []

                return ToolResult(
                    success=True,
                    output={
                        "query": query,
                        "database": database,
                        "rows": rows,
                        "count": len(rows),
                    },
                )

            # Non-SELECT: execute and return status / affected row count
            async with db.get_connection(use_hot_tier=use_hot_tier, use_cold_tier=use_cold_tier) as conn:
                status = await conn.execute(query, *params_tuple)

            affected_rows: Optional[int] = None
            if status:
                # asyncpg status examples: "INSERT 0 1", "UPDATE 3"
                parts = status.split()
                if parts and parts[-1].isdigit():
                    affected_rows = int(parts[-1])

            return ToolResult(
                success=True,
                output={
                    "query": query,
                    "database": database,
                    "status": status,
                    "affected_rows": affected_rows,
                },
            )

        except Exception as e:
            logger.error(f"PostgreSQL query error: {e}")
            return ToolResult(success=False, output=None, error=str(e))


class PostgresSafeQueryExecutorTool(Tool):
    """Execute PostgreSQL queries with safety constraints (read-only, limits, timeout)"""

    def __init__(self):
        super().__init__()
        self.name = "postgres_safe_query_executor"
        self.description = "Execute PostgreSQL queries with safety constraints: read-only mode, row limits, and timeouts"
        self.category = ToolCategory.DATABASE
        self.safety_level = ToolSafety.MODERATE
        self.parameters = [
            ToolParameter(
                name="query",
                type="string",
                description="SQL query to execute (use $1, $2 placeholders for parameters)",
                required=True,
            ),
            ToolParameter(
                name="database",
                type="string",
                description="Logical database/schema to target",
                required=False,
                default="unified",
                enum=["unified", "memory_hot", "memory_cold"],
            ),
            ToolParameter(
                name="read_only",
                type="boolean",
                description="Enforce read-only mode (only SELECT/SHOW-like queries allowed)",
                required=False,
                default=True,
            ),
            ToolParameter(
                name="max_rows",
                type="integer",
                description="Maximum number of rows to return (0 = unlimited)",
                required=False,
                default=1000,
            ),
            ToolParameter(
                name="timeout_seconds",
                type="number",
                description="Query timeout in seconds",
                required=False,
                default=30.0,
            ),
            ToolParameter(
                name="params",
                type="array",
                description="Query parameters for parameterized queries",
                required=False,
            ),
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="postgres_safe_query_executor",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.QUERY_DATABASE,
                    description="Execute PostgreSQL queries with safety constraints"
                )
            ]
        )

    async def execute(
        self,
        query: str,
        database: str = "unified",
        read_only: bool = True,
        max_rows: int = 1000,
        timeout_seconds: float = 30.0,
        params: List = None,
    ) -> ToolResult:
        try:
            from core.database import get_database_manager

            db = get_database_manager()
            if not getattr(db, "initialized", False):
                await db.initialize()

            query_upper = query.strip().upper()
            is_select_like = (
                query_upper.startswith("SELECT")
                or query_upper.startswith("WITH")
                or query_upper.startswith("SHOW")
            )

            if read_only and not is_select_like:
                return ToolResult(
                    success=False,
                    output=None,
                    error="Read-only mode enabled: only SELECT/SHOW/WITH queries allowed",
                )

            # Basic pattern safety checks (same as MySQL variant; still useful)
            dangerous_patterns = [
                r"\bINTO\s+OUTFILE\b",
                r"\bINTO\s+DUMPFILE\b",
                r"\bLOAD\s+DATA\b",
                r"\bLOAD_FILE\b",
            ]
            for pattern in dangerous_patterns:
                if re.search(pattern, query_upper):
                    return ToolResult(
                        success=False,
                        output=None,
                        error=f"Query contains forbidden pattern: {pattern}",
                    )

            use_hot_tier = database == "memory_hot"
            use_cold_tier = database == "memory_cold"
            params_tuple: Tuple = tuple(params or ())
            start_time = time.time()

            async def _execute_query() -> ToolResult:
                if is_select_like:
                    # Fetch all, then enforce max_rows in Python for simplicity
                    rows = await db.execute_query(
                        query,
                        params_tuple,
                        use_hot_tier=use_hot_tier,
                        use_cold_tier=use_cold_tier,
                        fetch_all=True,
                    ) or []

                    truncated = False
                    if max_rows > 0 and len(rows) > max_rows:
                        rows = rows[:max_rows]
                        truncated = True

                    elapsed = time.time() - start_time
                    return ToolResult(
                        success=True,
                        output={
                            "query": query[:200] + "..." if len(query) > 200 else query,
                            "database": database,
                            "read_only_mode": read_only,
                            "rows": rows,
                            "count": len(rows),
                            "truncated": truncated,
                            "max_rows": max_rows,
                            "execution_time_ms": round(elapsed * 1000, 2),
                            "timeout_seconds": timeout_seconds,
                        },
                    )

                # Non-SELECT-like queries (only when read_only is False)
                async with db.get_connection(
                    use_hot_tier=use_hot_tier,
                    use_cold_tier=use_cold_tier,
                ) as conn:
                    status = await conn.execute(query, *params_tuple)

                elapsed = time.time() - start_time

                affected_rows: Optional[int] = None
                if status:
                    parts = status.split()
                    if parts and parts[-1].isdigit():
                        affected_rows = int(parts[-1])

                return ToolResult(
                    success=True,
                    output={
                        "query": query[:200] + "..." if len(query) > 200 else query,
                        "database": database,
                        "read_only_mode": read_only,
                        "affected_rows": affected_rows,
                        "status": status,
                        "execution_time_ms": round(elapsed * 1000, 2),
                        "timeout_seconds": timeout_seconds,
                    },
                )

            try:
                return await asyncio.wait_for(_execute_query(), timeout=timeout_seconds)
            except asyncio.TimeoutError:
                return ToolResult(
                    success=False,
                    output={"timeout_seconds": timeout_seconds},
                    error=f"Query exceeded timeout of {timeout_seconds} seconds",
                )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))
