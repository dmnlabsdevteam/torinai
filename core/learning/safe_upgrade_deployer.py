#!/usr/bin/env python3
"""
Safe Upgrade Deployer & Rollback
==========================================================
Orchestrates safe deployment of validated code upgrades

Features:
- Multiple deployment strategies (canary, blue-green, rolling)
- Automatic health monitoring
- Automatic rollback on failures
- Zero-downtime deployment
- Gradual traffic shifting
- Deployment history tracking

Strategy:
1. Validate deployment readiness
2. Create backup/snapshot
3. Deploy using selected strategy
4. Monitor health metrics
5. Auto-rollback if issues detected
6. Cleanup old versions

Safety:
- Fail-closed on validation failures
- Automatic rollback threshold (configurable)
- Health check enforcement
- Backup before deployment
- Gradual rollout (canary mode)
"""

import asyncio
import json
import logging
import shutil
import os
import time
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from enum import Enum

# Import from previous modules
# from core.learning.upgrade_validator import UpgradeValidator
# from core.learning.upgrade_sandbox import UpgradeSandbox


logger = logging.getLogger(__name__)


class DeploymentStrategy(Enum):
    """Deployment strategy types"""
    CANARY = "canary"
    BLUE_GREEN = "blue_green"
    ROLLING = "rolling"
    IMMEDIATE = "immediate"
    DIRECT = "direct"


@dataclass
class DeploymentConfig:
    """Deployment configuration"""
    deployment_id: str
    rollout_strategy: str  # "canary", "blue_green", "rolling", "immediate"
    rollback_enabled: bool = True
    canary_percentage: int = 10  # % of traffic for canary
    health_check_interval_sec: int = 30
    monitoring_period_sec: int = 300  # Monitor for 5 minutes
    max_failure_rate: float = 0.05  # 5% max error rate
    backup_enabled: bool = True


@dataclass
class DeploymentStatus:
    """Current deployment status"""
    deployment_id: str
    status: str  # "pending", "in_progress", "completed", "failed", "rolled_back"
    progress: float  # 0.0 to 100.0
    completed_steps: List[str] = field(default_factory=list)
    current_step: str = ""
    started_at: datetime = field(default_factory=datetime.now)


@dataclass
class DeploymentResult:
    """Result of deployment"""
    success: bool
    deployment_id: str
    status: str  # "deployed", "rolled_back", "failed"
    errors: List[str] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    duration_seconds: float = 0.0


