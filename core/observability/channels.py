"""One stream in, four streams out.

Everything the system emitted went to one logger, so watching Torin reason meant
reading it interleaved with connection-pool churn and 371 tool registrations.
The signal was there; it was 2% of the volume.

No subsystem was changed to make this work. All 222 modules already log through
`getLogger(__name__)`, so every record arrives carrying `core.<subsystem>.<...>`
-- the channel is derivable from what is already there. Routing is decided in
this one file, which is what keeps a new subsystem from silently landing in the
wrong place: an unmatched prefix goes to SYSTEM by name, not by accident.

Channels are about WHOSE ACTIVITY a line describes, not how severe it is.
Severity is orthogonal and already carried by levelname; a pool timeout is
SYSTEM whether it is INFO or CRITICAL.
"""
import logging
import os
from pathlib import Path
from typing import Dict, Tuple

SUBSTRATE = "substrate"
SYSTEM = "system"
SECURITY = "security"
HEALTH = "health"

# FOUR PANELS, ONE PER CONCERN. TASKS was folded into SUBSTRATE and HEALTH was
# split out of SYSTEM on 2026-08-25.
#
# The substrate IS Torin thinking AND acting -- learning, reasoning, memory,
# then the agents, execution and tools that carry a decision out. Those are not
# two things to a substrate-first system; a task is the substrate doing
# something, so it belongs in the same panel, not a separate "tasks" lane that
# implied a request-processing pipeline.
#
# HEALTH and SECURITY are the two watching faculties, now peers -- health and
# monitoring had been buried in the SYSTEM catch-all while security had its own
# panel, which is the asymmetry that made this wrong. SYSTEM keeps only the
# machinery neither faculty owns: the database, services, the API, integration.
ALL_CHANNELS = (SUBSTRATE, SYSTEM, SECURITY, HEALTH)

#: Logger-name prefix -> channel. Longest prefix wins, so a more specific rule
#: can carve a module out of its parent without reordering anything.
ROUTES: Tuple[Tuple[str, str], ...] = (
    # THE SUBSTRATE: thinking and acting are one concern.
    ("core.learning",       SUBSTRATE),
    ("core.reasoning",      SUBSTRATE),
    ("core.domain",         SUBSTRATE),
    ("core.memory",         SUBSTRATE),
    ("core.semantics",      SUBSTRATE),
    ("core.agents",         SUBSTRATE),
    ("core.execution",      SUBSTRATE),
    ("core.tools.execution_tools", SUBSTRATE),

    # SECURITY: what was permitted, refused, or recorded.
    ("core.security",       SECURITY),
    ("core.governance",     SECURITY),
    ("core.safety",         SECURITY),

    # HEALTH: the monitoring faculty, its own panel now, not folded into SYSTEM.
    ("core.health",         HEALTH),
    ("core.monitoring",     HEALTH),

    # SYSTEM: the machinery neither faculty owns. Listed explicitly rather than
    # left to the default so the intent is visible when reading this table.
    ("core.database",       SYSTEM),
    ("core.services",       SYSTEM),
    ("core.tools",          SYSTEM),
    ("core.api",            SYSTEM),
    ("core.integration",    SYSTEM),
    ("core.system",         SYSTEM),
    ("core.utils",          SYSTEM),
    ("core.chaos",          SYSTEM),
)


def channel_for(logger_name: str) -> str:
    """Which channel a record belongs to. Unknown prefixes are SYSTEM."""
    best, best_len = SYSTEM, -1
    for prefix, channel in ROUTES:
        if (logger_name == prefix or logger_name.startswith(prefix + ".")) \
                and len(prefix) > best_len:
            best, best_len = channel, len(prefix)
    return best


class ChannelFilter(logging.Filter):
    """Admit only this channel's records, and stamp every record with its own.

    The stamp is set on ALL records the filter sees, including rejected ones, so
    any other handler -- the combined log, a future sink -- can read
    `record.channel` without repeating the routing decision.
    """

    def __init__(self, channel: str):
        super().__init__()
        self.channel = channel

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "channel"):
            record.channel = channel_for(record.name)
        return record.channel == self.channel


def log_dir() -> Path:
    return Path(os.getenv("TORIN_HOME", ".")) / "logs" / "channels"


def install(level: int = logging.INFO) -> Dict[str, Path]:
    """Attach one file handler per channel to the root logger.

    ADDITIVE. The combined `logs/torin_main.log` and the stdout stream stay
    exactly as they were: this is a second way to read the same records, not a
    replacement, so nothing that currently greps the main log breaks.
    """
    directory = log_dir()
    directory.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S")

    root = logging.getLogger()
    paths: Dict[str, Path] = {}

    for channel in ALL_CHANNELS:
        path = directory / f"{channel}.log"
        # Re-running install() must not stack duplicate handlers onto root.
        tag = f"torin-channel:{channel}"
        if any(getattr(h, "_torin_tag", None) == tag for h in root.handlers):
            paths[channel] = path
            continue
        handler = logging.FileHandler(path)
        handler.setLevel(level)
        handler.setFormatter(formatter)
        handler.addFilter(ChannelFilter(channel))
        handler._torin_tag = tag
        root.addHandler(handler)
        paths[channel] = path

    return paths
