#!/usr/bin/env python3
"""
Add Frontier Foresight Tables Migration
Creates benchmark_history and research_publications tables for capability tracking
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

        # Create benchmark_history table
        await db.execute_query("""
            CREATE TABLE IF NOT EXISTS benchmark_history (
                id INT AUTO_INCREMENT PRIMARY KEY,
                capability VARCHAR(255) NOT NULL,
                benchmark_name VARCHAR(255) NOT NULL,
                score DECIMAL(10, 4) NOT NULL,
                measured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                model_version VARCHAR(100) NULL,
                dataset_version VARCHAR(100) NULL,
                metadata JSON NULL,
                INDEX idx_capability (capability),
                INDEX idx_measured_at (measured_at),
                INDEX idx_capability_time (capability, measured_at DESC)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            COMMENT='Benchmark performance history for frontier capability tracking'
        """, commit=True)
        logger.info("✓ benchmark_history table created")

        # Create research_publications table
        await db.execute_query("""
            CREATE TABLE IF NOT EXISTS research_publications (
                id INT AUTO_INCREMENT PRIMARY KEY,
                capability VARCHAR(255) NOT NULL,
                paper_title TEXT NOT NULL,
                authors TEXT NULL,
                published_date DATE NOT NULL,
                venue VARCHAR(255) NULL,
                arxiv_id VARCHAR(50) NULL,
                doi VARCHAR(100) NULL,
                abstract TEXT NULL,
                key_findings JSON NULL,
                performance_claims JSON NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_capability (capability),
                INDEX idx_published_date (published_date DESC),
                INDEX idx_capability_date (capability, published_date DESC),
                INDEX idx_arxiv (arxiv_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            COMMENT='Research publications for tracking frontier capabilities'
        """, commit=True)
        logger.info("✓ research_publications table created")

        logger.info("Migration complete")

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(apply_migration())
