#!/usr/bin/env python3
"""One authority for what the dashboard can see and control.

The Monitoring and Security tabs need two real things per system: its live
status, and a way to stop or restart it. Both must be the SAME truth the
substrate acts on, so both are derived from this one registry rather than from a
hand-kept list in the app or a second query in a helper script.

WHY A COMMAND QUEUE RATHER THAN A DIRECT CALL. The controllable systems are live
objects inside the running substrate's process. The dashboard is a separate
process and cannot call a method on an object it does not hold. So control is
indirect and real: the app writes a command row, the substrate -- which DOES
hold the objects -- reads it on its loop and calls the actual start/stop method,
then records the outcome and the resulting status. Nothing is simulated; a
button press moves a real monitor.

STATUS IS MEASURED, NOT ASSERTED. Each system exposes a real attribute that says
whether it is running -- `is_monitoring`, `monitoring_active`, `is_running`.
`snapshot` reads those live, so a dot is green because the loop is actually
turning, not because something claimed it started.

SYSTEMS WITH NO LIFECYCLE ARE HONEST ABOUT IT. `safety_framework`, the security
`controller` and `malware_sandbox` are always-on gates and analysers: they have
no start/stop because they are not loops that can be off while the substrate is
up. They appear with status and `controllable=False`, so the app shows a dot and
no button rather than a button that would lie.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

MONITORING = "monitoring"
SECURITY = "security"

RUNNING = "running"
STOPPED = "stopped"
ABSENT = "absent"           # the substrate is up but this system was never built
GATE = "gate"               # always-on, no lifecycle to report


@dataclass(frozen=True)
class ControlledSystem:
    """One system the dashboard lists: how to reach it, read it, move it."""

    name: str
    kind: str                       # MONITORING or SECURITY
    description: str
    #: name of the attribute on the top-level AutonomousSystem that holds the
    #: live instance -- the only place every controllable object is referenced.
    holder_attr: str
    #: attribute on the live instance that is truthy when it is actually running.
    running_attr: Optional[str]
    #: coroutine method names on the instance. None where there is no lifecycle.
    start_method: Optional[str]
    stop_method: Optional[str]

    @property
    def controllable(self) -> bool:
        return bool(self.start_method and self.stop_method)


#: THE REGISTRY. Every name, method and attribute here was read from the module
#: it names, not assumed. Adding a system is one entry; the app, the status
#: reader and the dispatcher all pick it up with no further change.
REGISTRY: Dict[str, ControlledSystem] = {
    s.name: s for s in [
        ControlledSystem(
            "health_monitor", MONITORING,
            "Continuous CPU / memory / disk / component health",
            holder_attr="health_monitor", running_attr="is_monitoring",
            start_method="start_monitoring", stop_method="stop_monitoring"),
        ControlledSystem(
            "system_watchdog", MONITORING,
            "Detects a dead component and restarts it",
            holder_attr="system_watchdog", running_attr="is_running",
            start_method="start", stop_method="stop"),
        ControlledSystem(
            "monitoring_coordinator", MONITORING,
            "Orchestrates the monitoring subsystems",
            holder_attr="monitoring_coordinator", running_attr="is_monitoring",
            start_method="start_monitoring", stop_method="stop_monitoring"),
        ControlledSystem(
            "security_audit_worker", SECURITY,
            "Continuous security auditing; findings become tasks",
            holder_attr="audit_worker", running_attr="monitoring_active",
            start_method="start_monitoring", stop_method="stop_monitoring"),
        ControlledSystem(
            "threat_blocking", SECURITY,
            "Blocks known-bad entities in real time",
            holder_attr="threat_blocking", running_attr="monitoring_active",
            start_method="start_monitoring", stop_method="stop_monitoring"),
        ControlledSystem(
            "safety_framework", SECURITY,
            "The single evaluation point every tool call passes through",
            holder_attr="safety_framework", running_attr=None,
            start_method=None, stop_method=None),
        ControlledSystem(
            "security_controller", SECURITY,
            "Central enforcement: injection, path, rate-limit checks",
            holder_attr="security_controller", running_attr=None,
            start_method=None, stop_method=None),
        ControlledSystem(
            "malware_sandbox", SECURITY,
            "Isolated static analysis of suspicious files",
            holder_attr="malware_sandbox", running_attr=None,
            start_method=None, stop_method=None),
        ControlledSystem(
            "backup_scheduler", MONITORING,
            "Scheduled database and state backups (always-on, guardian-owned)",
            holder_attr="backup_scheduler", running_attr="scheduler_active",
            start_method="start_scheduler", stop_method="stop_scheduler"),
    ]
}


def resolve_live(autonomous_system: Any) -> Dict[str, Any]:
    """Build the map of REAL live instances the substrate is running.

    Reads the exact objects off the AutonomousSystem and its coordinator -- the
    same references the loops use -- so status and control act on what is
    actually turning, not on a re-resolved singleton. A system the running
    process never built is simply absent from the map, and reads as ABSENT.
    """
    coord = getattr(autonomous_system, "autonomous_coordinator", None)

    def first(*candidates):
        for holder, attr in candidates:
            if holder is None:
                continue
            inst = getattr(holder, attr, None)
            if inst is not None:
                return inst
        return None

    a = autonomous_system
    return {
        "health_monitor": first((a, "health_monitor"), (coord, "health_monitor")),
        "system_watchdog": first((a, "system_watchdog"), (coord, "system_watchdog")),
        "monitoring_coordinator": first((a, "monitoring_coordinator"),
                                        (coord, "monitoring_coordinator")),
        "security_audit_worker": first((a, "audit_worker"),
                                       (coord, "security_audit_worker")),
        "threat_blocking": first((a, "threat_blocking"), (coord, "threat_blocking")),
        "safety_framework": first((a, "safety_framework"), (coord, "safety_framework")),
        "security_controller": first((a, "security_controller"),
                                     (coord, "security_controller")),
        "malware_sandbox": first((a, "malware_sandbox"), (coord, "malware_sandbox")),
    }


def _instance(live: Dict[str, Any], system: ControlledSystem) -> Optional[Any]:
    """The live object for a system from the explicit map, or None.

    An explicit map rather than attribute-guessing, because the live instances
    are split across the AutonomousSystem and the coordinator, and reading a
    freshly-resolved singleton could return a DIFFERENT object than the one the
    loop is actually running -- which would make a green dot a lie. The substrate
    builds this map from the exact objects it holds; see `resolve_live`.
    """
    return live.get(system.name)


def _status_of(live: Dict[str, Any], system: ControlledSystem) -> str:
    inst = _instance(live, system)
    if inst is None:
        return ABSENT
    if system.running_attr is None:
        return GATE
    return RUNNING if bool(getattr(inst, system.running_attr, False)) else STOPPED


def snapshot(live: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every listed system with its REAL status, read live off the instances.

    `host` is the top-level AutonomousSystem, which holds every controllable
    object. Read here rather than persisted-then-read so a dot cannot be stale:
    it is whatever the object says right now.
    """
    rows = []
    for system in REGISTRY.values():
        rows.append({
            "name": system.name,
            "kind": system.kind,
            "description": system.description,
            "status": _status_of(live, system),
            "controllable": system.controllable,
        })
    rows.sort(key=lambda r: (r["kind"], r["name"]))
    return rows


