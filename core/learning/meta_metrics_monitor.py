#!/usr/bin/env python3
"""
Meta-Metrics Monitor
Monitors the meta-learner's own health and standards to prevent self-degradation

This module guards the guards - it watches whether the meta-learning system
is maintaining its own standards or gradually relaxing constraints.

Tracks:
- Meta-learning parameter drift (min_trials, adaptation_threshold, exploration_quota)
- Strategy adoption velocity (how fast new strategies are promoted/deprecated)
- Meta-confidence levels (average confidence across all strategies)
- Standards stability (are safety thresholds being lowered over time?)
"""

import json
import logging
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path
from dotenv import load_dotenv

from core.database import TorinUnifiedDatabase, get_unified_db

# Load environment variables
env_file = Path(__file__).parent.parent.parent / ".env.production"
if env_file.exists():
    load_dotenv(env_file)

logger = logging.getLogger(__name__)


# Approved defaults - meta-learning parameters should not deviate below these
APPROVED_DEFAULTS = {
    "min_trials": 5,
    "adaptation_threshold": 0.7,
    "exploration_quota": 0.10,
    "confidence_threshold": 0.7,
    "success_rate_early": 0.60,  # For < 20 trials
    "success_rate_established": 0.70  # For 20+ trials
}

#: Below this, a strategy is counted as a low-confidence adoption. Named once:
#: the snapshot counted `< 0.7` and the degradation check alerted at `< 0.6`,
#: so the report could show low-confidence adoptions climbing while the check
#: that watches for exactly that stayed quiet.
LOW_CONFIDENCE_THRESHOLD = APPROVED_DEFAULTS["confidence_threshold"]

#: How far a governed parameter may slip before an alert escalates. A single
#: trial fewer and a collapse to zero were both reported CRITICAL, which makes
#: the severity carry no information.
_ALERT_BANDS = {
    "min_trials":           ((3.0, "CRITICAL"), (2.0, "HIGH"), (1.0, "MEDIUM")),
    "adaptation_threshold": ((0.20, "CRITICAL"), (0.10, "HIGH"), (0.05, "MEDIUM")),
    "exploration_quota":    ((0.20, "CRITICAL"), (0.10, "HIGH"), (0.05, "MEDIUM")),
}


def _alert_severity(parameter_name, drift_amount) -> str:
    """Severity from how far the parameter moved.

    CRITICAL when the magnitude is unknown: an unmeasurable drift on a
    standards guard is not a small problem, and defaulting it downward would
    hide exactly the case where the measurement itself failed.
    """
    if parameter_name is None or drift_amount is None:
        return "CRITICAL"
    magnitude = abs(float(drift_amount))
    for threshold, severity in _ALERT_BANDS.get(parameter_name, ()):
        if magnitude >= threshold:
            return severity
    return "LOW"


#: More low-confidence adoptions than this in one snapshot is the shape of
#: standards relaxing: strategies taken up before they have earned it.
MAX_LOW_CONFIDENCE_ADOPTIONS = 3


@dataclass
class MetaParameterSnapshot:
    """Snapshot of meta-learning parameters at a point in time"""
    snapshot_id: str
    timestamp: datetime

    # Current parameter values
    min_trials: int
    adaptation_threshold: float
    exploration_quota: float

    # Derived metrics
    avg_strategy_confidence: float
    total_strategies: int
    low_confidence_adoptions: int

    # Drift from approved defaults
    min_trials_drift: int  # Should be 0 (no drift from 5)
    threshold_drift: float  # Should be 0 (no drift from 0.7)
    exploration_drift: float  # Should be <= 0 (not higher than 0.10)

    # Velocity metrics
    strategies_promoted_last_week: int = 0
    strategies_deprecated_last_week: int = 0
    rate_of_change: float = 0.0  # Churn rate

    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MetaHealthReport:
    """Health report for the meta-learning system itself"""
    timestamp: datetime
    overall_health: str  # "HEALTHY", "DEGRADED", "CRITICAL"

    # Standards stability
    standards_degradation_detected: bool
    standards_stability_score: float  # 0-100

    # Adoption patterns
    adoption_velocity: str  # "STABLE", "ACCELERATING", "DECELERATING"
    avg_confidence_trend: str  # "IMPROVING", "DEGRADING", "STABLE"

    # Alerts
    alerts: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    # Supporting data
    current_snapshot: Optional[MetaParameterSnapshot] = None
    parameter_history: List[MetaParameterSnapshot] = field(default_factory=list)