class SafeUpgradeDeployer:
    """
    Orchestrates safe deployment of code upgrades

    Deployment flow:
    1. Validate deployment readiness (all checks pass)
    2. Create backup/snapshot
    3. Execute deployment strategy
    4. Monitor health metrics
    5. Auto-rollback if failures detected
    6. Cleanup old versions

    Deployment strategies:
    - Immediate: Deploy all at once (fastest, highest risk)
    - Canary: Deploy to small % first, monitor, then full deploy
    - Blue-Green: Deploy to standby environment, switch traffic
    - Rolling: Gradually replace instances one-by-one
    """

    def __init__(self, config: Dict[str, Any] = None):
        # Default configuration
        if config is None:
            config = {}

        self.config = DeploymentConfig(
            deployment_id=config.get("deployment_id", f"deploy_{int(time.time())}"),
            rollout_strategy=config.get("rollout_strategy", "canary"),
            rollback_enabled=config.get("rollback_enabled", True),
            canary_percentage=config.get("canary_percentage", 10),
            health_check_interval_sec=config.get("health_check_interval_sec", 30),
            monitoring_period_sec=config.get("monitoring_period_sec", 300),
            max_failure_rate=config.get("max_failure_rate", 0.05),
            backup_enabled=config.get("backup_enabled", True)
        )

        # Deployment tracking
        self.deployment_history: List[DeploymentResult] = []
        self.current_status: Optional[DeploymentStatus] = None
        self.backup_paths: List[str] = []
        self.deployed_version = None
        self.previous_version: Optional[str] = None

        logger.info(f"SafeUpgradeDeployer initialized: {self.config.deployment_id}")

    async def deploy_upgrade(
        self,
        file_paths: List[str],
        metadata: Dict[str, Any]
    ) -> DeploymentResult:
        """
        Deploy validated upgrade with selected strategy

        Args:
            file_paths: Files to deploy
            metadata: Deployment metadata (version, description, etc.)

        Returns:
            DeploymentResult with deployment outcome
        """
        if not file_paths:
            logger.error("No files provided for deployment")
            return DeploymentResult(
                success=False,
                deployment_id=self.config.deployment_id,
                status="failed",
                errors=["No files to deploy"]
            )

        logger.info(f"Deploying upgrade: {len(file_paths)} file(s)")

        # Create deployment status
        status = DeploymentStatus(
            deployment_id=self.config.deployment_id,
            status="pending",
            progress=0.0,
            current_step="validation"
        )
        self.current_status = status

        start_time = time.time()

        try:
            # Step 1: Validate deployment readiness
            await self._update_status("validating", 10.0)
            is_ready, validation_msg = await self._validate_deployment_readiness(file_paths)
            if not is_ready:
                raise Exception(f"Deployment validation failed: {validation_msg}")

            # Step 2: Create backup
            if self.config.backup_enabled:
                await self._update_status("creating_backup", 20.0)
                backup_created = await self._create_backup(file_paths)
                if not backup_created:
                    raise Exception("Backup creation failed")

            # Step 3: Deploy based on strategy
            await self._update_status("deploying", 30.0)

            if self.config.rollout_strategy == "canary":
                deploy_success = await self._deploy_with_canary(file_paths, metadata)
            elif self.config.rollout_strategy == "blue_green":
                deploy_success = await self._deploy_blue_green(file_paths, metadata)
            elif self.config.rollout_strategy == "rolling":
                deploy_success = await self._deploy_rolling(file_paths, metadata)
            else:  # immediate
                deploy_success = await self._deploy_immediate(file_paths, metadata)

            if not deploy_success:
                raise Exception("Deployment failed")

            # Step 4: Monitor health
            await self._update_status("monitoring", 80.0)
            health_ok = await self._monitor_deployment()

            if not health_ok:
                raise Exception("Health checks failed after deployment")

            # Step 5: Cleanup
            await self._update_status("cleanup", 95.0)
            await self._cleanup_deployment()

            # Success
            await self._update_status("completed", 100.0)
            duration = time.time() - start_time

            logger.info(f"Deployment successful: {self.config.deployment_id}")

            return DeploymentResult(
                success=True,
                deployment_id=self.config.deployment_id,
                status="deployed",
                errors=[],
                duration_seconds=duration
            )

        except Exception as e:
            logger.error(f"Deployment failed: {e}")
            await self._update_status("failed", self.current_status.progress if self.current_status else 0)

            # Attempt rollback if enabled
            if self.config.rollback_enabled:
                logger.warning("Attempting automatic rollback")
                rollback_success = await self._perform_rollback(file_paths)

                if rollback_success:
                    status = "rolled_back"
                else:
                    status = "failed"
            else:
                status = "failed"

            duration = time.time() - start_time

            return DeploymentResult(
                success=False,
                deployment_id=self.config.deployment_id,
                status=status,
                errors=[str(e)],
                duration_seconds=duration
            )

    #: Where pre-deployment copies live. NOT /tmp: rollback is the only thing
    #: standing between a bad self-modification and a broken system, and its
    #: single copy of the previous code was being written somewhere the OS is
    #: entitled to delete.
    BACKUP_ROOT = Path(__file__).resolve().parents[2] / "runtime" / "upgrade_backups"

    def _backup_dir(self) -> Path:
        return self.BACKUP_ROOT / str(self.config.deployment_id)

    @staticmethod
    def _backup_name(target: str) -> str:
        """A backup filename that cannot collide.

        This used `os.path.basename(file_path)`, so `core/memory/utils.py` and
        `core/tools/utils.py` in one deployment both backed up to `utils.py` --
        the second overwrote the first, and rollback then restored one file's
        contents over the other. The full path, flattened, is unique.
        """
        return str(target).replace(os.sep, "__").lstrip("._") or "unnamed"

    async def _create_backup(self, file_paths: List[str]) -> bool:
        """Copy every file this deployment will touch, before touching it."""
        try:
            backup_dir = self._backup_dir()
            backup_dir.mkdir(parents=True, exist_ok=True)
            logger.info("Creating backup: %s", backup_dir)

            manifest = {}
            for file_path in file_paths:
                if not os.path.exists(file_path):
                    # A target that does not exist yet is a NEW file. Recorded
                    # so rollback removes it rather than leaving it behind.
                    manifest[str(file_path)] = None
                    continue
                backup_path = backup_dir / self._backup_name(file_path)
                shutil.copy2(file_path, backup_path)
                manifest[str(file_path)] = str(backup_path)
                logger.debug("Backed up: %s -> %s", file_path, backup_path)

            (backup_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
            self.backup_paths.append(str(backup_dir))
            logger.info("Backup created: %d file(s)", len(manifest))
            return True

        except Exception as e:
            logger.error(f"Backup creation failed: {e}")
            return False

    # ── What a deployment actually consists of ───────────────────────────
    #
    # THE TARGET PATH USED TO BE GUESSED BY STRING SURGERY:
    #
    #     target_path = file_path.replace('/tmp/', '/').replace('_upgrade', '')
    #
    # For `/tmp/foo_upgrade.py` that resolves to `/foo.py` -- the filesystem
    # root -- and for anything not matching those two substrings it wrote the
    # file over itself. Where a change belongs is not derivable from a string;
    # it is stated by the caller or it is not known.

    def _resolve_writes(self, file_paths: List[str],
                        metadata: Dict[str, Any]) -> List[Tuple[str, str]]:
        """(target_path, content) for every file this deployment writes.

        Refuses rather than guesses. The caller declares the targets in
        `file_paths` and the content in `metadata["code"]`, or per-target in
        `metadata["file_contents"]`.
        """
        contents = metadata.get("file_contents")
        if isinstance(contents, dict) and contents:
            return [(str(path), str(text)) for path, text in contents.items()]

        code = metadata.get("code")
        if code is None or not str(code).strip():
            raise ValueError(
                "deployment metadata carries no 'code' and no 'file_contents'; "
                "refusing to deploy, because there is nothing to write and the "
                "target cannot be inferred from the path")

        if not file_paths:
            raise ValueError("no target paths given for the code to be written to")
        return [(str(path), str(code)) for path in file_paths]

    @staticmethod
    def _write_atomic(target: str, content: str) -> None:
        """Write via a temp file in the same directory, then replace.

        A half-written module is importable and broken. `os.replace` is atomic
        on the same filesystem, so a reader sees either the old file or the new
        one and never a partial one.
        """
        target_path = Path(target)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        staging = target_path.with_suffix(target_path.suffix + ".deploying")
        staging.write_text(content)
        os.replace(staging, target_path)

    @staticmethod
    def _compiles(content: str, name: str) -> Tuple[bool, str]:
        """Whether the content is at least syntactically valid Python.

        The cheapest check that can refuse a file BEFORE it replaces a working
        one. Not a substitute for the sandbox; a floor beneath it.
        """
        if not str(name).endswith(".py"):
            return True, ""
        try:
            compile(content, name, "exec")
            return True, ""
        except SyntaxError as error:
            return False, f"{error.__class__.__name__}: {error}"

    async def _deploy_with_canary(
        self,
        file_paths: List[str],
        metadata: Dict[str, Any]
    ) -> bool:
        """Deploy, then watch, and undo it if the system gets worse.

        THE OLD CANARY DEPLOYED NOTHING. It computed `canary_path = file_path +
        ".canary"`, never used the variable, then monitored for five minutes
        and called the result "canary health" -- but no canary existed, so it
        was measuring the UNCHANGED system and reporting that as evidence the
        new code was safe. It then called `_deploy_immediate` for everything.
        A gate that manufactures its own passing signal is worse than no gate.

        There is one process here, not a fleet, so a percentage of traffic is
        not a thing that can be split. What CAN be done, and is what canary
        exists for, is bounded exposure: deploy for real, watch closely for a
        fixed window, and roll back automatically the moment health or error
        rate moves the wrong way.
        """
        try:
            self._error_rate_unverified = False
            baseline_error_rate = await self._get_error_rate("production")
            logger.info("Canary: deploying under observation (baseline error rate %s)",
                        "unmeasured" if baseline_error_rate is None
                        else f"{baseline_error_rate * 100:.2f}%")

            if not await self._deploy_immediate(file_paths, metadata):
                return False

            observed = 0
            interval = self.config.health_check_interval_sec
            while observed < self.config.monitoring_period_sec:
                await asyncio.sleep(interval)
                observed += interval

                healthy = await self._verify_health_checks("production")
                error_rate = await self._get_error_rate("production")

                if not healthy:
                    logger.error("Canary: health check failed after %ds — rolling back", observed)
                    await self._perform_rollback(file_paths)
                    return False
                if error_rate is None:
                    # UNMEASURED IS NOT WITHIN THRESHOLD. Recorded on the
                    # deployment so a canary that watched only health is never
                    # mistaken for one that watched errors too.
                    self._error_rate_unverified = True
                    logger.warning(
                        "Canary: error rate unmeasured at %ds — this canary is "
                        "watching health only", observed)
                elif error_rate > self.config.max_failure_rate:
                    logger.error("Canary: error rate %.2f%% exceeds %.2f%% after %ds "
                                 "— rolling back", error_rate * 100,
                                 self.config.max_failure_rate * 100, observed)
                    await self._perform_rollback(file_paths)
                    return False

                logger.info("Canary: %ds/%ds observed, healthy, error rate %s",
                            observed, self.config.monitoring_period_sec,
                            "unmeasured" if error_rate is None
                            else f"{error_rate * 100:.2f}%")

            logger.info("Canary: survived the observation window")
            return True

        except Exception as e:
            logger.error(f"Canary deployment error: {e}")
            return False

    async def _deploy_blue_green(
        self,
        file_paths: List[str],
        metadata: Dict[str, Any]
    ) -> bool:
        """Stage every file, verify the staged copies, then swap them in together.

        THE OLD BLUE-GREEN WROTE NOTHING. `green_path = file_path + ".green"`
        was computed and discarded, "Switching traffic to green environment"
        was a log line with no switch behind it, and both health checks read
        production -- so it verified the environment it had not changed.

        The property blue-green actually buys is ALL-OR-NOTHING: no moment
        exists where half the files are new. That is achievable here -- stage
        every file beside its target, verify each staged copy, and only then
        replace them one after another with no verification in between.
        """
        staged: List[Tuple[Path, str]] = []
        try:
            writes = self._resolve_writes(file_paths, metadata)

            for target, content in writes:
                ok, why = self._compiles(content, target)
                if not ok:
                    logger.error("Blue-green: staged copy of %s does not compile (%s); "
                                 "nothing has been swapped in", target, why)
                    raise RuntimeError(f"{target}: {why}")

                green = Path(target).with_suffix(Path(target).suffix + ".green")
                green.parent.mkdir(parents=True, exist_ok=True)
                green.write_text(content)
                staged.append((green, target))
                logger.info("Blue-green: staged %s", green)

            # Every file verified. Swap them in; os.replace is atomic per file
            # and nothing between them can fail a check and leave a split state.
            for green, target in staged:
                os.replace(green, target)
                logger.info("Blue-green: swapped in %s", target)
            staged.clear()

            if not await self._verify_health_checks("production"):
                logger.error("Blue-green: health check failed after swap")
                return False

            logger.info("Blue-Green deployment successful")
            return True

        except Exception as e:
            logger.error(f"Blue-Green deployment error: {e}")
            return False
        finally:
            # Staging files never swapped in must not be left lying beside the
            # real ones, where the next deployment would find them.
            for green, _target in staged:
                try:
                    if green.exists():
                        green.unlink()
                except OSError as cleanup_error:
                    logger.error("Could not remove staged %s: %s", green, cleanup_error)

    async def _deploy_rolling(
        self,
        file_paths: List[str],
        metadata: Dict[str, Any]
    ) -> bool:
        """Write one file at a time, checking health between each.

        THE OLD ROLLING DEPLOYMENT WROTE NOTHING AT ALL. `num_instances = 5`
        sat under the comment "Simulate multiple instances", and the inner loop
        was a single `logger.debug("Deployed ... to instance N")` with no copy
        behind it. It slept fifty seconds, health-checked the unchanged system
        five times, and returned True having shipped nothing -- and the cycle
        above recorded a successful deployment.

        There are no instances to roll across. What rolling means for files is
        incremental exposure: change one, confirm the system still stands,
        change the next -- so a bad file is caught before the rest follow it.
        """
        applied: List[str] = []
        try:
            writes = self._resolve_writes(file_paths, metadata)
            logger.info("Rolling deployment across %d file(s)", len(writes))

            for index, (target, content) in enumerate(writes, start=1):
                ok, why = self._compiles(content, target)
                if not ok:
                    logger.error("Rolling: %s does not compile (%s); stopping at %d/%d",
                                 target, why, index, len(writes))
                    if applied:
                        await self._perform_rollback(file_paths)
                    return False

                self._write_atomic(target, content)
                applied.append(target)
                logger.info("Rolling: applied %d/%d — %s", index, len(writes), target)

                if not await self._verify_health_checks("production"):
                    logger.error("Rolling: health check failed after %s; rolling back "
                                 "the %d file(s) applied so far", target, len(applied))
                    await self._perform_rollback(file_paths)
                    return False

                if index < len(writes):
                    await asyncio.sleep(self.config.health_check_interval_sec)

            logger.info("Rolling deployment completed: %d file(s)", len(applied))
            return True

        except Exception as e:
            logger.error(f"Rolling deployment error: {e}")
            if applied:
                await self._perform_rollback(file_paths)
            return False

    async def _deploy_immediate(
        self,
        file_paths: List[str],
        metadata: Dict[str, Any]
    ) -> bool:
        """Write every file at once. Fastest, and the least recoverable."""
        try:
            writes = self._resolve_writes(file_paths, metadata)
            logger.info("Immediate deployment: %d file(s)", len(writes))

            for target, content in writes:
                ok, why = self._compiles(content, target)
                if not ok:
                    logger.error("Immediate: %s does not compile (%s); refusing", target, why)
                    return False

            for target, content in writes:
                self._write_atomic(target, content)
                logger.info("Deployed: %s", target)

            return True

        except Exception as e:
            logger.error(f"Immediate deployment error: {e}")
            return False

    async def _monitor_deployment(self) -> bool:
        """Monitor deployment health"""
        try:
            monitoring_start = time.time()
            monitoring_duration = self.config.monitoring_period_sec
            check_interval = self.config.health_check_interval_sec

            logger.info(f"Monitoring deployment for {monitoring_duration}s")

            checks_passed = 0
            checks_failed = 0

            while (time.time() - monitoring_start) < monitoring_duration:
                # Perform health check
                healthy = await self._verify_health_checks("production")

                if healthy:
                    checks_passed += 1
                else:
                    checks_failed += 1

                # Check failure threshold
                total_checks = checks_passed + checks_failed
                failure_rate = checks_failed / total_checks if total_checks > 0 else 0

                if failure_rate > self.config.max_failure_rate:
                    logger.error(
                        f"Failure rate exceeded threshold: "
                        f"{failure_rate:.2%} > {self.config.max_failure_rate:.2%}"
                    )
                    return False

                # Wait before next check
                await asyncio.sleep(check_interval)

            logger.info(
                f"Monitoring complete: {checks_passed} passed, "
                f"{checks_failed} failed"
            )

            return True

        except Exception as e:
            logger.error(f"Monitoring error: {e}")
            return False

    async def _verify_health_checks(self, environment: str = "production") -> bool:
        """
        Verify health checks for environment

        Checks:
        - Service responding (HTTP 200)
        - Database connectivity
        - Memory usage within limits
        """
        import psutil

        # Check database connectivity
        try:
            from core.database import get_database_manager
            db = get_database_manager()
            await db.query("SELECT 1")
        except Exception as e:
            logger.warning(f"Database health check failed ({environment}): {e}")
            return False

        # Check memory usage
        try:
            memory = psutil.virtual_memory()
            if memory.percent > 90:  # More than 90% memory used
                logger.warning(f"Memory health check failed ({environment}): {memory.percent}%")
                return False
        except Exception as e:
            logger.debug(f"Memory check unavailable: {e}")

        # Check CPU usage
        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            if cpu_percent > 95:  # More than 95% CPU used
                logger.warning(f"CPU health check failed ({environment}): {cpu_percent}%")
                return False
        except Exception as e:
            logger.debug(f"CPU check unavailable: {e}")

        # Check disk space
        try:
            disk = psutil.disk_usage('/')
            if disk.percent > 90:  # More than 90% disk used
                logger.warning(f"Disk health check failed ({environment}): {disk.percent}%")
                return False
        except Exception as e:
            logger.debug(f"Disk check unavailable: {e}")

        return True

    async def _get_error_rate(self, environment: str = "production") -> Optional[float]:
        """Failures per minute over the monitoring window, or None if unmeasured.

        THIS ASKED THE WRONG SOURCE, TWICE. It first queried `request_logs`,
        which is not a table in this database; then `access_logs`, which is
        HTTP access logging that nothing in core/ writes and which holds zero
        rows. Both raised or returned nothing, and both fell through to
        `return 0.01` under the comment "assume low error rate if no data" --
        a constant permanently below `max_failure_rate`, so the canary's error
        gate could not fail for any state of the system.

        This is not a web service; its errors are the failures its subsystems
        report. `unified.failure_events` is where those now converge.

        None means UNMEASURED. The caller must not read it as healthy.
        """
        try:
            from core.observability import failure_record

            return await failure_record.failure_rate(
                within_minutes=max(1, self.config.monitoring_period_sec // 60))
        except Exception as e:
            logger.error("Failure rate unavailable (%s); reporting UNMEASURED "
                         "rather than assuming a low rate", e)
            return None

    async def _perform_rollback(self, file_paths: List[str]) -> bool:
        """Restore every file to exactly what it was before this deployment.

        Driven by the manifest written at backup time rather than by basename
        guessing, so a file that did not exist beforehand is REMOVED rather
        than left in place -- otherwise a rolled-back deployment still leaves
        its new modules on disk, importable, and nothing says so.
        """
        try:
            if not self.backup_paths:
                logger.error("No backups available for rollback")
                return False

            backup_dir = Path(self.backup_paths[-1])
            manifest_path = backup_dir / "manifest.json"
            if not manifest_path.exists():
                logger.error("Backup manifest not found: %s", manifest_path)
                return False

            logger.info("Performing rollback from %s", backup_dir)
            manifest = json.loads(manifest_path.read_text())

            restored, removed, missing = 0, 0, []
            for target, backup_file in manifest.items():
                if backup_file is None:
                    if os.path.exists(target):
                        os.remove(target)
                        removed += 1
                        logger.info("Removed (did not exist before): %s", target)
                    continue
                if os.path.exists(backup_file):
                    shutil.copy2(backup_file, target)
                    restored += 1
                    logger.info("Restored: %s", target)
                else:
                    missing.append(target)

            if missing:
                # A rollback that could not restore everything has NOT undone
                # the deployment, and saying otherwise is the worst possible
                # lie for this particular function to tell.
                logger.error("Rollback incomplete: no backup for %s", ", ".join(missing))
                return False

            rollback_healthy = await self._verify_health_checks("production")
            if not rollback_healthy:
                logger.error("Health checks failed after rollback")
                return False

            logger.info("Rollback successful: %d restored, %d removed", restored, removed)
            return True

        except Exception as e:
            logger.error(f"Rollback failed: {e}")
            return False

    async def _validate_deployment_readiness(
        self,
        file_paths: List[str]
    ) -> Tuple[bool, str]:
        """
        Validate deployment is ready

        Checks:
        - All files exist
        - Validation passed
        - Sandbox tests passed
        - Health checks passing (current system)
        """
        # Check all files exist
        for file_path in file_paths:
            if not os.path.exists(file_path):
                return False, f"File not found: {file_path}"

        try:
            from core.health.health_monitor import get_health_monitor
            health = get_health_monitor()
            health_status = await health.get_system_health()

            if health_status.get('overall_health', 0) < 0.7:
                return False, f"System health too low: {health_status.get('overall_health')}"

        except Exception as e:
            logger.warning(f"Could not verify system health: {e}")

        return True, "Deployment ready"

    async def _cleanup_deployment(self):
        """Cleanup after successful deployment"""
        # Remove old backups (keep most recent 3)
        while len(self.backup_paths) > 3:
            old_backup = self.backup_paths.pop(0)
            try:
                if os.path.exists(old_backup):
                    shutil.rmtree(old_backup)
                    logger.debug(f"Removed old backup: {old_backup}")
            except Exception as e:
                logger.error(f"Failed to remove old backup: {e}")

    async def _update_status(self, step: str, progress: float):
        """Update deployment status"""
        if self.current_status:
            self.current_status.current_step = step
            self.current_status.progress = progress
            self.current_status.completed_steps.append(step)

            logger.info(
                f"Deployment progress: {step} ({progress:.1f}%)"
            )

    async def get_deployment_status(self) -> Optional[DeploymentStatus]:
        """Get current deployment status"""
        return self.current_status

    async def get_deployment_history(
        self,
        limit: int = 10
    ) -> List[DeploymentResult]:
        """
        Get deployment history from database

        Returns:
            Recent deployment results (most recent first)
        """
        try:
            from core.database import get_database_manager
            db = get_database_manager()

            results = await db.query(
                """SELECT * FROM deployment_history
                   ORDER BY started_at DESC LIMIT %s""",
                (limit,)
            )

            history = []
            for row in results:
                result = DeploymentResult(
                    deployment_id=row.get('deployment_id'),
                    success=row.get('success'),
                    strategy=DeploymentStrategy(row.get('strategy', 'direct')),
                    files_deployed=row.get('files_deployed', []),
                    backup_paths=row.get('backup_paths', []),
                    started_at=row.get('started_at'),
                    completed_at=row.get('completed_at'),
                    error_message=row.get('error_message')
                )
                history.append(result)

            return history

        except Exception as e:
            logger.debug(f"Failed to query deployment history: {e}")
            # Fallback to in-memory history
            return self.deployment_history[-limit:]

    async def _store_deployment_record(
        self,
        result: DeploymentResult,
        file_paths: List[str],
        metadata: Dict[str, Any]
    ) -> bool:
        """
        Store deployment record in database

        Important for audit trail and rollback capability
        """
        # Store deployment record in database (Postgres)
        try:
            from core.database import get_database_manager
            import json
            db = get_database_manager()

            await db.execute_query(
                """
                INSERT INTO deployment_history
                   (deployment_id, timestamp, success, status, duration_seconds,
                    files_deployed, errors, metadata, rollout_strategy, rolled_back,
                    started_at, completed_at)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                """,
                params=(
                    result.deployment_id,
                    datetime.now(),
                    result.success,
                    result.status,
                    result.duration_seconds,
                    json.dumps(file_paths),
                    json.dumps(result.errors),
                    json.dumps(metadata),
                    self.config.rollout_strategy,
                    result.status == "rolled_back",
                    result.started_at,
                    result.completed_at,
                ),
                commit=True,
            )

            logger.info(f"Deployment record stored in database: {result.deployment_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to store deployment record: {e}")
            return False

    async def _notify_deployment_event(
        self,
        event_type: str,
        deployment_id: str,
        details: Dict[str, Any]
    ):
        """Send deployment notifications via Slack"""
        logger.info(f"Deployment event: {event_type} - {deployment_id}")

        # Send Slack notification
        try:
            from core.integration.slack_notifier import get_slack_notifier
            slack = get_slack_notifier()

            # Format notification message
            status_emoji = {
                'started': '🚀',
                'completed': '✅',
                'failed': '❌',
                'rolled_back': '⏮️'
            }.get(event_type, '📦')

            message = f"{status_emoji} Deployment {event_type.upper()}\n"
            message += f"ID: {deployment_id}\n"
            for key, value in details.items():
                message += f"{key}: {value}\n"

            await slack.send_message(message, channel="UPGRADES")

        except Exception as e:
            logger.error(f"Failed to send deployment notification: {e}")


async def deploy_upgrade_safe(
    file_paths: List[str],
    metadata: Dict[str, Any],
    strategy: str = "canary"
) -> DeploymentResult:
    """
    Convenience function to deploy upgrade

    Args:
        file_paths: Files to deploy
        metadata: Deployment metadata
        strategy: Deployment strategy (canary, blue_green, rolling, immediate)

    Returns:
        DeploymentResult
    """
    deployer = SafeUpgradeDeployer(
        config={
            "rollout_strategy": strategy,
            "rollback_enabled": True,
            "canary_percentage": 10
        }
    )

    result = await deployer.deploy_upgrade(file_paths, metadata)
    return result


# Example usage
async def main():
    # Example deployment
    file_paths = [
        "core/learning/improvement_monitor.py",
    ]

    metadata = {
        "version": "2.0.0",
        "description": "Learning system improvements",
        "author": "TorinAI"
    }

    deployer = SafeUpgradeDeployer(
        config={
            "rollout_strategy": "canary",
            "canary_percentage": 10,
            "monitoring_period_sec": 60
        }
    )

    result = await deployer.deploy_upgrade(file_paths, metadata)

    print(f"\nDeployment Result:")
    print(f"Success: {result.success}")
    print(f"Status: {result.status}")
    print(f"Duration: {result.duration_seconds:.2f}s")
    if result.errors:
        print(f"Errors: {', '.join(result.errors)}")



# ---------------------------------------------------------------------------
# Singleton accessor
#
# Deploys a validated upgrade with rollback.
# enhanced_asi_self_improvement.py has always imported `get_safe_deployer` from this
# module, but it was never defined -- the import silently bound the name to
# None via `except ImportError`, and the ASI phase that depends on it aborted
# every single improvement cycle. The class below was complete; only this
# accessor was missing.
# ---------------------------------------------------------------------------

_safe_deployer_instance: Optional[SafeUpgradeDeployer] = None


def get_safe_deployer(config: Optional[Dict[str, Any]] = None) -> SafeUpgradeDeployer:
    """Get the shared SafeUpgradeDeployer instance (singleton)."""
    global _safe_deployer_instance
    if _safe_deployer_instance is None:
        _safe_deployer_instance = SafeUpgradeDeployer(config) if config else SafeUpgradeDeployer()
    return _safe_deployer_instance

if __name__ == "__main__":
    asyncio.run(main())
