#!/usr/bin/env python3
"""The Guardian: monitoring and security as a daemon, not a substrate subsystem.

WHY THIS EXISTS. Monitoring and security were objects INSIDE the substrate's
process, so they died with it -- a watchdog whose job is to survive a crash
could not, because it crashed too. The dashboard made this visible: stop the
substrate and every control went dead, because the objects and the loop that
would act on a command were both gone.

The guardian is the fix. It is a separate process that CONSTRUCTS and RUNS the
monitoring and security systems, owns their control loop, and is meant to start
before the substrate and outlive it. The thing that protects a system must be
more durable than the thing it protects, not a feature of it.

WHY THIS IS POSSIBLE WITHOUT REWRITING THEM. Each system already constructs
standalone -- `HealthMonitor(config=None)`, `MonitoringCoordinator(...)`,
`get_audit_worker()` -- and only TOUCHES the coordinator through optional,
guarded callbacks (`if self.autonomous_coordinator:`). Their one real coupling,
security findings becoming remediation tasks, already crosses the boundary
through the task queue (`TaskSource.SECURITY_AUDIT`): a finding is written as a
task row the substrate drains when it is up. So nothing here reimplements a
system; it hosts the real ones.

SOLE OWNER OF THE CONTROL LOOP. When the guardian runs, it is the authority for
these systems' status and control -- it holds the live objects, so it is the
only process that can truthfully report them or move them. The substrate does
not also run this loop; two drainers on one command queue would race.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from typing import Any, Dict, Optional

logger = logging.getLogger("core.guardian")


class Guardian:
    """Hosts the monitoring and security systems and serves the dashboard."""

    def __init__(self) -> None:
        self._live: Dict[str, Any] = {}
        self._db: Optional[Any] = None
        self._stopping = asyncio.Event()

    async def _build(self) -> None:
        """Construct the real systems this process will own and run.

        Each is built through its own module accessor -- the same object the
        rest of the codebase resolves -- and started. A system that cannot be
        built is logged and left out of the live map, where it reads as ABSENT
        rather than pretending to run.
        """
        # WHAT THE GUARDIAN OWNS, AND WHAT IT DOES NOT.
        #
        # The guardian is the EXTERNAL always-on layer: watch that the substrate
        # is alive, and run security. It does NOT run health_monitor or
        # monitoring_coordinator -- those monitor the substrate's OWN internal
        # subsystems (memory, learning, reasoning...), which do not exist when
        # the substrate is down. Coordinating the health of subsystems that are
        # not running is meaningless, so that apparatus lives WITH the substrate
        # and its data is stale-but-visible when the substrate is off. The
        # Monitoring page reads that component health directly; it is not a
        # guardian concern.
        builders = {
            "system_watchdog":
                ("core.health.system_watchdog", "get_system_watchdog", "start"),
            "security_audit_worker":
                ("core.security.security_audit_worker", "get_audit_worker", "start_monitoring"),
            # Backups are a durability concern that must survive the substrate,
            # so the always-on guardian owns the scheduler. The substrate defers
            # to it when a guardian is present (see core/main.py), so exactly one
            # scheduler runs.
            "backup_scheduler":
                ("core.services.backup_scheduler", "get_backup_scheduler", "start_scheduler"),
        }

        import importlib
        for name, (module_path, accessor, start) in builders.items():
            try:
                module = importlib.import_module(module_path)
                instance = getattr(module, accessor)()
                if hasattr(instance, "__await__"):
                    instance = await instance
                self._live[name] = instance
                logger.info("guardian built %s", name)
            except Exception as error:
                logger.error("guardian could not build %s: %s: %s",
                             name, type(error).__name__, error)

        # Make the ownership boundary explicit on the live monitor, regardless
        # of when its singleton was first built.
        try:
            from core.health.health_monitor import get_health_monitor
            get_health_monitor().set_scope("system")
        except Exception as error:
            logger.error("guardian could not set health scope: %s", error)

        # THE INTEGRATED SECURITY SYSTEM IS THE ONE SECURITY AUTHORITY.
        #
        # threat_blocking used to be built here on its own with
        # firewall_test_mode=False, which is why the firewall warned "not
        # running as root": it tried to apply real pf rules from a user-level
        # process. But local pf is the wrong enforcement surface anyway -- every
        # Dominion Labs service ingresses through the API Gateway -> Cloudflare
        # tunnel, so the MacBook has no direct public exposure and the edge is
        # where blocks belong. So the enforcement is the Cloudflare WAF, the
        # local firewall stays in dry-run (test_mode=True), and one call builds
        # threat_intel + firewall + WAF + the coordinating threat-blocking
        # engine, populating the singleton the health checks and the audit
        # worker read (previously None, so firewall/threat_intel graded absent).
        try:
            from core.security import create_integrated_security_system
            zone_id = await self._cloudflare_zone_id("dmnlabs.org")
            system = create_integrated_security_system(
                test_mode=True,               # local pf is not the enforcement surface
                cloudflare_zone_id=zone_id,   # Cloudflare edge IS
            )
            # Expose the coordinating engine as the controllable/observable unit.
            self._live["threat_blocking"] = system["threat_blocking"]
            logger.info(
                "guardian built integrated_security (threat_intel=%s, waf=%s, "
                "firewall=dry-run)",
                system.get("has_threat_intel_keys"), system.get("has_waf"))
        except Exception as error:
            logger.error("guardian could not build integrated_security: %s: %s",
                         type(error).__name__, error)

        # Start each system's own loop, best effort. A start that fails leaves
        # the object present but STOPPED -- visible and restartable from the
        # dashboard, not silently missing.
        from core.health import system_control as sc
        for name in list(self._live):
            outcome = await sc.apply(self._live, name, "start")
            logger.info("guardian start %s -> %s", name,
                        outcome.get("status") or outcome.get("reason"))

    async def _cloudflare_zone_id(self, domain: str) -> Optional[str]:
        """Resolve a Cloudflare zone id for a domain from the API token.

        The token is the authority: it already scopes which zones it can touch,
        so the zone id is derived from it rather than being a second hand-kept
        secret. Falls back to CLOUDFLARE_ZONE_ID if the lookup cannot run. None
        means the WAF is not wired and edge enforcement is unavailable -- the
        honest state, not a silent dry-run pretending to enforce.
        """
        import os
        env_zone = os.getenv("CLOUDFLARE_ZONE_ID")
        if env_zone:
            return env_zone
        token = os.getenv("CLOUDFLARE_API_TOKEN")
        if not token:
            return None
        try:
            import aiohttp
            url = f"https://api.cloudflare.com/client/v4/zones?name={domain}"
            headers = {"Authorization": f"Bearer {token}"}
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers,
                                       timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    data = await resp.json()
            if data.get("success") and data.get("result"):
                zid = data["result"][0]["id"]
                logger.info("resolved Cloudflare zone %s -> %s", domain, zid)
                return zid
            logger.warning("Cloudflare zone lookup for %s returned no result: %s",
                           domain, data.get("errors"))
        except Exception as error:
            logger.warning("Cloudflare zone lookup failed for %s: %s", domain, error)
        return None

    async def _control_loop(self) -> None:
        """Publish live status and apply dashboard commands every 2s."""
        from core.health import system_control as sc
        while not self._stopping.is_set():
            try:
                await sc.publish_status(self._live, self._db)
                await self._heartbeat()
                await sc.drain_commands(self._live, self._db)
            except Exception as error:
                logger.error("guardian control loop error: %s", error)
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                pass

    async def _heartbeat(self) -> None:
        """Mark that a guardian is alive, so the substrate defers control to it."""
        if self._db is None:
            return
        try:
            await self._db.execute_query(
                "INSERT INTO unified.system_control_status "
                "(name, kind, description, status, controllable, updated_at) "
                "VALUES ('__guardian_heartbeat__','guardian','guardian process',"
                "'running',false,NOW()) "
                "ON CONFLICT (name) DO UPDATE SET updated_at = NOW(), status='running'",
                None, commit=True)
        except Exception as error:
            logger.debug("guardian heartbeat failed: %s", error)

    async def run(self) -> None:
        # WRITE TO THE CHANNEL LOGS THE DASHBOARD READS.
        #
        # Without this the guardian's output -- the systems it hosts and every
        # control confirmation -- went only to logs/guardian.log (launchd
        # stdout), never to logs/channels/*.log. So a stop applied by the
        # guardian changed a real system and left no trace where anyone was
        # looking, which is exactly why a button press showed no confirmation.
        # install() is idempotent, so doing it here as well as in the substrate
        # is safe.
        try:
            from core.observability import channels
            channels.install()
        except Exception as error:
            logger.warning("guardian could not install channel logging: %s", error)

        logger.info("Guardian starting (monitoring + security, independent of the substrate)")
        # Announce BEFORE building. Some hosted systems are slow to start
        # (threat_blocking initialises the firewall), and until the first
        # heartbeat the substrate would think no guardian is present and try to
        # take ownership. A DB handle is enough to claim the role.
        from core.database import get_database_manager
        self._db = get_database_manager()
        await self._db.initialize()
        await self._heartbeat()
        await self._build()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self._stopping.set)
            except (NotImplementedError, RuntimeError):
                pass
        logger.info("Guardian up: %d system(s) hosted", len(self._live))
        await self._control_loop()
        await self._shutdown()

    async def _shutdown(self) -> None:
        from core.health import system_control as sc
        logger.info("Guardian stopping; leaving its systems as they are")
        # The systems keep running unless explicitly stopped: the guardian going
        # down for a restart should not take monitoring with it. A supervising
        # launch agent brings the guardian back.
        try:
            await sc.publish_status(self._live, self._db)
        except Exception:
            pass


async def main() -> int:
    # THIS PROCESS IS THE SYSTEM LAYER. Declare it before any health monitor is
    # built, so the guardian grades only the components it owns (active defense,
    # infrastructure, the observability apparatus) and never the substrate's
    # cognition. Ownership is the boundary the health system was missing.
    import os
    os.environ["TORINAI_HEALTH_SCOPE"] = "system"

    # Load the Dominion Labs environment FIRST, before any security system reads
    # os.getenv. The master .env lives one level above TorinAI and holds the
    # shared credentials the guardian needs -- notably the threat-intelligence
    # keys (ABUSEIPDB/VIRUSTOTAL/OTX) and Cloudflare token. Without this the
    # guardian ran with only TorinAI's partial local env and threat_intel had
    # zero sources.
    try:
        from core.utils.env_loader import load_global_env, resolve_env_files
        load_global_env(force_reload=True)
        logger.info("guardian environment loaded from: %s",
                    ", ".join(str(f) for f in resolve_env_files()) or "(none)")
    except Exception as error:
        logger.error("guardian could not load global environment: %s", error)

    guardian = Guardian()
    await guardian.run()
    return 0
