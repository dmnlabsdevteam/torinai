#!/usr/bin/env python3
"""
Apply Adaptive Learning Database Views
======================================
Creates the tool_category_affinity and recent_tool_usage views
for the adaptive tool learning system.

Run this script after the database has been initialized:
    python migrations/apply_adaptive_learning_views.py
"""

import asyncio
import logging
from pathlib import Path
import sys

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.database.unified_database_mysql import TorinUnifiedDatabaseMySQL

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def apply_views():
    """Apply adaptive learning views to database"""
    db = TorinUnifiedDatabaseMySQL()

    try:
        await db.initialize()
        logger.info("✓ Database connected")

        # Read SQL file
        sql_file = Path(__file__).parent / "create_adaptive_learning_views.sql"
        with open(sql_file, 'r') as f:
            sql_content = f.read()

        # Split into individual statements
        statements = [s.strip() for s in sql_content.split(';') if s.strip() and not s.strip().startswith('--')]

        # Execute each statement
        for i, statement in enumerate(statements, 1):
            # Skip USE statements (already connected to correct DB)
            if statement.upper().startswith('USE'):
                continue

            try:
                await db.execute_query(statement, commit=True)
                logger.info(f"✓ Statement {i}/{len(statements)} executed")
            except Exception as e:
                logger.error(f"✗ Statement {i} failed: {e}")
                logger.error(f"Statement: {statement[:200]}...")

        logger.info("✓ Adaptive learning views applied successfully")

        # Verify views exist
        result = await db.execute_query(
            "SELECT COUNT(*) as count FROM information_schema.VIEWS WHERE TABLE_SCHEMA = 'torinai_unified' AND TABLE_NAME IN ('tool_category_affinity', 'recent_tool_usage')"
        )

        if result and result[0]['count'] == 2:
            logger.info("✓ Both views verified: tool_category_affinity, recent_tool_usage")
        else:
            logger.warning(f"⚠ View verification: found {result[0]['count'] if result else 0}/2 views")

    except Exception as e:
        logger.error(f"✗ Migration failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await db.close()
        logger.info("Database connection closed")


if __name__ == "__main__":
    print("=" * 80)
    print("Applying Adaptive Learning Views")
    print("=" * 80)
    asyncio.run(apply_views())
    print("=" * 80)
    print("Migration complete")
    print("=" * 80)
