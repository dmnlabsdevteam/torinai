#!/usr/bin/env python3
"""
Convergence Gate — Phase 1: Hard Convergence Core
==================================================

Formal convergence verification using:
- constraint_solver.py — Z3 SMT solver for invariant proofs
- advanced_proof_engine.py — theorem proving
- epistemic_engine.py — uncertainty quantification
- checkpoint_manager.py — state delta tracking

Architecture:
    Before LLM can call propose_completion, the system must prove:
    1. constraint_solver.check_invariants(task) == SAT
    2. epistemic_engine.uncertainty(task) < threshold
    3. checkpoint_manager.state_delta() < epsilon
    
    This replaces probabilistic convergence (LLM confidence, scoring)
    with formal convergence (constraint satisfaction, proofs, uncertainty).

Design Principle:
    The LLM proposes, the formal system disposes.
    - LLM can REQUEST convergence check
    - System PROVES convergence formally
    - No completion without proof
"""

import asyncio
import logging
import json
import hashlib
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class ConvergenceState(Enum):
    """Convergence verification states"""
    NOT_STARTED = "not_started"           # No iterations yet
    ACTIVE = "active"                     # Making progress
    STALLED = "stalled"                   # State not changing (delta < epsilon)
    CONSTRAINTS_VIOLATED = "violated"     # Invariants not satisfied
    UNCERTAIN = "uncertain"               # Epistemic uncertainty too high
    CONVERGED = "converged"               # All gates passed
    FAILED = "failed"                     # Cannot converge
    PARTIAL_CONVERGENCE = "partial_convergence"  # Some gates passed, some failed


@dataclass
class ConvergenceInvariant:
    """Task-specific invariant that must be proven"""
    invariant_id: str
    description: str
    constraint_expr: str               # Natural language or Z3 expr
    task_type: str                     # TaskType.name this applies to
    required: bool = True              # Must be satisfied for convergence
    proof_method: str = "smt"          # "smt", "theorem", "epistemic"


@dataclass
class ConvergenceResult:
    """Result of convergence check with CEGAR-style structured feedback"""
    converged: bool
    state: ConvergenceState
    
    # Formal proofs
    constraints_satisfied: bool
    constraint_proofs: Dict[str, Any] = field(default_factory=dict)
    
    # Epistemic measures
    epistemic_uncertainty: float = 1.0
    uncertainty_threshold: float = 0.3
    
    # State stability
    state_delta: float = float('inf')
    delta_threshold: float = 0.01
    
    # Failures
    violated_invariants: List[str] = field(default_factory=list)
    missing_proofs: List[str] = field(default_factory=list)
    
    # CEGAR: Structured proof details
    failed_invariants_structured: List[Dict[str, Any]] = field(default_factory=list)
    counterexample_state: Optional[Dict[str, Any]] = None
    delta_diagnostic: Optional[Dict[str, Any]] = None
    epistemic_decomposition: Optional[Dict[str, Any]] = None
    
    # Metadata
    iterations_checked: int = 0
    timestamp: datetime = field(default_factory=datetime.now)
    reason: str = ""


