#!/usr/bin/env python3
"""
Backup Scheduler
================
Automated backup scheduling and management for TorinAI

Features:
- Scheduled database backups
- File system backups
- Incremental and full backup support
- Backup rotation and retention policies
- PostgreSQL-backed backup catalog
- Backup verification and restoration
"""

import logging
import asyncio
import json
import os
import tarfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any, List, Optional, Set
from datetime import datetime, timedelta
from enum import Enum
import hashlib

from core.database import get_database_manager

logger = logging.getLogger(__name__)


class BackupType(Enum):
    """Backup types"""
    FULL = "full"
    INCREMENTAL = "incremental"
    DIFFERENTIAL = "differential"


class BackupStatus(Enum):
    """Backup status"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    VERIFIED = "verified"


class BackupTarget(Enum):
    """Backup targets"""
    DATABASE = "database"
    FILES = "files"
    CONFIGURATION = "configuration"
    LOGS = "logs"
    MODELS = "models"
    ALL = "all"


@dataclass
class BackupConfig:
    """Backup configuration"""
    backup_id: str
    backup_type: BackupType
    targets: List[BackupTarget]
    schedule: str  # Cron-like schedule
    retention_days: int = 30
    compression: bool = True
    encryption: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BackupRecord:
    """Backup execution record"""
    record_id: str
    backup_id: str
    backup_type: BackupType
    targets: List[BackupTarget]
    start_time: datetime
    end_time: Optional[datetime] = None
    status: BackupStatus = BackupStatus.PENDING
    file_path: Optional[str] = None
    file_size: Optional[int] = None
    checksum: Optional[str] = None
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RestoreRequest:
    """Backup restore request"""
    request_id: str
    backup_record_id: str
    targets: List[BackupTarget]
    restore_path: Optional[str] = None
    overwrite: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


class BackupScheduler:
    """
    Backup Scheduler

    Manages automated backups:
    - Schedules periodic backups
    - Executes backup operations
    - Manages backup retention
    - Persists the backup catalog to PostgreSQL
    - Supports backup verification and restoration
    """

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}

        # Backup configurations
        self.backup_configs: Dict[str, BackupConfig] = {}
        self.backup_records: List[BackupRecord] = []

        # Scheduler state
        self.scheduler_active = False
        self.backup_tasks: Set[asyncio.Task] = set()

        # Paths — must be durable; /tmp is purged by the OS
        self.backup_dir = self.config.get(
            'backup_dir',
            os.getenv('TORIN_BACKUP_DIR', str(Path(__file__).resolve().parents[2] / 'data' / 'backups'))
        )
        self.data_dir = self.config.get('data_dir', './data')

        # Create backup directory
        os.makedirs(self.backup_dir, exist_ok=True)

        # Statistics
        self.stats = {
            'total_backups': 0,
            'successful_backups': 0,
            'failed_backups': 0,
            'total_size_bytes': 0,
            'last_backup_time': None
        }

        # Integration points
        self.database = None
        self.slack_notifier = None
        self._catalog_ready = False

        logger.info(f"BackupScheduler initialized (backup_dir={self.backup_dir})")

    async def _ensure_catalog(self) -> bool:
        """Create the backup catalog table and load existing records into memory."""
        if self._catalog_ready:
            return True

        try:
            db = get_database_manager()
            await db.execute_query(
                """
                CREATE TABLE IF NOT EXISTS backup_records (
                    record_id      VARCHAR(64) PRIMARY KEY,
                    backup_id      VARCHAR(64) NOT NULL,
                    backup_type    VARCHAR(32) NOT NULL,
                    targets        JSONB NOT NULL DEFAULT '[]'::jsonb,
                    status         VARCHAR(32) NOT NULL,
                    start_time     TIMESTAMP NOT NULL,
                    end_time       TIMESTAMP,
                    file_path      TEXT,
                    file_size      BIGINT,
                    checksum       VARCHAR(64),
                    error_message  TEXT,
                    metadata       JSONB NOT NULL DEFAULT '{}'::jsonb
                )
                """,
                commit=True
            )
            await db.execute_query(
                "CREATE INDEX IF NOT EXISTS idx_backup_records_start_time "
                "ON backup_records (start_time DESC)",
                commit=True
            )
            self._catalog_ready = True
            await self._load_records()
            return True

        except Exception as e:
            logger.error(f"Backup catalog unavailable: {e}")
            return False

    async def _load_records(self, limit: int = 500):
        """Rehydrate the in-memory catalog from Postgres so it survives restarts."""
        try:
            db = get_database_manager()
            rows = await db.execute_query(
                """
                SELECT record_id, backup_id, backup_type, targets, status, start_time,
                       end_time, file_path, file_size, checksum, error_message, metadata
                FROM backup_records
                ORDER BY start_time DESC
                LIMIT $1
                """,
                (limit,),
                fetch_all=True
            ) or []

            loaded = []
            for row in rows:
                r = dict(row)
                targets = r['targets'] if isinstance(r['targets'], list) else json.loads(r['targets'] or '[]')
                metadata = r['metadata'] if isinstance(r['metadata'], dict) else json.loads(r['metadata'] or '{}')
                loaded.append(BackupRecord(
                    record_id=r['record_id'],
                    backup_id=r['backup_id'],
                    backup_type=BackupType(r['backup_type']),
                    targets=[BackupTarget(t) for t in targets],
                    start_time=r['start_time'],
                    end_time=r['end_time'],
                    status=BackupStatus(r['status']),
                    file_path=r['file_path'],
                    file_size=r['file_size'],
                    checksum=r['checksum'],
                    error_message=r['error_message'],
                    metadata=metadata,
                ))

            loaded.reverse()
            self.backup_records = loaded
            logger.info(f"Loaded {len(loaded)} backup record(s) from catalog")

        except Exception as e:
            logger.error(f"Failed to load backup catalog: {e}")

    async def _persist_record(self, record: BackupRecord) -> bool:
        """Write a backup record to Postgres. Upserts so status transitions persist."""
        if not await self._ensure_catalog():
            return False

        try:
            db = get_database_manager()
            await db.execute_query(
                """
                INSERT INTO backup_records (
                    record_id, backup_id, backup_type, targets, status, start_time,
                    end_time, file_path, file_size, checksum, error_message, metadata
                ) VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7, $8, $9, $10, $11, $12::jsonb)
                ON CONFLICT (record_id) DO UPDATE SET
                    status        = EXCLUDED.status,
                    end_time      = EXCLUDED.end_time,
                    file_path     = EXCLUDED.file_path,
                    file_size     = EXCLUDED.file_size,
                    checksum      = EXCLUDED.checksum,
                    error_message = EXCLUDED.error_message,
                    metadata      = EXCLUDED.metadata
                """,
                (
                    record.record_id,
                    record.backup_id,
                    record.backup_type.value,
                    json.dumps([t.value for t in record.targets]),
                    record.status.value,
                    record.start_time,
                    record.end_time,
                    record.file_path,
                    record.file_size,
                    record.checksum,
                    record.error_message,
                    json.dumps(record.metadata or {}),
                ),
                commit=True
            )
            return True

        except Exception as e:
            logger.error(f"Failed to persist backup record {record.record_id}: {e}")
            return False

    async def _delete_record(self, record_id: str) -> bool:
        """Remove a record from the catalog when its archive is deleted."""
        try:
            db = get_database_manager()
            await db.execute_query(
                "DELETE FROM backup_records WHERE record_id = $1",
                (record_id,),
                commit=True
            )
            return True
        except Exception as e:
            logger.error(f"Failed to delete backup record {record_id}: {e}")
            return False

    async def start_scheduler(self):
        """Start backup scheduler"""
        if self.scheduler_active:
            logger.warning("Backup scheduler already active")
            return

        self.scheduler_active = True
        logger.info("Starting backup scheduler")

        # Start scheduler loop
        asyncio.create_task(self._scheduler_loop())

    async def stop_scheduler(self):
        """Stop backup scheduler"""
        self.scheduler_active = False

        # Cancel running tasks
        for task in self.backup_tasks:
            task.cancel()

        self.backup_tasks.clear()

        logger.info("Stopped backup scheduler")

    async def _scheduler_loop(self):
        """Scheduler loop"""
        while self.scheduler_active:
            try:
                # Check each backup config
                for config in self.backup_configs.values():
                    if await self._should_run_backup(config):
                        # Create backup task
                        task = asyncio.create_task(self._execute_backup(config))
                        self.backup_tasks.add(task)
                        task.add_done_callback(self.backup_tasks.discard)

                # Wait before next check
                await asyncio.sleep(60)  # Check every minute

            except Exception as e:
                logger.error(f"Error in scheduler loop: {e}")
                await asyncio.sleep(60)

    async def _should_run_backup(self, config: BackupConfig) -> bool:
        """Check if backup should run based on schedule"""
        try:
            from croniter import croniter
            from datetime import datetime

            cron = croniter(config.schedule, datetime.now())
            next_run = cron.get_next(datetime)

            recent_backups = [
                r for r in self.backup_records
                if r.backup_id == config.backup_id and
                r.status == BackupStatus.COMPLETED
            ]

            if not recent_backups:
                return True

            last_backup = max(recent_backups, key=lambda r: r.start_time)

            return datetime.now() >= next_run and (datetime.now() - last_backup.start_time).total_seconds() > 3600

        except ImportError:
            cutoff = datetime.now() - timedelta(hours=24)
            recent_backups = [
                r for r in self.backup_records
                if r.backup_id == config.backup_id and
                r.start_time >= cutoff and
                r.status == BackupStatus.COMPLETED
            ]
            return len(recent_backups) == 0

    async def _execute_backup(self, config: BackupConfig):
        """Execute backup"""
        record_id = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        record = BackupRecord(
            record_id=record_id,
            backup_id=config.backup_id,
            backup_type=config.backup_type,
            targets=config.targets,
            start_time=datetime.now(),
            status=BackupStatus.IN_PROGRESS
        )

        self.backup_records.append(record)
        self.stats['total_backups'] += 1

        logger.info(f"Starting backup: {record_id}")

        try:
            # Create backup file
            backup_file = await self._create_backup(config, record)

            # Calculate checksum
            checksum = await self._calculate_checksum(backup_file)

            # Update record
            record.file_path = backup_file
            record.file_size = os.path.getsize(backup_file)
            record.checksum = checksum
            record.status = BackupStatus.COMPLETED
            record.end_time = datetime.now()

            # Record the completed backup in the catalog
            await self._persist_record(record)

            # Clean old backups
            await self._cleanup_old_backups(config)

            self.stats['successful_backups'] += 1
            self.stats['total_size_bytes'] += record.file_size
            self.stats['last_backup_time'] = datetime.now()

            logger.info(f"Backup completed: {record_id} ({record.file_size} bytes)")

            # Notify success
            if self.slack_notifier:
                await self._notify_backup_success(record)

        except Exception as e:
            logger.error(f"Backup failed: {e}")

            record.status = BackupStatus.FAILED
            record.error_message = str(e)
            record.end_time = datetime.now()

            self.stats['failed_backups'] += 1

            # Notify failure
            if self.slack_notifier:
                await self._notify_backup_failure(record, str(e))

    async def _create_backup(
        self,
        config: BackupConfig,
        record: BackupRecord
    ) -> str:
        """
        Create backup file

        Args:
            config: Backup configuration
            record: Backup record

        Returns:
            Path to backup file
        """
        backup_filename = f"{record.record_id}.tar.gz"
        backup_path = os.path.join(self.backup_dir, backup_filename)

        with tarfile.open(backup_path, "w:gz") as tar:
            # Backup each target
            for target in config.targets:
                if target == BackupTarget.DATABASE:
                    await self._backup_database(tar)
                elif target == BackupTarget.FILES:
                    await self._backup_files(tar)
                elif target == BackupTarget.CONFIGURATION:
                    await self._backup_configuration(tar)
                elif target == BackupTarget.LOGS:
                    await self._backup_logs(tar)
                elif target == BackupTarget.MODELS:
                    await self._backup_models(tar)
                elif target == BackupTarget.ALL:
                    await self._backup_database(tar)
                    await self._backup_files(tar)
                    await self._backup_configuration(tar)

        return backup_path

    async def _backup_database(self, tar: tarfile.TarFile):
        """Backup database files"""
        db_path = os.path.join(self.data_dir, 'databases')
        if os.path.exists(db_path):
            tar.add(db_path, arcname='databases')

    async def _backup_files(self, tar: tarfile.TarFile):
        """Backup data files"""
        files_path = os.path.join(self.data_dir, 'files')
        if os.path.exists(files_path):
            tar.add(files_path, arcname='files')

    async def _backup_configuration(self, tar: tarfile.TarFile):
        """Backup configuration files"""
        config_path = './config'
        if os.path.exists(config_path):
            tar.add(config_path, arcname='config')

    async def _backup_logs(self, tar: tarfile.TarFile):
        """Backup log files"""
        logs_path = './logs'
        if os.path.exists(logs_path):
            tar.add(logs_path, arcname='logs')

    async def _backup_models(self, tar: tarfile.TarFile):
        """Backup model files"""
        models_path = os.path.join(self.data_dir, 'models')
        if os.path.exists(models_path):
            tar.add(models_path, arcname='models')

    async def _calculate_checksum(self, file_path: str) -> str:
        """Calculate file checksum"""
        sha256_hash = hashlib.sha256()

        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)

        return sha256_hash.hexdigest()

    async def _cleanup_old_backups(self, config: BackupConfig):
        """Clean up old backups based on retention policy"""
        cutoff = datetime.now() - timedelta(days=config.retention_days)

        # Get old backups
        old_backups = [
            r for r in self.backup_records
            if r.backup_id == config.backup_id and
            r.start_time < cutoff and
            r.status == BackupStatus.COMPLETED
        ]

        for record in old_backups:
            try:
                # Delete local file
                if record.file_path and os.path.exists(record.file_path):
                    os.remove(record.file_path)

                # Drop it from the catalog so the two stay consistent
                await self._delete_record(record.record_id)

                logger.info(f"Deleted old backup: {record.record_id}")

            except Exception as e:
                logger.error(f"Failed to delete old backup: {e}")

    async def _notify_backup_success(self, record: BackupRecord):
        """Notify backup success"""
        if not self.slack_notifier:
            return

        try:
            await self.slack_notifier.send_message(
                channel="ACTIVITY",
                title="Backup Completed",
                message=f"Backup {record.record_id} completed successfully",
                metadata={
                    'backup_id': record.backup_id,
                    'size_mb': round(record.file_size / 1024 / 1024, 2),
                    'duration_seconds': (
                        (record.end_time - record.start_time).total_seconds()
                        if record.end_time else 0
                    )
                }
            )
        except Exception as e:
            logger.error(f"Failed to send Slack notification: {e}")

    async def _notify_backup_failure(self, record: BackupRecord, error: str):
        """Notify backup failure"""
        if not self.slack_notifier:
            return

        try:
            await self.slack_notifier.send_message(
                channel="ALERTS",
                title="Backup Failed",
                message=f"Backup {record.record_id} failed: {error}",
                severity="high",
                metadata={
                    'backup_id': record.backup_id,
                    'error': error
                }
            )
        except Exception as e:
            logger.error(f"Failed to send Slack notification: {e}")

    async def add_backup_config(
        self,
        backup_id: str,
        backup_type: BackupType,
        targets: List[BackupTarget],
        schedule: str = "0 0 * * *",  # Daily at midnight
        retention_days: int = 30
    ) -> BackupConfig:
        """
        Add backup configuration

        Args:
            backup_id: Backup identifier
            backup_type: Backup type
            targets: Backup targets
            schedule: Cron-like schedule
            retention_days: Retention period

        Returns:
            Backup configuration
        """
        config = BackupConfig(
            backup_id=backup_id,
            backup_type=backup_type,
            targets=targets,
            schedule=schedule,
            retention_days=retention_days
        )

        self.backup_configs[backup_id] = config

        logger.info(f"Added backup configuration: {backup_id}")

        return config

    async def run_backup_now(
        self,
        backup_id: str
    ) -> Optional[BackupRecord]:
        """
        Run backup immediately

        Args:
            backup_id: Backup configuration ID

        Returns:
            Backup record or None
        """
        if backup_id not in self.backup_configs:
            logger.warning(f"Backup configuration not found: {backup_id}")
            return None

        config = self.backup_configs[backup_id]

        await self._execute_backup(config)

        # Return latest record
        return self.backup_records[-1] if self.backup_records else None

    async def restore_backup(
        self,
        request: RestoreRequest
    ) -> bool:
        """
        Restore from backup

        Args:
            request: Restore request

        Returns:
            True if restored successfully
        """
        # Find backup record
        record = None
        for r in self.backup_records:
            if r.record_id == request.backup_record_id:
                record = r
                break

        if not record:
            logger.error(f"Backup record not found: {request.backup_record_id}")
            return False

        logger.info(f"Restoring backup: {request.backup_record_id}")

        try:
            # Fall back to the newest usable archive rather than refusing to restore
            usable, skipped = await self._find_usable_archive(record)

            if not usable:
                logger.error(
                    f"No usable backup archive found. Checked {len(skipped)} record(s); "
                    f"every archive is missing or corrupted."
                )
                await self._notify_restore_unavailable(record, skipped)
                return False

            if usable.record_id != record.record_id:
                logger.warning(
                    f"Requested backup {record.record_id} is unusable "
                    f"({skipped[0][1] if skipped else 'unavailable'}). "
                    f"Restoring from {usable.record_id} ({usable.start_time}) instead."
                )
                await self._notify_restore_substituted(record, usable, skipped)

            # Extract backup
            restore_path = request.restore_path or self.data_dir

            with tarfile.open(usable.file_path, "r:gz") as tar:
                tar.extractall(restore_path)

            logger.info(
                f"Backup restored to: {restore_path} (from {usable.record_id})"
            )

            return True

        except Exception as e:
            logger.error(f"Restore failed: {e}")
            return False

    async def _find_usable_archive(self, preferred: BackupRecord):
        """Find the newest archive that exists and passes checksum.

        Tries the requested record first, then walks back through completed
        backups. Returns (usable_record_or_None, skipped) where skipped is a
        list of (record, reason) for everything rejected along the way.
        """
        candidates = [preferred] + [
            r for r in sorted(
                self.backup_records, key=lambda r: r.start_time, reverse=True
            )
            if r.record_id != preferred.record_id
            and r.status == BackupStatus.COMPLETED
        ]

        skipped = []
        for rec in candidates:
            if not rec.file_path or not os.path.exists(rec.file_path):
                skipped.append((rec, "archive missing"))
                await self._mark_archive_unusable(rec, "archive missing")
                continue

            if rec.checksum:
                checksum = await self._calculate_checksum(rec.file_path)
                if checksum != rec.checksum:
                    skipped.append((rec, "checksum mismatch"))
                    await self._mark_archive_unusable(rec, "checksum mismatch")
                    continue

            return rec, skipped

        return None, skipped

    async def _mark_archive_unusable(self, record: BackupRecord, reason: str):
        """Flag a catalog entry whose archive can no longer be used."""
        if record.metadata.get('archive_unusable') == reason:
            return

        record.metadata['archive_unusable'] = reason
        record.metadata['archive_checked_at'] = datetime.now().isoformat()
        await self._persist_record(record)
        logger.warning(f"Backup {record.record_id} marked unusable: {reason}")

    async def _notify_restore_substituted(
        self,
        requested: BackupRecord,
        used: BackupRecord,
        skipped: List
    ):
        """Notify that a restore succeeded from a different backup than requested."""
        if not self.slack_notifier:
            return

        try:
            await self.slack_notifier.send_message(
                channel="ALERTS",
                title="Restore Used a Fallback Backup",
                message=(
                    f"Requested backup {requested.record_id} was unusable. "
                    f"Restored from {used.record_id} ({used.start_time}) instead."
                ),
                severity="high",
                metadata={
                    'requested_record': requested.record_id,
                    'restored_record': used.record_id,
                    'restored_from': used.start_time.isoformat(),
                    'skipped': [
                        {'record_id': r.record_id, 'reason': why} for r, why in skipped
                    ],
                }
            )
        except Exception as e:
            logger.error(f"Failed to send Slack notification: {e}")

    async def _notify_restore_unavailable(self, requested: BackupRecord, skipped: List):
        """Notify that no usable archive exists at all."""
        if not self.slack_notifier:
            return

        try:
            await self.slack_notifier.send_message(
                channel="ALERTS",
                title="Restore Failed — No Usable Backup",
                message=(
                    f"Restore of {requested.record_id} failed. "
                    f"All {len(skipped)} candidate archive(s) are missing or corrupted."
                ),
                severity="critical",
                metadata={
                    'requested_record': requested.record_id,
                    'skipped': [
                        {'record_id': r.record_id, 'reason': why} for r, why in skipped
                    ],
                }
            )
        except Exception as e:
            logger.error(f"Failed to send Slack notification: {e}")

    async def verify_backup(
        self,
        record_id: str
    ) -> bool:
        """
        Verify backup integrity

        Args:
            record_id: Backup record ID

        Returns:
            True if verified successfully
        """
        # Find record
        record = None
        for r in self.backup_records:
            if r.record_id == record_id:
                record = r
                break

        if not record:
            logger.error(f"Backup record not found: {record_id}")
            return False

        try:
            # Check if file exists
            if not os.path.exists(record.file_path):
                logger.error(f"Backup file not found: {record.file_path}")
                return False

            # Verify checksum
            checksum = await self._calculate_checksum(record.file_path)

            if checksum == record.checksum:
                record.status = BackupStatus.VERIFIED
                logger.info(f"Backup verified: {record_id}")
                return True
            else:
                logger.error(f"Checksum mismatch for backup: {record_id}")
                return False

        except Exception as e:
            logger.error(f"Verification failed: {e}")
            return False

    async def get_backup_records(
        self,
        backup_id: Optional[str] = None,
        status: Optional[BackupStatus] = None
    ) -> List[BackupRecord]:
        """
        Get backup records

        Args:
            backup_id: Filter by backup ID
            status: Filter by status

        Returns:
            List of backup records
        """
        records = self.backup_records

        if backup_id:
            records = [r for r in records if r.backup_id == backup_id]

        if status:
            records = [r for r in records if r.status == status]

        return records

    async def get_statistics(self) -> Dict[str, Any]:
        """Get backup statistics"""
        return {
            **self.stats,
            'total_configs': len(self.backup_configs),
            'total_records': len(self.backup_records),
            'scheduler_active': self.scheduler_active,
            'success_rate': (
                self.stats['successful_backups'] / self.stats['total_backups'] * 100
                if self.stats['total_backups'] > 0 else 100.0
            )
        }

    def set_database(self, database):
        """Set database integration"""
        self.database = database
        logger.info("Database integration configured")

    def set_slack_notifier(self, slack_notifier):
        """Set Slack notifier integration"""
        self.slack_notifier = slack_notifier
        logger.info("Slack notifier integration configured")


# Global instance
_backup_scheduler: Optional[BackupScheduler] = None


def get_backup_scheduler() -> BackupScheduler:
    """Get global backup scheduler instance"""
    global _backup_scheduler
    if _backup_scheduler is None:
        _backup_scheduler = BackupScheduler()
    return _backup_scheduler


# Test usage
async def main():
    """Test backup scheduler"""
    logging.basicConfig(level=logging.INFO)

    scheduler = get_backup_scheduler()

    # Add backup configuration
    await scheduler.add_backup_config(
        backup_id="daily_backup",
        backup_type=BackupType.FULL,
        targets=[BackupTarget.DATABASE, BackupTarget.CONFIGURATION],
        schedule="0 0 * * *",
        retention_days=7
    )

    # Run backup
    record = await scheduler.run_backup_now("daily_backup")

    print(f"\n{'='*60}")
    print("Backup Scheduler Test")
    print(f"{'='*60}")
    print(f"Backup ID: {record.record_id if record else 'N/A'}")
    print(f"Status: {record.status.value if record else 'N/A'}")
    print(f"Size: {record.file_size if record else 0} bytes")

    stats = await scheduler.get_statistics()
    print(f"\nStatistics: {stats}")


if __name__ == "__main__":
    asyncio.run(main())
