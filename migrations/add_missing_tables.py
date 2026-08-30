#!/usr/bin/env python3
"""
Add Missing Tables Migration
Creates tool_tracking_state, governance_module_state, and chaos_adapter_state tables
"""

import asyncio
import logging
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.database.unified_database_mysql import TorinUnifiedDatabaseMySQL

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def apply_migration():
    db = TorinUnifiedDatabaseMySQL()

    try:
        await db.initialize()
        logger.info("Database connected")

        # Create tool_tracking_state table
        await db.execute_query("""
            CREATE TABLE IF NOT EXISTS tool_tracking_state (
                id INT AUTO_INCREMENT PRIMARY KEY,
                tool_name VARCHAR(128) NOT NULL,
                tracking_type ENUM(
                    'cooldown',
                    'failure_count',
                    'sequence',
                    'failed_params',
                    'blocked_params'
                ) NOT NULL,
                state_data JSON NOT NULL,
                iteration_count INT DEFAULT 0,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NULL,
                UNIQUE KEY idx_tool_tracking (tool_name, tracking_type),
                INDEX idx_tracking_type (tracking_type),
                INDEX idx_expires_at (expires_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            COMMENT='Tool tracking state for intrinsic motivation diversity enforcement'
        """, commit=True)
        logger.info("✓ tool_tracking_state table created")

        # Create governance_module_state table
        await db.execute_query("""
            CREATE TABLE IF NOT EXISTS governance_module_state (
                id INT AUTO_INCREMENT PRIMARY KEY,
                module_name VARCHAR(255) NOT NULL UNIQUE,
                is_frozen BOOLEAN DEFAULT FALSE,
                file_hash VARCHAR(64) NULL,
                file_path TEXT NULL,
                original_attributes JSON NULL,
                frozen_at TIMESTAMP NULL,
                last_verified TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_frozen_status (is_frozen),
                INDEX idx_module_name (module_name)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            COMMENT='Runtime governance module freeze state and integrity tracking'
        """, commit=True)
        logger.info("✓ governance_module_state table created")

        # Create chaos_adapter_state table
        await db.execute_query("""
            CREATE TABLE IF NOT EXISTS chaos_adapter_state (
                id INT AUTO_INCREMENT PRIMARY KEY,
                adapter_name VARCHAR(128) NOT NULL,
                method_path VARCHAR(255) NOT NULL,
                original_method_info JSON NOT NULL,
                is_injected BOOLEAN DEFAULT FALSE,
                injection_type VARCHAR(50) NULL,
                stored_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY idx_adapter_method (adapter_name, method_path)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            COMMENT='Chaos adapter state for storing original method references'
        """, commit=True)
        logger.info("✓ chaos_adapter_state table created")

        logger.info("Migration complete")

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(apply_migration())