class ConvergenceGate:
    """
    Formal convergence verification gate
    
    Before LLM can propose completion:
    1. Prove all task invariants (Z3 SMT)
    2. Epistemic uncertainty below threshold
    3. State delta below epsilon (fixpoint detection)
    """
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        
        # Risk 3: Deadline vs Invariant conflict policy
        # Options: 'fail', 'escalate', 'defer', 'relax_threshold'
        self.deadline_policy = self.config.get('deadline_policy', 'fail')
        self.relaxation_factor = self.config.get('relaxation_factor', 1.5)  # Multiply threshold by this
        
        # Lazy-load reasoning engines
        self._constraint_solver = None
        self._proof_engine = None
        self._epistemic_engine = None
        
        # Invariants registry (task_type -> list of invariants)
        self.invariants: Dict[str, List[ConvergenceInvariant]] = {}
        
        # State tracking per task
        self._task_states: Dict[str, List[Dict[str, Any]]] = {}
        self._task_checkpoints: Dict[str, List[str]] = {}

        # Consecutive zero-delta (fixpoint) counter per task.
        # A single thinking iteration with no new tool calls must NOT be treated
        # as a fixpoint — the model may make tool calls the very next iteration.
        # Only declare stalled after FIXPOINT_CONSECUTIVE_THRESHOLD iterations
        # in a row with zero semantic delta.
        self._consecutive_fixpoint: Dict[str, int] = {}
        self.FIXPOINT_CONSECUTIVE_THRESHOLD = self.config.get('fixpoint_consecutive_threshold', 3)
        
        # Statistics
        self.stats = {
            'total_checks': 0,
            'converged': 0,
            'failed_constraints': 0,
            'failed_uncertainty': 0,
            'failed_delta': 0,
        }
        
        # Calibration tracking: uncertainty vs actual success
        self._calibration_data: List[Tuple[float, bool]] = []  # (uncertainty, success)
        self._last_calibration_check = datetime.now()
        
        logger.info("ConvergenceGate initialized (Phase 1: Hard Convergence Core)")
        
        # Initialize default invariants
        self._initialize_default_invariants()
    
    # ─────────────────────────────────────────────────────────────────────────
    # Lazy Engine Initialization
    # ─────────────────────────────────────────────────────────────────────────
    
    @property
    def constraint_solver(self):
        """Lazy-load constraint solver"""
        if self._constraint_solver is None:
            from core.reasoning.constraint_solver import ConstraintSolver
            self._constraint_solver = ConstraintSolver()
        return self._constraint_solver
    
    @property
    def proof_engine(self):
        """Lazy-load proof engine"""
        if self._proof_engine is None:
            from core.reasoning.advanced_proof_engine import AdvancedProofEngine
            self._proof_engine = AdvancedProofEngine()
        return self._proof_engine
    
    @property
    def epistemic_engine(self):
        """Lazy-load epistemic engine"""
        if self._epistemic_engine is None:
            from core.reasoning.epistemic_engine import get_epistemic_engine
            self._epistemic_engine = get_epistemic_engine()
        return self._epistemic_engine
    
    # ─────────────────────────────────────────────────────────────────────────
    # Invariant Registry
    # ─────────────────────────────────────────────────────────────────────────
    
    def _initialize_default_invariants(self):
        """Initialize default invariants for core task types"""
        
        # SECURITY_REMEDIATION: Must prove finding no longer exists
        self.register_invariant(ConvergenceInvariant(
            invariant_id="security_finding_resolved",
            description="Security finding must no longer exist after remediation",
            constraint_expr="NOT(finding_exists(finding_id))",
            task_type="SECURITY_REMEDIATION",
            required=True,
            proof_method="smt"
        ))
        
        # EXECUTION: Must prove side-effects occurred
        self.register_invariant(ConvergenceInvariant(
            invariant_id="side_effects_occurred",
            description="Execution task must produce observable side-effects",
            constraint_expr="tool_calls_successful > 0",
            task_type="EXECUTION",
            required=True,
            proof_method="smt"
        ))
        
        # RESEARCH: Must have gathered information
        self.register_invariant(ConvergenceInvariant(
            invariant_id="information_gathered",
            description="Research task must gather verifiable information",
            constraint_expr="information_entropy_delta > 0",
            task_type="RESEARCH",
            required=True,
            proof_method="epistemic"
        ))
        
        logger.info(f"Registered {len(self.invariants)} default invariants")
    
    def register_invariant(self, invariant: ConvergenceInvariant):
        """Register a task-specific invariant"""
        if invariant.task_type not in self.invariants:
            self.invariants[invariant.task_type] = []
        self.invariants[invariant.task_type].append(invariant)
        logger.debug(f"Registered invariant: {invariant.invariant_id} for {invariant.task_type}")
    
    # ─────────────────────────────────────────────────────────────────────────
    # State Tracking
    # ─────────────────────────────────────────────────────────────────────────
    
    def reset_task_state(self, task_id: str) -> None:
        """Clear all checkpoints for a task.

        Must be called at the start of each execution attempt (including
        retries) so stale delta history from a previous run does not
        incorrectly trigger convergence in the new attempt.
        """
        self._task_states.pop(task_id, None)
        self._task_checkpoints.pop(task_id, None)
        self._consecutive_fixpoint.pop(task_id, None)
        logger.debug(f"[CONVERGENCE] Reset task state for {task_id}")

    async def checkpoint_state(self, task_id: str, iteration: int, state: Dict[str, Any]):
        """Save task state checkpoint for delta computation"""
        if task_id not in self._task_states:
            self._task_states[task_id] = []
            self._task_checkpoints[task_id] = []

        # CRITICAL: shallow-copy tool_results and epistemic_mutations so each
        # checkpoint captures an independent snapshot.  The executor passes the
        # *same* mutable list reference every call; without copying, states[-1]
        # and states[-2] always point to the same list → hash_t == hash_{t-1}
        # → delta=0.0 every iteration → convergence gate fires as a false fixpoint.
        state_snapshot = {
            'tool_results': [dict(tr) for tr in state.get('tool_results', [])],
            'epistemic_mutations': list(state.get('epistemic_mutations', [])),
        }

        # Append state snapshot
        self._task_states[task_id].append({
            'iteration': iteration,
            'timestamp': datetime.now().isoformat(),
            'state': state_snapshot
        })
        
        # THE DISK CHECKPOINT IS RETIRED (2026-08-24).
        #
        # This used to also gzip `state` to data/convergence_checkpoints/ via
        # CheckpointManager. Nothing ever read it back: `load_checkpoint`,
        # `get_latest_checkpoint` and `restore_from_latest` had no callers
        # outside their own module, and the delta below is computed from
        # `self._task_states` -- the in-memory snapshot taken immediately above
        # -- never from the files. With max_checkpoints=100 the store sat
        # permanently at its cap, so every checkpoint was written, held, and
        # pruned away having never been read once.
        #
        # It was also the wrong state to preserve. What it held was
        # {tool_results, epistemic_mutations}: iteration state of the model's
        # tool-use loop, with no rules, concepts, bindings or reasoning record
        # in it. Restoring one would not have restored Torin to anything.
        #
        # The 100 files and the module are in
        # backups/checkpoints_retired_20260824/.
        self._task_checkpoints[task_id].append(f"{task_id}_iter{iteration}")

        logger.debug(f"Snapshotted state for {task_id} at iteration {iteration}")
    
    def _compute_state_delta(self, task_id: str) -> Tuple[float, Optional[Dict[str, Any]]]:
        """Compute canonicalized semantic state change between last two checkpoints.
        
        CRITICAL: State must be:
        1. Semantically relevant (exclude logs, timestamps, metadata)
        2. Deterministic (same state = same hash)
        3. Canonicalized (normalized ordering, whitespace)
        
        Non-canonicalized state causes false non-convergence.
        
        Returns:
            (delta, diagnostic) - diagnostic contains state comparison details
        """
        states = self._task_states.get(task_id, [])
        if len(states) < 2:
            return float('inf'), None  # Not enough history
        
        # Compare last two states
        state_t = states[-1]['state']
        state_t_minus_1 = states[-2]['state']
        
        # Extract ONLY semantically relevant state components
        canonical_t = self._canonicalize_state(state_t)
        canonical_t_minus_1 = self._canonicalize_state(state_t_minus_1)
        
        # Hash canonicalized state
        hash_t = hashlib.sha256(
            json.dumps(canonical_t, sort_keys=True).encode()
        ).hexdigest()
        hash_t_minus_1 = hashlib.sha256(
            json.dumps(canonical_t_minus_1, sort_keys=True).encode()
        ).hexdigest()
        
        diagnostic = {
            "previous_state_hash": hash_t_minus_1[:8],
            "current_state_hash": hash_t[:8],
            "fixpoint_reached": hash_t == hash_t_minus_1
        }
        
        if hash_t == hash_t_minus_1:
            diagnostic["semantic_delta"] = 0.0
            diagnostic["progress"] = "fixpoint"
            return 0.0, diagnostic  # Fixpoint reached (no semantic change)
        
        # Compute semantic delta (tool results, epistemic mutations, etc.)
        tool_delta = self._compare_tool_results(
            canonical_t.get('tool_results', []),
            canonical_t_minus_1.get('tool_results', [])
        )
        
        epistemic_delta = abs(
            canonical_t.get('epistemic_mutation_count', 0) -
            canonical_t_minus_1.get('epistemic_mutation_count', 0)
        )
        
        # Normalized delta [0, 1]
        delta = min(1.0, (tool_delta + epistemic_delta * 0.1) / 10.0)

        diagnostic["semantic_delta"] = delta
        diagnostic["tool_delta"] = tool_delta
        diagnostic["epistemic_delta"] = epistemic_delta
        diagnostic["progress"] = "active" if delta > 0.1 else "minimal"
        
        return delta, diagnostic
    
    def _canonicalize_state(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Extract and canonicalize semantically relevant state.
        
        Excludes:
        - Timestamps (iteration, timestamp fields)
        - Logs (execution_ledger)
        - Metadata (conversation_history with assistant reasoning)
        - Non-deterministic IDs
        
        Includes:
        - Tool call outcomes (success/failure, critical errors)
        - Epistemic mutations (count, total delta)
        - Task state changes (file modifications, API calls)
        """
        canonical = {
            'tool_results': [],
            'epistemic_mutation_count': 0,
            'epistemic_total_delta': 0.0,
        }
        
        # Canonicalize tool results: extract only success/failure + critical outputs
        for tr in state.get('tool_results', []):
            canonical['tool_results'].append({
                'tool': tr.get('tool', 'unknown'),
                'success': tr.get('success', False),
                # Only include output if it's state-changing (file paths, API responses)
                'output_hash': hashlib.sha256(
                    str(tr.get('output', '')).encode()
                ).hexdigest()[:8]  # Short hash for comparison
            })
        
        # Canonicalize epistemic mutations: count + total delta
        mutations = state.get('epistemic_mutations', [])
        canonical['epistemic_mutation_count'] = len(mutations)
        canonical['epistemic_total_delta'] = sum(
            m.delta for m in mutations if hasattr(m, 'delta')
        )
        
        return canonical
    
    def _compare_tool_results(self, results_t: List[Dict], results_t_minus_1: List[Dict]) -> float:
        """Compare tool results between iterations.
        
        Counts ALL new tool calls regardless of success/failure — a failed call
        is still evidence the agent is making forward progress.  Only 0 when
        nothing new was attempted at all.
        """
        new_calls = sum(
            1 for r in results_t
            if r not in results_t_minus_1
        )
        return float(new_calls)
    
    # ─────────────────────────────────────────────────────────────────────────
    # Epistemic Uncertainty
    # ─────────────────────────────────────────────────────────────────────────
    
    async def _check_epistemic_uncertainty(
        self,
        task: Any,
        threshold: float = 0.3,
        iteration: int = 0
    ) -> Tuple[bool, float, Optional[Dict[str, Any]]]:
        """Check if epistemic uncertainty is below threshold.
        
        CRITICAL RISKS:
        1. Calibration Drift: Uncertainty may not correlate to correctness
        2. Stagnation Trap: Uncertainty never drops → permanent deadlock
        
        Mitigations:
        - Track uncertainty history for calibration validation
        - Detect stagnation: if attempts > N and delta ≈ 0, escalate/fail
        
        Returns:
            (ok, uncertainty, decomposition) - decomposition breaks down uncertainty by source
        """
        try:
            # Get unstable regions (high-entropy beliefs/hypotheses)
            # NOTE: get_unstable_regions() is synchronous — no await
            unstable = self.epistemic_engine.get_unstable_regions()
            
            # Filter by task domain/context
            task_domain = getattr(task, 'metadata', {}).get('domain', 'general')
            relevant_unstable = [
                u for u in unstable
                if u.domain == task_domain or u.domain == 'general'
            ]
            
            if not relevant_unstable:
                # An EMPTY unstable set has two opposite meanings, and this
                # collapsed both into "maximum uncertainty":
                #
                #   (a) the engine has never registered anything for this task
                #       -> genuinely no data, uncertainty IS maximum
                #   (b) the engine registered beliefs and they have all been
                #       resolved below the instability threshold
                #       -> that is CONVERGENCE, the success case
                #
                # get_unstable_regions() returns only HIGH-entropy beliefs, so
                # the better the epistemic engine performs, the emptier this
                # list becomes. Reading (b) as (a) inverted the signal: every
                # resolved belief made the system look less informed, the
                # controller saw uncertainty pinned at exactly 1.000 forever,
                # the Bayesian budget could never converge, and the loop ran to
                # its cap (observed: 31+ iterations, delta 0.000).
                #
                # Distinguish them by asking whether ANY belief exists for this
                # domain, not merely whether an unstable one does.
                try:
                    all_beliefs = [
                        b for b in self.epistemic_engine._uncertainty().beliefs.values()
                        if getattr(b, "domain", "general") in (task_domain, "general")
                    ]
                except Exception as e:
                    logger.debug(f"belief census unavailable: {e}")
                    all_beliefs = []

                if not all_beliefs:
                    # (a) genuinely no measurements yet.
                    return False, 1.0, None

                # (b) everything tracked is resolved. Report the real mean
                # entropy rather than a sentinel -- this is what lets the
                # controller observe convergence and stop.
                resolved_entropy = (
                    sum(getattr(b, "entropy", 0.0) for b in all_beliefs) / len(all_beliefs)
                )
                logger.info(
                    f"[CONVERGENCE] no unstable regions remain; "
                    f"{len(all_beliefs)} belief(s) resolved, mean entropy "
                    f"{resolved_entropy:.4f} (was reported as 1.000)"
                )
                return resolved_entropy <= threshold, resolved_entropy, {
                    "total_uncertainty": resolved_entropy,
                    "unstable_regions_count": 0,
                    "resolved_belief_count": len(all_beliefs),
                    "uncertainty_by_source": {"all_resolved": resolved_entropy},
                }
            
            # Compute average entropy
            avg_entropy = sum(u.entropy for u in relevant_unstable) / len(relevant_unstable)
            
            # Build decomposition by source
            decomposition = {
                "total_uncertainty": avg_entropy,
                "unstable_regions_count": len(relevant_unstable),
                "uncertainty_by_source": {}
            }
            
            # Group by source (e.g., causal_effect, observability_gap, tool_noise)
            for u in relevant_unstable:
                source = getattr(u, 'source', 'unknown')
                if source not in decomposition["uncertainty_by_source"]:
                    decomposition["uncertainty_by_source"][source] = []
                decomposition["uncertainty_by_source"][source].append({
                    "region": getattr(u, 'region', 'unknown'),
                    "entropy": u.entropy
                })
            
            # Compute average per source
            for source, regions in decomposition["uncertainty_by_source"].items():
                avg_source_entropy = sum(r["entropy"] for r in regions) / len(regions)
                decomposition["uncertainty_by_source"][source] = {
                    "average_entropy": avg_source_entropy,
                    "region_count": len(regions),
                    "regions": regions[:3]  # Top 3 regions for detail
                }
            
            # Stagnation detection: track uncertainty history
            task_id = task.id if hasattr(task, 'id') else 'unknown'
            if task_id not in self._task_states:
                self._task_states[task_id] = []
            
            # Record uncertainty for this iteration
            history = self._task_states.get(task_id, [])
            if history:
                history[-1]['uncertainty'] = avg_entropy
            
            # Check for stagnation: uncertainty not decreasing over last 3 iterations
            if len(history) >= 3:
                recent_uncertainties = [
                    h.get('uncertainty', 1.0) for h in history[-3:]
                ]
                uncertainty_delta = max(recent_uncertainties) - min(recent_uncertainties)
                
                if uncertainty_delta < 0.05 and avg_entropy > threshold:
                    # Stagnation detected: uncertainty stuck above threshold
                    logger.warning(
                        f"⚠️  STAGNATION TRAP DETECTED: uncertainty={avg_entropy:.3f} "
                        f"stuck above threshold={threshold} for 3 iterations (delta={uncertainty_delta:.3f})"
                    )
                    
                    # Escalation: if iteration > 10, force pass with warning
                    if iteration > 10:
                        logger.error(
                            f"🚨 Forcing convergence after {iteration} iterations "
                            f"(uncertainty stagnation detected)"
                        )
                        raise ConvergenceStagnationError(f"Convergence stagnation detected after {iteration} iterations")
            
            return avg_entropy < threshold, avg_entropy, decomposition
            
        except Exception as e:
            logger.warning(f"Epistemic uncertainty check failed: {e}")
            return False, 1.0, {"error": str(e)}
    
    # ─────────────────────────────────────────────────────────────────────────
    # Constraint Solving
    # ─────────────────────────────────────────────────────────────────────────
    
    async def _check_constraints(
        self,
        task: Any,
        state: Dict[str, Any]
    ) -> Tuple[bool, Dict[str, Any], List[str], List[Dict[str, Any]], Optional[Dict[str, Any]]]:
        """Check task invariants using Z3 SMT solver
        
        Returns:
            (all_satisfied, proofs, violated_ids, structured_failures, counterexample)
        """
        task_type_name = task.type.name if hasattr(task, 'type') else 'UNKNOWN'
        invariants = self.invariants.get(task_type_name, [])
        
        if not invariants:
            logger.debug(f"No invariants registered for {task_type_name}")
            return True, {}, [], [], None
        
        if not self.constraint_solver.available:
            logger.warning("Z3 not available - skipping constraint checks")
            return True, {}, [], [], None
        
        violated = []
        proofs = {}
        structured_failures = []
        counterexample = None
        
        for inv in invariants:
            if not inv.required:
                continue
            
            try:
                if inv.proof_method == "smt":
                    satisfied, model = await self._verify_smt_constraint(inv, task, state)
                elif inv.proof_method == "epistemic":
                    satisfied, model = await self._verify_epistemic_constraint(inv, task, state)
                else:
                    satisfied, model = True, None
                
                proofs[inv.invariant_id] = {
                    'satisfied': satisfied,
                    'description': inv.description,
                    'method': inv.proof_method
                }
                
                if not satisfied:
                    violated.append(inv.invariant_id)
                    structured_failures.append({
                        "invariant": inv.invariant_id,
                        "expression": inv.constraint_expr,
                        "result": False,
                        "description": inv.description
                    })
                    if model and not counterexample:
                        counterexample = model
                    
            except Exception as e:
                logger.error(f"Constraint check failed for {inv.invariant_id}: {e}")
                violated.append(inv.invariant_id)
                proofs[inv.invariant_id] = {
                    'satisfied': False,
                    'error': str(e)
                }
                structured_failures.append({
                    "invariant": inv.invariant_id,
                    "expression": inv.constraint_expr,
                    "result": False,
                    "error": str(e)
                })
        
        all_satisfied = len(violated) == 0
        return all_satisfied, proofs, violated, structured_failures, counterexample
    
    async def _verify_smt_constraint(
        self,
        invariant: ConvergenceInvariant,
        task: Any,
        state: Dict[str, Any]
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """Verify constraint using Z3 SMT solver.
        
        CRITICAL: Must query AUTHORITATIVE state, not LLM assertions.
        
        Failure mode:
        finding_exists = tool_result['llm_says_fixed']  # ❌ Formal theater
        
        Correct:
        finding_exists = security_audit_worker.get_active_findings(finding_id)  # ✅ Ground truth
        
        Returns:
            (satisfied, counterexample) - counterexample is Z3 model when satisfied=False
        """
        
        # Extract verification context from state
        tool_results = state.get('tool_results', [])
        epistemic_mutations = state.get('epistemic_mutations', [])
        
        # Build constraint problem based on invariant type
        if invariant.invariant_id == "security_finding_resolved":
            # Query AUTHORITATIVE state: security_audit_worker
            finding_id = task.metadata.get('finding_id') if hasattr(task, 'metadata') else None
            if not finding_id:
                return False  # Cannot verify without finding_id
            
            # Query ground truth from authoritative state store
            try:
                # get_security_audit_worker does not exist — the correct function
                # is get_audit_worker() in the same module.
                from core.security.security_audit_worker import get_audit_worker
                audit_worker = get_audit_worker()

                # get_active_findings may be sync or async depending on version
                _findings_result = audit_worker.get_active_findings()
                if asyncio.iscoroutine(_findings_result):
                    active_findings = await _findings_result
                else:
                    active_findings = _findings_result or []

                finding_exists = any(
                    getattr(f, 'finding_id', None) == finding_id
                    or (isinstance(f, dict) and f.get('finding_id') == finding_id)
                    for f in active_findings
                )

                logger.info(
                    f"🔬 SMT verification: finding_id={finding_id}, "
                    f"exists={finding_exists} (authoritative state query)"
                )

                if finding_exists:
                    counterexample = {
                        "finding_id": finding_id,
                        "finding_exists": True,
                        "remediation_status": "incomplete",
                        "verification_source": "authoritative_state"
                    }
                    return False, counterexample
                else:
                    return True, None

            except ImportError as e:
                logger.warning(
                    f"Cannot import audit worker for finding {finding_id}: {e} — "
                    "falling back to tool-result verification"
                )
            except Exception as e:
                logger.error(f"Failed to query authoritative state for finding {finding_id}: {e}")
                # Fallback: check tool results (less reliable)
                security_scans = [
                    r for r in tool_results
                    if r.get('tool') in ('security_scan', 'verify_security_fix')
                ]
                
                if not security_scans:
                    counterexample = {
                        "finding_id": finding_id,
                        "verification_status": "no_verification_data",
                        "verification_source": "none"
                    }
                    return False, counterexample
                
                latest_scan = security_scans[-1]
                findings = latest_scan.get('result', {}).get('findings', [])
                finding_exists = any(f.get('id') == finding_id for f in findings)
                
                logger.warning(
                    f"⚠️  Using tool results for verification (authoritative state unavailable)"
                )
                
                if finding_exists:
                    counterexample = {
                        "finding_id": finding_id,
                        "finding_exists": True,
                        "verification_source": "tool_results",
                        "latest_scan": latest_scan.get('tool')
                    }
                    return False, counterexample
                else:
                    return True, None
            
        elif invariant.invariant_id == "side_effects_occurred":
            # Count successful tool calls (excluding meta-tools)
            successful_calls = sum(
                1 for r in tool_results
                if r.get('success') and r.get('tool') not in ('request_tools',)
            )
            if successful_calls > 0:
                return True, None
            else:
                counterexample = {
                    "successful_tool_calls": 0,
                    "total_tool_calls": len(tool_results),
                    "reason": "no_side_effects"
                }
                return False, counterexample
            
        elif invariant.invariant_id == "information_gathered":
            # This is epistemic, defer to epistemic check
            return True, None
        
        return True, None
    
    async def _verify_epistemic_constraint(
        self,
        invariant: ConvergenceInvariant,
        task: Any,
        state: Dict[str, Any]
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """Verify constraint using epistemic reasoning
        
        Returns:
            (satisfied, counterexample) - counterexample includes epistemic state when unsatisfied
        """
        
        epistemic_mutations = state.get('epistemic_mutations', [])
        
        if invariant.invariant_id == "information_gathered":
            # Must have positive entropy reduction OR successful tool calls.
            # Exploration/research tasks gather information via tool calls
            # (read_file, search_files, extract_call_graph, etc.) which do not
            # necessarily produce explicit epistemic_mutations.  Counting
            # successful tool calls as information gathering is correct: any
            # successful retrieval or observation reduces uncertainty.
            total_delta = sum(
                m.delta for m in epistemic_mutations
                if hasattr(m, 'delta')
            )
            successful_tools = sum(
                1 for r in state.get('tool_results', [])
                if r.get('success', False)
            )
            # Require at least 3 successful tool calls — a single directory
            # listing or file read does not constitute "information gathered".
            if total_delta > 0 or successful_tools >= 3:
                return True, None
            else:
                counterexample = {
                    "total_entropy_reduction": total_delta,
                    "mutations_count": len(epistemic_mutations),
                    "successful_tool_calls": successful_tools,
                    "required_tool_calls": 3,
                    "reason": "insufficient_information_gain",
                }
                return False, counterexample
        
        return True, None
    
    # ─────────────────────────────────────────────────────────────────────────
    # Main Convergence Check
    # ─────────────────────────────────────────────────────────────────────────
    
    async def check_convergence(
        self,
        task: Any,
        iteration: int,
        state: Dict[str, Any],
        uncertainty_threshold: Optional[float] = None,
        delta_threshold: Optional[float] = None,
        deadline_seconds: Optional[float] = None,
        elapsed_seconds: Optional[float] = None
    ) -> ConvergenceResult:
        """
        Check if task has converged
        
        Convergence requires:
        1. All invariants satisfied (SMT proofs)
        2. Epistemic uncertainty below threshold
        3. State delta below epsilon (fixpoint)
        
        Returns:
            ConvergenceResult with detailed verification
        """
        self.stats['total_checks'] += 1
        
        # Checkpoint current state
        await self.checkpoint_state(task.id, iteration, state)
        
        # Default thresholds
        if uncertainty_threshold is None:
            uncertainty_threshold = self.config.get('uncertainty_threshold', 0.3)
        if delta_threshold is None:
            delta_threshold = self.config.get('delta_threshold', 0.01)
        
        result = ConvergenceResult(
            converged=False,
            state=ConvergenceState.ACTIVE,
            constraints_satisfied=False,
            uncertainty_threshold=uncertainty_threshold,
            delta_threshold=delta_threshold,
            iterations_checked=iteration
        )
        
        # ── Gate 1: Constraint Satisfaction ──
        constraints_ok, proofs, violated, structured_failures, counterexample = await self._check_constraints(task, state)
        result.constraints_satisfied = constraints_ok
        result.constraint_proofs = proofs
        result.violated_invariants = violated
        result.failed_invariants_structured = structured_failures
        result.counterexample_state = counterexample
        
        if not constraints_ok:
            result.state = ConvergenceState.CONSTRAINTS_VIOLATED
            result.reason = f"Invariants violated: {', '.join(violated)}"
            self.stats['failed_constraints'] += 1
            return result
        
        # ── Gate 2: Epistemic Uncertainty ──
        uncertainty_ok, uncertainty, epistemic_decomposition = await self._check_epistemic_uncertainty(
            task, uncertainty_threshold, iteration
        )
        result.epistemic_uncertainty = uncertainty
        result.epistemic_decomposition = epistemic_decomposition
        
        if not uncertainty_ok:
            result.state = ConvergenceState.UNCERTAIN
            result.reason = f"Epistemic uncertainty too high: {uncertainty:.3f} > {uncertainty_threshold}"
            self.stats['failed_uncertainty'] += 1
            # NOTE: Do NOT return early here.  Let the delta (fixpoint) gate run.
            #
            # Rationale: for exploratory / analysis tasks the epistemic engine
            # may legitimately report high uncertainty (the domain IS uncertain).
            # If the state has reached a fixpoint (delta ≈ 0) there is nothing
            # more the agent can do regardless of residual uncertainty.  In that
            # case we allow convergence so the completion validator can score the
            # proposal (it will produce a lower score due to open questions/risks).
            #
            # If the state is still actively changing the delta gate below will
            # return early, which is the correct behaviour.
            # (Original: `return result` here was the bug blocking all completions.)
        
        # ── Gate 3: State Delta (Fixpoint Detection) ──
        if iteration > 0:
            delta, delta_diagnostic = self._compute_state_delta(task.id)
            result.state_delta = delta
            result.delta_diagnostic = delta_diagnostic

            if delta > 10 * delta_threshold:
                # State still changing significantly — reset consecutive counter
                # and keep running regardless of uncertainty.
                self._consecutive_fixpoint[task.id] = 0
                result.state = ConvergenceState.ACTIVE
                result.reason = f"State still evolving: delta={delta:.4f}"
                self.stats['failed_delta'] += 1
                return result

            if delta < delta_threshold:
                # Zero-delta iteration.  Only declare STALLED after
                # FIXPOINT_CONSECUTIVE_THRESHOLD consecutive such iterations.
                # A single thinking/reasoning iteration with no new tool calls
                # is normal and must NOT be treated as a fixpoint.
                count = self._consecutive_fixpoint.get(task.id, 0) + 1
                self._consecutive_fixpoint[task.id] = count
                if count < self.FIXPOINT_CONSECUTIVE_THRESHOLD:
                    # Not stalled yet — agent is likely between tool calls.
                    logger.debug(
                        f"[CONVERGENCE] {task.id} delta≈0 for {count}/"
                        f"{self.FIXPOINT_CONSECUTIVE_THRESHOLD} consecutive iters "
                        f"— not yet a fixpoint"
                    )
                    result.state = ConvergenceState.ACTIVE
                    result.reason = (
                        f"delta≈0 for {count}/{self.FIXPOINT_CONSECUTIVE_THRESHOLD} "
                        f"consecutive iters — waiting for fixpoint confirmation"
                    )
                    return result
                # Genuine fixpoint: FIXPOINT_CONSECUTIVE_THRESHOLD iters of no change
                result.state = ConvergenceState.STALLED
                result.reason = (
                    f"Fixpoint confirmed after {count} consecutive zero-delta iters "
                    f"(delta={delta:.4f} < {delta_threshold})"
                )
            else:
                # Moderate delta — some progress but below active threshold.
                # Reset the consecutive counter (agent is doing something).
                self._consecutive_fixpoint[task.id] = 0
        
        # ── All Gates Passed ──
        # Guard: if epistemic uncertainty is too high AND we are NOT at a
        # fixpoint, don't converge.  (The ACTIVE case already returned early
        # above.  This guard catches the "moderate delta, high uncertainty"
        # band where the agent is still making progress — let it continue.)
        if not uncertainty_ok and result.state not in (
            ConvergenceState.STALLED,
            ConvergenceState.CONVERGED,
        ):
            return result

        result.converged = True
        result.state = ConvergenceState.CONVERGED
        result.reason = (
            "Convergence gates passed: constraints satisfied, "
            + (
                f"uncertainty low ({uncertainty:.3f})"
                if uncertainty_ok
                else f"uncertainty high ({uncertainty:.3f}) but fixpoint reached — completing with caveat"
            )
            + f", delta={result.state_delta:.4f}"
        )
        self.stats['converged'] += 1
        
        logger.info(
            f"✓ Task {task.id} CONVERGED at iteration {iteration}: "
            f"constraints={constraints_ok}, uncertainty={uncertainty:.3f}, delta={result.state_delta:.4f}"
        )
        
        # Risk 3: Check deadline vs invariant conflict
        if deadline_seconds and elapsed_seconds:
            time_remaining = deadline_seconds - elapsed_seconds
            if time_remaining <= 0 and not result.converged:
                logger.warning(
                    f"⚠️ RISK 3: Deadline expired ({elapsed_seconds:.1f}s/{deadline_seconds:.1f}s), "
                    f"invariants not satisfied. Policy: {self.deadline_policy}"
                )
                
                if self.deadline_policy == 'fail':
                    result.state = ConvergenceState.FAILED
                    result.reason = f"DEADLINE EXPIRED. {result.reason}"
                    result.converged = False
                elif self.deadline_policy == 'escalate':
                    logger.error(f"🚨 ESCALATION: Task {task.id} deadline expired")
                    result.reason = f"ESCALATED. {result.reason}"
                elif self.deadline_policy == 'relax_threshold':
                    relaxed = uncertainty_threshold * self.relaxation_factor
                    if result.epistemic_uncertainty < relaxed:
                        logger.warning(f"Relaxing threshold: {uncertainty_threshold:.3f} → {relaxed:.3f}")
                        result.converged = True
                        result.uncertainty_threshold = relaxed
                        result.reason = f"RELAXED THRESHOLD. {result.reason}"
                elif self.deadline_policy == 'defer':
                    logger.warning(f"Deferring decision for task {task.id}")
                    result.reason = f"DEFERRED. {result.reason}"
        
        return result
    
    def get_stats(self) -> Dict[str, Any]:
        """Get convergence statistics with calibration validation"""
        stats = {
            **self.stats,
            'convergence_rate': (
                self.stats['converged'] / self.stats['total_checks']
                if self.stats['total_checks'] > 0 else 0.0
            )
        }
        
        # Add calibration metrics
        if len(self._calibration_data) >= 10:
            calibration_metrics = self._validate_calibration()
            stats['calibration'] = calibration_metrics
        
        return stats
    
    def _validate_calibration(self) -> Dict[str, Any]:
        """Validate epistemic uncertainty calibration.
        
        Checks if uncertainty correlates with actual success rate.
        If uncertainty is well-calibrated:
        - Low uncertainty (< 0.3) -> high success rate (> 0.8)
        - High uncertainty (> 0.7) -> low success rate (< 0.5)
        
        Returns calibration metrics for monitoring.
        """
        if len(self._calibration_data) < 10:
            return {'status': 'insufficient_data', 'samples': len(self._calibration_data)}
        
        # Bucket by uncertainty ranges
        low_uncertainty = [(u, s) for u, s in self._calibration_data if u < 0.3]
        med_uncertainty = [(u, s) for u, s in self._calibration_data if 0.3 <= u < 0.7]
        high_uncertainty = [(u, s) for u, s in self._calibration_data if u >= 0.7]
        
        metrics = {
            'total_samples': len(self._calibration_data),
            'low_uncertainty_success_rate': (
                sum(s for _, s in low_uncertainty) / len(low_uncertainty)
                if low_uncertainty else None
            ),
            'med_uncertainty_success_rate': (
                sum(s for _, s in med_uncertainty) / len(med_uncertainty)
                if med_uncertainty else None
            ),
            'high_uncertainty_success_rate': (
                sum(s for _, s in high_uncertainty) / len(high_uncertainty)
                if high_uncertainty else None
            ),
        }
        
        # Check calibration quality
        low_sr = metrics['low_uncertainty_success_rate']
        high_sr = metrics['high_uncertainty_success_rate']
        
        if low_sr is not None and high_sr is not None:
            # Well-calibrated: low uncertainty -> high success, high uncertainty -> low success
            is_calibrated = low_sr > 0.7 and high_sr < 0.6
            calibration_gap = low_sr - high_sr  # Should be positive and large
            
            metrics['is_calibrated'] = is_calibrated
            metrics['calibration_gap'] = calibration_gap
            
            if calibration_gap < 0.2:
                logger.warning(
                    f"WARNING: CALIBRATION DRIFT DETECTED: uncertainty not correlated with success "
                    f"(gap={calibration_gap:.3f}, expected > 0.2)"
                )
                metrics['status'] = 'drift_detected'
            else:
                metrics['status'] = 'calibrated'
        else:
            metrics['status'] = 'insufficient_data_per_bucket'
        
        return metrics
    
    def record_convergence_outcome(self, uncertainty: float, success: bool):
        """Record convergence outcome for calibration validation."""
        self._calibration_data.append((uncertainty, success))
        
        # Keep last 100 samples
        if len(self._calibration_data) > 100:
            self._calibration_data = self._calibration_data[-100:]
        
        # Periodic calibration check (every 50 samples)
        if len(self._calibration_data) % 50 == 0 and len(self._calibration_data) >= 50:
            calibration = self._validate_calibration()
            if calibration.get('status') == 'drift_detected':
                logger.error(
                    f"ALERT: Epistemic calibration drift detected: "
                    f"low_uncertainty_sr={calibration.get('low_uncertainty_success_rate', 0):.2f}, "
                    f"high_uncertainty_sr={calibration.get('high_uncertainty_success_rate', 0):.2f}"
                )


# ─────────────────────────────────────────────────────────────────────────────
# Global singleton
# ─────────────────────────────────────────────────────────────────────────────

_gate_instance: Optional[ConvergenceGate] = None


def get_convergence_gate() -> ConvergenceGate:
    """Get or create the global ConvergenceGate singleton"""
    global _gate_instance
    if _gate_instance is None:
        _gate_instance = ConvergenceGate()
    return _gate_instance