async def apply(live: Dict[str, Any], system_name: str, action: str) -> Dict[str, Any]:
    """Execute one control action against the REAL live system. Never raises.

    Returns what happened, including the status after, so the caller records a
    fact rather than an intention. A restart is stop-then-start, and a stop of an
    already-stopped system is reported as a no-op rather than an error -- the end
    state is what was asked for.
    """
    system = REGISTRY.get(system_name)
    if system is None:
        return {"ok": False, "reason": f"unknown system {system_name!r}"}
    if action not in ("start", "stop", "restart"):
        return {"ok": False, "reason": f"unknown action {action!r}"}
    if not system.controllable:
        return {"ok": False, "reason": f"{system_name} has no lifecycle to control"}

    inst = _instance(live, system)
    if inst is None:
        return {"ok": False, "reason": f"{system_name} is not running in this process"}

    async def _call(method_name: str) -> None:
        method = getattr(inst, method_name, None)
        if method is None:
            raise AttributeError(f"{system_name}.{method_name} does not exist")
        result = method()
        if hasattr(result, "__await__"):
            await result

    try:
        if action in ("stop", "restart"):
            await _call(system.stop_method)
        if action in ("start", "restart"):
            await _call(system.start_method)
    except Exception as error:
        logger.error("control %s on %s failed: %s: %s",
                     action, system_name, type(error).__name__, error)
        return {"ok": False, "reason": f"{type(error).__name__}: {error}",
                "status": _status_of(live, system)}

    status = _status_of(live, system)
    # LOG TO THE SYSTEM'S OWN CHANNEL so the action is confirmed where the
    # dashboard shows it. A control that changes a real system with no visible
    # trace is indistinguishable from a button that did nothing -- which is
    # exactly what a stop with no log entry looked like. `core.health.*` routes
    # to the HEALTH pane, `core.security.*` to SECURITY.
    channel = "core.health" if system.kind == MONITORING else "core.security"
    logging.getLogger(f"{channel}.control").info(
        "%s %s -> %s (dashboard)", action, system_name, status)
    logger.info("control %s on %s -> %s", action, system_name, status)
    return {"ok": True, "status": status}