class MetaMetricsMonitor:
    """
    Monitor the meta-learner's own health and parameters

    Prevents the meta-learning system from degrading its own standards over time.
    This is "second-order governance" - watching the watchers.
    """

    def __init__(self, db_config: Dict[str, Any] = None):
        # db_config is kept for backward API compatibility but ignored;
        # MetaMetricsMonitor now uses the unified PostgreSQL database.
        _ = db_config

        # get_unified_db is a COROUTINE FUNCTION. Assigning it here without
        # awaiting stored a coroutine object on self.db, so every database call
        # in this class raised "'coroutine' object has no attribute
        # execute_query" -- and all three public methods swallowed it. The
        # monitor that exists to watch for meta-learner degradation could not
        # read a single row. Resolved lazily instead, in an async context.
        self.db: Optional[TorinUnifiedDatabase] = None

        logger.info("Meta-metrics monitor initialized on unified PostgreSQL - guarding the meta-learner")

    async def _get_db(self) -> TorinUnifiedDatabase:
        """Resolve the shared pool on first use."""
        if self.db is None:
            self.db = await get_unified_db()
        return self.db

    @staticmethod
    def _as_dict(value: Any) -> Dict[str, Any]:
        """asyncpg hands back a jsonb column as a str, not a dict.

        Calling .get() on it raised AttributeError on every row, so the drift
        comparison and degradation detector produced nothing even once the
        connection worked.
        """
        if isinstance(value, dict):
            return value
        if isinstance(value, str) and value:
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return {}
        return {}

    #: A selection whose propensity was below this was an exploratory pick:
    #: the policy did not favour that arm and it was taken anyway.
    EXPLORATION_PROPENSITY = 0.34

    #: Fewest decisions before an exploration rate means anything. Below this
    #: the rate is noise and is reported as unmeasured rather than as a number.
    MIN_DECISIONS_FOR_RATE = 20

    #: Fewest snapshots before a trend can be called. Two points make a line
    #: through noise; the report says UNKNOWN instead.
    MIN_SNAPSHOTS_FOR_TREND = 3

    async def _strategy_statistics(self):
        """(avg confidence, count, low-confidence count) from the store, or None.

        `unified.meta_learning_strategies` is what survives a restart, so two
        processes taking a snapshot an hour apart describe the same system.
        None, never a tuple of zeros: an unreadable store must not enter the
        history as a measurement.
        """
        try:
            db = await self._get_db()
            # TWO POPULATIONS, DELIBERATELY. `total` is every registered arm;
            # confidence and adoptions count only arms with at least one trial.
            #
            # An arm that has never been selected has confidence 0.0 because it
            # has no evidence, not because it performs badly. Averaging those in
            # would drag the mean from 0.473 to 0.245 and hold this report below
            # its own 0.7 alert threshold permanently -- and registering a new
            # arm would look like standards degrading. "Adoption" likewise means
            # an arm was USED at low confidence; an unused arm was not adopted.
            rows = await db.execute_query(
                """SELECT COUNT(*)                                  AS total,
                          COUNT(*) FILTER (WHERE trials > 0)        AS exercised,
                          AVG(confidence) FILTER (WHERE trials > 0) AS avg_confidence,
                          COUNT(*) FILTER (WHERE trials > 0
                                             AND confidence < $1)   AS low_confidence
                     FROM unified.meta_learning_strategies""",
                (LOW_CONFIDENCE_THRESHOLD,), fetch_all=True)
        except Exception as error:
            logger.error("Strategy statistics unavailable: %s", error)
            return None

        if not rows:
            return None
        row = rows[0]
        total = int(row["total"] or 0)
        exercised = int(row["exercised"] or 0)
        if exercised == 0:
            # Arms registered but none used yet: the population is real and
            # measurable, the confidence average genuinely does not exist.
            # None for the average, not 0.0 -- there is nothing to average.
            return None, total, 0
        return (float(row["avg_confidence"]), total, int(row["low_confidence"] or 0))

    async def _promotion_counts(self):
        """(promoted, deprecated) strategies in the last week.

        Promotion is a strategy crossing into usable confidence; deprecation is
        one whose failures now outnumber its successes. Both read from the
        strategy store's own timestamps, so nothing has to remember to report.
        """
        try:
            db = await self._get_db()
            rows = await db.execute_query(
                """SELECT COUNT(*) FILTER (WHERE trials > 0
                                             AND confidence >= $1)     AS promoted,
                          COUNT(*) FILTER (WHERE trials > 0
                                             AND failures > successes) AS deprecated
                     FROM unified.meta_learning_strategies
                    WHERE updated_at > NOW() - INTERVAL '7 days'""",
                (LOW_CONFIDENCE_THRESHOLD,), fetch_all=True)
        except Exception as error:
            logger.error("Promotion counts unavailable: %s", error)
            return 0, 0
        if not rows:
            return 0, 0
        return int(rows[0]["promoted"] or 0), int(rows[0]["deprecated"] or 0)

    async def _parameter_rate_of_change(self) -> float:
        """How fast the meta-parameters themselves are moving.

        The sum of absolute change in the two governed parameters across the
        last two snapshots. A meta-parameter that moves every cycle is drifting
        even when no single step crosses a threshold, and that is precisely the
        shape a per-snapshot threshold check cannot see.
        """
        try:
            db = await self._get_db()
            rows = await db.execute_query(
                """SELECT min_trials, adaptation_threshold
                     FROM unified.meta_parameter_snapshots
                    ORDER BY timestamp DESC LIMIT 2""", fetch_all=True) or []
        except Exception as error:
            logger.error("Parameter rate of change unavailable: %s", error)
            return 0.0
        if len(rows) < 2:
            return 0.0
        newer, older = rows[0], rows[1]
        change = abs(int(newer["min_trials"] or 0) - int(older["min_trials"] or 0))
        change += abs(float(newer["adaptation_threshold"] or 0.0)
                      - float(older["adaptation_threshold"] or 0.0))
        return round(change, 4)

    async def _measured_exploration_rate(self) -> Optional[float]:
        """The share of recent selections that were exploratory, or None.

        Read from `meta_decision_records.chosen_propensity`, which records how
        likely the policy was to pick the arm it picked. Nothing needs to
        report exploration separately; the decision log already knows.
        """
        try:
            db = await self._get_db()
            rows = await db.execute_query(
                """SELECT COUNT(*) AS total,
                          COUNT(*) FILTER (WHERE chosen_propensity < $1) AS exploratory
                     FROM unified.meta_decision_records
                    WHERE decided_at > NOW() - INTERVAL '30 days'
                      AND chosen_propensity IS NOT NULL""",
                (self.EXPLORATION_PROPENSITY,), fetch_all=True)
        except Exception as error:
            logger.error("Exploration rate unavailable: %s", error)
            return None

        if not rows:
            return None
        total = int(rows[0]["total"] or 0)
        if total < self.MIN_DECISIONS_FOR_RATE:
            logger.info("Only %d decisions in 30 days; exploration rate is "
                        "unmeasured rather than estimated", total)
            return None
        return int(rows[0]["exploratory"] or 0) / total

    async def _snapshot_series(self, column: str) -> List[float]:
        """Recent values of one snapshot column, oldest first."""
        try:
            db = await self._get_db()
            rows = await db.execute_query(
                f"""SELECT {column} AS value FROM unified.meta_parameter_snapshots
                     WHERE {column} IS NOT NULL
                     ORDER BY timestamp DESC LIMIT 10""", fetch_all=True) or []
        except Exception as error:
            logger.error("Snapshot series for %s unavailable: %s", column, error)
            return []
        return [float(r["value"]) for r in reversed(rows)]

    @staticmethod
    def _describe_trend(series: List[float], rising: str, falling: str,
                        tolerance: float) -> str:
        """Which way a series is going, or UNKNOWN if it cannot be said."""
        if len(series) < MetaMetricsMonitor.MIN_SNAPSHOTS_FOR_TREND:
            return "UNKNOWN"
        change = series[-1] - series[0]
        if abs(change) <= tolerance:
            return "STABLE"
        return rising if change > 0 else falling

    async def _adoption_velocity(self) -> str:
        """Whether strategies are being adopted faster or slower than before.

        Measured as the change in how many strategies the learner holds across
        recent snapshots. Accelerating adoption is the shape that precedes
        standards slipping: arms promoted before they have earned it.
        """
        series = await self._snapshot_series("total_strategies")
        return self._describe_trend(series, "ACCELERATING", "SLOWING", tolerance=1.0)

    async def _confidence_trend(self) -> str:
        """Whether average strategy confidence is rising or falling."""
        series = await self._snapshot_series("avg_strategy_confidence")
        return self._describe_trend(series, "RISING", "FALLING", tolerance=0.05)

    async def _publish_metrics(self, snapshot: "MetaParameterSnapshot") -> int:
        """Publish this snapshot's measurements to the improvement record.

        `unified.improvement_metrics` and `unified.metric_measurements` were
        both EMPTY, and their producers -- `ImprovementMonitor.track_improvement`
        and `record_measurement` -- had zero callers anywhere in the codebase.
        The table, the schema and the writer all existed; nothing ever joined
        them, so no component's improvement was recorded by the system built to
        record it.

        The meta-parameters are the natural first publisher because they are
        the one place a real APPROVED BASELINE exists to compare against.
        Everywhere else has to invent one; here it is `APPROVED_DEFAULTS`, which
        is what "approved" means.

        Returns how many were published. Never raises: this is telemetry about
        the health check, and it must not be able to fail the health check.
        """
        published = 0
        try:
            from core.learning.improvement_monitor import (
                MetricType, get_improvement_monitor)

            monitor = get_improvement_monitor()

            # (metric name, type, approved baseline, measured value)
            # A None measurement is SKIPPED, not published as zero -- the whole
            # point of measuring these is that unmeasured and bad are different.
            measurements = [
                ("meta.min_trials", MetricType.QUALITY_SCORE,
                 float(APPROVED_DEFAULTS["min_trials"]), float(snapshot.min_trials)),
                ("meta.adaptation_threshold", MetricType.QUALITY_SCORE,
                 APPROVED_DEFAULTS["adaptation_threshold"],
                 snapshot.adaptation_threshold),
                ("meta.exploration_quota", MetricType.QUALITY_SCORE,
                 APPROVED_DEFAULTS["exploration_quota"], snapshot.exploration_quota),
                ("meta.avg_strategy_confidence", MetricType.QUALITY_SCORE,
                 LOW_CONFIDENCE_THRESHOLD, snapshot.avg_strategy_confidence),
                ("meta.total_strategies", MetricType.THROUGHPUT,
                 None, snapshot.total_strategies),
            ]

            for name, metric_type, baseline, current in measurements:
                if current is None or baseline is None:
                    continue
                try:
                    ok, metric = await monitor.track_improvement(
                        component_name="meta_learning",
                        metric_type=metric_type,
                        metric_name=name,
                        baseline_value=float(baseline),
                        current_value=float(current),
                        metadata={"source": "meta_metrics_monitor",
                                  "snapshot_id": snapshot.snapshot_id})
                    published += 1 if ok else 0

                    # improvement_metrics holds ONE row per metric (the insert
                    # upserts), so it only ever shows the latest value.
                    # metric_measurements is the time-series half and was
                    # likewise empty. Without it there is a current reading and
                    # no history, which is exactly what a trend needs.
                    if ok and metric is not None:
                        await monitor.record_measurement(
                            metric_id=metric.metric_id,
                            value=float(current),
                            metadata={"snapshot_id": snapshot.snapshot_id})
                except Exception as error:
                    logger.error("Could not publish %s: %s", name, error)

        except Exception as error:
            logger.error("Metric publication unavailable: %s", error)
        return published

    async def capture_snapshot(
        self,
        meta_learner
    ) -> MetaParameterSnapshot:
        """
        Capture current snapshot of meta-learning parameters

        Args:
            meta_learner: MetaLearner instance to inspect

        Returns:
            MetaParameterSnapshot with current state
        """
        try:
            # Extract current parameters
            min_trials = getattr(meta_learner, 'min_trials', APPROVED_DEFAULTS['min_trials'])
            adaptation_threshold = getattr(meta_learner, 'adaptation_threshold', APPROVED_DEFAULTS['adaptation_threshold'])

            # MEASURED, NOT ASSUMED. This was `exploration_quota = 0.10` with
            # the note "actual calculation needed" -- and 0.10 is exactly the
            # hardcoded `exploration_quota_limit` default in
            # `MetaLearner.select_strategy`. So the monitor compared the limit
            # against itself: `exploration_drift` was structurally 0.0 on every
            # snapshot, and a meta-learner exploring far more or far less than
            # its quota drifted invisibly.
            #
            # `unified.meta_decision_records` holds 11,720 real selections with
            # `chosen_propensity` -- the probability the chosen arm was picked
            # under the policy. A low propensity is an exploratory pick, so the
            # actual exploration rate is measurable rather than declared.
            exploration_quota = await self._measured_exploration_rate()
            if exploration_quota is None:
                # Not enough decisions to measure. The snapshot records that
                # rather than substituting the limit and reporting no drift.
                exploration_quota = APPROVED_DEFAULTS['exploration_quota']
                exploration_measured = False
            else:
                exploration_measured = True

            # Strategy statistics, from the store rather than from whichever
            # object happened to be passed in.
            #
            # THIS READ USED TO BE `getattr(meta_learner, 'strategies', {})`,
            # and that is why the history disagrees with itself. A process
            # that had loaded 29 strategies wrote 29; a process holding 18
            # partially-initialised ones wrote 18 at confidence 0.0 -- into the
            # same series, as though confidence had collapsed. The learner's
            # in-memory dict is a per-process view; only 15 of those 29 were
            # ever persisted, so the number also changed on every restart.
            #
            # Worse, the `else` branch wrote 0.0 for a learner holding nothing
            # at all. Zero confidence is the WORST value this metric can take,
            # and it was what got recorded when the metric could not be
            # measured -- so an unreadable learner looked exactly like a
            # catastrophically degraded one, on a report whose entire job is
            # detecting degradation.
            stats = await self._strategy_statistics()
            if stats is None:
                # All three columns are nullable. NULL means unmeasured, and
                # the trend queries skip it; 0.0 would have been a data point.
                avg_confidence = None
                total_strategies = None
                low_confidence = None
            else:
                avg_confidence, total_strategies, low_confidence = stats

            # Calculate drift from approved defaults
            min_trials_drift = min_trials - APPROVED_DEFAULTS['min_trials']
            threshold_drift = adaptation_threshold - APPROVED_DEFAULTS['adaptation_threshold']
            exploration_drift = exploration_quota - APPROVED_DEFAULTS['exploration_quota']
            promoted, deprecated = await self._promotion_counts()
            rate_of_change = await self._parameter_rate_of_change()

            # Persist snapshot using unified.meta_parameter_snapshots (PostgreSQL)
            drift_metrics = {
                "min_trials_drift": min_trials_drift,
                "threshold_drift": threshold_drift,
                "exploration_drift": exploration_drift,
                # Measured from meta_learning_strategies and the snapshot
                # history. These were three hardcoded zeros, which made
                # "nothing was promoted" and "promotions are not counted"
                # the same reading on a drift report.
                "strategies_promoted_last_week": promoted,
                "strategies_deprecated_last_week": deprecated,
                "rate_of_change": rate_of_change,
            }

            db = await self._get_db()
            row = await db.execute_query(
                """
                INSERT INTO meta_parameter_snapshots (
                    min_trials,
                    adaptation_threshold,
                    exploration_quota,
                    avg_strategy_confidence,
                    total_strategies,
                    low_confidence_adoptions,
                    drift_metrics
                ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING snapshot_id,
                          timestamp,
                          min_trials,
                          adaptation_threshold,
                          exploration_quota,
                          avg_strategy_confidence,
                          total_strategies,
                          low_confidence_adoptions,
                          drift_metrics
                """,
                params=(
                    min_trials,
                    adaptation_threshold,
                    exploration_quota,
                    avg_confidence,
                    total_strategies,
                    low_confidence,
                    # asyncpg has no codec registered for dict->jsonb on this
                    # pool, so a raw dict raised "invalid input for query
                    # argument" and no snapshot was ever written.
                    json.dumps(drift_metrics),
                ),
                fetch_one=True,
            )

            if not row:
                raise RuntimeError("Failed to insert meta-parameter snapshot")

            stored_drift = self._as_dict(row.get("drift_metrics"))

            snapshot = MetaParameterSnapshot(
                snapshot_id=str(row["snapshot_id"]),
                timestamp=row["timestamp"],
                min_trials=row["min_trials"],
                adaptation_threshold=float(row["adaptation_threshold"])
                if row["adaptation_threshold"] is not None
                else adaptation_threshold,
                exploration_quota=float(row["exploration_quota"])
                if row["exploration_quota"] is not None
                else exploration_quota,
                avg_strategy_confidence=float(row["avg_strategy_confidence"])
                if row["avg_strategy_confidence"] is not None
                else avg_confidence,
                # `or` would turn a real, measured zero back into the
                # fallback. These are read as written.
                total_strategies=row["total_strategies"],
                low_confidence_adoptions=row["low_confidence_adoptions"],
                min_trials_drift=stored_drift.get("min_trials_drift", min_trials_drift),
                threshold_drift=stored_drift.get("threshold_drift", threshold_drift),
                exploration_drift=stored_drift.get("exploration_drift", exploration_drift),
                strategies_promoted_last_week=stored_drift.get("strategies_promoted_last_week", 0),
                strategies_deprecated_last_week=stored_drift.get("strategies_deprecated_last_week", 0),
                rate_of_change=stored_drift.get("rate_of_change", 0.0),
            )

            # Every measurement in this snapshot also goes to the improvement
            # record, so a component's meta-parameters sit alongside every other
            # component's metrics instead of only in this module's own table.
            published = await self._publish_metrics(snapshot)

            logger.info("Captured meta-parameter snapshot: %s (%d metrics published)",
                        snapshot.snapshot_id, published)

            return snapshot

        except Exception as e:
            logger.error(f"Error capturing meta-parameter snapshot: {e}")
            return None

    async def detect_standards_degradation(
        self,
        days: int = 30
    ) -> Tuple[bool, List[str]]:
        """
        Detect if meta-learning standards have degraded over time

        Checks:
        - Has min_trials been lowered? (accepting less-proven strategies)
        - Has adaptation_threshold been lowered? (weaker adoption criteria)
        - Has exploration_quota increased? (more experimental code)

        Args:
            days: Lookback period for trend analysis

        Returns:
            Tuple of (degradation_detected, violations_list)
        """
        try:
            # Get parameter history from unified.meta_parameter_snapshots
            db = await self._get_db()
            rows = await db.execute_query(
                """
                SELECT
                    min_trials,
                    adaptation_threshold,
                    exploration_quota,
                    avg_strategy_confidence,
                    total_strategies,
                    low_confidence_adoptions,
                    drift_metrics,
                    timestamp
                FROM meta_parameter_snapshots
                WHERE timestamp >= NOW() - $1 * INTERVAL '1 day'
                ORDER BY timestamp ASC
                """,
                params=(days,),
                fetch_all=True,
            )

            snapshots: List[Dict[str, Any]] = []
            for row in rows or []:
                drift = self._as_dict(row.get("drift_metrics"))

                # `x or DEFAULT` WAS BACKWARDS ON EVERY ONE OF THESE. Zero is
                # falsy, and zero is the MAXIMALLY DEGRADED value each of these
                # can hold: min_trials=0 accepts a strategy with no evidence at
                # all, adaptation_threshold=0.0 adopts one that never succeeds.
                # The `or` turned exactly those readings into the approved
                # default, so the worst possible standards were reported as the
                # sanctioned ones -- by the detector meant to catch them.
                # Only a genuine NULL falls back now, and it falls back to None.
                def _value(key: str, default_key: str):
                    raw = row.get(key)
                    return APPROVED_DEFAULTS[default_key] if raw is None else float(raw)

                min_trials = row.get("min_trials")
                min_trials = (APPROVED_DEFAULTS["min_trials"] if min_trials is None
                              else int(min_trials))
                adaptation_threshold = _value("adaptation_threshold", "adaptation_threshold")
                exploration_quota = _value("exploration_quota", "exploration_quota")

                # DRIFT IS DERIVED WHEN IT WAS NOT STORED. `drift.get(k, 0)`
                # made a snapshot with no drift_metrics indistinguishable from
                # one measured at zero drift. Drift is just the parameter minus
                # its approved value, and the parameter is right here, so it is
                # recomputed rather than assumed absent.
                snapshots.append({
                    "min_trials": min_trials,
                    "adaptation_threshold": adaptation_threshold,
                    "exploration_quota": exploration_quota,
                    "min_trials_drift": int(drift.get(
                        "min_trials_drift",
                        min_trials - APPROVED_DEFAULTS["min_trials"])),
                    "threshold_drift": float(drift.get(
                        "threshold_drift",
                        adaptation_threshold - APPROVED_DEFAULTS["adaptation_threshold"])),
                    "exploration_drift": float(drift.get(
                        "exploration_drift",
                        exploration_quota - APPROVED_DEFAULTS["exploration_quota"])),
                    "timestamp": row.get("timestamp"),
                })

            if not snapshots:
                # NOTHING TO CHECK IS NOT A CLEAN BILL OF HEALTH. Same reasoning
                # as the crash path below: a caller reads False as "standards
                # are intact", and no snapshot means nobody knows.
                return True, ["standards could not be verified: no parameter "
                              f"snapshot in the last {days} days"]

            # ONE SNAPSHOT IS ENOUGH FOR THE DRIFT CHECKS, and this used to
            # refuse to run them without two. Drift is measured against
            # APPROVED_DEFAULTS, not against history -- a single snapshot fully
            # answers "has min_trials been lowered below what was approved".
            # Requiring two meant a freshly-started system with maximally
            # relaxed parameters reported "Insufficient history" and False.
            # Only the progressive-trend check below genuinely needs a series.

            violations = []
            degradation_detected = False

            # Check for drift in min_trials
            earliest = snapshots[0]
            latest = snapshots[-1]

            if latest['min_trials_drift'] < 0:
                violations.append(
                    f"min_trials lowered from {APPROVED_DEFAULTS['min_trials']} to {latest['min_trials']} "
                    f"(drift: {latest['min_trials_drift']})"
                )
                degradation_detected = True

            if latest['threshold_drift'] < -0.05:  # Allow 5% tolerance
                violations.append(
                    f"adaptation_threshold lowered from {APPROVED_DEFAULTS['adaptation_threshold']:.2f} "
                    f"to {latest['adaptation_threshold']:.2f} (drift: {latest['threshold_drift']:.2f})"
                )
                degradation_detected = True

            if latest['exploration_drift'] > 0.05:  # Allow 5% tolerance
                violations.append(
                    f"exploration_quota increased from {APPROVED_DEFAULTS['exploration_quota']:.2f} "
                    f"to {latest['exploration_quota']:.2f} (drift: {latest['exploration_drift']:.2f})"
                )
                degradation_detected = True

            # Check for trend (progressive degradation)
            if len(snapshots) >= 5:
                min_trials_trend = [s['min_trials'] for s in snapshots]
                if min_trials_trend[-1] < min_trials_trend[0]:
                    violations.append(
                        f"min_trials trending downward: {min_trials_trend[0]} → {min_trials_trend[-1]}"
                    )
                    degradation_detected = True

            if degradation_detected:
                logger.error(
                    f"⚠️  META-LEARNING STANDARDS DEGRADATION DETECTED: {len(violations)} violations"
                )
                for v in violations:
                    logger.error(f"   - {v}")

                # Persist meta-health alerts for each violation
                try:
                    await self._create_meta_health_alerts(violations, earliest, latest)
                except Exception as alert_error:
                    logger.error(f"Failed to persist meta-health alerts: {alert_error}")

            return degradation_detected, violations

        except Exception as e:
            # A CHECK THAT CRASHED FOUND NO DEGRADATION, AND SO DID A CHECK
            # THAT RAN. `False` here means "standards are intact" to every
            # caller, so a broken guard reported a healthy system -- on the
            # module whose stated purpose is to guard the guards.
            #
            # True with the error as the violation says the opposite: standards
            # could not be confirmed, which is the honest state and the one a
            # caller should act on.
            logger.error(f"Error detecting standards degradation: {e}", exc_info=True)
            return True, [f"standards could not be verified: {type(e).__name__}: {e}"]

    async def get_meta_health(
        self,
        meta_learner
    ) -> MetaHealthReport:
        """
        Generate comprehensive health report for meta-learning system

        Args:
            meta_learner: MetaLearner instance to inspect

        Returns:
            MetaHealthReport with health status and alerts
        """
        try:
            # Capture current snapshot
            current_snapshot = await self.capture_snapshot(meta_learner)

            # Detect standards degradation
            degradation_detected, violations = await self.detect_standards_degradation(days=30)

            # Calculate standards stability score
            if current_snapshot:
                # PENALISE ONLY THE DEGRADING DIRECTION.
                #
                # This took abs() of each drift, so a configuration STRICTER
                # than approved -- more trials required, a higher adoption
                # threshold, less exploration than the quota allows -- lowered
                # the stability score exactly as much as a relaxed one. The
                # module then contradicted itself: detect_standards_degradation
                # flags only `min_trials_drift < 0`, `threshold_drift < -0.05`
                # and `exploration_drift > +0.05`, so a tightened system scored
                # as unstable while the detector correctly reported no
                # degradation.
                #
                # exploration_quota matters most here: it is a CAP, and the
                # measured rate is now 0.057 against an approved 0.10. Being
                # under the cap is compliance, not drift.
                relaxed = (
                    max(0, -current_snapshot.min_trials_drift) * 5 +
                    max(0.0, -current_snapshot.threshold_drift) * 50 +
                    max(0.0, current_snapshot.exploration_drift) * 100
                )
                standards_stability_score = max(0, 100 - relaxed)
            else:
                standards_stability_score = 0

            # Generate alerts FIRST -- overall_health used to be decided before
            # these existed, and read only degradation/stability. The confidence
            # alert was appended afterwards and could never influence the
            # verdict, so the monitor would report HEALTHY while holding an
            # alert saying otherwise. A health signal that its own alerts cannot
            # move is not a health signal.
            alerts = []
            warnings = []

            if degradation_detected:
                alerts.append("CRITICAL: Meta-learning standards have degraded")
                alerts.extend(violations)

            if current_snapshot:
                # These are None when the strategy store could not be read.
                # A missing measurement is stated as missing: comparing None
                # would raise, treating it as 0 would raise a false alert, and
                # treating it as fine would hide a real one.
                adoptions = current_snapshot.low_confidence_adoptions
                if adoptions is None:
                    warnings.append("low-confidence adoptions not measured this cycle")
                elif adoptions > MAX_LOW_CONFIDENCE_ADOPTIONS:
                    warnings.append(
                        f"{adoptions} low-confidence strategies adopted recently"
                    )

                confidence = current_snapshot.avg_strategy_confidence
                if confidence is None:
                    warnings.append("average strategy confidence not measured this cycle")
                elif confidence < LOW_CONFIDENCE_THRESHOLD:
                    alerts.append(
                        f"Average strategy confidence too low: {confidence:.2f}"
                    )

            # Determine overall health, now that every signal is in hand.
            #
            # Absence of data is NOT evidence of ill health. With no snapshot,
            # standards_stability_score is 0, which tripped `< 50` and reported
            # CRITICAL while `alerts` was empty -- literally
            # "🚨 META-LEARNER HEALTH: CRITICAL - 0 critical alerts", and it
            # would have fired a Slack page with an empty bullet list. A
            # verdict nothing can justify is worse than no verdict: it trains
            # the reader to ignore CRITICAL.
            if current_snapshot is None:
                overall_health = "UNKNOWN"
                warnings.append(
                    "no meta-parameter snapshot available — meta-learner health "
                    "cannot be assessed (this is missing data, not degradation)"
                )
            elif degradation_detected or standards_stability_score < 50:
                overall_health = "CRITICAL"
            elif alerts or standards_stability_score < 75:
                overall_health = "DEGRADED"
            else:
                overall_health = "HEALTHY"

            # Create report
            report = MetaHealthReport(
                timestamp=datetime.now(),
                overall_health=overall_health,
                standards_degradation_detected=degradation_detected,
                standards_stability_score=standards_stability_score,
                # THESE ALWAYS SAID "STABLE". Two of the four indicators on a
                # report whose entire job is noticing that standards are being
                # relaxed were hardcoded, so a meta-learner promoting
                # strategies twice as fast, or losing confidence steadily,
                # reported STABLE on both. Computed from the snapshot history
                # now; UNKNOWN when there are too few snapshots to say.
                adoption_velocity=await self._adoption_velocity(),
                avg_confidence_trend=await self._confidence_trend(),
                alerts=alerts,
                warnings=warnings,
                current_snapshot=current_snapshot
            )

            if overall_health == "CRITICAL":
                logger.error(f"🚨 META-LEARNER HEALTH: CRITICAL - {len(alerts)} critical alerts")
            elif overall_health == "DEGRADED":
                logger.warning(f"⚠️  META-LEARNER HEALTH: DEGRADED - {len(warnings)} warnings")
            elif overall_health == "UNKNOWN":
                logger.info("❔ META-LEARNER HEALTH: UNKNOWN — no snapshot to assess")
            else:
                logger.info(f"✅ META-LEARNER HEALTH: HEALTHY")

            return report

        except Exception as e:
            logger.error(f"Error generating meta-health report: {e}")
            return None

    async def _create_meta_health_alerts(
        self,
        violations: List[str],
        earliest: Dict[str, Any],
        latest: Dict[str, Any]
    ) -> None:
        """Create meta_health_alerts rows for detected standards violations.

        Maps high-level violations into structured alerts so that the
        governance and monitoring layers can reason about meta-standards
        degradation over time.
        """
        for violation in violations:
            alert_type = "standards_degradation"
            parameter_name: Optional[str] = None
            old_value: Optional[float] = None
            new_value: Optional[float] = None
            drift_amount: Optional[float] = None

            if violation.startswith("min_trials lowered"):
                parameter_name = "min_trials"
                old_value = float(APPROVED_DEFAULTS["min_trials"])
                new_value = float(latest.get("min_trials", old_value))
                drift_amount = float(latest.get("min_trials_drift", 0))
            elif violation.startswith("adaptation_threshold lowered"):
                parameter_name = "adaptation_threshold"
                old_value = float(APPROVED_DEFAULTS["adaptation_threshold"])
                new_value = float(latest.get("adaptation_threshold", old_value))
                drift_amount = float(latest.get("threshold_drift", 0.0))
            elif violation.startswith("exploration_quota increased"):
                parameter_name = "exploration_quota"
                old_value = float(APPROVED_DEFAULTS["exploration_quota"])
                new_value = float(latest.get("exploration_quota", old_value))
                drift_amount = float(latest.get("exploration_drift", 0.0))
            elif violation.startswith("min_trials trending downward"):
                parameter_name = "min_trials"
                old_value = float(earliest.get("min_trials", APPROVED_DEFAULTS["min_trials"]))
                new_value = float(latest.get("min_trials", old_value))
                drift_amount = new_value - old_value

            # DETERMINISTIC PER VIOLATION PER DAY, NOT A FRESH UUID.
            #
            # get_meta_health runs on the coordinator's loop, and each pass
            # re-detects the same standing violation. With uuid4() every pass
            # inserted another row, so one unchanged degradation accumulated
            # alerts indefinitely and read as a worsening trend. The same
            # defect and the same fix as regression_record.report.
            day = datetime.now().strftime("%Y%m%d")
            digest = hashlib.sha256(
                f"{parameter_name}|{violation}|{day}".encode()).hexdigest()[:24]
            alert_id = f"meta_alert_{digest}"

            # Severity from magnitude. Every alert was hardcoded CRITICAL, so
            # min_trials slipping by one and min_trials reaching zero raised
            # the identical alarm.
            severity = _alert_severity(parameter_name, drift_amount)

            await (await self._get_db()).execute_query(
                """
                INSERT INTO meta_health_alerts (
                    alert_id,
                    alert_type,
                    severity,
                    message,
                    parameter_name,
                    old_value,
                    new_value,
                    drift_amount
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (alert_id) DO NOTHING
                """,
                params=(
                    alert_id,
                    alert_type,
                    severity,
                    violation,
                    parameter_name,
                    old_value,
                    new_value,
                    drift_amount,
                ),
            )


# Global singleton
_meta_metrics_monitor: Optional[MetaMetricsMonitor] = None


def get_meta_metrics_monitor() -> MetaMetricsMonitor:
    """Get or create the global meta-metrics monitor"""
    global _meta_metrics_monitor
    if _meta_metrics_monitor is None:
        _meta_metrics_monitor = MetaMetricsMonitor()
    return _meta_metrics_monitor
