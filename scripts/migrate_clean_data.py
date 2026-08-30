#!/usr/bin/env python3
"""
Clean Data Migration: MySQL → PostgreSQL + pgvector
====================================================

Migrates ONLY validated, non-corrupted data from MySQL to PostgreSQL.

User Constraint: "cannot rely on what's in mysql because it is completely messed up"
Strategy: Fresh schema with selective clean data migration only

What to Migrate:
- Governance laws (5 laws - immutable seed data)
- Validated directives (governance_validated = TRUE only)
- Recent memory (last 7 days with embeddings)
- Active experiments (status = 'running')

What to Skip:
- Corrupted logs (operation_logs, auth_logs, system_logs)
- Failed experiments
- Unvalidated directives
- Old memory (8+ days)
- Test data (test_sessions, test_results)
"""

import asyncio
import json
import sys
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.database.unified_database_mysql import TorinUnifiedDatabaseMySQL
from core.database import TorinUnifiedDatabase  # PostgreSQL (aliased in __init__.py)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class DataMigrator:
    """Migrates clean data from MySQL to PostgreSQL"""

    def __init__(self):
        self.mysql_db = TorinUnifiedDatabaseMySQL()
        self.postgres_db = TorinUnifiedDatabase()  # PostgreSQL

        # Migration statistics
        self.stats = {
            'governance_laws': 0,
            'internal_directives': 0,
            'directive_applications': 0,
            'memories_hot': 0,
            'memories_cold': 0,
            'active_experiments': 0,
            'errors': 0
        }

    async def initialize(self):
        """Initialize both database connections"""
        logger.info("Initializing database connections...")

        await self.mysql_db.initialize()
        logger.info("✓ MySQL connected")

        await self.postgres_db.initialize()
        logger.info("✓ PostgreSQL connected")

    async def close(self):
        """Close database connections"""
        await self.mysql_db.close()
        await self.postgres_db.close()
        logger.info("Database connections closed")

    async def migrate_governance_laws(self) -> int:
        """
        Migrate governance laws (immutable seed data)

        Note: These should already be seeded in postgres_schemas.sql,
        but we'll verify and update if needed.
        """
        logger.info("\n=== Migrating Governance Laws ===")

        try:
            # Fetch all governance laws from MySQL
            laws = await self.mysql_db.execute_query(
                "SELECT * FROM governance_laws ORDER BY law_number",
                fetch_all=True
            )

            if not laws:
                logger.warning("No governance laws found in MySQL")
                return 0

            migrated = 0

            for law in laws:
                try:
                    # Check if law already exists in Postgres (from seed data)
                    existing = await self.postgres_db.execute_query(
                        "SELECT law_id FROM unified.governance_laws WHERE law_id = $1",
                        (law['law_id'],),
                        fetch_one=True
                    )

                    if existing:
                        logger.debug(f"Law {law['law_number']} already exists in PostgreSQL (from seed data)")
                        migrated += 1
                        continue

                    # Insert law into PostgreSQL
                    await self.postgres_db.execute_query(
                        """
                        INSERT INTO unified.governance_laws
                        (law_id, law_number, law_name, law_description, requirements,
                         created_at, immutable)
                        VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7)
                        """,
                        (
                            law['law_id'],
                            law['law_number'],
                            law['law_name'],
                            law['law_description'],
                            json.dumps(law['requirements']) if isinstance(law['requirements'], (dict, list)) else law['requirements'],
                            law['created_at'],
                            law.get('immutable', True)
                        ),
                        commit=True
                    )

                    migrated += 1
                    logger.info(f"✓ Migrated Law {law['law_number']}: {law['law_name']}")

                except Exception as e:
                    logger.error(f"Failed to migrate law {law.get('law_id')}: {e}")
                    self.stats['errors'] += 1

            self.stats['governance_laws'] = migrated
            logger.info(f"Governance Laws: {migrated} migrated")
            return migrated

        except Exception as e:
            logger.error(f"Governance laws migration failed: {e}")
            self.stats['errors'] += 1
            return 0

    async def migrate_validated_directives(self) -> int:
        """
        Migrate ONLY validated directives (governance_validated = TRUE)

        Skips unvalidated/draft directives as they may be corrupted.
        """
        logger.info("\n=== Migrating Validated Directives ===")

        try:
            # Fetch only validated directives from MySQL
            directives = await self.mysql_db.execute_query(
                """
                SELECT * FROM internal_directives
                WHERE governance_validated = TRUE
                ORDER BY created_at DESC
                """,
                fetch_all=True
            )

            if not directives:
                logger.warning("No validated directives found in MySQL")
                return 0

            migrated = 0

            for directive in directives:
                try:
                    # Check if directive already exists
                    existing = await self.postgres_db.execute_query(
                        "SELECT directive_id FROM unified.internal_directives WHERE directive_id = $1",
                        (directive['directive_id'],),
                        fetch_one=True
                    )

                    if existing:
                        logger.debug(f"Directive {directive['directive_id']} already exists, skipping")
                        continue

                    # Insert directive into PostgreSQL
                    await self.postgres_db.execute_query(
                        """
                        INSERT INTO unified.internal_directives
                        (directive_id, directive_name, directive_category, directive_type,
                         status, directive_parameters, directive_rationale, directive_results,
                         governance_validated, validation_details, total_applications,
                         successful_applications, failed_applications, average_confidence_score,
                         last_applied_at, created_at, updated_at, deprecated_at, replaced_by_directive_id)
                        VALUES ($1, $2, $3, $4, $5::unified.directive_status, $6::jsonb, $7, $8::jsonb,
                                $9, $10::jsonb, $11, $12, $13, $14, $15, $16, $17, $18, $19)
                        """,
                        (
                            directive['directive_id'],
                            directive['directive_name'],
                            directive['directive_category'],
                            directive['directive_type'],
                            directive['status'],
                            json.dumps(directive['directive_parameters']) if isinstance(directive['directive_parameters'], (dict, list)) else directive['directive_parameters'],
                            directive.get('directive_rationale'),
                            json.dumps(directive['directive_results']) if isinstance(directive.get('directive_results'), (dict, list)) else directive.get('directive_results'),
                            directive['governance_validated'],
                            json.dumps(directive['validation_details']) if isinstance(directive.get('validation_details'), (dict, list)) else directive.get('validation_details'),
                            directive.get('total_applications', 0),
                            directive.get('successful_applications', 0),
                            directive.get('failed_applications', 0),
                            directive.get('average_confidence_score'),
                            directive.get('last_applied_at'),
                            directive['created_at'],
                            directive.get('updated_at', directive['created_at']),
                            directive.get('deprecated_at'),
                            directive.get('replaced_by_directive_id')
                        ),
                        commit=True
                    )

                    migrated += 1
                    logger.info(f"✓ Migrated directive: {directive['directive_name']} (validated)")

                except Exception as e:
                    logger.error(f"Failed to migrate directive {directive.get('directive_id')}: {e}")
                    self.stats['errors'] += 1

            self.stats['internal_directives'] = migrated
            logger.info(f"Validated Directives: {migrated} migrated")
            return migrated

        except Exception as e:
            logger.error(f"Directive migration failed: {e}")
            self.stats['errors'] += 1
            return 0

    async def migrate_directive_applications(self) -> int:
        """
        Migrate directive applications for validated directives only
        """
        logger.info("\n=== Migrating Directive Applications ===")

        try:
            # Get list of validated directives in Postgres
            validated_directives = await self.postgres_db.execute_query(
                "SELECT directive_id FROM unified.internal_directives",
                fetch_all=True
            )

            if not validated_directives:
                logger.warning("No directives in PostgreSQL to migrate applications for")
                return 0

            directive_ids = [d['directive_id'] for d in validated_directives]

            # Fetch applications for these directives from MySQL
            placeholders = ','.join(['%s'] * len(directive_ids))
            applications = await self.mysql_db.execute_query(
                f"""
                SELECT * FROM directive_applications
                WHERE directive_id IN ({placeholders})
                ORDER BY applied_at DESC
                LIMIT 1000
                """,
                tuple(directive_ids),
                fetch_all=True
            )

            if not applications:
                logger.info("No applications found for validated directives")
                return 0

            migrated = 0

            for app in applications:
                try:
                    # Insert application into PostgreSQL
                    await self.postgres_db.execute_query(
                        """
                        INSERT INTO unified.directive_applications
                        (application_id, directive_id, applied_context, application_result,
                         success, confidence_score, applied_at, duration_ms, applied_by_component)
                        VALUES ($1, $2, $3::jsonb, $4::jsonb, $5, $6, $7, $8, $9)
                        ON CONFLICT (application_id) DO NOTHING
                        """,
                        (
                            app['application_id'],
                            app['directive_id'],
                            json.dumps(app['applied_context']) if isinstance(app.get('applied_context'), (dict, list)) else app.get('applied_context'),
                            json.dumps(app['application_result']) if isinstance(app.get('application_result'), (dict, list)) else app.get('application_result'),
                            app.get('success'),
                            app.get('confidence_score'),
                            app['applied_at'],
                            app.get('duration_ms'),
                            app.get('applied_by_component')
                        ),
                        commit=True
                    )

                    migrated += 1

                except Exception as e:
                    logger.error(f"Failed to migrate application {app.get('application_id')}: {e}")
                    self.stats['errors'] += 1

            self.stats['directive_applications'] = migrated
            logger.info(f"Directive Applications: {migrated} migrated")
            return migrated

        except Exception as e:
            logger.error(f"Application migration failed: {e}")
            self.stats['errors'] += 1
            return 0

    async def migrate_recent_memory(self, days: int = 7) -> int:
        """
        Migrate recent memory (last N days) with embeddings

        Only migrates memories with valid embeddings for semantic search.
        """
        logger.info(f"\n=== Migrating Recent Memory (last {days} days) ===")

        try:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)

            # Fetch recent memories from MySQL hot tier
            memories = await self.mysql_db.execute_query(
                """
                SELECT * FROM memory_hot
                WHERE created_at >= %s
                AND embeddings IS NOT NULL
                ORDER BY created_at DESC
                LIMIT 10000
                """,
                (cutoff_date,),
                use_hot_tier=True,
                fetch_all=True
            )

            if not memories:
                logger.info("No recent memories with embeddings found in MySQL")
                return 0

            migrated = 0

            for memory in memories:
                try:
                    # Parse embedding from JSON
                    embedding = None
                    if memory.get('embeddings'):
                        if isinstance(memory['embeddings'], str):
                            embedding = json.loads(memory['embeddings'])
                        else:
                            embedding = memory['embeddings']

                    # Validate embedding dimensions (should be 384 for all-MiniLM-L6-v2)
                    if embedding and len(embedding) != 384:
                        logger.warning(f"Invalid embedding dimensions for {memory['memory_id']}: {len(embedding)} (expected 384)")
                        continue

                    # Insert memory into PostgreSQL with vector embedding
                    await self.postgres_db.execute_query(
                        """
                        INSERT INTO memory_hot.memory_hot
                        (memory_id, memory_type, content, embedding, importance_score,
                         access_count, last_accessed, created_at, tags, related_memories)
                        VALUES ($1, $2, $3::jsonb, $4::vector, $5, $6, $7, $8, $9::jsonb, $10::jsonb)
                        ON CONFLICT (memory_id) DO NOTHING
                        """,
                        (
                            memory['memory_id'],
                            memory['memory_type'],
                            json.dumps(memory['content']) if isinstance(memory.get('content'), (dict, list)) else memory.get('content'),
                            embedding,
                            memory.get('importance_score'),
                            memory.get('access_count', 0),
                            memory.get('last_accessed_at'),  # MySQL column name
                            memory['created_at'],
                            json.dumps(memory.get('tags', [])) if isinstance(memory.get('tags'), list) else memory.get('tags'),
                            json.dumps(memory.get('related_memories', [])) if isinstance(memory.get('related_memories'), list) else memory.get('related_memories')
                        ),
                        use_hot_tier=True,
                        commit=True
                    )

                    migrated += 1

                    if migrated % 100 == 0:
                        logger.info(f"Progress: {migrated} memories migrated...")

                except Exception as e:
                    logger.error(f"Failed to migrate memory {memory.get('memory_id')}: {e}")
                    self.stats['errors'] += 1

            self.stats['memories_hot'] = migrated
            logger.info(f"Recent Memories: {migrated} migrated with embeddings")
            return migrated

        except Exception as e:
            logger.error(f"Memory migration failed: {e}")
            self.stats['errors'] += 1
            return 0

    async def migrate_active_experiments(self) -> int:
        """
        Migrate ONLY active chaos experiments (status = 'running')

        Skips failed/completed experiments.
        """
        logger.info("\n=== Migrating Active Chaos Experiments ===")

        try:
            # Fetch active experiments from MySQL
            experiments = await self.mysql_db.execute_query(
                """
                SELECT * FROM chaos_experiments
                WHERE status = 'running'
                ORDER BY started_at DESC
                """,
                fetch_all=True
            )

            if not experiments:
                logger.info("No active chaos experiments found in MySQL")
                return 0

            migrated = 0

            for exp in experiments:
                try:
                    # Insert experiment into PostgreSQL
                    await self.postgres_db.execute_query(
                        """
                        INSERT INTO unified.chaos_experiments
                        (experiment_id, experiment_type, target_component, config,
                         status, started_at, ended_at, duration_seconds, results, metadata)
                        VALUES ($1, $2, $3, $4::jsonb, $5::unified.experiment_status, $6, $7, $8, $9::jsonb, $10::jsonb)
                        ON CONFLICT (experiment_id) DO NOTHING
                        """,
                        (
                            exp['experiment_id'],
                            exp['experiment_type'],
                            exp['target_component'],
                            json.dumps(exp['config']) if isinstance(exp.get('config'), (dict, list)) else exp.get('config'),
                            exp['status'],
                            exp['started_at'],
                            exp.get('ended_at'),
                            exp.get('duration_seconds'),
                            json.dumps(exp.get('results')) if isinstance(exp.get('results'), (dict, list)) else exp.get('results'),
                            json.dumps(exp.get('metadata')) if isinstance(exp.get('metadata'), (dict, list)) else exp.get('metadata')
                        ),
                        commit=True
                    )

                    migrated += 1
                    logger.info(f"✓ Migrated active experiment: {exp['experiment_id']}")

                except Exception as e:
                    logger.error(f"Failed to migrate experiment {exp.get('experiment_id')}: {e}")
                    self.stats['errors'] += 1

            self.stats['active_experiments'] = migrated
            logger.info(f"Active Experiments: {migrated} migrated")
            return migrated

        except Exception as e:
            logger.error(f"Experiment migration failed: {e}")
            self.stats['errors'] += 1
            return 0

    async def verify_migration(self):
        """Verify migrated data integrity"""
        logger.info("\n=== Verifying Migration ===")

        try:
            # Check governance laws
            laws_count = await self.postgres_db.execute_query(
                "SELECT COUNT(*) as count FROM unified.governance_laws",
                fetch_one=True
            )
            logger.info(f"✓ Governance Laws: {laws_count['count']} in PostgreSQL")

            # Check directives
            directives_count = await self.postgres_db.execute_query(
                "SELECT COUNT(*) as count FROM unified.internal_directives WHERE governance_validated = TRUE",
                fetch_one=True
            )
            logger.info(f"✓ Validated Directives: {directives_count['count']} in PostgreSQL")

            # Check memories with embeddings
            memories_count = await self.postgres_db.execute_query(
                "SELECT COUNT(*) as count FROM memory_hot.memory_hot WHERE embedding IS NOT NULL",
                use_hot_tier=True,
                fetch_one=True
            )
            logger.info(f"✓ Memories with Embeddings: {memories_count['count']} in PostgreSQL")

            # Check HNSW index exists
            index_check = await self.postgres_db.execute_query(
                """
                SELECT indexname FROM pg_indexes
                WHERE schemaname = 'memory_hot'
                AND tablename = 'memory_hot'
                AND indexdef LIKE '%hnsw%'
                """,
                fetch_all=True
            )

            if index_check:
                logger.info(f"✓ HNSW Index: {index_check[0]['indexname']} exists")
            else:
                logger.warning("⚠ HNSW index not found - semantic search may be slow")

        except Exception as e:
            logger.error(f"Verification failed: {e}")

    def print_summary(self):
        """Print migration summary"""
        logger.info("\n" + "="*60)
        logger.info("MIGRATION SUMMARY")
        logger.info("="*60)
        logger.info(f"Governance Laws:         {self.stats['governance_laws']}")
        logger.info(f"Validated Directives:    {self.stats['internal_directives']}")
        logger.info(f"Directive Applications:  {self.stats['directive_applications']}")
        logger.info(f"Recent Memories:         {self.stats['memories_hot']}")
        logger.info(f"Active Experiments:      {self.stats['active_experiments']}")
        logger.info(f"Errors:                  {self.stats['errors']}")
        logger.info("="*60)

        total_migrated = (
            self.stats['governance_laws'] +
            self.stats['internal_directives'] +
            self.stats['directive_applications'] +
            self.stats['memories_hot'] +
            self.stats['active_experiments']
        )

        logger.info(f"Total Records Migrated:  {total_migrated}")
        logger.info("="*60)


async def main():
    """Run clean data migration"""
    logger.info("="*60)
    logger.info("CLEAN DATA MIGRATION: MySQL → PostgreSQL")
    logger.info("="*60)
    logger.info("Strategy: Fresh schema with selective clean data only")
    logger.info("User Constraint: Cannot rely on MySQL data - it's messed up")
    logger.info("="*60)

    migrator = DataMigrator()

    try:
        # Initialize connections
        await migrator.initialize()

        # Migrate clean data in order
        await migrator.migrate_governance_laws()
        await migrator.migrate_validated_directives()
        await migrator.migrate_directive_applications()
        await migrator.migrate_recent_memory(days=7)
        await migrator.migrate_active_experiments()

        # Verify migration
        await migrator.verify_migration()

        # Print summary
        migrator.print_summary()

        logger.info("\n✅ Clean data migration completed successfully!")

    except Exception as e:
        logger.error(f"\n❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    finally:
        await migrator.close()


if __name__ == "__main__":
    asyncio.run(main())
