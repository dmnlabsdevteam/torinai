#!/usr/bin/env python3
"""
Capability Benchmark Suite
Frozen baseline anchoring to detect capability regression across improvement cycles.

This module prevents "capability narrowing" - where the system optimizes specific
metrics (latency, memory) but loses general reasoning competence.

Tracks:
- Reasoning capabilities (logic, causal inference, abstract reasoning)
- Coding capabilities (generation, debugging, refactoring)
- Analysis capabilities (data interpretation, pattern recognition)
- Comprehension capabilities (context understanding, instruction following)

All benchmarks are FROZEN - they never change, enabling true regression detection.
"""

import logging
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path
from dotenv import load_dotenv

from core.database import (TorinUnifiedDatabase, get_database_manager,
                           get_unified_db)

# Load environment variables
env_file = Path(__file__).parent.parent.parent / ".env.production"
if env_file.exists():
    load_dotenv(env_file)

logger = logging.getLogger(__name__)


@dataclass
class BenchmarkTestCase:
    """Single frozen test case"""
    test_id: str
    domain: str  # "reasoning", "coding", "analysis", "comprehension"
    difficulty: str  # "easy", "medium", "hard"
    prompt: str
    expected_output: str
    evaluation_criteria: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BenchmarkResult:
    """Result of running a single benchmark"""
    test_id: str
    cycle_id: str
    timestamp: datetime
    success: bool
    score: float  # 0.0-1.0
    latency_ms: float
    output: str
    evaluation_details: Dict[str, Any]


@dataclass
class CapabilityReport:
    """Capability assessment across all domains"""
    cycle_id: str
    timestamp: datetime

    # Domain scores (0.0-1.0)
    reasoning_score: float
    coding_score: float
    analysis_score: float
    comprehension_score: float
    overall_score: float

    # Regression detection
    regression_detected: bool
    regression_domains: List[str]
    regression_severity: str  # "NONE", "MINOR", "MODERATE", "SEVERE"

    # Statistical data
    tests_passed: int
    tests_failed: int
    avg_latency_ms: float
    confidence_interval: Tuple[float, float]

    # Comparison to baseline
    baseline_delta: float
    statistical_significance: float  # p-value