async def guardian_present(db_manager: Any = None, within_seconds: int = 6) -> bool:
    """Whether a guardian process is currently publishing status.

    The guardian upserts a heartbeat every loop; if it is fresher than a couple
    of loops, the guardian is up and owns control. Read rather than assumed, so
    a crashed guardian releases ownership back to the substrate fallback on its
    own.
    """
    if db_manager is None:
        from core.database import get_database_manager
        db_manager = get_database_manager()
    try:
        rows = await db_manager.execute_query(
            "SELECT EXTRACT(EPOCH FROM (NOW() - updated_at))::int AS age "
            "FROM unified.system_control_status WHERE name = $1",
            ("__guardian_heartbeat__",), fetch_all=True)
        return bool(rows) and int(rows[0]["age"]) <= within_seconds
    except Exception:
        return False


SUBSTRATE_HEARTBEAT = "__substrate_heartbeat__"


async def publish_substrate_heartbeat(db_manager: Any = None) -> None:
    """Advertise that the substrate process is alive.

    Symmetric with the guardian heartbeat. Written every control-loop cycle,
    BEFORE any deferral to the guardian, because it means "the substrate process
    exists", independent of who currently owns control. Readers in other
    processes (the health monitor) use it to tell an intentionally stopped
    substrate apart from a subsystem that regressed: a cognitive subsystem
    reading zero while no substrate heartbeat is fresh is expected-off, not a
    regression.
    """
    if db_manager is None:
        from core.database import get_database_manager
        db_manager = get_database_manager()
    try:
        await db_manager.execute_query(
            "INSERT INTO unified.system_control_status "
            "(name, kind, description, status, controllable, updated_at) "
            "VALUES ($1,'substrate','substrate process','running',false,NOW()) "
            "ON CONFLICT (name) DO UPDATE SET updated_at = NOW(), status='running'",
            (SUBSTRATE_HEARTBEAT,), commit=True)
    except Exception as error:
        logger.debug("substrate heartbeat failed: %s", error)


async def substrate_present(db_manager: Any = None, within_seconds: int = 8) -> bool:
    """Whether the substrate process is currently alive.

    The substrate upserts its heartbeat every control cycle (~2s). Fresher than
    a few cycles means it is running; stale or absent means it is stopped, and
    its cognitive subsystems being down is the expected consequence, not a
    fault. Read rather than assumed, so a crash is reflected on its own.
    """
    if db_manager is None:
        from core.database import get_database_manager
        db_manager = get_database_manager()
    try:
        rows = await db_manager.execute_query(
            "SELECT EXTRACT(EPOCH FROM (NOW() - updated_at))::int AS age "
            "FROM unified.system_control_status WHERE name = $1",
            (SUBSTRATE_HEARTBEAT,), fetch_all=True)
        return bool(rows) and int(rows[0]["age"]) <= within_seconds
    except Exception:
        return False


async def drain_commands(live: Dict[str, Any], db_manager: Any = None,
                        actor: str = "__substrate__") -> int:
    """Execute every pending control command against the real systems.

    Called on the substrate's own loop, because the substrate is the only
    process that holds the live objects. Each command is claimed, applied, and
    marked done/failed with what actually happened -- so the dashboard reads a
    result, not a hope. Returns how many it handled.
    """
    if db_manager is None:
        from core.database import get_database_manager
        db_manager = get_database_manager()

    try:
        pending = await db_manager.execute_query(
            "SELECT id, system, action FROM unified.system_control_commands "
            "WHERE status = 'pending' ORDER BY requested_at LIMIT 20",
            None, fetch_all=True) or []
    except Exception as error:
        logger.error("could not read control commands: %s", error)
        return 0

    handled = 0
    for row in pending:
        outcome = await apply(live, row["system"], row["action"])
        status = "done" if outcome.get("ok") else "failed"
        detail = outcome.get("status") or outcome.get("reason") or ""
        try:
            await db_manager.execute_query(
                "UPDATE unified.system_control_commands "
                "SET status = $1, result = $2, acted_at = NOW() WHERE id = $3",
                (status, str(detail)[:400], row["id"]), commit=True)
            handled += 1
        except Exception as error:
            logger.error("could not record control result for %s: %s",
                         row["id"], error)
    return handled


_STATUS_DDL = (
    "CREATE TABLE IF NOT EXISTS unified.system_control_status ("
    " name TEXT PRIMARY KEY, kind TEXT NOT NULL, description TEXT,"
    " status TEXT NOT NULL, controllable BOOLEAN NOT NULL,"
    " updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"
)


async def publish_status(live: Dict[str, Any], db_manager: Any = None) -> None:
    """Write the live status of every system for readers in other processes.

    A separate process cannot read the live objects, so the substrate publishes
    the same snapshot to a table the dashboard selects. Upsert by name: one
    current row per system, no history to prune.
    """
    if db_manager is None:
        from core.database import get_database_manager
        db_manager = get_database_manager()
    try:
        await db_manager.execute_query(_STATUS_DDL, None, commit=True)
        for r in snapshot(live):
            await db_manager.execute_query(
                "INSERT INTO unified.system_control_status "
                "(name, kind, description, status, controllable, updated_at) "
                "VALUES ($1,$2,$3,$4,$5,NOW()) "
                "ON CONFLICT (name) DO UPDATE SET status=EXCLUDED.status, "
                "kind=EXCLUDED.kind, description=EXCLUDED.description, "
                "controllable=EXCLUDED.controllable, updated_at=NOW()",
                (r["name"], r["kind"], r["description"], r["status"],
                 r["controllable"]), commit=True)
    except Exception as error:
        logger.error("could not publish system status: %s", error)


__all__ = ["ControlledSystem", "REGISTRY", "snapshot", "apply", "resolve_live",
           "drain_commands", "publish_status", "guardian_present",
    "substrate_present", "publish_substrate_heartbeat", "SUBSTRATE_HEARTBEAT",
           "MONITORING", "SECURITY", "RUNNING", "STOPPED", "ABSENT", "GATE"]