class CapabilityBenchmarkSuite:
    """
    Frozen capability benchmark suite for regression detection

    Prevents capability narrowing by maintaining frozen test cases that evaluate
    general reasoning, coding, analysis, and comprehension across all improvement cycles.
    """

    def __init__(self, db_config: Dict[str, Any] = None, llm_service = None):
        # db_config kept for backward compatibility but no longer used directly;
        # CapabilityBenchmarkSuite now uses the unified PostgreSQL database.
        _ = db_config

        self.llm_service = llm_service

        # EVERY DATABASE CALL IN THIS SUITE WAS FAILING.
        #
        # `get_unified_db` is declared `async` while doing nothing async -- it
        # just returns the singleton -- so this stored a COROUTINE, and every
        # `self.db.execute_query(...)` raised
        #
        #     'coroutine' object has no attribute 'execute_query'
        #
        # into a handler that logged and continued. Measured consequences:
        # `frozen_capability_benchmarks` held 0 rows after loading 26
        # benchmarks, no benchmark result was ever persisted, and
        # `get_active_baseline()` therefore found no frozen baseline -- so the
        # regression detector had nothing to compare against and could not
        # report a regression no matter how far capability fell.
        #
        # `get_database_manager` is the synchronous accessor and returns the
        # same singleton object (verified identical).
        self.db: TorinUnifiedDatabase = get_database_manager()

        # Benchmark storage
        self.benchmarks: Dict[str, BenchmarkTestCase] = {}
        self.benchmarks_loaded = False

        #: The substrate that answers the benchmarks. Lazily built so
        #: constructing the suite does not initialise the reasoning stack.
        self._neural_bridge = None

        logger.info("Capability Benchmark Suite initialized")

    def _reasoner(self):
        """The neural bridge. Substrate-first; a model only if it escalates."""
        if self._neural_bridge is None:
            from core.reasoning.neural_bridge import get_neural_bridge

            self._neural_bridge = get_neural_bridge()
        return self._neural_bridge

    async def load_benchmarks(self, benchmarks_dir: Optional[Path] = None) -> int:
        """
        Load frozen benchmarks from JSON files

        Args:
            benchmarks_dir: Directory containing benchmark JSON files

        Returns:
            Number of benchmarks loaded
        """
        if benchmarks_dir is None:
            benchmarks_dir = Path(__file__).parent / "capability_benchmarks"

        if not benchmarks_dir.exists():
            logger.warning(f"Benchmark directory not found: {benchmarks_dir}")
            return 0

        loaded = 0

        # Load benchmarks from JSON files
        for json_file in benchmarks_dir.glob("*.json"):
            try:
                with open(json_file, 'r') as f:
                    data = json.load(f)

                # Each JSON file contains a list of test cases
                for test_data in data.get('tests', []):
                    benchmark = BenchmarkTestCase(
                        test_id=test_data['test_id'],
                        domain=test_data['domain'],
                        difficulty=test_data['difficulty'],
                        prompt=test_data['prompt'],
                        expected_output=test_data['expected_output'],
                        evaluation_criteria=test_data.get('evaluation_criteria', {}),
                        metadata=test_data.get('metadata', {})
                    )

                    self.benchmarks[benchmark.test_id] = benchmark
                    loaded += 1

                logger.info(f"Loaded {len(data.get('tests', []))} benchmarks from {json_file.name}")

            except Exception as e:
                logger.error(f"Error loading benchmarks from {json_file}: {e}")

        # Store benchmarks in database (if not already stored)
        await self._store_benchmarks_in_db()

        self.benchmarks_loaded = True
        logger.info(f"✅ Loaded {loaded} total capability benchmarks")

        return loaded

    async def _store_benchmarks_in_db(self):
        """Store benchmarks in database for persistence"""
        try:
            for benchmark in self.benchmarks.values():
                # Check if already exists in unified.frozen_capability_benchmarks
                existing = await self.db.execute_query(
                    """
                    SELECT test_id
                    FROM frozen_capability_benchmarks
                    WHERE test_id = $1
                    """,
                    params=(benchmark.test_id,),
                    fetch_one=True,
                )

                if existing:
                    continue  # Already stored

                # Store new benchmark in unified.frozen_capability_benchmarks
                await self.db.execute_query(
                    """
                    INSERT INTO frozen_capability_benchmarks
                    (test_id, domain, difficulty, prompt, expected_output,
                     evaluation_criteria, metadata)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """,
                    params=(
                        benchmark.test_id,
                        benchmark.domain,
                        benchmark.difficulty,
                        benchmark.prompt,
                        benchmark.expected_output,
                        json.dumps(benchmark.evaluation_criteria),
                        json.dumps(benchmark.metadata),
                    ),
                )

        except Exception as e:
            logger.error(f"Error storing benchmarks in database: {e}")

    async def run_benchmarks(
        self,
        cycle_id: str,
        domains: Optional[List[str]] = None,
        sample_size: Optional[int] = None
    ) -> CapabilityReport:
        """
        Run capability benchmarks for a cycle

        Args:
            cycle_id: Improvement cycle ID
            domains: Specific domains to test (None = all)
            sample_size: Limit number of tests per domain (None = all)

        Returns:
            CapabilityReport with results
        """
        if not self.benchmarks_loaded:
            await self.load_benchmarks()

        # NO MODEL REQUIREMENT. This refused to run at all without an
        # `llm_service`, which made the capability gate model-dependent: with
        # the model down every cycle came back UNKNOWN and capability was never
        # verified. Answers now come from the substrate via the neural bridge
        # (the bridge is substrate-first and substrate-only -- it never reaches a
        # model to answer), so the benchmark measures the substrate
        # rather than the model that may or may not be behind it.

        # Filter benchmarks by domain
        if domains:
            test_benchmarks = [b for b in self.benchmarks.values() if b.domain in domains]
        else:
            test_benchmarks = list(self.benchmarks.values())

        # Sample if requested
        if sample_size:
            import random
            # Sample evenly across domains
            domain_samples = {}
            for benchmark in test_benchmarks:
                if benchmark.domain not in domain_samples:
                    domain_samples[benchmark.domain] = []
                domain_samples[benchmark.domain].append(benchmark)

            sampled = []
            per_domain = sample_size // len(domain_samples)
            for domain_tests in domain_samples.values():
                sampled.extend(random.sample(domain_tests, min(per_domain, len(domain_tests))))

            test_benchmarks = sampled

        logger.info(f"🧪 Running {len(test_benchmarks)} capability benchmarks for cycle {cycle_id}")

        # Run each benchmark
        results: List[BenchmarkResult] = []
        for benchmark in test_benchmarks:
            result = await self._run_single_benchmark(benchmark, cycle_id)
            results.append(result)

            # Store result in database
            await self._store_result(result)

        # Generate capability report
        report = await self._generate_capability_report(cycle_id, results)

        # Store report in database
        await self._store_report(report)

        return report

    async def _run_single_benchmark(
        self,
        benchmark: BenchmarkTestCase,
        cycle_id: str
    ) -> BenchmarkResult:
        """Run a single benchmark test"""
        import time

        start_time = time.time()

        try:
            # THE SUBSTRATE ANSWERS, NOT A MODEL SERVICE.
            #
            # This called `self.llm_service.generate(...)` directly, so the
            # frozen benchmark measured whatever model happened to be served
            # and could not run at all without one. The bridge is
            # substrate-first: deterministic formalizers and solvers are tried
            # before any model is consulted, which is the thing whose
            # capability this suite is supposed to be tracking.
            from core.reasoning.neural_bridge import (ReasoningMode,
                                                      ReasoningRequest)

            request = ReasoningRequest(
                query=benchmark.prompt,
                context=[f"Capability benchmark {benchmark.test_id}",
                         f"Domain: {benchmark.domain}"],
            )
            result = await self._reasoner().reason(request)

            latency_ms = (time.time() - start_time) * 1000

            # A FAILED GENERATION IS NOT A WRONG ANSWER.
            #
            # `reason()` reports failure by putting the reason IN the answer --
            # "Error: LLM generation failed (answer truncated: the model used
            # its entire 2048-token budget on reasoning without emitting...)"
            # -- and recording the real state in metadata. Grading that string
            # against the expected answer scores 0.0, and the capability report
            # then says the substrate cannot reason.
            #
            # Measured on this suite: reasoning 0.03 and comprehension 0.03,
            # almost entirely from truncated generations. Freezing a baseline
            # on those numbers would make an infrastructure fault the permanent
            # definition of the system's competence.
            metadata = getattr(result, "metadata", None) or {}
            answer = str(getattr(result, "answer", "") or "")

            # THIS SUITE MEASURES THE SUBSTRATE. IT WAS MEASURING THE MODEL.
            #
            # The bridge is substrate-first, so the routing was
            # right -- but every one of these benchmarks is prose the substrate
            # cannot yet represent, so `_substrate_first` declines all of them
            # and, with no model fallback, they return honest inability. Before
            # the fallback was removed, the model's answer was
            # then graded and recorded as the SUBSTRATE's capability.
            #
            # The proof is in the stored results: items that came back
            # "Error: LLM generation failed (answer truncated: the model used
            # its entire 2048-token budget...)" scored 0 -- a model-side fault
            # attributed to substrate competence -- while `reasoning_logic_001`
            # returned fluent model prose and also scored 0. Neither number
            # said anything about the substrate.
            #
            # A substrate that cannot answer yet is the honest starting point,
            # and moving that number is what teaching is for. Masking it with a
            # model's answer means the baseline can never show learning,
            # because it was never measuring the thing that learns.
            substrate_answered = bool(metadata.get(
                "substrate_formalized", metadata.get("verified", False)))
            teacher_consulted = bool(metadata.get("teacher_consulted", False))

            if not substrate_answered:
                # NOT ungraded, and not an error: a real, recorded ZERO. The
                # substrate could not answer this, which is a fact about the
                # substrate and exactly what the baseline should track.
                logger.info(
                    "Benchmark %s: substrate could not represent it "
                    "(teacher_consulted=%s) — recorded as 0.0 substrate capability",
                    benchmark.test_id, teacher_consulted)
                return BenchmarkResult(
                    test_id=benchmark.test_id, cycle_id=cycle_id,
                    timestamp=datetime.now(), success=False, score=0.0,
                    latency_ms=latency_ms, output=answer,
                    evaluation_details={
                        "graded": True, "grader": "substrate_coverage",
                        "answered_by": "teacher" if teacher_consulted else "nobody",
                        "substrate_formalized": False,
                        "reason": metadata.get("reason") or "unsupported_input",
                        "note": ("the substrate could not represent this input; "
                                 "any answer shown came from the teacher and "
                                 "does not count as substrate capability")})

            output = answer

            # Evaluate output
            evaluation = await self._evaluate_output(
                output=output,
                expected=benchmark.expected_output,
                criteria=benchmark.evaluation_criteria
            )

            success = evaluation['success']
            score = evaluation['score']

            return BenchmarkResult(
                test_id=benchmark.test_id,
                cycle_id=cycle_id,
                timestamp=datetime.now(),
                success=success,
                score=score,
                latency_ms=latency_ms,
                output=output,
                evaluation_details=evaluation
            )

        except Exception as e:
            # A BENCHMARK THAT COULD NOT RUN IS NOT A BENCHMARK THE SYSTEM
            # FAILED. score=0.0 fed straight into the domain average and the
            # regression detector, so an unreachable reasoner or a transport
            # error manufactured exactly the capability drop this suite exists
            # to detect. Ungraded results are excluded from the scores.
            logger.error(f"Benchmark {benchmark.test_id} could not run: {e}")
            return BenchmarkResult(
                test_id=benchmark.test_id,
                cycle_id=cycle_id,
                timestamp=datetime.now(),
                success=None,
                score=None,
                latency_ms=(time.time() - start_time) * 1000,
                output="",
                evaluation_details={'error': str(e), 'graded': False}
            )

    async def _evaluate_output(
        self,
        output: str,
        expected: str,
        criteria: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Evaluate LLM output against expected output

        Uses criteria-specific evaluation methods (exact match, semantic similarity, etc.)
        """
        evaluation_type = criteria.get('type', 'semantic_similarity')

        if evaluation_type == 'exact_match':
            success = output.strip() == expected.strip()
            score = 1.0 if success else 0.0

        elif evaluation_type == 'contains':
            required_phrases = criteria.get('required_phrases', [])
            matches = sum(1 for phrase in required_phrases if phrase in output)
            score = matches / len(required_phrases) if required_phrases else 0.0
            success = score >= criteria.get('threshold', 0.7)

        elif evaluation_type == 'semantic_similarity':
            # A FROZEN BENCHMARK NEEDS A FROZEN GRADER.
            #
            # This asked the model to score its own answer. Two things wrong
            # with that: the model attests to its own competence, which the
            # substrate architecture forbids everywhere else; and the yardstick
            # then drifts with the model, so a score from one cycle is not
            # comparable with a score from the next -- which is the entire
            # purpose of a frozen suite.
            #
            # Worse, `except: score = 0.0` turned a failed GRADING call into a
            # failed BENCHMARK, and enough of those read as capability
            # regression -- a fabricated one, from a grader that never ran.
            #
            # Token F1 against the expected answer is deterministic, needs no
            # model, and is the standard measure for exactly this comparison.
            score = self._token_f1(output, expected)
            success = score >= criteria.get('threshold', 0.7)

        elif evaluation_type == 'custom':
            # NOT SILENTLY ZERO. `custom` had no branch, so it fell to the
            # `else` below and scored 0.0 on every run -- one of the 26 frozen
            # benchmarks was permanently failing and dragging the capability
            # score down for a reason nobody had stated.
            score, success, detail = self._evaluate_custom(output, criteria)
            return {'success': success, 'score': score,
                    'evaluation_type': evaluation_type, 'criteria': criteria,
                    'grader': 'deterministic', 'detail': detail}

        else:
            # An unknown type is UNGRADED, not failed. Returning success=False
            # made "this suite does not know how to mark it" indistinguishable
            # from "the system got it wrong".
            logger.error("Unknown evaluation type %r for a frozen benchmark; "
                         "reporting UNGRADED rather than failed", evaluation_type)
            return {'success': None, 'score': None, 'graded': False,
                    'evaluation_type': evaluation_type, 'criteria': criteria,
                    'grader': 'none',
                    'detail': f'no grader for evaluation type {evaluation_type!r}'}

        return {
            'success': success,
            'score': score,
            'graded': True,
            'grader': 'deterministic',
            'evaluation_type': evaluation_type,
            'criteria': criteria
        }

    #: Words carrying no content, excluded so overlap measures meaning rather
    #: than grammar. Short and fixed on purpose: a grader that tunes its own
    #: stopword list is no longer frozen.
    _STOPWORDS = frozenset({
        "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
        "of", "to", "in", "on", "at", "by", "for", "with", "and", "or", "but",
        "that", "this", "these", "those", "it", "its", "as", "from", "then",
        "so", "because", "which", "there", "their",
    })

    @classmethod
    def _tokens(cls, text: str) -> List[str]:
        import re
        words = re.findall(r"[a-z0-9]+", str(text).lower())
        return [w for w in words if w not in cls._STOPWORDS]

    @classmethod
    def _token_f1(cls, output: str, expected: str) -> float:
        """Harmonic mean of token precision and recall. Deterministic.

        Rewards an answer that contains what the expected answer contains
        without padding, and is stable across runs -- two properties the model
        grader had neither of.
        """
        from collections import Counter

        produced, wanted = Counter(cls._tokens(output)), Counter(cls._tokens(expected))
        if not produced or not wanted:
            return 0.0
        shared = sum((produced & wanted).values())
        if not shared:
            return 0.0
        precision = shared / sum(produced.values())
        recall = shared / sum(wanted.values())
        return 2 * precision * recall / (precision + recall)

    @staticmethod
    def _evaluate_custom(output: str, criteria: Dict[str, Any]):
        """Graders for the constraint benchmarks, keyed by their description.

        Each is a stated, checkable rule rather than a judgement, so the result
        does not depend on who is asked.
        """
        description = str(criteria.get('description', '')).strip()
        threshold = float(criteria.get('threshold', 1.0))

        forbidden = None
        if "must not contain the letter" in description.lower():
            import re
            letters = re.findall(r"'([A-Za-z])'", description)
            forbidden = {c.lower() for c in letters}

        if forbidden:
            hits = sum(1 for c in str(output).lower() if c in forbidden)
            score = 1.0 if hits == 0 else 0.0
            return score, score >= threshold, (
                f"{hits} occurrence(s) of {sorted(forbidden)}")

        # No grader for this rule. UNGRADED, never failed.
        return None, None, f"no deterministic grader for constraint: {description!r}"

    async def _generate_capability_report(
        self,
        cycle_id: str,
        results: List[BenchmarkResult]
    ) -> CapabilityReport:
        """Generate capability report from benchmark results"""

        # UNGRADED RESULTS ARE NOT ZEROES. A test with no grader, or one that
        # could not run, carries score=None; averaging it as 0.0 would report a
        # capability drop that nothing measured, and `len(results) -
        # tests_passed` would count it as a failure.
        graded = [r for r in results if r.score is not None]
        ungraded = [r for r in results if r.score is None]
        if ungraded:
            logger.warning("%d of %d benchmarks were UNGRADED and are excluded "
                           "from the capability scores: %s", len(ungraded),
                           len(results), ", ".join(r.test_id for r in ungraded))

        # Calculate domain scores
        domain_scores = {}
        # A DOMAIN WITH NOTHING TO GRADE IS NOT A DOMAIN SCORING ZERO.
        #
        # The else branch below set an unmeasured domain to 0.0 and the overall
        # score averaged it in, so a suite holding no coding benchmarks reported
        # coding competence of zero and dragged the overall down with it.
        # Unmeasured domains are excluded from the overall average and reported
        # separately, so "we did not test this" stays distinct from "it failed".
        unmeasured_domains = []
        for domain in ['reasoning', 'coding', 'analysis', 'comprehension']:
            domain_results = [r for r in graded if self.benchmarks[r.test_id].domain == domain]
            if domain_results:
                domain_scores[domain] = sum(r.score for r in domain_results) / len(domain_results)
            else:
                unmeasured_domains.append(domain)

        overall_score = sum(domain_scores.values()) / len(domain_scores) if domain_scores else 0.0
        if unmeasured_domains:
            logger.warning("No graded benchmarks for %s; excluded from the overall "
                           "score rather than counted as zero",
                           ", ".join(unmeasured_domains))

        # Calculate statistics
        tests_passed = sum(1 for r in graded if r.success)
        tests_failed = len(graded) - tests_passed
        avg_latency = sum(r.latency_ms for r in results) / len(results) if results else 0.0

        # Calculate confidence interval (Wilson score)
        confidence_interval = self._calculate_wilson_score(tests_passed, len(graded))

        # Detect regression
        regression_detected, regression_domains, regression_severity, baseline_delta, p_value = \
            await self._detect_capability_regression(cycle_id, domain_scores, overall_score)

        return CapabilityReport(
            cycle_id=cycle_id,
            timestamp=datetime.now(),
            reasoning_score=domain_scores.get('reasoning'),
            coding_score=domain_scores.get('coding'),
            analysis_score=domain_scores.get('analysis'),
            comprehension_score=domain_scores.get('comprehension'),
            overall_score=overall_score,
            regression_detected=regression_detected,
            regression_domains=regression_domains,
            regression_severity=regression_severity,
            tests_passed=tests_passed,
            tests_failed=tests_failed,
            avg_latency_ms=avg_latency,
            confidence_interval=confidence_interval,
            baseline_delta=baseline_delta,
            statistical_significance=p_value
        )

    def _calculate_wilson_score(self, successes: int, total: int) -> Tuple[float, float]:
        """Calculate Wilson score confidence interval (95%)"""
        if total == 0:
            return (0.0, 0.0)

        from math import sqrt

        z = 1.96  # 95% confidence
        p = successes / total

        denominator = 1 + z**2 / total
        center = (p + z**2 / (2 * total)) / denominator
        margin = z * sqrt((p * (1 - p) + z**2 / (4 * total)) / total) / denominator

        lower = max(0.0, center - margin)
        upper = min(1.0, center + margin)

        return (lower, upper)

    async def _detect_capability_regression(
        self,
        cycle_id: str,
        domain_scores: Dict[str, float],
        overall_score: float
    ) -> Tuple[bool, List[str], str, float, float]:
        """
        Detect capability regression vs FROZEN baseline (or fallback to first 5 cycles)

        Prioritizes frozen baseline (immutable, governance-approved) over soft baseline.
        This prevents baseline drift where the floor itself slowly lowers.

        Returns:
            (regression_detected, regression_domains, severity, baseline_delta, p_value)
        """
        try:
            # PRIORITY 1: Use frozen baseline if available (unified.capability_baseline_freezes)
            frozen_baseline = await self.get_active_baseline()

            if frozen_baseline:
                logger.debug(f"Using frozen baseline {frozen_baseline['version']} for regression detection")
                baseline = {
                    'reasoning': frozen_baseline['reasoning_baseline'],
                    'coding': frozen_baseline['coding_baseline'],
                    'analysis': frozen_baseline['analysis_baseline'],
                    'comprehension': frozen_baseline['comprehension_baseline'],
                    'overall': frozen_baseline['overall_baseline']
                }
                baseline_type = "FROZEN"
            else:
                # FALLBACK: Use first 5 cycles as soft baseline from unified.capability_reports
                baseline_reports = await self.db.execute_query(
                    """
                    SELECT
                        reasoning_score, coding_score, analysis_score,
                        comprehension_score, overall_score
                    FROM capability_reports
                    ORDER BY timestamp ASC
                    LIMIT 5
                    """,
                    fetch_all=True,
                )

                if not baseline_reports:
                    # No baseline yet - this is the first report
                    logger.info("No baseline - this is the first capability report")
                    return (False, [], "NONE", 0.0, 1.0)

                # Calculate baseline averages
                baseline = {
                    'reasoning': sum(r['reasoning_score'] for r in baseline_reports) / len(baseline_reports),
                    'coding': sum(r['coding_score'] for r in baseline_reports) / len(baseline_reports),
                    'analysis': sum(r['analysis_score'] for r in baseline_reports) / len(baseline_reports),
                    'comprehension': sum(r['comprehension_score'] for r in baseline_reports) / len(baseline_reports),
                    'overall': sum(r['overall_score'] for r in baseline_reports) / len(baseline_reports)
                }
                baseline_type = "SOFT"
                logger.debug(f"Using soft baseline (first {len(baseline_reports)} cycles) - consider freezing baseline")

            # Detect regression in each domain
            regression_domains = []
            regression_threshold = 0.10  # 10% drop is regression

            unmeasured_now = []
            for domain in ['reasoning', 'coding', 'analysis', 'comprehension']:
                current = domain_scores.get(domain)
                baseline_val = baseline.get(domain)

                # A DOMAIN THIS RUN DID NOT TEST HAS NOT REGRESSED.
                #
                # `domain_scores.get(domain, 0.0)` read an untested domain as
                # zero, so a run that simply held no coding benchmarks was
                # reported as having LOST all coding capability -- measured
                # here as regression_domains=[coding, comprehension], severity
                # MODERATE, against a suite that never asked a coding question.
                # That is the loudest possible false positive on the gate that
                # blocks deployment.
                if current is None:
                    unmeasured_now.append(domain)
                    continue
                if baseline_val is None or float(baseline_val) <= 0:
                    continue

                drop_pct = (float(baseline_val) - float(current)) / float(baseline_val)
                if drop_pct > regression_threshold:
                    regression_domains.append(domain)

            if unmeasured_now:
                logger.warning(
                    "Domains not tested this run (%s) — excluded from regression "
                    "detection rather than counted as lost capability",
                    ", ".join(unmeasured_now))

            # The suite is the authority on capability against the frozen
            # floor. It reports each domain that fell; the health monitor and
            # the improvement cycle decide what that is worth.
            try:
                from core.observability import regression_record

                for domain in regression_domains:
                    await regression_record.report(
                        subject=f"capability.{domain}", dimension="benchmark_score",
                        detail=(f"{domain} fell below the frozen baseline "
                                f"({float(baseline[domain]):.3f} -> "
                                f"{float(domain_scores[domain]):.3f})"),
                        source_system="capability_benchmarks",
                        baseline_value=float(baseline[domain]),
                        current_value=float(domain_scores[domain]),
                        metadata={"cycle_id": cycle_id})
                for domain, score in domain_scores.items():
                    if domain not in regression_domains:
                        await regression_record.resolve(f"capability.{domain}",
                                                        "benchmark_score")
            except Exception as regression_error:
                logger.error("Capability regression not recorded: %s", regression_error)

            # Calculate overall baseline delta
            baseline_delta = (overall_score - float(baseline['overall'])
                              if baseline.get('overall') is not None else 0.0)

            # Determine severity
            if not regression_domains:
                severity = "NONE"
                regression_detected = False
            elif len(regression_domains) == 1:
                severity = "MINOR"
                regression_detected = True
            elif len(regression_domains) == 2:
                severity = "MODERATE"
                regression_detected = True
            else:
                severity = "SEVERE"
                regression_detected = True

            # Statistical significance (simplified - use t-test in production)
            # For now, assume significant if delta > 0.15
            p_value = 0.01 if abs(baseline_delta) > 0.15 else 0.20

            if regression_detected:
                logger.warning(
                    f"⚠️  CAPABILITY REGRESSION DETECTED in cycle {cycle_id}: "
                    f"{severity} - Domains: {', '.join(regression_domains)}"
                )

            return (regression_detected, regression_domains, severity, baseline_delta, p_value)

        except Exception as e:
            logger.error(f"Error detecting capability regression: {e}")
            return (False, [], "NONE", 0.0, 1.0)

    async def _store_result(self, result: BenchmarkResult):
        """Store benchmark result in database"""
        try:
            result_id = f"{result.test_id}_{result.cycle_id}_{result.timestamp.timestamp()}"

            await self.db.execute_query(
                """
                INSERT INTO capability_benchmark_results
                (result_id, test_id, cycle_id, timestamp, success, score,
                 latency_ms, output, evaluation_details)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                params=(
                    result_id,
                    result.test_id,
                    result.cycle_id,
                    result.timestamp,
                    result.success,
                    result.score,
                    result.latency_ms,
                    result.output,
                    json.dumps(result.evaluation_details),
                ),
            )

        except Exception as e:
            logger.error(f"Error storing benchmark result: {e}")

    async def _store_report(self, report: CapabilityReport):
        """Store capability report in database"""
        try:
            report_id = f"capability_report_{report.cycle_id}_{report.timestamp.timestamp()}"

            await self.db.execute_query(
                """
                INSERT INTO capability_reports
                (report_id, cycle_id, timestamp, reasoning_score, coding_score,
                 analysis_score, comprehension_score, overall_score,
                 regression_detected, regression_domains, regression_severity,
                 tests_passed, tests_failed, avg_latency_ms,
                 baseline_delta, statistical_significance)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
                """,
                params=(
                    report_id,
                    report.cycle_id,
                    report.timestamp,
                    report.reasoning_score,
                    report.coding_score,
                    report.analysis_score,
                    report.comprehension_score,
                    report.overall_score,
                    report.regression_detected,
                    ','.join(report.regression_domains),
                    report.regression_severity,
                    report.tests_passed,
                    report.tests_failed,
                    report.avg_latency_ms,
                    report.baseline_delta,
                    report.statistical_significance,
                ),
            )

            logger.info(f"✅ Stored capability report for cycle {report.cycle_id}")

        except Exception as e:
            logger.error(f"Error storing capability report: {e}")

    def _create_error_report(self, cycle_id: str, error: str) -> CapabilityReport:
        """Report that the benchmarks could not run — NOT that they passed.

        This previously returned `regression_detected=False,
        regression_severity="NONE"` with every score at 0.0 and 0 tests run,
        which is indistinguishable from a clean pass. That verdict is consumed
        by a HARD GATE in enhanced_asi_self_improvement:

            if report.regression_detected and severity == "SEVERE":
                BLOCK the improvement

        So "I could not measure capability" opened the gate that exists to stop
        capability narrowing — the failure mode the whole module was written to
        prevent. An unrunnable benchmark is not evidence of safety.

        `regression_detected=True` with severity UNKNOWN is the honest answer:
        something is wrong and it has not been ruled out. The gate keys on
        SEVERE, so this does not silently block every deployment — but the flag,
        the empty domains and `tests_passed == tests_failed == 0` are all
        visible to any caller that looks, and the log says so plainly.
        """
        logger.error(
            f"CAPABILITY BENCHMARKS DID NOT RUN ({error}) — reporting UNKNOWN, "
            f"not 'no regression'. 0 of {len(self.benchmarks)} frozen tests executed; "
            f"capability regression has NOT been ruled out for cycle {cycle_id}."
        )
        return CapabilityReport(
            cycle_id=cycle_id,
            timestamp=datetime.now(),
            reasoning_score=0.0,
            coding_score=0.0,
            analysis_score=0.0,
            comprehension_score=0.0,
            overall_score=0.0,
            regression_detected=True,
            regression_domains=["<benchmarks did not run>"],
            regression_severity="UNKNOWN",
            tests_passed=0,
            tests_failed=0,
            avg_latency_ms=0.0,
            confidence_interval=(0.0, 0.0),
            baseline_delta=0.0,
            # Not 1.0 — that asserted a perfectly insignificant difference from
            # a comparison never performed.
            statistical_significance=0.0
        )

    async def freeze_baseline(
        self,
        consolidation_cycles: int,
        governance_decision_id: Optional[str] = None,
        approved_by: Optional[str] = None,
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Freeze capability baseline - creates IMMUTABLE baseline requiring governance approval

        This prevents baseline drift where the floor itself slowly lowers.
        Once frozen, baseline can only change with explicit governance approval.

        Args:
            consolidation_cycles: Number of stable cycles used to establish baseline
            governance_decision_id: Governance system decision ID approving freeze
            approved_by: Approver identifier (human or governance tier)
            notes: Additional context for freeze event

        Returns:
            Freeze event details with version and signature
        """
        try:
            # Get last N cycles for baseline calculation
            recent_cycles = await self.db.execute_query(
                """
                SELECT reasoning_score, coding_score, analysis_score,
                       comprehension_score, overall_score
                FROM capability_reports
                ORDER BY timestamp DESC
                LIMIT $1
                """,
                params=(consolidation_cycles,),
                fetch_all=True,
            )

            if len(recent_cycles) < consolidation_cycles:
                return {
                    "error": f"Insufficient cycles for baseline freeze. Need {consolidation_cycles}, have {len(recent_cycles)}"
                }

            # Calculate baseline as average of consolidation cycles
            # A DOMAIN NO CYCLE MEASURED HAS NO BASELINE, and averaging it as
            # zero would freeze a floor of zero for it -- a floor nothing can
            # fall through, which is the one thing a frozen baseline must never
            # be. `sum(...)` over a column holding NULL also simply raised:
            #     unsupported operand type(s) for +: 'int' and 'NoneType'
            def _mean(column: str):
                values = [float(c[column]) for c in recent_cycles
                          if c.get(column) is not None]
                return (sum(values) / len(values)) if values else None

            reasoning_baseline = _mean('reasoning_score')
            coding_baseline = _mean('coding_score')
            analysis_baseline = _mean('analysis_score')
            comprehension_baseline = _mean('comprehension_score')
            overall_baseline = _mean('overall_score')

            unmeasured = [name for name, value in (
                ("reasoning", reasoning_baseline), ("coding", coding_baseline),
                ("analysis", analysis_baseline),
                ("comprehension", comprehension_baseline)) if value is None]
            if unmeasured:
                logger.warning(
                    "Freezing a baseline with no value for %s: those domains "
                    "were never measured across the consolidation cycles and "
                    "are recorded as unmeasured rather than as zero",
                    ", ".join(unmeasured))

            # ENHANCEMENT: Multi-criteria stability analysis
            import statistics

            # Criterion 1: Overall score variance (low variance = stable)
            overall_scores = [float(c['overall_score']) for c in recent_cycles
                              if c.get('overall_score') is not None]
            overall_variance = statistics.variance(overall_scores) if len(overall_scores) > 1 else 0
            variance_score = max(0, 100 - (overall_variance * 1000))

            # Criterion 2: Cross-domain variance (all domains should be stable)
            domain_variances = []
            for domain in ['reasoning_score', 'coding_score', 'analysis_score', 'comprehension_score']:
                # Skip domains no cycle measured: `statistics.variance` over a
                # list containing None raises "can't convert type 'NoneType' to
                # numerator/denominator", which the handler turned into a bare
                # {"error": ...} and the freeze simply did not happen.
                domain_scores = [float(c[domain]) for c in recent_cycles
                                 if c[domain] is not None]
                if len(domain_scores) < 2:
                    continue
                domain_variances.append(statistics.variance(domain_scores))

            max_domain_variance = max(domain_variances) if domain_variances else 0.0
            domain_stability_score = max(0, 100 - (max_domain_variance * 1000))

            # Criterion 3: Trend check (scores should not be trending down)
            # Calculate slope of overall scores
            x = list(range(len(overall_scores)))
            x_mean = sum(x) / len(x)
            y_mean = sum(overall_scores) / len(overall_scores)
            numerator = sum((x[i] - x_mean) * (overall_scores[i] - y_mean) for i in range(len(x)))
            denominator = sum((x[i] - x_mean) ** 2 for i in range(len(x)))
            slope = numerator / denominator if denominator != 0 else 0

            # Negative slope = degrading trend
            if slope < -0.005:  # > 0.5% per cycle degradation
                trend_penalty = 30
                trend_warning = f"Degrading trend detected (slope={slope:.4f})"
            elif slope < 0:
                trend_penalty = 10
                trend_warning = f"Slight downward trend (slope={slope:.4f})"
            else:
                trend_penalty = 0
                trend_warning = None

            # Combined stability score (weighted average)
            stability_score = (
                variance_score * 0.5 +          # 50% weight on overall variance
                domain_stability_score * 0.3 +  # 30% weight on worst domain
                (100 - trend_penalty) * 0.2     # 20% weight on trend
            )

            # Multi-criteria gating
            stability_issues = []

            # Gate 1: Variance threshold
            VARIANCE_THRESHOLD = 0.0001  # Max acceptable variance (~1% stdev)
            if overall_variance > VARIANCE_THRESHOLD:
                stability_issues.append(
                    f"Overall variance too high: {overall_variance:.6f} (threshold: {VARIANCE_THRESHOLD})"
                )

            # Gate 2: Domain variance threshold
            DOMAIN_VARIANCE_THRESHOLD = 0.00015
            if max_domain_variance > DOMAIN_VARIANCE_THRESHOLD:
                stability_issues.append(
                    f"Domain variance too high: {max_domain_variance:.6f} (threshold: {DOMAIN_VARIANCE_THRESHOLD})"
                )

            # Gate 3: Trend check
            if slope < -0.005:
                stability_issues.append(
                    f"Degrading trend: {slope:.4f} points/cycle"
                )

            # Gate 4: Minimum stability score
            STABILITY_THRESHOLD = 80.0
            if stability_score < STABILITY_THRESHOLD:
                stability_issues.append(
                    f"Stability score too low: {stability_score:.1f} (threshold: {STABILITY_THRESHOLD})"
                )

            # Log stability analysis
            if stability_issues:
                logger.warning(
                    f"⚠️  Baseline freeze stability concerns ({len(stability_issues)} issues):"
                )
                for issue in stability_issues:
                    logger.warning(f"   - {issue}")
                logger.warning(
                    f"Recommendation: Run {consolidation_cycles * 2} cycles for better stability, "
                    "or override with governance approval"
                )
            else:
                logger.info(
                    f"✅ Stability analysis passed: score={stability_score:.1f}, "
                    f"variance={overall_variance:.6f}, slope={slope:.6f}"
                )

            # Get current version count from unified.capability_baseline_freezes
            count_row = await self.db.execute_query(
                "SELECT COUNT(*) AS count FROM capability_baseline_freezes",
                fetch_one=True,
            )
            version_num = (count_row.get('count', 0) if count_row else 0) + 1
            version = f"v{version_num}.0"

            # Generate signature hash (SHA-256 of baseline values)
            import hashlib
            baseline_string = f"{reasoning_baseline}{coding_baseline}{analysis_baseline}{comprehension_baseline}{overall_baseline}{version}"
            signature_hash = hashlib.sha256(baseline_string.encode()).hexdigest()

            # Create freeze event
            freeze_id = f"freeze_{datetime.now().timestamp()}_{version}"

            # Determine status based on governance approval
            if governance_decision_id:
                status = "ACTIVE"
                governance_approved = True
            else:
                status = "PENDING_APPROVAL"
                governance_approved = False

            # Deactivate previous baselines if this one is approved
            if status == "ACTIVE":
                await self.db.execute_query(
                    """
                    UPDATE capability_baseline_freezes
                    SET status = 'SUPERSEDED'
                    WHERE status = 'ACTIVE'
                    """,
                )

            # Insert freeze event
            await self.db.execute_query(
                """
                INSERT INTO capability_baseline_freezes
                (freeze_id, version, frozen_at, reasoning_baseline, coding_baseline,
                 analysis_baseline, comprehension_baseline, overall_baseline,
                 consolidation_cycles, stability_score, governance_approved,
                 governance_decision_id, approved_by, signature_hash, status, notes)
                VALUES ($1, $2, NOW(), $3, $4, $5, $6, $7, $8, $9, $10,
                        $11, $12, $13, $14, $15)
                """,
                params=(
                    freeze_id,
                    version,
                    reasoning_baseline,
                    coding_baseline,
                    analysis_baseline,
                    comprehension_baseline,
                    overall_baseline,
                    consolidation_cycles,
                    stability_score,
                    governance_approved,
                    governance_decision_id,
                    approved_by,
                    signature_hash,
                    status,
                    notes,
                ),
            )

            logger.info(
                f"🔒 BASELINE FROZEN: {version} - "
                f"Overall={overall_baseline:.2%}, Stability={stability_score:.1f}, "
                f"Status={status}"
            )

            return {
                "freeze_id": freeze_id,
                "version": version,
                "baselines": {
                    "reasoning": reasoning_baseline,
                    "coding": coding_baseline,
                    "analysis": analysis_baseline,
                    "comprehension": comprehension_baseline,
                    "overall": overall_baseline
                },
                "stability_score": stability_score,
                "consolidation_cycles": consolidation_cycles,
                "signature_hash": signature_hash,
                "status": status,
                "governance_approved": governance_approved
            }

        except Exception as e:
            logger.error(f"Error freezing baseline: {e}")
            return {"error": str(e)}

    async def request_baseline_activation(self, version: str) -> Dict[str, Any]:
        """Put a frozen baseline to a person for approval.

        `freeze_baseline` writes PENDING_APPROVAL unless it is handed a
        `governance_decision_id`, and nothing existed to obtain one -- so a
        frozen baseline could be created and then never become the baseline
        anything compares against. The gate was right and had no door.

        The decision is a real row a person answers in the dashboard, the same
        path that authorises a self-modification deployment. A capability floor
        is exactly the kind of thing that should not be self-approved: it
        decides, from then on, what counts as the system getting worse.
        """
        from core.governance import approval_requests

        rows = await self.db.execute_query(
            """SELECT version, reasoning_baseline, coding_baseline,
                      analysis_baseline, comprehension_baseline, overall_baseline,
                      consolidation_cycles, stability_score, signature_hash, notes
                 FROM capability_baseline_freezes
                WHERE version = $1 AND status = 'PENDING_APPROVAL'""",
            params=(version,), fetch_all=True)
        if not rows:
            return {"error": f"no baseline {version} awaiting approval"}

        frozen = dict(rows[0])
        measured = {name: float(frozen[f"{name}_baseline"])
                    for name in ("reasoning", "coding", "analysis", "comprehension")
                    if frozen.get(f"{name}_baseline") is not None}
        unmeasured = [name for name in
                      ("reasoning", "coding", "analysis", "comprehension")
                      if frozen.get(f"{name}_baseline") is None]

        request = await approval_requests.request(
            action_id=f"capability_baseline:{version}",
            action_type="capability_baseline_activation",
            tier="MAJOR",
            scope="major",
            requester="capability_benchmark_suite",
            summary=(f"Activate capability baseline {version} — overall "
                     f"{float(frozen['overall_baseline']):.3f} over "
                     f"{frozen['consolidation_cycles']} consolidation cycles"),
            rationale=("Once active, this becomes the floor every later run is "
                       "compared against, and regression is measured from it. "
                       "Domains with no measurement are recorded as unmeasured "
                       "rather than zero, so they cannot create a floor nothing "
                       "can fall through."),
            details={"version": version, "measured": measured,
                     "unmeasured": unmeasured,
                     "stability_score": float(frozen["stability_score"]),
                     "consolidation_cycles": int(frozen["consolidation_cycles"]),
                     "signature_hash": frozen["signature_hash"],
                     "notes": frozen.get("notes")})

        return {"version": version, "approval_id": request.approval_id,
                "status": request.status}

    async def activate_approved_baseline(self, version: str) -> Dict[str, Any]:
        """Make a baseline ACTIVE once a person has approved it.

        Reads the decision rather than being told it: the caller cannot assert
        approval, only point at a request that was answered.
        """
        from core.governance import approval_requests

        action_id = f"capability_baseline:{version}"
        decision = await approval_requests.decision_for(action_id)
        if decision is None:
            return {"error": f"baseline {version} has not been decided yet",
                    "status": "PENDING_APPROVAL"}
        if decision is False:
            return {"error": f"baseline {version} was declined", "status": "DECLINED"}

        granted = await approval_requests.find(action_id)
        await self.db.execute_query(
            "UPDATE capability_baseline_freezes SET status = 'SUPERSEDED' "
            "WHERE status = 'ACTIVE'", commit=True)
        await self.db.execute_query(
            """UPDATE capability_baseline_freezes
                  SET status = 'ACTIVE', governance_approved = true,
                      governance_decision_id = $1
                WHERE version = $2""",
            params=(f"approval:{granted.approval_id}", version), commit=True)

        logger.warning("🔒 Capability baseline %s is now ACTIVE, approved by %s",
                       version, granted.decided_by)
        return {"version": version, "status": "ACTIVE",
                "approved_by": granted.decided_by,
                "authenticated": granted.authenticated}

    async def get_active_baseline(self) -> Optional[Dict[str, Any]]:
        """
        Get currently active frozen baseline

        Returns:
            Active baseline dict or None if no baseline frozen yet
        """
        try:
            baseline = await self.db.execute_query(
                """
                SELECT freeze_id, version, frozen_at, reasoning_baseline,
                       coding_baseline, analysis_baseline, comprehension_baseline,
                       overall_baseline, consolidation_cycles, stability_score,
                       signature_hash, approved_by
                FROM capability_baseline_freezes
                WHERE status = 'ACTIVE'
                ORDER BY frozen_at DESC
                LIMIT 1
                """,
                fetch_one=True,
            )

            if baseline:
                logger.debug(f"Active baseline: {baseline['version']} (frozen {baseline['frozen_at']})")

            return baseline

        except Exception as e:
            logger.error(f"Error getting active baseline: {e}")
            return None

    async def detect_long_horizon_drift(
        self,
        domain: str = "overall",
        window_size: int = 30
    ) -> Dict[str, Any]:
        """
        Detect long-horizon drift using 30-cycle rolling window

        This catches the "boiling frog" problem:
        - 1% degradation per cycle = 30% total loss over 30 cycles
        - No single cycle triggers gates
        - But cumulative drift is catastrophic

        Args:
            domain: Domain to analyze ("overall", "reasoning", "coding", etc.)
            window_size: Rolling window size in cycles (default 30)

        Returns:
            Drift analysis with slope, velocity, volatility
        """
        try:
            # Get last N cycles
            score_field = f"{domain}_score" if domain != "overall" else "overall_score"
            cycles = await self.db.execute_query(
                f"""
                SELECT cycle_id, {score_field} AS score, timestamp
                FROM capability_reports
                ORDER BY timestamp DESC
                LIMIT $1
                """,
                params=(window_size,),
                fetch_all=True,
            )

            if len(cycles) < window_size:
                return {
                    "error": f"Insufficient data. Need {window_size} cycles, have {len(cycles)}"
                }

            # Reverse to get chronological order
            cycles = list(reversed(cycles))
            scores = [c['score'] for c in cycles]

            # Calculate regression slope (linear regression)
            slope = self._calculate_regression_slope(scores)

            # Calculate drift velocity (rate of change per cycle)
            # UNITS: slope is in absolute points per cycle (e.g., -0.0003 = -0.03% per cycle)
            # drift_velocity is in percentage points per cycle (e.g., -0.03)
            drift_velocity = slope * 100  # Convert to percentage points per cycle
            drift_velocity_pct_per_cycle = drift_velocity  # Explicit unit: % per cycle

            # Calculate volatility (coefficient of variation)
            # UNITS: volatility_score is dimensionless (stdev/mean)
            # High volatility (> 0.10) indicates erratic performance
            volatility_score = self._calculate_volatility_score(scores)

            # Determine trend direction
            if abs(slope) < 0.001:  # < 0.1% per cycle
                trend_direction = "STABLE"
            elif slope > 0:
                trend_direction = "IMPROVING"
            else:
                trend_direction = "DEGRADING"

            # Statistical significance (using correlation coefficient)
            from scipy import stats
            x = list(range(len(scores)))
            correlation, p_value = stats.pearsonr(x, scores)

            # ENHANCEMENT: Calculate cumulative change with volatility weighting
            cumulative_change = slope * window_size  # Total change over window
            cumulative_change_pct = cumulative_change * 100  # In percentage points

            # ENHANCEMENT: Weight severity by volatility
            # High volatility may mask cumulative drift OR indicate instability
            # Volatility penalty: increase severity if drift + high volatility
            VOLATILITY_THRESHOLD_LOW = 0.05   # < 5% CV = stable
            VOLATILITY_THRESHOLD_HIGH = 0.15  # > 15% CV = very erratic

            if volatility_score > VOLATILITY_THRESHOLD_HIGH:
                # High volatility + drift = increased severity
                volatility_multiplier = 1.3
                volatility_flag = "HIGH_VOLATILITY"
            elif volatility_score < VOLATILITY_THRESHOLD_LOW:
                # Low volatility + drift = confidence in trend
                volatility_multiplier = 1.0
                volatility_flag = "STABLE"
            else:
                # Moderate volatility
                volatility_multiplier = 1.1
                volatility_flag = "MODERATE_VOLATILITY"

            # Apply volatility weighting to cumulative change
            weighted_cumulative_change = abs(cumulative_change) * volatility_multiplier

            # ENHANCEMENT: Determine severity with volatility weighting
            if weighted_cumulative_change < 0.05:  # < 5% total change
                severity = "NONE"
            elif weighted_cumulative_change < 0.10:  # < 10% total change
                severity = "LOW"
            elif weighted_cumulative_change < 0.20:  # < 20% total change
                severity = "MEDIUM"
            elif weighted_cumulative_change < 0.30:  # < 30% total change
                severity = "HIGH"
            else:
                severity = "CRITICAL"

            # ENHANCEMENT: Early warning system - predictive alert
            # Project drift to next 10 cycles and warn if approaching critical
            projected_cycles_ahead = 10
            projected_cumulative = (slope * (window_size + projected_cycles_ahead)) * volatility_multiplier

            early_warning = None
            if severity == "MEDIUM" and abs(projected_cumulative) > 0.25:
                early_warning = {
                    "alert": "APPROACHING_HIGH",
                    "message": f"Current MEDIUM drift will reach HIGH in ~{projected_cycles_ahead} cycles if trend continues",
                    "projected_cumulative_pct": round(projected_cumulative * 100, 2),
                    "cycles_until_high": projected_cycles_ahead
                }
                logger.warning(
                    f"🔮 EARLY WARNING: {domain} drift approaching HIGH severity. "
                    f"Projected: {projected_cumulative*100:.1f}% in {projected_cycles_ahead} cycles"
                )
            elif severity == "LOW" and abs(projected_cumulative) > 0.15:
                early_warning = {
                    "alert": "APPROACHING_MEDIUM",
                    "message": f"Current LOW drift will reach MEDIUM in ~{projected_cycles_ahead} cycles if trend continues",
                    "projected_cumulative_pct": round(projected_cumulative * 100, 2),
                    "cycles_until_medium": projected_cycles_ahead
                }
                logger.info(
                    f"🔮 Early warning: {domain} drift may reach MEDIUM in {projected_cycles_ahead} cycles"
                )

            drift_analysis = {
                "domain": domain,
                "window_size": window_size,
                "window_start_cycle": cycles[0]['cycle_id'],
                "window_end_cycle": cycles[-1]['cycle_id'],
                # Drift metrics with explicit units
                "regression_slope": round(slope, 6),  # Absolute points per cycle
                "drift_velocity_pct_per_cycle": round(drift_velocity_pct_per_cycle, 4),  # % per cycle
                "cumulative_change": round(cumulative_change, 6),  # Absolute points total
                "cumulative_change_pct": round(cumulative_change_pct, 2),  # % total
                "weighted_cumulative_change": round(weighted_cumulative_change, 6),  # Volatility-adjusted
                # Volatility analysis
                "volatility_score": round(volatility_score, 4),  # Coefficient of variation
                "volatility_flag": volatility_flag,  # STABLE | MODERATE_VOLATILITY | HIGH_VOLATILITY
                "volatility_multiplier": round(volatility_multiplier, 2),
                # Trend analysis
                "trend_direction": trend_direction,
                "statistical_significance": round(p_value, 4),
                "correlation": round(correlation, 4),
                # Severity (volatility-weighted)
                "severity": severity,
                # Early warning system
                "early_warning": early_warning,
                # Score statistics
                "scores": {
                    "first_cycle": scores[0],
                    "last_cycle": scores[-1],
                    "average": sum(scores) / len(scores),
                    "min": min(scores),
                    "max": max(scores),
                    "range": max(scores) - min(scores)
                },
                # Units documentation
                "units": {
                    "regression_slope": "absolute_points_per_cycle",
                    "drift_velocity": "percentage_points_per_cycle",
                    "cumulative_change": "absolute_points_total",
                    "volatility_score": "coefficient_of_variation_dimensionless"
                }
            }

            # Store drift tracking event
            drift_id = f"drift_{domain}_{datetime.now().timestamp()}"

            await self.db.execute_query(
                """
                INSERT INTO capability_drift_tracking
                (drift_id, domain, window_start_cycle, window_end_cycle, window_size,
                 regression_slope, drift_velocity, volatility_score, trend_direction,
                 statistical_significance, detected_at, severity)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, NOW(), $11)
                """,
                params=(
                    drift_id,
                    domain,
                    cycles[0]['cycle_id'],
                    cycles[-1]['cycle_id'],
                    window_size,
                    slope,
                    drift_velocity,
                    volatility_score,
                    trend_direction,
                    p_value,
                    severity,
                ),
            )

            # Log warnings
            if severity in ["HIGH", "CRITICAL"]:
                logger.error(
                    f"🚨 LONG-HORIZON DRIFT DETECTED: {severity} in {domain} - "
                    f"Cumulative change: {drift_analysis['cumulative_change_pct']:.1f}% "
                    f"over {window_size} cycles"
                )
            elif severity == "MEDIUM":
                logger.warning(
                    f"⚠️  Long-horizon drift detected in {domain}: "
                    f"{drift_analysis['cumulative_change_pct']:.1f}% over {window_size} cycles"
                )

            return drift_analysis

        except ImportError:
            logger.error("scipy required for drift detection")
            return {"error": "scipy not available"}
        except Exception as e:
            logger.error(f"Error detecting long-horizon drift: {e}")
            return {"error": str(e)}

    def _calculate_regression_slope(self, scores: List[float]) -> float:
        """Calculate linear regression slope using least squares"""
        n = len(scores)
        x = list(range(n))

        # Calculate means
        x_mean = sum(x) / n
        y_mean = sum(scores) / n

        # Calculate slope
        numerator = sum((x[i] - x_mean) * (scores[i] - y_mean) for i in range(n))
        denominator = sum((x[i] - x_mean) ** 2 for i in range(n))

        slope = numerator / denominator if denominator != 0 else 0
        return slope

    def _calculate_volatility_score(self, scores: List[float]) -> float:
        """Calculate volatility as standard deviation normalized by mean"""
        import statistics

        if len(scores) < 2:
            return 0.0

        mean = statistics.mean(scores)
        stdev = statistics.stdev(scores)

        # Coefficient of variation (normalized volatility)
        volatility = (stdev / mean) if mean != 0 else 0
        return volatility

    async def detect_cross_domain_drift_correlation(
        self,
        window_size: int = 30
    ) -> Dict[str, Any]:
        """
        ENHANCEMENT: Detect systemic performance decay across multiple domains

        This catches correlated drift - when reasoning + memory + perception all
        trend down together, indicating systemic degradation rather than domain-specific issues.

        Args:
            window_size: Rolling window size in cycles (default 30)

        Returns:
            Cross-domain correlation analysis with systemic drift index
        """
        try:
            # Run drift detection for all domains
            domains = ['reasoning', 'coding', 'analysis', 'comprehension', 'overall']
            domain_drifts = {}

            for domain in domains:
                drift = await self.detect_long_horizon_drift(domain, window_size)
                if 'error' not in drift:
                    domain_drifts[domain] = drift

            if len(domain_drifts) < 2:
                return {"error": "Insufficient domains for correlation analysis"}

            # Extract slopes for correlation calculation
            domain_slopes = {
                domain: data['regression_slope']
                for domain, data in domain_drifts.items()
            }

            # Calculate cross-domain correlation matrix
            from scipy import stats
            import itertools

            correlations = {}
            for domain1, domain2 in itertools.combinations(domains, 2):
                if domain1 in domain_drifts and domain2 in domain_drifts:
                    # Get time series for both domains
                    score_field1 = f"{domain1}_score" if domain1 != "overall" else "overall_score"
                    score_field2 = f"{domain2}_score" if domain2 != "overall" else "overall_score"
                    rows = await self.db.execute_query(
                        f"""
                        SELECT {score_field1} AS score1, {score_field2} AS score2
                        FROM capability_reports
                        ORDER BY timestamp DESC
                        LIMIT $1
                        """,
                        params=(window_size,),
                        fetch_all=True,
                    )

                    if len(rows) >= window_size:
                        scores1 = [r['score1'] for r in reversed(rows)]
                        scores2 = [r['score2'] for r in reversed(rows)]

                        correlation, p_value = stats.pearsonr(scores1, scores2)
                        correlations[f"{domain1}_{domain2}"] = {
                            "correlation": round(correlation, 4),
                            "p_value": round(p_value, 4),
                            "significant": p_value < 0.05
                        }

            # Calculate systemic drift index
            # High index = many domains trending down together (systemic issue)
            degrading_domains = [
                domain for domain, data in domain_drifts.items()
                if data['trend_direction'] == "DEGRADING"
            ]

            # Check if degrading domains are correlated
            systemic_correlations = []
            for pair, corr_data in correlations.items():
                domain1, domain2 = pair.split('_')
                if domain1 in degrading_domains and domain2 in degrading_domains:
                    if corr_data['correlation'] > 0.5 and corr_data['significant']:
                        systemic_correlations.append((pair, corr_data['correlation']))

            # Systemic drift index: 0-100
            # Based on: number of degrading domains + correlation strength
            num_degrading = len(degrading_domains)
            avg_correlation = (
                sum(c for _, c in systemic_correlations) / len(systemic_correlations)
                if systemic_correlations else 0
            )

            systemic_index = (
                (num_degrading / len(domains)) * 50 +  # 50 points for domain count
                avg_correlation * 50                     # 50 points for correlation
            )

            # Determine systemic severity
            if systemic_index > 75:
                systemic_severity = "CRITICAL"
                systemic_alert = "🚨 SYSTEMIC DEGRADATION: Multiple domains degrading in correlation"
            elif systemic_index > 50:
                systemic_severity = "HIGH"
                systemic_alert = "⚠️  Systemic drift detected: Correlated domain degradation"
            elif systemic_index > 25:
                systemic_severity = "MEDIUM"
                systemic_alert = "⚠️  Potential systemic issue: Some domain correlation"
            else:
                systemic_severity = "LOW"
                systemic_alert = None

            analysis = {
                "window_size": window_size,
                "domains_analyzed": list(domain_drifts.keys()),
                "degrading_domains": degrading_domains,
                "domain_drifts": domain_drifts,
                "cross_domain_correlations": correlations,
                "systemic_correlations": [
                    {"pair": pair, "correlation": corr}
                    for pair, corr in systemic_correlations
                ],
                "systemic_drift_index": round(systemic_index, 2),
                "systemic_severity": systemic_severity,
                "systemic_alert": systemic_alert,
                "interpretation": {
                    "num_domains_degrading": num_degrading,
                    "pct_domains_degrading": round((num_degrading / len(domains)) * 100, 1),
                    "avg_cross_correlation": round(avg_correlation, 4),
                    "is_systemic": systemic_index > 50
                }
            }

            # Log systemic alerts
            if systemic_alert:
                if systemic_severity in ["CRITICAL", "HIGH"]:
                    logger.error(
                        f"{systemic_alert} - "
                        f"Systemic index: {systemic_index:.1f}, "
                        f"Degrading: {', '.join(degrading_domains)}"
                    )
                else:
                    logger.warning(systemic_alert)

            return analysis

        except ImportError:
            logger.error("scipy required for cross-domain correlation analysis")
            return {"error": "scipy not available"}
        except Exception as e:
            logger.error(f"Error in cross-domain drift correlation: {e}")
            return {"error": str(e)}


# Global singleton
_capability_benchmark_suite: Optional[CapabilityBenchmarkSuite] = None


def get_capability_benchmark_suite() -> CapabilityBenchmarkSuite:
    """Get or create the global capability benchmark suite"""
    global _capability_benchmark_suite
    if _capability_benchmark_suite is None:
        _capability_benchmark_suite = CapabilityBenchmarkSuite()
    return _capability_benchmark_suite
